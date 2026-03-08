# Runbook — voice-to-vault Operations

This document covers day-to-day operations, restart procedures, debugging,
and update workflows for the voice-to-vault production system.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Check service health | `make status` or `curl http://localhost:8080/health` |
| Tail live logs | `make logs` |
| Restart OpenClaw | `make restart` |
| Stop everything | `make stop` |
| Start everything | `make start` |
| Check Telegram webhook | `make check-webhook` |
| View nightly agent log | `tail -f /var/log/voice-to-vault/nightly-$(date +%Y-%m-%d).log` |
| Manual nightly run | `cd /opt/voice-to-vault && bash agents/nightly_processor/run.sh` |

---

## Service Restart Procedures

### OpenClaw is not responding

```bash
# Check container status
docker compose ps

# Check recent logs for errors
docker compose logs --tail=100 openclaw

# Restart the container
make restart

# If still failing, do a full stop/start
make stop && make start

# Verify health after restart
curl -sf http://localhost:8080/health
```

### Caddy TLS certificate issue

```bash
# Check Caddy logs
docker compose logs --tail=50 caddy

# Force certificate renewal (Caddy auto-renews but manual override if needed)
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile

# Check domain resolution
dig +short yourdomain.com
```

### Telegram webhook not receiving updates

```bash
# Verify webhook registration
make check-webhook

# Re-register if url is empty or wrong
make register-webhook

# Test with a manual getUpdates (disable webhook first, then re-enable)
set -a; source .env; set +a
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"
```

---

## Debugging Pipeline Failures

### Step-by-step failure isolation

When you receive a `❌ Pipeline failed at step N` Telegram message:

**Step 2 — Audio download failure**
```bash
# Check Telegram bot token validity
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"

# Check container can reach Telegram CDN
docker compose exec openclaw curl -sf https://api.telegram.org
```

**Step 4 — Whisper transcription failure**
```bash
# Check OpenAI API key and quota
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" | jq '.data[0]'

# Check audio size (Whisper limit: 25 MB)
docker compose logs openclaw | grep "Downloaded"
```

**Step 5 — Claude classification failure**
```bash
# Check Anthropic API key
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-haiku-4-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}'
```

**Step 7/8 — Git push failure**
```bash
# Test deploy key access
GIT_SSH_COMMAND="ssh -i ${VAULT_DEPLOY_KEY_PATH} -o StrictHostKeyChecking=no" \
  git ls-remote git@github.com:${VAULT_REPO}.git

# Check deploy key has write access (not read-only)
# Go to: https://github.com/${VAULT_REPO}/settings/keys
# Verify "Allow write access" is checked for the vault_deploy_key

# Check vault clone state
ls -la /tmp/vault-clone/
git -C /tmp/vault-clone status
```

---

## Update Procedures

### Update voice-to-vault code

```bash
cd /opt/voice-to-vault

# Pull latest code
git pull origin main

# Restart to pick up changes
make restart

# Verify
make status && make logs
```

### Update OpenClaw image

```bash
cd /opt/voice-to-vault

# Pull latest image
docker compose pull openclaw

# Recreate container with new image
docker compose up -d --force-recreate openclaw

# Verify health
make status
```

### Update Whisper vocabulary prompt

```bash
# Edit .env
vim /opt/voice-to-vault/.env

# Restart to pick up new WHISPER_PROMPT value
make restart

# See docs/WHISPER_PROMPT.md for update guidelines
```

### Rotate Telegram bot token

```bash
# 1. Get new token from @BotFather: /mybots → your bot → API Token → Revoke and generate
# 2. Update .env
vim /opt/voice-to-vault/.env   # update TELEGRAM_BOT_TOKEN

# 3. Restart
make restart

# 4. Re-register webhook (new token changes the webhook URL)
make register-webhook
```

### Rotate vault deploy key

```bash
# 1. Generate new key
ssh-keygen -t ed25519 -C "voice-to-vault-deploy-key-$(date +%Y%m%d)" \
  -f /root/.ssh/vault_deploy_key_new -N ""

# 2. Add new public key to GitHub vault repo
cat /root/.ssh/vault_deploy_key_new.pub
# → GitHub: https://github.com/${VAULT_REPO}/settings/keys → Add deploy key (write access)

# 3. Update .env
vim /opt/voice-to-vault/.env   # update VAULT_DEPLOY_KEY_PATH

# 4. Rename key
mv /root/.ssh/vault_deploy_key /root/.ssh/vault_deploy_key_old
mv /root/.ssh/vault_deploy_key_new /root/.ssh/vault_deploy_key
chmod 400 /root/.ssh/vault_deploy_key

# 5. Restart
make restart

# 6. Test push
GIT_SSH_COMMAND="ssh -i /root/.ssh/vault_deploy_key -o StrictHostKeyChecking=no" \
  git ls-remote git@github.com:${VAULT_REPO}.git

# 7. Remove old key from GitHub after confirming new key works
```

---

## Deploy Key Rotation

Formal procedure for rotating the vault SSH Deploy Key (e.g. after suspected exposure):

1. **Generate new key pair** on the VPS:
   ```bash
   ssh-keygen -t ed25519 -C "voice-to-vault-deploy-key-$(date +%Y%m%d)" \
     -f /root/.ssh/vault_deploy_key_new -N ""
   chmod 400 /root/.ssh/vault_deploy_key_new
   ```

2. **Add new public key to GitHub Deploy Keys** (write access):
   ```bash
   cat /root/.ssh/vault_deploy_key_new.pub
   # → https://github.com/hashbulla/second-brain-vault/settings/keys
   # → Add deploy key → Allow write access → Save
   ```

3. **Update `VAULT_DEPLOY_KEY_PATH` in `.env`**:
   ```bash
   vim /opt/voice-to-vault/.env
   # Set: VAULT_DEPLOY_KEY_PATH=/root/.ssh/vault_deploy_key_new
   ```

4. **Restart services to pick up the new key**:
   ```bash
   make restart
   ```

5. **Verify pipeline with smoke test**:
   ```bash
   make smoke-test
   # Send a test voice message — confirm ACK and vault commit appear
   ```

6. **Remove old key from GitHub Deploy Keys** once new key is confirmed working:
   - Go to: `https://github.com/hashbulla/second-brain-vault/settings/keys`
   - Find the old key by its creation date or title
   - Click **Delete** → confirm

> **Key permissions:** Deploy keys must always be `chmod 400` (read-only by owner).
> Never `600` or `644`. Verify: `stat -c "%a" /root/.ssh/vault_deploy_key` → must output `400`.

---

## Processing Schedule

The vault is processed automatically three times daily:

- **06:00 CET**: morning run — processes overnight voice notes
- **14:00 CET**: afternoon run — processes morning session notes
- **23:00 CET**: nightly run — full daily hygiene pass

On-demand processing:

```bash
# Telegram: send /process to your bot

# CLI (from VPS, reads TRIGGER_SECRET from .env automatically):
make process

# Direct execution:
ssh root@<vps> bash /opt/voice-to-vault/agents/nightly_processor/run.sh
```

---

## Nightly Agent Operations

### Manual nightly run

```bash
# Run immediately (outside of cron schedule)
cd /opt/voice-to-vault
bash agents/nightly_processor/run.sh

# Watch real-time output
tail -f /var/log/voice-to-vault/nightly-$(date +%Y-%m-%d).log
```

### View agent logs

```bash
# Today's log
cat /var/log/voice-to-vault/nightly-$(date +%Y-%m-%d).log

# List all nightly logs
ls -la /var/log/voice-to-vault/

# Search for errors across all runs
grep -r "ERROR\|WARN" /var/log/voice-to-vault/nightly-*.log
```

### Agent ran but didn't process notes

Common causes:
1. Inbox notes have `status: needs-review` — check frontmatter, these are intentionally skipped.
2. Project wikilinks reference non-existent folders — check `10_Projects/` structure.
3. ANTHROPIC_API_KEY not set in `.env` — agent requires it to run.
4. Lock file stuck — check `/tmp/voice-to-vault-nightly.lock`.

```bash
# Remove stuck lock (only if no agent process is running)
ls -la /tmp/voice-to-vault-nightly.lock
cat /tmp/voice-to-vault-nightly.lock
kill -0 $(cat /tmp/voice-to-vault-nightly.lock) && echo "running" || rm /tmp/voice-to-vault-nightly.lock
```

---

## Disk Space Management

```bash
# Check Docker space usage
docker system df

# Check log directory
du -sh /var/log/voice-to-vault/

# Check vault clone size
du -sh /tmp/vault-clone/

# Prune unused Docker images (safe to run anytime)
docker image prune -f

# Remove old nightly logs (keep last 90 days)
find /var/log/voice-to-vault -name "nightly-*.log" -mtime +90 -delete
```

---

## VPS Monitoring

### Resource check

```bash
# CPU / memory
htop

# Disk
df -h

# Docker stats
docker stats --no-stream

# Network connections
ss -tlnp
```

### Hetzner console

If SSH is inaccessible, use the Hetzner Cloud Console:
→ https://console.hetzner.cloud → Your Server → Console

---

## Backup and Recovery

### What is backed up automatically

- **Vault content:** GitHub `second-brain-vault` repo is the authoritative backup.
  Every note commit is a recoverable snapshot. GitHub retains full history.
- **OpenClaw SQLite DB:** Volume `voice-to-vault-openclaw-data` on VPS.
  Not critical — contains only event deduplication state.

### Recovering from VPS loss

The Hetzner VPS is stateless — all state lives in GitHub.

```bash
# Provision new CX22 instance, then:
curl -fsSL https://raw.githubusercontent.com/hashbulla/voice-to-vault/main/hetzner/setup.sh | bash

# Restore .env (keep a secure offline backup of API keys)
# Restore vault_deploy_key (keep offline backup or generate new + re-register)
# Run: make deploy && make register-webhook
```

Recovery time objective: < 60 minutes from bare Hetzner instance.
