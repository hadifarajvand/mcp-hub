# MCP Hub - Dokploy Deployment Guide

This guide covers step-by-step setup of MCP Hub on Dokploy using the Docker Compose configuration.

## Prerequisites

- ✅ Dokploy instance running and accessible
- ✅ GitHub repository access (https://github.com/hadifarajvand/mcp-hub)
- ✅ Domain name with DNS pointing to Dokploy server
- ✅ Google OAuth 2.0 credentials (optional, for Google Workspace MCP)
- ✅ Dokploy API key (optional, for Dokploy MCP)

## Step 1: Create Dokploy Compose Project

1. Open Dokploy dashboard
2. Navigate to **Projects** → **New Project**
3. Select **Compose** option
4. Click **Continue**

## Step 2: Configure Git Repository

In the repository configuration section:

| Field | Value |
|-------|-------|
| Repository URL | `https://github.com/hadifarajvand/mcp-hub.git` |
| Branch | `master` |
| Dockerfile Path | Leave empty (uses `docker-compose.yml`) |
| Build Type | Docker Compose |
| Provider | GitHub |

Click **Save & Continue**

## Step 3: Set Environment Variables

### 3a. Google Workspace MCP Configuration

Add the following environment variables to the `google-workspace` service:

```
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret-here
GOOGLE_OAUTH_REDIRECT_URI=https://mcp.yourdomain.com/google-workspace/oauth/callback
TOOL_TIER=docs,sheets,slides,drive,gmail,calendar
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

**How to get credentials:**
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create or select a project
3. Enable APIs: Google Drive, Google Docs, Google Sheets, Google Slides, Gmail, Google Calendar
4. Create OAuth 2.0 credentials (Client ID/Secret)
5. Add authorized redirect URI in Google Cloud Console

### 3b. Transcriber MCP Configuration

Add the following environment variables to the `transcriber` service:

```
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
WHISPER_MODEL=base
```

**Notes:**
- ✅ No credentials needed!
- Model options: `tiny`, `base` (recommended), `small`, `medium`, `large`
- Model will auto-download on first run (~140MB for base)
- Supports 99+ languages

### 3c. Dokploy MCP Configuration

Add the following environment variables to the `dokploy` service:

```
DOKPLOY_URL=http://dokploy:3000
DOKPLOY_API_KEY=your-api-key-from-dokploy-settings
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
MCP_BEARER_TOKEN=
```

**How to get API key:**
1. Open Dokploy dashboard
2. Go to **Settings** → **API Tokens**
3. Create new token (or use existing)
4. Copy and paste into `DOKPLOY_API_KEY`

## Step 4: Configure Domain & TLS

1. In Dokploy project settings, configure domain: `mcp.yourdomain.com`
2. Enable **Automatic TLS** (Let's Encrypt)
3. Ensure DNS A record points to your Dokploy server IP:
   ```
   mcp.yourdomain.com  A  your-dokploy-server-ip
   ```

## Step 5: Configure Ports (if needed)

The default docker-compose.yml maps:
- Port 8001 → Google Workspace MCP
- Port 8002 → Transcriber MCP
- Port 8003 → Dokploy MCP

These are routed through Traefik. If you need custom ports, update docker-compose.yml before deploying.

## Step 6: Deploy

1. Click **Deploy** in Dokploy dashboard
2. Monitor the build and startup process
3. Wait for all three services to show ✅ **Healthy** status

Expected wait time: 2-5 minutes
- Google Workspace: ~60s startup
- Transcriber: ~180s (Whisper model downloads)
- Dokploy: ~45s startup

## Step 7: Verify Deployment

Test each MCP endpoint:

```bash
# Google Workspace
curl -I https://mcp.yourdomain.com/google-workspace/health

# Transcriber
curl -I https://mcp.yourdomain.com/transcriber/health

# Dokploy
curl -I https://mcp.yourdomain.com/dokploy/health
```

Expected response: `200 OK`

## Step 8: Connect to Claude

### Option A: Claude Code CLI

```bash
claude mcp add --transport http google-workspace https://mcp.yourdomain.com/google-workspace
claude mcp add --transport http transcriber https://mcp.yourdomain.com/transcriber
claude mcp add --transport http dokploy https://mcp.yourdomain.com/dokploy

# Verify
claude mcp list-tools
```

### Option B: Claude Desktop

Edit `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "curl",
      "args": ["https://mcp.yourdomain.com/google-workspace"]
    },
    "transcriber": {
      "command": "curl",
      "args": ["https://mcp.yourdomain.com/transcriber"]
    },
    "dokploy": {
      "command": "curl",
      "args": ["https://mcp.yourdomain.com/dokploy"]
    }
  }
}
```

Restart Claude Desktop. MCPs will appear in tool picker.

## Troubleshooting

### Services fail to start

**Check logs:**
```bash
# Via Dokploy UI or
docker logs mcp-google-workspace
docker logs mcp-transcriber
docker logs mcp-dokploy
```

**Common issues:**
- Missing `.env` variables → Add all required vars in Dokploy UI
- Invalid OAuth credentials → Verify in Google Cloud Console
- Invalid Dokploy API key → Generate new token in Dokploy Settings

### OAuth flow doesn't redirect

1. Verify `GOOGLE_OAUTH_REDIRECT_URI` in Dokploy exactly matches your domain
2. Add redirect URI to Google Cloud Console OAuth settings
3. Ensure DNS resolves to Dokploy server

### Transcriber times out on large files

- Whisper has limits (~3 hours audio, ~2.4MB max)
- For large files, consider splitting audio first
- Check logs: `docker logs mcp-transcriber`

### Dokploy MCP can't reach Dokploy API

1. Verify `DOKPLOY_URL` is correct and reachable
2. For Dokploy within Docker: use internal URL `http://dokploy:3000`
3. For external Dokploy: use full HTTPS URL
4. Check API key is valid

### TLS certificate not issued

1. Ensure firewall allows ports 80/443
2. Verify DNS A record points to Dokploy server
3. Wait 60-120s for Let's Encrypt validation
4. Check Dokploy logs for ACME errors

## Production Checklist

- [ ] All three services show ✅ Healthy in Dokploy
- [ ] Health endpoints respond with 200 OK
- [ ] Domain has valid HTTPS certificate
- [ ] Google OAuth credentials are valid
- [ ] Dokploy API key is valid
- [ ] MCPs are registered in Claude Desktop/Code
- [ ] Claude can call MCP tools
- [ ] Test Google Workspace tool (file listing)
- [ ] Test Transcriber tool (audio file)
- [ ] Test Dokploy tool (list projects)

## Performance Tuning

### For high load:

1. **Scale services** in Dokploy:
   - Set container replicas to 2-3
   - Enable load balancing

2. **Increase timeouts** (if needed):
   - Transcriber: Increase `start_period` to 240s for large models
   - Dokploy: Increase `DOKPLOY_TIMEOUT` if API is slow

3. **Monitor resources**:
   - Transcriber uses significant memory (~2GB for base model)
   - Google Workspace uses moderate memory (~500MB)
   - Dokploy uses minimal memory (~200MB)

## Backup & Recovery

### Backup OAuth tokens:
```bash
docker cp mcp-google-workspace:/app/tokens ./tokens-backup
```

### Restore after redeployment:
1. Remove old containers
2. Redeploy via Dokploy
3. Copy tokens back to volume

## Updating MCPs

To update to latest MCP code:

1. In Dokploy, click **Rebuild**
2. Monitor build process
3. Verify services go healthy
4. Re-test in Claude

This pulls latest code from GitHub repositories.

## Support

- **MCP Issues**: See project README.md
- **Dokploy Issues**: Check Dokploy documentation
- **Google OAuth**: Refer to Google Cloud Console docs
- **Logs**: Check Dokploy dashboard or `docker logs`

---

**Deployment Status**: Ready for production
**Last Updated**: 2026-09-21
