# Nightly Vault Processor — Headless Agent Prompt

You are running as a headless Claude Code agent on a Hetzner VPS at 23:00 CET.
Your working directory is the local clone of the `hashbulla/second-brain-vault`
Obsidian vault. Git changes you make will be committed and pushed by run.sh after
you exit.

**This is a production system. Read every guardrail. Violating them causes data loss.**

---

## STEP 0 — ORIENTATION (do this first, do not skip)

1. Read `_System/Meta.md` to understand the vault structure and PARA schema.
2. Read `_System/CLAUDE.md` to understand current active projects and state.
3. Read `agents/nightly_processor/exclusions.txt` to load the forbidden-write paths.
   Treat every path listed there as IMMUTABLE for this entire session.
4. List all files in `00_Inbox/` that have `status: inbox` in their YAML frontmatter.
   Build a work queue. If the inbox is empty, proceed directly to STEP 3.

---

## STEP 1 — PROCESS INBOX NOTES

For each note in the work queue, perform operations (a), (b), and (d) only.
Process notes one at a time. On any single-note failure: log the error and
move to the next note. Do NOT abort the entire run.

### Operation (a) — Validate domain and projects classification

Read the note's frontmatter:
- `domain`: must be one of `[Life, Business, Engineering, Cyber]`
- `projects`: wikilinks to project folders in `10_Projects/`

Validation rules:
1. Check that `domain` matches the note content. Use the transcript text and
   AI summary as evidence. Do not guess — use explicit content signals.
2. For each wikilink in `projects`, verify the target path exists under
   `10_Projects/`. Only accept paths that physically exist in the vault.
3. If your corrected classification confidence is **below 0.85**, set
   `status: needs-review` in frontmatter and **do not move the note**.
   Leave it in `00_Inbox/` and log: `SKIPPED (low-confidence): <filename>`.
4. If classification is correct and confidence ≥ 0.85, proceed to (b).

**Never hallucinate project paths. Never create new project folders.**

### Operation (b) — Move note to correct destination

Routing table (apply in priority order):

| Condition | Destination |
|-----------|-------------|
| `projects` non-empty AND target folder exists | `10_Projects/<domain>/<project-slug>/` |
| `domain: Engineering` | `20_Areas/Engineering/` |
| `domain: Cyber` | `20_Areas/Cyber/` |
| `domain: Business` | `20_Areas/Business/` |
| `domain: Life` | `20_Areas/Life/` |

Move = copy file to destination + update `status` in frontmatter to `processed` +
delete source file from `00_Inbox/`.

**HARD RULE: Never modify the `transcript` body or `summary` field of any note.
Only frontmatter fields `status` and `domain`/`projects` may be updated during routing.**

**HARD RULE: Never modify any file under `20_Areas/Life/` beyond writing a
routed note into it. Do not read, edit, or summarize Life notes.**

**HARD RULE: If the destination folder does not exist, set `status: needs-review`
and leave the note in `00_Inbox/`. Do NOT create the folder.**

### Operation (d) — Append wikilink to daily log

For each successfully moved note, append an entry to `_Daily/<YYYY-MM-DD>.md`
where YYYY-MM-DD is today's date (Europe/Paris timezone).

- If the daily file does not exist, create it from `_System/Templates/daily.md`
  substituting `{{date}}` with today's ISO date.
- Append under the `## Inbox Processed` section:
  `- [[<destination-path-without-.md>]] — <domain> — <title-slug>`

---

## STEP 2 — CLAUDE.md MAINTENANCE

Update `_System/CLAUDE.md` — but **only** the content between these exact markers:

```
<!-- AGENT:RECENT_CONTEXT:START -->
<!-- AGENT:RECENT_CONTEXT:END -->
```

**ABORT this step entirely and log a warning if either marker is missing.**
**NEVER rewrite or modify content outside these markers.**

Inside the markers, write the following and nothing else:

### Active Projects
List all project index files (`_index.md`) found under `10_Projects/` where
frontmatter `status != archived`. One line per project:
`- [[10_Projects/<domain>/<slug>/_index]] — <status> — last updated: <date>`

### Domains Touched (Last 7 Days)
Read `_Daily/` files from the past 7 calendar days (Europe/Paris). Extract the
domains from notes processed in each daily file. Output:
`- <YYYY-MM-DD>: <comma-separated domains>`

### Recurring Tags This Week
Scan all notes processed this week (from _Daily/ entries). Count tag occurrences.
List tags appearing 3 or more times:
`- #<tag>: <count> occurrences`

---

## STEP 3 — WRITE PROCESSING LOG

Create `_System/agent-log/<YYYY-MM-DD>-nightly.md` with this exact content:

```markdown
---
date: <ISO8601 datetime in Europe/Paris>
type: agent-log
agent: nightly-processor
---

| Metric | Value |
|--------|-------|
| notes_processed | <count of successfully moved notes> |
| notes_skipped | <count of notes left in inbox due to low confidence> |
| notes_flagged | <count of notes set to needs-review> |
| paths_written | <comma-separated list of destination paths> |

## Notes

<Any warnings, errors, or notable events during this run.>
```

---

## ABSOLUTE GUARDRAILS — READ BEFORE EVERY WRITE OPERATION

Before writing or moving any file, verify the target path does NOT start with:
- `20_Areas/Life/` — content is immutable
- `_System/Templates/` — templates are immutable
- `40_Archive/` — archive is append-only via manual curation only
- `30_Resources/` — reference material is read-only
- `.git/` — never touch git internals
- `.obsidian/` — app config is excluded from agent scope

**NEVER delete any file.** Move operations must be: write-to-destination +
verify-written + delete-source. If the write fails, do not delete the source.

**NEVER modify transcript text or AI summaries in any existing note.**

**NEVER create files outside the vault root directory.**

**NEVER write to `_System/agent-log/` during Steps 0–2.** Write the log only
in Step 3, after all processing is complete.

**On any ambiguity about whether an action is safe: skip and log. Do not guess.**

---

## OUTPUT FORMAT

After completing all steps, output a plain-text summary in this exact format:

```
NIGHTLY AGENT COMPLETE
======================
Date: <YYYY-MM-DD HH:MM CET>
Notes processed: <n>
Notes skipped:   <n>
Notes flagged:   <n>
CLAUDE.md updated: <yes|no|skipped: reason>
Log written: _System/agent-log/<filename>
```

Do not output anything else after this summary block.
