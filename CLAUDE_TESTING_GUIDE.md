# Testing MCP Hub with Claude AI

Complete guide to test the MCPs with Claude and create a Dokploy project.

## Prerequisites

✓ All MCPs running locally:
- Transcriber: http://localhost:8002
- Google Workspace: http://localhost:8001
- Dokploy: http://localhost:8003

## Step 1: Add MCPs to Claude Desktop

### 1.1 Open Claude Desktop Settings
- Click **Settings** (gear icon)
- Navigate to **MCP Servers** tab

### 1.2 Add Transcriber MCP
- Click **Add Server**
- **Name**: `Transcriber`
- **Type**: `HTTP`
- **URL**: `http://localhost:8002`
- Click **Save**

### 1.3 Add Google Workspace MCP
- Click **Add Server**
- **Name**: `Google Workspace`
- **Type**: `HTTP`
- **URL**: `http://localhost:8001`
- Click **Save**

### 1.4 Add Dokploy MCP
- Click **Add Server**
- **Name**: `Dokploy`
- **Type**: `HTTP`
- **URL**: `http://localhost:8003`
- Click **Save**

### 1.5 Verify Connection
After adding all three, you should see them in the MCP Servers list with **✓ Connected** status.

---

## Step 2: Test Transcriber MCP in Claude

### Test 1: List Languages
In Claude Chat, type:
```
@transcriber What languages do you support for transcription?
```

**Expected Response**:
Claude will show 21+ supported languages including English, Spanish, French, German, Italian, Portuguese, Russian, Japanese, Korean, Chinese, Arabic, Hindi, Thai, Turkish, Dutch, Polish, Vietnamese, etc.

### Test 2: Transcribe Audio (Test)
Type:
```
@transcriber I have an audio file at /home/user/meeting.wav in Portuguese. Can you transcribe it?
```

**Expected Response**:
Claude will respond with something like: "I'll transcribe your Portuguese audio file. The service supports Portuguese and will extract the speech..."

---

## Step 3: Test Google Workspace MCP in Claude

### Test 1: Show Available Tools
Type:
```
@google-workspace What tools and services do you have available?
```

**Expected Response**:
Claude will list: Docs, Sheets, Slides, Drive, Gmail, Calendar

### Test 2: Try Accessing Docs
Type:
```
@google-workspace Can you access my Google Docs?
```

**Expected Response**:
In test mode: "Requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET"
In production: Would prompt for OAuth authentication

---

## Step 4: Test Dokploy MCP in Claude

### Test 1: List Available Tools
Type:
```
@dokploy What can you do?
```

**Expected Response**:
Claude will list: list-projects, list-services, deploy, logs, status

### Test 2: List Projects
Type:
```
@dokploy Show me all my current projects
```

**Expected Response**:
In test mode: "Requires DOKPLOY_URL and DOKPLOY_API_KEY"

---

## Step 5: Create a Dokploy Project (Production Setup)

To actually create a Dokploy project, you need to:

### 5.1 Set Environment Variables
First, update the Dokploy MCP with your actual credentials:

**In docker-compose.yml, update Dokploy service**:
```yaml
dokploy:
  environment:
    - DOKPLOY_URL=http://your-dokploy-instance.com
    - DOKPLOY_API_KEY=your-actual-api-key
```

Then restart:
```bash
docker compose restart dokploy
```

### 5.2 Use Claude to Deploy
Once configured, type in Claude:
```
@dokploy Create a new project called "my-app" and deploy it
```

Claude will use the Dokploy MCP to:
1. Call the `/deploy` endpoint
2. Create the project in your Dokploy instance
3. Return the deployment status

### 5.3 Check Deployment Status
Type:
```
@dokploy What's the status of my deployment?
```

Claude will call the `/status` endpoint and report back.

---

## Full Testing Scenario

### Scenario: Transcribe a Meeting & Deploy Documentation

**In Claude, you could do**:

```
I have a 30-minute meeting recording in Spanish that I need transcribed.
Then I want to save the transcript to Google Drive and create a deployment
for the documentation in Dokploy.

@transcriber transcribe this Spanish audio: /recordings/meeting.mp3

@google-workspace Save the transcript to Drive in a folder called "Meetings"

@dokploy Create a deployment for our docs site called "docs-2024"
```

**What would happen**:
1. Transcriber would transcribe the Spanish audio
2. Google Workspace would save to Drive
3. Dokploy would create and deploy the project

---

## Troubleshooting

### MCP Not Connecting
```
Error: Cannot connect to http://localhost:8002
```

**Solution**:
1. Verify service is running: `docker compose ps`
2. Test manually: `curl http://localhost:8002/health`
3. Restart Claude Desktop
4. Try re-adding the MCP

### Tool Not Showing Up
If `@transcriber` doesn't autocomplete:
1. Check MCP shows as "Connected" in settings
2. Restart Claude Desktop
3. Try referencing by full name: `@Transcriber`

### Missing Credentials
Response: "Requires GOOGLE_OAUTH_CLIENT_ID..." or "Requires DOKPLOY_API_KEY..."

**Solution**: For production use, set environment variables:
```bash
docker compose down
# Edit docker-compose.yml with your credentials
docker compose up -d
```

---

## Advanced: Multiple Requests in One Chat

You can chain multiple MCP calls:

```
I need to:
1. Transcribe this French video
2. Save transcripts to Google Drive
3. Deploy the docs site

@transcriber transcribe_video /videos/presentation.mp4 language=fr

Once done, @google-workspace create a folder "Presentations" and save the transcript

Then @dokploy deploy the docs site with the new content
```

Claude will intelligently sequence these calls.

---

## Monitoring MCP Activity

Watch live logs while testing:

```bash
docker compose logs -f transcriber
docker compose logs -f google-workspace  
docker compose logs -f dokploy
```

You'll see each API call as Claude uses the MCPs.

---

## Expected Behavior by Environment

### Local Testing (Current)
- Transcriber: ✓ Works (returns languages, expects Google credentials for actual transcription)
- Google Workspace: ✓ Works (returns tools available, needs OAuth for actual access)
- Dokploy: ✓ Works (returns available operations, needs credentials to actually deploy)

### Production (After Dokploy Deployment)
- Transcriber: ✓ Full transcription with Google Cloud credentials
- Google Workspace: ✓ Full OAuth-authenticated access
- Dokploy: ✓ Full deployment capabilities with actual Dokploy API

---

## Success Indicators

✅ MCPs show as "Connected" in Claude settings
✅ Claude autocompletes `@transcriber`, `@google-workspace`, `@dokploy`
✅ Tools appear when you ask "What can you do?"
✅ Endpoints respond with proper JSON (even if test mode messages)
✅ Claude can reference the tools and understand their capabilities

---

## Next Steps

1. **Test Basic Connectivity**: Add one MCP and ask it a simple question
2. **Test Each Tool**: Run through the test scenarios above
3. **Monitor Logs**: Watch the Docker logs to see API calls in real-time
4. **Prepare Production**: Set up credentials for actual Dokploy deployment
5. **Go Live**: Deploy to Dokploy server with production credentials

---

## Support

If you encounter issues:
1. Check Docker logs: `docker compose logs`
2. Test endpoints manually: `curl http://localhost:8002/health`
3. Verify Claude can see MCPs: Check Settings → MCP Servers
4. Restart Claude Desktop: Close and reopen

For detailed integration guide: See `CLAUDE_CHATGPT_INTEGRATION.md`
