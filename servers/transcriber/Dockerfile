FROM pytorch/pytorch:2.1.0-cuda12.1-runtime-ubuntu22.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy pyTranscriber (cloned locally)
COPY vendor /app/vendor

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model (base model ~140MB)
RUN mkdir -p /app/whisper_models && \
    python -c "import whisper; whisper.load_model('base', download_root='/app/whisper_models', device='cpu')" && \
    echo "✓ Whisper base model cached"

# Copy MCP server code
COPY server.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "server.py"]
