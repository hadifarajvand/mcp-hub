#!/usr/bin/env python3
"""End-to-end tests for the web MCP through the gateway (dev overlay: needs web-fixture).

  set -a; . ./.env; set +a; python tests/web_e2e.py [base_url]
"""
import asyncio
import json
import os
import subprocess
import sys

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
sys.path.insert(0, os.path.dirname(__file__))
import hubclient  # noqa: E402
FX = "http://172.30.55.200:8080"
failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {('- ' + str(detail)[:150]) if (detail and not ok) else ''}")
    if not ok:
        failures.append(name)


async def main():
    http = httpx.AsyncClient(auth=hubclient.HubAuth("web"), timeout=90)
    async with Client(streamable_http_client(f"{BASE}/web/mcp", http_client=http)) as c:
        async def call(name, args):
            r = await c.call_tool(name, args)
            text = "".join(getattr(x, "text", "") for x in r.content)
            return r.is_error, text, r.structured_content

        async def ok_fetch(args):
            err, text, sc = await call("fetch_url", args)
            if err:
                print(f"       (fetch_url error for {args.get('url')}: {text[:200]})")
            return (None if err else sc), text

        tools = {t.name for t in (await c.list_tools()).tools}
        check("tools exposed", {"search", "fetch", "web_search", "fetch_url", "fetch_many", "extract_links"} <= tools, tools)

        # ---- ChatGPT-compatible search/fetch shapes (live internet) ----
        err, text, _ = await call("search", {"query": "python programming language"})
        results = json.loads(text)["results"] if not err else []
        check("search: JSON text {results:[{id,title,url}]}", bool(results) and all({"id", "title", "url"} <= set(r) for r in results), text)
        err, text, _ = await call("fetch", {"id": "https://www.python.org/"})
        doc = json.loads(text) if not err else {}
        check("fetch: JSON text {id,title,text,url,metadata}", {"id", "title", "text", "url", "metadata"} <= set(doc) and len(doc.get("text", "")) > 200, text[:200])

        err, text, sc = await call("web_search", {"query": "rust ownership", "max_results": 5, "site": "doc.rust-lang.org"})
        urls = [r["url"] for r in sc["results"]] if sc else []
        check("web_search: structured results", not err and len(urls) >= 1, text[:200])
        # site: is passed to the engines as an operator; engines honour it unevenly, so only warn.
        if not all("doc.rust-lang.org" in u for u in urls):
            print(f"[WARN] site filter not honoured by every engine: {urls}")
        err, text, _ = await call("web_search", {"query": "x", "categories": "bogus"})
        check("web_search: bad category -> isError", err)
        err, text, _ = await call("web_search", {"query": "x", "page": 99})
        check("web_search: bad page -> isError", err)

        # ---- extraction quality (fixture) ----
        sc, _ = await ok_fetch({"url": f"{FX}/article"})
        md = sc["content"] if sc else ""
        check("article markdown has main content", "PINEAPPLE-7421" in md, md[:200])
        check("article markdown drops nav/footer boilerplate", "NAVIGATION NOISE" not in md and "COOKIE BANNER" not in md, md[:300])
        check("article metadata (title/author)", sc and sc["title"] and "Fixture Article" in sc["title"] and sc["metadata"].get("author") == "Ada Lovelace", sc and sc["metadata"])
        sc2, _ = await ok_fetch({"url": f"{FX}/article", "format": "text"})
        check("text format", sc2 and "PINEAPPLE-7421" in sc2["content"] and "#" not in sc2["content"][:5])
        sc3, _ = await ok_fetch({"url": f"{FX}/article", "format": "html"})
        check("html format returns raw markup", sc3 and "<nav>" in sc3["content"])
        sc4, _ = await ok_fetch({"url": f"{FX}/article", "format": "metadata"})
        check("metadata format has no body", sc4 and sc4["content"] == "" and sc4["title"] and "Fixture Article" in sc4["title"])
        sc5, _ = await ok_fetch({"url": f"{FX}/article", "include_links": True})
        check("include_links keeps hyperlinks", sc5 and "/linked-page" in sc5["content"], sc5 and sc5["content"][:300])
        sc, _ = await ok_fetch({"url": f"{FX}/pdf"})
        check("PDF text extraction", sc and "PDF-MARKER-5530" in sc["content"], sc and sc["content"])
        sc, _ = await ok_fetch({"url": f"{FX}/json"})
        check("JSON passthrough", sc and '"hello"' in sc["content"])
        sc, _ = await ok_fetch({"url": f"{FX}/text"})
        check("text/plain passthrough", sc and sc["content"] == "plain text body")
        sc, _ = await ok_fetch({"url": f"{FX}/redirect"})
        check("redirect followed; final_url reported", sc and sc["final_url"].endswith("/article") and "PINEAPPLE" in sc["content"], sc and sc["final_url"])

        # ---- pagination ----
        full, _ = await ok_fetch({"url": f"{FX}/long", "max_length": 100000})
        total = full["total_length"]
        pages, start = [], 0
        while start is not None and len(pages) < 200:
            p, _ = await ok_fetch({"url": f"{FX}/long", "max_length": 5000, "start_index": start})
            pages.append(p["content"])
            start = p["next_start_index"]
        joined = "".join(pages)
        check("pagination reassembles exactly (len == total_length, prefix == first page)",
              len(joined) == total and joined.startswith(full["content"]) and len(pages) > 3 and full["next_start_index"] == 100000, (len(pages), total, len(joined)))
        err, _, _ = await call("fetch_url", {"url": f"{FX}/article", "max_length": 0})
        check("max_length=0 rejected", err)

        # ---- failure modes must be tool errors, not crashes ----
        for path, why in [("/404", "HTTP 404"), ("/binary", "content type"), ("/private", "robots"), ("/redirect-loop", "redirects"),
                          ("/gzip-bomb", "exceeds"), ("/huge", "exceeds")]:
            err, text, _ = await call("fetch_url", {"url": FX + path})
            check(f"{path} -> isError ({why})", err and why.split()[0].lower() in text.lower(), text[:160])

        # ---- SSRF through the tool surface ----
        for u in ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8000/health", "http://localhost:8000/health",
                  "http://dokploy:3000/health", "http://dokploy-stub:3000/api/project.all", "http://hub-auth:9000/", "http://searxng:8080/search?q=x&format=json",
                  "http://[::1]:8000/", "http://[::ffff:7f00:1]:8080/", "http://2130706433:8080/", "http://0x7f.1:8080/", "http://user:pw@example.com/",
                  "file:///etc/passwd", "gopher://example.com/", "http://example.com:22/", "http://example.com:6379/",
                  FX + "/redirect-metadata", FX + "/redirect-internal"]:
            err, text, _ = await call("fetch_url", {"url": u})
            check(f"SSRF blocked: {u}", err and "PINEAPPLE" not in text and "project" not in text.lower().replace("projectid", "") + "x"[:0], text[:140])

        # ---- links / many ----
        err, text, sc = await call("extract_links", {"url": f"{FX}/article"})
        urls = [l["url"] for l in sc["links"]] if sc else []
        check("extract_links absolute + deduped", f"{FX}/linked-page" in urls and "https://example.org/ext" in urls, urls)
        err, text, sc = await call("extract_links", {"url": f"{FX}/article", "same_domain_only": True})
        check("extract_links same_domain_only", sc and all(l["url"].startswith(FX) for l in sc["links"]) and sc["links"], text[:200])
        err, text, sc = await call("fetch_many", {"urls": [f"{FX}/article", f"{FX}/404", "http://169.254.169.254/", f"{FX}/text"]})
        r = sc["results"] if sc else []
        check("fetch_many isolates failures", len(r) == 4 and "content" in r[0] and "error" in r[1] and "error" in r[2] and "content" in r[3], text[:300])
        err, _, _ = await call("fetch_many", {"urls": [FX + "/text"] * 11})
        check("fetch_many >10 rejected", err)

    await http.aclose()

    # ---- network isolation: fetchnet cannot reach the trusted network ----
    for host in ["dokploy", "github", "google-workspace", "dokploy-stub"]:
        out = subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "exec", "-T", "web", "python", "-c",
                              f"import socket;socket.gethostbyname('{host}')"], capture_output=True, text=True)
        check(f"web container cannot resolve trusted service '{host}'", out.returncode != 0, out.stdout + out.stderr[-100:])

    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


asyncio.run(main())
