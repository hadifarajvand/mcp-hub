FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (ffmpeg needed for audio/video processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy MCP server code
COPY server.py .

EXPOSE 8000

# Extended start period for Whisper model download on first run (~140MB)
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with unbuffered output for better logging
CMD ["python", "-u", "server.py"]
