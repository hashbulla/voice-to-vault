#!/usr/bin/env python3
"""
smoke_test.py — End-to-end smoke test with real API calls.

Estimated cost: ~$0.02 per run.
Run manually only:
  python tests/smoke/smoke_test.py

Requires all env vars set (see .env.template).
Does NOT use real Telegram audio — calls each component directly.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent.parent / "openclaw" / "skills" / "vault-writer"
sys.path.insert(0, str(SKILL_DIR))

VALID_DOMAINS = {"Life", "Business", "Engineering", "Cyber"}
SMOKE_BRANCH = "smoke-test-do-not-merge"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _check_env():
    required = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "VAULT_REPO", "VAULT_DEPLOY_KEY_PATH",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing required env vars: {', '.join(missing)}")
        sys.exit(1)


def _load_audio_fixture() -> bytes:
    fixture = FIXTURES_DIR / "fr_5sec.ogg"
    if fixture.exists():
        return fixture.read_bytes()
    # Fallback: generate minimal OGG with ffmpeg if available
    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            tmp_path = f.name
        result = subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
             "-c:a", "libvorbis", "-q:a", "3", "-y", tmp_path],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0:
            audio = Path(tmp_path).read_bytes()
            Path(tmp_path).unlink(missing_ok=True)
            return audio
    except Exception:
        pass
    # Last resort: minimal valid OGG header bytes
    print("WARNING: Using minimal synthetic audio bytes (ffmpeg not available)")
    return b"OggS" + b"\x00" * 256


def step1_transcription(audio: bytes) -> tuple[str, float]:
    from transcriber import transcribe_audio
    whisper_prompt = os.environ.get("WHISPER_PROMPT", "")
    result = transcribe_audio(audio, language="fr", whisper_prompt=whisper_prompt)
    assert result.text, "Transcription returned empty text"
    assert 0 <= result.duration <= 30, f"Unexpected duration: {result.duration}"
    return result.text, result.duration


def step2_classification(text: str) -> tuple:
    from classifier import classify_transcript, ClassificationResult
    result = classify_transcript(text, lang="fr")
    assert result.domain in VALID_DOMAINS, f"Invalid domain: {result.domain}"
    assert result.title_slug, "title_slug is empty"
    assert result.tags, "tags is empty"
    assert result.summary, "summary is empty"
    return result


def step3_formatting(transcript_obj, classification) -> tuple[str, str]:
    from note_formatter import build_note
    from transcriber import VerboseTranscript
    file_path, content = build_note(transcript_obj, classification, lang="fr")
    assert file_path.startswith("00_Inbox/"), f"Bad file_path: {file_path}"
    assert "---\n" in content, "No frontmatter in note content"
    return file_path, content


def step4_git(file_path: str, content: str, title_slug: str) -> str:
    import git_writer
    from pathlib import Path
    import os

    # Override branch to smoke test branch
    original_branch = os.environ.get("VAULT_BRANCH", "main")
    os.environ["VAULT_BRANCH"] = SMOKE_BRANCH

    try:
        sha = git_writer.write_note_and_push(file_path, content, title_slug)
    finally:
        os.environ["VAULT_BRANCH"] = original_branch

    assert sha and len(sha) >= 12, f"Invalid SHA: {sha}"
    assert re.match(r"^[0-9a-f]+$", sha[:12]), f"SHA not hexadecimal: {sha[:12]}"
    return sha[:12]


def step5_daemon() -> str:
    daemon_url = os.environ.get("TRIGGER_DAEMON_URL", "")
    if not daemon_url:
        return "SKIPPED"
    import httpx
    try:
        resp = httpx.get(f"{daemon_url}/health", timeout=5.0)
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
        return "PASS"
    except Exception as exc:
        return f"FAIL ({exc})"


def main():
    _check_env()

    print("SMOKE TEST — voice-to-vault")
    print("=" * 50)

    results = {}
    total_cost_est = 0.0

    # Step 1: Transcription
    try:
        audio = _load_audio_fixture()
        text, duration = step1_transcription(audio)
        results["step1"] = f"PASS (duration={duration:.1f}s, chars={len(text)})"
        total_cost_est += 0.006  # Whisper cost estimate
        print(f"Step 1 Whisper: PASS  (duration={duration:.1f}s, chars={len(text)})")
    except Exception as exc:
        results["step1"] = f"FAIL ({exc})"
        print(f"Step 1 Whisper: FAIL  ({exc})")
        sys.exit(1)

    time.sleep(0.5)

    # Step 2: Classification
    try:
        from transcriber import VerboseTranscript
        transcript_obj = VerboseTranscript(text=text, language="fr", duration=duration, segments=[])
        classification = step2_classification(text)
        results["step2"] = f"PASS (domain={classification.domain}, slug={classification.title_slug})"
        total_cost_est += 0.0001  # Haiku cost estimate
        print(f"Step 2 Haiku:   PASS  (domain={classification.domain}, slug={classification.title_slug})")
    except Exception as exc:
        results["step2"] = f"FAIL ({exc})"
        print(f"Step 2 Haiku:   FAIL  ({exc})")
        sys.exit(1)

    time.sleep(0.5)

    # Step 3: Note formatting
    try:
        from transcriber import VerboseTranscript
        transcript_obj = VerboseTranscript(text=text, language="fr", duration=duration, segments=[])
        file_path, content = step3_formatting(transcript_obj, classification)
        results["step3"] = "PASS"
        print(f"Step 3 Format:  PASS  (path={file_path})")
    except Exception as exc:
        results["step3"] = f"FAIL ({exc})"
        print(f"Step 3 Format:  FAIL  ({exc})")
        sys.exit(1)

    # Step 4: Git write
    if os.environ.get("VAULT_REPO") and os.environ.get("VAULT_DEPLOY_KEY_PATH"):
        try:
            sha = step4_git(file_path, content, classification.title_slug)
            results["step4"] = f"PASS (sha: {sha})"
            print(f"Step 4 Git:     PASS  (sha: {sha})")
        except Exception as exc:
            results["step4"] = f"FAIL ({exc})"
            print(f"Step 4 Git:     FAIL  ({exc})")
    else:
        results["step4"] = "SKIPPED (VAULT_REPO not set)"
        print("Step 4 Git:     SKIPPED")

    # Step 5: Daemon health
    daemon_result = step5_daemon()
    results["step5"] = daemon_result
    print(f"Step 5 Daemon:  {daemon_result}")

    # Summary
    print("\n" + "=" * 50)
    overall = "PASS" if all("FAIL" not in v for v in results.values()) else "FAIL"
    print(f"OVERALL: {overall}")
    print(f"Estimated cost: ${total_cost_est:.4f}")

    if overall == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
