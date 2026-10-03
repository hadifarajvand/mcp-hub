# MCP Hub

One self-hosted entry point for several MCP servers, built to run as a single **Dokploy Compose** app.
Access is controlled by **OAuth 2.1** (owner password + TOTP, scopes per MCP, short-lived rotating tokens);
each MCP runs in its own hardened container.

| Route | Server | Scopes | Needs |
|---|---|---|---|
| `/web/mcp` | in-repo: SearXNG search + readable fetch (ChatGPT-compatible `search`/`fetch`) | `web:read` | nothing (self-hosted SearXNG) |
| `/latex/mcp` | in-repo: 30 tools, projects/edit/compile in an isolated sandbox | `latex:use` | nothing |
| `/github/mcp` | official [`github-mcp-server`](https://github.com/github/github-mcp-server) 1.14.0 | `github:read` (+`github:write`) | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `/dokploy/mcp` | official [`@dokploy/mcp`](https://github.com/Dokploy/mcp) 0.30.7 | `dokploy:use` | `DOKPLOY_URL`, `DOKPLOY_API_KEY` |
| `/google-workspace/mcp` | [`workspace-mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) 2.0.0 | `workspace:use` | Google OAuth client, `USER_GOOGLE_EMAIL` |
| `/transcriber/mcp` | in-repo, Google Cloud Speech-to-Text | `transcriber:use` | `GOOGLE_CREDENTIALS_JSON` |

An MCP whose credentials are missing still starts; calling it returns an error (GitHub: HTTP 503 from the gateway).

```
client ─HTTPS─> Dokploy Traefik ─> gateway (Caddy) ──forward_auth──> hub-auth (OAuth server + token check)
                                      └─> one container per MCP        (authnet, internal)
networks: hub (trusted MCPs) · fetchnet (web, transcriber, searxng) · latexnet (latex + sandbox, NO internet) · authnet
```

## Run locally

```bash
cp .env.example .env
./scripts/gen-owner.sh                         # prints HUB_OWNER_PASSWORD_HASH + HUB_OWNER_TOTP_SECRET -> put both in .env
# set PUBLIC_BASE_URL=http://127.0.0.1:8080 in .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# tests (need pip install mcp==2.3.0 httpx pyotp pytest; .env also needs HUBTEST_PASSWORD for the helper):
set -a; . ./.env; set +a
pytest tests/test_ssrf.py tests/test_latex_api.py tests/test_hubauth.py
python tests/smoke.py && python tests/web_e2e.py && python tests/latex_e2e.py && python tests/oauth_e2e.py
./tests/security.sh && python tests/gateway_failclosed.py
```
Behind a TLS-intercepting proxy add `-f docker-compose.proxy-ca.yml` with `BUILD_CA_FILE=/path/ca.crt`.

## Connect a client

See [docs/oauth.md](docs/oauth.md). In short: `claude mcp add --transport http web https://mcp.example.com/web/mcp`
then authenticate in the browser; or add the URL as a custom connector in claude.ai / ChatGPT. One connector per MCP.

## Docs

[docs/dokploy.md](docs/dokploy.md) deploy · [docs/oauth.md](docs/oauth.md) how access works, operating, limits ·
[docs/scopes.md](docs/scopes.md) · [docs/adding-an-mcp.md](docs/adding-an-mcp.md)

## Security model and limits (summary)

- Passing the owner login (password + a fresh TOTP code) is the root of trust: it can authorize clients for Dokploy,
  GitHub and Google. Use a long unique password. Open Dynamic Client Registration is required by claude.ai/ChatGPT and
  is mitigated, not eliminated (see docs/oauth.md).
- Authorization is **per MCP, not per tool**. Dokploy and Workspace are all-or-nothing.
- **LaTeX is code execution.** The sandbox has no network, no secrets, one job at a time, rlimits, a read-only root and
  hardened TeX settings (shell-escape off, paranoid file access, `-norc`, a biber path guard). **LuaLaTeX is the exception**:
  it cannot run under TeX's file restrictions, so its Lua can read any file inside the sandbox (which holds nothing
  sensitive). Disable it with `LATEX_ENABLE_LUALATEX=false`. Not a multi-tenant sandbox.
- Web fetch blocks private/internal addresses (resolve once, connect to the pinned IP, re-check every redirect) and runs
  on a network that cannot reach the other MCPs. SearXNG result quality depends on upstream engines tolerating your IP.
- No JavaScript rendering; transcriber limited to ~5 minutes per call.
- Not verified in the build environment: real claude.ai/ChatGPT connectors, real GitHub/Google/Dokploy calls, Traefik/TLS.
