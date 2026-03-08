"""
test_note_formatter.py — Pure unit tests for note_formatter module.

Zero mocks needed — this module has no external dependencies.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone


from classifier import ClassificationResult
from note_formatter import (
    _format_projects_as_wikilinks,
    _format_tags_yaml,
    build_note,
)
from transcriber import VerboseTranscript


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_transcript(text="Bonjour, voici ma note.", duration=42.0, language="fr"):
    return VerboseTranscript(text=text, language=language, duration=duration, segments=[])


def _make_classification(
    domain="Engineering",
    projects=None,
    tags=None,
    summary="Un résumé.",
    needs_review=False,
    title_slug="ma-note-de-test",
):
    return ClassificationResult(
        domain=domain,
        projects=projects or [],
        tags=tags or ["k8s", "devops"],
        summary=summary,
        needs_review=needs_review,
        title_slug=title_slug,
    )


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter fields as a dict of raw string values."""
    lines = content.split("\n")
    assert lines[0] == "---", f"Expected ---  got: {lines[0]!r}"
    end = lines.index("---", 1)
    fm = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


# ── _format_projects_as_wikilinks ──────────────────────────────────────────────

class TestFormatProjectsAsWikilinks:
    def test_empty_list_returns_empty_yaml_array(self):
        assert _format_projects_as_wikilinks([]) == "[]"

    def test_single_project(self):
        result = _format_projects_as_wikilinks(["my-project"])
        # Function wraps all wikilinks in a YAML inline array: [[[my-project]]]
        assert result == "[[[my-project]]]"

    def test_multiple_projects(self):
        result = _format_projects_as_wikilinks(["alpha", "beta"])
        assert result == "[[[alpha]], [[beta]]]"

    def test_three_projects(self):
        result = _format_projects_as_wikilinks(["a", "b", "c"])
        assert result == "[[[a]], [[b]], [[c]]]"


# ── _format_tags_yaml ─────────────────────────────────────────────────────────

class TestFormatTagsYaml:
    def test_empty_list_returns_empty_yaml_array(self):
        assert _format_tags_yaml([]) == "[]"

    def test_single_tag(self):
        assert _format_tags_yaml(["k8s"]) == "[k8s]"

    def test_multiple_tags_comma_separated(self):
        result = _format_tags_yaml(["k8s", "operator", "devsecops"])
        assert result == "[k8s, operator, devsecops]"

    def test_tags_not_quoted(self):
        result = _format_tags_yaml(["my-tag"])
        assert '"' not in result
        assert "'" not in result


# ── build_note ────────────────────────────────────────────────────────────────

class TestBuildNote:
    def test_french_lang_produces_resume_ia_prefix(self):
        t = _make_transcript()
        c = _make_classification(summary="Mon résumé ici.")
        _, body = build_note(t, c, lang="fr")
        assert "Résumé IA :" in body

    def test_french_lang_does_not_produce_ai_summary(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        assert "AI Summary" not in body

    def test_english_lang_produces_ai_summary_prefix(self):
        t = _make_transcript(text="Here is my note.", language="en")
        c = _make_classification()
        _, body = build_note(t, c, lang="en")
        assert "AI Summary :" in body

    def test_english_lang_does_not_produce_resume_ia(self):
        t = _make_transcript(text="Here is my note.", language="en")
        c = _make_classification()
        _, body = build_note(t, c, lang="en")
        assert "Résumé IA" not in body

    def test_needs_review_true_sets_status_needs_review(self):
        t = _make_transcript()
        c = _make_classification(needs_review=True)
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["status"] == "needs-review"

    def test_needs_review_false_sets_status_inbox(self):
        t = _make_transcript()
        c = _make_classification(needs_review=False)
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["status"] == "inbox"

    def test_empty_projects_produces_empty_yaml_array(self):
        t = _make_transcript()
        c = _make_classification(projects=[])
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["projects"] == "[]"

    def test_non_empty_projects_produces_wikilinks(self):
        t = _make_transcript()
        c = _make_classification(projects=["MyProject"])
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert "[[MyProject]]" in fm["projects"]

    def test_file_path_format(self):
        t = _make_transcript()
        c = _make_classification(title_slug="my-slug")
        file_path, _ = build_note(t, c, lang="fr")
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        assert file_path == f"00_Inbox/{today}-my-slug.md"

    def test_file_path_starts_with_00_inbox(self):
        t = _make_transcript()
        c = _make_classification()
        file_path, _ = build_note(t, c, lang="fr")
        assert file_path.startswith("00_Inbox/")

    def test_file_path_ends_with_md(self):
        t = _make_transcript()
        c = _make_classification()
        file_path, _ = build_note(t, c, lang="fr")
        assert file_path.endswith(".md")

    def test_uuid_in_frontmatter_is_valid_uuid4(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        note_id = fm["id"]
        parsed = uuid.UUID(note_id, version=4)
        assert str(parsed) == note_id

    def test_date_field_is_iso8601_with_timezone(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        date_str = fm["date"]
        # Should contain timezone offset (+HH:MM or Z)
        assert re.search(r"[+\-]\d{2}:\d{2}$|Z$", date_str), f"No timezone in: {date_str}"

    def test_duration_sec_formatted_to_1_decimal(self):
        t = _make_transcript(duration=95.347)
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["duration_sec"] == "95.3"

    def test_duration_sec_zero(self):
        t = _make_transcript(duration=0.0)
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["duration_sec"] == "0.0"

    def test_raw_transcript_appears_verbatim_after_separator(self):
        transcript_text = "Voici ma note exacte avec des mots précis."
        t = _make_transcript(text=transcript_text)
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        # Find separator and check transcript after it
        parts = body.split("---\n\n")
        assert len(parts) >= 2
        # Last part should start with the transcript text
        assert parts[-1].startswith(transcript_text)

    def test_transcript_never_truncated(self):
        long_text = "Mot " * 500  # 500 words
        t = _make_transcript(text=long_text)
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        assert long_text.strip() in body

    def test_source_field_defaults_to_openclaw(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["source"] == "openclaw"

    def test_source_field_custom_value(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr", source="manual")
        fm = _parse_frontmatter(body)
        assert fm["source"] == "manual"

    def test_lang_field_in_frontmatter(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["lang"] == "fr"

    def test_domain_field_in_frontmatter(self):
        t = _make_transcript()
        c = _make_classification(domain="Cyber")
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["domain"] == "Cyber"

    def test_transcript_model_in_frontmatter(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        fm = _parse_frontmatter(body)
        assert fm["transcript_model"] == "whisper-1"

    def test_body_contains_separator_between_summary_and_transcript(self):
        t = _make_transcript()
        c = _make_classification()
        _, body = build_note(t, c, lang="fr")
        assert "\n---\n" in body
