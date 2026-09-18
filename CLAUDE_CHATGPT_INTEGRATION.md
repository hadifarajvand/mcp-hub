# Claude & ChatGPT Integration Guide

Complete guide for connecting MCP Hub to Claude AI and ChatGPT.

## Table of Contents
1. [Claude Integration](#claude-integration)
2. [ChatGPT Integration](#chatgpt-integration)
3. [API Specifications](#api-specifications)
4. [Testing & Verification](#testing--verification)

---

## Claude Integration

### Method 1: Claude Desktop / Claude Code (Native MCP Support)

Claude has native support for HTTP-based MCPs. This is the **recommended method**.

#### Step 1: Get Service URLs

For **local testing**:
```
Transcriber:     http://localhost:8002
Google Workspace: http://localhost:8001
Dokploy:         http://localhost:8003
```

For **production (Dokploy)**:
```
Transcriber:     https://mcp.yourdomain.com/transcriber
Google Workspace: https://mcp.yourdomain.com/google-workspace
Dokploy:         https://mcp.yourdomain.com/dokploy
```

#### Step 2: Add to Claude Desktop

1. **Open Claude Desktop Settings**
2. **MCP Servers tab**
3. **Click "Add Server"**
4. **Enter:**
   - **Name**: `Transcriber`
   - **Type**: `HTTP`
   - **URL**: `http://localhost:8002` (or production URL)

5. **Repeat for Google Workspace and Dokploy**

#### Step 3: Verify Connection

In Claude Desktop:
```
@transcriber list all supported languages
```

Or:
```
@google-workspace show available tools
```

### Method 2: Claude Code (CLI)

Add MCPs via command line:

```bash
claude mcp add transcriber http http://localhost:8002
claude mcp add google-workspace http http://localhost:8001
claude mcp add dokploy http http://localhost:8003
```

### Method 3: Claude via config file

Edit `~/.claude/mcp_config.json`:

```json
{
  "mcps": [
    {
      "name": "transcriber",
      "type": "http",
      "url": "http://localhost:8002"
    },
    {
      "name": "google-workspace",
      "type": "http",
      "url": "http://localhost:8001"
    },
    {
      "name": "dokploy",
      "type": "http",
      "url": "http://localhost:8003"
    }
  ]
}
```

### Claude Usage Examples

Once connected, you can:

```
User: @transcriber Can you transcribe this Portuguese audio?
Claude: I'll use the transcriber MCP to transcribe Portuguese audio...

User: @google-workspace List my recent Google Drive files
Claude: I'll access your Google Workspace files...

User: @dokploy Show me all current deployments
Claude: I'll check your Dokploy projects...
```

---

## ChatGPT Integration

ChatGPT doesn't natively support MCP, but you can integrate via:

### Method 1: OpenAI Actions (Custom GPTs)

Create a Custom GPT that uses our REST API:

#### Step 1: Get OpenAPI Schema

We provide OpenAPI 3.0 schemas:

- **Transcriber**: `servers/transcriber/openapi.json`
- **Google Workspace**: `servers/google-workspace/openapi.json`
- **Dokploy**: `servers/dokploy/openapi.json`

#### Step 2: Create Custom GPT

1. **Go to**: https://chat.openai.com/gpts/editor
2. **Configure → Actions**
3. **Create new action**
4. **Import schema** from one of our OpenAPI specs
5. **Set authentication** (if needed):
   - For **Google Workspace**: OAuth 2.0
   - For **Dokploy**: Bearer Token
   - For **Transcriber**: No auth

#### Step 3: Example Custom GPT Names

- **"Transcriber Pro"** - Uses Transcriber MCP
- **"Google Workspace Assistant"** - Uses Google Workspace MCP
- **"Dokploy Manager"** - Uses Dokploy MCP

### Method 2: OpenAI Plugin (Deprecated but still works)

Create `ai-plugin.json` in your MCP service root:

```json
{
  "schema_version": "v1",
  "name_for_human": "Transcriber",
  "name_for_model": "transcriber",
  "description_for_human": "Transcribe audio and video files using Google Cloud Speech-to-Text",
  "description_for_model": "Plugin for transcribing audio and video files. Supports 20+ languages.",
  "auth": {
    "type": "none"
  },
  "api": {
    "type": "openapi",
    "url": "http://localhost:8002/openapi.json"
  },
  "logo_url": "https://example.com/logo.png",
  "contact_email": "support@example.com",
  "legal_info_url": "https://example.com/legal"
}
```

Host at: `http://yourserver.com/.well-known/ai-plugin.json`

### Method 3: REST API Direct Integration

Use ChatGPT's Code Interpreter to call our APIs:

```python
import requests
import json

# Transcribe audio
response = requests.post(
    'http://localhost:8002/transcribe_audio',
    json={
        'file_path': '/path/to/audio.wav',
        'language': 'en'
    }
)

transcript = response.json()['transcript']
print(f"Transcribed: {transcript}")
```

---

## API Specifications

### Transcriber API

**Base URL**: `http://localhost:8002` or `https://mcp.yourdomain.com/transcriber`

**Endpoints**:

#### POST /transcribe_audio
```bash
curl -X POST http://localhost:8002/transcribe_audio \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/path/to/audio.wav",
    "language": "en"
  }'
```

**Response**:
```json
{
  "transcript": "Hello world",
  "success": true,
  "confidence": 0.95
}
```

#### POST /transcribe_video
```bash
curl -X POST http://localhost:8002/transcribe_video \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/path/to/video.mp4",
    "language": "en"
  }'
```

#### POST /list_supported_languages
```bash
curl -X POST http://localhost:8002/list_supported_languages \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response**:
```json
{
  "languages": {
    "en": "English",
    "pt-BR": "Portuguese (Brazil)",
    "ja": "Japanese",
    ...
  },
  "count": 21
}
```

#### GET /health
```bash
curl http://localhost:8002/health
```

**Response**:
```json
{
  "status": "ok",
  "service": "transcriber-mcp"
}
```

### Google Workspace API

**Base URL**: `http://localhost:8001` or `https://mcp.yourdomain.com/google-workspace`

**Endpoints** (all require OAuth 2.0 authentication):

- `POST /docs` - Access Google Docs
- `POST /sheets` - Access Google Sheets
- `POST /slides` - Access Google Slides
- `POST /drive` - Access Google Drive
- `POST /gmail` - Access Gmail
- `POST /calendar` - Access Google Calendar
- `GET /health` - Health check
- `GET /` - Service info

### Dokploy API

**Base URL**: `http://localhost:8003` or `https://mcp.yourdomain.com/dokploy`

**Endpoints** (all require DOKPLOY_API_KEY):

- `POST /list-projects` - List Dokploy projects
- `POST /list-services` - List services
- `POST /deploy` - Deploy project
- `POST /logs` - Get logs
- `POST /status` - Check status
- `GET /health` - Health check
- `GET /` - Service info

---

## Testing & Verification

### Test with Claude

```bash
# In Claude Desktop or Code:
@transcriber Can you list the supported languages?
@google-workspace What tools are available?
@dokploy Show current deployments
```

### Test with ChatGPT (via Code Interpreter)

```python
import requests

# Test all services
services = {
    'transcriber': 'http://localhost:8002',
    'google-workspace': 'http://localhost:8001',
    'dokploy': 'http://localhost:8003'
}

for name, url in services.items():
    health = requests.get(f'{url}/health')
    print(f"{name}: {health.status_code} - {health.json()}")
```

### Test with cURL

```bash
# Test Transcriber
curl http://localhost:8002/health

# Test Google Workspace
curl http://localhost:8001/

# Test Dokploy
curl http://localhost:8003/
```

---

## Authentication Setup

### Google Workspace OAuth

For production Claude/ChatGPT access:

1. **Create OAuth 2.0 credentials** in Google Cloud Console
2. **Set authorization URI**: `https://accounts.google.com/o/oauth2/v2/auth`
3. **Set token URI**: `https://oauth2.googleapis.com/token`
4. **Set scopes**:
   - `https://www.googleapis.com/auth/documents`
   - `https://www.googleapis.com/auth/spreadsheets`
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar`

### Dokploy API Key

1. **Generate in Dokploy dashboard**: Settings → API Keys
2. **Add to request header**: `Authorization: Bearer YOUR_API_KEY`

### Transcriber (No Auth Required)

The Transcriber MCP works without authentication but requires:
- `GOOGLE_APPLICATION_CREDENTIALS` (for actual transcription)

---

## Best Practices

### For Claude Integration

✅ Use native MCP support (HTTP transport)  
✅ Add multiple MCPs for different services  
✅ Use descriptive names  
✅ Test with `@mcp_name command` syntax  

### For ChatGPT Integration

✅ Use OpenAI Actions for Custom GPTs  
✅ Provide clear OpenAPI schemas  
✅ Set up proper authentication  
✅ Document all available operations  

### General

✅ Use HTTPS in production  
✅ Implement proper rate limiting  
✅ Monitor API usage  
✅ Keep credentials secure  
✅ Test all endpoints before deployment  

---

## Troubleshooting

### Claude can't connect to MCP

```bash
# Check if service is running
curl http://localhost:8002/health

# Verify MCP configuration
cat ~/.claude/mcp_config.json

# Restart Claude Desktop
```

### ChatGPT OpenAI Action fails

1. **Verify OpenAPI schema**: Validate at https://editor.swagger.io/
2. **Check authentication**: Ensure credentials are correctly configured
3. **Test endpoint**: Use cURL to test API directly
4. **Check CORS**: Ensure CORS headers are present

### Services not responding

```bash
# Check Docker services
docker compose -f docker-compose.test.yml ps

# View logs
docker compose -f docker-compose.test.yml logs -f transcriber

# Restart services
docker compose -f docker-compose.test.yml restart
```

---

## Example Workflows

### Claude: Transcribe & Summarize

```
User: I have an hour-long Portuguese interview. Can you transcribe it and summarize the key points?

Claude: I'll help with that. Let me:
1. Use @transcriber to transcribe the audio in Portuguese
2. Summarize the transcribed text
3. Extract key points
```

### ChatGPT: Deploy & Monitor

```
User: Deploy my latest changes to Dokploy and show me the status

ChatGPT: Using the Dokploy API, I'll:
1. Trigger the deployment
2. Monitor the logs
3. Verify the new status
```

### Both: Multi-Service Workflow

```
1. Transcribe meeting recording (Transcriber)
2. Store in Google Drive (Google Workspace)
3. Deploy updated docs (Dokploy)
4. Send calendar reminder (Google Workspace)
```

---

## Support & Documentation

- **OpenAPI Schemas**: `servers/*/openapi.json`
- **Local Testing**: `LOCAL_TESTING.md`
- **Deployment**: `DEPLOYMENT_STATUS.md`
- **GitHub**: `https://github.com/hadifarajvand/mcp-hub`

For issues or questions, see the GitHub repository documentation.
