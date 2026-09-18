# Transcriber MCP — OpenAI Whisper Setup

The Transcriber MCP uses **OpenAI Whisper** for local speech recognition. **No credentials, no Google Cloud account, no API keys needed!**

## How It Works

- **Local Processing**: Whisper runs entirely on your server (no external API calls)
- **Auto Model Caching**: First run downloads the model (~140MB), then cached for future use
- **99+ Languages**: Supports automatic language detection or specify language
- **All Formats**: MP3, WAV, FLAC, OGG, M4A, MP4, MKV, WebM, and more

## Zero Setup Required

Just copy the `.env.example`:

```bash
cp servers/transcriber/.env.example servers/transcriber/.env
```

No credentials needed. The Dockerfile pre-caches the Whisper base model during build.

## Configuration

Edit `servers/transcriber/.env`:

```bash
# Whisper Model Size
# Options: tiny (39M), base (140M), small (466M), medium (1.5G), large (2.9G)
# Default: base (good balance, pre-cached)
WHISPER_MODEL=base

# Models directory (auto-managed, no action needed)
WHISPER_MODELS_DIR=/app/whisper_models

# HTTP server
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0
```

## Usage

Once deployed:

```bash
# Transcribe audio file
# In Claude: "Please transcribe /path/to/audio.mp3 in English"

# Transcribe video file (audio extracted automatically)
# In Claude: "Transcribe /path/to/video.mp4"

# List supported languages
# In Claude: "What languages does the transcriber support?"
```

## Supported Languages

Whisper supports 99+ languages including:
- English (en)
- Spanish (es)
- French (fr)
- German (de)
- Italian (it)
- Portuguese (pt, pt-BR)
- Russian (ru)
- Japanese (ja)
- Chinese (zh, zh-CN, zh-TW)
- Korean (ko)
- Arabic (ar)
- Hindi (hi)
- And many more...

## Model Trade-offs

| Model | Size | Speed | Quality | GPU RAM |
|-------|------|-------|---------|---------|
| tiny | 39M | Very Fast | Basic | 1GB |
| base | 140M | Fast | Good | 2GB |
| small | 466M | Medium | Better | 3GB |
| medium | 1.5G | Slower | Very Good | 5GB |
| large | 2.9G | Slowest | Excellent | 10GB |

## Docker Build

The Dockerfile automatically:
1. Installs FFmpeg (for video processing)
2. Installs PyTorch with CUDA support (GPU enabled)
3. Installs Whisper library
4. Pre-caches the base model (~140MB download at build time)

```bash
docker compose build transcriber
```

First build takes ~5 minutes (downloads model). Subsequent builds use cached layer.

## Troubleshooting

### Transcription slow on CPU

- GPU recommended for faster transcription
- Docker includes CUDA support (pytorch/pytorch:2.1.0-cuda12.1-runtime image)
- CPU transcription is 10x slower

### "Whisper not available" error

- Check container logs: `docker logs mcp-transcriber`
- Verify build completed successfully
- Rebuild: `docker compose build --no-cache transcriber`

### Out of memory during transcription

- Reduce model size (use `WHISPER_MODEL=tiny` instead of `large`)
- Increase Docker memory limit in compose or container settings

### Supported format error

- Ensure FFmpeg is available (included in Dockerfile)
- Check file is valid media format

## Advanced: GPU Acceleration

The container uses `pytorch/pytorch:2.1.0-cuda12.1-runtime`, which includes CUDA support.

For GPU acceleration:
1. Ensure NVIDIA GPU drivers installed on host
2. Install NVIDIA Docker runtime: https://github.com/NVIDIA/nvidia-docker
3. Add to `docker-compose.yml`:
   ```yaml
   transcriber:
     runtime: nvidia
     environment:
       - NVIDIA_VISIBLE_DEVICES=all
   ```

## No Costs

Whisper is open-source and free. No billing, no API calls, no quotas.

## Support

- [OpenAI Whisper GitHub](https://github.com/openai/whisper)
- [Whisper Model Documentation](https://openai.com/research/whisper)
- [pyTranscriber GitHub](https://github.com/raryelcostasouza/pyTranscriber)
