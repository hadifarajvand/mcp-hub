#!/usr/bin/env python3
"""
Transcriber MCP Server — OpenAI Whisper via pyTranscriber
Transcribes audio and video files locally using OpenAI Whisper.
No credentials required — models cached locally after first download.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

# Add vendor pyTranscriber to path
sys.path.insert(0, "/app/vendor")

try:
    import whisper
    whisper_available = True
except ImportError:
    print("Warning: Whisper not available yet (will be installed)")
    whisper_available = False

from mcp.server import Server
from mcp.types import Tool, TextContent, ToolResult

app = Server("transcriber-mcp")

# Supported languages (Whisper supports 99+ languages)
SUPPORTED_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-BR": "Portuguese (Brazil)",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "tr": "Turkish",
    "nl": "Dutch",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "hu": "Hungarian",
    "cs": "Czech",
    "ro": "Romanian",
    "el": "Greek",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
}

# Model size (can be: tiny, base, small, medium, large)
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
MODELS_DIR = os.getenv("WHISPER_MODELS_DIR", "/app/whisper_models")

# Ensure models directory exists
os.makedirs(MODELS_DIR, exist_ok=True)


def load_whisper_model():
    """Load Whisper model (downloads if needed)."""
    try:
        print(f"Loading Whisper model: {MODEL_SIZE}")
        model = whisper.load_model(
            MODEL_SIZE,
            device="cuda" if _cuda_available() else "cpu",
            download_root=MODELS_DIR,
        )
        return model
    except Exception as e:
        print(f"Error loading Whisper model: {e}")
        raise


def _cuda_available():
    """Check if CUDA is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


@app.call_tool()
async def transcribe_audio(
    file_path: str,
    language: str = "en",
    verbose: bool = False,
) -> ToolResult:
    """
    Transcribe an audio file using OpenAI Whisper.

    Args:
        file_path: Path to audio file (MP3, WAV, FLAC, OGG, M4A, etc.)
        language: Language code (e.g., 'en', 'pt-BR', 'ja'). Defaults to 'en'.
        verbose: Show transcription progress. Defaults to False.

    Returns:
        Transcript text with timing information.
    """
    if not whisper_available:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Error: Whisper not available. Check container logs.",
                )
            ],
            is_error=True,
        )

    try:
        if not os.path.exists(file_path):
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Error: File not found: {file_path}",
                    )
                ],
                is_error=True,
            )

        print(f"Transcribing audio: {file_path}")
        model = load_whisper_model()

        result = model.transcribe(
            file_path,
            language=language,
            verbose=verbose,
        )

        if not result or not result.get("text"):
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="No speech detected in audio file.",
                    )
                ],
                is_error=False,
            )

        transcript = result["text"].strip()
        segments_info = ""
        if result.get("segments"):
            segments_info = "\n\nDetailed segments:\n"
            for seg in result["segments"]:
                segments_info += f"[{seg['start']:.2f}s - {seg['end']:.2f}s] {seg['text']}\n"

        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Transcript:\n\n{transcript}{segments_info}",
                )
            ],
            is_error=False,
        )

    except Exception as e:
        return ToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            is_error=True,
        )


@app.call_tool()
async def transcribe_video(
    file_path: str,
    language: str = "en",
    verbose: bool = False,
) -> ToolResult:
    """
    Transcribe a video file by extracting audio using OpenAI Whisper.

    Args:
        file_path: Path to video file (MP4, MOV, AVI, MKV, WebM, etc.)
        language: Language code (e.g., 'en', 'pt-BR', 'ja'). Defaults to 'en'.
        verbose: Show transcription progress. Defaults to False.

    Returns:
        Transcript text with timing information.
    """
    if not whisper_available:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Error: Whisper not available. Check container logs.",
                )
            ],
            is_error=True,
        )

    try:
        if not os.path.exists(file_path):
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Error: File not found: {file_path}",
                    )
                ],
                is_error=True,
            )

        print(f"Transcribing video (extracting audio first): {file_path}")

        # Whisper can handle video files directly, but we'll extract audio for efficiency
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_audio_path = tmp_audio.name

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    file_path,
                    "-ab",
                    "160k",
                    "-ac",
                    "2",
                    "-ar",
                    "16000",
                    "-vn",
                    tmp_audio_path,
                ],
                check=True,
                capture_output=True,
            )

            # Transcribe extracted audio
            return await transcribe_audio(
                file_path=tmp_audio_path,
                language=language,
                verbose=verbose,
            )

        finally:
            if os.path.exists(tmp_audio_path):
                os.remove(tmp_audio_path)

    except subprocess.CalledProcessError as e:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Error: Failed to extract audio from video: {e.stderr.decode() if e.stderr else str(e)}",
                )
            ],
            is_error=True,
        )
    except Exception as e:
        return ToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            is_error=True,
        )


@app.call_tool()
async def list_supported_languages() -> ToolResult:
    """List all supported language codes for transcription."""
    lang_list = json.dumps(SUPPORTED_LANGUAGES, indent=2)
    return ToolResult(
        content=[
            TextContent(
                type="text",
                text=f"Supported languages ({len(SUPPORTED_LANGUAGES)}+):\n\n{lang_list}\n\nUse the language code (e.g., 'en', 'pt-BR', 'ja') as the language parameter.\n\nNote: Whisper supports 99+ languages total.",
            )
        ],
        is_error=False,
    )


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="transcribe_audio",
            description="Transcribe an audio file to text using OpenAI Whisper (local, no credentials needed)",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the audio file (MP3, WAV, FLAC, OGG, M4A, etc.)",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g., 'en', 'pt-BR', 'ja'). Default: en",
                        "default": "en",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Show transcription progress. Default: false",
                        "default": False,
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="transcribe_video",
            description="Transcribe a video file to text using OpenAI Whisper (extracts audio automatically)",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the video file (MP4, MOV, AVI, MKV, WebM, etc.)",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g., 'en', 'pt-BR', 'ja'). Default: en",
                        "default": "en",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": "Show transcription progress. Default: false",
                        "default": False,
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="list_supported_languages",
            description="List all supported language codes for transcription",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_HTTP_PORT", 8000))
    host = os.getenv("MCP_HOST", "0.0.0.0")

    print(f"Starting Transcriber MCP server on {host}:{port}")
    print(f"Whisper model: {MODEL_SIZE}")
    print(f"Models directory: {MODELS_DIR}")
    print(f"CUDA available: {_cuda_available()}")

    uvicorn.run(app, host=host, port=port)
