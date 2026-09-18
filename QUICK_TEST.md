# Quick Testing Guide

## 1. Start Services

```bash
cd mcp-hub
docker compose up
```

Wait for all services to report "healthy" (30-60 seconds).

## 2. Test Each Service

### Transcriber (Port 8002)

```bash
# Health check
curl http://localhost:8002/health

# List supported languages
curl -X POST http://localhost:8002/list_supported_languages \
  -H "Content-Type: application/json" \
  -d '{}'

# Test transcription (no file exists, but endpoint responds)
curl -X POST http://localhost:8002/transcribe_audio \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/tmp/test.wav", "language": "en"}'
```

**Expected:** HTTP 200 with JSON response (either error or success message)

### Google Workspace (Port 8001)

```bash
# Health check
curl http://localhost:8001/health
```

**Expected:** HTTP 200 if OAuth credentials are not required for health check
**Note:** Full OAuth setup requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET

### Dokploy (Port 8003)

```bash
# Health check  
curl http://localhost:8003/health
```

**Expected:** HTTP 200 if server is running

## 3. In Claude Code/Desktop

Add these as MCP servers with HTTP transport:
- `http://localhost:8001` - Google Workspace
- `http://localhost:8002` - Transcriber
- `http://localhost:8003` - Dokploy

Then test by viewing available tools from each server.

## 4. Check Logs

```bash
# All services
docker compose logs

# Specific service
docker compose logs -f transcriber
docker compose logs -f google-workspace
docker compose logs -f dokploy
```

## Environment Variables Needed for Full Functionality

### Transcriber (Optional)
```
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```
Without this, API still works but returns "not available" errors.

### Google Workspace (Required)
```
GOOGLE_OAUTH_CLIENT_ID=xxx
GOOGLE_OAUTH_CLIENT_SECRET=xxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8001/oauth/callback
```

### Dokploy (Required)
```
DOKPLOY_URL=http://localhost:3000
DOKPLOY_API_KEY=xxx
```

## Success Criteria

- [ ] All three services report "healthy" in `docker compose ps`
- [ ] HTTP endpoints respond with status 200 to health checks
- [ ] Transcriber API returns JSON responses to `/transcribe_audio` and `/list_supported_languages`
- [ ] Claude Code can reach and display tools from at least Transcriber
- [ ] No Python/Node.js runtime errors in logs
