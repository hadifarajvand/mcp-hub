# OAuth 2.1 authorization server + token verifier for the MCP hub (reachable only through the gateway).
FROM python:3.11-slim

WORKDIR /app
COPY hub-auth/requirements.txt .
# build_ca: optional CA for builds behind a TLS-intercepting proxy (see docker-compose.dev.yml)
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY hub-auth/hubauth ./hubauth

RUN mkdir -p /data && chown 10001:10001 /data
ENV PYTHONUNBUFFERED=1 HUBAUTH_DB=/data/hubauth.db
USER 10001:10001
EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/healthz', timeout=4)"

CMD ["python", "-m", "hubauth"]
