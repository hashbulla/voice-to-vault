"""
test_main.py — Unit tests for main.py pipeline orchestration.

All external dependencies are mocked. Tests cover security controls,
step failure handling, and the full success path.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ── Module-level import helper ────────────────────────────────────────────────


def _import_main(monkeypatch, webhook_secret="test-secret-abc123"):
    """Import main module with required env set."""
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", webhook_secret)
    # Force re-import since module reads env at import time
    for mod in list(sys.modules.keys()):
        if mod in (
            "main",
            "classifier",
            "git_writer",
            "note_formatter",
            "telegram_ack",
            "transcriber",
        ):
            sys.modules.pop(mod, None)
    import main

    return main


def _base_event(
    user_id="999888777", file_id="FILE123", caption=None, secret="test-secret-abc123"
):
    event = {
        "message": {
            "message_id": 1,
            "from": {"id": int(user_id) if user_id.isdigit() else user_id},
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


# ── Security: user allowlist ───────────────────────────────────────────────────


class TestUserAllowlist:
    def test_non_whitelisted_user_returns_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        event = _base_event(user_id="111000111")

        with (
            patch.object(main, "get_telegram_file_path", MagicMock()) as m_get,
            patch.object(main, "download_telegram_audio", MagicMock()) as m_dl,
            patch.object(main, "transcribe_audio", MagicMock()) as m_tr,
            patch.object(main, "classify_transcript", MagicMock()) as m_cl,
            patch.object(main, "write_note_and_push", MagicMock()) as m_git,
        ):
            result = main.run(event)

        assert result["status"] == "rejected"
        m_get.assert_not_called()
        m_dl.assert_not_called()
        m_tr.assert_not_called()
        m_cl.assert_not_called()
        m_git.assert_not_called()

    def test_whitelisted_user_proceeds(self, monkeypatch):
        main = _import_main(monkeypatch)

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(main, "transcribe_audio") as m_tr,
            patch.object(main, "classify_transcript") as m_cl,
            patch.object(
                main,
                "build_note",
                return_value=("00_Inbox/2026-03-08-slug.md", "content"),
            ),
            patch.object(main, "write_note_and_push", return_value="abc" * 14),
            patch.object(main, "send_success_ack"),
        ):
            from transcriber import VerboseTranscript
            from classifier import ClassificationResult

            m_tr.return_value = VerboseTranscript("text", "fr", 90.0, [])
            m_cl.return_value = ClassificationResult(
                "Engineering", [], ["k8s"], "Summary.", False, "my-slug"
            )
            result = main.run(_base_event())

        assert result["status"] == "success"


# ── Missing file_id ────────────────────────────────────────────────────────────


class TestMissingFileId:
    def test_missing_voice_file_id_returns_error_step_1(self, monkeypatch):
        main = _import_main(monkeypatch)
        event = _base_event()
        event["message"]["voice"] = {}  # no file_id

        with patch.object(main, "send_error_notification") as m_err:
            result = main.run(event)

        assert result["status"] == "error"
        assert result["step"] == 1
        m_err.assert_called_once()


# ── Caption / language detection ──────────────────────────────────────────────


class TestCaptionLanguageDetection:
    def _run_with_caption(self, monkeypatch, caption):
        main = _import_main(monkeypatch)
        captured = {}

        def fake_transcribe(audio_bytes, language, whisper_prompt):
            captured["lang"] = language
            from transcriber import VerboseTranscript

            return VerboseTranscript("text", language, 90.0, [])

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(main, "transcribe_audio", side_effect=fake_transcribe),
            patch.object(main, "classify_transcript") as m_cl,
            patch.object(
                main,
                "build_note",
                return_value=("00_Inbox/2026-03-08-slug.md", "content"),
            ),
            patch.object(main, "write_note_and_push", return_value="abc" * 14),
            patch.object(main, "send_success_ack"),
        ):
            from classifier import ClassificationResult

            m_cl.return_value = ClassificationResult(
                "Engineering", [], ["k8s"], "Summary.", False, "my-slug"
            )
            main.run(_base_event(caption=caption))

        return captured.get("lang")

    def test_caption_en_sets_lang_en(self, monkeypatch):
        lang = self._run_with_caption(monkeypatch, "!en")
        assert lang == "en"

    def test_caption_fr_sets_lang_fr(self, monkeypatch):
        lang = self._run_with_caption(monkeypatch, "!fr")
        assert lang == "fr"

    def test_unknown_caption_discarded_lang_defaults_to_fr(self, monkeypatch):
        lang = self._run_with_caption(monkeypatch, "!de")
        assert lang == "fr"

    def test_empty_caption_lang_defaults_to_fr(self, monkeypatch):
        lang = self._run_with_caption(monkeypatch, "")
        assert lang == "fr"


# ── Step failure handling ─────────────────────────────────────────────────────


class TestStepFailures:
    def _run_with_step_failure(self, monkeypatch, fail_step: int):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        patches = {
            "get_telegram_file_path": MagicMock(return_value="voice/file.ogg"),
            "download_telegram_audio": MagicMock(return_value=b"audio"),
            "transcribe_audio": MagicMock(
                return_value=VerboseTranscript("text", "fr", 90.0, [])
            ),
            "classify_transcript": MagicMock(
                return_value=ClassificationResult(
                    "Engineering", [], ["k8s"], "Summary.", False, "slug"
                )
            ),
            "build_note": MagicMock(
                return_value=("00_Inbox/2026-03-08-slug.md", "content")
            ),
            "write_note_and_push": MagicMock(return_value="abc" * 14),
            "send_success_ack": MagicMock(),
            "send_error_notification": MagicMock(),
        }

        step_to_fn = {
            4: "transcribe_audio",
            5: "classify_transcript",
            7: "write_note_and_push",
        }
        if fail_step in step_to_fn:
            patches[step_to_fn[fail_step]].side_effect = RuntimeError(
                f"Step {fail_step} failed"
            )

        with patch.multiple(main, **patches):
            result = main.run(_base_event())

        return result, patches["send_error_notification"]

    def test_step_4_whisper_failure_sends_error_notification(self, monkeypatch):
        result, m_err = self._run_with_step_failure(monkeypatch, 4)
        assert result["status"] == "error"
        assert result["step"] == 4
        m_err.assert_called_once()
        call_args = m_err.call_args
        assert call_args.args[1] == 4 or call_args.kwargs.get("step") == 4

    def test_step_5_haiku_failure_sends_error_notification(self, monkeypatch):
        result, m_err = self._run_with_step_failure(monkeypatch, 5)
        assert result["status"] == "error"
        assert result["step"] == 5
        m_err.assert_called_once()

    def test_step_7_git_failure_sends_error_notification(self, monkeypatch):
        result, m_err = self._run_with_step_failure(monkeypatch, 7)
        assert result["status"] == "error"
        m_err.assert_called_once()

    def test_step_4_failure_does_not_proceed_to_classification(self, monkeypatch):
        main = _import_main(monkeypatch)
        m_classify = MagicMock()

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(
                main, "transcribe_audio", side_effect=RuntimeError("Whisper down")
            ),
            patch.object(main, "classify_transcript", m_classify),
            patch.object(main, "send_error_notification"),
        ):
            main.run(_base_event())

        m_classify.assert_not_called()

    def test_step_9_ack_failure_is_non_fatal(self, monkeypatch):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(
                main,
                "transcribe_audio",
                return_value=VerboseTranscript("text", "fr", 90.0, []),
            ),
            patch.object(
                main,
                "classify_transcript",
                return_value=ClassificationResult(
                    "Engineering", [], ["k8s"], "Summary.", False, "slug"
                ),
            ),
            patch.object(
                main,
                "build_note",
                return_value=("00_Inbox/2026-03-08-slug.md", "content"),
            ),
            patch.object(main, "write_note_and_push", return_value="abc" * 14),
            patch.object(
                main, "send_success_ack", side_effect=RuntimeError("Telegram down")
            ),
        ):
            result = main.run(_base_event())

        # ACK failure is non-fatal — pipeline should still return success
        assert result["status"] == "success"


# ── _require_env ──────────────────────────────────────────────────────────────


class TestRequireEnv:
    def test_raises_if_required_var_missing(self, monkeypatch):
        main = _import_main(monkeypatch)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            main.run(_base_event())

    def test_passes_when_all_vars_present(self, monkeypatch):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(
                main,
                "transcribe_audio",
                return_value=VerboseTranscript("text", "fr", 90.0, []),
            ),
            patch.object(
                main,
                "classify_transcript",
                return_value=ClassificationResult(
                    "Engineering", [], ["k8s"], "Summary.", False, "slug"
                ),
            ),
            patch.object(
                main,
                "build_note",
                return_value=("00_Inbox/2026-03-08-slug.md", "content"),
            ),
            patch.object(main, "write_note_and_push", return_value="abc" * 14),
            patch.object(main, "send_success_ack"),
        ):
            result = main.run(_base_event())

        assert result["status"] == "success"


# ── Full success path ─────────────────────────────────────────────────────────


class TestFullSuccessPath:
    def test_returns_all_required_fields(self, monkeypatch):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(
                main,
                "transcribe_audio",
                return_value=VerboseTranscript("hello world", "fr", 95.3, []),
            ),
            patch.object(
                main,
                "classify_transcript",
                return_value=ClassificationResult(
                    "Engineering", [], ["k8s"], "Summary.", False, "kubernetes-operator"
                ),
            ),
            patch.object(
                main,
                "build_note",
                return_value=("00_Inbox/2026-03-08-kubernetes-operator.md", "content"),
            ),
            patch.object(
                main,
                "write_note_and_push",
                return_value="abc123def456abc123def456abc123def456abc1",
            ),
            patch.object(main, "send_success_ack"),
        ):
            result = main.run(_base_event())

        assert result["status"] == "success"
        assert result["file_path"] == "00_Inbox/2026-03-08-kubernetes-operator.md"
        assert result["commit_sha"] == "abc123def456abc123def456abc123def456abc1"
        assert result["domain"] == "Engineering"
        assert result["title_slug"] == "kubernetes-operator"
        assert result["needs_review"] is False
        assert result["duration_sec"] == 95.3
        assert "word_count" in result


# ── handle() — webhook secret validation ─────────────────────────────────────


class TestHandleWebhookSecret:
    def test_valid_secret_proceeds(self, monkeypatch):
        main = _import_main(monkeypatch)
        from transcriber import VerboseTranscript
        from classifier import ClassificationResult

        with (
            patch.object(main, "get_telegram_file_path", return_value="voice/file.ogg"),
            patch.object(main, "download_telegram_audio", return_value=b"audio"),
            patch.object(
                main,
                "transcribe_audio",
                return_value=VerboseTranscript("text", "fr", 90.0, []),
            ),
            patch.object(
                main,
                "classify_transcript",
                return_value=ClassificationResult(
                    "Engineering", [], ["k8s"], "Summary.", False, "slug"
                ),
            ),
            patch.object(
                main,
                "build_note",
                return_value=("00_Inbox/2026-03-08-slug.md", "content"),
            ),
            patch.object(main, "write_note_and_push", return_value="abc" * 14),
            patch.object(main, "send_success_ack"),
        ):
            result = main.handle(_base_event(secret="test-secret-abc123"))

        assert result["status"] == "success"

    def test_invalid_secret_returns_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        result = main.handle(_base_event(secret="wrong-secret"))
        assert result["status"] == "rejected"
        assert result["reason"] == "invalid_secret"

    def test_missing_secret_header_returns_rejected(self, monkeypatch):
        main = _import_main(monkeypatch)
        event = _base_event()
        event["headers"] = {}  # no secret header
        result = main.handle(event)
        assert result["status"] == "rejected"

    def test_invalid_secret_zero_downstream_calls(self, monkeypatch):
        main = _import_main(monkeypatch)
        m_run = MagicMock()
        with patch.object(main, "run", m_run):
            main.handle(_base_event(secret="wrong-secret"))
        m_run.assert_not_called()
