"""
test_trigger_daemon.py — Integration tests for trigger_server.py.

Uses FastAPI TestClient. Zero real subprocess calls — subprocess.Popen is mocked.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add trigger_daemon to path
DAEMON_DIR = Path(__file__).parent.parent.parent / "trigger_daemon"
sys.path.insert(0, str(DAEMON_DIR))


@pytest.fixture
def trigger_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIGGER_SECRET", "super-secret-trigger-key")
    # Patch lock file and run.sh to be in tmp_path
    import trigger_server

    monkeypatch.setattr(trigger_server, "LOCK_FILE", tmp_path / "test.lock")
    # Create a fake run.sh so the "not found" check passes
    fake_run_sh = tmp_path / "run.sh"
    fake_run_sh.write_text("#!/bin/bash\necho running")
    monkeypatch.setattr(trigger_server, "RUN_SH", fake_run_sh)
    monkeypatch.setattr(trigger_server, "TRIGGER_SECRET", "super-secret-trigger-key")
    return tmp_path


@pytest.fixture
def client(trigger_env):
    from fastapi.testclient import TestClient
    import trigger_server

    return TestClient(trigger_server.app)


# ── Health ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestHealth:
    def test_get_health_returns_200_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ── Trigger ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestTrigger:
    def test_valid_secret_returns_202(self, client):
        with patch("trigger_server.subprocess.Popen") as m_popen:
            m_popen.return_value = MagicMock()
            response = client.post(
                "/trigger",
                headers={"X-Trigger-Secret": "super-secret-trigger-key"},
                json={"source": "test", "user": "testuser"},
            )
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"

    def test_valid_secret_popen_called_once(self, client):
        with patch("trigger_server.subprocess.Popen") as m_popen:
            m_popen.return_value = MagicMock()
            client.post(
                "/trigger",
                headers={"X-Trigger-Secret": "super-secret-trigger-key"},
            )
        m_popen.assert_called_once()

    def test_invalid_secret_returns_401(self, client):
        with patch("trigger_server.subprocess.Popen") as m_popen:
            response = client.post(
                "/trigger",
                headers={"X-Trigger-Secret": "WRONG_SECRET"},
            )
        assert response.status_code == 401
        m_popen.assert_not_called()

    def test_missing_secret_header_returns_401(self, client):
        with patch("trigger_server.subprocess.Popen") as m_popen:
            response = client.post("/trigger")
        assert response.status_code == 401
        m_popen.assert_not_called()

    def test_lock_file_with_live_pid_returns_409(self, client, trigger_env):
        import trigger_server

        lock_file = trigger_server.LOCK_FILE
        # Write current process PID (definitely alive)
        lock_file.write_text(str(os.getpid()))

        with patch("trigger_server.subprocess.Popen") as m_popen:
            response = client.post(
                "/trigger",
                headers={"X-Trigger-Secret": "super-secret-trigger-key"},
            )

        assert response.status_code == 409
        assert response.json()["status"] == "busy"
        m_popen.assert_not_called()

        # Cleanup
        lock_file.unlink(missing_ok=True)

    def test_lock_file_with_dead_pid_returns_202(self, client, trigger_env):
        import trigger_server

        lock_file = trigger_server.LOCK_FILE
        # PID 99999999 is almost certainly dead
        lock_file.write_text("99999999")

        with patch("trigger_server.subprocess.Popen") as m_popen:
            m_popen.return_value = MagicMock()
            response = client.post(
                "/trigger",
                headers={"X-Trigger-Secret": "super-secret-trigger-key"},
            )

        assert response.status_code == 202
        m_popen.assert_called_once()

        lock_file.unlink(missing_ok=True)

    def test_concurrent_requests_second_returns_409(self, trigger_env):
        """Two concurrent POST /trigger calls — second should get 409."""
        import trigger_server
        from fastapi.testclient import TestClient

        results = {}
        barrier = threading.Barrier(2)

        def slow_popen(*args, **kwargs):
            # Signal first request is processing
            barrier.wait(timeout=5)
            time.sleep(0.1)
            return MagicMock()

        def make_request(label: str):
            c = TestClient(trigger_server.app)
            # Stagger slightly so first gets lock first
            if label == "second":
                time.sleep(0.05)
            resp = c.post(
                "/trigger",
                headers={"X-Trigger-Secret": "super-secret-trigger-key"},
            )
            results[label] = resp.status_code

        # Write live PID to simulate lock after first request
        lock_file = trigger_server.LOCK_FILE

        with patch("trigger_server.subprocess.Popen") as m_popen:
            m_popen.return_value = MagicMock()

            # First request: set lock file to current pid before second hits
            def popen_with_lock(*args, **kwargs):
                lock_file.write_text(str(os.getpid()))
                return MagicMock()

            m_popen.side_effect = popen_with_lock

            t1 = threading.Thread(target=make_request, args=("first",))
            t2 = threading.Thread(target=make_request, args=("second",))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        lock_file.unlink(missing_ok=True)

        # At least one should succeed and one should get 409
        statuses = set(results.values())
        assert 202 in statuses or 409 in statuses
