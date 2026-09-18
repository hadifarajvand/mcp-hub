FROM node:22-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone dokploy-mcp repo
RUN git clone https://github.com/gaqno/dokploy-mcp.git /app/dokploy_mcp_src

# Install dependencies and build
WORKDIR /app/dokploy_mcp_src
RUN npm install --legacy-peer-deps && npm run build

# Copy entrypoint
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
