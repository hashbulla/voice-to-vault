#!/usr/bin/env python3
"""
classifier_eval.py — Standalone evaluation script for the Claude Haiku classifier.

Makes REAL Anthropic API calls. Run manually only:
  python tests/evaluation/classifier_eval.py

Requires: ANTHROPIC_API_KEY set in environment.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Add vault-writer to path
SKILL_DIR = Path(__file__).parent.parent.parent / "openclaw" / "skills" / "vault-writer"
sys.path.insert(0, str(SKILL_DIR))

from classifier import classify_transcript, VALID_DOMAINS

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Cost estimate: ~$0.0001 per call with claude-haiku-4-5
COST_PER_CALL = 0.0001

SLUG_RE = re.compile(r"^[a-z0-9-]{3,60}$")

# Soft assertions: expected domain per fixture
EXPECTED_DOMAINS = {
    "fr_engineering_k8s.txt": "Engineering",
    "fr_business_prospect.txt": "Business",
    "fr_life_reflection.txt": "Life",
    "fr_cyber_osint.txt": "Cyber",
}

EXPECTED_NEEDS_REVIEW = {
    "edge_ambiguous_domain.txt": True,
    "edge_empty_transcript.txt": True,
}


@dataclass
class FixtureResult:
    filename: str
    hard_pass: bool
    soft_domain_match: bool | None  # None if no expectation
    soft_needs_review_match: bool | None
    domain: str
    title_slug: str
    tags: list[str]
    summary: str
    needs_review: bool
    hard_failures: list[str]
    error: str | None


def evaluate_fixture(filename: str, text: str) -> FixtureResult:
    hard_failures = []
    error = None
    domain = ""
    title_slug = ""
    tags = []
    summary = ""
    needs_review = False

    try:
        result = classify_transcript(text, lang="fr")
        domain = result.domain
        title_slug = result.title_slug
        tags = result.tags
        summary = result.summary
        needs_review = result.needs_review

        # Hard constraints
        if domain not in VALID_DOMAINS:
            hard_failures.append(f"domain '{domain}' not in VALID_DOMAINS")

        if not isinstance(tags, list) or not (1 <= len(tags) <= 5):
            hard_failures.append(f"tags must be list of 1-5 items, got {len(tags)}: {tags}")

        if not SLUG_RE.match(title_slug):
            hard_failures.append(f"title_slug '{title_slug}' does not match ^[a-z0-9-]{{3,60}}$")

        if not summary or not isinstance(summary, str):
            hard_failures.append("summary must be a non-empty string")

        if not isinstance(needs_review, bool):
            hard_failures.append(f"needs_review must be bool, got {type(needs_review)}")

    except Exception as exc:
        error = str(exc)
        hard_failures.append(f"Exception: {exc}")

    # Soft assertions
    soft_domain = None
    if filename in EXPECTED_DOMAINS:
        soft_domain = (domain == EXPECTED_DOMAINS[filename])

    soft_review = None
    if filename in EXPECTED_NEEDS_REVIEW:
        soft_review = (needs_review == EXPECTED_NEEDS_REVIEW[filename])

    return FixtureResult(
        filename=filename,
        hard_pass=len(hard_failures) == 0 and error is None,
        soft_domain_match=soft_domain,
        soft_needs_review_match=soft_review,
        domain=domain,
        title_slug=title_slug,
        tags=tags,
        summary=summary,
        needs_review=needs_review,
        hard_failures=hard_failures,
        error=error,
    )


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
    fixtures = sorted(FIXTURES_DIR.glob("*.txt"))

    if not fixtures:
        print(f"ERROR: No fixture files found in {FIXTURES_DIR}")
        sys.exit(1)

    print(f"CLASSIFIER EVALUATION")
    print(f"Model: {model}")
    print(f"Transcripts: {len(fixtures)}")
    print("-" * 60)

    results = []
    for fixture in fixtures:
        text = fixture.read_text(encoding="utf-8").strip()
        print(f"  Evaluating {fixture.name}...", end=" ", flush=True)
        result = evaluate_fixture(fixture.name, text)
        results.append(result)
        status = "PASS" if result.hard_pass else "FAIL"
        print(f"{status} (domain={result.domain}, needs_review={result.needs_review})")
        time.sleep(0.5)  # Rate limiting

    # Compute metrics
    hard_pass_count = sum(1 for r in results if r.hard_pass)
    soft_domain_results = [r for r in results if r.soft_domain_match is not None]
    soft_domain_pass = sum(1 for r in soft_domain_results if r.soft_domain_match)
    soft_review_results = [r for r in results if r.soft_needs_review_match is not None]
    soft_review_pass = sum(1 for r in soft_review_results if r.soft_needs_review_match)

    total_cost = len(results) * COST_PER_CALL

    # Build report
    now = datetime.now(tz=timezone.utc)
    report_lines = [
        "CLASSIFIER EVALUATION REPORT",
        f"Date: {now.isoformat()}",
        f"Model: {model}",
        f"Transcripts evaluated: {len(results)}",
        f"Hard constraints: {hard_pass_count}/{len(results)} passed",
        f"Soft domain assertions: {soft_domain_pass}/{len(soft_domain_results)} matched expected",
        f"Soft needs_review assertions: {soft_review_pass}/{len(soft_review_results)} matched expected",
        "",
        "PASS/FAIL per fixture:",
        f"{'Fixture':<45} {'Hard':<6} {'Domain':<16} {'Needs Review':<14} {'Expected Domain':<16}",
        "-" * 100,
    ]

    for r in results:
        hard_str = "PASS" if r.hard_pass else "FAIL"
        exp_domain = EXPECTED_DOMAINS.get(r.filename, "—")
        domain_match = "" if r.soft_domain_match is None else ("✓" if r.soft_domain_match else "✗")
        review_match = "" if r.soft_needs_review_match is None else ("✓" if r.soft_needs_review_match else "✗")
        report_lines.append(
            f"{r.filename:<45} {hard_str:<6} {r.domain:<16} {str(r.needs_review):<14} {exp_domain:<16} {domain_match} {review_match}"
        )
        if r.hard_failures:
            for failure in r.hard_failures:
                report_lines.append(f"  ❌ {failure}")

    report_lines.extend([
        "",
        f"Total API cost estimate: ~${total_cost:.4f}",
    ])

    report = "\n".join(report_lines)
    print("\n" + report)

    # Save report
    date_str = now.strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"{date_str}-classifier.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Exit code
    if hard_pass_count < len(results):
        print("\nFAIL: Some hard constraints failed — classifier is broken")
        sys.exit(1)

    print("\nPASS: All hard constraints passed")


if __name__ == "__main__":
    main()
