#!/bin/bash
set -e

# Validate required environment variables
if [ -z "$GOOGLE_OAUTH_CLIENT_ID" ]; then
    echo "ERROR: GOOGLE_OAUTH_CLIENT_ID not set"
    exit 1
fi

if [ -z "$GOOGLE_OAUTH_CLIENT_SECRET" ]; then
    echo "ERROR: GOOGLE_OAUTH_CLIENT_SECRET not set"
    exit 1
fi

# Export for the MCP server
export GOOGLE_OAUTH_CLIENT_ID
export GOOGLE_OAUTH_CLIENT_SECRET
export GOOGLE_OAUTH_REDIRECT_URI="${GOOGLE_OAUTH_REDIRECT_URI:-https://mcp.local/google-workspace/oauth/callback}"
export TOKEN_STORAGE_PATH="/app/tokens"
export MCP_HTTP_PORT="${MCP_HTTP_PORT:-8000}"
export MCP_HOST="${MCP_HOST:-0.0.0.0}"
export TOOL_TIER="${TOOL_TIER:-docs,sheets,slides,drive,gmail,calendar}"

echo "Starting Google Workspace MCP server..."
echo "  Client ID: ${GOOGLE_OAUTH_CLIENT_ID:0:20}..."
echo "  Redirect URI: ${GOOGLE_OAUTH_REDIRECT_URI}"
echo "  Tool Tier: ${TOOL_TIER}"
echo "  Listening on ${MCP_HOST}:${MCP_HTTP_PORT}"

# Add workspace_mcp_src to Python path and run the server
export PYTHONPATH="/app/workspace_mcp_src:${PYTHONPATH}"
cd /app/workspace_mcp_src

# Try running as module
python -m google_workspace_mcp.server \
    --http \
    --host "${MCP_HOST}" \
    --port "${MCP_HTTP_PORT}" \
    --token-storage "${TOKEN_STORAGE_PATH}" || \
# Fallback: try running server.py if module doesn't work
python server.py
