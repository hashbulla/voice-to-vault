# Whisper Vocabulary Prompt — Rationale and Update Guide

## What the Whisper Prompt Does

The `WHISPER_PROMPT` environment variable provides a vocabulary hint list
to the OpenAI Whisper `whisper-1` model. It is not a system prompt — Whisper
is a transcription model, not a language model. The prompt serves two purposes:

1. **Vocabulary anchoring:** Whisper biases its tokeniser toward words that
   appear in the prompt. If you say "K3s" and the prompt contains "K3s",
   Whisper will transcribe it as "K3s" rather than "k3s", "case", or "caise".

2. **Context priming:** The prompt signal improves recognition accuracy for
   technical domain terms that are rare in Whisper's training data, especially
   when spoken in French.

## Current Vocabulary List (Rationale)

| Category | Terms | Rationale |
|----------|-------|-----------|
| Container/K8s | Kubernetes, K3s, RKE2, OpenShift, Helm, K8s | Core daily vocabulary; K3s frequently misheard as "k-three-s" |
| IaC/GitOps | Terraform, GitOps, CI/CD | Standard tooling; CI/CD slash often dropped in audio |
| OS/Runtime | Kali Linux, Debian, WSL2, Docker, Podman | Platform terms; "WSL2" commonly misheard as "double-u-s-l-two" |
| Cloud/PaaS | Koyeb, Fly.io, Cloudflare | Exotic names; without hint: "koieb", "fly-dot-io" |
| Languages | Python, Go, TypeScript, FastAPI | Prevent "python" → "pie thon", "Go" → "go" (too short) |
| Source control | GitHub, GitLab | Distinguish from each other in rapid speech |
| AI/ML | Claude Code, Claude Haiku, Anthropic, OpenAI, OpenClaw, Obsidian, MCP, RAG, LangGraph, Whisper | New terminology; "MCP" → "M-C-P", "RAG" → "rag" without hint |
| Comms | Telegram, BotFather, webhook | "BotFather" often split into two words without hint |
| Security | OSINT, pentest, Red Team, CVE, RBAC, mTLS, zero-trust, SOC, SIEM | Acronyms frequently lost in French speech |
| Architecture | microservices | Often transcribed as two words |
| Business | Freelance, GTM, SaaS | French pronunciation of "SaaS" = "saas" (sounds like "sa") |
| Location | Rennes, Bretagne | Local proper nouns |

## When to Update the Vocabulary List

Update the prompt when:
- A new client uses a non-standard technology name (e.g., proprietary platform)
- A recurring mistranscription appears in your vault notes
- You start a project in a new domain (add domain-specific terms)
- A framework or tool becomes a daily-use term

## How to Update

1. Edit `.env` — add terms to `WHISPER_PROMPT` (comma-separated)
2. Restart OpenClaw: `make restart`
3. Verify with a test voice note containing the new term

## Guidelines for Effective Terms

- **Include proper nouns** that Whisper's training data likely underrepresents.
- **Include acronyms** (especially 3-4 letter ones): RBAC, mTLS, SOC, SIEM.
- **Include version-specific names**: K3s, RKE2 (numbers in names confuse ASR).
- **Avoid common words** — they don't need bias and can distort surrounding text.
- **Keep total length under 224 tokens** (~900 characters) — Whisper's prompt
  window is limited and excess is silently truncated.

## Checking Prompt Length

```bash
python3 -c "
import os, tiktoken
enc = tiktoken.get_encoding('cl100k_base')
prompt = os.environ.get('WHISPER_PROMPT', '')
tokens = enc.encode(prompt)
print(f'Tokens: {len(tokens)} / 224')
print('OK' if len(tokens) <= 224 else 'WARNING: too long — excess will be truncated')
"
```

## Language Override (!en)

When you send a voice note with caption `!en`, `WHISPER_LANGUAGE` is overridden
to `en` for that note only. The vocabulary prompt remains the same — all domain
terms are valid in both French and English context. The Claude classifier prompt
is also told to produce the summary in English.
