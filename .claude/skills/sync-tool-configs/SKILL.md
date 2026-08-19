---
name: sync-tool-configs
description: Two-way sync between the .claude/ source of truth and every other tool (Cursor, Codex, …). Forward - regenerate native agent files + the AGENTS.md roster so adding/changing an agent propagates everywhere. Reverse - import agents authored in another tool back into .claude/. Triggers on "sync tool configs", "regenerate agents", "update the other tools", "port the agents", "import agents from cursor/codex", "pull in that agent I built", "are the tools in sync", or after adding/removing an agent or skill. Owned by the config-steward agent.
---

## Response contract

Honor the **Response contract** in `.claude/CLAUDE.md`: headline → `Decisions needed:` →
evidence bullets. This skill writes only generated files, so no record preview is required —
but always report what changed.

## What this skill does

Keeps the OS portable across tools with zero drift, **in both directions**. `.claude/agents/**`
is the single source of truth; this skill regenerates the native agent definitions for every
other supported tool (forward) and pulls tool-authored agents back into the OS (reverse).

Generated (never hand-edited): `.cursor/agents/*.md`, `.codex/agents/*.toml`,
`AGENTS.md` roster block. Owner: the `config-steward` agent.

## Steps

1. **Pull in anything authored in another tool (reverse):**
   ```
   python scripts/sync-tool-configs.py --import
   ```
   New Cursor/Codex agents land in `.claude/agents/imported/` and are propagated to all tools.
   Report each imported agent and remind that they need review (tools/model) and relocation to
   `office/`/`dev/`. Name collisions are reported, not overwritten.

2. **Regenerate (forward):**
   ```
   python scripts/sync-tool-configs.py
   ```
   Report the summary (created / updated / removed, per tool). (`--import` already runs this,
   so this is only needed on its own when nothing was imported.)

3. **Verify parity (both directions):**
   ```
   python scripts/sync-tool-configs.py --check
   ```
   Must exit 0. Non-zero lists *forward-stale* generated files (regenerate) and/or *importable*
   tool-authored agents (run `--import`).

4. **Report** the agent count and the tools now in sync. If nothing changed, say so plainly.

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
