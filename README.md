# MCP Hub

One self-hosted entry point for several MCP servers, built to run as a single
**Dokploy Compose** app. Every request needs a bearer token; each MCP lives in
its own hardened container.

| Route | Server | Needs |
|---|---|---|
| `/dokploy/mcp` | official [`@dokploy/mcp`](https://github.com/Dokploy/mcp) 0.30.7 | `DOKPLOY_URL`, `DOKPLOY_API_KEY` |
| `/github/mcp` | official [`github-mcp-server`](https://github.com/github/github-mcp-server) 1.14.0 (read-only by default) | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `/transcriber/mcp` | in-repo server, Google Cloud Speech-to-Text | `GOOGLE_CREDENTIALS_JSON` |
| `/google-workspace/mcp` | [`workspace-mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) 2.0.0 | OAuth client ID/secret, `USER_GOOGLE_EMAIL` |

An MCP whose credentials are missing still starts; calling it returns an error
(GitHub returns HTTP 503 from the gateway).

```
client ──HTTPS──> Dokploy Traefik ──> gateway (Caddy, bearer check) ──> one container per MCP
```

## Run locally

```bash
cp .env.example .env          # set MCP_HUB_TOKEN=$(openssl rand -hex 32), PUBLIC_BASE_URL=http://127.0.0.1:8080
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
pip install mcp==2.3.0 httpx
MCP_HUB_TOKEN=... python tests/smoke.py      # connectivity, real MCP client
MCP_HUB_TOKEN=... tests/security.sh          # auth / isolation / hardening / secrets
```

Behind a TLS-intercepting proxy, set `BUILD_CA_FILE=/path/to/ca.crt` in `.env`.

## Connect a client

```bash
claude mcp add --transport http dokploy https://mcp.example.com/dokploy/mcp \
  --header "Authorization: Bearer $MCP_HUB_TOKEN"
```

Clients that cannot send custom headers (claude.ai web connectors, ChatGPT)
are **not supported**: they require an OAuth flow this hub does not implement.

## Deploy / extend

- Dokploy setup: [docs/dokploy.md](docs/dokploy.md)
- Adding another MCP: [docs/adding-an-mcp.md](docs/adding-an-mcp.md)

## Security model and limits

- One shared bearer token (min 32 chars) gates everything except `/healthz` and
  Google's OAuth browser callback. Anyone holding it can use every configured
  MCP, including whatever your Dokploy API key and GitHub PAT allow. Scope those
  credentials minimally. Rotate with `MCP_HUB_TOKEN_2`.
- No rate limiting in the gateway. Add a Traefik rate-limit middleware in Dokploy.
- MCP containers can reach the internet (they must, to call GitHub/Google/Dokploy).
  They are not published on any host port and are reachable only via the gateway.
- Transcriber limits: ~5 minutes of audio per call (inline Google STT limit),
  20 MB input; URL downloads block non-public addresses.
