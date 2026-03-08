"""
conftest.py — Shared fixtures and environment setup for voice-to-vault test suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add vault-writer skill directory to path so modules import without package prefix
SKILL_DIR = Path(__file__).parent.parent / "openclaw" / "skills" / "vault-writer"
sys.path.insert(0, str(SKILL_DIR))

# Minimum required env vars — set before any module-level imports that read them
_BASE_ENV = {
    "OPENCLAW_WEBHOOK_SECRET": "test-secret-abc123",
    "TELEGRAM_BOT_TOKEN": "123456:TEST_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID": "999888777",
    "OPENAI_API_KEY": "sk-test-openai-key",
    "ANTHROPIC_API_KEY": "sk-ant-test-key",
    "VAULT_REPO": "testowner/test-vault",
    "VAULT_DEPLOY_KEY_PATH": "/tmp/test_deploy_key",
    "VAULT_BRANCH": "main",
    "WHISPER_LANGUAGE": "fr",
    "CLAUDE_MODEL": "claude-haiku-4-5",
}


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    """Set required environment variables for every test."""
    for k, v in _BASE_ENV.items():
        monkeypatch.setenv(k, v)
    yield


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a minimal temporary vault directory structure."""
    inbox = tmp_path / "00_Inbox"
    inbox.mkdir()
    system = tmp_path / "_System"
    system.mkdir()
    return tmp_path


@pytest.fixture
def sample_transcript():
    """Return a realistic VerboseTranscript for use in tests."""
    from transcriber import VerboseTranscript

    return VerboseTranscript(
        text="Aujourd'hui j'ai travaillé sur le design d'un opérateur Kubernetes pour External Secrets.",
        language="fr",
        duration=95.3,
        segments=[],
    )


@pytest.fixture
def sample_classification():
    """Return a realistic ClassificationResult for use in tests."""
    from classifier import ClassificationResult

    return ClassificationResult(
        domain="Engineering",
        projects=[],
        tags=["kubernetes", "operator", "devsecops"],
        summary="Design d'un opérateur Kubernetes pour External Secrets sur RKE2.",
        needs_review=False,
        title_slug="kubernetes-operator-design",
    )


@pytest.fixture
def mock_openai_client(mocker):
    """Mock the entire openai.OpenAI client."""
    mock_client = MagicMock()
    mocker.patch("openai.OpenAI", return_value=mock_client)
    return mock_client


@pytest.fixture
def mock_anthropic_client(mocker):
    """Mock the entire anthropic.Anthropic client."""
    mock_client = MagicMock()
    mocker.patch("anthropic.Anthropic", return_value=mock_client)
    return mock_client
