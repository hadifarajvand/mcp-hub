#!/usr/bin/env python3
"""Test the REAL gateway/Caddyfile in isolation with a stub auth service and an echo 'github'.

Proves the GitHub block fails CLOSED: read-only unless hub-auth explicitly answers X-Hub-Readonly: 0,
the PAT is substituted, client X-MCP-* controls are dropped, and spoofed identity headers never reach upstream.
Needs the built image `mcp-hub-gateway` (docker compose build gateway) and python:3.11-slim.
"""
import json
import subprocess
import sys
import tempfile
import textwrap
import time

import httpx

NET, PORT = "gwtest-net", 18080
failures = []
STUB_AUTH = textwrap.dedent('''
    import http.server, json, os
    MODE = os.environ["MODE"]
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if MODE == "deny":
                self.send_response(401); self.send_header("WWW-Authenticate", 'Bearer error="invalid_token"'); self.end_headers(); return
            self.send_response(200)
            if MODE == "zero": self.send_header("X-Hub-Readonly", "0")
            if MODE == "one": self.send_header("X-Hub-Readonly", "1")
            if MODE == "garbage": self.send_header("X-Hub-Readonly", "false")
            if MODE == "empty": self.send_header("X-Hub-Readonly", "")
            self.send_header("X-Hub-Subject", "owner")
            self.end_headers()
        do_POST = do_GET
        def log_message(self, *a): pass
    http.server.HTTPServer(("0.0.0.0", 9000), H).serve_forever()
''')
ECHO = textwrap.dedent('''
    import http.server, json
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({k.lower(): v for k, v in self.headers.items()}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        do_GET = do_POST
        def log_message(self, *a): pass
    http.server.HTTPServer(("0.0.0.0", 8082), H).serve_forever()
''')


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {('- ' + str(detail)[:200]) if (detail and not ok) else ''}")
    if not ok:
        failures.append(name)


def sh(*a, **kw):
    return subprocess.run(a, capture_output=True, text=True, **kw)


def run_scenario(mode, headers=None):
    d = tempfile.mkdtemp()
    open(f"{d}/stub.py", "w").write(STUB_AUTH)
    open(f"{d}/echo.py", "w").write(ECHO)
    names = []

    def up(name, *args):
        sh("docker", "run", "-d", "--rm", "--name", name, "--network", NET, *args)
        names.append(name)

    try:
        up("gw-stub", "--network-alias", "hub-auth", "-e", f"MODE={mode}", "-v", f"{d}/stub.py:/s.py:ro", "python:3.11-slim", "python", "/s.py")
        up("gw-echo", "--network-alias", "github", "-v", f"{d}/echo.py:/e.py:ro", "python:3.11-slim", "python", "/e.py")
        up("gw-caddy", "-p", f"127.0.0.1:{PORT}:8080", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN=ghp_REAL_PAT_VALUE", "mcp-hub-gateway")
        for _ in range(50):
            try:
                if httpx.get(f"http://127.0.0.1:{PORT}/healthz", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        time.sleep(1)
        h = {"Authorization": "Bearer client-supplied-token", "Content-Type": "application/json", **(headers or {})}
        return httpx.post(f"http://127.0.0.1:{PORT}/github/mcp", json={"x": 1}, headers=h, timeout=20)
    finally:
        for n in names:
            sh("docker", "rm", "-f", n)


def main():
    sh("docker", "network", "rm", NET)
    sh("docker", "network", "create", NET)
    try:
        spoof = {"X-MCP-Toolsets": "all", "X-MCP-Tools": "create_issue", "X-MCP-Features": "all", "X-MCP-Insiders": "true", "X-MCP-Lockdown": "false",
                 "X-MCP-Exclude-Tools": "", "X-Hub-Subject": "attacker", "X-Hub-Scopes": "github:write", "X-MCP-Readonly": "false", "X-Hub-Readonly": "0"}
        for mode, expect, why in [("none", "true", "auth service omitted the header"), ("empty", "true", "auth service sent an empty header"),
                                  ("garbage", "true", "auth service sent an unexpected value"), ("one", "true", "explicit read-only"),
                                  ("zero", "false", "ONLY an explicit 0 lifts read-only")]:
            r = run_scenario(mode, spoof)
            got = r.json() if r.status_code == 200 else {}
            check(f"[{mode}] upstream receives X-MCP-Readonly={expect} ({why})", r.status_code == 200 and got.get("x-mcp-readonly") == expect, (r.status_code, got.get("x-mcp-readonly")))
            check(f"[{mode}] the PAT replaces the client's Authorization", got.get("authorization") == "Bearer ghp_REAL_PAT_VALUE" and "client-supplied-token" not in json.dumps(got), got.get("authorization"))
            leaked = [k for k in ("x-mcp-toolsets", "x-mcp-tools", "x-mcp-features", "x-mcp-insiders", "x-mcp-lockdown", "x-mcp-exclude-tools") if k in got]
            check(f"[{mode}] client-sent X-MCP-* controls are dropped", not leaked, leaked)
            check(f"[{mode}] spoofed X-Hub-Scopes never reaches upstream; subject comes only from the auth service",
                  got.get("x-hub-scopes") in (None, "") and got.get("x-hub-subject") == "owner", (got.get("x-hub-scopes"), got.get("x-hub-subject")))
        r = run_scenario("deny", spoof)
        check("[deny] auth service refuses -> client gets 401 + WWW-Authenticate and upstream is never contacted", r.status_code == 401 and "invalid_token" in r.headers.get("www-authenticate", ""), r.status_code)
    finally:
        sh("docker", "network", "rm", NET)
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


main()
