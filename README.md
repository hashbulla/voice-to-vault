# voice-to-vault

A production-grade agentic AI pipeline that captures French voice notes via Telegram, transcribes them with OpenAI Whisper, classifies them with Claude Haiku, and inserts structured markdown notes into an Obsidian second brain — all without touching a keyboard. The vault then serves as persistent, structured context for professional Claude Code sessions across four freelance domains. This is not a hobby project: it runs on a Hetzner VPS, processes notes end-to-end in under 30 seconds, handles failures gracefully at every step, and costs under €4/month in infrastructure.

---

## Architecture

### Real-Time Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MOBILE / DESKTOP                                                           │
│                                                                             │
│  ┌─────────────────┐                                                        │
│  │  Telegram App   │  voice message (OGG)  +  optional caption "!en"        │
│  └────────┬────────┘                                                        │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │ HTTPS webhook  POST /webhook/telegram
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  HETZNER CX22  (€3.79/mo · Debian 12 · Docker)                             │
│                                                                             │
│  Caddy ──TLS──▶  OpenClaw ──▶  vault-writer skill                          │
│                                │                                            │
│                    ┌───────────▼──────────────────────┐                    │
│                    │  2. getFile → download OGG        │                    │
│                    │  3. detect !en language override  │                    │
│                    │  4. ──────────────────────────────┼──▶ OpenAI Whisper │
│                    │     whisper-1 · verbose_json      │    (~$0.006/note) │
│                    │  5. ──────────────────────────────┼──▶ Claude Haiku   │
│                    │     domain · tags · slug · summary│    (~$0.0001/note)│
│                    │  6. assemble YAML + markdown      │                    │
│                    │  7. write 00_Inbox/<date>-<slug>  │                    │
│                    │  8. git commit + push ────────────┼──▶ GitHub (SSH)   │
│                    │  9. Telegram ACK ✅               │                    │
│                    └───────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
                           │
                    SSH Deploy Key (write-only)
                           │
                           ▼
              ┌────────────────────────────┐
              │  GitHub (private)          │
              │  second-brain-vault · main │
              └──────────────┬─────────────┘
                             │
              Obsidian Git auto-pull (5 min)
              ┌──────────────┴──────────────┐
              ▼                             ▼
   ┌──────────────────┐         ┌───────────────────────┐
   │  Obsidian Mobile │         │  Obsidian Desktop     │
   │  iOS / Android   │         │  Kali Linux           │
   └──────────────────┘         └──────────┬────────────┘
                                           │
                              claude --dangerously-skip-permissions
                                           ▼
                              ┌──────────────────────────┐
                              │  Claude Code sessions    │
                              │  reads _System/CLAUDE.md │
                              │  for project context     │
                              └──────────────────────────┘
```

### Nightly Agent Loop (23:00 CET)

```
Hetzner cron (TZ=Europe/Paris)
        │
        ▼
   run.sh
   ├── lock guard (prevent overlap)
   ├── git pull vault clone
   ├── claude --dangerously-skip-permissions < AGENT_PROMPT.md
   │         │
   │         ├── CONTEXT LOADING
   │         │   ├── Read _System/Meta.md
   │         │   ├── Read _System/CLAUDE.md
   │         │   └── List 00_Inbox/ (status: inbox)
   │         │
   │         ├── FOR EACH INBOX NOTE
   │         │   ├── (a) validate domain + projects
   │         │   ├── (b) move to 10_Projects/ or 20_Areas/
   │         │   └── (d) append wikilink to _Daily/<today>.md
   │         │
   │         ├── CLAUDE.md MAINTENANCE
   │         │   └── update AGENT:RECENT_CONTEXT section only
   │         │
   │         └── WRITE AGENT LOG
   │             └── _System/agent-log/<date>-nightly.md
   │
   └── git push vault changes ──▶ GitHub main
```

---

## Capability Matrix

| Capability                    | STT Obsidian Plugin                | voice-to-vault                                     |
| ----------------------------- | ---------------------------------- | -------------------------------------------------- |
| Capture surface               | Obsidian must be open              | Telegram, any device, app closed, walking          |
| Classification                | None — you manually tag everything | Claude Haiku generates domain, tags, summary, slug |
| Frontmatter                   | None                               | Full YAML schema on every note                     |
| Cross-device frictionless     | ❌                                  | ✅                                                  |
| Git history / audit trail     | ❌                                  | ✅ per-note commits                                 |
| Pipeline extensibility        | ❌ zero                             | ✅ add skills at will                               |
| Works when Obsidian is closed | ❌                                  | ✅                                                  |

---

## Stack

| Component | Technology | Role | Why this, not that |
|-----------|-----------|------|--------------------|
| Capture | Telegram Bot API | Voice message ingestion | Zero-friction: native mobile voice recorder, no app install |
| Orchestration | OpenClaw | Skill dispatch on Telegram events | Declarative routing + retry + ACL without building a custom FastAPI service that needs auth, health checks, and error handling from scratch |
| Transcription | OpenAI Whisper API (`whisper-1`) | Speech-to-text | API is $0.006/min vs. self-hosted Whisper on CX22 that would saturate the VPS CPU for 30+ seconds per note |
| Classification | Claude Haiku (`claude-haiku-4-5`) | Domain/tag/summary inference | Haiku: $0.25/MTok input — cheapest capable model for structured JSON extraction; GPT-3.5-turbo is comparable cost but Claude's instruction following is more reliable for strict JSON-only output |
| Vault storage | GitHub private repo | Markdown persistence + history | Free, fully replicated, git history = audit trail; Obsidian Sync at €8/mo adds no value over a Deploy Key workflow |
| Sync | Obsidian Git (community plugin) | Desktop + mobile vault sync | No monthly fee; works on both iOS and Android via HTTPS PAT; survives offline periods with merge-on-reconnect |
| VPS | Hetzner CX22 (€3.79/mo) | Always-on pipeline host | Cheapest EU VPS with sufficient RAM for Docker + OpenClaw; Koyeb/Fly.io free tiers don't support persistent SSH key mounts needed for vault write operations |
| TLS | Caddy | HTTPS termination for Telegram webhook | Automatic Let's Encrypt; zero configuration vs. nginx + certbot cron |
| Agent runtime | Claude Code (`claude --dangerously-skip-permissions`) | Nightly vault organisation | Headless file manipulation with language understanding; no custom script can match the vault-aware routing logic in AGENT_PROMPT.md |
| Note format | Obsidian markdown + YAML frontmatter | Structured knowledge storage | Queryable via Dataview; compatible with any future markdown pipeline |

---

## Prerequisites

| Requirement | Version | Where to get it |
|-------------|---------|-----------------|
| Hetzner Cloud account | — | https://www.hetzner.com/cloud |
| Hetzner CX22 instance | Debian 12 | Hetzner Cloud Console |
| GitHub account | — | https://github.com |
| Telegram account + @BotFather access | — | https://t.me/BotFather |
| OpenAI API key | API v1 | https://platform.openai.com/api-keys |
| Anthropic API key | API v1 | https://console.anthropic.com |
| Docker + Docker Compose | 24.x + v2 | Installed by `hetzner/setup.sh` |
| Claude Code CLI | latest | Installed by `hetzner/setup.sh` |
| Node.js | 20 LTS | Installed by `hetzner/setup.sh` |
| Domain name (for TLS) | — | Any registrar; point A record to Hetzner IP |

**Monthly cost estimate:** Hetzner CX22 €3.79 + OpenAI Whisper ~$0.18 (at 30 notes/day × 30s avg) + Claude Haiku ~$0.002 = **~€3.97/month total.**

---

## Deployment — Full Runbook

### 1. Provision Hetzner CX22

1. Log in to https://console.hetzner.cloud
2. Create Server:
   - Location: Nuremberg (or Falkenstein — both EU, GDPR compliant)
   - Image: **Debian 12**
   - Type: **CX22** (2 vCPU, 4 GB RAM)
   - SSH key: paste your Kali Linux public key (`~/.ssh/id_ed25519.pub`)
   - Firewall: none at creation — `setup.sh` configures UFW
3. Note the public IPv4 address.

### 2. Point your domain to the VPS

```bash
# In your DNS provider, create an A record:
# vault.yourdomain.com  →  <hetzner-public-ip>
# TTL: 300 seconds

# Verify propagation:
dig +short vault.yourdomain.com
```

### 3. Run the VPS bootstrap script

```bash
ssh root@<hetzner-ip>

# Download and execute the bootstrap script
curl -fsSL https://raw.githubusercontent.com/hashbulla/voice-to-vault/main/hetzner/setup.sh | bash

# The script installs: Docker, Caddy, Node.js, Claude Code, Claude Code,
# UFW rules, SSH hardening, log directories, and registers the nightly cron.
```

**⚠️ Verify your SSH key is authorised before the script hardens SSH.**
SSH password authentication is disabled at the end of the script.

### 4. Generate the vault Deploy Key

```bash
# On the Hetzner VPS (as root):
ssh-keygen -t ed25519 -C "voice-to-vault-deploy-key" \
  -f /root/.ssh/vault_deploy_key -N ""

# Show the public key — you will add this to GitHub in the next step
cat /root/.ssh/vault_deploy_key.pub
```

Go to `https://github.com/hashbulla/second-brain-vault/settings/keys`:
- Click **Add deploy key**
- Title: `voice-to-vault-hetzner`
- Key: paste the public key output
- ✅ **Allow write access** — required for note commits

### 5. Create your Telegram bot

1. Open Telegram → search `@BotFather` → `/newbot`
2. Name: `Voice to Vault` (or any name)
3. Username: `yourusername_vault_bot` (must end in `bot`)
4. Copy the **API token** — you will use it as `TELEGRAM_BOT_TOKEN`

Get your Telegram user ID:
1. Message `@userinfobot`
2. Copy the **Id** field — this is your `TELEGRAM_ALLOWED_USER_ID`

### 6. Configure .env

```bash
cd /opt/voice-to-vault
cp .env.template .env
vim .env
```

Fill in all values. See the [Configuration Reference](#configuration-reference) table below.

Key values to set:
```bash
TELEGRAM_BOT_TOKEN=1234567890:AAF...
TELEGRAM_ALLOWED_USER_ID=123456789
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
VAULT_REPO=hashbulla/second-brain-vault
VAULT_DEPLOY_KEY_PATH=/root/.ssh/vault_deploy_key
OPENCLAW_WEBHOOK_URL=https://vault.yourdomain.com
OPENCLAW_WEBHOOK_SECRET=$(openssl rand -hex 32)
OPENCLAW_DOMAIN=vault.yourdomain.com
```

### 7. Deploy services

```bash
cd /opt/voice-to-vault
make deploy
# Expected: pulls images, starts openclaw + caddy containers
# Verify: make status
```

### 8. Register the Telegram webhook

```bash
make register-webhook
# Expected output: {"ok":true,"result":true,"description":"Webhook was set"}

# Verify:
make check-webhook
# Expected: "url" field contains your OPENCLAW_WEBHOOK_URL
```

### 9. Bootstrap the Obsidian vault

**Initialize the GitHub repo:**
```bash
# Clone second-brain-vault to your Kali desktop
git clone git@github.com:hashbulla/second-brain-vault.git ~/vault
cd ~/vault

# The repo should already contain the scaffold from the second repository
# Verify structure:
ls -la
```

**Install Obsidian (Kali Linux):**
```bash
# Download Obsidian AppImage from https://obsidian.md/download
chmod +x Obsidian-*.AppImage
./Obsidian-*.AppImage

# Open vault: ~/vault
```

**Install Obsidian plugins (in order):**
1. Settings → Community Plugins → Turn on community plugins
2. Install: **Obsidian Git** → configure with SSH (see `obsidian/plugins.md`)
3. Install: **Dataview** → enable JavaScript queries
4. Install: **Templater** → set template folder to `_System/Templates`
5. Install: **Calendar** → set daily note folder to `_Daily`

**Mobile (iOS/Android):**
1. Install Obsidian from App Store / Play Store
2. Install Obsidian Git → configure with HTTPS + GitHub PAT
3. Install same plugin set as desktop

### 10. End-to-end smoke test

```bash
# 1. Verify OpenClaw health
make smoke-test

# 2. Send a voice message to your Telegram bot from your personal account
#    Say anything in French, e.g.:
#    "Note sur le projet K3s : j'ai configuré le load balancer MetalLB
#     ce matin, ça marche bien avec les nodes ARM."

# 3. Within 30 seconds you should receive a Telegram ACK:
#    ✅ Note captured — 2024-01-15 14:32
#    📋 k3s-metallb-load-balancer
#    🗂 Domain: Engineering
#    🏷 Tags: #kubernetes #k3s #networking #load-balancing
#    ...

# 4. Verify vault commit:
#    https://github.com/hashbulla/second-brain-vault/commits/main
#    Expected: commit "feat(inbox): k3s-metallb-load-balancer [openclaw]"

# 5. Pull vault in Obsidian → verify note appears in 00_Inbox/
```

---

## Configuration Reference

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | string | **required** | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | string | **required** | Your numeric Telegram user ID (from @userinfobot) |
| `OPENAI_API_KEY` | string | **required** | OpenAI API key for Whisper transcription |
| `WHISPER_LANGUAGE` | string | `fr` | ISO 639-1 default language. Override per-note with caption `!en` |
| `WHISPER_PROMPT` | string | see template | Vocabulary hint list — improves technical term recognition |
| `ANTHROPIC_API_KEY` | string | **required** | Anthropic API key for Claude Haiku classification |
| `CLAUDE_MODEL` | string | `claude-haiku-4-5` | Anthropic model for classification. Use latest Haiku for cost efficiency |
| `VAULT_REPO` | string | **required** | GitHub repo in `owner/name` format |
| `VAULT_DEPLOY_KEY_PATH` | string | **required** | Absolute path to SSH Deploy Key with write access to vault repo |
| `VAULT_BRANCH` | string | `main` | Branch to commit vault notes to |
| `OPENCLAW_PORT` | integer | `8080` | Internal port OpenClaw listens on |
| `OPENCLAW_WEBHOOK_URL` | string | **required** | Public HTTPS URL where Telegram sends webhooks |
| `OPENCLAW_WEBHOOK_SECRET` | string | **required** | Secret token for webhook authenticity verification |
| `OPENCLAW_DOMAIN` | string | **required** | Domain for Caddy TLS (must have A record pointing to VPS) |
| `NIGHTLY_AGENT_LOG` | string | `/var/log/voice-to-vault` | Directory for nightly agent log files |
| `NIGHTLY_CRON_TZ` | string | `Europe/Paris` | Cron timezone for nightly scheduling |
| `DEBUG` | integer | `0` | Set to `1` for verbose pipeline logging |
| `MAX_AUDIO_BYTES` | integer | `26214400` | Max accepted audio file size (25 MB = Whisper API limit) |
| `GIT_AUTHOR_NAME` | string | `voice-to-vault[bot]` | Git author name on vault commits |
| `GIT_AUTHOR_EMAIL` | string | `bot@voice-to-vault.local` | Git author email on vault commits |

---

## Use Cases

### Use Case 1 — AI Automation Client Project

**Scenario:** You're on the Paris RER, heading back from a client kickoff for a process automation mission. The prospect wants an AI agent to handle invoice routing from their ERP. You don't have your laptop, but you need to capture the decision points before you forget them.

**Telegram voice input (French):**
> *"Note de réunion client : Acme Industries, mission automatisation des factures. Ils utilisent SAP S/4HANA avec un workflow d'approbation manuel actuellement à 3 jours de délai. Ils veulent descendre à 4 heures. Budget confirmé 45 000 euros. Décision clé : on va utiliser Claude pour extraire les métadonnées des PDFs et LangGraph pour l'orchestration du workflow. Prochaine étape : proof of concept sur les 50 dernières factures PDF, deadline dans 2 semaines. Contact : Pierre Lefebvre, DSI."*

**Resulting vault note (`00_Inbox/2024-01-15-acme-invoice-automation-poc.md`):**
```markdown
---
id: a7f3c2d1-8b4e-4f1a-9c2d-3e7f8a9b0c1d
date: 2024-01-15T18:32:14+01:00
type: voice-note
lang: fr
source: openclaw
status: inbox
domain: Business
projects: []
tags: [ai-automation, client-meeting, invoice-processing, langgraph, proof-of-concept]
duration_sec: 42.3
transcript_model: whisper-1
---
> **Résumé IA :** Réunion de cadrage client Acme Industries pour une mission d'automatisation de traitement de factures SAP, budget 45k€, POC Claude+LangGraph en 2 semaines.

---

Note de réunion client : Acme Industries, mission automatisation des factures. Ils utilisent SAP S/4HANA avec un workflow d'approbation manuel actuellement à 3 jours de délai. Ils veulent descendre à 4 heures. Budget confirmé 45 000 euros. Décision clé : on va utiliser Claude pour extraire les métadonnées des PDFs et LangGraph pour l'orchestration du workflow. Prochaine étape : proof of concept sur les 50 dernières factures PDF, deadline dans 2 semaines. Contact : Pierre Lefebvre, DSI.
```

**Opening prompt for billable Claude Code session:**
```
Read _System/CLAUDE.md. Then read 10_Projects/ai-automation/acme-industries/_index.md.

Context: I'm starting work on the Acme Industries invoice automation POC.
The scope is: extract metadata from 50 PDF invoices using Claude claude-haiku-4-5,
route them through a LangGraph approval workflow, targeting < 4h processing time.
The client stack is SAP S/4HANA. Budget: €45k. POC deadline: 2 weeks from today.

Today's task: design the LangGraph state machine for the 3-stage approval workflow
(extraction → validation → routing). Output a Python module with the full graph
definition, state schema, and node functions. Include error handling for
malformed PDFs. Use the Anthropic SDK directly — no LangChain abstractions.
```

---

### Use Case 2 — DevSecOps / Kubernetes Architecture Decision

**Scenario:** You're reviewing a K3s cluster design for a new mission. The client wants multi-tenant workload isolation. Walking to the station, you record your thinking on the CNI choice before the decision meeting tomorrow.

**Telegram voice input (French):**
> *"Réflexion architecture K3s mission Betacloud : le client veut isolation multi-tenant niveau réseau. J'hésite entre Cilium et Calico. Cilium c'est eBPF natif, meilleure observabilité avec Hubble, Network Policy niveau L7, mais overhead mémoire plus important sur les petits noeuds ARM. Calico c'est plus mature, plus simple à opérer, mais pas de L7. Pour un cluster de 6 noeuds avec workloads isolés par namespace client, je pense partir sur Cilium avec les Network Policies strictes par défaut. À valider avec le client sur la contrainte mémoire des noeuds."*

**Resulting vault note (`00_Inbox/2024-01-15-betacloud-k3s-cni-cilium-vs-calico.md`):**
```markdown
---
id: b8e4d3f2-9c5f-4g2b-0d3e-4f8g9a0b1c2e
date: 2024-01-15T19:14:07+01:00
type: voice-note
lang: fr
source: openclaw
status: inbox
domain: Engineering
projects: []
tags: [kubernetes, k3s, cilium, network-policy, multi-tenant]
duration_sec: 38.7
transcript_model: whisper-1
---
> **Résumé IA :** Analyse comparative Cilium vs Calico pour mission K3s Betacloud multi-tenant, avec préférence pour Cilium eBPF malgré la contrainte mémoire ARM.

---

Réflexion architecture K3s mission Betacloud : le client veut isolation multi-tenant niveau réseau. J'hésite entre Cilium et Calico. [...]
```

**Opening prompt for billable Claude Code session:**
```
Read _System/CLAUDE.md. Then read 10_Projects/devsecops/betacloud/_index.md.

Context: I'm preparing for a CNI decision meeting on a K3s cluster for Betacloud.
Cluster: 6 nodes (ARM64, 4 GB RAM each). Requirement: strict network isolation
per client namespace, with L7 policy capability preferred. Two options:
Cilium (eBPF, L7, Hubble) vs Calico (mature, L3/L4 only).

Today's task: produce a decision matrix comparing Cilium and Calico across these
dimensions: L7 policy support, memory footprint on ARM64, operational complexity,
observability (metrics + traces), Kubernetes version compatibility with K3s 1.29,
and zero-trust readiness. Then write the recommended Helm values for Cilium
installation on K3s with strict default-deny NetworkPolicy. Output should be a
markdown document I can share with the client tomorrow.
```

---

### Use Case 3 — Freelance Deal Flow

**Scenario:** A recruiter called about a 6-month DevSecOps contract in Paris. You took a 3-minute call in the hallway. Now you need to log the qualification before the details fade.

**Telegram voice input (French):**
> *"Appel Maxence Dubois, cabinet Talent IT, opportunité DevSecOps mission Paris 8ème. Client final : fintech non divulguée. Durée 6 mois renouvelable. TJM 700 à 750 euros, full remote possible 3 jours par semaine. Stack : Kubernetes OpenShift, GitOps Argo CD, Jenkins. Profil recherché : expertise RBAC et audit sécurité K8s. Intéressant mais le TJM est 50 euros en dessous de mon tarif. J'ai dit que je revenais d'ici jeudi. À évaluer : est-ce que la flexibilité remote compense le delta TJM, et est-ce que c'est fintech ou banking réglementé."*

**Resulting vault note (`00_Inbox/2024-01-15-talent-it-devsecops-openshift-paris.md`):**
```markdown
---
id: c9f5e4g3-0d6g-4h3c-1e4f-5g9h0a1b2c3f
date: 2024-01-15T11:47:22+01:00
type: voice-note
lang: fr
source: openclaw
status: inbox
domain: Business
projects: []
tags: [deal-flow, devsecops, openshift, freelance, prospect-qualification]
duration_sec: 61.2
transcript_model: whisper-1
---
> **Résumé IA :** Qualification d'une opportunité DevSecOps 6 mois Paris via Talent IT, TJM 700-750€ full remote partiel, OpenShift/ArgoCD, décision attendue jeudi.

---

Appel Maxence Dubois, cabinet Talent IT, opportunité DevSecOps mission Paris 8ème. [...]
```

**Opening prompt for billable Claude Code session:**
```
Read _System/CLAUDE.md. Then read 10_Projects/freelance/deal-flow/_index.md
and list all notes tagged #deal-flow from the last 30 days.

Context: I received a freelance DevSecOps opportunity — 6 months, OpenShift/
ArgoCD/Jenkins, Paris 8th, 3 days remote, TJM €700-750. My current rate is €800.
The recruiter is Maxence Dubois at Talent IT. Decision deadline: Thursday.

Today's task:
1. Create a prospect qualification note in 10_Projects/freelance/deal-flow/
   with the details from the inbox note dated 2024-01-15.
2. Write a 5-criterion Go/No-Go scorecard for this opportunity (rate delta,
   remote flexibility, tech stack alignment, sector risk, duration).
3. Draft a reply email to Maxence that buys 2 more days and asks two
   qualifying questions: client industry confirmation + ArgoCD version
   (to estimate ramp-up time).

Output the scorecard and email draft. Do not send anything — output only.
```

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| Bot receives message but no ACK | OpenClaw container down | `make status && make restart` |
| ACK received but no vault commit | Deploy Key has no write access | GitHub repo → Settings → Keys → check "Allow write access" |
| `❌ Pipeline failed at step 4` | OpenAI API key invalid or quota exhausted | Check key at https://platform.openai.com/api-keys; check usage/billing |
| `❌ Pipeline failed at step 5` | Anthropic API key invalid | Check key at https://console.anthropic.com |
| `❌ Pipeline failed at step 8` | SSH deploy key not found or wrong path | Check `VAULT_DEPLOY_KEY_PATH` in `.env`; verify file exists with `ls -la` |
| Telegram webhook not triggered | Webhook URL not reachable | `make check-webhook`; verify Caddy is running and domain resolves |
| Nightly agent runs but no notes moved | All notes have `status: needs-review` | Check frontmatter; verify project wikilinks point to existing folders |
| Nightly agent skips CLAUDE.md update | Agent markers missing | Restore markers in `_System/CLAUDE.md`: see `agents/CLAUDE.md.template` |
| Obsidian Git sync conflict | Concurrent writes from mobile and nightly agent | Accept incoming (agent) changes; manual notes use a dedicated folder |
| Audio transcribed in wrong language | Note sent without `!en` caption | Add caption `!en` to override; or update `WHISPER_LANGUAGE=en` in `.env` |
| `whisper-1` misreads technical terms | Vocabulary list incomplete | Add terms to `WHISPER_PROMPT` in `.env`; see `docs/WHISPER_PROMPT.md` |
| Nightly cron not running | TZ prefix missing or cron not installed | `crontab -l`; compare with `hetzner/crontab.example` |
| Container OOM killed | Insufficient VPS memory | CX22 (4 GB) is sufficient; check for memory leaks with `docker stats` |

---

## Contributing

### Issue Template

When opening a bug report, include:
- **Pipeline step** where the failure occurred (1–10)
- **Telegram ACK error message** if received
- **Container logs:** `docker compose logs --tail=50 openclaw`
- **Environment:** VPS OS, Docker version, OpenClaw version
- **Reproducer:** what voice message content triggers the issue (if applicable)

### PR Checklist

Before opening a pull request:
- [ ] All Python code passes `make lint`
- [ ] New env vars are documented in `.env.template` and the Configuration Reference table
- [ ] Skill changes are tested end-to-end (voice → vault)
- [ ] AGENT_PROMPT.md changes are tested with a dry run (`claude --print < agents/nightly_processor/AGENT_PROMPT.md`)
- [ ] No API keys, tokens, or secrets in any committed file
- [ ] RUNBOOK.md updated if the change affects operations

### Adding a New OpenClaw Skill

1. Create `openclaw/skills/<skill-name>/` directory
2. Write `skill.yml` (see `vault-writer/skill.yml` for reference)
3. Implement `main.py` with a `handle(event: dict) -> dict` entry point
4. Register the skill in `openclaw/config.yml` under `skills:` and add a route
5. Add required env vars to `.env.template` with comments
6. Document the skill in `obsidian/plugins.md` if it affects Obsidian sync
7. Test with `make restart && make logs` before opening a PR

### Skill Development Guide

The vault-writer skill follows this pattern — use it as a template:

```
skill/
├── skill.yml         ← metadata, triggers, env var declarations
├── main.py           ← handle(event) entry point, step-by-step pipeline
├── <module>.py       ← one module per concern (transcriber, classifier, etc.)
└── requirements.txt  ← pip dependencies
```

Naming conventions:
- Step numbers match the pipeline documentation (1–10)
- Each step wrapped in `try/except` with explicit error notification
- All external calls use explicit timeouts
- Logging: `logger.info()` for success paths, `logger.error()` for failures

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built by [hashbulla](https://github.com/hashbulla) — Staff AI Engineer · DevSecOps · Rennes, Bretagne.*
