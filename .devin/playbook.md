# Devin playbook — TbAI OS

Devin reads `AGENTS.md` at the repo root natively. **That file is your primary instruction
set.** This playbook adds Devin-specific guidance only.

## Before starting any task

1. `git pull origin main` and report the result. Stop on merge conflict.
2. Read, in order: `AGENTS.md` → `CLAUDE.md` (engagement identity) → `.claude/CLAUDE.md`
   (generic brain) → `initiative/CLAUDE.md` (if present).
3. Identify which **initiative** the work belongs to. If ambiguous, ask before proceeding —
   initiative separation is absolute; never blend records across initiatives.

## Working as the team

- The OS is two specialist teams defined in `.claude/agents/`. When Devin spawns sub-agents
  for parallel subtasks, **give each sub-agent one role's system prompt** (from the matching
  `.md` file) and keep it inside that role's boundaries.
- The only path from the AI Office team to the dev team is the `engineering-liaison` role.

## Hard rules (see AGENTS.md → "Hard rules" for the full list)

- Never delete content from records — append or mark superseded.
- Always file raw source input under `docs/records/inputs/YYYY-MM/`.
- Corp-data (Teams / Outlook / SharePoint / Salesforce) is read-only and
  explicit-invocation only.
- File-placement hooks are not enforced outside Claude Code — follow
  `docs/FILE-ORGANIZATION.md` manually.

## Output shape

Follow the response contract in `AGENTS.md`: headline → decisions needed → evidence bullets →
preview before writing to `docs/records/`.
