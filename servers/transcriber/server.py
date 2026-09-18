#!/usr/bin/env python3
"""
Transcriber MCP Server — Google Cloud Speech-to-Text
Transcribes audio and video files using Google's speech recognition API.
Requires GOOGLE_APPLICATION_CREDENTIALS environment variable to be set.
"""

import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path

try:
    from google.cloud import speech
    GOOGLE_CLOUD_AVAILABLE = True
except ImportError:
    GOOGLE_CLOUD_AVAILABLE = False
    print("Warning: Google Cloud Speech SDK not available")

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Transcriber MCP")

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


class TranscribeRequest(BaseModel):
    file_path: str
    language: str = "en"


class ListLanguagesRequest(BaseModel):
    pass


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "transcriber-mcp"}


@app.post("/transcribe_audio")
async def transcribe_audio(request: TranscribeRequest):
    """Transcribe an audio file using Google Cloud Speech-to-Text"""
    if not GOOGLE_CLOUD_AVAILABLE:
        return {
            "error": "Google Cloud Speech not available. Check GOOGLE_APPLICATION_CREDENTIALS.",
            "success": False,
        }

    if not os.path.exists(request.file_path):
        return {
            "error": f"File not found: {request.file_path}",
            "success": False,
        }

    try:
        print(f"Transcribing audio: {request.file_path} (language: {request.language})")

        client = speech.SpeechClient()

        # Read audio file
        with open(request.file_path, "rb") as audio_file:
            content = audio_file.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=request.language,
        )

        # Perform transcription
        response = client.recognize(config=config, audio=audio)

        if not response.results:
            return {
                "transcript": "",
                "success": True,
                "message": "No speech detected in audio",
            }

        # Combine all transcription results
        transcript_parts = []
        for result in response.results:
            for alternative in result.alternatives:
                transcript_parts.append(alternative.transcript)

        transcript = " ".join(transcript_parts)
        return {
            "transcript": transcript,
            "success": True,
            "confidence": (
                sum(alt.confidence for result in response.results
                    for alt in result.alternatives) / max(len([alt for result in response.results for alt in result.alternatives]), 1)
            ),
        }

    except Exception as e:
        return {
            "error": f"Transcription failed: {str(e)}",
            "success": False,
        }


@app.post("/transcribe_video")
async def transcribe_video(request: TranscribeRequest):
    """Transcribe a video file by extracting audio first"""
    if not GOOGLE_CLOUD_AVAILABLE:
        return {
            "error": "Google Cloud Speech not available.",
            "success": False,
        }

    if not os.path.exists(request.file_path):
        return {
            "error": f"File not found: {request.file_path}",
            "success": False,
        }

    try:
        print(f"Transcribing video (extracting audio first): {request.file_path}")

        # Create temporary audio file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            tmp_audio_path = tmp_audio.name

        try:
            # Extract audio from video using ffmpeg
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    request.file_path,
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
                timeout=300,
            )

            # Transcribe the extracted audio
            audio_request = TranscribeRequest(
                file_path=tmp_audio_path,
                language=request.language,
            )
            return await transcribe_audio(audio_request)

        finally:
            if os.path.exists(tmp_audio_path):
                try:
                    os.remove(tmp_audio_path)
                except:
                    pass

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        return {
            "error": f"Failed to extract audio from video: {stderr}",
            "success": False,
        }
    except Exception as e:
        return {
            "error": f"Video transcription failed: {str(e)}",
            "success": False,
        }


@app.post("/list_supported_languages")
async def list_supported_languages(request: ListLanguagesRequest = None):
    """List all supported language codes for transcription"""
    return {
        "languages": SUPPORTED_LANGUAGES,
        "count": len(SUPPORTED_LANGUAGES),
        "message": f"Supported {len(SUPPORTED_LANGUAGES)}+ languages. Use language codes like 'en', 'pt-BR', 'ja'",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_HTTP_PORT", "8000"))
    host = os.getenv("MCP_HOST", "0.0.0.0")
    print(f"Starting Transcriber MCP server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
