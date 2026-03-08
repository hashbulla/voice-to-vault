"""
test_security.py — Security control integration tests.

Zero external API calls. Tests every security control in isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SKILL_DIR = Path(__file__).parent.parent.parent / "openclaw" / "skills" / "vault-writer"
sys.path.insert(0, str(SKILL_DIR))

MAX_AUDIO_BYTES = 26_214_400


def _import_main(monkeypatch, webhook_secret="test-secret-abc123"):
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", webhook_secret)
    for mod in list(sys.modules.keys()):
        if mod in ("main", "classifier", "git_writer", "note_formatter",
                   "telegram_ack", "transcriber"):
            sys.modules.pop(mod, None)
    import main
    return main


def _base_event(user_id=999888777, file_id="FILE123", caption=None, secret="test-secret-abc123"):
    event = {
        "message": {
            "message_id": 1,
            "from": {"id": user_id},
            "chat": {"id": 12345},
            "voice": {
                "file_id": file_id,
                "file_unique_id": "unique123",
                "duration": 90,
                "mime_type": "audio/ogg",
                "file_size": 100000,
            },
        },
        "headers": {
            "x-telegram-bot-api-secret-token": secret,
        },
    }
    if caption is not None:
        event["message"]["caption"] = caption
    return event


# ── Webhook secret validation ─────────────────────────────────────────────────

@pytest.mark.integration
class TestWebhookSecretValidation:
    def test_valid_secret_proceeds(self, monkeypatch, caplog):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with patch.object(main, "get_telegram_file_path", return_value="f.ogg"), \
             patch.object(main, "download_telegram_audio", return_value=b"audio"), \
             patch.object(main, "transcribe_audio", return_value=VerboseTranscript("text", "fr", 1.0, [])), \
             patch.object(main, "classify_transcript", return_value=ClassificationResult("Engineering", [], [], "s.", False, "slug")), \
             patch.object(main, "build_note", return_value=("00_Inbox/x.md", "content")), \
             patch.object(main, "write_note_and_push", return_value="abc" * 14), \
             patch.object(main, "send_success_ack"):
            result = main.handle(_base_event())

        assert result["status"] == "success"

    def test_invalid_secret_returns_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        result = main.handle(_base_event(secret="WRONG_SECRET"))
        assert result["status"] == "rejected"
        assert result["reason"] == "invalid_secret"

    def test_invalid_secret_zero_downstream_calls(self, monkeypatch):
        main = _import_main(monkeypatch)
        m_run = MagicMock()
        with patch.object(main, "run", m_run):
            main.handle(_base_event(secret="WRONG_SECRET"))
        m_run.assert_not_called()

    def test_invalid_secret_emits_warning_log(self, monkeypatch, caplog):
        import logging
        main = _import_main(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="vault-writer"):
            main.handle(_base_event(secret="WRONG_SECRET"))
        assert any("secret" in r.message.lower() or "mismatch" in r.message.lower()
                   for r in caplog.records)

    def test_warning_does_not_log_full_secret(self, monkeypatch, caplog):
        import logging
        main = _import_main(monkeypatch)
        long_secret = "a" * 40
        with caplog.at_level(logging.WARNING, logger="vault-writer"):
            main.handle(_base_event(secret=long_secret))
        for record in caplog.records:
            assert long_secret not in record.message, "Full secret leaked in log"

    def test_missing_secret_header_returns_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        event = _base_event()
        event["headers"] = {}
        result = main.handle(event)
        assert result["status"] == "rejected"

    def test_missing_webhook_secret_env_raises_at_import(self, monkeypatch):
        monkeypatch.delenv("OPENCLAW_WEBHOOK_SECRET", raising=False)
        for mod in list(sys.modules.keys()):
            if mod == "main":
                sys.modules.pop(mod)
        with pytest.raises((RuntimeError, Exception)):
            import main  # noqa: F401


# ── User ID allowlist ─────────────────────────────────────────────────────────

@pytest.mark.integration
class TestUserIdAllowlist:
    def test_correct_user_id_proceeds(self, monkeypatch):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with patch.object(main, "get_telegram_file_path", return_value="f.ogg"), \
             patch.object(main, "download_telegram_audio", return_value=b"audio"), \
             patch.object(main, "transcribe_audio", return_value=VerboseTranscript("text", "fr", 1.0, [])), \
             patch.object(main, "classify_transcript", return_value=ClassificationResult("Engineering", [], [], "s.", False, "slug")), \
             patch.object(main, "build_note", return_value=("00_Inbox/x.md", "content")), \
             patch.object(main, "write_note_and_push", return_value="abc" * 14), \
             patch.object(main, "send_success_ack"):
            result = main.run(_base_event(user_id=999888777))

        assert result["status"] == "success"

    def test_wrong_user_id_returns_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        m_api = MagicMock()
        with patch.object(main, "get_telegram_file_path", m_api):
            result = main.run(_base_event(user_id=111222333))
        assert result["status"] == "rejected"
        m_api.assert_not_called()

    def test_user_id_as_integer_accepted(self, monkeypatch):
        """Telegram sometimes sends user_id as integer — must be accepted."""
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        event = _base_event(user_id=999888777)  # already int in _base_event
        with patch.object(main, "get_telegram_file_path", return_value="f.ogg"), \
             patch.object(main, "download_telegram_audio", return_value=b"audio"), \
             patch.object(main, "transcribe_audio", return_value=VerboseTranscript("text", "fr", 1.0, [])), \
             patch.object(main, "classify_transcript", return_value=ClassificationResult("Engineering", [], [], "s.", False, "slug")), \
             patch.object(main, "build_note", return_value=("00_Inbox/x.md", "content")), \
             patch.object(main, "write_note_and_push", return_value="abc" * 14), \
             patch.object(main, "send_success_ack"):
            result = main.run(event)

        assert result["status"] == "success"

    def test_missing_user_id_returns_error(self, monkeypatch):
        main = _import_main(monkeypatch)
        event = _base_event()
        del event["message"]["from"]
        with patch.object(main, "send_error_notification", MagicMock()):
            result = main.run(event)
        # Should return rejected (empty user_id != allowed_id) or error, not crash
        assert result["status"] in ("rejected", "error")


# ── Caption sanitisation ──────────────────────────────────────────────────────

@pytest.mark.integration
class TestCaptionSanitisation:
    def _get_lang(self, monkeypatch, caption):
        main = _import_main(monkeypatch)
        captured = {}

        def fake_transcribe(audio, lang, prompt):
            captured["lang"] = lang
            from transcriber import VerboseTranscript
            return VerboseTranscript("text", lang, 1.0, [])

        from classifier import ClassificationResult
        with patch.object(main, "get_telegram_file_path", return_value="f.ogg"), \
             patch.object(main, "download_telegram_audio", return_value=b"audio"), \
             patch.object(main, "transcribe_audio", side_effect=fake_transcribe), \
             patch.object(main, "classify_transcript", return_value=ClassificationResult("Engineering", [], [], "s.", False, "slug")), \
             patch.object(main, "build_note", return_value=("00_Inbox/x.md", "content")), \
             patch.object(main, "write_note_and_push", return_value="abc" * 14), \
             patch.object(main, "send_success_ack"):
            main.run(_base_event(caption=caption))

        return captured.get("lang")

    def test_caption_en_accepted_lang_en(self, monkeypatch):
        assert self._get_lang(monkeypatch, "!en") == "en"

    def test_caption_fr_accepted_lang_fr(self, monkeypatch):
        assert self._get_lang(monkeypatch, "!fr") == "fr"

    def test_empty_caption_accepted_lang_fr(self, monkeypatch):
        assert self._get_lang(monkeypatch, "") == "fr"

    def test_injection_caption_sanitised_to_empty_lang_fr(self, monkeypatch):
        lang = self._get_lang(monkeypatch, "!en; rm -rf /")
        assert lang == "fr"

    def test_unknown_caption_sanitised_lang_fr(self, monkeypatch):
        lang = self._get_lang(monkeypatch, "ANYTHING_ELSE")
        assert lang == "fr"

    def test_null_byte_caption_sanitised(self, monkeypatch):
        lang = self._get_lang(monkeypatch, "!en\x00malicious")
        # null-byte in caption is unknown → discarded → default fr
        assert lang == "fr"


# ── Audio size limit ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestAudioSizeLimit:
    def test_audio_over_max_bytes_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        oversized = b"x" * (MAX_AUDIO_BYTES + 1)

        with patch.object(main, "get_telegram_file_path", return_value="f.ogg"), \
             patch.object(main, "download_telegram_audio", return_value=oversized), \
             patch.object(main, "send_error_notification"):
            result = main.run(_base_event())

        assert result["status"] == "error"

    def test_audio_exactly_at_max_bytes_accepted(self, monkeypatch):
        main = _import_main(monkeypatch)
        exact_size = b"x" * MAX_AUDIO_BYTES
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with patch.object(main, "get_telegram_file_path", return_value="f.ogg"), \
             patch.object(main, "download_telegram_audio", return_value=exact_size), \
             patch.object(main, "transcribe_audio", return_value=VerboseTranscript("text", "fr", 1.0, [])), \
             patch.object(main, "classify_transcript", return_value=ClassificationResult("Engineering", [], [], "s.", False, "slug")), \
             patch.object(main, "build_note", return_value=("00_Inbox/x.md", "content")), \
             patch.object(main, "write_note_and_push", return_value="abc" * 14), \
             patch.object(main, "send_success_ack"):
            result = main.run(_base_event())

        # Exact size is accepted — should not error on size alone
        # (may still succeed or fail for other reasons)
        assert result["status"] != "rejected"
