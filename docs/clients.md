# Connecting to MCP Hub Servers

Guide to setting up Claude Code, Claude Desktop, and other MCP clients to use the MCP hub servers.

## Claude Code (CLI)

### Local Development Setup

Once the MCP hub is running locally (`docker compose up`), add servers to Claude Code:

```bash
# Add Google Workspace MCP
claude mcp add --transport http google-workspace http://localhost:8001

# Add Transcriber MCP
claude mcp add --transport http transcriber http://localhost:8002

# Add Dokploy MCP
claude mcp add --transport http dokploy http://localhost:8003

# List all configured MCPs
claude mcp list

# Verify tools are available in a claude session
claude list-tools
```

### Remote Deployment (Dokploy)

Once deployed on Dokploy behind a domain (e.g., `mcp.yourdomain.com`):

```bash
# Add Google Workspace MCP (remote)
claude mcp add --transport http google-workspace https://mcp.yourdomain.com/google-workspace

# Add Transcriber MCP (remote)
claude mcp add --transport http transcriber https://mcp.yourdomain.com/transcriber

# Add Dokploy MCP (remote)
claude mcp add --transport http dokploy https://mcp.yourdomain.com/dokploy

# Optional: If MCP bearer token is enabled, pass Authorization header
claude mcp add --transport http dokploy https://mcp.yourdomain.com/dokploy --bearer-token "your-token-here"
```

## Claude Desktop

### Prerequisites

- Claude Desktop app (download from [claude.ai](https://claude.ai))
- MCP hub running locally or accessible via HTTPS

### Configuration

Claude Desktop reads MCP configuration from `claude_desktop_config.json`:

**macOS / Linux**: `~/.claude/claude_desktop_config.json`

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json` or `C:\Users\<YourUsername>\AppData\Roaming\Claude\claude_desktop_config.json`

#### Local Development Example

```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "curl",
      "args": ["--http1.1", "http://localhost:8001"],
      "env": {}
    },
    "transcriber": {
      "command": "curl",
      "args": ["--http1.1", "http://localhost:8002"],
      "env": {}
    },
    "dokploy": {
      "command": "curl",
      "args": ["--http1.1", "http://localhost:8003"],
      "env": {}
    }
  }
}
```

#### Remote Deployment Example

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
      "env": {
        "MCP_BEARER_TOKEN": "your-optional-bearer-token"
      }
    }
  }
}
```

**Note**: Claude Desktop uses `curl` for HTTP transport. Ensure `curl` is available on your system PATH.

### After Updating Config

1. Restart Claude Desktop completely
2. Wait ~10 seconds for MCPs to connect
3. Start a new conversation to load the new MCPs
4. MCPs appear in the tool picker when you start typing

## Testing MCP Connections

### Quick Health Check

```bash
# Test each MCP endpoint
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health

# For remote:
curl https://mcp.yourdomain.com/google-workspace/health
curl https://mcp.yourdomain.com/transcriber/health
curl https://mcp.yourdomain.com/dokploy/health
```

### Verify Tools in Claude

Once connected, ask Claude about available tools:

```
@claude "What tools do you have access to?"
```

Expected response includes:
- **Google Workspace**: list_files, create_doc, update_sheet, send_email, create_calendar_event, etc.
- **Transcriber**: transcribe_audio, transcribe_video, list_supported_languages
- **Dokploy**: deploy_application, create_database, list_projects, create_backup, etc.

## Troubleshooting

### MCP not appearing in Claude

1. **Check server is running**: `curl http://localhost:8001`
2. **Verify configuration syntax**: Ensure JSON in `claude_desktop_config.json` is valid
3. **Restart Claude**: Fully close and reopen Claude Desktop
4. **Check logs**: Claude Desktop logs are in:
   - **macOS/Linux**: `~/.claude/logs/`
   - **Windows**: `%APPDATA%\Claude\logs\`

### "Connection refused" error

- Verify port mapping in `docker-compose.yml`
- Ensure `docker compose up` succeeded (no startup errors)
- Try accessing the health endpoint directly: `curl http://localhost:8001/health`

### "Permission denied" for remote URLs

- Verify HTTPS certificate is valid (not self-signed)
- Check firewall allows outbound HTTPS to `mcp.yourdomain.com`
- Verify bearer token (if configured) is correct

### OAuth flow doesn't complete

- Check `GOOGLE_OAUTH_REDIRECT_URI` matches your deployment domain
- Ensure you can access the callback URL in your browser
- Check OAuth redirect URIs are configured correctly in Google Cloud Console

## Advanced: Bearer Token Authentication

For Dokploy MCP, set an additional authentication layer:

### Claude Code

```bash
claude mcp add --transport http dokploy https://mcp.yourdomain.com/dokploy \
  --bearer-token "super-secret-token-abc123"
```

### Claude Desktop

```json
{
  "mcpServers": {
    "dokploy": {
      "command": "curl",
      "args": [
        "--http1.1",
        "-H", "Authorization: Bearer super-secret-token-abc123",
        "https://mcp.yourdomain.com/dokploy"
      ],
      "env": {}
    }
  }
}
```

Generate a strong token:

```bash
openssl rand -base64 32
```

Then set in Dokploy environment: `MCP_BEARER_TOKEN=super-secret-token-abc123`

## Advanced: Custom MCP Client

For custom applications or agents, use any HTTP client to call the MCP servers:

```python
import requests

# Initialize connection
response = requests.post(
    "http://localhost:8001/message",
    json={
        "id": 1,
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "my-app", "version": "1.0"}
        }
    }
)

# List tools
response = requests.post(
    "http://localhost:8001/message",
    json={
        "id": 2,
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {}
    }
)

# Call a tool (example: list Google Drive files)
response = requests.post(
    "http://localhost:8001/message",
    json={
        "id": 3,
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "list_files",
            "arguments": {"folder_id": "root"}
        }
    }
)
```

See [MCP Specification](https://spec.modelcontextprotocol.io) for full protocol details.
