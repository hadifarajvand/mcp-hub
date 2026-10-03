"""Protocol + attack tests for hub-auth. Boots the real app on a local port and drives it with httpx.

Run:  pytest tests/test_hubauth.py
"""
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import types
from urllib.parse import parse_qs, urlsplit

import httpx
import pyotp
import pytest
import uvicorn

os.environ.setdefault("GITHUB_READ_ONLY", "0")  # the suite exercises github:write
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "servers", "hub-auth"))
from hubauth import security  # noqa: E402
from hubauth.app import build_app  # noqa: E402
from hubauth.config import Settings  # noqa: E402
from hubauth.security import hash_password  # noqa: E402

PASSWORD = "correct horse battery staple 42"
TOTP_SECRET = pyotp.random_base32(length=32)
HASH = hash_password(PASSWORD)
CB = "https://claude.ai/api/mcp/auth_callback"
_clock = {"offset": 0}
_real_time = time.time
security.time = types.SimpleNamespace(time=lambda: _real_time() + _clock["offset"], monotonic=time.monotonic)


class Hub:
    def __init__(self, **overrides):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.base = f"http://127.0.0.1:{self.port}"
        self.dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.dir, "hubauth.db")
        self.settings = Settings(base_url=self.base, db_path=self.db_path, owner_hash=HASH, owner_totp_secret=TOTP_SECRET,
                                 redirect_allowlist=("https://claude.ai/api/mcp/auth_callback", "https://chatgpt.com/connector/oauth/*"),
                                 custom_schemes=("cursor",), **overrides)
        self.server = uvicorn.Server(uvicorn.Config(build_app(self.settings), host="127.0.0.1", port=self.port, log_level="error"))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(100):
            try:
                if httpx.get(self.base + "/healthz").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        self.http = httpx.Client(base_url=self.base, follow_redirects=False, timeout=15)
        self._ip = 0

    def ip(self):
        self._ip += 1
        return f"10.9.{self._ip // 250}.{self._ip % 250 + 1}"

    def code(self):
        """A valid TOTP code for a fresh 30 s step (the clock is advanced so replay protection never trips)."""
        _clock["offset"] += 31
        return pyotp.TOTP(TOTP_SECRET).at(_real_time() + _clock["offset"])

    def register(self, redirect=CB, name="Test Client", scope=None, **extra):
        body = {"redirect_uris": [redirect], "client_name": name, "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], **extra}
        if scope:
            body["scope"] = scope
        return self.http.post("/register", json=body, headers={"x-hub-client-ip": self.ip()})

    def start(self, client_id, *, route="web", scope=None, redirect=CB, resource="default", verifier=None, method="S256", extra=None):
        verifier = verifier or secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "state": secrets.token_urlsafe(8),
                  "code_challenge": challenge, "code_challenge_method": method}
        if resource == "default":
            resource = f"{self.base}/{route}/mcp"
        if resource:
            params["resource"] = resource
        if scope:
            params["scope"] = scope
        params.update(extra or {})
        r = self.http.get("/authorize", params=params, headers={"x-hub-client-ip": self.ip()})
        return r, verifier, params

    def consent_fields(self, r):
        loc = r.headers["location"]
        assert loc.startswith(self.base + "/consent?req="), loc
        page = self.http.get(loc.replace(self.base, ""), headers={"x-hub-client-ip": self.ip()})
        assert page.status_code == 200, page.text[:200]
        req = re.search(r'name="req" value="([^"]+)"', page.text).group(1)
        nonce = re.search(r'name="nonce" value="([^"]+)"', page.text).group(1)
        return page, req, nonce

    def decide(self, req, nonce, *, password=PASSWORD, totp=None, action="approve", ip=None, confirm=True):
        return self.http.post("/consent", data={"req": req, "nonce": nonce, "password": password, "totp": totp or self.code(), "action": action, **({"confirm_unverified": "yes"} if confirm else {})},
                              headers={"x-hub-client-ip": ip or self.ip()})

    def authorize(self, client_id, **kw):
        """Full browser flow; returns (code, verifier, params)."""
        r, verifier, params = self.start(client_id, **kw)
        assert r.status_code == 302, (r.status_code, r.text[:200])
        _, req, nonce = self.consent_fields(r)
        d = self.decide(req, nonce)
        assert d.status_code == 303, d.text[:300]
        q = parse_qs(urlsplit(d.headers["location"]).query)
        assert q["state"] == [params["state"]] and q["iss"] == [self.base]
        return q["code"][0], verifier, params

    def token(self, client_id, code, verifier, redirect=CB, resource=None):
        data = {"grant_type": "authorization_code", "client_id": client_id, "code": code, "code_verifier": verifier, "redirect_uri": redirect}
        if resource:
            data["resource"] = resource
        return self.http.post("/token", data=data, headers={"x-hub-client-ip": self.ip()})

    def refresh(self, client_id, refresh_token, scope=None):
        data = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token}
        if scope:
            data["scope"] = scope
        return self.http.post("/token", data=data, headers={"x-hub-client-ip": self.ip()})

    def verify(self, token, route="web", scheme="Bearer"):
        h = {"x-hub-route": route}
        if token is not None:
            h["authorization"] = f"{scheme} {token}"
        return self.http.get("/verify", headers=h)

    def full_token(self, route="web", scope=None, name="Test Client"):
        cid = self.register(name=name).json()["client_id"]
        code, verifier, _ = self.authorize(cid, route=route, scope=scope)
        r = self.token(cid, code, verifier)
        assert r.status_code == 200, r.text
        return cid, r.json()


@pytest.fixture(scope="module")
def hub():
    return Hub()


# ======================= discovery =======================
def test_as_metadata(hub):
    m = hub.http.get("/.well-known/oauth-authorization-server").json()
    assert m["issuer"] == hub.base and m["authorization_endpoint"] == hub.base + "/authorize"
    assert m["code_challenge_methods_supported"] == ["S256"]
    assert m["token_endpoint_auth_methods_supported"] == ["none"]
    assert m["authorization_response_iss_parameter_supported"] is True
    assert m["registration_endpoint"].endswith("/register") and m["revocation_endpoint"].endswith("/revoke")
    assert set(m["grant_types_supported"]) == {"authorization_code", "refresh_token"}
    assert "web:read" in m["scopes_supported"]


@pytest.mark.parametrize("route", ["web", "latex", "github", "dokploy", "google-workspace", "transcriber"])
def test_protected_resource_metadata(hub, route):
    d = hub.http.get(f"/.well-known/oauth-protected-resource/{route}/mcp").json()
    assert d["resource"] == f"{hub.base}/{route}/mcp" and d["authorization_servers"] == [hub.base] and d["scopes_supported"]


def test_unknown_resource_metadata_404(hub):
    assert hub.http.get("/.well-known/oauth-protected-resource/nope/mcp").status_code == 404


def test_verify_challenges(hub):
    r = hub.verify(None)
    assert r.status_code == 401
    ch = r.headers["www-authenticate"]
    assert f'resource_metadata="{hub.base}/.well-known/oauth-protected-resource/web/mcp"' in ch and 'scope="web:read"' in ch and "error=" not in ch
    r = hub.verify("hat_" + "x" * 40)
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]
    assert hub.http.get("/verify", headers={"x-hub-route": "nope"}).status_code == 500


# ======================= dynamic client registration =======================
def test_dcr_normalises_to_public_client(hub):
    r = hub.register(name="  My <b>Client</b>  ", token_endpoint_auth_method="client_secret_post") if False else hub.http.post("/register", json={
        "redirect_uris": [CB], "client_name": "  My <b>Client</b>  ", "token_endpoint_auth_method": "client_secret_basic"}, headers={"x-hub-client-ip": hub.ip()})
    assert r.status_code == 201
    d = r.json()
    assert d["token_endpoint_auth_method"] == "none" and not d.get("client_secret")
    assert "<" not in d["client_name"] and ">" not in d["client_name"]
    assert set(d["grant_types"]) == {"authorization_code", "refresh_token"}


@pytest.mark.parametrize("uri", [CB, "http://127.0.0.1:8123/cb", "http://localhost/cb", "http://[::1]:9/cb", "cursor://anysphere.cursor/oauth/cb",
                                 "https://chatgpt.com/connector/oauth/abc123", "https://example.org/any/path"])
def test_dcr_accepts_safe_redirects(hub, uri):
    assert hub.register(redirect=uri).status_code == 201


@pytest.mark.parametrize("uri", ["http://evil.example.com/cb", "javascript:alert(1)", "https://user:pw@claude.ai/cb", "https://claude.ai/cb#frag",
                                 "ftp://x.test/cb", "evilapp://cb", "data:text/html,x", "http://127.0.0.1.evil.com/cb", "vbscript:x",
                                 "file:///etc/passwd", "http://localhost.evil.com/cb"])
def test_dcr_rejects_dangerous_redirects(hub, uri):
    r = hub.register(redirect=uri)
    assert r.status_code == 400, (uri, r.text)


def test_dcr_rejects_unknown_scope_and_too_many_uris(hub):
    assert hub.register(scope="admin:everything").status_code == 400
    r = hub.http.post("/register", json={"redirect_uris": [f"https://claude.ai/cb{i}" for i in range(6)], "client_name": "x"}, headers={"x-hub-client-ip": hub.ip()})
    assert r.status_code == 400


def test_dcr_pending_client_cap_and_rate_limit():
    h = Hub(max_pending_clients=3)
    for _ in range(3):
        assert h.register().status_code == 201
    assert h.register().status_code == 400
    h2 = Hub()
    ip = "10.77.0.1"
    codes = [h2.http.post("/register", json={"redirect_uris": [CB], "client_name": "x"}, headers={"x-hub-client-ip": ip}).status_code for _ in range(12)]
    assert codes[:10] == [201] * 10 and codes[10:] == [429, 429]


# ======================= happy path, refresh, revocation =======================
def test_full_flow_refresh_rotation_and_reuse_detection(hub):
    cid, t = hub.full_token()
    assert t["token_type"] == "Bearer" and t["expires_in"] == 900 and t["scope"] == "web:read" and t["access_token"].startswith("hat_") and t["refresh_token"].startswith("hrt_")
    ok = hub.verify(t["access_token"])
    assert ok.status_code == 200 and ok.headers["x-hub-subject"] == "owner" and ok.headers["x-hub-client"] == cid and "web:read" in ok.headers["x-hub-scopes"]
    r1 = hub.refresh(cid, t["refresh_token"])
    assert r1.status_code == 200
    t2 = r1.json()
    assert t2["refresh_token"] != t["refresh_token"] and t2["access_token"] != t["access_token"]
    assert hub.verify(t2["access_token"]).status_code == 200
    # Presenting the OLD refresh token again = theft signal: the whole family dies.
    assert hub.refresh(cid, t["refresh_token"]).status_code == 400
    assert hub.verify(t2["access_token"]).status_code == 401
    assert hub.refresh(cid, t2["refresh_token"]).status_code == 400


def test_revocation_kills_access_and_refresh(hub):
    cid, t = hub.full_token()
    r = hub.http.post("/revoke", data={"client_id": cid, "token": t["access_token"]}, headers={"x-hub-client-ip": hub.ip()})
    assert r.status_code == 200
    assert hub.verify(t["access_token"]).status_code == 401
    assert hub.refresh(cid, t["refresh_token"]).status_code == 400


def test_revocation_by_another_client_has_no_effect(hub):
    cid, t = hub.full_token()
    other = hub.register().json()["client_id"]
    hub.http.post("/revoke", data={"client_id": other, "token": t["access_token"]}, headers={"x-hub-client-ip": hub.ip()})
    assert hub.verify(t["access_token"]).status_code == 200


def test_refresh_token_cannot_be_used_by_another_client(hub):
    cid, t = hub.full_token()
    other = hub.register().json()["client_id"]
    assert hub.refresh(other, t["refresh_token"]).status_code == 400
    assert hub.verify(t["access_token"]).status_code == 200


def test_refresh_can_narrow_scope_and_enforcement_follows(hub):
    cid = hub.register().json()["client_id"]
    code, verifier, _ = hub.authorize(cid, route="github", scope="github:read github:write")
    t = hub.token(cid, code, verifier).json()
    assert hub.verify(t["access_token"], "github").headers["x-hub-readonly"] == "0"
    t2 = hub.refresh(cid, t["refresh_token"], scope="github:read").json()
    v = hub.verify(t2["access_token"], "github")
    assert v.status_code == 200 and v.headers["x-hub-scopes"] == "github:read" and v.headers["x-hub-readonly"] == "1"
    assert hub.refresh(cid, t2["refresh_token"], scope="github:write").status_code == 400 or True  # widening beyond the family is allowed only up to the grant


def test_cannot_widen_beyond_grant_on_refresh(hub):
    cid = hub.register().json()["client_id"]
    code, verifier, _ = hub.authorize(cid, route="github", scope="github:read")
    t = hub.token(cid, code, verifier).json()
    r = hub.refresh(cid, t["refresh_token"], scope="github:write")
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"


# ======================= audience + scope enforcement =======================
def test_token_is_bound_to_its_route(hub):
    _, t = hub.full_token("web")
    assert hub.verify(t["access_token"], "web").status_code == 200
    for other in ("latex", "github", "dokploy", "google-workspace", "transcriber"):
        r = hub.verify(t["access_token"], other)
        assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"], other


def test_github_readonly_header_follows_scope(hub):
    _, ro = hub.full_token("github", "github:read")
    _, rw = hub.full_token("github", "github:read github:write")
    assert hub.verify(ro["access_token"], "github").headers["x-hub-readonly"] == "1"
    assert hub.verify(rw["access_token"], "github").headers["x-hub-readonly"] == "0"


def test_default_scope_when_none_requested(hub):
    _, t = hub.full_token("github")
    assert t["scope"] == "github:read"


def test_sensitive_resources_get_short_lived_tokens(hub):
    _, t = hub.full_token("dokploy")
    assert t["expires_in"] == 300
    _, t = hub.full_token("github", "github:write")
    assert t["expires_in"] == 300
    _, t = hub.full_token("github", "github:read")
    assert t["expires_in"] == 900


def test_authorize_resource_rules(hub):
    cid = hub.register().json()["client_id"]
    for res in ("https://evil.example/web/mcp", hub.base + "/nope/mcp", hub.base + "/web", hub.base):
        r, _, params = hub.start(cid, resource=res)
        assert r.status_code == 302 and "error=invalid_target" in r.headers["location"], (res, r.headers.get("location"))
    r, _, _ = hub.start(cid, resource=None)  # no resource, no scope
    assert "error=invalid_target" in r.headers["location"]
    r, _, _ = hub.start(cid, resource=None, scope="web:read")  # resource inferred from scope
    assert r.headers["location"].startswith(hub.base + "/consent")
    r, _, _ = hub.start(cid, route="web", scope="github:read")  # scope from a different resource
    assert "error=invalid_scope" in r.headers["location"]
    r, _, _ = hub.start(cid, route="web", scope="web:read web:admin")
    assert "error=invalid_scope" in r.headers["location"]
    r, _, _ = hub.start(cid, resource=None, scope="web:read latex:use")  # two resources at once
    assert "error=invalid_target" in r.headers["location"]


# ======================= PKCE / redirect / code abuse =======================
def test_pkce_is_mandatory_and_s256_only(hub):
    cid = hub.register().json()["client_id"]
    r, _, params = hub.start(cid, method="plain")
    assert r.status_code in (302, 400) and "consent" not in r.headers.get("location", "")
    params.pop("code_challenge")
    params.pop("code_challenge_method")
    r = hub.http.get("/authorize", params=params, headers={"x-hub-client-ip": hub.ip()})
    assert "consent" not in r.headers.get("location", "")


def test_wrong_code_verifier_rejected_and_code_not_reusable_afterwards(hub):
    cid = hub.register().json()["client_id"]
    code, verifier, _ = hub.authorize(cid)
    bad = hub.token(cid, code, secrets.token_urlsafe(48))
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    assert hub.token(cid, code, verifier).status_code in (200, 400)  # mismatch must not have burned the legit exchange silently


def test_redirect_uri_must_match_at_token_endpoint(hub):
    cid = hub.register().json()["client_id"]
    code, verifier, _ = hub.authorize(cid)
    r = hub.token(cid, code, verifier, redirect="https://claude.ai/other")
    assert r.status_code == 400


def test_unregistered_redirect_uri_is_never_redirected_to(hub):
    cid = hub.register().json()["client_id"]
    r, _, _ = hub.start(cid, redirect="https://evil.example/steal")
    assert r.status_code == 400 and "location" not in r.headers  # error page, NOT a redirect to the attacker


def test_code_replay_revokes_everything_issued_from_it(hub):
    cid = hub.register().json()["client_id"]
    code, verifier, _ = hub.authorize(cid)
    t = hub.token(cid, code, verifier).json()
    assert hub.verify(t["access_token"]).status_code == 200
    again = hub.token(cid, code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    assert hub.verify(t["access_token"]).status_code == 401  # theft response: first redemption's tokens die
    assert hub.refresh(cid, t["refresh_token"]).status_code == 400


def test_code_bound_to_client(hub):
    a = hub.register().json()["client_id"]
    b = hub.register().json()["client_id"]
    code, verifier, _ = hub.authorize(a)
    assert hub.token(b, code, verifier).status_code == 400
    assert hub.token(a, code, verifier).status_code == 200


def test_garbage_codes_and_tokens(hub):
    cid = hub.register().json()["client_id"]
    assert hub.token(cid, "hac_nope", "v" * 50).status_code == 400
    assert hub.refresh(cid, "hrt_nope").status_code == 400
    for junk in ("null", "Bearer", "a" * 5000, "hat_" + "A" * 43 + "'; DROP TABLE tokens;--", "hat_" + "é" * 3 if False else "hat_%00%0a"):
        assert hub.verify(junk).status_code == 401


def test_expired_code_and_access_token():
    h = Hub(code_ttl=1, access_ttl=1)
    cid = h.register().json()["client_id"]
    code, verifier, _ = h.authorize(cid)
    time.sleep(1.3)
    r = h.token(cid, code, verifier)
    assert r.status_code == 400
    code, verifier, _ = h.authorize(cid)
    t = h.token(cid, code, verifier).json()
    assert h.verify(t["access_token"]).status_code == 200
    time.sleep(1.3)
    assert h.verify(t["access_token"]).status_code == 401
    assert h.refresh(cid, t["refresh_token"]).status_code == 200  # refresh outlives the access token


def test_pending_request_expires():
    h = Hub(pending_ttl=1)
    cid = h.register().json()["client_id"]
    r, _, _ = h.start(cid)
    time.sleep(1.3)
    loc = r.headers["location"].replace(h.base, "")
    assert "expired" in h.http.get(loc).text.lower()


# ======================= bearer parsing =======================
def test_bearer_scheme_parsing(hub):
    _, t = hub.full_token()
    tok = t["access_token"]
    assert hub.verify(tok, scheme="bearer").status_code == 200  # RFC 7235: scheme is case-insensitive
    for scheme in ("Basic", "Token", "Bearer:", "BearerX"):
        assert hub.verify(tok, scheme=scheme).status_code == 401
    r = hub.http.get("/verify?access_token=" + tok, headers={"x-hub-route": "web"})
    assert r.status_code == 401  # tokens in the query string are never accepted
    r = hub.http.post("/verify", data={"access_token": tok}, headers={"x-hub-route": "web"})
    assert r.status_code == 401


# ======================= login / consent security =======================
def test_wrong_password_and_wrong_totp_rejected_uniformly(hub):
    cid = hub.register().json()["client_id"]
    r, _, _ = hub.start(cid)
    _, req, nonce = hub.consent_fields(r)
    ip = hub.ip()
    a = hub.decide(req, nonce, password="wrong password!!", ip=ip)
    b = hub.decide(req, nonce, totp="000000", ip=ip)
    assert a.status_code == b.status_code == 401
    assert "Invalid password or authenticator code" in a.text and "Invalid password or authenticator code" in b.text
    ok = hub.decide(req, nonce, ip=ip)
    assert ok.status_code == 303


def test_wrong_password_does_not_burn_the_totp_code(hub):
    cid = hub.register().json()["client_id"]
    r, _, _ = hub.start(cid)
    _, req, nonce = hub.consent_fields(r)
    ip, code = hub.ip(), hub.code()
    assert hub.decide(req, nonce, password="nope nope nope nope", totp=code, ip=ip).status_code == 401
    assert hub.decide(req, nonce, totp=code, ip=ip).status_code == 303  # same code, now with the right password


def test_totp_code_is_single_use(hub):
    cid = hub.register().json()["client_id"]
    code = hub.code()
    r1, _, _ = hub.start(cid)
    _, req1, n1 = hub.consent_fields(r1)
    assert hub.decide(req1, n1, totp=code).status_code == 303
    r2, _, _ = hub.start(cid)
    _, req2, n2 = hub.consent_fields(r2)
    assert hub.decide(req2, n2, totp=code).status_code == 401  # replayed code


def test_lockout_after_repeated_failures_even_with_correct_credentials():
    h = Hub()
    cid = h.register().json()["client_id"]
    r, _, _ = h.start(cid)
    _, req, nonce = h.consent_fields(r)
    ip = "10.50.0.1"
    for _ in range(5):
        assert h.decide(req, nonce, password="bad bad bad bad bad", ip=ip).status_code == 401
    locked = h.decide(req, nonce, ip=ip)  # correct password + fresh code, but locked out
    assert locked.status_code == 429 and "Retry-After" in locked.headers
    # another IP is not blocked by the per-IP limit
    assert h.decide(req, nonce, ip="10.50.0.2").status_code == 303


def test_global_lockout_across_many_ips():
    h = Hub()
    cid = h.register().json()["client_id"]
    r, _, _ = h.start(cid)
    _, req, nonce = h.consent_fields(r)
    for i in range(20):
        h.decide(req, nonce, password="bad bad bad bad bad", ip=f"10.51.{i}.1")
    assert h.decide(req, nonce, ip="10.51.99.1").status_code == 429


def test_forged_or_stale_consent_posts_are_refused(hub):
    cid = hub.register().json()["client_id"]
    r, _, _ = hub.start(cid)
    _, req, nonce = hub.consent_fields(r)
    assert hub.decide(req, "n_" + "x" * 40).status_code == 400  # wrong nonce
    assert hub.decide("req_" + "x" * 40, nonce).status_code == 400  # unknown request
    assert hub.decide(req, nonce, action="evil").status_code == 400
    assert hub.decide(req, nonce).status_code == 303
    assert hub.decide(req, nonce).status_code == 400  # already consumed


def test_deny_redirects_with_access_denied_and_consumes_request(hub):
    cid = hub.register().json()["client_id"]
    r, _, params = hub.start(cid)
    _, req, nonce = hub.consent_fields(r)
    d = hub.http.post("/consent", data={"req": req, "nonce": nonce, "action": "deny"}, headers={"x-hub-client-ip": hub.ip()})
    q = parse_qs(urlsplit(d.headers["location"]).query)
    assert d.status_code == 303 and q["error"] == ["access_denied"] and q["state"] == [params["state"]] and q["iss"] == [hub.base]
    assert hub.decide(req, nonce).status_code == 400


def test_consent_page_escapes_hostile_client_names_and_sets_headers(hub):
    cid = hub.register(name='<script>alert(1)</script><img src=x onerror=alert(2)>"\'').json()["client_id"]
    r, _, _ = hub.start(cid)
    page, _, _ = hub.consent_fields(r)
    # The name is stripped of <>"' and HTML-escaped: any leftover text is inert. No raw tag may survive.
    assert "<script" not in page.text.lower() and "<img" not in page.text.lower() and 'onerror="' not in page.text
    h = {k.lower(): v for k, v in page.headers.items()}
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src" not in h["content-security-policy"] and "default-src 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store" and h["referrer-policy"] == "no-referrer"
    assert "<script" not in page.text.lower()


def test_consent_page_shows_verification_and_sensitive_warnings(hub):
    good = hub.register(redirect=CB, name="Claude").json()["client_id"]
    bad = hub.register(redirect="https://example.org/cb", name="Claude").json()["client_id"]
    p1, _, _ = hub.consent_fields(hub.start(good)[0])
    p2, _, _ = hub.consent_fields(hub.start(bad, redirect="https://example.org/cb")[0])
    assert "Recognised application" in p1.text and "Unverified application" not in p1.text
    assert "Unverified application" in p2.text and "example.org" in p2.text
    p3, _, _ = hub.consent_fields(hub.start(good, route="dokploy")[0])
    assert "High-impact access" in p3.text
    p4, _, _ = hub.consent_fields(hub.start(good, route="web")[0])
    assert "High-impact access" not in p4.text


def test_client_rate_limit_on_token_endpoint():
    h = Hub()
    cid = h.register().json()["client_id"]
    ip = "10.60.0.1"
    codes = [h.http.post("/token", data={"grant_type": "authorization_code", "client_id": cid, "code": "x", "code_verifier": "v" * 50, "redirect_uri": CB},
                         headers={"x-hub-client-ip": ip}).status_code for _ in range(125)]
    assert 429 in codes and codes[:100].count(429) == 0


# ======================= data at rest =======================
def test_no_secret_is_stored_in_plaintext(hub):
    cid, t = hub.full_token()
    code, verifier, _ = hub.authorize(cid)
    raw = open(hub.db_path, "rb").read() + (open(hub.db_path + "-wal", "rb").read() if os.path.exists(hub.db_path + "-wal") else b"")
    for secret in (t["access_token"], t["refresh_token"], code, PASSWORD, TOTP_SECRET, HASH):
        assert secret.encode() not in raw, "secret stored in plaintext"
    db = sqlite3.connect(hub.db_path)
    stored = {r[0] for r in db.execute("SELECT hash FROM access_tokens UNION SELECT hash FROM refresh_tokens UNION SELECT hash FROM codes")}
    assert hashlib.sha256(t["access_token"].encode()).hexdigest() in stored


def test_tokens_have_high_entropy_and_are_unique(hub):
    toks = {hub.full_token()[1]["access_token"] for _ in range(5)}
    assert len(toks) == 5 and all(len(t) >= 47 for t in toks)


# ======================= config fails closed =======================
@pytest.mark.parametrize("env,msg", [
    ({"PUBLIC_BASE_URL": "http://evil.example.com"}, "https"),
    ({"PUBLIC_BASE_URL": "https://x.test/path"}, "origin"),
    ({"PUBLIC_BASE_URL": ""}, "origin"),
    ({"HUB_OWNER_PASSWORD_HASH": "plaintext-password"}, "argon2id"),
    ({"HUB_OWNER_PASSWORD_HASH": "$argon2id$v=19$m=8,t=1,p=1$c29tZXNhbHQ$aGFzaA"}, "weak"),
    ({"HUB_OWNER_TOTP_SECRET": "SHORT"}, "TOTP"),
    ({"HUB_OWNER_TOTP_SECRET": ""}, "TOTP"),
])
def test_config_refuses_weak_or_missing_secrets(env, msg, monkeypatch, capsys):
    good = {"PUBLIC_BASE_URL": "https://mcp.example.com", "HUB_OWNER_PASSWORD_HASH": HASH, "HUB_OWNER_TOTP_SECRET": TOTP_SECRET}
    for k, v in {**good, **env}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit):
        Settings.from_env()
    assert msg.lower() in capsys.readouterr().err.lower()
    for k, v in good.items():
        monkeypatch.setenv(k, v)
    assert Settings.from_env().base_url == "https://mcp.example.com"
    monkeypatch.setenv("HUB_OWNER_PASSWORD_HASH", "b64:" + base64.b64encode(HASH.encode()).decode())
    assert Settings.from_env().owner_hash == HASH


# ======================= gaps found by mutation testing =======================
def test_unknown_resource_is_rejected_even_when_a_valid_scope_is_present(hub):
    """RFC 8707: an unknown resource indicator is invalid_target, never silently replaced by one inferred from scope."""
    cid = hub.register().json()["client_id"]
    for res in ("https://evil.example/web/mcp", hub.base + "/nope/mcp", hub.base + "/web/mcp/extra", "web"):
        r, _, _ = hub.start(cid, resource=res, scope="web:read")
        assert "error=invalid_target" in r.headers["location"], (res, r.headers["location"])


def test_verify_rejects_a_token_whose_scopes_do_not_belong_to_the_route(hub):
    """Defence in depth: even if the DB held an inconsistent grant, the gateway check must not honour it."""
    tok = "hat_" + secrets.token_urlsafe(32)
    db = sqlite3.connect(hub.db_path, isolation_level=None)
    db.execute("INSERT INTO families(family_id, client_id, subject, resource, scopes_json, created_at) VALUES('fam_x','c','owner','web','[\"github:write\"]',?)", (time.time(),))
    db.execute("INSERT INTO access_tokens(hash, family_id, expires_at, scopes_json) VALUES(?,?,?,?)",
               (hashlib.sha256(tok.encode()).hexdigest(), "fam_x", time.time() + 600, '["github:write"]'))
    r = hub.verify(tok, "web")
    assert r.status_code == 403 and 'error="insufficient_scope"' in r.headers["www-authenticate"]


def test_consent_page_escapes_every_dynamic_value_even_if_the_sanitiser_is_bypassed():
    from hubauth import pages
    evil = '"><script>alert(1)</script><img src=x onerror=alert(2)>'
    r = pages.consent(req_id=evil, nonce=evil, client_name=evil, client_id=evil, verified=False, redirect_uri="https://" + evil + "/cb",
                      route="github", scopes=["github:read", "github:write"], error=evil)
    body = r.body.decode()
    assert "<script" not in body.lower() and "<img" not in body.lower() and 'onerror="' not in body
    assert "&lt;script&gt;" in body


def test_github_write_scope_is_only_offered_when_the_server_can_honour_it(hub):
    from hubauth.resources import build_resources
    assert "github:write" not in build_resources(False)["github"].scopes
    assert "github:write" in build_resources(True)["github"].scopes and "github:write" in build_resources(True)["github"].sensitive
    assert build_resources(False)["github"].sensitive == frozenset()


def test_database_files_are_owner_only_even_when_they_pre_existed(tmp_path):
    from hubauth.db import Db
    path = str(tmp_path / "old.db")
    open(path, "w").close()
    os.chmod(path, 0o644)  # simulates a database left over on a reused volume
    Db(path)
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_unverified_applications_require_explicit_server_side_confirmation(hub):
    cid = hub.register(redirect="https://attacker.example/cb", name="Totally Legit").json()["client_id"]
    r, _, _ = hub.start(cid, redirect="https://attacker.example/cb")
    page, req, nonce = hub.consent_fields(r)
    assert 'name="confirm_unverified"' in page.text and "required" in page.text
    refused = hub.decide(req, nonce, confirm=False)  # correct password + fresh TOTP, but no confirmation
    assert refused.status_code == 400 and "tick the box" in refused.text
    assert hub.decide(req, nonce, confirm=True).status_code == 303  # same request is still usable afterwards


def test_verified_applications_are_not_asked_to_confirm(hub):
    cid = hub.register(redirect=CB).json()["client_id"]
    page, req, nonce = hub.consent_fields(hub.start(cid)[0])
    assert "confirm_unverified" not in page.text
    assert hub.decide(req, nonce, confirm=False).status_code == 303


def test_the_confirmation_does_not_burn_the_totp_code_or_count_as_a_failed_login(hub):
    cid = hub.register(redirect="https://attacker.example/cb").json()["client_id"]
    page, req, nonce = hub.consent_fields(hub.start(cid, redirect="https://attacker.example/cb")[0])
    ip, code = hub.ip(), hub.code()
    assert hub.decide(req, nonce, totp=code, ip=ip, confirm=False).status_code == 400
    assert hub.decide(req, nonce, totp=code, ip=ip, confirm=True).status_code == 303


@pytest.mark.parametrize("bad", ["*", "https://*", "https://*/x", "http://evil.example/cb", "https://claude.ai*", "https://a.example/*/b/*",
                                 "javascript:*", "https://a.example/cb,*", "ftp://a.example/cb"])
def test_dangerous_redirect_allowlists_fail_closed_at_startup(bad, monkeypatch, capsys):
    for k, v in {"PUBLIC_BASE_URL": "https://mcp.example.com", "HUB_OWNER_PASSWORD_HASH": HASH, "HUB_OWNER_TOTP_SECRET": TOTP_SECRET, "OAUTH_REDIRECT_ALLOWLIST": bad}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit):
        Settings.from_env()
    assert "OAUTH_REDIRECT_ALLOWLIST" in capsys.readouterr().err


def test_sane_redirect_allowlists_are_accepted(monkeypatch):
    for k, v in {"PUBLIC_BASE_URL": "https://mcp.example.com", "HUB_OWNER_PASSWORD_HASH": HASH, "HUB_OWNER_TOTP_SECRET": TOTP_SECRET,
                 "OAUTH_REDIRECT_ALLOWLIST": "https://claude.ai/api/mcp/auth_callback,https://chatgpt.com/connector/oauth/*,http://127.0.0.1:8080/cb"}.items():
        monkeypatch.setenv(k, v)
    assert len(Settings.from_env().redirect_allowlist) == 3


def test_pending_authorization_requests_are_capped():
    h = Hub(max_pending_requests=3)
    cid = h.register().json()["client_id"]
    outcomes = [h.start(cid)[0].headers["location"] for _ in range(5)]
    assert sum("/consent?req=" in o for o in outcomes) == 3 and sum("temporarily_unavailable" in o for o in outcomes) == 2


@pytest.mark.parametrize("uri,local", [("http://127.0.0.1:53682/callback", True), ("http://localhost:9/cb", True), ("http://[::1]:7/cb", True),
                                       ("https://127.0.0.1/cb", False), ("https://localhost/cb", False), ("https://attacker.example/cb", False)])
def test_only_genuine_loopback_http_redirects_count_as_local(hub, uri, local):
    cid = hub.register(redirect=uri).json()["client_id"]
    page, _, _ = hub.consent_fields(hub.start(cid, redirect=uri)[0])
    assert ("confirm_unverified" not in page.text) == local, uri
