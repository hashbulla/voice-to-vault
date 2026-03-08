"""
test_telegram_ack.py — Unit tests for telegram_ack module.

All HTTP calls are mocked — zero real network activity.
Critical security tests for HTML injection in ACK messages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


from telegram_ack import (
    _format_duration,
    send_error_notification,
    send_success_ack,
)


def _make_mock_response(status_code=200, ok=True):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"ok": ok}
    mock_resp.text = ""
    return mock_resp


def _setup_httpx_mock(mocker, response=None):
    if response is None:
        response = _make_mock_response()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = response
    mocker.patch("telegram_ack.httpx.Client", return_value=mock_client)
    return mock_client


# ── Security: HTML injection tests ────────────────────────────────────────────


class TestHtmlEscaping:
    def _get_post_body(self, mocker, **kwargs) -> str:
        mock_client = _setup_httpx_mock(mocker)
        ts = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        send_success_ack(
            chat_id=123,
            title_slug=kwargs.get("title_slug", "safe-slug"),
            domain=kwargs.get("domain", "Engineering"),
            tags=kwargs.get("tags", ["k8s"]),
            projects=kwargs.get("projects", []),
            summary=kwargs.get("summary", "A safe summary."),
            duration_sec=60.0,
            word_count=10,
            timestamp=ts,
        )
        call_args = mock_client.post.call_args
        payload = (
            call_args.kwargs.get("json") or call_args.args[1]
            if call_args.args
            else call_args.kwargs["json"]
        )
        return payload["text"]

    def test_script_tag_in_slug_is_html_escaped(self, mocker):
        body = self._get_post_body(mocker, title_slug="<script>alert(1)</script>")
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    def test_ampersand_in_summary_is_html_escaped(self, mocker):
        body = self._get_post_body(mocker, summary="Life & work balance")
        assert "Life &amp; work balance" in body
        # Raw & must not appear in summary section
        assert "Life & work" not in body

    def test_gt_in_tag_is_html_escaped(self, mocker):
        body = self._get_post_body(mocker, tags=["tag>1"])
        assert "tag>1" not in body
        assert "tag&gt;1" in body

    def test_lt_in_project_is_html_escaped(self, mocker):
        """_esc uses html.escape(quote=False) so < and > are escaped, quotes are not."""
        body = self._get_post_body(mocker, projects=["<evil>"])
        assert "<evil>" not in body
        assert "&lt;evil&gt;" in body


# ── Duration formatting ────────────────────────────────────────────────────────


class TestFormatDuration:
    def test_90_seconds_formats_as_1m_30s(self):
        assert _format_duration(90) == "1m 30s"

    def test_45_seconds_formats_as_0m_45s_or_45s(self):
        result = _format_duration(45)
        # The implementation returns "Xs" if minutes==0
        assert result == "45s"

    def test_0_seconds_formats_correctly(self):
        result = _format_duration(0)
        assert result == "0s"

    def test_60_seconds_is_1m_0s(self):
        assert _format_duration(60) == "1m 0s"

    def test_3661_seconds(self):
        # 61 minutes 1 second
        assert _format_duration(3661) == "61m 1s"


# ── Functional tests ───────────────────────────────────────────────────────────


class TestSendSuccessAck:
    def test_empty_projects_renders_as_dash(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        ts = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        send_success_ack(
            chat_id=123,
            title_slug="slug",
            domain="Engineering",
            tags=["k8s"],
            projects=[],
            summary="Summary.",
            duration_sec=60.0,
            word_count=10,
            timestamp=ts,
        )
        body = mock_client.post.call_args.kwargs["json"]["text"]
        assert "—" in body

    def test_empty_tags_renders_as_dash(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        ts = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        send_success_ack(
            chat_id=123,
            title_slug="slug",
            domain="Engineering",
            tags=[],
            projects=[],
            summary="Summary.",
            duration_sec=60.0,
            word_count=10,
            timestamp=ts,
        )
        body = mock_client.post.call_args.kwargs["json"]["text"]
        # Tags line should show — not empty
        assert "Tags: —" in body

    def test_timestamp_formatted_correctly(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        ts = datetime(2026, 3, 8, 14, 35, 0, tzinfo=timezone.utc)
        send_success_ack(
            chat_id=123,
            title_slug="slug",
            domain="Engineering",
            tags=["k8s"],
            projects=[],
            summary="Summary.",
            duration_sec=60.0,
            word_count=10,
            timestamp=ts,
        )
        body = mock_client.post.call_args.kwargs["json"]["text"]
        # Timestamp should be formatted as YYYY-MM-DD HH:MM
        assert "2026-03-08" in body

    def test_parse_mode_is_html(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        ts = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        send_success_ack(
            chat_id=123,
            title_slug="slug",
            domain="Engineering",
            tags=[],
            projects=[],
            summary="Summary.",
            duration_sec=60.0,
            word_count=10,
            timestamp=ts,
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "HTML"

    def test_post_called_exactly_once(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        ts = datetime(2026, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        send_success_ack(
            chat_id=123,
            title_slug="slug",
            domain="Engineering",
            tags=[],
            projects=[],
            summary="Summary.",
            duration_sec=60.0,
            word_count=10,
            timestamp=ts,
        )
        mock_client.post.assert_called_once()


# ── Error notification tests ───────────────────────────────────────────────────


class TestSendErrorNotification:
    def test_step_number_appears_in_message(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        send_error_notification(chat_id=123, step=4, reason="Whisper failed")
        body = mock_client.post.call_args.kwargs["json"]["text"]
        assert "4" in body

    def test_reason_string_is_html_escaped(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        send_error_notification(
            chat_id=123, step=4, reason="Error <details> here & there"
        )
        body = mock_client.post.call_args.kwargs["json"]["text"]
        assert "<details>" not in body
        assert "&lt;details&gt;" in body

    def test_api_failure_does_not_raise(self, mocker):
        """send_error_notification must never raise — best-effort only."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("Network failure")
        mocker.patch("telegram_ack.httpx.Client", return_value=mock_client)
        # Should NOT raise
        send_error_notification(chat_id=123, step=4, reason="Some error")

    def test_step_0_appears_in_message(self, mocker):
        mock_client = _setup_httpx_mock(mocker)
        send_error_notification(chat_id=123, step=0, reason="Unhandled exception")
        body = mock_client.post.call_args.kwargs["json"]["text"]
        assert "0" in body
