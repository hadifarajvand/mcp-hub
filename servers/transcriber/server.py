#!/usr/bin/env python3
"""
Transcriber MCP Server — Google Speech Recognition via pyTranscriber
Transcribes audio and video files using Google's built-in speech recognition.
No credentials required — uses Google Translate/Speech services.
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
    from pytranscriber.control.ctr_autosub import CtrAutosub
    google_speech_available = True
except ImportError:
    print("Warning: pyTranscriber Autosub (Google Speech) not available yet")
    google_speech_available = False

from mcp.server import Server
from mcp.types import Tool, TextContent, ToolResult

app = Server("transcriber-mcp")

# Supported languages (Google Speech-to-Text supports 100+ languages)
SUPPORTED_LANGUAGES = {
    "en": "English",
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "es": "Spanish",
    "es-ES": "Spanish (Spain)",
    "es-MX": "Spanish (Mexico)",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ar": "Arabic",
    "ar-SA": "Arabic (Saudi Arabia)",
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
    "th": "Thai",
    "uk": "Ukrainian",
}


@app.call_tool()
async def transcribe_audio(
    file_path: str,
    language: str = "en",
    output_format: str = "text",
) -> ToolResult:
    """
    Transcribe an audio file using Google's speech recognition.

    Args:
        file_path: Path to audio file (MP3, WAV, FLAC, OGG, M4A, etc.)
        language: Language code (e.g., 'en', 'pt-BR', 'ja'). Defaults to 'en'.
        output_format: Output format: 'text' or 'srt' (subtitles). Defaults to 'text'.

    Returns:
        Transcript text or SRT subtitles.
    """
    if not google_speech_available:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Error: pyTranscriber Google Speech module not available. Check container logs.",
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

        print(f"Transcribing audio with Google Speech: {file_path}")

        # Create output file paths
        base_path = Path(file_path).stem
        output_dir = Path(tempfile.gettempdir())
        txt_output = str(output_dir / f"{base_path}.txt")
        srt_output = str(output_dir / f"{base_path}.srt")

        # Use Google Speech (Autosub) via pyTranscriber
        try:
            result = CtrAutosub.generate_subtitles(
                source_path=file_path,
                src_language=language,
                outputTXT=txt_output,
                outputSRT=srt_output,
            )

            if result is None or result == -1:
                return ToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text="Error: Transcription failed or was canceled.",
                        )
                    ],
                    is_error=True,
                )

            # Read the output file
            if output_format == "srt" and os.path.exists(srt_output):
                with open(srt_output, 'r', encoding='utf-8') as f:
                    content = f.read()
                return ToolResult(
                    content=[TextContent(type="text", text=content)],
                    is_error=False,
                )
            elif os.path.exists(txt_output):
                with open(txt_output, 'r', encoding='utf-8') as f:
                    content = f.read()
                return ToolResult(
                    content=[TextContent(type="text", text=content)],
                    is_error=False,
                )
            else:
                return ToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text="No output generated.",
                        )
                    ],
                    is_error=False,
                )

        finally:
            # Cleanup temp files
            if os.path.exists(txt_output):
                os.remove(txt_output)
            if os.path.exists(srt_output):
                os.remove(srt_output)

    except Exception as e:
        return ToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            is_error=True,
        )


@app.call_tool()
async def transcribe_video(
    file_path: str,
    language: str = "en",
    output_format: str = "text",
) -> ToolResult:
    """
    Transcribe a video file by extracting audio using Google's speech recognition.

    Args:
        file_path: Path to video file (MP4, MOV, AVI, MKV, WebM, etc.)
        language: Language code (e.g., 'en', 'pt-BR', 'ja'). Defaults to 'en'.
        verbose: Show transcription progress. Defaults to False.

    Returns:
        Transcript text with timing information.
    """
    if not google_speech_available:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Error: pyTranscriber Google Speech module not available. Check container logs.",
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
                output_format=output_format,
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
                text=f"Supported languages ({len(SUPPORTED_LANGUAGES)}+):\n\n{lang_list}\n\nUse the language code (e.g., 'en', 'pt-BR', 'ja') as the language parameter.\n\nNote: Google Speech-to-Text supports 100+ languages total.",
            )
        ],
        is_error=False,
    )


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="transcribe_audio",
            description="Transcribe an audio file to text using Google's built-in speech recognition (no credentials needed)",
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
                    "output_format": {
                        "type": "string",
                        "description": "Output format: 'text' for plain text or 'srt' for subtitle format. Default: text",
                        "default": "text",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="transcribe_video",
            description="Transcribe a video file to text using Google's built-in speech recognition (extracts audio automatically)",
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
                    "output_format": {
                        "type": "string",
                        "description": "Output format: 'text' for plain text or 'srt' for subtitle format. Default: text",
                        "default": "text",
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
    print(f"Using Google's built-in speech recognition (via pyTranscriber)")

    uvicorn.run(app, host=host, port=port)
