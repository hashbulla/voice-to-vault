"""
classifier.py — Claude Haiku frontmatter classifier for voice-to-vault pipeline.

Sends transcript to Claude Haiku and returns structured metadata for
Obsidian frontmatter generation.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)

CLASSIFIER_SYSTEM_PROMPT = """You are a vault classifier for a French Staff AI Engineer's Obsidian second brain. Given a voice note transcript, return ONLY a valid JSON object with these fields:
{
  "domain": "one of [Life, Business, Engineering, Cyber]",
  "projects": [],
  "tags": ["3-5 lowercase kebab-case tags"],
  "summary": "one sentence in the same language as the transcript",
  "needs_review": false,
  "title_slug": "kebab-case-english-slug-max-6-words"
}
Never hallucinate project names. If no project matches, return [].
The summary must be in French if lang=fr, English if lang=en.
needs_review must be true if your classification confidence is below 0.85.
Return ONLY the JSON object — no prose, no markdown code fences."""

VALID_DOMAINS = {"Life", "Business", "Engineering", "Cyber"}


@dataclass
class ClassificationResult:
    domain: str
    projects: list[str]
    tags: list[str]
    summary: str
    needs_review: bool
    title_slug: str


def _sanitise_slug(raw: str) -> str:
    """
    Ensure title_slug is valid kebab-case, max 6 words.

    Strips any characters outside [a-z0-9-], collapses multiple dashes,
    and truncates to 6 hyphen-delimited segments.
    """
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    parts = slug.split("-")
    return "-".join(parts[:6])


def _parse_classifier_response(raw: str, lang: str) -> ClassificationResult:
    """
    Parse and validate the JSON response from Claude Haiku.

    Strips optional markdown code fences, validates domain,
    sanitises slug, and enforces tag count limits.

    Args:
        raw: Raw string content from Claude Haiku response.
        lang: Language code ('fr' or 'en') for summary language hint.

    Returns:
        ClassificationResult with validated fields.

    Raises:
        ValueError: If JSON is malformed or required fields are missing.
    """
    # Strip markdown code fences if Claude wraps despite instruction
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean.strip(), flags=re.MULTILINE)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Classifier returned non-JSON: {exc}\nRaw: {raw[:500]}") from exc

    # Validate required fields
    for key in ("domain", "projects", "tags", "summary", "needs_review", "title_slug"):
        if key not in data:
            raise ValueError(f"Classifier response missing field '{key}': {data}")

    domain = str(data["domain"]).strip()
    if domain not in VALID_DOMAINS:
        logger.warning(
            "Classifier returned invalid domain '%s', defaulting to 'Engineering'", domain
        )
        domain = "Engineering"

    tags = [str(t).lower().strip() for t in data.get("tags", [])[:5]]
    projects = [str(p).strip() for p in data.get("projects", [])]
    title_slug = _sanitise_slug(str(data.get("title_slug", "untitled-note")))

    return ClassificationResult(
        domain=domain,
        projects=projects,
        tags=tags,
        summary=str(data.get("summary", "")).strip(),
        needs_review=bool(data.get("needs_review", False)),
        title_slug=title_slug or "untitled-note",
    )


def classify_transcript(transcript: str, lang: str) -> ClassificationResult:
    """
    Send transcript to Claude Haiku and return structured classification metadata.

    Args:
        transcript: Full transcript text from Whisper.
        lang: Language code ('fr' or 'en') to guide summary language.

    Returns:
        ClassificationResult with domain, tags, summary, slug etc.

    Raises:
        anthropic.AnthropicError: On API-level errors.
        ValueError: If response cannot be parsed.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")

    user_message = (
        f"Language: {lang}\n\nTranscript:\n{transcript}"
    )

    logger.info("Sending transcript to %s for classification (%d chars)", model, len(transcript))

    message = client.messages.create(
        model=model,
        max_tokens=512,
        system=CLASSIFIER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_content = message.content[0].text
    logger.debug("Classifier raw response: %s", raw_content[:300])

    result = _parse_classifier_response(raw_content, lang)
    logger.info(
        "Classification: domain=%s, slug=%s, needs_review=%s",
        result.domain,
        result.title_slug,
        result.needs_review,
    )
    return result
