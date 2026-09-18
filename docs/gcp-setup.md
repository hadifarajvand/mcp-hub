# Google Cloud Setup for Transcriber MCP

Complete guide to configure Google Cloud credentials for the Transcriber MCP (Google Speech-to-Text).

## Overview

The Transcriber MCP uses Google Cloud Speech-to-Text API to convert audio and video to text. You'll need a Google Cloud service account with appropriate permissions.

## Step 1: Create Google Cloud Project (if needed)

If you already created a project for OAuth (Google Workspace), you can reuse it or create a separate one.

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown
3. Click **New Project**
4. Name: "MCP Hub Transcriber" (or reuse existing)
5. Click **Create**

## Step 2: Enable Speech-to-Text API

1. Go to **APIs & Services** → **Library**
2. Search for **Cloud Speech-to-Text API**
3. Click it
4. Click **Enable**
5. Wait for confirmation

## Step 3: Create Service Account

Service accounts allow the MCP to authenticate without user interaction.

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **Service Account**
3. Fill in:
   - Service account name: "mcp-transcriber"
   - Service account ID: (auto-filled)
   - Description: "MCP hub transcriber service"
4. Click **Create and Continue**
5. Grant roles:
   - Select **Cloud Speech-to-Text Client** role
   - Or search for and select: `roles/speech.client`
6. Click **Continue**
7. Click **Done**

## Step 4: Create Service Account Key

1. Go to **APIs & Services** → **Credentials**
2. Under **Service Accounts**, click the newly created account (`mcp-transcriber@...`)
3. Go to the **Keys** tab
4. Click **Add Key** → **Create new key**
5. Type: **JSON**
6. Click **Create**
7. A JSON file downloads automatically

## Step 5: Configure MCP Hub

1. Save the downloaded JSON file securely (e.g., `google-credentials.json`)

2. Edit `servers/transcriber/.env`:

```bash
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

3. Update `docker-compose.yml` to mount the credentials:

Edit the `transcriber` service in `docker-compose.yml`:

```yaml
transcriber:
  build:
    context: ./servers/transcriber
    dockerfile: Dockerfile
  container_name: mcp-transcriber
  env_file:
    - ./servers/transcriber/.env
  ports:
    - "8002:8000"
  volumes:
    - transcriber-cache:/app/cache
    - ./google-credentials.json:/app/credentials.json:ro  # Add this line
  environment:
    - MCP_HTTP_PORT=8000
    - MCP_HOST=0.0.0.0
  # ... rest of config
```

4. (Local dev only) Copy JSON to root of mcp-hub:

```bash
cp ~/Downloads/mcp-transcriber-*.json ./google-credentials.json
```

## Step 6: Set Up Billing

Google Cloud APIs require billing to be enabled:

1. Go to **Billing**
2. Click **Create Account** (if you don't have one)
3. Add a payment method
4. Link the billing account to your project

Speech-to-Text has a free tier: **60 minutes per month** (auto-renewable). Production usage is charged per minute.

See [Speech-to-Text Pricing](https://cloud.google.com/speech-to-text/pricing).

## Step 7: Test

1. Start the MCP hub:
   ```bash
   docker compose up --build
   ```

2. Test transcription:
   ```bash
   # Via Claude Code
   claude list-tools  # Should see transcribe_audio, transcribe_video, list_supported_languages
   
   # Or directly to the MCP
   curl http://localhost:8002/health
   ```

3. Try transcribing a sample file:
   ```bash
   # Download a sample audio file
   wget https://www.w3schools.com/html/horse.mp3 -O sample.mp3
   
   # Use Claude to transcribe
   # "Please transcribe this audio file: /path/to/sample.mp3"
   ```

## Billing Alerts

To avoid unexpected charges, set up billing alerts:

1. Go to **Billing** → **Budgets**
2. Click **Create Budget**
3. Set budget amount (e.g., $10/month)
4. Add alert thresholds (e.g., 50%, 100%)
5. Set notification email
6. Click **Create Budget**

## Service Account Security

**Do NOT commit `google-credentials.json` to Git!**

1. Add to `.gitignore`:
   ```
   google-credentials.json
   ```

2. For Dokploy deployment:
   - Use Dokploy's **Secrets** feature to store the JSON securely
   - Or mount as a volume from a secrets manager

3. Rotate keys periodically:
   - Delete old key in **Service Accounts** → **Keys**
   - Create new key
   - Update environment variable

## Transcription Quotas & Limits

Google Speech-to-Text has these limits (per [documentation](https://cloud.google.com/speech-to-text/quotas)):

| Limit | Value |
|-------|-------|
| Max file size (long-running) | Unlimited (up to 480 hours) |
| Max file size (synchronous) | 500 MB |
| Max audio length (free tier) | 60 min/month |
| Concurrent requests | 100+ (depends on tier) |
| Supported formats | MP3, WAV, FLAC, OGG, M4A, and 15+ others |
| Supported languages | 100+ |

## Troubleshooting

### "Permission denied" when starting transcriber

- Verify `GOOGLE_APPLICATION_CREDENTIALS` path is correct
- Ensure JSON file is readable by Docker container
- Check service account has **Cloud Speech-to-Text Client** role

### "Invalid API key" or "API_KEY_INVALID"

- Service account credentials are not API keys
- Ensure you're using a **service account JSON**, not an API key
- Re-download the JSON from service account **Keys** tab

### "Usage limit exceeded" error

- You've exceeded the free tier (60 min/month)
- Billing must be enabled; add a payment method
- Or delete the project and create a new one next month

### Transcription takes a long time

- Large files (1+ GB) may take several minutes
- The MCP timeout is 300 seconds by default (adjust in `.env` if needed)
- Google Cloud may queue requests during high usage

### "Failed to extract audio from video"

- Ensure `ffmpeg` is installed in the Transcriber container
- Dockerfile includes `ffmpeg` by default
- Check video file format is supported by ffmpeg

## Advanced: Multiple Projects or Accounts

To use different projects for different MCPs:

1. Create separate service accounts in different projects
2. In Dokploy, set different `GOOGLE_APPLICATION_CREDENTIALS` paths per service
3. Or use separate Docker Compose files per deployment

## Support

- [Google Cloud Speech-to-Text Documentation](https://cloud.google.com/speech-to-text/docs)
- [Google Cloud Service Accounts](https://cloud.google.com/iam/docs/service-accounts)
- [Speech-to-Text API Reference](https://cloud.google.com/speech-to-text/docs/reference)
- [Supported Languages](https://cloud.google.com/speech-to-text/docs/languages)
