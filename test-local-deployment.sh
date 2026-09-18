#!/bin/bash
# Complete local deployment and testing script

set -e

echo "=========================================="
echo "MCP Hub - Local Deployment & Testing"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
COMPOSE_FILE="docker-compose.test.yml"
MAX_WAIT=120
CHECK_INTERVAL=5

# Function to print status
status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

error() {
    echo -e "${RED}[✗]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Step 1: Clean up
status "Step 1: Cleaning up previous deployment..."
docker compose -f $COMPOSE_FILE down -v 2>/dev/null || true
docker system prune -f 2>/dev/null || true
echo ""

# Step 2: Build
status "Step 2: Building Docker images..."
docker compose -f $COMPOSE_FILE build --no-cache
success "Docker images built"
echo ""

# Step 3: Start services
status "Step 3: Starting services..."
docker compose -f $COMPOSE_FILE up -d
echo "Waiting for services to initialize..."
sleep 10
echo ""

# Step 4: Check service status
status "Step 4: Checking service health..."
docker compose -f $COMPOSE_FILE ps
echo ""

# Step 5: Wait for healthy status
status "Step 5: Waiting for all services to be healthy..."
ELAPSED=0
ALL_HEALTHY=false

while [ $ELAPSED -lt $MAX_WAIT ]; do
    GOOGLE_HEALTH=$(docker compose -f $COMPOSE_FILE exec -T google-workspace curl -s http://localhost:8000/health 2>/dev/null || echo "")
    TRANSCRIBER_HEALTH=$(docker compose -f $COMPOSE_FILE exec -T transcriber curl -s http://localhost:8000/health 2>/dev/null || echo "")
    DOKPLOY_HEALTH=$(docker compose -f $COMPOSE_FILE exec -T dokploy curl -s http://localhost:8000/health 2>/dev/null || echo "")

    if [ -n "$GOOGLE_HEALTH" ] && [ -n "$TRANSCRIBER_HEALTH" ] && [ -n "$DOKPLOY_HEALTH" ]; then
        ALL_HEALTHY=true
        break
    fi

    echo -n "."
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
done

echo ""
if [ "$ALL_HEALTHY" = true ]; then
    success "All services are healthy!"
else
    warning "Services may still be starting, checking logs..."
fi
echo ""

# Step 6: Test connectivity
status "Step 6: Testing service connectivity..."
echo ""

# Test Transcriber
echo -n "Testing Transcriber (port 8002)... "
if curl -s -f http://localhost:8002/health > /dev/null; then
    success "Transcriber responding"
    echo "  Endpoint: http://localhost:8002"
else
    error "Transcriber not responding"
fi

# Test Google Workspace
echo -n "Testing Google Workspace (port 8001)... "
if curl -s -f http://localhost:8001/health > /dev/null; then
    success "Google Workspace responding"
    echo "  Endpoint: http://localhost:8001"
else
    error "Google Workspace not responding"
fi

# Test Dokploy
echo -n "Testing Dokploy (port 8003)... "
if curl -s -f http://localhost:8003/health > /dev/null; then
    success "Dokploy responding"
    echo "  Endpoint: http://localhost:8003"
else
    error "Dokploy not responding"
fi
echo ""

# Step 7: Test API endpoints
status "Step 7: Testing API endpoints..."
echo ""

echo "Testing Transcriber APIs:"
echo -n "  /health... "
curl -s -f http://localhost:8002/health > /dev/null && success "OK" || error "FAILED"

echo -n "  /list_supported_languages... "
LANG_RESPONSE=$(curl -s -X POST http://localhost:8002/list_supported_languages -H "Content-Type: application/json" -d '{}')
if echo "$LANG_RESPONSE" | grep -q "languages"; then
    success "OK"
    echo "    Sample: $(echo $LANG_RESPONSE | jq '.count') languages available"
else
    error "FAILED"
fi

echo -n "  /transcribe_audio (error case)... "
AUDIO_RESPONSE=$(curl -s -X POST http://localhost:8002/transcribe_audio -H "Content-Type: application/json" -d '{"file_path":"/nonexistent.wav"}')
if echo "$AUDIO_RESPONSE" | grep -q "error\|success"; then
    success "OK"
else
    error "FAILED"
fi
echo ""

echo "Testing Google Workspace APIs:"
echo -n "  /health... "
curl -s -f http://localhost:8001/health > /dev/null && success "OK" || error "FAILED"

echo -n "  /... "
GW_RESPONSE=$(curl -s http://localhost:8001/)
if echo "$GW_RESPONSE" | grep -q "Google Workspace"; then
    success "OK"
    echo "    Service: $(echo $GW_RESPONSE | jq -r '.service')"
else
    error "FAILED"
fi
echo ""

echo "Testing Dokploy APIs:"
echo -n "  /health... "
curl -s -f http://localhost:8003/health > /dev/null && success "OK" || error "FAILED"

echo -n "  /... "
DK_RESPONSE=$(curl -s http://localhost:8003/)
if echo "$DK_RESPONSE" | grep -q "Dokploy"; then
    success "OK"
    echo "    Service: $(echo $DK_RESPONSE | jq -r '.service')"
else
    error "FAILED"
fi
echo ""

# Step 8: Show service info
status "Step 8: Service Information"
echo ""
echo "Service URLs (for MCP clients):"
echo "  Google Workspace: http://localhost:8001"
echo "  Transcriber:      http://localhost:8002"
echo "  Dokploy:          http://localhost:8003"
echo ""

echo "Container Status:"
docker compose -f $COMPOSE_FILE ps
echo ""

echo "View Logs:"
echo "  docker compose -f docker-compose.test.yml logs -f [service]"
echo "  Supported services: google-workspace, transcriber, dokploy"
echo ""

# Step 9: Summary
echo "=========================================="
echo "Testing Summary"
echo "=========================================="

GOOGLE_UP=$(curl -s -f http://localhost:8001/health > /dev/null && echo "UP" || echo "DOWN")
TRANSCRIBER_UP=$(curl -s -f http://localhost:8002/health > /dev/null && echo "UP" || echo "DOWN")
DOKPLOY_UP=$(curl -s -f http://localhost:8003/health > /dev/null && echo "UP" || echo "DOWN")

echo "Google Workspace:  $GOOGLE_UP"
echo "Transcriber:       $TRANSCRIBER_UP"
echo "Dokploy:           $DOKPLOY_UP"
echo ""

if [ "$GOOGLE_UP" = "UP" ] && [ "$TRANSCRIBER_UP" = "UP" ] && [ "$DOKPLOY_UP" = "UP" ]; then
    success "All services are running and responding!"
    echo ""
    echo "Next Steps:"
    echo "  1. Test in Claude Code/Claude Desktop"
    echo "  2. Add each MCP server using HTTP transport"
    echo "  3. Verify tools are accessible"
    echo "  4. Once satisfied, deploy to Dokploy:"
    echo "     git push origin master"
    echo "     Then deploy via Dokploy dashboard"
else
    error "Some services are not responding"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check container logs:"
    echo "     docker compose -f docker-compose.test.yml logs"
    echo "  2. Verify ports are available: 8001, 8002, 8003"
    echo "  3. Check Docker network: docker network ls"
fi
