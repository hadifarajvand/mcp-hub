"""OAuth authorization server policy: clients, codes, tokens, revocation. Plugs into the MCP SDK's handlers."""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken, RegistrationError, TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .config import Settings
from .db import Db, new_secret, sha256
from .resources import ALL_SCOPES, RESOURCES, SCOPE_TO_ROUTE, route_for_resource
from .security import audit

SUBJECT = "owner"
MAX_FAMILY_LIFETIME = 180 * 86400  # after this, a fresh login (password + TOTP) is required
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _sanitize_name(name: str | None) -> str:
    name = re.sub(r"[\x00-\x1f\x7f<>\"'`]", "", name or "").strip()
    return name[:80] or "Unnamed client"


class HubProvider:
    def __init__(self, settings: Settings, db: Db):
        self.s = settings
        self.db = db

    # ------------------------------------------------------------------ clients
    def _redirect_ok(self, uri: str) -> bool:
        try:
            p = urlsplit(uri)
        except ValueError:
            return False
        if len(uri) > 2048 or p.fragment or p.username or p.password or any(c in uri for c in " \t\r\n\\"):
            return False
        if p.scheme == "https":
            return bool(p.hostname)
        if p.scheme == "http":
            return p.hostname in LOOPBACK  # RFC 8252 loopback redirect for native apps
        return p.scheme in self.s.custom_schemes and not p.hostname == ""

    def _is_verified(self, uris: list[str]) -> bool:
        def match(u: str) -> bool:
            return any(u == pat or (pat.endswith("*") and u.startswith(pat[:-1])) for pat in self.s.redirect_allowlist)
        return bool(uris) and all(match(u) for u in uris)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.db.one("SELECT info_json FROM clients WHERE client_id=?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(row["info_json"]) if row else None

    def client_verified(self, client_id: str) -> bool:
        row = self.db.one("SELECT verified FROM clients WHERE client_id=?", (client_id,))
        return bool(row and row["verified"])

    async def register_client(self, info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (info.redirect_uris or [])]
        if not uris or len(uris) > 5:
            raise RegistrationError("invalid_redirect_uri", "provide between 1 and 5 redirect URIs")
        for u in uris:
            if not self._redirect_ok(u):
                raise RegistrationError("invalid_redirect_uri", "redirect URIs must be https, a loopback http URL, or an allowed app scheme")
        pending = self.db.one("SELECT COUNT(*) AS n FROM clients WHERE client_id NOT IN (SELECT client_id FROM families)")["n"]
        if pending >= self.s.max_pending_clients:
            audit("register_rejected", reason="too_many_pending")
            raise RegistrationError("invalid_client_metadata", "too many unused registrations; try again later")
        # Normalise: every client is a public PKCE client with the two grants we implement.
        info.token_endpoint_auth_method = "none"
        info.client_secret = None
        info.client_secret_expires_at = None
        info.grant_types = ["authorization_code", "refresh_token"]
        info.response_types = ["code"]
        info.client_name = _sanitize_name(info.client_name)
        requested = (info.scope or "").split()
        info.scope = " ".join(s for s in requested if s in SCOPE_TO_ROUTE) or " ".join(ALL_SCOPES)
        verified = self._is_verified(uris)
        self.db.x("INSERT INTO clients(client_id, info_json, created_at, verified) VALUES(?,?,?,?)",
                  (info.client_id, info.model_dump_json(), time.time(), int(verified)))
        audit("client_registered", client_id=info.client_id, name=info.client_name, redirect_hosts=sorted({urlsplit(u).netloc or urlsplit(u).scheme for u in uris}), verified=verified)

    # ------------------------------------------------------------------ authorize
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        route = route_for_resource(self.s.base_url, params.resource)
        if params.resource and route is None:
            raise AuthorizeError("invalid_target", "unknown resource")
        requested = list(params.scopes or [])
        if route is None:
            routes = {SCOPE_TO_ROUTE.get(s) for s in requested}
            if not requested or None in routes or len(routes) != 1:
                raise AuthorizeError("invalid_target", "the 'resource' parameter is required (one MCP endpoint per authorization)")
            route = routes.pop()
        res = RESOURCES[route]
        scopes = requested or list(res.default_scopes)
        for s in scopes:
            if s not in res.scopes:
                raise AuthorizeError("invalid_scope", f"scope {s!r} is not offered by this resource")
        req_id, nonce = new_secret("req_"), new_secret("n_")
        now = time.time()
        self.db.x("INSERT INTO pending(req_id, nonce, client_id, params_json, resource, scopes_json, created_at, expires_at) VALUES(?,?,?,?,?,?,?,?)",
                  (req_id, nonce, client.client_id, params.model_dump_json(), route, self.db.dumps(scopes), now, now + self.s.pending_ttl))
        audit("authorize_started", client_id=client.client_id, resource=route, scopes=scopes)
        return f"{self.s.base_url}/consent?req={req_id}"

    def get_pending(self, req_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM pending WHERE req_id=? AND expires_at>?", (req_id, time.time()))
        if not row:
            return None
        import json
        return {"req_id": row["req_id"], "nonce": row["nonce"], "client_id": row["client_id"], "route": row["resource"],
                "scopes": json.loads(row["scopes_json"]), "params": AuthorizationParams.model_validate_json(row["params_json"])}

    def deny(self, req_id: str) -> str | None:
        p = self.get_pending(req_id)
        if not p:
            return None
        self.db.x("DELETE FROM pending WHERE req_id=?", (req_id,))
        audit("authorize_denied", client_id=p["client_id"], resource=p["route"])
        prm = p["params"]
        return construct_redirect_uri(str(prm.redirect_uri), error="access_denied", state=prm.state, iss=self.s.base_url)

    def approve(self, req_id: str) -> str | None:
        """Called only after password + TOTP succeeded. Single-use: consumes the pending request."""
        p = self.get_pending(req_id)
        if not p or self.db.x("DELETE FROM pending WHERE req_id=?", (req_id,)) != 1:
            return None
        prm: AuthorizationParams = p["params"]
        family, code = new_secret("fam_"), new_secret("hac_")
        now = time.time()
        self.db.x("INSERT INTO families(family_id, client_id, subject, resource, scopes_json, created_at) VALUES(?,?,?,?,?,?)",
                  (family, p["client_id"], SUBJECT, p["route"], self.db.dumps(p["scopes"]), now))
        self.db.x("INSERT INTO codes(hash, family_id, client_id, redirect_uri, redirect_explicit, challenge, scopes_json, resource, subject, expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (sha256(code), family, p["client_id"], str(prm.redirect_uri), int(prm.redirect_uri_provided_explicitly), prm.code_challenge,
                   self.db.dumps(p["scopes"]), p["route"], SUBJECT, now + self.s.code_ttl))
        audit("authorize_approved", client_id=p["client_id"], resource=p["route"], scopes=p["scopes"])
        return construct_redirect_uri(str(prm.redirect_uri), code=code, state=prm.state, iss=self.s.base_url)

    # ------------------------------------------------------------------ token endpoint
    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        import json
        row = self.db.one("SELECT * FROM codes WHERE hash=?", (sha256(authorization_code),))
        if not row or row["client_id"] != client.client_id:
            return None
        if row["used"]:  # replay of a code that was already redeemed: assume theft, burn everything issued from it
            self.db.revoke_family(row["family_id"], "authorization_code_reuse")
            audit("code_reuse_detected", client_id=client.client_id, resource=row["resource"])
            return None
        return AuthorizationCode(code=authorization_code, scopes=json.loads(row["scopes_json"]), expires_at=row["expires_at"], client_id=row["client_id"],
                                 code_challenge=row["challenge"], redirect_uri=row["redirect_uri"], redirect_uri_provided_explicitly=bool(row["redirect_explicit"]),
                                 resource=self.s.base_url + RESOURCES[row["resource"]].path, subject=row["subject"])

    def _ttl(self, route: str, scopes: list[str]) -> int:
        return self.s.access_ttl_sensitive if any(s in RESOURCES[route].sensitive for s in scopes) else self.s.access_ttl

    def _issue(self, conn, family: str, route: str, access_scopes: list[str], family_created: float) -> OAuthToken:
        now = time.time()
        access, refresh = new_secret("hat_"), new_secret("hrt_")
        ttl = self._ttl(route, access_scopes)
        refresh_exp = min(now + self.s.refresh_ttl, family_created + MAX_FAMILY_LIFETIME)
        conn.execute("INSERT INTO access_tokens(hash, family_id, expires_at, scopes_json) VALUES(?,?,?,?)", (sha256(access), family, now + ttl, self.db.dumps(access_scopes)))
        conn.execute("INSERT INTO refresh_tokens(hash, family_id, expires_at) VALUES(?,?,?)", (sha256(refresh), family, refresh_exp))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ttl, scope=" ".join(access_scopes), refresh_token=refresh)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        h = sha256(authorization_code.code)

        def redeem(conn):
            if conn.execute("UPDATE codes SET used=1 WHERE hash=? AND used=0", (h,)).rowcount != 1:
                return None  # lost a race with another redemption of the same code
            row = conn.execute("SELECT c.family_id, c.resource, c.scopes_json, f.created_at, f.revoked FROM codes c JOIN families f USING(family_id) WHERE c.hash=?", (h,)).fetchone()
            if not row or row["revoked"]:
                return None
            import json
            return self._issue(conn, row["family_id"], row["resource"], json.loads(row["scopes_json"]), row["created_at"])

        tokens = self.db.tx(redeem)
        if tokens is None:
            row = self.db.one("SELECT family_id FROM codes WHERE hash=?", (h,))
            if row:
                self.db.revoke_family(row["family_id"], "authorization_code_reuse")
            audit("code_redeem_failed", client_id=client.client_id)
            raise TokenError("invalid_grant", "authorization code is invalid or already used")
        audit("tokens_issued", client_id=client.client_id, grant="authorization_code")
        return tokens

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        import json
        row = self.db.one("SELECT r.family_id, r.expires_at, r.rotated, f.client_id, f.resource, f.scopes_json, f.revoked FROM refresh_tokens r JOIN families f USING(family_id) WHERE r.hash=?",
                          (sha256(refresh_token),))
        if not row or row["client_id"] != client.client_id or row["revoked"]:
            return None
        if row["rotated"]:  # an already-rotated refresh token was presented: the family is compromised
            self.db.revoke_family(row["family_id"], "refresh_token_reuse")
            audit("refresh_reuse_detected", client_id=client.client_id, resource=row["resource"])
            return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"], scopes=json.loads(row["scopes_json"]), expires_at=int(row["expires_at"]),
                            resource=self.s.base_url + RESOURCES[row["resource"]].path, subject=SUBJECT)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        h = sha256(refresh_token.token)

        def rotate(conn):
            if conn.execute("UPDATE refresh_tokens SET rotated=1 WHERE hash=? AND rotated=0", (h,)).rowcount != 1:
                return None
            row = conn.execute("SELECT r.family_id, f.resource, f.created_at, f.revoked FROM refresh_tokens r JOIN families f USING(family_id) WHERE r.hash=?", (h,)).fetchone()
            if not row or row["revoked"]:
                return None
            return self._issue(conn, row["family_id"], row["resource"], scopes, row["created_at"])

        tokens = self.db.tx(rotate)
        if tokens is None:
            row = self.db.one("SELECT family_id FROM refresh_tokens WHERE hash=?", (h,))
            if row:
                self.db.revoke_family(row["family_id"], "refresh_token_reuse")
            audit("refresh_failed", client_id=client.client_id)
            raise TokenError("invalid_grant", "refresh token is invalid or already used")
        audit("tokens_issued", client_id=client.client_id, grant="refresh_token")
        return tokens

    # ------------------------------------------------------------------ verification / revocation
    def verify_access(self, token: str) -> dict | None:
        import json
        row = self.db.one("SELECT a.expires_at, a.scopes_json, f.family_id, f.client_id, f.subject, f.resource, f.revoked FROM access_tokens a JOIN families f USING(family_id) WHERE a.hash=?",
                          (sha256(token),))
        if not row or row["revoked"] or row["expires_at"] < time.time():
            return None
        return {"client_id": row["client_id"], "subject": row["subject"], "route": row["resource"], "scopes": json.loads(row["scopes_json"]),
                "family_id": row["family_id"], "expires_at": row["expires_at"]}

    async def load_access_token(self, token: str) -> AccessToken | None:
        v = self.verify_access(token)
        if not v:
            return None
        return AccessToken(token=token, client_id=v["client_id"], scopes=v["scopes"], expires_at=int(v["expires_at"]),
                           resource=self.s.base_url + RESOURCES[v["route"]].path, subject=v["subject"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        h = sha256(token.token)
        row = self.db.one("SELECT family_id FROM access_tokens WHERE hash=? UNION SELECT family_id FROM refresh_tokens WHERE hash=?", (h, h))
        if row:
            self.db.revoke_family(row["family_id"], "revoked_by_client")
            audit("token_revoked", client_id=token.client_id)

    async def exchange_identity_assertion(self, client, params):  # not offered (metadata does not advertise it)
        raise TokenError("unsupported_grant_type", "not supported")
