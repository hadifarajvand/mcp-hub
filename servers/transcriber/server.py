#!/usr/bin/env python3
"""
Transcriber MCP Server — Google Cloud Speech-to-Text
Transcribes audio and video files using Google's speech recognition API.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

# Try to import Google Cloud Speech
try:
    from google.cloud import speech
    google_cloud_available = True
except ImportError:
    print("Warning: Google Cloud Speech not installed")
    google_cloud_available = False

from mcp.server import Server
from mcp.types import TextContent, Tool

app = Server("transcriber-mcp")

# Supported languages
SUPPORTED_LANGUAGES = {
    "en": "English",
    "en-US": "English (US)",
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
    "vi": "Vietnamese",
}


@app.call_tool()
async def transcribe_audio(
    file_path: str,
    language: str = "en",
):
    """
    Transcribe an audio file using Google Cloud Speech-to-Text.

    Args:
        file_path: Path to audio file (MP3, WAV, FLAC, OGG, M4A, etc.)
        language: Language code (e.g., 'en', 'pt-BR', 'ja'). Defaults to 'en'.

    Returns:
        Transcript text.
    """
    if not google_cloud_available:
        return [
            TextContent(
                type="text",
                text="Error: Google Cloud Speech not available. Check GOOGLE_APPLICATION_CREDENTIALS.",
            )
        ]

    if not os.path.exists(file_path):
        return [
            TextContent(
                type="text",
                text=f"Error: File not found: {file_path}",
            )
        ]

    try:
        print(f"Transcribing audio: {file_path}")

        client = speech.SpeechClient()

        with open(file_path, "rb") as audio_file:
            content = audio_file.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=language,
        )

        response = client.recognize(config=config, audio=audio)

        if not response.results:
            return [
                TextContent(
                    type="text",
                    text="No transcription result found.",
                )
            ]

        transcript = ""
        for result in response.results:
            for alternative in result.alternatives:
                transcript += alternative.transcript + " "

        return [
            TextContent(
                type="text",
                text=transcript.strip(),
            )
        ]

    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Error: {str(e)}",
            )
        ]


@app.call_tool()
async def transcribe_video(
    file_path: str,
    language: str = "en",
):
    """
    Transcribe a video file by extracting audio using Google Cloud Speech-to-Text.

    Args:
        file_path: Path to video file (MP4, MOV, AVI, MKV, WebM, etc.)
        language: Language code (e.g., 'en', 'pt-BR', 'ja'). Defaults to 'en'.

    Returns:
        Transcript text.
    """
    if not google_cloud_available:
        return [
            TextContent(
                type="text",
                text="Error: Google Cloud Speech not available.",
            )
        ]

    if not os.path.exists(file_path):
        return [
            TextContent(
                type="text",
                text=f"Error: File not found: {file_path}",
            )
        ]

    try:
        print(f"Transcribing video (extracting audio first): {file_path}")

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
            )

        finally:
            if os.path.exists(tmp_audio_path):
                os.remove(tmp_audio_path)

    except subprocess.CalledProcessError as e:
        return [
            TextContent(
                type="text",
                text=f"Error: Failed to extract audio from video: {e.stderr.decode() if e.stderr else str(e)}",
            )
        ]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Error: {str(e)}",
            )
        ]


@app.call_tool()
async def list_supported_languages():
    """List all supported language codes for transcription."""
    lang_list = json.dumps(SUPPORTED_LANGUAGES, indent=2)
    return [
        TextContent(
            type="text",
            text=f"Supported languages ({len(SUPPORTED_LANGUAGES)}+):\n\n{lang_list}\n\nUse the language code (e.g., 'en', 'pt-BR', 'ja') as the language parameter.",
        )
    ]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="transcribe_audio",
            description="Transcribe an audio file to text using Google Cloud Speech-to-Text",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to audio file (MP3, WAV, FLAC, OGG, M4A, etc.)",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g., 'en', 'pt-BR', 'ja'). Default: 'en'",
                        "default": "en",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="transcribe_video",
            description="Transcribe a video file by extracting audio using Google Cloud Speech-to-Text",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to video file (MP4, MOV, AVI, MKV, WebM, etc.)",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g., 'en', 'pt-BR', 'ja'). Default: 'en'",
                        "default": "en",
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

    uvicorn.run(app, host="0.0.0.0", port=8000)
