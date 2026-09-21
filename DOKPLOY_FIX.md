# Dokploy Configuration Fix

## Problem
Error path shows: `/code/docker-compose.yml/servers/dokploy/.env`

Dokploy is treating `docker-compose.yml` as a directory instead of a file.

## Solution: Correct Dokploy UI Settings

### In Dokploy Dashboard:

**Projects → Your MCP Project → Settings**

| Setting | Value |
|---------|-------|
| **Build Type** | Docker Compose |
| **Repository** | https://github.com/hadifarajvand/mcp-hub.git |
| **Branch** | master |
| **Dockerfile Path** | (LEAVE EMPTY) |
| **Docker Context** | (LEAVE EMPTY) |
| **Compose File** | docker-compose.yml |

### Critical: 
- ✋ Do NOT set "Dockerfile Path" for Docker Compose projects
- ✓ Compose File should be: `docker-compose.yml` (not a directory path)
- ✓ No trailing slashes

### Steps:
1. Open project settings
2. Clear any incorrect paths
3. Set Build Type to "Docker Compose"
4. Set Compose File to "docker-compose.yml"
5. Click **Save**
6. Click **Rebuild** (not Deploy)

## Expected Result

After rebuild, you should see:
- ✅ Repo cloned successfully
- ✅ docker-compose.yml parsed correctly  
- ✅ Three services building
- ✅ Google Workspace: Healthy (60s)
- ✅ Transcriber: Healthy (180s)
- ✅ Dokploy: Healthy (45s)

## Environment Variables in Dokploy

Once the project is set up, add these via Dokploy UI (not files):

**google-workspace service:**
```
GOOGLE_OAUTH_CLIENT_ID=your-id
GOOGLE_OAUTH_CLIENT_SECRET=your-secret
GOOGLE_OAUTH_REDIRECT_URI=https://mcp.yourdomain.com/google-workspace/oauth/callback
TOOL_TIER=docs,sheets,slides,drive,gmail,calendar
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

**transcriber service:**
```
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
WHISPER_MODEL=base
```

**dokploy service:**
```
DOKPLOY_URL=http://dokploy:3000
DOKPLOY_API_KEY=your-key
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

---

The code and docker-compose.yml are correct. The issue is in Dokploy's UI configuration.
