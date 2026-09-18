#!/usr/bin/env python3
"""
Google Speech-to-Text MCP Server
Transcribes audio and video files using Google Cloud Speech-to-Text API.
Inspired by pyTranscriber's multilingual transcription capabilities.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path
from typing import Any
from mcp.server import Server
from mcp.types import Tool, TextContent, ToolResult
import google.auth
from google.cloud import speech_v1

# FastMCP server initialization
app = Server("transcriber-mcp")

# Supported language codes (simplified set; Google Cloud Speech supports 100+)
SUPPORTED_LANGUAGES = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "es-ES": "Spanish (Spain)",
    "es-MX": "Spanish (Mexico)",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
    "ja-JP": "Japanese",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ko-KR": "Korean",
    "ru-RU": "Russian",
    "ar-SA": "Arabic",
    "hi-IN": "Hindi",
}

# Initialize Google Cloud Speech-to-Text client
try:
    speech_client = speech_v1.SpeechClient()
    credentials_available = True
except Exception as e:
    print(f"Warning: Could not initialize Google Cloud Speech client: {e}")
    print("Ensure GOOGLE_APPLICATION_CREDENTIALS is set or credentials are available.")
    credentials_available = True  # Attempt to fail gracefully at runtime


@app.call_tool()
async def transcribe_audio(
    file_path: str,
    language_code: str = "en-US",
    punctuation: bool = True,
) -> ToolResult:
    """
    Transcribe an audio file using Google Cloud Speech-to-Text.

    Args:
        file_path: Path to audio file (MP3, WAV, FLAC, OGG, etc.)
        language_code: Language code (e.g., 'en-US', 'pt-BR'). Defaults to 'en-US'.
        punctuation: Add punctuation to transcript. Defaults to True.

    Returns:
        Transcript text and confidence score.
    """
    if not credentials_available:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Error: Google Cloud credentials not available. Set GOOGLE_APPLICATION_CREDENTIALS environment variable.",
                )
            ],
            is_error=True,
        )

    try:
        # Validate file exists
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

        # Read audio file
        with open(file_path, "rb") as audio_file:
            content = audio_file.read()

        # Determine encoding from file extension
        file_ext = Path(file_path).suffix.lower()
        encoding_map = {
            ".mp3": speech_v1.RecognitionConfig.AudioEncoding.MP3,
            ".wav": speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            ".flac": speech_v1.RecognitionConfig.AudioEncoding.FLAC,
            ".ogg": speech_v1.RecognitionConfig.AudioEncoding.OGG_OPUS,
        }
        encoding = encoding_map.get(
            file_ext, speech_v1.RecognitionConfig.AudioEncoding.MP3
        )

        # Configure recognition
        config = speech_v1.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=16000,
            language_code=language_code,
            enable_automatic_punctuation=punctuation,
        )

        audio = speech_v1.RecognitionAudio(content=content)

        # Perform transcription
        operation = speech_client.long_running_recognize(config=config, audio=audio)
        response = operation.result(timeout=300)

        # Extract transcript and confidence
        transcripts = []
        for result in response.results:
            if result.alternatives:
                alt = result.alternatives[0]
                transcripts.append(
                    {
                        "text": alt.transcript,
                        "confidence": alt.confidence,
                    }
                )

        if not transcripts:
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="No speech detected in audio file.",
                    )
                ],
                is_error=False,
            )

        result_text = "\n".join([t["text"] for t in transcripts])
        avg_confidence = (
            sum(t["confidence"] for t in transcripts) / len(transcripts)
        )

        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Transcript (confidence: {avg_confidence:.2%}):\n\n{result_text}",
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
    language_code: str = "en-US",
    punctuation: bool = True,
) -> ToolResult:
    """
    Transcribe a video file by extracting audio and using Google Cloud Speech-to-Text.

    Args:
        file_path: Path to video file (MP4, MOV, AVI, MKV, etc.)
        language_code: Language code (e.g., 'en-US', 'pt-BR'). Defaults to 'en-US'.
        punctuation: Add punctuation to transcript. Defaults to True.

    Returns:
        Transcript text and confidence score.
    """
    if not credentials_available:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text="Error: Google Cloud credentials not available. Set GOOGLE_APPLICATION_CREDENTIALS environment variable.",
                )
            ],
            is_error=True,
        )

    try:
        # Validate file exists
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

        # Extract audio from video using ffmpeg
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
                language_code=language_code,
                punctuation=punctuation,
            )

        finally:
            # Clean up temporary audio file
            if os.path.exists(tmp_audio_path):
                os.remove(tmp_audio_path)

    except subprocess.CalledProcessError as e:
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Error: Failed to extract audio from video: {e.stderr.decode()}",
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
                text=f"Supported languages:\n\n{lang_list}\n\nUse the language code (e.g., 'en-US') as the language_code parameter.",
            )
        ],
        is_error=False,
    )


# Register tools
@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="transcribe_audio",
            description="Transcribe an audio file (MP3, WAV, FLAC, OGG) to text using Google Cloud Speech-to-Text",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the audio file",
                    },
                    "language_code": {
                        "type": "string",
                        "description": "Language code (e.g., 'en-US', 'pt-BR'). Default: en-US",
                        "default": "en-US",
                    },
                    "punctuation": {
                        "type": "boolean",
                        "description": "Add punctuation to transcript. Default: true",
                        "default": True,
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="transcribe_video",
            description="Transcribe a video file (MP4, MOV, AVI, MKV) by extracting audio and using Google Cloud Speech-to-Text",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the video file",
                    },
                    "language_code": {
                        "type": "string",
                        "description": "Language code (e.g., 'en-US', 'pt-BR'). Default: en-US",
                        "default": "en-US",
                    },
                    "punctuation": {
                        "type": "boolean",
                        "description": "Add punctuation to transcript. Default: true",
                        "default": True,
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
    uvicorn.run(app, host=host, port=port)
