"""
trigger_server.py — voice-to-vault on-demand trigger daemon

Runs on the Hetzner HOST (not Docker) bound to 127.0.0.1:9999 only.
Receives POST /trigger from the vault-processor OpenClaw skill and
launches agents/nightly_processor/run.sh in a non-blocking subprocess.
"""

import hmac
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
TRIGGER_SECRET: str = os.environ.get("TRIGGER_SECRET", "")
LOCK_FILE = Path("/tmp/voice-to-vault-nightly.lock")
RUN_SH = Path("/opt/voice-to-vault/agents/nightly_processor/run.sh")

app = FastAPI(title="voice-to-vault trigger daemon", version="1.0.0")


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── Trigger ────────────────────────────────────────────────────────────────────
@app.post("/trigger")
async def trigger(
    request: Request,
    x_trigger_secret: str = Header(default=""),
) -> JSONResponse:
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    # ── Auth ───────────────────────────────────────────────────────────────────
    if not TRIGGER_SECRET:
        log.error("[%s] TRIGGER_SECRET not configured — refusing all requests", timestamp)
        raise HTTPException(status_code=500, detail="Trigger secret not configured")

    if not hmac.compare_digest(x_trigger_secret, TRIGGER_SECRET):
        log.warning("[%s] REJECTED — invalid X-Trigger-Secret header", timestamp)
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ── Parse body (best-effort) ───────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception:
        body = {}

    source = body.get("source", "unknown")
    user = body.get("user", "unknown")

    # ── Lock check ─────────────────────────────────────────────────────────────
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if process is actually running
            os.kill(pid, 0)
            # Process is alive
            log.info(
                "[%s] BUSY — agent already running (PID %d) | source=%s user=%s",
                timestamp, pid, source, user,
            )
            return JSONResponse(
                status_code=409,
                content={"status": "busy", "message": "Agent already running"},
            )
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock — remove it and proceed
            log.warning("[%s] Stale lock file found — removing and proceeding", timestamp)
            LOCK_FILE.unlink(missing_ok=True)

    # ── Launch run.sh ──────────────────────────────────────────────────────────
    if not RUN_SH.exists():
        log.error("[%s] run.sh not found at %s", timestamp, RUN_SH)
        raise HTTPException(status_code=500, detail="run.sh not found")

    log.info(
        "[%s] ACCEPTED — launching run.sh | source=%s user=%s",
        timestamp, source, user,
    )

    # Non-blocking: returns immediately; run.sh manages its own lock
    subprocess.Popen(
        ["bash", str(RUN_SH)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "message": "Processing started"},
    )
