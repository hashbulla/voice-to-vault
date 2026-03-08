"""
test_git_writer.py — Unit tests for git_writer module.

subprocess calls are mocked — zero real git operations.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import git_writer


# ── Helpers ───────────────────────────────────────────────────────────────────


def _set_env(monkeypatch, vault_clone_dir: str):
    monkeypatch.setenv("VAULT_REPO", "owner/vault")
    monkeypatch.setenv("VAULT_BRANCH", "main")
    monkeypatch.setenv("VAULT_DEPLOY_KEY_PATH", "/tmp/deploy_key")
    monkeypatch.setenv("VAULT_CLONE_DIR", vault_clone_dir)


# ── _git_env ──────────────────────────────────────────────────────────────────


class TestGitEnv:
    def test_git_ssh_command_set_with_deploy_key(self):
        env = git_writer._git_env("/path/to/key")
        assert "GIT_SSH_COMMAND" in env
        assert "/path/to/key" in env["GIT_SSH_COMMAND"]

    def test_strict_host_key_checking_disabled(self):
        env = git_writer._git_env("/path/to/key")
        assert "StrictHostKeyChecking=no" in env["GIT_SSH_COMMAND"]

    def test_user_known_hosts_file_disabled(self):
        env = git_writer._git_env("/path/to/key")
        assert "UserKnownHostsFile=/dev/null" in env["GIT_SSH_COMMAND"]


# ── _clone_or_pull ────────────────────────────────────────────────────────────


class TestCloneOrPull:
    def test_initial_clone_when_dir_not_exist(self, tmp_path, monkeypatch):
        clone_dir = tmp_path / "vault-clone"
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        run_calls = []

        def fake_run(cmd, cwd=None, env=None):
            run_calls.append(cmd)
            if cmd[0] == "git" and cmd[1] == "clone":
                # Simulate clone by creating directory
                clone_dir.mkdir(parents=True, exist_ok=True)
                (clone_dir / ".git").mkdir()
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            git_writer._clone_or_pull("owner/vault", "main", "/tmp/key")

        clone_cmds = [c for c in run_calls if "clone" in c]
        assert len(clone_cmds) == 1
        assert "--depth=50" in clone_cmds[0]

    def test_pull_when_dir_exists(self, tmp_path, monkeypatch):
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        run_calls = []

        def fake_run(cmd, cwd=None, env=None):
            run_calls.append(cmd)
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            git_writer._clone_or_pull("owner/vault", "main", "/tmp/key")

        fetch_cmds = [c for c in run_calls if "fetch" in c and "--unshallow" not in c]
        reset_cmds = [c for c in run_calls if "reset" in c]
        assert len(fetch_cmds) >= 1
        assert len(reset_cmds) >= 1

    def test_shallow_clone_fallback_triggers_unshallow(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        call_count = {"reset": 0}

        def fake_run(cmd, cwd=None, env=None):
            if "reset" in cmd and "--hard" in cmd:
                call_count["reset"] += 1
                if call_count["reset"] == 1:
                    raise RuntimeError(
                        "fatal: shallow file has changed since last read"
                    )
            return ""

        with caplog.at_level(logging.INFO, logger="git_writer"):
            with patch.object(git_writer, "_run", side_effect=fake_run):
                git_writer._clone_or_pull("owner/vault", "main", "/tmp/key")

        assert "unshallow" in caplog.text.lower() or "Shallow" in caplog.text


# ── write_note_and_push ───────────────────────────────────────────────────────


class TestWriteNoteAndPush:
    def _run_write(
        self,
        tmp_path,
        monkeypatch,
        file_path="00_Inbox/2026-03-08-test.md",
        content="test content",
        title_slug="test-slug",
    ):
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        captured_sha = {"value": "abc123def456abc123def456abc123def456abc1"}

        def fake_run(cmd, cwd=None, env=None):
            if "rev-parse" in cmd:
                return captured_sha["value"]
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            with patch.object(git_writer, "_clone_or_pull", return_value=clone_dir):
                sha = git_writer.write_note_and_push(file_path, content, title_slug)

        return sha, clone_dir

    def test_file_written_to_correct_path(self, tmp_path, monkeypatch):
        _set_env(monkeypatch, str(tmp_path / "vault-clone"))
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        run_calls = []

        def fake_run(cmd, cwd=None, env=None):
            run_calls.append(cmd)
            if "rev-parse" in cmd:
                return "abc123def456abc123def456abc123def456abc1"
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            with patch.object(git_writer, "_clone_or_pull", return_value=clone_dir):
                git_writer.write_note_and_push(
                    "00_Inbox/2026-03-08-slug.md", "content", "slug"
                )

        target = clone_dir / "00_Inbox" / "2026-03-08-slug.md"
        assert target.exists()
        assert target.read_text() == "content"

    def test_commit_message_format(self, tmp_path, monkeypatch):
        _set_env(monkeypatch, str(tmp_path / "vault-clone"))
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        run_calls = []

        def fake_run(cmd, cwd=None, env=None):
            run_calls.append(cmd)
            if "rev-parse" in cmd:
                return "abc123def456abc123def456abc123def456abc1"
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            with patch.object(git_writer, "_clone_or_pull", return_value=clone_dir):
                git_writer.write_note_and_push(
                    "00_Inbox/2026-03-08-my-note.md", "content", "my-note"
                )

        commit_cmds = [c for c in run_calls if "commit" in c]
        assert len(commit_cmds) == 1
        commit_msg = commit_cmds[0]
        assert "feat(inbox): my-note [openclaw]" in commit_msg

    def test_deploy_key_in_git_ssh_command(self, tmp_path, monkeypatch):
        _set_env(monkeypatch, str(tmp_path / "vault-clone"))
        monkeypatch.setenv("VAULT_DEPLOY_KEY_PATH", "/tmp/my_deploy_key")
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        push_envs = []

        def fake_run(cmd, cwd=None, env=None):
            if "push" in cmd and env:
                push_envs.append(env)
            if "rev-parse" in cmd:
                return "abc123def456abc123def456abc123def456abc1"
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            with patch.object(git_writer, "_clone_or_pull", return_value=clone_dir):
                git_writer.write_note_and_push(
                    "00_Inbox/2026-03-08-test.md", "content", "test"
                )

        assert len(push_envs) == 1
        assert "/tmp/my_deploy_key" in push_envs[0]["GIT_SSH_COMMAND"]

    def test_returns_full_commit_sha(self, tmp_path, monkeypatch):
        _set_env(monkeypatch, str(tmp_path / "vault-clone"))
        expected_sha = "abc123def456abc123def456abc123def456abc1"
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        def fake_run(cmd, cwd=None, env=None):
            if "rev-parse" in cmd:
                return expected_sha
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            with patch.object(git_writer, "_clone_or_pull", return_value=clone_dir):
                sha = git_writer.write_note_and_push(
                    "00_Inbox/2026-03-08-test.md", "content", "test"
                )

        assert sha == expected_sha

    def test_push_failure_raises_exception(self, tmp_path, monkeypatch):
        _set_env(monkeypatch, str(tmp_path / "vault-clone"))
        clone_dir = tmp_path / "vault-clone"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr(git_writer, "_CLONE_CACHE_DIR", clone_dir)

        def fake_run(cmd, cwd=None, env=None):
            if "push" in cmd:
                raise RuntimeError("Push failed: permission denied")
            if "rev-parse" in cmd:
                return "abc123def456abc123def456abc123def456abc1"
            return ""

        with patch.object(git_writer, "_run", side_effect=fake_run):
            with patch.object(git_writer, "_clone_or_pull", return_value=clone_dir):
                with pytest.raises(RuntimeError, match="Push failed"):
                    git_writer.write_note_and_push(
                        "00_Inbox/2026-03-08-test.md", "content", "test"
                    )
