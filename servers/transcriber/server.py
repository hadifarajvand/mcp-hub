#!/usr/bin/env python3
"""Transcriber MCP server: audio/video to text with Google Cloud Speech-to-Text.

Served over MCP streamable HTTP at /mcp. Input is either a public http(s) URL
or base64-encoded file content (the server cannot see the client's disk).

Credentials, in order of precedence:
  GOOGLE_CREDENTIALS_JSON         service-account JSON as a string (Dokploy-friendly)
  GOOGLE_APPLICATION_CREDENTIALS  path to a service-account JSON file
"""

import asyncio
import base64
import binascii
import json
import os
import subprocess
import tempfile
from pathlib import Path

import httpx
from google.cloud import speech
from google.oauth2 import service_account
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from ssrf import SSRFError, read_capped, safe_stream  # shared SSRF guard (servers/common/ssrf.py)

MAX_INPUT_BYTES = int(os.getenv("TRANSCRIBER_MAX_INPUT_MB", "20")) * 1024 * 1024
DOWNLOAD_TIMEOUT = 60
FFMPEG_TIMEOUT = 300
SAMPLE_RATE = 16000
# 16 kHz mono 16-bit PCM = 32000 bytes per second.
PCM_BYTES_PER_SECOND = SAMPLE_RATE * 2
# Synchronous recognize accepts up to ~60 s of audio.
SYNC_MAX_SECONDS = 55
# Inline audio content is capped at 10 MB by the API (about 5.4 minutes of PCM).
INLINE_MAX_BYTES = 10 * 1024 * 1024
RECOGNIZE_TIMEOUT = 900

SUPPORTED_LANGUAGES = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "es-ES": "Spanish (Spain)",
    "es-US": "Spanish (US)",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
    "pt-PT": "Portuguese (Portugal)",
    "pt-BR": "Portuguese (Brazil)",
    "ru-RU": "Russian",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "cmn-Hans-CN": "Chinese (Simplified)",
    "cmn-Hant-TW": "Chinese (Traditional)",
    "ar-SA": "Arabic",
    "fa-IR": "Persian",
    "hi-IN": "Hindi",
    "th-TH": "Thai",
    "tr-TR": "Turkish",
    "nl-NL": "Dutch",
    "pl-PL": "Polish",
    "vi-VN": "Vietnamese",
}


class TranscriberError(Exception):
    """An error whose message is safe to return to the MCP client."""


def _speech_client() -> speech.SpeechClient:
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as e:
            raise TranscriberError("GOOGLE_CREDENTIALS_JSON is not valid JSON") from e
        creds = service_account.Credentials.from_service_account_info(info)
        return speech.SpeechClient(credentials=creds)
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return speech.SpeechClient()
    raise TranscriberError(
        "Google Cloud credentials are not configured on the server "
        "(set GOOGLE_CREDENTIALS_JSON to a service-account key with Speech-to-Text access)"
    )


async def _download(url: str, dest: Path) -> None:
    """Fetch `url` into `dest` through the shared SSRF guard (pinned IP, re-validated redirects)."""
    try:
        async with safe_stream(url, timeout=DOWNLOAD_TIMEOUT) as resp:
            if resp.status_code != 200:
                raise TranscriberError(f"Download failed with HTTP {resp.status_code}")
            dest.write_bytes(await read_capped(resp, MAX_INPUT_BYTES))
    except SSRFError as e:
        raise TranscriberError(str(e)) from e


def _to_pcm(src: Path) -> bytes:
    """Convert any audio/video container to raw 16 kHz mono LINEAR16."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
        raise TranscriberError(f"Could not decode media: {detail[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise TranscriberError("Media conversion timed out") from e
    if not proc.stdout:
        raise TranscriberError("Media contains no audio track")
    return proc.stdout


def _recognize(pcm: bytes, language: str, punctuation: bool) -> dict:
    if len(pcm) > INLINE_MAX_BYTES:
        minutes = INLINE_MAX_BYTES / PCM_BYTES_PER_SECOND / 60
        raise TranscriberError(f"Audio is longer than the ~{minutes:.1f} minute limit for inline transcription")

    client = _speech_client()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=SAMPLE_RATE,
        audio_channel_count=1,
        language_code=language,
        enable_automatic_punctuation=punctuation,
    )
    audio = speech.RecognitionAudio(content=pcm)
    seconds = len(pcm) / PCM_BYTES_PER_SECOND
    if seconds <= SYNC_MAX_SECONDS:
        response = client.recognize(config=config, audio=audio, timeout=RECOGNIZE_TIMEOUT)
    else:
        response = client.long_running_recognize(config=config, audio=audio).result(timeout=RECOGNIZE_TIMEOUT)

    best = [r.alternatives[0] for r in response.results if r.alternatives]
    return {
        "transcript": " ".join(a.transcript.strip() for a in best).strip(),
        "language": language,
        "duration_seconds": round(seconds, 1),
        "average_confidence": round(sum(a.confidence for a in best) / len(best), 3) if best else None,
    }


def _process_sync(src: Path, language: str, punctuation: bool) -> dict:
    pcm = _to_pcm(src)
    return _recognize(pcm, language, punctuation)


async def _transcribe(audio_url: str | None, audio_base64: str | None, language: str, punctuation: bool) -> dict:
    if bool(audio_url) == bool(audio_base64):
        raise TranscriberError("Provide exactly one of audio_url or audio_base64")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input"
        if audio_url:
            await _download(audio_url, src)
        else:
            try:
                data = base64.b64decode(audio_base64, validate=True)
            except (binascii.Error, ValueError) as e:
                raise TranscriberError("audio_base64 is not valid base64") from e
            if len(data) > MAX_INPUT_BYTES:
                raise TranscriberError(f"File exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MB limit")
            src.write_bytes(data)
        return await asyncio.to_thread(_process_sync, src, language, punctuation)


def _allowed_hosts() -> list[str]:
    raw = os.getenv("MCP_ALLOWED_HOSTS", "transcriber:8000,localhost:*,127.0.0.1:*")
    return [h.strip() for h in raw.split(",") if h.strip()]


mcp = MCPServer(
    name="transcriber",
    instructions="Transcribe audio or video (by public URL or base64 content) to text with Google Cloud Speech-to-Text.",
)


@mcp.tool()
async def transcribe(
    audio_url: str | None = None,
    audio_base64: str | None = None,
    language: str = "en-US",
    punctuation: bool = True,
) -> dict:
    """Transcribe an audio or video file to text.

    Pass exactly one of:
      audio_url:    public http(s) URL of the media file
      audio_base64: base64-encoded file content (max 20 MB decoded)
    language is a BCP-47 code such as en-US, pt-BR, fa-IR (see list_languages).
    Any format ffmpeg can read works (mp3, wav, m4a, ogg, flac, mp4, mkv, webm...).
    Audio longer than about 5 minutes is rejected.
    """
    try:
        return await _transcribe(audio_url, audio_base64, language, punctuation)
    except TranscriberError as e:
        return {"error": str(e)}
    except httpx.HTTPError as e:
        return {"error": f"Download failed: {type(e).__name__}"}
    except Exception as e:  # Google API errors etc.; don't leak tracebacks
        return {"error": f"Transcription failed: {type(e).__name__}: {e}"}


@mcp.tool()
def list_languages() -> dict:
    """List common language codes accepted by `transcribe`. Any BCP-47 code supported by Google STT also works."""
    return {"languages": SUPPORTED_LANGUAGES}


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8000")),
        max_request_body_size=MAX_INPUT_BYTES * 2,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_allowed_hosts(),
            allowed_origins=[],
        ),
    )
