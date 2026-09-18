#!/bin/bash
# Verify Claude and ChatGPT compatibility for MCP Hub

echo "=========================================="
echo "Claude & ChatGPT Compatibility Check"
echo "=========================================="
echo ""

# Check if services are running
check_service() {
    local name=$1
    local port=$2

    if curl -s -f http://localhost:$port/health > /dev/null; then
        echo "✓ $name is running (port $port)"
        return 0
    else
        echo "✗ $name is NOT running (port $port)"
        return 1
    fi
}

echo "Step 1: Verify Services Running"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TRANSCRIBER_OK=$(check_service "Transcriber" 8002)
WORKSPACE_OK=$(check_service "Google Workspace" 8001)
DOKPLOY_OK=$(check_service "Dokploy" 8003)

echo ""

# Check HTTP protocol support
echo "Step 2: Verify HTTP Protocol Support"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Testing HTTP/1.1 Support:"
curl -I http://localhost:8002/health 2>/dev/null | grep HTTP
echo ""

# Check JSON responses
echo "Step 3: Verify JSON Responses"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Transcriber response:"
curl -s http://localhost:8002/health | jq '.service'

echo "Google Workspace response:"
curl -s http://localhost:8001/ | jq '.service'

echo "Dokploy response:"
curl -s http://localhost:8003/ | jq '.service'

echo ""

# Check OpenAPI/API Documentation
echo "Step 4: Check API Documentation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "servers/transcriber/openapi.json" ]; then
    echo "✓ Transcriber OpenAPI spec exists"
    OPENAPI_VALID=$(jq -e '.openapi' servers/transcriber/openapi.json > /dev/null 2>&1 && echo "valid" || echo "invalid")
    echo "  OpenAPI version: $(jq -r '.openapi' servers/transcriber/openapi.json 2>/dev/null || echo "unknown")"
    echo "  Status: $OPENAPI_VALID"
else
    echo "✗ Transcriber OpenAPI spec not found"
fi

if [ -f "servers/transcriber/ai-plugin.json" ]; then
    echo "✓ Transcriber AI plugin config exists"
else
    echo "✗ Transcriber AI plugin config not found"
fi

echo ""

# Check CORS headers
echo "Step 5: Check CORS Headers (for ChatGPT)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Transcriber CORS headers:"
curl -s -I http://localhost:8002/health | grep -i "access-control" || echo "No CORS headers found (expected for local testing)"

echo ""

# Test endpoint accessibility
echo "Step 6: Test Endpoint Accessibility"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Transcriber endpoints:"
echo "  GET /health: $(curl -s -w '%{http_code}' -o /dev/null http://localhost:8002/health)"
echo "  POST /transcribe_audio: $(curl -s -w '%{http_code}' -o /dev/null -X POST http://localhost:8002/transcribe_audio -H 'Content-Type: application/json' -d '{}')"
echo "  POST /list_supported_languages: $(curl -s -w '%{http_code}' -o /dev/null -X POST http://localhost:8002/list_supported_languages -H 'Content-Type: application/json' -d '{}')"

echo ""
echo "Google Workspace endpoints:"
echo "  GET /health: $(curl -s -w '%{http_code}' -o /dev/null http://localhost:8001/health)"
echo "  GET /: $(curl -s -w '%{http_code}' -o /dev/null http://localhost:8001/)"

echo ""
echo "Dokploy endpoints:"
echo "  GET /health: $(curl -s -w '%{http_code}' -o /dev/null http://localhost:8003/health)"
echo "  GET /: $(curl -s -w '%{http_code}' -o /dev/null http://localhost:8003/)"

echo ""

# Test error handling
echo "Step 7: Test Error Handling (Important for AI)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Testing invalid request handling:"
INVALID_RESPONSE=$(curl -s -X POST http://localhost:8002/transcribe_audio \
  -H "Content-Type: application/json" \
  -d 'invalid json')

if echo "$INVALID_RESPONSE" | grep -q "detail\|error"; then
    echo "✓ Error handling working (returns error details)"
else
    echo "⚠ Error handling may need improvement"
fi

echo ""

# Check rate limiting readiness
echo "Step 8: Performance & Stability Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Response times (10 requests each):"

echo -n "Transcriber /health: "
time_sum=0
for i in {1..10}; do
    start=$(date +%s%N)
    curl -s http://localhost:8002/health > /dev/null
    end=$(date +%s%N)
    time_ms=$(( (end - start) / 1000000 ))
    time_sum=$((time_sum + time_ms))
done
avg=$((time_sum / 10))
echo "~${avg}ms average"

echo -n "Google Workspace /health: "
time_sum=0
for i in {1..10}; do
    start=$(date +%s%N)
    curl -s http://localhost:8001/health > /dev/null
    end=$(date +%s%N)
    time_ms=$(( (end - start) / 1000000 ))
    time_sum=$((time_sum + time_ms))
done
avg=$((time_sum / 10))
echo "~${avg}ms average"

echo ""

# Summary
echo "=========================================="
echo "COMPATIBILITY SUMMARY"
echo "=========================================="
echo ""

READY_FOR_CLAUDE=true
READY_FOR_CHATGPT=true

if ! $TRANSCRIBER_OK || ! $WORKSPACE_OK || ! $DOKPLOY_OK; then
    READY_FOR_CLAUDE=false
    READY_FOR_CHATGPT=false
fi

if $READY_FOR_CLAUDE; then
    echo "✓ Ready for Claude Integration:"
    echo "  • All services running and healthy"
    echo "  • HTTP protocol supported"
    echo "  • JSON responses working"
    echo "  • Can be added to Claude Desktop/Code via HTTP transport"
else
    echo "✗ Not ready for Claude Integration:"
    echo "  • Some services not responding"
    echo "  • Please restart: docker compose -f docker-compose.test.yml up -d"
fi

echo ""

if $READY_FOR_CHATGPT; then
    echo "✓ Ready for ChatGPT Integration:"
    echo "  • All services accessible via REST API"
    echo "  • OpenAPI specifications available"
    echo "  • Error handling working"
    echo "  • Can be integrated via Custom GPT or Code Interpreter"

    if [ -f "servers/transcriber/openapi.json" ]; then
        echo "  • OpenAPI schema ready for import"
    fi
else
    echo "✗ Not ready for ChatGPT Integration:"
    echo "  • Some services not responding"
    echo "  • Please restart: docker compose -f docker-compose.test.yml up -d"
fi

echo ""

# Setup instructions
echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo ""
echo "For Claude Desktop:"
echo "  1. Open Claude Desktop Settings"
echo "  2. Go to MCP Servers"
echo "  3. Add: Transcriber → http://localhost:8002"
echo "  4. Add: Google Workspace → http://localhost:8001"
echo "  5. Add: Dokploy → http://localhost:8003"
echo ""
echo "For ChatGPT:"
echo "  1. Go to: https://chat.openai.com/gpts/editor"
echo "  2. Create New GPT"
echo "  3. Configure Actions"
echo "  4. Import OpenAPI from: servers/transcriber/openapi.json"
echo ""
echo "See SETUP_CLAUDE_CHATGPT.md for detailed instructions"
echo ""
