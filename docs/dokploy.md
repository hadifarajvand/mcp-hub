# Deploying on Dokploy

1. **Create a Compose app**: Project → Create Service → *Compose*. Source: this
   Git repo, compose path `./docker-compose.yml`, type *Docker Compose*.
2. **Owner login (once)**: run `./scripts/gen-owner.sh` on any machine with Docker. It prints
   `HUB_OWNER_PASSWORD_HASH` and `HUB_OWNER_TOTP_SECRET` and a TOTP URI; add the secret to your authenticator app.
   Nothing is stored by the script.
3. **Environment tab**: paste the variables from `.env.example`. Required: `PUBLIC_BASE_URL` (your https origin, no
   path), `HUB_OWNER_PASSWORD_HASH`, `HUB_OWNER_TOTP_SECRET`. Add credentials for the MCPs you want. Never commit `.env`.
   `docker compose` refuses to start without the three required values, and hub-auth refuses to start with a weak or
   malformed one.
4. **Domains tab**: host `mcp.example.com`, service `gateway`, port `8080`,
   HTTPS on (Let's Encrypt). The compose file already joins `gateway` to the
   external `dokploy-network` that Traefik uses.
5. **Deploy**, then verify from your machine:
   ```bash
   curl -i https://mcp.example.com/healthz                                  # 200 ok
   curl -i -X POST https://mcp.example.com/web/mcp                          # 401 + WWW-Authenticate with resource_metadata
   curl -s https://mcp.example.com/.well-known/oauth-authorization-server   # issuer must equal PUBLIC_BASE_URL exactly
   curl -i https://mcp.example.com/verify                                   # 404 (internal endpoint, never public)
   ```
6. **Rate limiting** (recommended): add a Traefik `rateLimit` middleware to the domain.

## Per-MCP setup

- **Dokploy MCP**: `DOKPLOY_URL` is the panel URL the container can reach (public
  HTTPS URL is simplest). Create the key under Settings → Profile → API/CLI.
  Responses redact env vars/passwords by default. `DOKPLOY_TOOL_PRESET` limits tools.
- **GitHub MCP**: fine-grained PAT limited to the repos you need. Read-only by default; set `GITHUB_READ_ONLY=0` to
  allow the `github:write` scope (a token must then hold it explicitly to write).
- **Transcriber**: enable the Cloud Speech-to-Text API, create a service account,
  paste its JSON key (single line) into `GOOGLE_CREDENTIALS_JSON`.
- **Google Workspace**: create an OAuth client of type *Web application* with
  redirect URI `${PUBLIC_BASE_URL}/google-workspace/oauth2callback`; set
  `USER_GOOGLE_EMAIL`. First use: call a Workspace tool, open the auth URL it
  returns, grant access; tokens persist in the `google-workspace-credentials` volume.

## Not verified locally (needs real credentials and a real domain)

Real claude.ai/ChatGPT connector authorization, real Google OAuth consent through the prefixed callback, real Dokploy API
calls, real GitHub calls, real Speech-to-Text transcription, and Traefik/TLS in
front of the gateway. Check these after the first deploy.
