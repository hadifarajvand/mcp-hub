FROM node:22-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone dokploy-mcp repo (using --depth 1 for faster clone)
RUN git clone --depth 1 https://github.com/gaqno/dokploy-mcp.git /app/dokploy_mcp_src

# Install dependencies and build
WORKDIR /app/dokploy_mcp_src
RUN npm install --legacy-peer-deps --no-optional && npm run build && npm prune --production

# Copy entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# Health check for API connectivity
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD []
