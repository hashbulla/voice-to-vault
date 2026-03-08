"""
test_transcriber.py — Unit tests for transcriber module.

All OpenAI API calls are mocked — zero real network activity.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from transcriber import VerboseTranscript, transcribe_audio

MAX_AUDIO_BYTES = 26_214_400  # 25 MB default


def _make_mock_response(
    text="Bonjour monde.", language="fr", duration=10.0, segments=None
):
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.language = language
    mock_resp.duration = duration
    mock_resp.segments = segments or []
    return mock_resp


class TestTranscribeAudio:
    def _setup_mock(self, mocker, response=None):
        if response is None:
            response = _make_mock_response()
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = response
        mocker.patch("transcriber.openai.OpenAI", return_value=mock_client)
        return mock_client

    def test_audio_exceeding_max_bytes_no_client_side_guard(self, mocker):
        """transcribe_audio has no client-side MAX_AUDIO_BYTES guard — size
        validation happens upstream in main.py (step 2 error handling).
        This test confirms the function does NOT raise on oversized input alone
        and that the API call IS made (Whisper will reject if truly invalid)."""
        mock_client = self._setup_mock(mocker)
        oversized = b"x" * (MAX_AUDIO_BYTES + 1)
        # Should NOT raise a client-side size error — function proceeds to API
        transcribe_audio(oversized, "fr", "")
        mock_client.audio.transcriptions.create.assert_called_once()

    def test_lang_fr_passed_to_whisper_api(self, mocker):
        mock_client = self._setup_mock(mocker)
        audio = b"fake ogg audio data"
        transcribe_audio(audio, "fr", "")
        call_kwargs = mock_client.audio.transcriptions.create.call_args
        assert (
            call_kwargs.kwargs.get("language") == "fr" or call_kwargs.args[0]
            if call_kwargs.args
            else True
        )
        # Check via kwargs
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["language"] == "fr"

    def test_lang_en_passed_to_whisper_api(self, mocker):
        mock_client = self._setup_mock(mocker)
        transcribe_audio(b"fake audio", "en", "")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["language"] == "en"

    def test_response_format_verbose_json_always_used(self, mocker):
        mock_client = self._setup_mock(mocker)
        transcribe_audio(b"fake audio", "fr", "")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["response_format"] == "verbose_json"

    def test_whisper_prompt_env_var_passed_when_set(self, mocker, monkeypatch):
        monkeypatch.setenv("WHISPER_PROMPT", "Kubernetes, RKE2, OpenClaw")
        mock_client = self._setup_mock(mocker)
        transcribe_audio(b"fake audio", "fr", "Kubernetes, RKE2, OpenClaw")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["prompt"] == "Kubernetes, RKE2, OpenClaw"

    def test_whisper_prompt_empty_when_env_absent(self, mocker):
        mock_client = self._setup_mock(mocker)
        transcribe_audio(b"fake audio", "fr", "")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["prompt"] == ""

    def test_duration_and_text_extracted_from_verbose_json(self, mocker):
        resp = _make_mock_response(text="Mon texte.", duration=37.5)
        self._setup_mock(mocker, response=resp)
        result = transcribe_audio(b"fake audio", "fr", "")
        assert result.text == "Mon texte."
        assert result.duration == 37.5

    def test_returns_verbose_transcript_dataclass(self, mocker):
        self._setup_mock(mocker)
        result = transcribe_audio(b"fake audio", "fr", "")
        assert isinstance(result, VerboseTranscript)

    def test_segments_extracted(self, mocker):
        segs = [{"id": 0, "text": "Hello"}]
        resp = _make_mock_response(segments=segs)
        self._setup_mock(mocker, response=resp)
        result = transcribe_audio(b"fake audio", "fr", "")
        assert result.segments == segs

    def test_empty_segments_defaults_to_list(self, mocker):
        resp = _make_mock_response(segments=None)
        resp.segments = None
        self._setup_mock(mocker, response=resp)
        result = transcribe_audio(b"fake audio", "fr", "")
        assert result.segments == []

    def test_model_is_whisper_1(self, mocker):
        mock_client = self._setup_mock(mocker)
        transcribe_audio(b"fake audio", "fr", "")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        assert kwargs["model"] == "whisper-1"

    def test_api_error_propagates(self, mocker):
        import openai as openai_module

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = (
            openai_module.APIConnectionError(
                request=MagicMock(), message="connection failed"
            )
        )
        mocker.patch("transcriber.openai.OpenAI", return_value=mock_client)
        with pytest.raises(openai_module.APIConnectionError):
            transcribe_audio(b"fake audio", "fr", "")
