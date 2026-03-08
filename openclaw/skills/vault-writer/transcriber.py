"""
transcriber.py — OpenAI Whisper API wrapper for voice-to-vault pipeline.

Downloads OGG audio from Telegram CDN and transcribes it using whisper-1.
Returns VerboseTranscript with text, duration, segments, and detected language.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass

import httpx
import openai

logger = logging.getLogger(__name__)


@dataclass
class VerboseTranscript:
    text: str
    language: str
    duration: float
    segments: list[dict]


def download_telegram_audio(file_path: str, bot_token: str) -> bytes:
    """
    Download audio file from Telegram CDN using the Telegram Bot API.

    Args:
        file_path: Telegram file_path string returned by getFile endpoint.
        bot_token: Telegram bot token from TELEGRAM_BOT_TOKEN env var.

    Returns:
        Raw bytes of the OGG audio file.

    Raises:
        RuntimeError: If the download fails or returns non-200 status.
    """
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    logger.info("Downloading audio from Telegram CDN: %s", url)

    with httpx.Client(timeout=60.0) as client:
        response = client.get(url)
        if response.status_code != 200:
            raise RuntimeError(
                f"Telegram CDN download failed: HTTP {response.status_code} — {response.text[:200]}"
            )
        audio_bytes = response.content

    logger.info("Downloaded %d bytes from Telegram CDN", len(audio_bytes))
    return audio_bytes


def get_telegram_file_path(file_id: str, bot_token: str) -> str:
    """
    Resolve a Telegram file_id to a downloadable file_path via getFile API.

    Args:
        file_id: The file_id from the voice message object.
        bot_token: Telegram bot token.

    Returns:
        file_path string for CDN download.

    Raises:
        RuntimeError: If the API call fails or file_path is missing.
    """
    url = f"https://api.telegram.org/bot{bot_token}/getFile"
    logger.info("Resolving file_id %s via getFile", file_id)

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params={"file_id": file_id})

    if response.status_code != 200:
        raise RuntimeError(
            f"getFile API failed: HTTP {response.status_code} — {response.text[:200]}"
        )

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"getFile returned ok=false: {data}")

    file_path = data["result"].get("file_path")
    if not file_path:
        raise RuntimeError(f"getFile response missing file_path: {data}")

    logger.info("Resolved file_path: %s", file_path)
    return file_path


def transcribe_audio(
    audio_bytes: bytes,
    language: str,
    whisper_prompt: str,
) -> VerboseTranscript:
    """
    Transcribe audio bytes using OpenAI Whisper API (whisper-1 model).

    Uses verbose_json response format to capture duration and segments
    alongside the full transcript text.

    Args:
        audio_bytes: Raw OGG audio bytes downloaded from Telegram CDN.
        language: ISO-639-1 language code ('fr' or 'en').
        whisper_prompt: Vocabulary hint string from WHISPER_PROMPT env var.

    Returns:
        VerboseTranscript dataclass with text, language, duration, segments.

    Raises:
        openai.OpenAIError: On API-level errors.
        RuntimeError: On unexpected response structure.
    """
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Write bytes to temp file; Whisper API requires a file-like object
    # with a recognisable audio extension — use .ogg
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        logger.info(
            "Sending %d bytes to Whisper API (lang=%s, model=whisper-1)",
            len(audio_bytes),
            language,
        )
        with open(tmp_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language=language,
                prompt=whisper_prompt,
                response_format="verbose_json",
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # openai SDK returns a Transcription object when response_format=verbose_json
    if not hasattr(response, "text"):
        raise RuntimeError(f"Unexpected Whisper response structure: {response}")

    transcript = VerboseTranscript(
        text=response.text,
        language=getattr(response, "language", language),
        duration=float(getattr(response, "duration", 0.0)),
        segments=getattr(response, "segments", []) or [],
    )

    logger.info(
        "Transcription complete: %.1fs, %d chars, %d segments",
        transcript.duration,
        len(transcript.text),
        len(transcript.segments),
    )
    return transcript
