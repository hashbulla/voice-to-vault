#!/usr/bin/env bash
# run.sh — Nightly vault processor cron entrypoint for voice-to-vault
#
# Invoked by cron at 23:00 CET (Europe/Paris) on the Hetzner VPS.
# Runs the headless Claude Code agent against the local vault clone.
#
# Usage: /opt/voice-to-vault/agents/nightly_processor/run.sh
# Cron:  0 23 * * * TZ=Europe/Paris /opt/voice-to-vault/agents/nightly_processor/run.sh

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="/opt/voice-to-vault/.env"
LOG_DIR="${NIGHTLY_AGENT_LOG:-/var/log/voice-to-vault}"
LOG_FILE="${LOG_DIR}/nightly-$(date +%Y-%m-%d).log"
VAULT_CLONE_DIR="${VAULT_CLONE_DIR:-/tmp/vault-clone}"
AGENT_PROMPT="${SCRIPT_DIR}/AGENT_PROMPT.md"
LOCK_FILE="/tmp/voice-to-vault-nightly.lock"

# ── Logging setup ─────────────────────────────────────────────────────────────
mkdir -p "${LOG_DIR}"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "${LOG_FILE}"
}

# ── Lock guard: prevent overlapping runs ──────────────────────────────────────
if [ -f "${LOCK_FILE}" ]; then
    existing_pid=$(cat "${LOCK_FILE}" 2>/dev/null || echo "unknown")
    if kill -0 "${existing_pid}" 2>/dev/null; then
        log "ERROR: Nightly agent already running (PID ${existing_pid}). Exiting."
        exit 1
    else
        log "WARN: Stale lock file found (PID ${existing_pid} not running). Removing."
        rm -f "${LOCK_FILE}"
    fi
fi

echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"; log "Lock released."' EXIT

# ── Load environment ──────────────────────────────────────────────────────────
if [ ! -f "${ENV_FILE}" ]; then
    log "ERROR: .env file not found at ${ENV_FILE}"
    exit 1
fi

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

# ── Validate required environment variables ───────────────────────────────────
required_vars=(
    VAULT_REPO
    VAULT_DEPLOY_KEY_PATH
    VAULT_BRANCH
    ANTHROPIC_API_KEY
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        log "ERROR: Required environment variable '${var}' is not set."
        exit 1
    fi
done

# ── Verify Claude Code is available ──────────────────────────────────────────
if ! command -v claude &>/dev/null; then
    log "ERROR: 'claude' CLI not found. Install Claude Code first."
    exit 1
fi

# ── Pull latest vault clone ───────────────────────────────────────────────────
log "INFO: Pulling latest vault from ${VAULT_REPO}/${VAULT_BRANCH}"

GIT_SSH_CMD="ssh -i ${VAULT_DEPLOY_KEY_PATH} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

if [ -d "${VAULT_CLONE_DIR}/.git" ]; then
    GIT_SSH_COMMAND="${GIT_SSH_CMD}" git -C "${VAULT_CLONE_DIR}" fetch origin "${VAULT_BRANCH}" 2>>"${LOG_FILE}"
    GIT_SSH_COMMAND="${GIT_SSH_CMD}" git -C "${VAULT_CLONE_DIR}" reset --hard "origin/${VAULT_BRANCH}" 2>>"${LOG_FILE}"
else
    log "INFO: No vault clone found — performing initial clone"
    mkdir -p "$(dirname "${VAULT_CLONE_DIR}")"
    GIT_SSH_COMMAND="${GIT_SSH_CMD}" git clone \
        --depth=50 \
        --branch "${VAULT_BRANCH}" \
        "git@github.com:${VAULT_REPO}.git" \
        "${VAULT_CLONE_DIR}" 2>>"${LOG_FILE}"
fi

log "INFO: Vault clone up to date at ${VAULT_CLONE_DIR}"

# ── Run headless Claude Code agent ───────────────────────────────────────────
log "INFO: Starting nightly Claude Code agent"

cd "${VAULT_CLONE_DIR}"

AGENT_EXIT_CODE=0
claude \
    --dangerously-skip-permissions \
    < "${AGENT_PROMPT}" \
    >> "${LOG_FILE}" 2>&1 || AGENT_EXIT_CODE=$?

if [ "${AGENT_EXIT_CODE}" -ne 0 ]; then
    log "ERROR: Claude Code agent exited with code ${AGENT_EXIT_CODE}"
    exit "${AGENT_EXIT_CODE}"
fi

log "INFO: Claude Code agent completed successfully"

# ── Push vault changes ────────────────────────────────────────────────────────
log "INFO: Checking for vault changes to push"

if git -C "${VAULT_CLONE_DIR}" diff --quiet HEAD; then
    log "INFO: No changes to push — vault already up to date"
else
    log "INFO: Pushing agent changes to ${VAULT_REPO}/${VAULT_BRANCH}"
    GIT_SSH_COMMAND="${GIT_SSH_CMD}" git -C "${VAULT_CLONE_DIR}" push origin "${VAULT_BRANCH}" 2>>"${LOG_FILE}"
    log "INFO: Push complete"
fi

log "INFO: Nightly processing complete"
