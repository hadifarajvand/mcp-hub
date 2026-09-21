FROM python:3.11-slim

WORKDIR /app

# Install system dependencies with minimal bloat
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone workspace-mcp repo (using --depth 1 for faster clone)
RUN git clone --depth 1 https://github.com/taylorwilsdon/google_workspace_mcp.git /app/workspace_mcp_src

# Install Python dependencies
WORKDIR /app/workspace_mcp_src
RUN pip install --no-cache-dir -q -e . || pip install --no-cache-dir -q \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    fastmcp==0.5.0 \
    google-auth==2.25.2 \
    google-auth-oauthlib==1.2.0 \
    google-auth-httplib2==0.2.0 \
    google-api-python-client==2.104.0 \
    python-dotenv==1.0.0 \
    pyyaml==6.0.1

# Create tokens directory for OAuth persistence
RUN mkdir -p /app/tokens && chmod 755 /app/tokens

# Copy entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# Health check with increased start period for initial OAuth setup
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD []
