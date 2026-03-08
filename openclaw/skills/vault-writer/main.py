"""
main.py — Core vault-writer skill for voice-to-vault pipeline.

Entry point invoked by OpenClaw on every Telegram voice message event.
Implements the full 10-step pipeline:
  1. Receive OpenClaw event payload
  2. Download OGG from Telegram CDN
  3. Detect language override (!en caption)
  4. Transcribe via OpenAI Whisper API
  5. Classify via Claude Haiku
  6. Assemble Obsidian markdown note
  7. Write to vault repo
  8. Git commit + push via Deploy Key
  9. Send enriched Telegram ACK
  10. Error handling at every step with Telegram notifications
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime, timezone

from classifier import classify_transcript
from git_writer import write_note_and_push
from note_formatter import build_note
from telegram_ack import send_error_notification, send_success_ack
from transcriber import (
    VerboseTranscript,
    download_telegram_audio,
    get_telegram_file_path,
    transcribe_audio,
)

# Configure structured logging — OpenClaw captures stderr/stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("vault-writer")


def _count_words(text: str) -> int:
    return len(text.split())


def _require_env(*keys: str) -> None:
    """
    Raise EnvironmentError if any required environment variable is missing.
    """
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )


def run(event: dict) -> dict:
    """
    Execute the full voice-to-vault pipeline for a single Telegram voice message.

    Args:
        event: OpenClaw event payload. Expected structure:
          {
            "message": {
              "message_id": int,
              "from": {"id": int, ...},
              "chat": {"id": int, ...},
              "voice": {
                "file_id": str,
                "file_unique_id": str,
                "duration": int,
                "mime_type": str,
                "file_size": int
              },
              "caption": str | None   # optional — "!en" triggers English mode
            }
          }

    Returns:
        Dict with pipeline result metadata for OpenClaw logging.
    """
    # ── Pre-flight checks ─────────────────────────────────────────────────────
    _require_env(
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "VAULT_REPO",
        "VAULT_DEPLOY_KEY_PATH",
    )

    message = event.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    sender_id = str(message.get("from", {}).get("id", ""))
    voice = message.get("voice", {})
    caption = (message.get("caption") or "").strip()

    if not chat_id:
        raise ValueError("Event missing message.chat.id")

    # ── Security: reject messages from non-whitelisted users ──────────────────
    allowed_id = os.environ["TELEGRAM_ALLOWED_USER_ID"]
    if sender_id != allowed_id:
        logger.warning("Rejected message from unauthorized user_id=%s", sender_id)
        return {"status": "rejected", "reason": "unauthorized_user"}

    file_id = voice.get("file_id")
    if not file_id:
        logger.error("Event has no voice.file_id — not a voice message?")
        send_error_notification(chat_id, 1, "Event missing voice.file_id")
        return {"status": "error", "step": 1}

    # ── Step 1: Event received ────────────────────────────────────────────────
    logger.info("Pipeline start — file_id=%s, chat_id=%s", file_id, chat_id)

    # ── Step 2: Download OGG audio from Telegram CDN ──────────────────────────
    step = 2
    try:
        bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
        file_path = get_telegram_file_path(file_id, bot_token)
        audio_bytes = download_telegram_audio(file_path, bot_token)
    except Exception as exc:
        logger.error("Step %d failed: %s\n%s", step, exc, traceback.format_exc())
        send_error_notification(chat_id, step, str(exc)[:200])
        return {"status": "error", "step": step, "error": str(exc)}

    # ── Step 3: Detect language override ─────────────────────────────────────
    step = 3
    try:
        lang = "en" if caption.lower() == "!en" else os.environ.get("WHISPER_LANGUAGE", "fr")
        logger.info("Language selected: %s (caption=%r)", lang, caption)
    except Exception as exc:
        logger.error("Step %d failed: %s\n%s", step, exc, traceback.format_exc())
        send_error_notification(chat_id, step, str(exc)[:200])
        return {"status": "error", "step": step, "error": str(exc)}

    # ── Step 4: Transcribe via OpenAI Whisper API ─────────────────────────────
    step = 4
    try:
        whisper_prompt = os.environ.get("WHISPER_PROMPT", "")
        transcript: VerboseTranscript = transcribe_audio(audio_bytes, lang, whisper_prompt)
        logger.info(
            "Transcript: %.1fs, %d chars", transcript.duration, len(transcript.text)
        )
    except Exception as exc:
        logger.error("Step %d failed: %s\n%s", step, exc, traceback.format_exc())
        send_error_notification(chat_id, step, str(exc)[:200])
        return {"status": "error", "step": step, "error": str(exc)}

    # ── Step 5: Classify via Claude Haiku ────────────────────────────────────
    step = 5
    try:
        classification = classify_transcript(transcript.text, lang)
        logger.info(
            "Classification: domain=%s, slug=%s, needs_review=%s",
            classification.domain,
            classification.title_slug,
            classification.needs_review,
        )
    except Exception as exc:
        logger.error("Step %d failed: %s\n%s", step, exc, traceback.format_exc())
        send_error_notification(chat_id, step, str(exc)[:200])
        return {"status": "error", "step": step, "error": str(exc)}

    # ── Step 6: Assemble Obsidian markdown note ───────────────────────────────
    step = 6
    try:
        vault_file_path, note_content = build_note(transcript, classification, lang)
        logger.info("Note assembled: %s (%d bytes)", vault_file_path, len(note_content))
    except Exception as exc:
        logger.error("Step %d failed: %s\n%s", step, exc, traceback.format_exc())
        send_error_notification(chat_id, step, str(exc)[:200])
        return {"status": "error", "step": step, "error": str(exc)}

    # ── Steps 7+8: Write file and git push via Deploy Key ─────────────────────
    step = 7
    try:
        commit_sha = write_note_and_push(
            vault_file_path,
            note_content,
            classification.title_slug,
        )
        logger.info("Pushed to vault: %s (commit=%s)", vault_file_path, commit_sha[:12])
    except Exception as exc:
        logger.error("Step %d failed: %s\n%s", step, exc, traceback.format_exc())
        send_error_notification(chat_id, step, str(exc)[:200])
        return {"status": "error", "step": step, "error": str(exc)}

    # ── Step 9: Send enriched Telegram ACK ───────────────────────────────────
    step = 9
    try:
        word_count = _count_words(transcript.text)
        capture_time = datetime.now(tz=timezone.utc).astimezone()
        send_success_ack(
            chat_id=chat_id,
            title_slug=classification.title_slug,
            domain=classification.domain,
            tags=classification.tags,
            projects=classification.projects,
            summary=classification.summary,
            duration_sec=transcript.duration,
            word_count=word_count,
            timestamp=capture_time,
        )
    except Exception as exc:
        # ACK failure is non-fatal — note is already written and pushed
        logger.error("Step %d (ACK) failed: %s\n%s", step, exc, traceback.format_exc())
        # Attempt minimal fallback notification
        try:
            from telegram_ack import _send_telegram_message
            _send_telegram_message(
                chat_id,
                f"✅ Note saved: <code>{classification.title_slug}</code> (ACK formatting failed)",
            )
        except Exception:  # noqa: BLE001
            pass

    logger.info(
        "Pipeline complete — slug=%s, commit=%s",
        classification.title_slug,
        commit_sha[:12],
    )

    return {
        "status": "success",
        "file_path": vault_file_path,
        "commit_sha": commit_sha,
        "domain": classification.domain,
        "title_slug": classification.title_slug,
        "needs_review": classification.needs_review,
        "duration_sec": transcript.duration,
        "word_count": _count_words(transcript.text),
    }


# ── OpenClaw skill entry point ────────────────────────────────────────────────
# OpenClaw calls handle(event) for skill-based integrations.

def handle(event: dict) -> dict:
    """
    OpenClaw skill handler. Wraps run() with top-level exception guard.

    Any unhandled exception here is a bug — logged with full traceback.
    """
    try:
        return run(event)
    except Exception as exc:
        logger.critical(
            "Unhandled exception in vault-writer:\n%s", traceback.format_exc()
        )
        # Attempt error notification — best effort
        chat_id = (
            event.get("message", {}).get("chat", {}).get("id")
        )
        if chat_id:
            send_error_notification(chat_id, 0, f"Unhandled: {str(exc)[:150]}")
        return {"status": "fatal_error", "error": str(exc)}
