# Architecture — voice-to-vault

## System Overview

voice-to-vault is a three-layer agentic pipeline:

1. **Capture layer** — Telegram bot receives voice messages
2. **Processing layer** — OpenClaw skill transcribes, classifies, and vaults notes in real-time
3. **Organisation layer** — Nightly Claude Code agent routes and contextualises the vault

---

## Real-Time Pipeline (voice message → vault in < 30 seconds)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MOBILE / DESKTOP                                                           │
│                                                                             │
│  ┌─────────────────┐                                                        │
│  │  Telegram App   │  (voice message, optional caption "!en")               │
│  └────────┬────────┘                                                        │
└───────────┼─────────────────────────────────────────────────────────────────┘
            │ OGG audio + message metadata
            │ HTTPS webhook POST
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  HETZNER CX22 VPS (Debian 12)                                               │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  Caddy (TLS termination, Let's Encrypt auto-cert)                  │     │
│  └───────────────────────────────┬────────────────────────────────────┘     │
│                                  │ HTTP (internal)                          │
│  ┌───────────────────────────────▼────────────────────────────────────┐     │
│  │  OpenClaw Container                                                │     │
│  │                                                                    │     │
│  │  ┌──────────────────────┐   ┌───────────────────────────────────┐ │     │
│  │  │  Telegram Connector  │──▶│  vault-writer Skill               │ │     │
│  │  │  (webhook receiver)  │   │                                   │ │     │
│  │  │  guard: user_id ACL  │   │  1. Receive event                 │ │     │
│  │  └──────────────────────┘   │  2. getFile → download OGG        │ │     │
│  │                             │  3. Detect !en language           │ │     │
│  │                             │  4. ──▶ OpenAI Whisper API        │ │     │
│  │                             │  5. ──▶ Claude Haiku API          │ │     │
│  │                             │  6. Build YAML + markdown note    │ │     │
│  │                             │  7. Write 00_Inbox/YYYY-MM-DD-... │ │     │
│  │                             │  8. git commit + push via SSH     │ │     │
│  │                             │  9. Send Telegram ACK             │ │     │
│  │                             └───────────────────────────────────┘ │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────┬──────────────────────┬───────────────────────────┘
                          │                      │
             HTTPS API    │                      │ HTTPS API
             (Whisper-1)  │                      │ (Claude Haiku)
                          ▼                      ▼
             ┌────────────────────┐  ┌───────────────────────┐
             │  OpenAI API        │  │  Anthropic API        │
             │  whisper-1 model   │  │  claude-haiku-4-5     │
             │  verbose_json resp │  │  JSON classification  │
             └────────────────────┘  └───────────────────────┘

                     │ SSH/git push (Deploy Key)
                     ▼
             ┌────────────────────────────────────────────────┐
             │  GitHub                                        │
             │  hashbulla/second-brain-vault (PRIVATE)        │
             │  Branch: main                                  │
             │  New commit: feat(inbox): <slug> [openclaw]    │
             └──────────────────────┬─────────────────────────┘
                                    │
                    Obsidian Git pull (every 5 min)
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
         ┌──────────────────┐           ┌──────────────────────┐
         │  Obsidian Mobile │           │  Obsidian Desktop    │
         │  (iOS/Android)   │           │  (Kali Linux)        │
         │  Read-only sync  │           │  Full editing        │
         └──────────────────┘           └──────────┬───────────┘
                                                   │
                                        claude --dangerously-skip-permissions
                                        (Claude Code sessions)
                                                   │
                                                   ▼
                                        ┌──────────────────────┐
                                        │  Claude Code         │
                                        │  Reads _System/      │
                                        │  CLAUDE.md for       │
                                        │  project context     │
                                        └──────────────────────┘
```

---

## Nightly Agent Loop (23:00 CET)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  HETZNER CX22 VPS                                                           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  cron (TZ=Europe/Paris)                                              │   │
│  │  0 23 * * *  agents/nightly_processor/run.sh                        │   │
│  └────────────────────────────┬─────────────────────────────────────────┘   │
│                               │                                             │
│                               ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  run.sh                                                              │   │
│  │                                                                      │   │
│  │  1. Lock guard (prevent overlapping runs)                           │   │
│  │  2. Load .env                                                       │   │
│  │  3. git pull vault clone ──────────────────────────────────────────┼──┐ │
│  │  4. claude --dangerously-skip-permissions < AGENT_PROMPT.md        │  │ │
│  │  5. git push vault changes ─────────────────────────────────────────┼──┘ │
│  │  6. Release lock                                                    │   │
│  └────────────────────────────┬─────────────────────────────────────────┘   │
│                               │ stdin                                       │
│                               ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Claude Code Agent (headless)                                        │   │
│  │                                                                      │   │
│  │  CONTEXT LOADING                                                     │   │
│  │  └── Read _System/Meta.md                                           │   │
│  │  └── Read _System/CLAUDE.md                                         │   │
│  │  └── Read exclusions.txt                                            │   │
│  │  └── List 00_Inbox/ (status: inbox)                                 │   │
│  │                                                                      │   │
│  │  FOR EACH INBOX NOTE                                                 │   │
│  │  ├── (a) Validate domain + projects classification                  │   │
│  │  ├── (b) Move to correct destination folder                         │   │
│  │  └── (d) Append wikilink to _Daily/<today>.md                       │   │
│  │                                                                      │   │
│  │  CLAUDE.md MAINTENANCE                                               │   │
│  │  └── Rewrite AGENT:RECENT_CONTEXT section only                      │   │
│  │      - Active projects                                               │   │
│  │      - Last 7 days domains                                          │   │
│  │      - Recurring tags this week                                     │   │
│  │                                                                      │   │
│  │  WRITE AGENT LOG                                                     │   │
│  │  └── _System/agent-log/<date>-nightly.md                            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          │ SSH/git push (Deploy Key)
          ▼
  ┌───────────────────────────────────────┐
  │  GitHub: second-brain-vault (main)    │
  │  Commits:                             │
  │  - moved notes to correct areas       │
  │  - updated _Daily/<date>.md           │
  │  - updated _System/CLAUDE.md          │
  │  - new agent log entry               │
  └───────────────────────────────────────┘
```

---

## Data Flow — Voice Note Lifecycle

```
[Telegram voice] ──OGG──▶ [Whisper] ──text──▶ [Claude Haiku] ──JSON──▶ [note_formatter]
                                                                               │
                                                                         YAML frontmatter
                                                                         + summary blockquote
                                                                         + raw transcript
                                                                               │
                                                                               ▼
                                                              [00_Inbox/YYYY-MM-DD-slug.md]
                                                                               │
                                                                         git commit+push
                                                                               │
                                                                        [GitHub main branch]
                                                                               │
                                                                      Obsidian Git pull
                                                                               │
                                                              ┌────────────────┴──────────────────┐
                                                              │    Nightly Agent                  │
                                                              │    validate + route               │
                                                              │                                   │
                                                              ▼                                   ▼
                                               [10_Projects/<domain>/<slug>/]    [20_Areas/<domain>/]
                                                       (if project match)             (otherwise)
```

---

## Infrastructure Layers

```
┌─────────────────────────────────────────────────────────────┐
│  EXTERNAL SERVICES (paid APIs)                              │
│  ┌──────────────┐  ┌──────────────────┐                    │
│  │ OpenAI API   │  │  Anthropic API   │                    │
│  │ whisper-1    │  │  claude-haiku-4-5│                    │
│  │ ~$0.18/mo    │  │  ~$0.002/mo      │                    │
│  └──────────────┘  └──────────────────┘                    │
├─────────────────────────────────────────────────────────────┤
│  ORCHESTRATION (paid VPS)                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Hetzner CX22  €3.79/mo                              │  │
│  │  2 vCPU, 4 GB RAM, 40 GB NVMe, Debian 12            │  │
│  │  Docker: OpenClaw, Caddy                             │  │
│  │  Cron: nightly Claude Code agent                    │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  STORAGE (free tier)                                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  GitHub (private)                                    │  │
│  │  hashbulla/second-brain-vault                       │  │
│  │  ~1 MB/month growth at 3 voice notes/day            │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  CLIENT (free)                                              │
│  ┌─────────────────┐  ┌──────────────────────────────────┐ │
│  │  Telegram Bot   │  │  Obsidian (desktop + mobile)     │ │
│  │  (free)         │  │  Obsidian Git (free plugin)      │ │
│  └─────────────────┘  └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

Total monthly cost: ~€3.79 + ~$0.182 ≈ €3.97/month
```

---

## Security Model

| Boundary | Mechanism | Why |
|----------|-----------|-----|
| Telegram bot access | User ID allowlist (TELEGRAM_ALLOWED_USER_ID) | Bot is public — without allowlist anyone could trigger the pipeline |
| Webhook authenticity | OPENCLAW_WEBHOOK_SECRET header | Prevents spoofed webhook calls from non-Telegram sources |
| Vault write access | SSH Deploy Key (write-only, scoped to one repo) | Principle of least privilege — key cannot read other repos |
| VPS access | SSH key-only, password auth disabled, UFW | Standard VPS hardening |
| API keys | Container environment only, never logged | Keys visible only to root on VPS |
| Agent scope | exclusions.txt + hardcoded guardrails in prompt | Prevents Claude Code from modifying irreversible or personal content |
