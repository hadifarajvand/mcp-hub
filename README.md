# MCP Hub — Google Workspace, Transcriber, Dokploy

A unified, self-hosted **Model Context Protocol (MCP) hub** combining three powerful MCP servers, deployed on **Dokploy** with Docker. Enables Claude Code, Claude Desktop, and other MCP clients to seamlessly:

- **Manage Google Workspace** — Create, read, edit files in Google Drive, Docs, Sheets, Slides; send/manage emails; schedule calendar events
- **Transcribe multilingual audio/video** — Convert MP3, WAV, MP4, MOV to text via Google Cloud Speech-to-Text
- **Control Dokploy deployments** — Manage applications, databases, domains, backups from an MCP interface

## Quick Start

### Prerequisites

- Docker & Docker Compose (v20.10+)
- Dokploy instance running (self-hosted or cloud)
- Google Cloud account with OAuth 2.0 credentials (for Workspace MCP)
- Google Cloud service account with Speech-to-Text API enabled (for Transcriber MCP)
- Dokploy API key (for Dokploy MCP)

### Local Development

```bash
# Clone this repository
git clone <repo-url> mcp-hub
cd mcp-hub

# Copy environment template
cp servers/google-workspace/.env.example servers/google-workspace/.env
cp servers/transcriber/.env.example servers/transcriber/.env
cp servers/dokploy/.env.example servers/dokploy/.env

# Edit .env files with your credentials
nano servers/google-workspace/.env
nano servers/transcriber/.env
nano servers/dokploy/.env

# Build and start all MCP servers
docker compose up --build

# In another terminal, test the health endpoints
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

Each server exposes an HTTP endpoint:
- **Google Workspace MCP**: `http://localhost:8001` (port 8001)
- **Transcriber MCP**: `http://localhost:8002` (port 8002)
- **Dokploy MCP**: `http://localhost:8003` (port 8003)

### Connecting to Claude Code

Once services are running locally:

```bash
# Add Google Workspace MCP
claude mcp add --transport http google-workspace http://localhost:8001

# Add Transcriber MCP
claude mcp add --transport http transcriber http://localhost:8002

# Add Dokploy MCP
claude mcp add --transport http dokploy http://localhost:8003

# Verify tools are available
claude mcp list-tools
```

See [docs/clients.md](docs/clients.md) for detailed Claude Code & Claude Desktop setup.

## Architecture

```
mcp-hub/
├── docker-compose.yml           # Three-service compose project
├── servers/
│   ├── google-workspace/        # Google Workspace MCP (120+ tools)
│   │   ├── Dockerfile
│   │   ├── docker-entrypoint.sh
│   │   └── .env.example
│   ├── transcriber/             # Google Speech-to-Text MCP (3 tools)
│   │   ├── Dockerfile
│   │   ├── server.py            # FastMCP implementation
│   │   ├── requirements.txt
│   │   └── .env.example
│   └── dokploy/                 # Dokploy control MCP (53 tools)
│       ├── Dockerfile
│       ├── docker-entrypoint.sh
│       └── .env.example
└── docs/
    ├── clients.md               # Claude Code / Desktop setup
    ├── oauth-setup.md           # Google OAuth configuration
    ├── gcp-setup.md             # Google Cloud project setup
    └── deployment.md            # Dokploy deployment guide
```

## MCP Servers

### 1. Google Workspace MCP
**Tools**: 120+ across 12 Google services (Drive, Docs, Sheets, Slides, Gmail, Calendar, Tasks, Meet, Contacts, Admin)

**Base**: [taylorwilsdon/workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp)

**Setup**:
1. Create OAuth 2.0 credentials in Google Cloud Console
2. Set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in `.env`
3. On first use, authenticate via OAuth browser flow
4. Tokens persist in Docker volume for subsequent runs

**Key features**:
- Multi-tier tool exposure (limit context bloat by enabling only needed services)
- OAuth 2.1 with automatic token refresh
- Supports all standard Workspace operations

See [docs/oauth-setup.md](docs/oauth-setup.md) for full OAuth guide.

### 2. Transcriber MCP
**Tools**: 3 (transcribe_audio, transcribe_video, list_supported_languages)

**Base**: Custom FastMCP wrapper around Google Cloud Speech-to-Text API

**Supported formats**:
- Audio: MP3, WAV, FLAC, OGG, M4A
- Video: MP4, MOV, AVI, MKV, WebM (audio extracted automatically)

**Supported languages**: 100+ via Google Cloud Speech-to-Text (en-US, pt-BR, es-ES, fr-FR, ja-JP, zh-CN, etc.)

**Setup**:
1. Create Google Cloud service account with Speech-to-Text API access
2. Download JSON credentials
3. Mount credentials as secret in Docker
4. Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env`

See [docs/gcp-setup.md](docs/gcp-setup.md) for full GCP setup guide.

### 3. Dokploy MCP
**Tools**: 53 across deployments, containers, databases, domains, backups, monitoring

**Base**: [gaqno/dokploy-mcp](https://github.com/gaqno/dokploy-mcp)

**Capabilities**:
- Deploy/redeploy applications
- Manage Docker containers, networks, volumes
- Configure and backup databases (MySQL, PostgreSQL, MongoDB, Redis, MariaDB)
- Manage domains and SSL certificates
- Monitor resource usage and logs
- Trigger backup/restore operations

**Setup**:
1. Get Dokploy API key from dashboard
2. Set `DOKPLOY_URL` and `DOKPLOY_API_KEY` in `.env`
3. Optionally set `MCP_BEARER_TOKEN` for additional security

See [docs/deployment.md](docs/deployment.md) for Dokploy-specific deployment guide.

## Deploying on Dokploy

### 1. Push to Git Repository

Dokploy pulls from a Git remote. Push this repository:

```bash
git add .
git commit -m "Initial MCP hub commit"
git push origin main
```

### 2. Create Dokploy Compose Project

1. Log into Dokploy dashboard
2. **Projects** → **New Project** → **Compose** (or select existing project)
3. **Configure Git**:
   - Repository URL: your fork's HTTPS URL
   - Branch: `main`
   - Dockerfile Path: Leave empty (uses docker-compose.yml)
4. **Save**

### 3. Set Environment Variables

In Dokploy dashboard, configure per-service environment variables:

**For google-workspace service**:
- `GOOGLE_OAUTH_CLIENT_ID`: Your OAuth client ID
- `GOOGLE_OAUTH_CLIENT_SECRET`: Your OAuth client secret
- `GOOGLE_OAUTH_REDIRECT_URI`: `https://mcp.yourdomain.com/google-workspace/oauth/callback`

**For transcriber service**:
- `GOOGLE_APPLICATION_CREDENTIALS`: `/app/credentials.json`
- Mount Google service account JSON as a secret

**For dokploy service**:
- `DOKPLOY_URL`: Internal URL to Dokploy API (e.g., `http://dokploy:3000`)
- `DOKPLOY_API_KEY`: API key from Dokploy settings

### 4. Configure TLS & Domains

Dokploy auto-configures Traefik routing:
- **Google Workspace**: `https://mcp.yourdomain.com/google-workspace`
- **Transcriber**: `https://mcp.yourdomain.com/transcriber`
- **Dokploy**: `https://mcp.yourdomain.com/dokploy`

Enable TLS in Dokploy dashboard (automatic via Let's Encrypt).

### 5. Deploy

Click **Deploy** in Dokploy. Monitor logs for errors.

## Adding a New MCP Server

To add a new MCP to the hub:

1. **Create directory**: `servers/new-mcp-name/`
2. **Add Dockerfile**: Wrap the existing MCP server or write minimal HTTP transport wrapper
3. **Add `.env.example`**: Document required credentials
4. **Update `docker-compose.yml`**: Add service block with health check and Traefik labels
5. **Update this README**: Document the new MCP's tools and setup

Example service in `docker-compose.yml`:

```yaml
new-mcp:
  build:
    context: ./servers/new-mcp-name
    dockerfile: Dockerfile
  container_name: mcp-new-mcp
  env_file:
    - ./servers/new-mcp-name/.env
  ports:
    - "8004:8000"
  environment:
    - MCP_HTTP_PORT=8000
    - MCP_HOST=0.0.0.0
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s
  restart: unless-stopped
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.new-mcp.rule=PathPrefix(`/new-mcp`)"
    - "traefik.http.services.new-mcp.loadbalancer.server.port=8000"
```

## Troubleshooting

### Containers fail to start

Check logs:
```bash
docker compose logs google-workspace
docker compose logs transcriber
docker compose logs dokploy
```

Common issues:
- Missing `.env` files (copy from `.env.example`)
- Invalid credentials (check Google OAuth / GCP / Dokploy settings)
- Port conflicts (change `ports` in `docker-compose.yml` if needed)

### OAuth flow hangs

Ensure `GOOGLE_OAUTH_REDIRECT_URI` matches your actual deployment domain exactly.

### Transcriber timeouts on large files

Google Cloud Speech-to-Text has file size and duration limits. See [GCP docs](https://cloud.google.com/speech-to-text/quotas) for details.

### Dokploy MCP cannot reach Dokploy API

Verify `DOKPLOY_URL` is reachable from the container (use internal URL if both run in Docker).

## Security Considerations

- **Credentials**: Never commit `.env` files; use Dokploy's secrets management
- **OAuth tokens**: Stored in Docker volumes; rotate credentials periodically
- **MCP bearer tokens**: Set `MCP_BEARER_TOKEN` in Dokploy MCP for authenticated access
- **Network**: Use HTTPS/TLS in production; behind firewall or VPN if possible
- **Scopes**: Google Workspace MCP starts with docs/sheets/slides/drive/gmail/calendar; add others only as needed

## License

This hub integrates open-source MCP servers licensed under their respective terms:
- `taylorwilsdon/workspace-mcp`: [License](https://github.com/taylorwilsdon/google_workspace_mcp/blob/main/LICENSE)
- `gaqno/dokploy-mcp`: [License](https://github.com/gaqno/dokploy-mcp/blob/main/LICENSE)

Transcriber MCP wrapper: MIT License

## Contributing

Improvements welcome! File issues or PRs to suggest new MCPs, fix bugs, or improve documentation.

## Support

- **MCP Spec**: [modelcontextprotocol.io](https://modelcontextprotocol.io)
- **Anthropic Docs**: [claude.ai/docs](https://claude.ai/docs)
- **Dokploy Docs**: [dokploy.com](https://dokploy.com)
