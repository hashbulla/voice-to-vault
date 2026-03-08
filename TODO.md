## Improvement Proposals — Ranked by ROI

Here are six improvements I consider core, not overkill. Ordered by value-to-effort ratio.

***

**Improvement A — Slash Commands for professional sessions (High ROI, Low Effort)**

Two `.claude/commands/` files. Zero infrastructure. Directly addresses your Q25 use case — getting full project context into a Claude Code session in one command.

```
/load-project  → reads CLAUDE.md + project _index.md + last 7 days
                  of notes → confirms context → ready to build
/new-project   → scaffolds a new 10_Projects/<domain>/<client>/ folder
                  with _index.md from template, prompts for objective,
                  deliverables, and client context from your voice notes
```

***

**Improvement B — Whisper audio quality gate (High ROI, Low Effort)**

The Whisper verbose_json response includes `no_speech_prob` per segment. A note recorded in a noisy environment (street, metro) may transcribe as garbage — correct YAML, correct structure, wrong content. Currently this reaches your vault silently.

Add a pre-classification check in `transcriber.py`: if average `no_speech_prob` across segments exceeds 0.4, set `status: needs-review` and add a `⚠️ Low audio quality` warning to the Telegram ACK before the note is classified. Zero API cost increase, one conditonal block.

***

**Improvement C — TODO system with lean task structure (High ROI, Medium Effort)**

Not a full task manager — a deliberate, minimal structure that integrates with the existing vault and pipeline.

```
_TODO/
├── work.md     ← professional tasks, one per section
└── personal.md ← personal tasks
```

Each task is a markdown checkbox with frontmatter-style inline metadata:
```markdown
- [ ] Préparer HLD pour client Legrand #devsecops due:2026-03-15 remind:true
- [ ] Renouveler assurance pro #business due:2026-03-20 remind:false
```

OpenClaw gets a new `/todo add <text>` Telegram command — you can add tasks by text message, not just voice. Reminders fire **only** for tasks with `remind:true` and a `due:` date within the next 24 hours. **No reminders without explicit opt-in.** Claude Code enrichment is deferred to Phase 4 when the list has real data.

***

**Improvement D — Monthly cost digest (Medium ROI, Low Effort)**

Your pipeline makes paid API calls on every voice note. As a freelancer and DevSecOps engineer, you should know exactly what this costs — both for personal budgeting and because clients reviewing your portfolio will ask about cost governance.

Add a lightweight cost tracker to `main.py`: after each successful pipeline run, append one line to `_System/costs/YYYY-MM.md`:
```
2026-03-08T19:23 | duration:103s | whisper:$0.0103 | haiku:$0.0002 | total:$0.0105
```

The nightly agent generates a monthly summary in `_Daily/` on the first of each month. Total cost visibility in your vault, zero external service.

***

**Improvement E — CI badges + semantic versioning (Medium ROI, Low Effort)**

Your `voice-to-vault` repo is a public portfolio artifact. Potential freelance clients will land on the README. Two things that signal production maturity in under 5 seconds:

1. `[![CI](https://github.com/hashbulla/voice-to-vault/actions/workflows/ci.yml/badge.svg)](...)` badge in the README header
2. A `CHANGELOG.md` with semantic versioning (`v1.0.0`, `v1.1.0`) — one entry per patch prompt run

A repo with no CI badge and no changelog reads as a weekend project. A repo with green CI and a versioned changelog reads as something you maintain and ship to clients.

***

**Improvement F — Vault health weekly digest (Lower ROI, Low Effort — defer)**

A Friday 18:00 OpenClaw cron that sends you a Telegram summary:
```
📊 Vault week in review — 2026-W11

📥 Notes captured:   12
✅ Notes processed:  11
⏳ Inbox backlog:    1
🗂 Top domains:      Engineering (6), Business (3), Life (2)
🏷 Top tags:         #kubernetes (4), #freelance (3), #k3s (2)
📁 Active projects:  3
```

High delight, low code — one new cron entry and one new OpenClaw skill reading `_Daily/` files. I recommend deferring this until the vault has 3+ weeks of real data so the digest is meaningful rather than empty.

***
