FROM python:3.11-slim

# Upstream: https://github.com/taylorwilsdon/google_workspace_mcp, pinned.
# build_ca: optional CA for builds behind a TLS-intercepting proxy (see docker-compose.dev.yml)
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir workspace-mcp==2.0.0

RUN useradd --uid 10001 --create-home app \
    && mkdir -p /data/credentials \
    && chown -R app:app /data

# Behind the hub gateway the public callback is <PUBLIC_BASE_URL>/google-workspace/oauth2callback;
# the gateway strips the prefix, so the server's own /oauth2callback route handles it.
ENV PYTHONUNBUFFERED=1 \
    WORKSPACE_MCP_PORT=8000 \
    WORKSPACE_MCP_HOST=0.0.0.0 \
    WORKSPACE_MCP_CREDENTIALS_DIR=/data/credentials \
    WORKSPACE_MCP_DISABLE_LOCAL_FILES=true \
    WORKSPACE_MCP_TOOL_TIER=core

USER app
VOLUME /data/credentials
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["workspace-mcp", "--transport", "streamable-http", "--single-user"]
