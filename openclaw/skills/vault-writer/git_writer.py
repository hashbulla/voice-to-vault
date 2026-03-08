"""
git_writer.py — GitHub private repo push via SSH Deploy Key for voice-to-vault.

Clones (or pulls) the vault repo into a local cache directory,
writes the note file, commits, and pushes over SSH using a dedicated
write-only Deploy Key. The local clone is reused across calls to
avoid redundant clones.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Local clone cache — reused across skill invocations within the same container
_CLONE_CACHE_DIR = Path(os.environ.get("VAULT_CLONE_DIR", "/tmp/vault-clone"))


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    """
    Run a subprocess command, returning stdout. Raises RuntimeError on failure.
    """
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )
    return result.stdout.strip()


def _git_env(deploy_key_path: str) -> dict:
    """
    Build environment dict that forces SSH to use the vault deploy key,
    disabling strict host key checking for automated operation.
    """
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {deploy_key_path} "
        f"-o StrictHostKeyChecking=no "
        f"-o UserKnownHostsFile=/dev/null"
    )
    return env


def _clone_or_pull(repo: str, branch: str, deploy_key_path: str) -> Path:
    """
    Ensure a local clone of the vault repo exists and is up to date.

    Uses SSH URL for push access. If clone already exists, does a
    fast-forward pull. If it does not exist, clones with --depth=50
    for efficiency.

    Args:
        repo: GitHub repo in 'owner/name' format.
        branch: Branch name (typically 'main').
        deploy_key_path: Absolute path to the SSH deploy key.

    Returns:
        Path to the local clone directory.

    Raises:
        RuntimeError: On git clone/pull failure.
    """
    ssh_url = f"git@github.com:{repo}.git"
    env = _git_env(deploy_key_path)

    if _CLONE_CACHE_DIR.exists() and (_CLONE_CACHE_DIR / ".git").exists():
        logger.info("Pulling latest from %s/%s", repo, branch)
        _run(["git", "fetch", "origin", branch], cwd=_CLONE_CACHE_DIR, env=env)
        try:
            _run(
                ["git", "reset", "--hard", f"origin/{branch}"],
                cwd=_CLONE_CACHE_DIR,
                env=env,
            )
        except RuntimeError:
            logger.info(
                "Shallow history detected — running git fetch --unshallow before retry"
            )
            _run(["git", "fetch", "--unshallow"], cwd=_CLONE_CACHE_DIR, env=env)
            _run(
                ["git", "reset", "--hard", f"origin/{branch}"],
                cwd=_CLONE_CACHE_DIR,
                env=env,
            )
    else:
        logger.info("Cloning %s (branch=%s) into %s", repo, branch, _CLONE_CACHE_DIR)
        _CLONE_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "clone",
                "--depth=50",
                "--branch",
                branch,
                ssh_url,
                str(_CLONE_CACHE_DIR),
            ],
            env=env,
        )

    # Configure identity for commits
    _run(
        ["git", "config", "user.email", "voice-to-vault@openclaw.local"],
        cwd=_CLONE_CACHE_DIR,
    )
    _run(
        ["git", "config", "user.name", "voice-to-vault[bot]"],
        cwd=_CLONE_CACHE_DIR,
    )

    return _CLONE_CACHE_DIR


def write_note_and_push(
    file_path: str,
    content: str,
    title_slug: str,
) -> str:
    """
    Write a note to the vault repo and push via Deploy Key.

    Args:
        file_path: Relative path within vault (e.g. '00_Inbox/2024-01-15-my-slug.md').
        content: Full markdown content of the note.
        title_slug: Kebab-case slug for commit message.

    Returns:
        Git commit SHA of the new commit.

    Raises:
        RuntimeError: On any git operation failure.
        OSError: On file write failure.
    """
    repo = os.environ["VAULT_REPO"]
    branch = os.environ.get("VAULT_BRANCH", "main")
    deploy_key_path = os.environ["VAULT_DEPLOY_KEY_PATH"]

    clone_dir = _clone_or_pull(repo, branch, deploy_key_path)
    env = _git_env(deploy_key_path)

    # Write note file, creating parent directories if needed
    target = clone_dir / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    logger.info("Wrote note to %s (%d bytes)", target, len(content))

    # Stage, commit, push
    _run(["git", "add", file_path], cwd=clone_dir)
    commit_message = f"feat(inbox): {title_slug} [openclaw]"
    _run(
        ["git", "commit", "-m", commit_message],
        cwd=clone_dir,
    )

    sha = _run(["git", "rev-parse", "HEAD"], cwd=clone_dir)
    logger.info("Committed %s: %s", title_slug, sha[:12])

    _run(["git", "push", "origin", branch], cwd=clone_dir, env=env)
    logger.info("Pushed to %s/%s", repo, branch)

    return sha
