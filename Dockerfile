# Root-level Dockerfile for Dokploy deployment with Docker build type
# Builds and runs docker-compose services

FROM docker:24-dind

WORKDIR /app

# Install docker-compose and curl for health checks
RUN apk add --no-cache docker-compose curl

# Copy entire repository
COPY . .

# Expose ports for all three MCP services
EXPOSE 8001 8002 8003

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Set compose project name
ENV COMPOSE_PROJECT_NAME=mcp-hub

# Start services with docker-compose
CMD ["sh", "-c", "dockerd-entrypoint.sh & sleep 3 && cd /app && docker-compose -f docker-compose.yml up"]
