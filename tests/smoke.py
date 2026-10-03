#!/usr/bin/env python3
"""Connectivity smoke test: real MCP client against every hub route.

  MCP_HUB_TOKEN=... python tests/smoke.py [base_url]    (needs: pip install mcp==2.3.0)
"""
import asyncio
import json
import os
import sys

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
TOKEN = os.environ["MCP_HUB_TOKEN"]
failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        failures.append(name)


async def _gh_unconfigured():
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as h:
        return (await h.get(f"{BASE}/github/mcp")).status_code == 503


async def run(route, call=None):
    http = httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60)
    try:
        transport = streamable_http_client(f"{BASE}/{route}/mcp", http_client=http)
        async with Client(transport) as c:
            tools = [t.name for t in (await c.list_tools()).tools]
            check(f"{route}: initialize + tools/list", len(tools) > 0, f"({len(tools)} tools)")
            if call:
                name, args, expect = call
                res = await c.call_tool(name, args)
                text = json.dumps(res.model_dump(), default=str)
                check(f"{route}: call {name}", expect(text), text[:160].replace("\n", " "))
    except BaseException as e:
        if route == "github" and await _gh_unconfigured():
            print("[SKIP] github: GITHUB_PERSONAL_ACCESS_TOKEN not set on the hub (gateway returns 503)")
            return
        subs = getattr(e, "exceptions", None) or [e]
        check(f"{route}: connect", False, "; ".join(f"{type(x).__name__}: {x}" for x in subs)[:300])
    finally:
        await http.aclose()


async def main():
    await run("dokploy", ("project-all", {}, lambda t: "stub-project" in t))
    await run("transcriber", ("list_languages", {}, lambda t: "en-US" in t))
    await run("transcriber", ("transcribe", {"audio_url": "http://169.254.169.254/x"},
                              lambda t: "non-public" in t or "Refusing" in t))
    await run("github")
    await run("google-workspace")
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


asyncio.run(main())
