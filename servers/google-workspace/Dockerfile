FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone workspace-mcp repo
RUN git clone https://github.com/taylorwilsdon/google_workspace_mcp.git /app/workspace_mcp_src

# Check what's in the repo
RUN ls -la /app/workspace_mcp_src/ && cat /app/workspace_mcp_src/requirements.txt 2>/dev/null || echo "No requirements.txt found"

# Install dependencies from requirements if exists
RUN if [ -f /app/workspace_mcp_src/requirements.txt ]; then \
      pip install --no-cache-dir -q -r /app/workspace_mcp_src/requirements.txt; \
    else \
      pip install --no-cache-dir -q mcp fastapi uvicorn pydantic requests google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client; \
    fi

# Create tokens directory for OAuth persistence
RUN mkdir -p /app/tokens

# Copy entrypoint
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
