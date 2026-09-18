# Claude + Dokploy MCP Demo

## Simulated Conversation: Creating a Dokploy Project via Claude

This shows what a real conversation with Claude using the Dokploy MCP would look like.

---

## Demo Scenario 1: Simple Project Deployment

### User Message (in Claude Chat):
```
@dokploy Create a new project called "my-website" and show me the deployment status
```

### What Happens Behind the Scenes:

1. **Claude recognizes the @dokploy MCP**
   - Sends request to: `http://localhost:8003`
   - Available tools: list-projects, list-services, deploy, logs, status

2. **Claude calls the deploy tool**
   ```json
   POST /deploy
   {
     "project_name": "my-website"
   }
   ```

3. **Claude receives response**:
   ```json
   {
     "message": "Requires DOKPLOY_URL and DOKPLOY_API_KEY",
     "error": "Not configured for mock testing"
   }
   ```

### Claude's Response to You:
```
I can help you deploy a project! However, I need you to configure 
the Dokploy MCP with your credentials first.

To enable this, please:

1. Update your docker-compose.yml with:
   - DOKPLOY_URL: Your Dokploy instance URL
   - DOKPLOY_API_KEY: Your API key from Dokploy dashboard

2. Restart the services:
   docker compose restart

Once configured, I can:
- Create new projects
- Deploy applications
- View deployment logs
- Check deployment status

Would you like me to explain how to get your API key?
```

---

## Demo Scenario 2: What It Would Look Like in Production

### User Message (After Configuring with Real Credentials):
```
@dokploy Create a production deployment for my app
```

### What Happens:

1. **Claude calls deploy endpoint**
   ```json
   POST /deploy
   {
     "project": "my-app",
     "environment": "production"
   }
   ```

2. **Dokploy MCP (with real credentials) responds**:
   ```json
   {
     "success": true,
     "project_id": "proj_abc123xyz",
     "project_name": "my-app",
     "status": "deploying",
     "deployment_url": "https://my-app.yourdomain.com",
     "message": "Deployment started successfully"
   }
   ```

3. **Claude's Response**:
   ```
   ✅ Deployment Created!

   Project: my-app
   Project ID: proj_abc123xyz
   Status: Deploying
   URL: https://my-app.yourdomain.com

   Your application is now deploying. I can check the status for you 
   if you'd like, or view the deployment logs.

   What would you like to do next?
   ```

---

## Demo Scenario 3: Multi-Step Workflow

### User Message:
```
I need to:
1. Deploy my new website version
2. Check the deployment status
3. Show me the logs

@dokploy Handle this for me
```

### Claude's Actions:

**Step 1: Deploy**
```
POST /deploy
→ Returns deployment ID and status
```

**Step 2: Check Status**
```
POST /status
→ Returns current deployment status
```

**Step 3: Get Logs**
```
POST /logs
→ Returns deployment logs
```

### Claude's Response:
```
🚀 Deployment Workflow Complete

Step 1: Deployment
✅ Status: Deploying
   URL: https://website.example.com
   Deployment ID: deploy_xyz789

Step 2: Current Status
✅ Progress: 65% complete
   Build: ✓ Succeeded
   Tests: ✓ Passed
   Deploy: In Progress

Step 3: Recent Logs
   12:34:56 - Starting deployment
   12:35:02 - Building Docker image
   12:35:45 - Image built successfully
   12:36:10 - Deploying to production
   12:36:32 - Deployment 65% complete

Your deployment is running smoothly. I'll be here if you need to 
check status again or view full logs.
```

---

## Demo Scenario 4: Error Handling

### User Message:
```
@dokploy Deploy my app to staging
```

### Claude Detects Missing Configuration:
```
❌ Configuration Required

I found the Dokploy MCP, but it's not fully configured yet.

To deploy your app, I need:
1. DOKPLOY_URL - Your Dokploy instance address
2. DOKPLOY_API_KEY - Your API key

Once you configure these, I can:
✓ Create and deploy projects
✓ List all your projects
✓ View deployment status
✓ Check logs
✓ Manage services

Steps:
1. Get your API key: Dokploy Dashboard → Settings → API Keys
2. Update docker-compose.yml with your credentials
3. Restart: docker compose restart
4. Try again

Would you like help with any of these steps?
```

---

## Real-World Use Cases

### Use Case 1: Deploy After Code Commit
```
I just pushed new code. Can you deploy the latest version?

@dokploy Deploy the main branch to production
```

Claude would:
- Call `/deploy` with your latest code
- Monitor the deployment
- Report success or errors

### Use Case 2: Rollback After Issues
```
The deployment had issues. Can you roll back to the previous version?

@dokploy Rollback to the last successful deployment
```

Claude would:
- Check deployment history with `/status`
- Identify the last stable deployment
- Roll back if supported
- Show you the new status

### Use Case 3: Monitor Multiple Deployments
```
I have 3 microservices. Can you check their deployment status?

@dokploy Check status of: api-service, web-app, worker-service
```

Claude would:
- Call `/status` for each service
- Compare deployment versions
- Alert you to any issues

### Use Case 4: Troubleshoot Deployment Failures
```
Deployment failed. What went wrong?

@dokploy Show me the logs from the last failed deployment
```

Claude would:
- Call `/logs`
- Analyze the logs
- Identify the failure reason
- Suggest fixes

---

## Integration with Other MCPs

### Combined Workflow Example:

```
I have a new video tutorial that needs:
1. Transcription in 5 languages
2. Upload to Google Drive
3. Deploy the tutorial site

@transcriber Transcribe video_tutorial.mp4 in: English, Spanish, 
French, German, Portuguese

@google-workspace Create folder "Tutorials/2024" and save all 
transcripts there

@dokploy Deploy the tutorial site with the new content
```

Claude orchestrates all three MCPs:
1. **Transcriber**: Transcribes video in all 5 languages
2. **Google Workspace**: Saves transcripts to Drive
3. **Dokploy**: Deploys updated site with new tutorials

---

## Testing Checklist

Before going to production, verify:

- [ ] All three MCPs show "Connected" in Claude Desktop settings
- [ ] `@transcriber`, `@google-workspace`, `@dokploy` autocomplete
- [ ] Can list tools for each MCP
- [ ] Error messages are clear (test mode messages)
- [ ] Docker logs show API calls as Claude makes them
- [ ] Response times are <200ms
- [ ] JSON responses are valid

---

## Getting Your Dokploy Credentials

### Step 1: Access Dokploy Dashboard
- URL: Your Dokploy instance
- Login with your credentials

### Step 2: Generate API Key
1. Navigate to: **Settings** → **API Keys**
2. Click: **Generate New API Key**
3. Copy the key (it won't be shown again!)

### Step 3: Get Your Instance URL
- Format: `https://dokploy.yourdomain.com` or `http://dokploy.local`
- This is your DOKPLOY_URL

### Step 4: Configure MCP
```yaml
# docker-compose.yml
dokploy:
  environment:
    - DOKPLOY_URL=https://dokploy.yourdomain.com
    - DOKPLOY_API_KEY=your_api_key_here
```

### Step 5: Restart
```bash
docker compose down
docker compose up -d
```

---

## What You Get

Once configured, Claude can:

✅ **Deploy projects** - Create and deploy new applications  
✅ **Manage services** - List and manage microservices  
✅ **Monitor status** - Real-time deployment status  
✅ **View logs** - Access deployment logs for debugging  
✅ **Track history** - See deployment history  
✅ **Troubleshoot** - Get Claude's analysis of issues  

---

## Success Indicators

You'll know it's working when:

1. Claude responds with actual deployment information (not error messages)
2. You see deployment IDs and URLs in Claude's responses
3. Deployment logs appear when requested
4. Status shows "Deploying" or "Success"
5. Docker logs show successful API calls

---

## Support & Documentation

- Full Integration Guide: `CLAUDE_CHATGPT_INTEGRATION.md`
- Setup Instructions: `SETUP_CLAUDE_CHATGPT.md`
- Testing Guide: `CLAUDE_TESTING_GUIDE.md`
- API Specs: `servers/dokploy/openapi.json`

---

## Summary

The Dokploy MCP with Claude gives you natural-language deployment control:

```
Instead of:  docker compose logs | grep error

You can ask:  @dokploy Why did the last deployment fail?
```

Claude handles the technical details and reports back in plain English.

Ready to test? Start with the setup guide above! 🚀
