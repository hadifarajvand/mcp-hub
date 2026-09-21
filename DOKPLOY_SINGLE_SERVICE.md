# Dokploy Deployment - Single Service Approach

Since Dokploy's Docker build type doesn't support docker-compose natively, deploy services individually.

## Phase 1: Transcriber MCP (Start Here - Zero Setup)

**In Dokploy Dashboard:**
- Build Type: Docker
- Dockerfile Path: (empty)
- Build Path: (empty)  
- Environment: None needed

**Deploy & Test:**
1. Click Rebuild
2. Wait 3-5 min (Whisper model downloads ~140MB)
3. Test: `curl https://mcp.yourdomain.com/health`

**Add to Claude:**
```bash
claude mcp add --transport http transcriber https://mcp.yourdomain.com
```

✅ Ready immediately. No credentials needed.

---

## Phase 2: Google Workspace MCP

**Create separate Dokploy project:**
- Dockerfile Path: `servers/google-workspace/Dockerfile`
- Environment Variables:
  - `GOOGLE_OAUTH_CLIENT_ID=your-id`
  - `GOOGLE_OAUTH_CLIENT_SECRET=your-secret`
  - `GOOGLE_OAUTH_REDIRECT_URI=https://workspace.yourdomain.com/oauth/callback`
  - `TOOL_TIER=docs,sheets,slides,drive,gmail,calendar`

Requires: Google OAuth setup in Google Cloud Console

---

## Phase 3: Dokploy MCP

**Create separate Dokploy project:**
- Dockerfile Path: `servers/dokploy/Dockerfile`
- Environment Variables:
  - `DOKPLOY_URL=http://dokploy:3000`
  - `DOKPLOY_API_KEY=your-api-key`

Requires: Dokploy API key from Settings

---

## Why This Works

- ✅ Each service is independent Dokploy project
- ✅ Dockerfile per service approach (no docker-compose)
- ✅ Compatible with Dokploy's Docker build type
- ✅ No environment path confusion
- ✅ Easy to add/remove services

## All 176 Tools in Claude

Once all three deployed, add to Claude Desktop config:

```json
{
  "mcpServers": {
    "transcriber": {"command": "curl", "args": ["https://mcp.yourdomain.com"]},
    "google-workspace": {"command": "curl", "args": ["https://workspace.yourdomain.com"]},
    "dokploy-mcp": {"command": "curl", "args": ["https://dokploy-mcp.yourdomain.com"]}
  }
}
```
