# Intent spec anchor — TbAI OS

Intent is spec-driven: agents coordinate around a single living spec. **In this repo, the
spec is not a product spec — it is the operating system itself.** The canonical spec files,
in priority order, are:

1. `AGENTS.md` (repo root) — portable brain: identity, startup, roster, routing, hard rules,
   frameworks, response contract.
2. `CLAUDE.md` (repo root) — engagement identity (initiatives, team, constraints).
3. `.claude/CLAUDE.md` — generic OS brain. **Source of truth for how the OS works.**
4. `initiative/CLAUDE.md` — the active initiative's scope and constraints, if present.

Point Intent's living spec at these files. Any agent coordinating in Intent must treat them
as the shared plan.

## Roles and skills as spec fragments

- Team roles: `.claude/agents/**/*.md` — each is a self-contained role spec. Assign one role
  per agent; do not blend.
- Skills (repeatable procedures): `.claude/skills/*/SKILL.md` — follow the steps as written.

## Invariants Intent agents must preserve

- **Initiative separation is absolute** — never merge records across initiatives; ambiguous
  initiative → stop and ask.
- **Records are append-only** — never delete; mark superseded.
- **Corp-data is read-only and explicit-invocation only.**
- File-placement hooks are not enforced here — honor `docs/FILE-ORGANIZATION.md` in the spec.
