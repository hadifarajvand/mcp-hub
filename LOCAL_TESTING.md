# Local Testing Guide

## Quick Start

Run the complete local deployment and testing with one command:

```bash
bash test-local-deployment.sh
```

This script will:
1. Clean up previous deployments
2. Build all Docker images
3. Start all three services
4. Wait for services to be healthy
5. Test all endpoints
6. Display service information

## Manual Testing Steps

If you prefer to run commands manually:

### 1. Start Services

```bash
docker compose -f docker-compose.test.yml up --build
```

### 2. Test Service Health

```bash
# Transcriber
curl http://localhost:8002/health

# Google Workspace  
curl http://localhost:8001/health

# Dokploy
curl http://localhost:8003/health
```

Expected response: `{"status":"ok","service":"..."}`

### 3. Test Endpoints

**Transcriber - List Languages:**
```bash
curl -X POST http://localhost:8002/list_supported_languages \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Transcriber - Transcribe Audio (test with non-existent file):**
```bash
curl -X POST http://localhost:8002/transcribe_audio \
  -H "Content-Type: application/json" \
  -d '{"file_path":"/tmp/test.wav","language":"en"}'
```

**Google Workspace - Service Info:**
```bash
curl http://localhost:8001/
```

**Dokploy - Service Info:**
```bash
curl http://localhost:8003/
```

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| Google Workspace | 8001 | http://localhost:8001 |
| Transcriber | 8002 | http://localhost:8002 |
| Dokploy | 8003 | http://localhost:8003 |

## What's Being Tested

### Google Workspace (Mock Server)
- Uses mock implementation for testing
- Real production version requires OAuth setup
- Tests HTTP connectivity and basic endpoints
- Mock responds to /health and / endpoints

### Transcriber (Real Implementation)
- Actual FastAPI server with real endpoints
- Tests transcription API structure
- Without Google Cloud credentials, returns "not available" errors
- Core functionality: `/health`, `/transcribe_audio`, `/transcribe_video`, `/list_supported_languages`

### Dokploy (Mock Server)
- Uses mock implementation for testing  
- Real production version requires Dokploy API credentials
- Tests HTTP connectivity and basic endpoints
- Mock responds to /health and / endpoints

## Viewing Logs

```bash
# All services
docker compose -f docker-compose.test.yml logs

# Specific service with follow
docker compose -f docker-compose.test.yml logs -f transcriber
docker compose -f docker-compose.test.yml logs -f google-workspace
docker compose -f docker-compose.test.yml logs -f dokploy
```

## Stopping Services

```bash
docker compose -f docker-compose.test.yml down
```

## Stopping and Removing Volumes

```bash
docker compose -f docker-compose.test.yml down -v
```

## Testing in Claude Code / Claude Desktop

Once services are running locally:

1. In Claude Code/Desktop settings, add MCP servers
2. Use HTTP transport type
3. Add servers:
   - `http://localhost:8001` - Google Workspace
   - `http://localhost:8002` - Transcriber
   - `http://localhost:8003` - Dokploy

4. Test by querying available tools from each server

## Troubleshooting

### Services won't start
- Check if ports 8001, 8002, 8003 are available
- Run `docker ps` to see if any containers are already using these ports
- Logs: `docker compose -f docker-compose.test.yml logs`

### Health checks timing out
- Services take time to start, wait 20-30 seconds
- Check: `docker compose -f docker-compose.test.yml ps`

### Transcriber returns "not available"
- This is expected - it means Google Cloud Speech isn't configured
- API is still working correctly (returns error response)
- Connectivity test passes

### Network errors
- For production: use docker-compose.yml (not .test.yml)
- Production version clones full repos from GitHub
- Test version uses minimal images for local testing

## Production vs Test

| Aspect | Test (test.yml) | Production (docker-compose.yml) |
|--------|-----------------|--------------------------------|
| Google Workspace | Mock server | Full cloned repo |
| Dokploy | Mock server | Full cloned repo + npm build |
| Transcriber | Real FastAPI | Real FastAPI (same) |
| Network deps | Minimal | Full (requires stable network) |
| Goal | Test connectivity | Deploy to Dokploy |

## Next Steps After Testing

Once all services are running and responding correctly:

1. ✅ Local testing passed
2. Use `docker-compose.yml` (production version) for Dokploy
3. Push to GitHub: `git push origin master`
4. Deploy via Dokploy dashboard using `https://github.com/hadifarajvand/mcp-hub.git`

## Support

For issues during testing:
1. Check logs: `docker compose -f docker-compose.test.yml logs`
2. Verify ports are available: `netstat -an | grep 800`
3. Restart services: `docker compose -f docker-compose.test.yml restart`
4. Clean and rebuild: `docker compose -f docker-compose.test.yml down -v && docker compose -f docker-compose.test.yml up --build`
