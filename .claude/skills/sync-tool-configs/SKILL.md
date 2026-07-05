---
name: sync-tool-configs
description: Regenerate every non-Claude-Code tool config (Cursor, Codex, and the AGENTS.md roster) from the .claude/ source of truth, so adding or changing an agent propagates everywhere. Triggers on "sync tool configs", "regenerate agents", "update the other tools", "port the agents", "are the tools in sync", or after adding/removing an agent or skill. Owned by the config-steward agent.
---

## Response contract

Honor the **Response contract** in `.claude/CLAUDE.md`: headline → `Decisions needed:` →
evidence bullets. This skill writes only generated files, so no record preview is required —
but always report what changed.

## What this skill does

Keeps the OS portable across tools with zero drift. `.claude/agents/**` is the single source
of truth; this skill regenerates the native agent definitions for every other supported tool
plus the roster block in `AGENTS.md`.

Generated (never hand-edited): `.cursor/agents/*.md`, `.codex/agents/*.toml`,
`AGENTS.md` roster block. Owner: the `config-steward` agent.

## Steps

1. **Regenerate:**
   ```
   python scripts/sync-tool-configs.py
   ```
   Report the summary (created / updated / removed, per tool).

2. **Verify parity:**
   ```
   python scripts/sync-tool-configs.py --check
   ```
   Must exit 0. If it does not, something wrote a generated file by hand — regenerate and
   re-check.

3. **Report** the agent count and the tools now in sync. If nothing changed, say so plainly.

## When to run

- Normally you do not have to — the `PostToolUse` hook auto-runs `--hook` mode whenever a
  file under `.claude/agents/` or `.claude/skills/` is written.
- Run manually after: editing the generator, onboarding a new tool, changing the tool-name
  mapping, or any time `--check` is failing.

## Escalate to the config-steward agent when

- A new tool needs a renderer added to the generator.
- The tool-name mapping needs updating for a tool's real identifiers.
- Generated output looks wrong and the fix is not obvious (fix the source or generator, never
  the generated file).
