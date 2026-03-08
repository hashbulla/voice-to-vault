# Obsidian Plugin Setup Guide

Complete, opinionated plugin configuration for the voice-to-vault Obsidian vault.
Follow the steps in order — some plugins depend on others being configured first.

---

## Required Plugins

### 1. Obsidian Git (Community)

**Purpose:** Syncs vault with `hashbulla/second-brain-vault` GitHub repo.
The vault is the source of truth — this plugin replaces Obsidian Sync.

**Install:** Settings → Community Plugins → Browse → "Obsidian Git" → Install → Enable

**Configuration** (Settings → Obsidian Git):
```
Auto pull interval: 5 (minutes)
Auto push interval: 0 (manual or on commit)
Auto commit message: "sync: {{date}} [obsidian-git]"
Commit message date format: YYYY-MM-DD HH:mm
Pull on startup: ON
Push on backup: ON
Sync method: Rebase
Disable push: OFF
```

**Authentication:** Use the same Deploy Key configured on the Hetzner VPS.
On desktop (Kali Linux):
```bash
# Clone the vault repo with SSH
git clone git@github.com:hashbulla/second-brain-vault.git ~/vault

# Set the vault as your Obsidian vault root
# Then configure Obsidian Git to use SSH remote
```

On mobile (iOS/Android):
- Use HTTPS with a GitHub Personal Access Token (PAT).
- Scope: `repo` only.
- Store in iOS/Android keychain via the plugin's credential manager.

---

### 2. Dataview (Community)

**Purpose:** Query and display vault data as dynamic tables and lists.
Used in project indices and daily notes.

**Install:** Settings → Community Plugins → Browse → "Dataview" → Install → Enable

**Configuration** (Settings → Dataview):
```
Enable JavaScript Queries: ON
Inline Query Prefix: =
Enable Inline Queries: ON
Date Format: YYYY-MM-DD
Automatic View Refreshing: ON
Refresh Interval: 5000 (ms)
```

**Example query (project index):**
```dataview
TABLE domain, status, date
FROM "00_Inbox"
WHERE type = "voice-note"
SORT date DESC
LIMIT 20
```

---

### 3. Templater (Community)

**Purpose:** Applies templates from `_System/Templates/` when creating new notes.
The nightly agent uses the same template structure.

**Install:** Settings → Community Plugins → Browse → "Templater" → Install → Enable

**Configuration** (Settings → Templater):
```
Template folder location: _System/Templates
Trigger Templater on new file creation: ON
Enable folder templates: ON
```

**Folder templates:**
| Folder | Template |
|--------|----------|
| `_Daily/` | `_System/Templates/daily.md` |
| `10_Projects/` | `_System/Templates/project-index.md` |
| `00_Inbox/` | `_System/Templates/voice-note.md` |

---

### 4. Calendar (Community)

**Purpose:** Visual calendar sidebar linking to daily notes in `_Daily/`.

**Install:** Settings → Community Plugins → Browse → "Calendar" → Install → Enable

**Configuration** (Settings → Calendar):
```
Words per dot: 250
Show week number: OFF
Confirm before creating new note: OFF
Daily note format: YYYY-MM-DD
Daily note folder: _Daily
Daily note template: _System/Templates/daily.md
```

---

### 5. Tag Wrangler (Community)

**Purpose:** Rename and manage tags consistently across the vault.
Essential for maintaining clean kebab-case tag taxonomy.

**Install:** Settings → Community Plugins → Browse → "Tag Wrangler" → Install → Enable

No configuration required — right-click any tag in the Tags panel to rename/merge.

---

## Recommended Core Plugin Settings

Enable these in Settings → Core Plugins:

| Plugin | Setting |
|--------|---------|
| Backlinks | Show backlinks in document: ON |
| Outgoing links | ON |
| Tag pane | ON |
| File recovery | Snapshot interval: 5min, Max snapshots: 20 |
| Daily notes | Folder: `_Daily`, Template: `_System/Templates/daily.md` |
| Templates | Template folder: `_System/Templates` |
| Workspaces | ON (save desktop vs mobile layouts separately) |

---

## .obsidian/app.json Recommended Settings

Apply in Settings → Editor / Appearance:

```
Default editing mode: Source mode
Vim key bindings: OFF (unless you prefer vim)
Show line numbers: OFF
Strict line breaks: OFF
Smart indent lists: ON
Fold heading: ON
Fold indent: ON
Use tabs: OFF
Tab size: 2
Spellcheck: ON (set to French as primary)
Default new file location: 00_Inbox
```

---

## Mobile-Specific Setup (iOS / Android)

1. Install Obsidian from App Store / Play Store.
2. Create vault → "Open folder as vault" → choose iCloud / local storage.
3. Enable Community Plugins (required: tap Settings → Community Plugins → Turn on).
4. Install: Obsidian Git, Dataview, Templater, Calendar (same as desktop).
5. Configure Obsidian Git with HTTPS + PAT (SSH is not supported on mobile).
6. Set auto-pull interval to 10 minutes for near-real-time inbox updates.

---

## Plugin Update Policy

Update plugins manually — avoid automatic updates in a production vault.
Before updating, check the plugin changelog for breaking changes to:
- Dataview query syntax
- Templater template function signatures
- Obsidian Git sync behaviour

Run `git status` before and after updates to verify no unexpected changes.
