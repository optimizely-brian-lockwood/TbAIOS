# Multi-tool support — use this OS from any agentic tool

The TbAI OS was built on Claude Code, but any team member can work inside the same operating
system from **OpenAI Codex, Cursor 3, Devin, Intent, or Google Antigravity**. This guide
explains how, and — honestly — what you gain and lose versus Claude Code.

## The design in one sentence

**One brain, generated everywhere.** The operating system's identity, team, routing,
frameworks, and hard rules live once — `.claude/CLAUDE.md`, the root `CLAUDE.md`, and the
roles/skills under `.claude/`. The portable summary (`AGENTS.md`) and every tool's **native
agent files** are *generated* from that source, and a hook keeps them current. No tool holds a
hand-written copy of anything, so nothing drifts.

```
.claude/CLAUDE.md + CLAUDE.md + .claude/agents/**   ← SOURCE OF TRUTH (edit here only)
        │  scripts/sync-tool-configs.py  (engine, hook-driven)
        ▼
    AGENTS.md (brain + generated roster)             ← portable brain (open standard)
    ├── .cursor/agents/*.md   + .cursor/rules/tbai-os.mdc   → Cursor 3 (native subagents)
    ├── .codex/agents/*.toml                                → Codex (native subagents)
    ├── .devin/playbook.md                                  → Devin
    ├── .intent/os.md                                       → Intent
    └── .antigravity/config.md                             → Antigravity
```

## Per-tool setup

| Tool | What it reads | You need to |
|---|---|---|
| **Claude Code** | `CLAUDE.md`, `.claude/` | Nothing — native. |
| **OpenAI Codex** | `AGENTS.md` + `.codex/agents/*.toml` (native subagents) | Open the repo; Codex loads `AGENTS.md` and the generated subagents automatically. |
| **Cursor 3** | `.cursor/rules/tbai-os.mdc` (`alwaysApply`) + `.cursor/agents/*.md` (native subagents) | Open the repo; the rule is always on and the generated agents appear in the Agents Window. |
| **Devin** | `AGENTS.md` + `.devin/playbook.md` + `.claude/agents/**` | Point Devin at the repo; add `.devin/playbook.md` as a knowledge/playbook source if prompted. |
| **Intent** | `.intent/os.md` → the CLAUDE/AGENTS files | Set Intent's living spec to the files listed in `.intent/os.md`. |
| **Antigravity** | `AGENTS.md` + `.antigravity/config.md` + `.claude/agents/**` | Open the repo; for custom-agent hosting, source prompts from `.claude/agents/**` (or the generated `.cursor/agents/`). |

## What ports, and how

| Capability | Claude Code | Codex / Cursor / Devin / Antigravity / Intent |
|---|---|---|
| Identity, routing, frameworks, hard rules | ✅ native | ✅ via `AGENTS.md` |
| Team roles (`.claude/agents/`) | ✅ executable subagents | ✅ **native subagents** — generated to `.cursor/agents/*.md`, `.codex/agents/*.toml`; Antigravity/Devin read `.claude/agents/` |
| Parallel multi-agent orchestration | ✅ native (subagents + Workflow) | ✅ each tool's own runner (Cursor Agents Window, Devin sub-agents, Antigravity subagents). Only the `Workflow` JS DSL is Claude-Code-specific |
| Skills (`.claude/skills/`) | ✅ `/skill` invocation | ⚠️ readable procedures — run the steps manually (not yet generated to native formats) |
| Hooks / guardrails | ✅ enforced on write | ⚠️ Cursor & Antigravity have native hooks (portable); Codex/Devin/Intent rely on prompt discipline |
| MCP connectors (corporate data, task systems) | ✅ per session | ⚠️ only if the tool supports MCP and you connect them |
| Slash-command skill invocation (`/ingest`) | ✅ | ❌ open `SKILL.md` and follow it manually |

**The honest bottom line:** on any tool you inherit the *full knowledge system* and the *team
as native runnable agents* — same records, roster, routing, and rules. The remaining
Claude-Code-only pieces are the `Workflow` orchestration DSL and slash-command skill
invocation; skills elsewhere are run as manual procedures. Cursor and Antigravity can even
enforce the guardrail hooks natively.

## Rules everyone must keep, regardless of tool

These are the load-bearing invariants. Breaking one corrupts the knowledge base:

1. **Initiative separation is absolute.** Never merge or blend records across initiatives.
   If which initiative a piece of work belongs to is unclear, stop and ask.
2. **Records are append-only.** Never delete; mark superseded.
3. **Always file raw source input** under `docs/records/inputs/YYYY-MM/`.
4. **Adopt one role at a time** — never blend two roles in a single pass.
5. **Corp-data is read-only and explicit-invocation only** — never auto-fetch from
   Teams / Outlook / SharePoint / Salesforce.
6. **Follow the response contract** — headline → decisions needed → evidence → preview
   before writing to `docs/records/`.

## Staying in sync — the generator, the hook, and the steward

When someone changes the OS — adds an agent, renames a role, retires one — every tool must
update too. That is automated, not manual, **and it works in both directions**:

- **Source of truth:** `.claude/agents/**`. This is where agents live.
- **Engine:** `scripts/sync-tool-configs.py`.
  - **Forward** (default): regenerates `.cursor/agents/*.md`, `.codex/agents/*.toml`, and the
    roster block in `AGENTS.md`. Idempotent; `--check` verifies parity (use in CI / pre-commit).
  - **Reverse** (`--import`): pulls an agent authored *inside* a tool (Cursor, Codex) back into
    `.claude/agents/imported/`, then forward-syncs it to every tool. Generated files carry an
    `AUTO-GENERATED` marker; the engine only overwrites/deletes marker-bearing files, so a
    hand-authored tool file is **never clobbered** — it is imported instead.
- **Hook:** a `PostToolUse` hook runs `sync-tool-configs.py --hook` whenever a file under
  `.claude/agents/` or `.claude/skills/` is written — so the tools regenerate the moment the
  source changes. (Forward only; import is deliberate, never automatic.)
- **Owner:** the **`config-steward`** agent. Route to it (or run the `/sync-tool-configs`
  skill) after adding/removing an agent, to import a tool-authored agent, when onboarding a new
  tool, or when `--check` fails.

### Someone built an agent in Cursor / Codex — how it comes home

1. They author, e.g., `.cursor/agents/deal-desk-analyst.md` directly in the tool.
2. `python scripts/sync-tool-configs.py --check` flags it as *importable*.
3. `python scripts/sync-tool-configs.py --import` writes
   `.claude/agents/imported/deal-desk-analyst.md` (the source of truth), removes the tool copy,
   and regenerates the agent for **every** tool.
4. `config-steward` reviews it — confirms `tools`/`model`, tightens read-only — and moves it
   into `office/` or `dev/`. Now it is a first-class OS role everywhere.

Portable parts (name, description, prompt) import cleanly. Tool-specific tool names get a
sensible default for review. Only **agents** auto-import; tool-specific rules/hooks/skills are
surfaced for a human decision, not pulled in automatically.

**Rules that keep this honest:**

- **Never hand-edit a generated file** (`.cursor/agents/*`, `.codex/agents/*`, the `AGENTS.md`
  roster block). Your edit is erased on the next run. Fix the source agent instead.
- **Adapters are pointers, not copies** (`.cursor/rules/`, `.devin/`, `.intent/`,
  `.antigravity/`). No brain content in them.
- **`AGENTS.md` prose is the only hand-written summary of the brain.** When `.claude/CLAUDE.md`
  changes materially, update `AGENTS.md` prose to match. The CLAUDE files always win on conflict.
- **Onboarding a new tool** = add a renderer to `sync-tool-configs.py` + a pointer adapter +
  a matrix row, then regenerate. The `config-steward` agent's definition documents the steps.

## For derived engagement repos

This multi-tool layer is generic and is inherited via upstream merge:

```
git fetch upstream
git merge upstream/main
```

After merging, a derived repo may lightly rename adapter titles (e.g. `.cursor/rules/`
description) to its engagement name, but should keep the adapters as pointers. Do not copy
brain content into them.
