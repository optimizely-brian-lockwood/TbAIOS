# Antigravity config — TbAI OS

Antigravity reads `AGENTS.md` at the repo root. **That is your primary instruction set.**
This file adds Antigravity-specific guidance only.

## Load order (binding, every session)

1. `AGENTS.md` — portable brain.
2. `CLAUDE.md` — engagement identity.
3. `.claude/CLAUDE.md` — generic OS brain, source of truth for how the OS works.
4. `initiative/CLAUDE.md` — active initiative scope, if present.

Start every session with `git pull origin main`; stop on merge conflict.

## Using Antigravity's capabilities with this OS

- **Multi-agent orchestration / dynamic subagents:** assign one role from `.claude/agents/`
  per subagent. Keep initiative separation intact across subagents — never let two subagents
  write to two different initiatives' records in one run without explicit scoping.
- **Built-in browser / scheduled background tasks:** corporate data (Teams, Outlook,
  SharePoint, Salesforce) is **read-only and explicit-invocation only**. Do not schedule
  background jobs that fetch corporate data without explicit user consent.
- **Custom-agent SDK:** if hosting OS roles as custom agents, source each agent's prompt from
  the matching `.claude/agents/**/*.md` file — do not paraphrase; drift from the source
  breaks the hard rules.

## Hard rules

Full list in `AGENTS.md → "Hard rules"`. The load-bearing ones: initiative separation is
absolute; records are append-only; always file raw input; corp-data read-only and
explicit-only; adopt one role at a time. File-placement hooks are not enforced outside Claude
Code — follow `docs/FILE-ORGANIZATION.md` manually.
