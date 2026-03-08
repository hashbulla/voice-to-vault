#!/usr/bin/env bash
# =============================================================================
# setup.sh — Hetzner CX22 full bootstrap for voice-to-vault
# =============================================================================
# Run as root on a fresh Debian 12 (Bookworm) Hetzner CX22 instance.
#
# What this script does:
#   1. System update and essential packages
#   2. UFW firewall (allow SSH + 80 + 443 only)
#   3. SSH hardening (disable password auth, root login)
#   4. Docker and Docker Compose install (official Docker repos)
#   5. Claude Code CLI install
#   6. Log directory creation
#   7. voice-to-vault deployment from GitHub
#   8. Vault deploy key installation
#   9. Nightly cron registration
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hashbulla/voice-to-vault/main/hetzner/setup.sh | bash
#   OR:
#   scp hetzner/setup.sh root@<hetzner-ip>:/tmp/setup.sh && ssh root@<hetzner-ip> bash /tmp/setup.sh
#
# Prerequisites (provide as env vars or answer interactive prompts):
#   VAULT_DEPLOY_KEY_PRIVATE — contents of the SSH private key for vault repo
#   GITHUB_TOKEN (optional) — for cloning private repos
# =============================================================================

set -euo pipefail

## ── Configuration ─────────────────────────────────────────────────────────────
DEPLOY_DIR="/opt/voice-to-vault"
LOG_DIR="/var/log/voice-to-vault"
DEPLOY_KEY_PATH="/root/.ssh/vault_deploy_key"
GITHUB_REPO="hashbulla/voice-to-vault"
NODE_VERSION="20"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

die() { log_error "$*"; exit 1; }

## ── Root check ────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || die "This script must be run as root."

log_info "==================================================================="
log_info "voice-to-vault — Hetzner CX22 Bootstrap"
log_info "==================================================================="
log_info "Host: $(hostname) | Debian: $(cat /etc/debian_version)"
log_info ""

## ── Step 1: System update ─────────────────────────────────────────────────────
log_info "Step 1/9: System update and essential packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git vim htop unzip jq \
    ufw fail2ban \
    ca-certificates gnupg lsb-release \
    python3 python3-pip \
    apt-transport-https \
    software-properties-common
log_info "✓ System updated"

## ── Step 2: UFW firewall ──────────────────────────────────────────────────────
log_info "Step 2/9: Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp     # HTTP/3 / QUIC
echo "y" | ufw enable
ufw status verbose
log_info "✓ UFW configured"

## ── Step 3: SSH hardening ─────────────────────────────────────────────────────
log_info "Step 3/9: Hardening SSH configuration..."
SSHD_CONFIG="/etc/ssh/sshd_config"

# Backup original
cp "${SSHD_CONFIG}" "${SSHD_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"

# Apply hardened settings
cat >> "${SSHD_CONFIG}" << 'EOF'

# voice-to-vault hardening additions
 PasswordAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
LoginGraceTime 30
EOF

systemctl reload sshd
log_warn "SSH password authentication DISABLED. Ensure your SSH key is authorized before disconnecting."
log_info "✓ SSH hardened"

## ── Step 4: Docker install ────────────────────────────────────────────────────
log_info "Step 4/9: Installing Docker from official repository..."

# Remove any old Docker installations
apt-get remove -y -qq docker docker-engine docker.io containerd runc 2>/dev/null || true

# Add Docker official GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker

# FIX C: Create non-root user for container workloads (uid/gid 1000)
useradd -r -u 1000 -g 1000 -s /sbin/nologin openclaw 2>/dev/null || true
mkdir -p /opt/voice-to-vault/vault-clone
chown 1000:1000 /opt/voice-to-vault/vault-clone
log_info "✓ Container user openclaw (uid 1000) created"

docker --version
docker compose version
log_info "✓ Docker installed"

## ── Step 5: Claude Code CLI install ──────────────────────────────────────────
log_info "Step 5/9: Installing Node.js ${NODE_VERSION} and Claude Code CLI..."

# Install Node.js via NodeSource
curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -
apt-get install -y -qq nodejs
node --version
npm --version

# Install Claude Code globally
npm install -g @anthropic-ai/claude-code
claude --version
log_info "✓ Claude Code installed"

## ── Step 6: Log directory setup ──────────────────────────────────────────────
log_info "Step 6/9: Creating log directories..."
mkdir -p "${LOG_DIR}"
chmod 755 "${LOG_DIR}"
log_info "✓ Log directory created: ${LOG_DIR}"

## ── Step 7: Clone voice-to-vault repository ──────────────────────────────────
log_info "Step 7/9: Cloning voice-to-vault repository..."

if [ -d "${DEPLOY_DIR}" ]; then
    log_warn "${DEPLOY_DIR} already exists — pulling latest."
    git -C "${DEPLOY_DIR}" pull origin main
else
    git clone "https://github.com/${GITHUB_REPO}.git" "${DEPLOY_DIR}"
fi

log_info "✓ Repository cloned to ${DEPLOY_DIR}"
log_info ""
log_warn "ACTION REQUIRED: Configure your .env file:"
log_warn "  cp ${DEPLOY_DIR}/.env.template ${DEPLOY_DIR}/.env"
log_warn "  vim ${DEPLOY_DIR}/.env"
log_warn ""

# Copy .env template and harden permissions immediately
if [ ! -f "${DEPLOY_DIR}/.env" ]; then
    cp "${DEPLOY_DIR}/.env.template" "${DEPLOY_DIR}/.env"
    # FIX D: Restrict .env — API keys must never be world-readable
    chmod 600 "${DEPLOY_DIR}/.env"
    chown root:root "${DEPLOY_DIR}/.env"
    log_info "✓ .env created with secure permissions (600)"
fi

## ── Step 8: Install vault deploy key ─────────────────────────────────────────
log_info "Step 8/9: Installing vault Deploy Key..."
mkdir -p /root/.ssh
chmod 700 /root/.ssh

if [ -n "${VAULT_DEPLOY_KEY_PRIVATE:-}" ]; then
    echo "${VAULT_DEPLOY_KEY_PRIVATE}" > "${DEPLOY_KEY_PATH}"
    # FIX A: Deploy key must be 400 (read-only by owner) — not 600
    chmod 400 "${DEPLOY_KEY_PATH}"
    log_info "✓ Deploy key written from environment variable"
else
    log_warn "VAULT_DEPLOY_KEY_PRIVATE not set."
    log_warn "Generate a deploy key manually with:"
    log_warn "  ssh-keygen -t ed25519 -C 'voice-to-vault-deploy-key' -f ${DEPLOY_KEY_PATH} -N ''"
    log_warn "Then add the PUBLIC key to your vault GitHub repo → Settings → Deploy Keys (WRITE access)."
    log_warn "Set VAULT_DEPLOY_KEY_PATH=${DEPLOY_KEY_PATH} in ${DEPLOY_DIR}/.env"
fi

# FIX A: Harden .ssh directory and key files
chmod 700 /root/.ssh
if [ -f "${DEPLOY_KEY_PATH}" ]; then
    chmod 400 "${DEPLOY_KEY_PATH}"
fi
if [ -f "${DEPLOY_KEY_PATH}.pub" ]; then
    chmod 400 "${DEPLOY_KEY_PATH}.pub"
fi

# Add GitHub to known hosts to prevent first-connect prompts
ssh-keyscan -H github.com >> /root/.ssh/known_hosts 2>/dev/null
chmod 644 /root/.ssh/known_hosts
log_info "✓ GitHub added to known_hosts"

## ── Step 9: Nightly cron registration ────────────────────────────────────────
log_info "Step 9/9: Registering nightly cron job..."
chmod +x "${DEPLOY_DIR}/agents/nightly_processor/run.sh"

CRON_JOB="0 23 * * * TZ=Europe/Paris ${DEPLOY_DIR}/agents/nightly_processor/run.sh >> ${LOG_DIR}/cron.log 2>&1"

# Install cron job (idempotent)
(crontab -l 2>/dev/null | grep -v "nightly_processor"; echo "${CRON_JOB}") | crontab -
crontab -l | grep nightly_processor

log_info "✓ Cron job registered: nightly at 23:00 CET"

## ── Security verification ─────────────────────────────────────────────────────
echo ""
echo "--- Security verification ---"

stat -c "%a %n" "${DEPLOY_KEY_PATH}" 2>/dev/null | \
    grep -q "^400" \
    && echo "✅ Deploy key permissions OK (400)" \
    || echo "❌ FAIL: Deploy key permissions incorrect (expected 400)"

stat -c "%a %n" "${DEPLOY_DIR}/.env" 2>/dev/null | \
    grep -q "^600" \
    && echo "✅ .env permissions OK (600)" \
    || echo "❌ FAIL: .env permissions incorrect (expected 600)"

echo ""

## ── Summary ───────────────────────────────────────────────────────────────────
echo ""
log_info "==================================================================="
log_info "Bootstrap complete!"
log_info "==================================================================="
echo ""
echo "  Next steps:"
echo "  ─────────────────────────────────────────────────────────────────"
echo "  1. Configure:  vim ${DEPLOY_DIR}/.env"
echo "  2. Deploy key: ssh-keygen -t ed25519 -f ${DEPLOY_KEY_PATH} -N ''"
echo "               Add public key to vault repo as Write Deploy Key"
echo "  3. Deploy:     cd ${DEPLOY_DIR} && make deploy"
echo "  4. Webhook:    make register-webhook"
echo "  5. Test:       make smoke-test"
echo ""
echo "  Logs: tail -f ${LOG_DIR}/nightly-\$(date +%Y-%m-%d).log"
echo ""
