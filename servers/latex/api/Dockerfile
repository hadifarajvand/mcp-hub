# LaTeX MCP API tier: workspace + editing + analysis. Contains NO TeX; compiles run in latex-worker.
FROM python:3.11-slim

WORKDIR /app
COPY latex/api/requirements.txt .
# build_ca: optional CA for builds behind a TLS-intercepting proxy (see docker-compose.dev.yml)
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY latex/api/*.py ./

# Named volume mounted here inherits this ownership on first use.
RUN mkdir -p /data/ws && chown -R 10001:10001 /data
ENV PYTHONUNBUFFERED=1 MCP_HOST=0.0.0.0 MCP_PORT=8000 LATEX_DATA_DIR=/data/ws
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["python", "server.py"]
