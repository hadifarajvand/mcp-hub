# MCP Hub Testing & Deployment Guide

## Local Testing

### Prerequisites
- Docker and Docker Compose installed
- Network connectivity for downloading dependencies

### Building Locally

```bash
cd mcp-hub
docker compose build
```

### Running Locally

```bash
# Start all three MCPs
docker compose up

# In another terminal, run tests
bash test-mcp-connectivity.sh
```

### Service URLs When Running Locally

| MCP | URL | Port |
|-----|-----|------|
| Google Workspace | http://localhost:8001 | 8001 |
| Transcriber | http://localhost:8002 | 8002 |
| Dokploy | http://localhost:8003 | 8003 |

## Testing Connectivity from MCP Clients

### Claude Code / Claude Desktop

1. **Add Google Workspace MCP:**
   ```
   Type: HTTP
   URL: http://localhost:8001
   ```
   - Requires: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` environment variables

2. **Add Transcriber MCP:**
   ```
   Type: HTTP
   URL: http://localhost:8002
   ```
   - **Optional:** `GOOGLE_APPLICATION_CREDENTIALS` for Google Cloud Speech-to-Text
   - **Without credentials:** API responds with error message but endpoint is accessible

3. **Add Dokploy MCP:**
   ```
   Type: HTTP
   URL: http://localhost:8003
   ```
   - Requires: `DOKPLOY_URL`, `DOKPLOY_API_KEY` environment variables

### Testing with curl

```bash
# Test Transcriber health
curl -X GET http://localhost:8002/health

# List supported languages
curl -X POST http://localhost:8002/list_supported_languages \
  -H "Content-Type: application/json" \
  -d '{}'

# Test transcription (without actual audio file)
curl -X POST http://localhost:8002/transcribe_audio \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/nonexistent.wav", "language": "en"}'
```

## Environment Configuration

### Google Workspace (.env)

```env
GOOGLE_OAUTH_CLIENT_ID=your-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
GOOGLE_OAUTH_REDIRECT_URI=https://mcp.yourdomain.com/google-workspace/oauth/callback
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
TOOL_TIER=docs,sheets,slides,drive,gmail,calendar
```

### Transcriber (.env)

```env
# Optional: Set only if using Google Cloud Speech-to-Text
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

### Dokploy (.env)

```env
DOKPLOY_URL=http://dokploy-instance.local:3000
DOKPLOY_API_KEY=your-api-key-from-dokploy-dashboard
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

## Deployment to Dokploy

### 1. Push to GitHub

```bash
git push origin master
```

### 2. Create Dokploy Compose Project

In Dokploy dashboard:
1. Projects → Create Compose Project
2. **Git Repository:** `https://github.com/hadifarajvand/mcp-hub.git`
3. **Branch:** `master`
4. **Compose File:** `docker-compose.yml`

### 3. Set Environment Variables

In Dokploy UI for each service:

**Google Workspace:**
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`

**Transcriber:**
- `GOOGLE_APPLICATION_CREDENTIALS` (optional)

**Dokploy:**
- `DOKPLOY_URL`
- `DOKPLOY_API_KEY`

### 4. Deploy

Click **Deploy** button. Dokploy will:
1. Clone repository
2. Build all three Docker images
3. Create containers
4. Configure Traefik routes
5. Start services with health checks

### 5. Verify Deployment

```bash
# Check service health
curl https://mcp.yourdomain.com/transcriber/health
curl https://mcp.yourdomain.com/google-workspace/health
curl https://mcp.yourdomain.com/dokploy/health

# Test connectivity from Claude Code
# Add MCPs using:
# https://mcp.yourdomain.com/transcriber
# https://mcp.yourdomain.com/google-workspace
# https://mcp.yourdomain.com/dokploy
```

## Troubleshooting

### Service won't start
- Check environment variables are set correctly
- View logs: `docker compose logs [service-name]`
- Verify network connectivity for dependency installation

### MCP client can't connect
- Verify service is healthy: `docker compose ps`
- Check port is exposed: `docker ps`
- Test with curl: `curl -X GET http://localhost:8XXX/health`

### Google Workspace OAuth issues
- Verify callback URL matches OAuth app configuration
- Token storage volume must persist: `docker volume ls`
- Check logs for credential errors: `docker compose logs google-workspace`

### Transcriber with Google Cloud
- Ensure service account JSON is available
- Set `GOOGLE_APPLICATION_CREDENTIALS` to correct path
- Verify service account has Speech-to-Text API access

## Architecture Overview

```
┌─────────────────────────────────────────┐
│        MCP Hub (Docker Compose)          │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────────────────────────┐  │
│  │  Google Workspace MCP            │  │
│  │  - Port: 8001 (local) / 8000     │  │
│  │  - Python + FastAPI + FastMCP    │  │
│  │  - Entry: main.py                │  │
│  └──────────────────────────────────┘  │
│                                         │
│  ┌──────────────────────────────────┐  │
│  │  Transcriber MCP                 │  │
│  │  - Port: 8002 (local) / 8000     │  │
│  │  - Python + FastAPI + Google     │  │
│  │    Cloud Speech-to-Text          │  │
│  │  - Entry: server.py              │  │
│  └──────────────────────────────────┘  │
│                                         │
│  ┌──────────────────────────────────┐  │
│  │  Dokploy MCP                     │  │
│  │  - Port: 8003 (local) / 8000     │  │
│  │  - Node.js + TypeScript + MCP SDK│  │
│  │  - Entry: dist/index.js          │  │
│  └──────────────────────────────────┘  │
│                                         │
└─────────────────────────────────────────┘
```

## Support

For issues or questions:
1. Check service logs: `docker compose logs`
2. Verify environment variables
3. Test connectivity with curl
4. Review error messages in MCP client
