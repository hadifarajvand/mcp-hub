"""HTTP surface: OAuth endpoints (SDK handlers), metadata, consent page, and /verify for the gateway."""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager

from mcp.server.auth.provider import AuthorizationParams
from mcp.server.auth.routes import build_metadata, create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from . import pages
from .config import Settings
from .db import Db
from .provider import HubProvider
from .resources import ALL_SCOPES, RESOURCES, resource_url
from .security import (LOGIN_FAILS_GLOBAL, LOGIN_FAILS_PER_IP, LOGIN_WINDOW, RateLimiter, audit, verify_password, verify_totp)

# path -> (max requests, per seconds), keyed by client IP. OAUTH_RATE_LIMIT_SCALE multiplies the limits (dev/test only).
_SCALE = float(os.getenv("OAUTH_RATE_LIMIT_SCALE", "1"))
RATE_RULES = {k: (max(1, int(n * _SCALE)), w) for k, (n, w) in
              {"/register": (10, 3600), "/token": (120, 60), "/authorize": (60, 60), "/revoke": (60, 60), "/consent": (40, 60)}.items()}


def client_ip(request: Request) -> str:
    # Set by the gateway from the real connection; hub-auth is reachable only through it.
    return request.headers.get("x-hub-client-ip") or (request.client.host if request.client else "unknown")


class RateLimitMiddleware:
    def __init__(self, app, limiter: RateLimiter):
        self.app, self.limiter = app, limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in RATE_RULES:
            limit, window = RATE_RULES[scope["path"]]
            ip = dict(scope["headers"]).get(b"x-hub-client-ip", b"").decode() or (scope["client"][0] if scope.get("client") else "unknown")
            key = f"rl:{scope['path']}:{ip}"
            if not self.limiter.allow(key, limit, window):
                audit("rate_limited", path=scope["path"], ip=ip)
                resp = JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": str(self.limiter.retry_after(key, window))})
                return await resp(scope, receive, send)
        await self.app(scope, receive, send)


def build_app(settings: Settings | None = None) -> Starlette:
    s = settings or Settings.from_env()
    db = Db(s.db_path)
    provider = HubProvider(s, db)
    limiter = RateLimiter()
    base = s.base_url
    issuer = AnyHttpUrl(base)

    # ---- metadata ----
    reg = ClientRegistrationOptions(enabled=True, valid_scopes=ALL_SCOPES, default_scopes=None)
    rev = RevocationOptions(enabled=True)
    meta = build_metadata(issuer, None, reg, rev).model_dump(mode="json", exclude_none=True)
    meta["issuer"] = base  # exact string match with the `iss` we return (RFC 8414 / 9207); pydantic adds a trailing "/"
    meta["token_endpoint_auth_methods_supported"] = ["none"]
    meta["revocation_endpoint_auth_methods_supported"] = ["none"]
    meta["authorization_response_iss_parameter_supported"] = True
    meta["scopes_supported"] = ALL_SCOPES
    meta["grant_types_supported"] = ["authorization_code", "refresh_token"]
    meta["code_challenge_methods_supported"] = ["S256"]
    cors = {"Access-Control-Allow-Origin": "*"}

    async def as_metadata(_: Request) -> Response:
        return JSONResponse(meta, headers={**cors, "Cache-Control": "public, max-age=300"})

    def prm_handler(route: str):
        res = RESOURCES[route]
        doc = {"resource": resource_url(base, route), "authorization_servers": [base], "scopes_supported": sorted(res.scopes),
               "bearer_methods_supported": ["header"], "resource_name": res.title}

        async def handler(_: Request) -> Response:
            return JSONResponse(doc, headers={**cors, "Cache-Control": "public, max-age=300"})
        return handler

    # ---- consent ----
    def render(p: dict, error: str | None = None, status: int = 200):
        client = db.one("SELECT info_json FROM clients WHERE client_id=?", (p["client_id"],))
        from mcp.shared.auth import OAuthClientInformationFull
        info = OAuthClientInformationFull.model_validate_json(client["info_json"])
        return pages.consent(req_id=p["req_id"], nonce=p["nonce"], client_name=info.client_name or "Unnamed client", client_id=p["client_id"],
                             verified=provider.client_verified(p["client_id"]), redirect_uri=str(p["params"].redirect_uri), route=p["route"],
                             scopes=p["scopes"], error=error, status=status)

    async def consent_get(request: Request) -> Response:
        p = provider.get_pending(request.query_params.get("req", ""))
        if not p:
            return pages.message("Request expired", "This authorization request is unknown or has expired. Start the connection again from your application.")
        return render(p)

    async def consent_post(request: Request) -> Response:
        ip = client_ip(request)
        form = await request.form()
        req_id, nonce, action = str(form.get("req", "")), str(form.get("nonce", "")), str(form.get("action", ""))
        p = provider.get_pending(req_id)
        if not p or not re.fullmatch(r"[A-Za-z0-9_\-]+", nonce) or not __import__("hmac").compare_digest(nonce, p["nonce"]):
            return pages.message("Request expired", "This authorization request is unknown, expired, or was not started from this page.")
        if action == "deny":
            url = provider.deny(req_id)
            return RedirectResponse(url, status_code=303) if url else pages.message("Request expired", "Nothing to deny.")
        if action != "approve":
            return pages.message("Bad request", "Unknown action.")
        # Lockout is checked BEFORE any credential is evaluated.
        if limiter.count(f"loginfail:{ip}", LOGIN_WINDOW) >= LOGIN_FAILS_PER_IP or limiter.count("loginfail:global", LOGIN_WINDOW) >= LOGIN_FAILS_GLOBAL:
            wait = max(limiter.retry_after(f"loginfail:{ip}", LOGIN_WINDOW), limiter.retry_after("loginfail:global", LOGIN_WINDOW))
            audit("login_locked_out", ip=ip)
            return pages.message("Too many attempts", f"Sign-in is temporarily locked. Try again in about {wait // 60 + 1} minutes.", 429, {"Retry-After": str(wait)})
        ok_pw = await asyncio.to_thread(verify_password, s.owner_hash, str(form.get("password", "")))
        ok_totp = verify_totp(db, s.owner_totp_secret, str(form.get("totp", "")), consume=ok_pw)  # evaluate both: uniform timing
        if not (ok_pw and ok_totp):
            limiter.add(f"loginfail:{ip}", LOGIN_WINDOW)
            limiter.add("loginfail:global", LOGIN_WINDOW)
            audit("login_failed", ip=ip, client_id=p["client_id"])
            return render(p, "Invalid password or authenticator code.", 401)
        url = provider.approve(req_id)
        if not url:
            return pages.message("Request expired", "This request was already used or has expired.")
        audit("login_ok", ip=ip, client_id=p["client_id"])
        return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})

    # ---- gateway token check (called by Caddy forward_auth on every MCP request) ----
    async def verify(request: Request) -> Response:
        route = request.headers.get("x-hub-route", "")
        res = RESOURCES.get(route)
        if res is None:
            audit("verify_misconfigured", route=route)
            return JSONResponse({"error": "misconfigured_route"}, status_code=500)
        prm = f"{base}/.well-known/oauth-protected-resource{res.path}"
        scope_hint = " ".join(res.default_scopes)
        challenge = f'Bearer resource_metadata="{prm}", scope="{scope_hint}"'
        m = re.match(r"^Bearer[ \t]+([A-Za-z0-9._~+/=\-]{1,512})$", request.headers.get("authorization", ""), re.I)
        if not m:
            return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": challenge})
        v = provider.verify_access(m.group(1))
        invalid = f'Bearer error="invalid_token", resource_metadata="{prm}", scope="{scope_hint}"'
        if not v:
            audit("verify_denied", route=route, reason="invalid_or_expired", ip=client_ip(request))
            return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": invalid})
        if v["route"] != route:  # audience binding: a token for one MCP is useless on another
            audit("verify_denied", route=route, reason="audience_mismatch", token_route=v["route"], client_id=v["client_id"], ip=client_ip(request))
            return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": invalid})
        granted = set(v["scopes"]) & set(res.scopes)
        if not granted:
            return JSONResponse({"error": "insufficient_scope"}, status_code=403, headers={
                "WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope_hint}", resource_metadata="{prm}"'})
        return Response(status_code=200, headers={
            "X-Hub-Subject": v["subject"], "X-Hub-Client": v["client_id"], "X-Hub-Scopes": " ".join(sorted(granted)),
            "X-Hub-Readonly": "0" if "github:write" in granted else "1",
        })

    # ---- RFC 7009 revocation. The SDK's handler demands a client_secret, which public PKCE clients do not have,
    # so none of them could ever revoke. Revoking a token kills its whole grant (access + refresh). ----
    async def revoke(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers={**cors, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "content-type"})
        form = await request.form()
        client = await provider.get_client(str(form.get("client_id", "")))
        if client is None:
            return JSONResponse({"error": "invalid_client"}, status_code=401, headers=cors)
        token = str(form.get("token", ""))
        if token and len(token) <= 512:
            from .db import sha256
            h = sha256(token)
            row = db.one("SELECT family_id FROM access_tokens WHERE hash=? UNION SELECT family_id FROM refresh_tokens WHERE hash=?", (h, h))
            # Only the client the token was issued to may revoke it; anything else is silently ignored (RFC 7009 2.2).
            if row and (fam := db.one("SELECT client_id FROM families WHERE family_id=?", (row["family_id"],))) and fam["client_id"] == client.client_id:
                db.revoke_family(row["family_id"], "revoked_by_client")
                audit("token_revoked", client_id=client.client_id)
        return JSONResponse({}, status_code=200, headers={**cors, "Cache-Control": "no-store"})

    async def healthz(_: Request) -> Response:
        return PlainTextResponse("ok")

    sdk_routes = [r for r in create_auth_routes(provider, issuer, None, reg, rev) if r.path not in ("/.well-known/oauth-authorization-server", "/revoke")]
    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", as_metadata, methods=["GET"]),
        *[Route(f"/.well-known/oauth-protected-resource{r.path}", prm_handler(r.route), methods=["GET"]) for r in RESOURCES.values()],
        Route("/consent", consent_get, methods=["GET"]),
        Route("/consent", consent_post, methods=["POST"]),
        Route("/revoke", revoke, methods=["POST", "OPTIONS"]),
        Route("/verify", verify, methods=["GET", "POST", "HEAD", "PUT", "DELETE", "PATCH"]),
        *sdk_routes,
    ]

    @asynccontextmanager
    async def lifespan(_):
        async def housekeeping():
            while True:
                try:
                    db.gc(s.client_gc_hours)
                except Exception as exc:  # noqa: BLE001
                    audit("gc_failed", error=type(exc).__name__)
                await asyncio.sleep(3600)
        task = asyncio.create_task(housekeeping())
        audit("hub_auth_started", base_url=base, resources=sorted(RESOURCES))
        yield
        task.cancel()

    app = Starlette(routes=routes, middleware=[Middleware(RateLimitMiddleware, limiter=limiter)], lifespan=lifespan)
    app.state.provider, app.state.db, app.state.settings = provider, db, s
    return app
