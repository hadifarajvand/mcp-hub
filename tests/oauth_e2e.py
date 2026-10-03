#!/usr/bin/env python3
"""OAuth end-to-end tests THROUGH THE GATEWAY (dev overlay).

  set -a; . ./.env; set +a; python tests/oauth_e2e.py

Part 1: a standards-compliant client (the MCP SDK's OAuthClientProvider) does discovery -> DCR -> PKCE -> consent ->
        token -> MCP calls -> refresh, unaided. Part 2: attacks against the gateway's enforcement.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2  # the MCP SDK's own HTTP client; OAuthClientProvider is an httpx2.Auth
from mcp import Client
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

sys.path.insert(0, os.path.dirname(__file__))
import hubclient  # noqa: E402

BASE = hubclient.BASE
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]
failures = []
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}}}
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {('- ' + str(detail)[:200]) if (detail and not ok) else ''}")
    if not ok:
        failures.append(name)


def sh(service, cmd):
    return subprocess.run(COMPOSE + ["exec", "-T", service, "sh", "-c", cmd], capture_output=True, text=True)


def post(route, token=None, headers=None, body=INIT):
    h = {**MCP_HEADERS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return httpx.post(f"{BASE}/{route}/mcp", json=body, headers=h, timeout=60)


class MemStorage(TokenStorage):
    def __init__(self):
        self.tokens, self.client = None, None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull):
        self.client = client_info


def sdk_provider(route, state):
    """OAuthClientProvider whose 'browser' is a scripted owner login."""
    holder = {}
    storage = MemStorage()

    async def redirect_handler(url: str):
        h = httpx.Client(follow_redirects=False, timeout=30)
        r = h.get(url)
        assert r.status_code == 302, (r.status_code, r.text[:200])
        page = h.get(r.headers["location"])
        req = re.search(r'name="req" value="([^"]+)"', page.text).group(1)
        nonce = re.search(r'name="nonce" value="([^"]+)"', page.text).group(1)
        for attempt in range(3):
            d = h.post(f"{BASE}/consent", data={"req": req, "nonce": nonce, "password": os.environ["HUBTEST_PASSWORD"], "totp": hubclient.next_totp(state), "action": "approve"})
            if d.status_code == 303 or d.status_code != 401 or attempt == 2:
                break
            time.sleep(31)
        assert d.status_code == 303, d.text[:200]
        q = parse_qs(urlsplit(d.headers["location"]).query)
        holder["result"] = AuthorizationCodeResult(code=q["code"][0], state=q.get("state", [None])[0], iss=q.get("iss", [None])[0])

    async def callback_handler():
        return holder["result"]

    meta = OAuthClientMetadata(redirect_uris=[AnyUrl(hubclient.REDIRECT)], client_name="SDK conformance client", token_endpoint_auth_method="none",
                               grant_types=["authorization_code", "refresh_token"], response_types=["code"])
    return OAuthClientProvider(server_url=f"{BASE}/{route}/mcp", client_metadata=meta, storage=storage, redirect_handler=redirect_handler,
                               callback_handler=callback_handler), storage


async def main():
    state = hubclient._load()

    # ===================== 1. standards-compliant client, unaided =====================
    print("--- standard OAuth client (MCP SDK) ---")
    for route, probe in (("web", "web_search"), ("latex", "list_templates")):
        provider, storage = sdk_provider(route, state)
        try:
            async with httpx2.AsyncClient(auth=provider, timeout=120) as http:
                async with Client(streamable_http_client(f"{BASE}/{route}/mcp", http_client=http)) as c:
                    tools = {t.name for t in (await c.list_tools()).tools}
                    check(f"SDK client completes the full OAuth flow and lists tools on /{route}", probe in tools, tools)
                    if route == "latex":
                        r = await c.call_tool("list_templates", {})
                        check("SDK client makes an authenticated tool call", not r.is_error and "article" in json.dumps(r.structured_content))
            tok = storage.tokens
            check(f"/{route}: server issued a short-lived bearer with a refresh token and a bounded scope",
                  tok and tok.access_token.startswith("hat_") and tok.refresh_token and (tok.expires_in or 0) <= 900 and tok.scope in ("web:read", "latex:use"), tok)
            check(f"/{route}: client registered itself as a PUBLIC PKCE client (no secret issued)",
                  storage.client and not storage.client.client_secret and storage.client.token_endpoint_auth_method == "none", storage.client)
        except Exception as e:  # noqa: BLE001
            subs = getattr(e, "exceptions", None) or [e]
            check(f"SDK OAuth flow on /{route}", False, "; ".join(f"{type(x).__name__}: {x}" for x in subs))

    # ===================== 2. discovery documents =====================
    print("\n--- discovery ---")
    meta = httpx.get(f"{BASE}/.well-known/oauth-authorization-server").json()
    check("issuer equals the public origin exactly (no trailing slash)", meta["issuer"] == BASE, meta["issuer"])
    check("only S256 PKCE advertised; public clients only", meta["code_challenge_methods_supported"] == ["S256"] and meta["token_endpoint_auth_methods_supported"] == ["none"])
    for route in ("web", "latex", "transcriber", "github", "google-workspace", "dokploy"):
        prm = httpx.get(f"{BASE}/.well-known/oauth-protected-resource/{route}/mcp").json()
        check(f"protected-resource metadata for /{route}", prm["resource"] == f"{BASE}/{route}/mcp" and prm["authorization_servers"] == [BASE] and prm["scopes_supported"], prm)
        r = post(route)
        ch = r.headers.get("www-authenticate", "")
        check(f"/{route} without a token: 401 + resource_metadata + scope hint", r.status_code == 401 and f"/.well-known/oauth-protected-resource/{route}/mcp" in ch and "scope=" in ch, (r.status_code, ch))

    # ===================== 3. gateway enforcement =====================
    print("\n--- enforcement at the gateway ---")
    routes = ["web", "latex", "transcriber"]
    toks = {r: hubclient.token_for(r) for r in routes}
    for r in routes:
        check(f"/{r}: valid token accepted", post(r, toks[r]).status_code == 200)
        for other in routes + ["dokploy", "google-workspace", "github"]:
            if other == r:
                continue
            resp = post(other, toks[r])
            check(f"token for /{r} is REJECTED on /{other} (audience binding)", resp.status_code == 401 and 'error="invalid_token"' in resp.headers.get("www-authenticate", ""), resp.status_code)
    for label, hdr in [("no scheme", "x"), ("Basic", "Basic " + toks["web"]), ("Token", "Token " + toks["web"]), ("empty bearer", "Bearer "), ("junk bearer", "Bearer hat_" + "A" * 43),
                       ("SQL-ish", "Bearer ' OR 1=1 --"), ("huge", "Bearer " + "A" * 20000)]:
        try:
            r = httpx.post(f"{BASE}/web/mcp", json=INIT, headers={**MCP_HEADERS, "Authorization": hdr}, timeout=30)
            check(f"bad Authorization ({label}) -> 401/4xx, never 200", r.status_code in (400, 401, 431) and r.status_code != 200, r.status_code)
        except httpx.HTTPError as e:
            check(f"bad Authorization ({label}) refused", True, e)
    r = httpx.post(f"{BASE}/web/mcp?access_token={toks['web']}", json=INIT, headers=MCP_HEADERS, timeout=30)
    check("token in the query string is NOT accepted", r.status_code == 401)
    r = httpx.post(f"{BASE}/web/mcp", json={**INIT, "access_token": toks["web"]}, headers=MCP_HEADERS, timeout=30)
    check("token in the body is NOT accepted", r.status_code == 401)
    for path in ("/verify", "/consent/../verify", "/%2e%2e/verify", "//verify"):
        r = httpx.get(BASE + path, headers={"X-Hub-Route": "web", "Authorization": f"Bearer {toks['web']}"}, timeout=15)
        check(f"internal /verify is not exposed ({path})", r.status_code in (404, 400), r.status_code)

    # ===================== 4. revocation + theft response =====================
    print("\n--- revocation and theft response ---")
    e = hubclient.login("web", name="revoke-test", cache=False)
    check("fresh grant works", post("web", e["access_token"]).status_code == 200)
    r = httpx.post(f"{BASE}/revoke", data={"client_id": e["client_id"], "token": e["access_token"]}, timeout=30)
    check("POST /revoke by a PUBLIC client succeeds (RFC 7009)", r.status_code == 200, (r.status_code, r.text))
    check("revoked access token is rejected IMMEDIATELY at the gateway", post("web", e["access_token"]).status_code == 401)
    rr = httpx.post(f"{BASE}/token", data={"grant_type": "refresh_token", "client_id": e["client_id"], "refresh_token": e["refresh_token"]}, timeout=30)
    check("the grant's refresh token died with it", rr.status_code == 400, rr.text)
    other = hubclient.login("web", name="revoke-other", cache=False)
    r = httpx.post(f"{BASE}/revoke", data={"client_id": e["client_id"], "token": other["access_token"]}, timeout=30)
    check("a client cannot revoke another client's token", post("web", other["access_token"]).status_code == 200)

    e = hubclient.login("web", name="theft-test", cache=False)
    t1 = httpx.post(f"{BASE}/token", data={"grant_type": "refresh_token", "client_id": e["client_id"], "refresh_token": e["refresh_token"]}, timeout=30).json()
    check("refresh rotates both tokens", t1["refresh_token"] != e["refresh_token"] and post("web", t1["access_token"]).status_code == 200)
    stolen = httpx.post(f"{BASE}/token", data={"grant_type": "refresh_token", "client_id": e["client_id"], "refresh_token": e["refresh_token"]}, timeout=30)
    check("re-using an old refresh token is refused", stolen.status_code == 400)
    check("...and the legitimate holder's newest access token is revoked too (theft response)", post("web", t1["access_token"]).status_code == 401)

    # ===================== 5. identity-header spoofing =====================
    print("\n--- identity header spoofing ---")
    ltok = hubclient.token_for("latex")
    spoof = {"X-Hub-Subject": "attacker", "X-Hub-Client": "evil", "X-Hub-Scopes": "dokploy:use", "X-Hub-Readonly": "0", "X-Hub-Route": "dokploy", "X-Hub-Client-IP": "6.6.6.6"}
    hdr = {**MCP_HEADERS, "Authorization": f"Bearer {ltok}", **spoof}
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(f"{BASE}/latex/mcp", json=INIT, headers=hdr)
        check("spoofed X-Hub-* headers do not change the outcome of a valid request", r.status_code == 200, r.status_code)
        sid = r.headers.get("mcp-session-id")
        hdr2 = {**hdr, **({"Mcp-Session-Id": sid} if sid else {})}
        await http.post(f"{BASE}/latex/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=hdr2)
        pname = f"spoof-{int(time.time())}"
        r = await http.post(f"{BASE}/latex/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_project", "arguments": {"name": pname}}}, headers=hdr2)
        check("tool call with spoofed identity still succeeds as the REAL subject", r.status_code == 200 and pname in r.text, r.text[:200])
    dirs = sh("latex", "ls /data/ws").stdout.split()
    check("project was created under 'owner', and no 'attacker' workspace exists", "owner" in dirs and "attacker" not in dirs and sh("latex", f"ls /data/ws/owner/{pname}").returncode == 0, dirs)
    wtok = hubclient.token_for("web")
    r = post("latex", wtok, headers={"X-Hub-Route": "web"})
    check("spoofed X-Hub-Route cannot make a web token valid on /latex", r.status_code == 401)
    sh("latex", f"rm -rf /data/ws/owner/{pname}")

    # ===================== 6. GitHub: scope -> read/write, fail closed =====================
    print("\n--- GitHub scope enforcement (fake PAT; no GitHub calls) ---")

    async def gh_tools(token, extra=None):
        async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {token}", **(extra or {})}) as http:
            async with Client(streamable_http_client(f"{BASE}/github/mcp", http_client=http)) as c:
                return {t.name for t in (await c.list_tools()).tools}

    ro = hubclient.token_for("github", ["github:read"])
    rw = hubclient.token_for("github", ["github:read", "github:write"])
    ro_tools, rw_tools = await gh_tools(ro), await gh_tools(rw)
    writes = lambda s: {n for n in s if n.startswith(("create_", "update_", "delete_", "merge_", "push_", "fork_", "add_"))}
    check("github:read token sees read-only tools", len(ro_tools) > 10 and not writes(ro_tools), (len(ro_tools), writes(ro_tools)))
    check("github:write token additionally sees write tools", len(writes(rw_tools)) > 5 and ro_tools < rw_tools, (len(rw_tools), len(ro_tools)))
    for label, extra in [("X-MCP-Readonly: false", {"X-MCP-Readonly": "false"}), ("X-MCP-Readonly: 0", {"X-MCP-Readonly": "0"}), ("X-Hub-Readonly: 0", {"X-Hub-Readonly": "0"}),
                         ("X-MCP-Toolsets: all", {"X-MCP-Toolsets": "all"}), ("X-MCP-Tools: create_issue", {"X-MCP-Tools": "create_issue"}),
                         ("all of them", {"X-MCP-Readonly": "false", "X-Hub-Readonly": "0", "X-MCP-Toolsets": "all", "X-MCP-Features": "all", "X-MCP-Insiders": "true"})]:
        got = await gh_tools(ro, extra)
        check(f"read-only token + client-sent '{label}' does NOT gain write tools or widen toolsets", got == ro_tools, (len(got), len(ro_tools)))
    check("a token for another route is refused on /github", post("github", wtok).status_code == 401)
    sc = httpx.post(f"{BASE}/register", json={"redirect_uris": [hubclient.REDIRECT], "client_name": "x", "scope": "github:write"}, timeout=30)
    check("github:write is a registrable, offered scope when the server is read-write", sc.status_code == 201)

    # ===================== 7. OAuth endpoint hygiene =====================
    print("\n--- OAuth endpoint hygiene ---")
    r = httpx.get(f"{BASE}/consent", params={"req": "req_bogus"}, timeout=15)
    check("consent page with an unknown request id shows 'expired' (400), leaks nothing", r.status_code == 400 and "expired" in r.text.lower() and "<form" not in r.text and "<input" not in r.text)
    r = httpx.get(f"{BASE}/authorize", params={"response_type": "code", "client_id": "nope", "redirect_uri": "https://evil.example/cb"}, timeout=15)
    check("authorize with an unknown client does not redirect to the attacker's URI", r.status_code == 400 and "location" not in r.headers)
    r = httpx.post(f"{BASE}/token", data={"grant_type": "client_credentials"}, timeout=15)
    check("client_credentials grant is not supported", r.status_code in (400, 401))
    r = httpx.post(f"{BASE}/token", data={"grant_type": "password", "username": "owner", "password": "x"}, timeout=15)
    check("password grant is not supported", r.status_code in (400, 401))
    h = {k.lower(): v for k, v in httpx.get(f"{BASE}/consent", params={"req": "x"}, timeout=15).headers.items()}
    check("security headers on the consent page", "frame-ancestors 'none'" in h.get("content-security-policy", "") and h.get("x-frame-options") == "DENY" and h.get("cache-control") == "no-store")

    # ===================== 8. no secrets in logs =====================
    print("\n--- secrets hygiene ---")
    logs = subprocess.run(COMPOSE + ["logs", "gateway", "hub-auth"], capture_output=True, text=True).stdout
    leaked = [t for t in list(toks.values()) + [ro, rw, ltok] if t in logs]
    check("no access token appears in gateway or hub-auth logs", not leaked, len(leaked))
    check("owner password never appears in logs", os.environ["HUBTEST_PASSWORD"] not in logs)
    events = {json.loads(l.split("|", 1)[1])["event"] for l in logs.splitlines() if "hub-auth-1" in l and "{" in l and l.split("|", 1)[1].strip().startswith("{")}
    check("audit log records the security events", {"client_registered", "authorize_approved", "login_ok", "tokens_issued", "token_revoked", "refresh_reuse_detected", "verify_denied"} <= events, sorted(events))
    check("hub-auth state is on a named volume, owned by the unprivileged user", sh("hub-auth", "stat -c %u /data/hubauth.db").stdout.strip() == "10001")

    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


asyncio.run(main())
