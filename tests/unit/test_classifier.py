"""
test_classifier.py — Unit tests for classifier module.

All Anthropic API calls are mocked — zero real network activity.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

from classifier import (
    ClassificationResult,
    _parse_classifier_response,
    _sanitise_slug,
    classify_transcript,
)


# ── _sanitise_slug ─────────────────────────────────────────────────────────────

class TestSanitiseSlug:
    def test_uppercase_converted_to_lowercase(self):
        assert _sanitise_slug("MySlug") == "myslug"

    def test_spaces_replaced_with_hyphens(self):
        assert _sanitise_slug("my slug here") == "my-slug-here"

    def test_special_characters_removed(self):
        result = _sanitise_slug("hello!@#world")
        assert "!" not in result
        assert "@" not in result
        assert "#" not in result

    def test_more_than_6_words_truncated(self):
        result = _sanitise_slug("one-two-three-four-five-six-seven-eight")
        parts = result.split("-")
        assert len(parts) <= 6

    def test_exactly_6_words_preserved(self):
        result = _sanitise_slug("one-two-three-four-five-six")
        assert result == "one-two-three-four-five-six"

    def test_multiple_consecutive_hyphens_collapsed(self):
        result = _sanitise_slug("foo---bar")
        assert "--" not in result
        assert result == "foo-bar"

    def test_leading_hyphens_stripped(self):
        result = _sanitise_slug("-leading-hyphen")
        assert not result.startswith("-")

    def test_trailing_hyphens_stripped(self):
        result = _sanitise_slug("trailing-hyphen-")
        assert not result.endswith("-")

    def test_all_lowercase_clean_slug_unchanged(self):
        assert _sanitise_slug("kubernetes-operator-design") == "kubernetes-operator-design"

    def test_empty_string_returns_empty(self):
        # _sanitise_slug("") → "" (caller handles defaulting)
        result = _sanitise_slug("")
        assert result == ""

    def test_numbers_preserved(self):
        result = _sanitise_slug("k8s-rke2-setup")
        assert result == "k8s-rke2-setup"


# ── _parse_classifier_response ────────────────────────────────────────────────

class TestParseClassifierResponse:
    def _valid_payload(self, **overrides) -> dict:
        base = {
            "domain": "Engineering",
            "projects": [],
            "tags": ["k8s", "operator"],
            "summary": "Un résumé de la note.",
            "needs_review": False,
            "title_slug": "kubernetes-operator-design",
        }
        base.update(overrides)
        return base

    def test_valid_json_returns_correct_result(self):
        raw = json.dumps(self._valid_payload())
        result = _parse_classifier_response(raw, "fr")
        assert isinstance(result, ClassificationResult)
        assert result.domain == "Engineering"
        assert result.title_slug == "kubernetes-operator-design"
        assert result.needs_review is False

    def test_json_in_markdown_fences_is_stripped_and_parsed(self):
        payload = self._valid_payload()
        raw = f"```json\n{json.dumps(payload)}\n```"
        result = _parse_classifier_response(raw, "fr")
        assert result.domain == "Engineering"

    def test_json_in_plain_fences_is_stripped(self):
        payload = self._valid_payload()
        raw = f"```\n{json.dumps(payload)}\n```"
        result = _parse_classifier_response(raw, "fr")
        assert result.domain == "Engineering"

    def test_missing_domain_raises_value_error(self):
        payload = self._valid_payload()
        del payload["domain"]
        with pytest.raises(ValueError, match="domain"):
            _parse_classifier_response(json.dumps(payload), "fr")

    def test_missing_tags_raises_value_error(self):
        payload = self._valid_payload()
        del payload["tags"]
        with pytest.raises(ValueError, match="tags"):
            _parse_classifier_response(json.dumps(payload), "fr")

    def test_missing_summary_raises_value_error(self):
        payload = self._valid_payload()
        del payload["summary"]
        with pytest.raises(ValueError, match="summary"):
            _parse_classifier_response(json.dumps(payload), "fr")

    def test_missing_needs_review_raises_value_error(self):
        payload = self._valid_payload()
        del payload["needs_review"]
        with pytest.raises(ValueError, match="needs_review"):
            _parse_classifier_response(json.dumps(payload), "fr")

    def test_missing_title_slug_raises_value_error(self):
        payload = self._valid_payload()
        del payload["title_slug"]
        with pytest.raises(ValueError, match="title_slug"):
            _parse_classifier_response(json.dumps(payload), "fr")

    def test_invalid_domain_defaults_to_engineering(self, caplog):
        payload = self._valid_payload(domain="Finance")
        with caplog.at_level(logging.WARNING, logger="classifier"):
            result = _parse_classifier_response(json.dumps(payload), "fr")
        assert result.domain == "Engineering"
        assert "Engineering" in caplog.text or "Finance" in caplog.text

    def test_tags_truncated_to_5_items(self):
        payload = self._valid_payload(tags=["a", "b", "c", "d", "e", "f", "g"])
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert len(result.tags) == 5

    def test_tags_5_items_not_truncated(self):
        payload = self._valid_payload(tags=["a", "b", "c", "d", "e"])
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert len(result.tags) == 5

    def test_title_slug_sanitised_special_chars_removed(self):
        payload = self._valid_payload(title_slug="Hello World!")
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert "!" not in result.title_slug
        assert " " not in result.title_slug

    def test_empty_title_slug_defaults_to_untitled_note(self):
        payload = self._valid_payload(title_slug="")
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert result.title_slug == "untitled-note"

    def test_needs_review_true_preserved(self):
        payload = self._valid_payload(needs_review=True)
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert result.needs_review is True

    def test_needs_review_false_preserved(self):
        payload = self._valid_payload(needs_review=False)
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert result.needs_review is False

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="non-JSON"):
            _parse_classifier_response("this is not json", "fr")

    def test_all_valid_domains_accepted(self):
        for domain in ["Life", "Business", "Engineering", "Cyber"]:
            payload = self._valid_payload(domain=domain)
            result = _parse_classifier_response(json.dumps(payload), "fr")
            assert result.domain == domain

    def test_title_slug_truncated_to_6_words(self):
        payload = self._valid_payload(
            title_slug="one-two-three-four-five-six-seven-eight"
        )
        result = _parse_classifier_response(json.dumps(payload), "fr")
        assert len(result.title_slug.split("-")) <= 6


# ── classify_transcript ───────────────────────────────────────────────────────

class TestClassifyTranscript:
    def _make_mock_client(self, mocker, response_text: str):
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=response_text)]
        mock_client.messages.create.return_value = mock_message
        mocker.patch("classifier.anthropic.Anthropic", return_value=mock_client)
        return mock_client

    def _valid_response(self) -> str:
        return json.dumps({
            "domain": "Engineering",
            "projects": [],
            "tags": ["k8s", "operator"],
            "summary": "Un résumé.",
            "needs_review": False,
            "title_slug": "kubernetes-operator",
        })

    def test_system_prompt_sent_unchanged(self, mocker):
        from classifier import CLASSIFIER_SYSTEM_PROMPT
        mock_client = self._make_mock_client(mocker, self._valid_response())
        classify_transcript("test transcript", "fr")
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == CLASSIFIER_SYSTEM_PROMPT

    def test_language_code_included_in_user_message(self, mocker):
        mock_client = self._make_mock_client(mocker, self._valid_response())
        classify_transcript("test transcript", "fr")
        call_kwargs = mock_client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "fr" in user_content

    def test_language_en_included_in_user_message(self, mocker):
        mock_client = self._make_mock_client(mocker, self._valid_response())
        classify_transcript("test transcript", "en")
        call_kwargs = mock_client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "en" in user_content

    def test_api_error_propagates(self, mocker):
        import anthropic as anthropic_module
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic_module.APIConnectionError(
            request=MagicMock()
        )
        mocker.patch("classifier.anthropic.Anthropic", return_value=mock_client)
        with pytest.raises(anthropic_module.APIConnectionError):
            classify_transcript("test transcript", "fr")

    def test_non_json_response_raises_value_error(self, mocker):
        self._make_mock_client(mocker, "This is not JSON at all.")
        with pytest.raises(ValueError):
            classify_transcript("test transcript", "fr")

    def test_returns_classification_result(self, mocker):
        self._make_mock_client(mocker, self._valid_response())
        result = classify_transcript("test transcript", "fr")
        assert isinstance(result, ClassificationResult)
