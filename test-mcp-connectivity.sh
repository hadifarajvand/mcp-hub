#!/bin/bash
# Test MCP connectivity and functionality

set -e

echo "============================="
echo "Testing MCP Hub Connectivity"
echo "============================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test function
test_service() {
    local service_name=$1
    local port=$2
    local health_endpoint=$3

    echo -n "Testing $service_name (localhost:$port)... "

    if curl -s -f "http://localhost:$port$health_endpoint" > /dev/null; then
        echo -e "${GREEN}✓ OK${NC}"
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}"
        return 1
    fi
}

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 5
echo ""

# Test Transcriber
test_service "Transcriber" 8002 "/health" || echo -e "${YELLOW}Note: Transcriber may need GOOGLE_APPLICATION_CREDENTIALS${NC}"

# Test Google Workspace
test_service "Google Workspace" 8001 "/health" || echo -e "${YELLOW}Note: Google Workspace may need GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET${NC}"

# Test Dokploy
test_service "Dokploy" 8003 "/health" || echo -e "${YELLOW}Note: Dokploy may need DOKPLOY_URL and DOKPLOY_API_KEY${NC}"

echo ""
echo "============================="
echo "Testing Transcriber API"
echo "============================="
echo ""

# Test transcriber endpoint
echo "Testing transcriber language list..."
curl -X POST "http://localhost:8002/list_supported_languages" \
    -H "Content-Type: application/json" \
    -d '{}' 2>/dev/null | jq '.' || echo "Could not reach transcriber"

echo ""
echo "============================="
echo "Service URLs for MCP Clients"
echo "============================="
echo ""
echo "Transcriber:        http://localhost:8002"
echo "Google Workspace:   http://localhost:8001"
echo "Dokploy:            http://localhost:8003"
echo ""
echo "Configuration in Claude Code/Desktop:"
echo "  - Use HTTP transport"
echo "  - Add servers by URL (e.g., http://localhost:8002)"
echo ""
