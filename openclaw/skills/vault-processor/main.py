"""
main.py — vault-processor OpenClaw skill

Handles /process Telegram command: validates sender, sends ACK, POSTs to
the host-side trigger daemon, and handles all response cases.
"""

import logging
import os

import httpx

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_ID: str = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")
TRIGGER_SECRET: str = os.environ.get("TRIGGER_SECRET", "")
TRIGGER_DAEMON_URL: str = os.environ.get(
    "TRIGGER_DAEMON_URL", "http://host.docker.internal:9999"
)

TELEGRAM_API = "https://api.telegram.org"


def _send_telegram(chat_id: str | int, text: str, parse_mode: str = "HTML") -> None:
    """Send a Telegram message. Logs errors but never raises."""
    url = f"{TELEGRAM_API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10.0,
        )
        if not resp.is_success:
            log.error("Telegram sendMessage failed: %s %s", resp.status_code, resp.text)
    except Exception as exc:
        log.error("Telegram sendMessage exception: %s", exc)


def handle_event(event: dict) -> dict:
    """
    OpenClaw skill entry point.

    event shape (Telegram message update):
      {
        "message": {
          "from": {"id": 123456789, ...},
          "chat": {"id": 123456789, ...},
          "text": "/process"
        }
      }
    """
    message = event.get("message", {})
    sender = message.get("from", {})
    sender_id = str(sender.get("id", ""))
    chat_id = message.get("chat", {}).get("id", sender_id)

    # ── Step 1: Validate sender ────────────────────────────────────────────────
    if sender_id != str(TELEGRAM_ALLOWED_USER_ID):
        log.warning("Rejected /process from unauthorized user %s", sender_id)
        return {"status": "rejected"}

    # ── Step 2: Send immediate ACK ─────────────────────────────────────────────
    _send_telegram(
        chat_id,
        "⚙️ Vault processing started...\nI'll confirm when done. This takes ~2-3 minutes.",
    )

    # ── Step 3: POST to trigger daemon ─────────────────────────────────────────
    trigger_url = f"{TRIGGER_DAEMON_URL.rstrip('/')}/trigger"
    try:
        resp = httpx.post(
            trigger_url,
            json={"source": "telegram", "user": sender_id},
            headers={"X-Trigger-Secret": TRIGGER_SECRET},
            timeout=5.0,
        )

        # ── Step 4: Handle responses ───────────────────────────────────────────
        if resp.status_code == 202:
            # run.sh will send the completion notification — no further action needed
            log.info("Trigger accepted (202) for user %s", sender_id)

        elif resp.status_code == 409:
            _send_telegram(
                chat_id,
                "⏳ Vault processing is already running. Check back in a few minutes.",
            )
            log.info("Trigger busy (409) for user %s", sender_id)

        elif resp.status_code == 401:
            log.error(
                "Trigger auth failed (401) for user %s — check TRIGGER_SECRET config",
                sender_id,
            )
            _send_telegram(
                chat_id,
                "❌ Trigger auth failed. Check TRIGGER_SECRET config.",
            )

        else:
            log.error(
                "Unexpected trigger response %d for user %s: %s",
                resp.status_code,
                sender_id,
                resp.text,
            )
            _send_telegram(
                chat_id,
                f"❌ Trigger daemon returned unexpected status {resp.status_code}.",
            )

    except Exception as exc:
        reason = str(exc)
        log.error("Could not reach trigger daemon for user %s: %s", sender_id, reason)
        _send_telegram(
            chat_id,
            f"❌ Could not reach trigger daemon: {reason}",
        )

    return {"status": "ok"}
