#!/bin/bash
set -e

# Validate required environment variables
if [ -z "$DOKPLOY_URL" ]; then
    echo "ERROR: DOKPLOY_URL not set (e.g., http://dokploy.local or https://deploy.yourdomain.com)"
    exit 1
fi

if [ -z "$DOKPLOY_API_KEY" ]; then
    echo "ERROR: DOKPLOY_API_KEY not set. Generate one from Dokploy dashboard."
    exit 1
fi

# Export for the MCP server
export DOKPLOY_URL
export DOKPLOY_API_KEY
export MCP_HTTP_PORT="${MCP_HTTP_PORT:-8000}"
export MCP_HOST="${MCP_HOST:-0.0.0.0}"
export MCP_BEARER_TOKEN="${MCP_BEARER_TOKEN:-}"

echo "Starting Dokploy MCP server..."
echo "  Dokploy URL: ${DOKPLOY_URL}"
echo "  Listening on ${MCP_HOST}:${MCP_HTTP_PORT}"

# Run the dokploy-mcp server with HTTP transport
cd /app/vendor
python -m dokploy_mcp.server \
    --http \
    --host "${MCP_HOST}" \
    --port "${MCP_HTTP_PORT}"
