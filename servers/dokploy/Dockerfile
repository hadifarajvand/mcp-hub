FROM node:22-slim

# Official Dokploy MCP server (https://github.com/Dokploy/mcp), pinned.
# build_ca: optional CA for builds behind a TLS-intercepting proxy (see docker-compose.dev.yml)
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm install -g --omit=dev @dokploy/mcp@0.30.7 && npm cache clean --force

# HTTP mode listens on :3000 and serves /mcp (streamable HTTP) and /health.
# Secrets in API responses (env, passwords, tokens) are redacted by default.
ENV NODE_ENV=production \
    MCP_TRANSPORT=http \
    DOKPLOY_REDACT_ENV=true

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["dokploy-mcp"]
