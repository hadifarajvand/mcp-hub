FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone the workspace-mcp repository
RUN git clone https://github.com/taylorwilsdon/google_workspace_mcp.git /app/vendor

WORKDIR /app/vendor

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create tokens directory for OAuth persistence
RUN mkdir -p /app/tokens

WORKDIR /app

# Copy entrypoint
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
