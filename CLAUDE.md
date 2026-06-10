# [ENGAGEMENT NAME] — AI Operating System

<!--
  INSTRUCTIONS FOR DERIVED REPOS
  ================================
  This file is the CLIENT LAYER of the TbAI Operating System.
  It extends `.claude/CLAUDE.md` (the generic OS brain synced from the TbAIOS upstream).

  Replace every [PLACEHOLDER] below with your engagement-specific values.
  Do NOT copy the generic OS brain content here — it lives in .claude/CLAUDE.md.

  To receive future TbAI OS updates:
    git remote add upstream https://github.com/optimizely-brian-lockwood/TbAIOS.git
    git fetch upstream
    git merge upstream/main
  Merges only affect .claude/ and docs/cs-team/, docs/dev-team/ — never your records.
-->

## Session startup — do this first, every time

**Before any other action, run:**

```bash
git pull origin main
```

Report the result in one line, then continue. If there is a merge conflict, stop and surface
it — do not proceed until resolved.

---

## What this OS serves

[One paragraph: what engagement this OS runs, what transformation is being delivered,
what the target outcome is.]

---

## The initiatives

<!-- Define one row per initiative. Multiple initiatives must never be merged or blended.
     When ingesting, routing, or producing any artifact, the initiative must be identified
     first. When unclear, ask before proceeding. -->

### [INITIATIVE-001] — [Initiative Name]

| Field | Value |
|---|---|
| **Initiative** | [Full name] |
| **Alias** | [I-001] |
| **Target** | [What success looks like — e.g., 30% efficiency gain in 18 months] |
| **Scope** | [Which teams/tiers/functions are in scope] |
| **Default posture** | [Capacity redeployment / headcount reduction / other] |
| **Current phase** | [e.g., Pre-kickoff / Wave 1 / Post-workshop execution] |
| **Records** | `docs/records/` |

<!-- Add more initiative blocks as needed. -->

---

## The human team

| Person | Role | Focus |
|---|---|---|
| [Name] | [Title / Role in engagement] | [What they own or decide] |
| [Name] | [Title / Role in engagement] | [What they own or decide] |

---

## Routing work

The generic routing table is in `.claude/CLAUDE.md`. Client-specific additions:

| Signal | Route to |
|---|---|
| [Any client-specific routing rule] | [Destination] |

---

## Skills

Standard skills (defined in `.claude/CLAUDE.md`): `/ingest`, `/corp-data`, `/morning-briefing`, `/challenge-me`.

Client-specific skills (if any):
- [Skill name] — [what it does]

---

## Corporate data access

<!-- Configure the dual-account architecture for corporate data access. -->

- **This session** runs on [personal account / Vertex AI].
- **Corporate data** goes through a CLI subprocess using
  `CLAUDE_CONFIG_DIR=~/.claude-corporate` with [corporate email] credentials.
- **Always Sonnet model** for corporate subprocess. Never Opus.
- See `.claude/skills/corp-data/skill.md` for the full execution pattern.

---

## Tool stack

| System | Role | What lives here |
|---|---|---|
| **AI OS** (this repo) | Knowledge system | Decisions, evidence, risks, artifacts, context, analysis |
| **[Task system]** | Action system | Who does what, by when, what's blocked |

**[Task system] space:** [Space name / ID]

---

## Sensitivity constraints

<!-- List any topics, names, or content that must NOT appear in any artifact.
     These are intentional redactions. If new information surfaces through
     legitimate channels, ingest it as new — never restore redacted content. -->

- [Redacted topic 1]
- [Redacted topic 2]

---

## Hard rules (client additions)

<!-- Add any client-specific hard rules that extend the base rules in .claude/CLAUDE.md. -->

- [Client-specific rule]
- **Never merge [I-001] and [I-002] records.** These are separate initiatives.
