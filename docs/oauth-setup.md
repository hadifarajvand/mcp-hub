# Google OAuth 2.0 Setup for Workspace MCP

Complete guide to configure Google OAuth credentials for the Google Workspace MCP.

## Overview

The Google Workspace MCP uses OAuth 2.0 to authenticate users and access their Google Workspace data. Each user grants permission once; tokens are refreshed automatically.

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown at the top
3. Click **New Project**
4. Enter project name (e.g., "MCP Hub Workspace")
5. Leave organization blank (or select yours)
6. Click **Create**
7. Wait for project to initialize (2-3 minutes)

## Step 2: Enable Required APIs

1. In Google Cloud Console, go to **APIs & Services** → **Library**
2. Search for and **enable** these APIs:
   - **Google Drive API**
   - **Google Docs API**
   - **Google Sheets API**
   - **Google Slides API**
   - **Gmail API**
   - **Google Calendar API**
   - **Google Tasks API** (optional)
   - **Google Meet API** (optional)
   - **Google Contacts API** (optional)

For each API:
- Click the API name
- Click **Enable**
- Wait for confirmation

## Step 3: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. If prompted, first click **Configure consent screen**:
   - User Type: Select **External** (or **Internal** if your org uses Google Workspace)
   - Fill in:
     - App name: "MCP Hub"
     - User support email: your email
     - Developer contact: your email
   - Click **Save and Continue**
   - Scopes: Add scopes manually (see below) or let the MCP request them
   - Click **Save and Continue** → **Back to Dashboard**

4. Now create the OAuth client ID:
   - Application type: **Web application**
   - Name: "MCP Hub Server"
   - Authorized JavaScript origins: Leave empty
   - Authorized redirect URIs: Add your callback URL:
     - **Local dev**: `http://localhost:8001/oauth/callback`
     - **Dokploy deployment**: `https://mcp.yourdomain.com/google-workspace/oauth/callback`
   - Click **Create**

5. Copy the credentials:
   - **Client ID**: Save this as `GOOGLE_OAUTH_CLIENT_ID`
   - **Client Secret**: Save this as `GOOGLE_OAUTH_CLIENT_SECRET`

## Step 4: Configure MCP Hub

1. Edit `servers/google-workspace/.env`:

```bash
GOOGLE_OAUTH_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-your-secret-here
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8001/oauth/callback  # For local dev
TOOL_TIER=docs,sheets,slides,drive,gmail,calendar
```

2. For Dokploy deployment, update `GOOGLE_OAUTH_REDIRECT_URI` to your domain:

```
GOOGLE_OAUTH_REDIRECT_URI=https://mcp.yourdomain.com/google-workspace/oauth/callback
```

## Step 5: First-Time OAuth Flow

1. Start the MCP hub:
   ```bash
   docker compose up
   ```

2. When Claude Code first calls a Google Workspace tool, it triggers OAuth:
   - The MCP opens a browser to Google's OAuth consent screen
   - User grants permission
   - Browser redirects to callback URL
   - Token is saved in Docker volume for future use

3. Subsequent calls use the saved token (auto-refreshed as needed)

## Scopes Explained

The MCP requests these scopes based on `TOOL_TIER`:

| Scope | Service | Permission |
|-------|---------|-----------|
| `https://www.googleapis.com/auth/drive` | Google Drive | Read/write files and folders |
| `https://www.googleapis.com/auth/docs` | Google Docs | Create/edit documents |
| `https://www.googleapis.com/auth/spreadsheets` | Google Sheets | Create/edit spreadsheets |
| `https://www.googleapis.com/auth/presentations` | Google Slides | Create/edit presentations |
| `https://www.googleapis.com/auth/gmail.modify` | Gmail | Read/send/manage emails |
| `https://www.googleapis.com/auth/calendar` | Google Calendar | Read/write calendar events |
| `https://www.googleapis.com/auth/tasks` | Google Tasks | Manage tasks |
| `https://www.googleapis.com/auth/drive.apps.readonly` | App Integration | List installed apps |

## Troubleshooting

### "Invalid client" error during OAuth

- Verify `GOOGLE_OAUTH_CLIENT_ID` matches Google Cloud Console
- Ensure the redirect URI exactly matches (protocol, domain, path)
- Check OAuth consent screen is configured

### "Access denied" after granting permission

- User may not have permission for requested services
- Check which APIs are enabled in Google Cloud Console
- Verify scopes match the user's permission level

### Token expired / "refresh_token_expired"

Tokens auto-refresh, but if user revokes access:
1. Delete the token file (usually in Docker volume)
2. Next MCP call will trigger OAuth flow again

### Redirect URI mismatch

Common mistake: localhost vs 127.0.0.1, or http vs https
- Google OAuth is strict about exact matches
- For local dev: `http://localhost:8001/oauth/callback` (not 127.0.0.1)
- For production: `https://mcp.yourdomain.com/google-workspace/oauth/callback` (must be HTTPS)

### "redirect_uri_mismatch" on Dokploy

Ensure in Dokploy environment:
```
GOOGLE_OAUTH_REDIRECT_URI=https://mcp.yourdomain.com/google-workspace/oauth/callback
```

And this exact URI is configured in Google Cloud Console OAuth settings.

## Advanced: Multiple Users

If multiple users will authenticate:
- Each user grants OAuth permission independently
- Each token is stored separately (in Docker volume)
- MCP switches between tokens based on calling user

For production multi-tenant setups, see the `workspace-mcp` [documentation](https://github.com/taylorwilsdon/google_workspace_mcp).

## Advanced: Custom Scopes

Override default scopes by setting:

```bash
GOOGLE_SCOPES=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/docs.readonly
```

Comma-separated list of scopes. See [Google Scopes Reference](https://developers.google.com/identity/protocols/oauth2/scopes).

## Security Notes

- **Never commit** `.env` files with client secrets
- **Rotate secrets** periodically in Google Cloud Console
- **Use HTTPS** in production (Dokploy + Let's Encrypt recommended)
- **Scope minimally**: Request only scopes you need
- **Token storage**: Docker volume can be encrypted with storage driver options

## Support

- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Google Workspace API Documentation](https://developers.google.com/workspace)
- [workspace-mcp GitHub](https://github.com/taylorwilsdon/google_workspace_mcp)
