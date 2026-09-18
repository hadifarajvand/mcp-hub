# Dokploy Deployment Guide

Complete guide to deploy the MCP Hub on Dokploy.

## Prerequisites

- Dokploy instance running (self-hosted or cloud)
- Git repository with MCP Hub code (forked or pushed to your Git service)
- Access to Dokploy admin dashboard
- Domain name (for HTTPS/TLS)
- Credentials ready:
  - Google OAuth client ID & secret (for Workspace MCP)
  - Google service account JSON (for Transcriber MCP)
  - Dokploy API key (for Dokploy MCP)

## Step 1: Prepare Repository

1. Fork this repository or push to your Git service (GitHub, GitLab, Gitea, Gitbucket):

```bash
git remote add origin https://github.com/your-org/mcp-hub.git
git push -u origin main
```

2. Ensure `docker-compose.yml` is in the repository root (it is by default)

3. Do NOT commit `.env` files or credentials:
   ```bash
   # Already in .gitignore, but verify:
   echo "google-credentials.json" >> .gitignore
   git add .gitignore
   git commit -m "Ensure credentials are not committed"
   git push
   ```

## Step 2: Create Dokploy Compose Project

1. Log into Dokploy dashboard (`https://your-dokploy-domain`)

2. Navigate to **Projects** (or create if needed)

3. Click **Create New Project** → **Compose**

4. Fill in project details:
   - **Name**: "mcp-hub"
   - **Description**: "MCP Hub for Google Workspace, Transcriber, Dokploy"

5. Configure Git:
   - **Repository URL**: `https://github.com/your-org/mcp-hub.git` (HTTPS, not SSH)
   - **Branch**: `main`
   - **Auto Deploy**: Toggle on (optional, to redeploy on push)
   - **Build on Deploy**: Enable
   - **Docker Compose Path**: Leave empty or set to `docker-compose.yml`

6. Click **Create Project**

## Step 3: Set Environment Variables

In Dokploy, set per-service environment variables (never committed to Git):

### Google Workspace Service

Navigate to the `google-workspace` service settings:

- `GOOGLE_OAUTH_CLIENT_ID`: Your OAuth client ID (from Google Cloud Console)
- `GOOGLE_OAUTH_CLIENT_SECRET`: Your OAuth client secret
- `GOOGLE_OAUTH_REDIRECT_URI`: `https://mcp.yourdomain.com/google-workspace/oauth/callback`
- `TOOL_TIER`: `docs,sheets,slides,drive,gmail,calendar` (or customize)
- `MCP_HTTP_PORT`: `8000`
- `MCP_HOST`: `0.0.0.0`

### Transcriber Service

Navigate to the `transcriber` service settings:

- `GOOGLE_APPLICATION_CREDENTIALS`: `/app/credentials.json`
- `MCP_HTTP_PORT`: `8000`
- `MCP_HOST`: `0.0.0.0`

Then, add the Google service account JSON as a file volume:
- File/Secret: `google-credentials.json` (contents: paste the JSON from your downloaded key)
- Mount to: `/app/credentials.json` (read-only)

### Dokploy Service

Navigate to the `dokploy` service settings:

- `DOKPLOY_URL`: Internal URL to Dokploy (e.g., `http://dokploy:3000` or `http://localhost:3000`)
- `DOKPLOY_API_KEY`: Your Dokploy API key (from **Settings** → **API Tokens** in Dokploy)
- `MCP_HTTP_PORT`: `8000`
- `MCP_HOST`: `0.0.0.0`
- `MCP_BEARER_TOKEN`: Optional, for additional security (e.g., a random 32-character token)

## Step 4: Configure Domains & TLS

Dokploy uses Traefik to automatically route requests. Configure domains:

1. Go to project settings → **Domains**

2. Set the base domain: `mcp.yourdomain.com`

3. For each service, Dokploy automatically routes:
   - `mcp.yourdomain.com/google-workspace` → google-workspace container
   - `mcp.yourdomain.com/transcriber` → transcriber container
   - `mcp.yourdomain.com/dokploy` → dokploy container

4. Enable TLS:
   - Dokploy integrates Let's Encrypt for free SSL certificates
   - Configure in **Project Settings** → **TLS/SSL**
   - Let's Encrypt will auto-renew 30 days before expiry

5. Verify DNS:
   - Ensure your domain (`mcp.yourdomain.com`) resolves to your Dokploy server's IP

## Step 5: Deploy

1. Click **Deploy** in Dokploy dashboard

2. Monitor deployment logs:
   - Watch for build progress and startup messages
   - Ensure all three services reach "healthy" state (green)

3. Once deployment is complete, verify endpoints:

```bash
# Test each MCP endpoint
curl https://mcp.yourdomain.com/google-workspace/health
curl https://mcp.yourdomain.com/transcriber/health
curl https://mcp.yourdomain.com/dokploy/health
```

Expected response: HTTP 200

## Step 6: Configure Clients

Now that the MCP hub is deployed, configure Claude Code or Claude Desktop to use the remote endpoints.

### Claude Code

```bash
claude mcp add --transport http google-workspace https://mcp.yourdomain.com/google-workspace
claude mcp add --transport http transcriber https://mcp.yourdomain.com/transcriber
claude mcp add --transport http dokploy https://mcp.yourdomain.com/dokploy
```

### Claude Desktop

Update `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "curl",
      "args": ["--http1.1", "https://mcp.yourdomain.com/google-workspace"],
      "env": {}
    },
    "transcriber": {
      "command": "curl",
      "args": ["--http1.1", "https://mcp.yourdomain.com/transcriber"],
      "env": {}
    },
    "dokploy": {
      "command": "curl",
      "args": ["--http1.1", "https://mcp.yourdomain.com/dokploy"],
      "env": {}
    }
  }
}
```

See [docs/clients.md](clients.md) for more details.

## Step 7: Test Google Workspace OAuth

The Google Workspace MCP requires OAuth authentication on first use:

1. In Claude (Code or Desktop), call a Google Workspace tool (e.g., "List my Google Drive files")

2. The MCP opens a browser to Google's OAuth consent screen

3. Grant permission to your Google account

4. Browser redirects back to `https://mcp.yourdomain.com/google-workspace/oauth/callback`

5. Token is saved in Docker volume; future calls use the saved token

**Troubleshooting**: If OAuth redirect fails:
- Verify domain resolves correctly
- Check firewall allows HTTPS on port 443
- Ensure `GOOGLE_OAUTH_REDIRECT_URI` in Dokploy exactly matches the callback URL

## Monitoring & Logs

### View Service Logs

In Dokploy dashboard, click on each service and view **Logs**:

```bash
# Or via Docker on the Dokploy server
docker logs mcp-google-workspace
docker logs mcp-transcriber
docker logs mcp-dokploy
```

### Monitor Resource Usage

Dokploy dashboard shows CPU, memory, and disk usage per service. Typical usage:
- **Google Workspace**: ~200 MB RAM, minimal CPU (idle)
- **Transcriber**: ~500 MB RAM, high CPU during transcription
- **Dokploy**: ~150 MB RAM, minimal CPU (idle)

### Alerts & Health Checks

Dokploy monitors container health via the `healthcheck` defined in `docker-compose.yml`. If a service becomes unhealthy:
- Logs will show the failure
- Container may be auto-restarted (depending on policy)
- Configure notifications in Dokploy settings

## Scaling & Updates

### Auto-Redeploy on Git Push

Enable **Auto Deploy** in project settings. Then:

```bash
# Push changes to main branch
git push origin main

# Dokploy automatically redeploys
```

### Manual Redeploy

Click **Redeploy** in Dokploy dashboard to pull latest code and rebuild.

### Scaling Services

By default, each service runs one container. To scale:

1. In `docker-compose.yml`, add `deploy:` section (if using Docker Swarm)
2. Or use Dokploy's **Scaling** feature in service settings
3. Or use external load balancer/orchestration

For most use cases, one container per service is sufficient.

## Backups & Persistence

### Persistent Data

MCP services store data in Docker volumes:
- **google-workspace-tokens**: OAuth tokens (automatically created)
- **transcriber-cache**: Transcription cache (optional)

Dokploy handles volume snapshots via its backup features. Configure in:
- **Project Settings** → **Backups**

### OAuth Token Recovery

If the `google-workspace-tokens` volume is lost:
1. Delete the volume
2. Redeploy
3. OAuth re-authentication will be required on next use

## Troubleshooting

### Deployment fails during build

Check build logs in Dokploy:
- Ensure all base images are accessible (Python 3.11, etc.)
- Verify network access to GitHub (for git clones)
- Check disk space on server

### Services unhealthy / stuck in restarting loop

1. Check logs: `docker logs mcp-<service>`
2. Common causes:
   - Missing or invalid `.env` variables
   - Google Cloud credentials not mounted or invalid
   - Port conflicts (8001, 8002, 8003 already in use)
3. Redeploy after fixing configuration

### Google Workspace OAuth redirect fails

- Verify domain resolves: `nslookup mcp.yourdomain.com`
- Check HTTPS works: `curl -v https://mcp.yourdomain.com/health`
- Ensure TLS certificate is valid (not self-signed)
- Verify callback URL in Google Cloud Console exactly matches

### Dokploy MCP cannot reach Dokploy API

- Use internal URL for `DOKPLOY_URL` (e.g., `http://dokploy:3000`, not public domain)
- If Dokploy runs on same server, verify network connectivity
- Check firewall rules between containers

### Transcriber times out on large files

- Increase `TRANSCRIPTION_TIMEOUT` in `.env` (in seconds)
- Google Cloud Speech-to-Text has processing limits
- For very large files (>1 GB), consider splitting into chunks

## Performance Optimization

### Caching

Transcriber MCP caches processed files in `transcriber-cache` volume. Clear if needed:

```bash
docker volume rm mcp-hub_transcriber-cache
docker compose up --build
```

### CPU/Memory Tuning

In `docker-compose.yml`, add resource limits per service:

```yaml
google-workspace:
  # ...
  deploy:
    resources:
      limits:
        cpus: '1'
        memory: 512M
      reservations:
        cpus: '0.5'
        memory: 256M
```

### Reverse Proxy Tuning

Dokploy's Traefik proxy can be tuned for throughput. Refer to [Traefik Docs](https://doc.traefik.io/traefik/).

## Support

- **Dokploy Docs**: [dokploy.com](https://dokploy.com)
- **Docker Compose**: [docker.com/docs/compose](https://docs.docker.com/compose/)
- **Let's Encrypt**: [letsencrypt.org](https://letsencrypt.org)
- **Traefik**: [traefik.io](https://traefik.io)
