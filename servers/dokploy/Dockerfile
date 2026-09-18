FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone dokploy-mcp repo
RUN git clone https://github.com/gaqno/dokploy-mcp.git /app/dokploy_mcp_src

# Check what's in the repo
RUN ls -la /app/dokploy_mcp_src/ && cat /app/dokploy_mcp_src/requirements.txt 2>/dev/null || echo "No requirements.txt found"

# Install dependencies from requirements if exists
RUN if [ -f /app/dokploy_mcp_src/requirements.txt ]; then \
      pip install --no-cache-dir -q -r /app/dokploy_mcp_src/requirements.txt; \
    else \
      pip install --no-cache-dir -q mcp fastapi uvicorn pydantic requests; \
    fi

# Copy entrypoint
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
