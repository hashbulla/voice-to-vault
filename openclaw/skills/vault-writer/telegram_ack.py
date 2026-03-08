"""
telegram_ack.py — Enriched Telegram confirmation and error messaging for voice-to-vault.

Sends structured ACK messages on success and detailed error notifications on failure.
All messages are sent via the Telegram Bot API sendMessage endpoint.
"""

from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


def _esc(value: str) -> str:
    """Escape a string for safe insertion into an HTML parse_mode Telegram message."""
    return html.escape(value, quote=False)


def _send_telegram_message(chat_id: str | int, text: str) -> None:
    """
    Send a text message via Telegram Bot API using MarkdownV2 parse mode.

    Args:
        chat_id: Telegram chat ID to send the message to.
        text: Message text (plain text — no MarkdownV2 escaping, HTML mode used).

    Raises:
        RuntimeError: If the API returns a non-200 status or ok=false.
    """
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.post(url, json=payload)

    if response.status_code != 200:
        logger.error(
            "Telegram sendMessage failed: HTTP %d — %s",
            response.status_code,
            response.text[:200],
        )
        raise RuntimeError(f"Telegram sendMessage failed: HTTP {response.status_code}")

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendMessage returned ok=false: {data}")

    logger.debug("Telegram ACK sent to chat_id=%s", chat_id)


def _format_duration(duration_sec: float) -> str:
    """
    Format duration in seconds to 'Xm Ys' or 'Xs' string.
    """
    total = int(duration_sec)
    minutes, seconds = divmod(total, 60)
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def send_success_ack(
    chat_id: str | int,
    title_slug: str,
    domain: str,
    tags: list[str],
    projects: list[str],
    summary: str,
    duration_sec: float,
    word_count: int,
    timestamp: datetime | None = None,
) -> None:
    """
    Send enriched success acknowledgement message to Telegram.

    Args:
        chat_id: Telegram chat ID of the sender.
        title_slug: Kebab-case note slug.
        domain: Classified domain (Engineering / Cyber / Business / Life).
        tags: List of tags (will be rendered as #hashtags).
        projects: List of project names (will be rendered as wikilinks).
        summary: One-sentence AI summary of the note.
        duration_sec: Audio duration in seconds from Whisper.
        word_count: Word count of the transcript.
        timestamp: Datetime of capture (defaults to now UTC).
    """
    if timestamp is None:
        timestamp = datetime.now(tz=timezone.utc).astimezone()

    ts_str = timestamp.strftime("%Y-%m-%d %H:%M")
    duration_str = _format_duration(duration_sec)
    tags_str = " ".join(f"#{_esc(t)}" for t in tags) if tags else "—"
    project_str = (
        "[[" + "]], [[".join(_esc(p) for p in projects) + "]]" if projects else "—"
    )

    message = (
        f"✅ <b>Note captured</b> — {ts_str}\n"
        f"\n"
        f"📋 <code>{_esc(title_slug)}</code>\n"
        f"🗂 Domain: <b>{_esc(domain)}</b>\n"
        f"🏷 Tags: {tags_str}\n"
        f"📁 Project: {project_str}\n"
        f"⏱ Duration: {duration_str}  |  📝 Words: {word_count}\n"
        f"🔍 Summary: <i>{_esc(summary)}</i>\n"
        f"\n"
        f"📥 Status: inbox — awaiting nightly processing"
    )

    _send_telegram_message(chat_id, message)
    logger.info("Success ACK sent to chat_id=%s for slug=%s", chat_id, title_slug)


def send_error_notification(
    chat_id: str | int,
    step: int,
    reason: str,
) -> None:
    """
    Send a pipeline failure notification to Telegram.

    Called on any unhandled exception in the pipeline steps.
    Does NOT raise on failure — best-effort notification only.

    Args:
        chat_id: Telegram chat ID of the sender.
        step: Pipeline step number that failed (1-10).
        reason: Short human-readable error description.
    """
    message = (
        f"❌ <b>Pipeline failed at step {step}:</b> {_esc(reason)}\n"
        f"\n"
        f"Check container logs for full traceback."
    )

    try:
        _send_telegram_message(chat_id, message)
        logger.info("Error notification sent to chat_id=%s (step %d)", chat_id, step)
    except Exception as exc:  # noqa: BLE001
        # Notification failure must not mask the original error
        logger.error("Failed to send error notification: %s", exc)
