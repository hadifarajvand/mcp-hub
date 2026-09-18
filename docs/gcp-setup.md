# Transcriber MCP — Google's Built-in Speech Recognition Setup

The Transcriber MCP uses **Google's built-in speech recognition** via pyTranscriber's Autosub module. **No credentials or setup needed!**

## How It Works

- **Google's Services**: Uses Google's speech recognition services (via Translate/Speech APIs)
- **No Auth Required**: Works without explicit API keys or service accounts
- **99+ Languages**: Automatic language detection or specify language
- **All Formats**: MP3, WAV, FLAC, OGG, M4A, MP4, MKV, WebM, and more
- **Subtitle Support**: Output as plain text or SRT subtitles with timecodes

## Zero Setup Required

Just copy the `.env.example`:

```bash
cp servers/transcriber/.env.example servers/transcriber/.env
```

No credentials needed. Use it immediately.

## Configuration

Edit `servers/transcriber/.env`:

```bash
# HTTP server
MCP_HTTP_PORT=8000
MCP_HOST=0.0.0.0

# That's it! No other configuration needed.
```

## Usage

Once deployed:

```bash
# Transcribe audio file (returns text)
# In Claude: "Please transcribe /path/to/audio.mp3 in English"

# Transcribe video file (audio extracted automatically)
# In Claude: "Transcribe /path/to/video.mp4"

# Get subtitles instead of plain text
# In Claude: "Transcribe /path/to/audio.mp3 output as SRT subtitles"

# List supported languages
# In Claude: "What languages does the transcriber support?"
```

## Supported Languages

Supports 100+ languages including:
- English (en, en-US, en-GB)
- Spanish (es, es-ES, es-MX)
- French (fr)
- German (de)
- Italian (it)
- Portuguese (pt, pt-BR, pt-PT)
- Russian (ru)
- Japanese (ja)
- Chinese (zh, zh-CN, zh-TW)
- Korean (ko)
- Arabic (ar, ar-SA)
- Hindi (hi)
- Thai (th)
- Turkish (tr)
- Dutch (nl)
- Polish (pl)
- And many more...

## Docker Build

The Dockerfile automatically:
1. Installs FFmpeg (for video processing)
2. Installs pyTranscriber with Autosub (Google Speech)
3. Installs MCP and HTTP server dependencies

```bash
docker compose build transcriber
```

Build is fast (1-2 minutes, no model downloads).

## Output Formats

### Plain Text (default)
```
This is the transcribed text from your audio file.
```

### SRT Subtitles
```
1
00:00:00,000 --> 00:00:05,000
This is the transcribed text from your audio file.
```

## Troubleshooting

### "pyTranscriber Google Speech module not available" error

- Check container logs: `docker logs mcp-transcriber`
- Verify build completed successfully
- Rebuild: `docker compose build --no-cache transcriber`

### Network timeout during transcription

- Google's speech services require internet connectivity
- Check firewall allows outbound HTTPS to Google services
- Retry the transcription

### Unsupported audio format

- Ensure FFmpeg is available (included in Dockerfile)
- Check file is valid media format
- Try converting to MP3: `ffmpeg -i input.wav -codec:a libmp3lame -q:a 2 output.mp3`

### Language detection issues

- Specify language explicitly instead of relying on auto-detection
- Use language code (e.g., 'pt-BR' for Portuguese Brazil)

## What This Uses Under the Hood

- **pyTranscriber**: Open-source transcription framework
- **Autosub 0.4.0**: Google Translate/Speech API integration (no auth needed)
- **FFmpeg**: Audio/video format handling
- **Google Services**: Actual speech recognition

## No Costs

Google's speech services accessed this way are free. No billing, no API quotas, no credits needed.

## Support

- [pyTranscriber GitHub](https://github.com/raryelcostasouza/pyTranscriber)
- [Autosub GitHub](https://github.com/BingLingGroup/autosub)
- [FFmpeg Documentation](https://ffmpeg.org)
