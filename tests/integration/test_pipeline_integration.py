"""
test_pipeline_integration.py — Full pipeline integration test.

Mocks only external network calls (OpenAI, Anthropic, Telegram CDN, GitHub).
Uses a real temporary git repo on disk for git operations.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add vault-writer skill dir
SKILL_DIR = Path(__file__).parent.parent.parent / "openclaw" / "skills" / "vault-writer"
sys.path.insert(0, str(SKILL_DIR))

TRANSCRIPT_TEXT = (
    "Aujourd'hui j'ai travaillé sur le design d'un opérateur Kubernetes pour External Secrets "
    "Operator sur un cluster RKE2. J'ai customisé le Helm chart et configuré les RBAC. "
    "Il faut penser à la rotation automatique des secrets."
)

CLASSIFICATION_JSON = json.dumps({
    "domain": "Engineering",
    "projects": [],
    "tags": ["kubernetes", "operator", "devsecops"],
    "summary": "Design d'un opérateur Kubernetes pour External Secrets sur RKE2.",
    "needs_review": False,
    "title_slug": "kubernetes-operator-design",
})


@pytest.fixture
def git_vault(tmp_path):
    """
    Create a real local git setup:
    - bare_remote/: acts as the remote
    - vault_clone/: the local clone (simulating what git_writer uses)
    """
    bare = tmp_path / "bare_remote"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True, capture_output=True,
    )

    # Clone it as the vault
    clone = tmp_path / "vault_clone"
    subprocess.run(
        ["git", "clone", str(bare), str(clone)],
        check=True, capture_output=True,
    )

    # Configure identity in clone
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(clone), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(clone), check=True, capture_output=True)

    # Create initial commit so branch exists
    (clone / "README.md").write_text("vault")
    subprocess.run(["git", "add", "."], cwd=str(clone), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(clone), check=True, capture_output=True)
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=str(clone), check=True, capture_output=True,
    )

    return {"bare": bare, "clone": clone}


@pytest.fixture
def env_setup(monkeypatch, git_vault):
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", "test-secret-abc123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "999888777")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("VAULT_REPO", "owner/vault")
    monkeypatch.setenv("VAULT_BRANCH", "main")
    monkeypatch.setenv("VAULT_DEPLOY_KEY_PATH", "/tmp/test_key")
    monkeypatch.setenv("VAULT_CLONE_DIR", str(git_vault["clone"]))
    monkeypatch.setenv("WHISPER_LANGUAGE", "fr")


def _make_event(secret="test-secret-abc123", user_id=999888777, file_id="FILE_K8S_001"):
    return {
        "message": {
            "message_id": 42,
            "from": {"id": user_id},
            "chat": {"id": 12345},
            "voice": {
                "file_id": file_id,
                "file_unique_id": "unique001",
                "duration": 95,
                "mime_type": "audio/ogg",
                "file_size": 120000,
            },
        },
        "headers": {
            "x-telegram-bot-api-secret-token": secret,
        },
    }


@pytest.mark.integration
def test_full_pipeline_engineering_note(env_setup, git_vault, monkeypatch):
    """
    Full pipeline integration test: mock all network calls, use real git.
    """
    for mod in list(sys.modules.keys()):
        if mod in ("main", "classifier", "git_writer", "note_formatter",
                   "telegram_ack", "transcriber"):
            sys.modules.pop(mod, None)

    import main
    import git_writer

    monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", git_vault["clone"])

    # Patch network calls only
    mock_whisper_resp = MagicMock()
    mock_whisper_resp.text = TRANSCRIPT_TEXT
    mock_whisper_resp.language = "fr"
    mock_whisper_resp.duration = 95.3
    mock_whisper_resp.segments = []

    mock_openai_client = MagicMock()
    mock_openai_client.audio.transcriptions.create.return_value = mock_whisper_resp

    mock_anthropic_msg = MagicMock()
    mock_anthropic_msg.content = [MagicMock(text=CLASSIFICATION_JSON)]
    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.return_value = mock_anthropic_msg

    telegram_ack_calls = []

    def fake_send_message(chat_id, text):
        telegram_ack_calls.append({"chat_id": chat_id, "text": text})

    def fake_get_file(file_id, bot_token):
        return "voice/file_k8s.ogg"

    def fake_download(file_path, bot_token):
        return b"fake ogg audio" * 1000  # realistic size

    def fake_git_push(cmd, cwd=None, env=None):
        if cmd[:2] == ["git", "push"]:
            # Actually push to local bare remote
            subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True)
            return ""
        result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    with patch("transcriber.openai.OpenAI", return_value=mock_openai_client), \
         patch("classifier.anthropic.Anthropic", return_value=mock_anthropic_client), \
         patch.object(main, "get_telegram_file_path", side_effect=fake_get_file), \
         patch.object(main, "download_telegram_audio", side_effect=fake_download), \
         patch("telegram_ack._send_telegram_message", side_effect=fake_send_message), \
         patch.object(git_writer, "_run", side_effect=fake_git_push):

        result = main.handle(_make_event())

    # ── Assert pipeline result ──────────────────────────────────────────────────
    assert result["status"] == "success", f"Pipeline failed: {result}"
    assert result["domain"] == "Engineering"
    assert result["title_slug"] == "kubernetes-operator-design"
    assert result["needs_review"] is False
    assert abs(result["duration_sec"] - 95.3) < 0.01

    # ── Assert file exists on disk ─────────────────────────────────────────────
    from datetime import datetime, timezone
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    expected_filename = f"{today}-kubernetes-operator-design.md"
    expected_path = git_vault["clone"] / "00_Inbox" / expected_filename
    assert expected_path.exists(), f"File not found: {expected_path}"

    # ── Assert frontmatter ─────────────────────────────────────────────────────
    content = expected_path.read_text(encoding="utf-8")
    # Parse frontmatter
    assert content.startswith("---\n")
    end_fm = content.index("---\n", 4)
    fm_raw = content[4:end_fm]
    fm = yaml.safe_load(fm_raw)

    assert fm["domain"] == "Engineering"
    assert fm["status"] == "inbox"
    assert fm["source"] == "openclaw"
    assert fm["lang"] == "fr"
    assert abs(fm["duration_sec"] - 95.3) < 0.01

    # ── Assert French summary prefix ───────────────────────────────────────────
    assert "Résumé IA :" in content

    # ── Assert transcript appears verbatim ────────────────────────────────────
    assert TRANSCRIPT_TEXT in content

    # ── Assert separator ──────────────────────────────────────────────────────
    assert "\n---\n" in content

    # ── Assert git commit ─────────────────────────────────────────────────────
    log_result = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=str(git_vault["clone"]),
        capture_output=True, text=True,
    )
    commits = log_result.stdout.strip().split("\n")
    assert len(commits) >= 2  # init + our commit
    assert "kubernetes-operator-design [openclaw]" in commits[0]

    # ── Assert Telegram ACK called once ────────────────────────────────────────
    assert len(telegram_ack_calls) == 1
    ack_text = telegram_ack_calls[0]["text"]
    assert "kubernetes-operator-design" in ack_text
    assert "Engineering" in ack_text
