# Root-level Dockerfile for Dokploy - Transcriber MCP (primary service)
# Simplest MCP: works immediately, no credentials needed
# Use this single service first, then add Google Workspace & Dokploy MCPs later

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio/video processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY servers/transcriber/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy transcriber MCP server code
COPY servers/transcriber/server.py .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run transcriber service (ready to use, no setup needed)
CMD ["python", "-u", "server.py"]
