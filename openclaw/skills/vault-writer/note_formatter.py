"""
note_formatter.py — Obsidian markdown note assembly for voice-to-vault pipeline.

Implements Option A note structure:
  YAML frontmatter → AI summary blockquote → hr → raw transcript
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classifier import ClassificationResult
    from transcriber import VerboseTranscript


def _format_projects_as_wikilinks(projects: list[str]) -> str:
    """
    Convert project name list to Obsidian wikilink YAML array.

    Returns '[]' for empty lists, or YAML inline list of [[wikilinks]].
    """
    if not projects:
        return "[]"
    links = [f"[[{p}]]" for p in projects]
    return "[" + ", ".join(links) + "]"


def _format_tags_yaml(tags: list[str]) -> str:
    """
    Format tags as YAML inline list for frontmatter.
    """
    if not tags:
        return "[]"
    return "[" + ", ".join(tags) + "]"


def build_note(
    transcript: "VerboseTranscript",
    classification: "ClassificationResult",
    lang: str,
    source: str = "openclaw",
) -> tuple[str, str]:
    """
    Assemble a complete Obsidian markdown note from transcript and classification.

    Args:
        transcript: VerboseTranscript from Whisper API.
        classification: ClassificationResult from Claude Haiku.
        lang: Language code ('fr' or 'en').
        source: Source system identifier (default: 'openclaw').

    Returns:
        Tuple of (file_path, note_content):
          - file_path: relative path within vault, e.g. '00_Inbox/2024-01-15-my-note.md'
          - note_content: complete markdown string ready to write to disk.
    """
    now = datetime.now(tz=timezone.utc).astimezone()
    date_iso = now.isoformat()
    date_prefix = now.strftime("%Y-%m-%d")
    note_id = str(uuid.uuid4())

    status = "needs-review" if classification.needs_review else "inbox"

    projects_yaml = _format_projects_as_wikilinks(classification.projects)
    tags_yaml = _format_tags_yaml(classification.tags)

    frontmatter = f"""---
id: {note_id}
date: {date_iso}
type: voice-note
lang: {lang}
source: {source}
status: {status}
domain: {classification.domain}
projects: {projects_yaml}
tags: {tags_yaml}
duration_sec: {transcript.duration:.1f}
transcript_model: whisper-1
---"""

    summary_label = "Résumé IA" if lang == "fr" else "AI Summary"
    summary_block = f"> **{summary_label} :** {classification.summary}"

    body = f"{frontmatter}\n{summary_block}\n\n---\n\n{transcript.text}\n"

    file_path = f"00_Inbox/{date_prefix}-{classification.title_slug}.md"
    return file_path, body
