# Deploying on Dokploy

1. **Create a Compose app**: Project → Create Service → *Compose*. Source: this
   Git repo, compose path `./docker-compose.yml`, type *Docker Compose*.
2. **Environment tab**: paste the variables from `.env.example`. Required:
   `MCP_HUB_TOKEN`, `PUBLIC_BASE_URL`. Add the credentials for the MCPs you want.
   Never commit `.env`.
3. **Domains tab**: host `mcp.example.com`, service `gateway`, port `8080`,
   HTTPS on (Let's Encrypt). The compose file already joins `gateway` to the
   external `dokploy-network` that Traefik uses.
4. **Deploy**, then verify from your machine:
   ```bash
   curl -i https://mcp.example.com/healthz                       # 200 ok
   curl -i https://mcp.example.com/dokploy/mcp                   # 401
   curl -i -H "Authorization: Bearer $MCP_HUB_TOKEN" https://mcp.example.com/dokploy/health   # 200
   ```
5. **Rate limiting** (recommended): add a Traefik `rateLimit` middleware to the domain.

## Per-MCP setup

- **Dokploy MCP**: `DOKPLOY_URL` is the panel URL the container can reach (public
  HTTPS URL is simplest). Create the key under Settings → Profile → API/CLI.
  Responses redact env vars/passwords by default. `DOKPLOY_TOOL_PRESET` limits tools.
- **GitHub MCP**: fine-grained PAT limited to the repos you need. Read-only unless
  `GITHUB_READ_ONLY=0`.
- **Transcriber**: enable the Cloud Speech-to-Text API, create a service account,
  paste its JSON key (single line) into `GOOGLE_CREDENTIALS_JSON`.
- **Google Workspace**: create an OAuth client of type *Web application* with
  redirect URI `${PUBLIC_BASE_URL}/google-workspace/oauth2callback`; set
  `USER_GOOGLE_EMAIL`. First use: call a Workspace tool, open the auth URL it
  returns, grant access; tokens persist in the `google-workspace-credentials` volume.

## Not verified locally (needs real credentials and a real domain)

Real Google OAuth consent flow through the prefixed callback, real Dokploy API
calls, real GitHub calls, real Speech-to-Text transcription, and Traefik/TLS in
front of the gateway. Check these after the first deploy.
