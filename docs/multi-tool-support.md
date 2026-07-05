# Multi-tool support — use this OS from any agentic tool

The TbAI OS was built on Claude Code, but any team member can work inside the same operating
system from **OpenAI Codex, Cursor 3, Devin, Intent, or Google Antigravity**. This guide
explains how, and — honestly — what you gain and lose versus Claude Code.

## The design in one sentence

**One brain, many doors.** The operating system's identity, team, routing, frameworks, and
hard rules live once (`.claude/CLAUDE.md`, the root `CLAUDE.md`, and the roles/skills under
`.claude/`). Every other tool reads a portable summary — `AGENTS.md` — through a small
adapter file. No tool gets its own copy of the rules, so nothing drifts out of sync.

```
.claude/CLAUDE.md (generic) + CLAUDE.md (engagement)   ← source of truth
        │
        ▼
    AGENTS.md                        ← portable brain (open standard)
    ├── .cursor/rules/tbai-os.mdc           → Cursor 3
    ├── .devin/playbook.md                  → Devin
    ├── .intent/os.md                       → Intent
    ├── .antigravity/config.md              → Antigravity
    └── (Codex reads AGENTS.md directly)
```

## Per-tool setup

| Tool | What it reads | You need to |
|---|---|---|
| **Claude Code** | `CLAUDE.md`, `.claude/` | Nothing — native. |
| **OpenAI Codex** | `AGENTS.md` (root, native) | Open the repo; Codex loads `AGENTS.md` automatically. |
| **Cursor 3** | `.cursor/rules/tbai-os.mdc` (`alwaysApply`) | Open the repo; the rule is always on and points to `AGENTS.md`. |
| **Devin** | `AGENTS.md` + `.devin/playbook.md` | Point Devin at the repo; add `.devin/playbook.md` as a knowledge/playbook source if prompted. |
| **Intent** | `.intent/os.md` → the CLAUDE/AGENTS files | Set Intent's living spec to the files listed in `.intent/os.md`. |
| **Antigravity** | `AGENTS.md` + `.antigravity/config.md` | Open the repo; if hosting roles as custom agents, source prompts from `.claude/agents/**`. |

## What ports, and what does not

| Capability | Claude Code | Codex / Cursor / Devin / Intent / Antigravity |
|---|---|---|
| Identity, routing, frameworks, hard rules | ✅ native | ✅ via `AGENTS.md` |
| Team role definitions (`.claude/agents/`) | ✅ executable subagents | ✅ readable role prompts — adopt one at a time |
| Skills (`.claude/skills/`) | ✅ `/skill` invocation | ✅ readable procedures — run the steps manually |
| Parallel multi-agent orchestration | ✅ native (subagents + Workflow) | ⚠️ use the tool's own multi-agent feature (Cursor Agents Window, Devin sub-agents, Antigravity subagents); it is not automatic |
| Hooks (file-placement validation) | ✅ enforced on write | ❌ not enforced — follow `docs/FILE-ORGANIZATION.md` by hand |
| MCP connectors (corporate data, task systems) | ✅ per session | ⚠️ only if the tool supports MCP and you connect them |
| Slash-command skill invocation (`/ingest`) | ✅ | ❌ open `SKILL.md` and follow it manually |

**The honest bottom line:** on any tool you inherit the *full knowledge system* — the same
records, team structure, routing, and rules. What you give up outside Claude Code is
*automation*: automatic subagent orchestration and hook-enforced guardrails. On other tools
you run those steps yourself and stay disciplined about the hard rules.

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

## Keeping the adapters honest

The adapters are deliberately **pointers, not copies** — they contain no duplicated rules, so
there is nothing to keep in sync when the brain changes. If you ever add real content to an
adapter, move it into `AGENTS.md` (or the CLAUDE files) instead and leave a pointer. The only
file that summarizes the brain is `AGENTS.md`; when `.claude/CLAUDE.md` changes materially,
update `AGENTS.md` to match. The CLAUDE files always win on conflict.

## For derived engagement repos

This multi-tool layer is generic and is inherited via upstream merge:

```
git fetch upstream
git merge upstream/main
```

After merging, a derived repo may lightly rename adapter titles (e.g. `.cursor/rules/`
description) to its engagement name, but should keep the adapters as pointers. Do not copy
brain content into them.
