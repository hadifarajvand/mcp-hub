# Setup Guide: Connect to Claude AI & ChatGPT

Quick setup instructions for connecting MCP Hub to Claude AI (Desktop/Code) and ChatGPT.

## Quick Start

### For Claude Desktop Users (Fastest ⚡)

1. **Ensure services are running**:
   ```bash
   docker compose -f docker-compose.test.yml up -d
   ```

2. **Open Claude Desktop Settings**

3. **Go to: MCP Servers**

4. **Add Server for each MCP**:
   ```
   Name: Transcriber
   Type: HTTP
   URL: http://localhost:8002
   ```

5. **Repeat for**:
   - Name: `Google Workspace`, URL: `http://localhost:8001`
   - Name: `Dokploy`, URL: `http://localhost:8003`

6. **Test in Claude**:
   ```
   @transcriber list supported languages
   ```

---

## Setup for Claude Code

```bash
# Add MCPs via CLI
claude mcp add transcriber http http://localhost:8002
claude mcp add google-workspace http http://localhost:8001
claude mcp add dokploy http http://localhost:8003

# Verify connection
claude mcp list
```

---

## Setup for ChatGPT

### Option 1: Custom GPT with OpenAI Actions (Recommended)

1. **Go to**: https://chat.openai.com/gpts/editor

2. **Click "Create New GPT"**

3. **Name**: "MCP Transcriber Assistant"

4. **Instructions**:
   ```
   You are a helpful AI assistant with access to transcription services.
   You can transcribe audio and video files using the Transcriber API.
   Always ask for confirmation before transcribing files.
   Provide clear summaries of transcriptions.
   ```

5. **Configure → Actions → Create New**

6. **Paste OpenAPI Schema**:
   - Copy content from: `servers/transcriber/openapi.json`
   - Paste into "Schema" field

7. **Authentication**: Set to "None"

8. **Save Action**

9. **Test with**:
   ```
   "Can you list all supported languages for transcription?"
   ```

### Option 2: ChatGPT Code Interpreter

Use in ChatGPT with Code Interpreter enabled:

```python
import requests
import json

# Transcriber API
transcriber_url = "http://localhost:8002"

# Get languages
response = requests.post(
    f"{transcriber_url}/list_supported_languages",
    json={}
)
languages = response.json()
print(f"Available languages: {len(languages['languages'])}")

# Transcribe audio
transcribe_response = requests.post(
    f"{transcriber_url}/transcribe_audio",
    json={
        "file_path": "/path/to/audio.wav",
        "language": "en"
    }
)
result = transcribe_response.json()
print(f"Transcription: {result}")
```

### Option 3: Manual API Calls

In ChatGPT, ask it to make API calls:

```
I have an audio file at /path/to/recording.mp3 in Portuguese.
Can you help me transcribe it using the available transcription API?
The API is at http://localhost:8002
The endpoint POST /transcribe_audio accepts:
- file_path: string
- language: string (default "en")
```

---

## Production Setup (Dokploy)

After deploying to Dokploy:

### For Claude

1. **Update MCP Server URL**:
   ```
   URL: https://mcp.yourdomain.com/transcriber
   ```

2. **Set authentication if needed**:
   - For Google Workspace: Add OAuth credentials
   - For Dokploy: Add API Key

### For ChatGPT

1. **Update OpenAPI schema URL** in Custom GPT:
   ```
   https://mcp.yourdomain.com/transcriber/openapi.json
   ```

2. **Add authentication**:
   - Type: Bearer Token
   - Token: Your API key

---

## Testing Connectivity

### Test from Claude

```
@transcriber What languages do you support?

@google-workspace Tell me about your available tools

@dokploy Show my current deployments
```

### Test from ChatGPT

Create a new chat:
```
I'm testing an API integration. The endpoint is at http://localhost:8002/health.
Can you make a GET request to this endpoint and show me the response?
```

### Test with cURL

```bash
# Transcriber
curl http://localhost:8002/health

# Google Workspace
curl http://localhost:8001/

# Dokploy
curl http://localhost:8003/
```

---

## Common Issues & Solutions

### "Claude can't connect to MCP"

**Solution**:
```bash
# Verify service is running
curl http://localhost:8002/health

# Restart Claude Desktop
# Check ~/.claude/mcp_config.json exists

# If needed, re-add MCP server in settings
```

### "ChatGPT can't access the API"

**Solution**:
1. Verify service is running: `curl http://localhost:8002/health`
2. Check OpenAPI schema is valid: https://editor.swagger.io/
3. Ensure no CORS issues (test in browser)
4. Try without authentication first

### "Service returns 404"

**Solution**:
1. Check URL is correct in MCP configuration
2. Verify Docker service is running: `docker compose ps`
3. Check logs: `docker compose logs transcriber`

### "Slow response times"

**Solution**:
1. Check local network: `ping localhost`
2. Look for resource issues: `docker stats`
3. Ensure no background processes consuming CPU

---

## API Endpoints Reference

### Transcriber (http://localhost:8002)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Check service health |
| POST | `/transcribe_audio` | Transcribe audio file |
| POST | `/transcribe_video` | Transcribe video file |
| POST | `/list_supported_languages` | Get available languages |

### Google Workspace (http://localhost:8001)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Check service health |
| GET | `/` | Get service info |
| POST | `/docs` | Access Google Docs |
| POST | `/sheets` | Access Google Sheets |
| POST | `/drive` | Access Google Drive |
| POST | `/gmail` | Access Gmail |
| POST | `/calendar` | Access Google Calendar |

### Dokploy (http://localhost:8003)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Check service health |
| GET | `/` | Get service info |
| POST | `/list-projects` | List projects |
| POST | `/deploy` | Deploy project |
| POST | `/status` | Check status |

---

## Environment Variables

### For Local Testing
```bash
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
GOOGLE_CLOUD_CREDENTIALS=/path/to/credentials.json  # Optional for Transcriber
```

### For Production (Dokploy)

**Transcriber**:
```
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

**Google Workspace**:
```
GOOGLE_OAUTH_CLIENT_ID=your-client-id
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
GOOGLE_OAUTH_REDIRECT_URI=https://mcp.yourdomain.com/google-workspace/oauth/callback
```

**Dokploy**:
```
DOKPLOY_URL=https://your-dokploy-instance.com
DOKPLOY_API_KEY=your-api-key
```

---

## Example Conversations

### Claude: Transcription Task

```
User: I need to transcribe a French interview (2 minutes). 
Can you help?

Claude: I can help you transcribe that using the Transcriber MCP!
Let me use the @transcriber service to process your French audio.

What's the file path to your audio file?
```

### ChatGPT: Multi-step Workflow

```
User: I have a video with Portuguese dialogue. 
Transcribe it, then create a summary.

ChatGPT: I'll help with that! Let me:
1. Call the Transcriber API to transcribe the video in Portuguese
2. Process the transcript
3. Create a concise summary

Here's the API request I'll make...
```

---

## Next Steps

1. ✅ **Verify services running**: `docker compose ps`
2. ✅ **Test endpoints**: `curl http://localhost:8002/health`
3. ✅ **Add to Claude**: Settings → MCP Servers
4. ✅ **Create ChatGPT Custom GPT**: chat.openai.com/gpts/editor
5. ✅ **Test both integrations**
6. ✅ **Deploy to production**: Follow DEPLOYMENT_STATUS.md

---

## Support

- **Local Testing**: See `LOCAL_TESTING.md`
- **Deployment**: See `DEPLOYMENT_STATUS.md`
- **Full Integration Guide**: See `CLAUDE_CHATGPT_INTEGRATION.md`
- **GitHub**: https://github.com/hadifarajvand/mcp-hub

