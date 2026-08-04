# Dev Team — Workflow

## Standard feature flow

```
Engineering Brief (via Engineering Liaison)
    ↓
Engineering Manager (intake + classify)
    ↓
Product Manager (spec + acceptance criteria)
    ↓
Software Architect (design review — if cross-component or new tech)
    ↓
UX Designer (flows + specs — if user-facing surface)
    ↓
Tech Lead (task breakdown + assignment)
    ↓
Developer / Senior Developer (implementation)
    ↓
QA Engineer (test plan + execution)
    ↓
Code Reviewer (PR review)
    ↓
Security Engineer (if required — see charter)
    ↓
DevOps Engineer (deploy to preview)
    ↓
Engineering Manager (confirm against the brief, hand back to Engineering Liaison)
```

Every stage after intake is unchanged whether the work originated from an Engineering
Brief (the normal path — see `docs/team/dev-team-handoff.md`) or from direct, in-repo work
on this OS's own scripts/skills/harness. What differs is only who the Engineering Manager
reports completion to: the Engineering Liaison for commissioned builds, or the person who
asked for OS-internal work.

## Compression for low-risk work

EM may compress the flow for small, low-risk changes (copy edits, minor styling, config
tweaks):
- Skip: UX Designer, Software Architect, Security Engineer
- Compress: Tech Lead + Developer may be the same invocation
- Required always: PM sign-off (even minimal), QA (even a quick smoke test), Code Review,
  EM close

Record what was compressed and why in the conversation.

## Tracking: FEATURES.md, ACTIVE-WORK.md, TEST-ISSUES.md, CHANGELOG.md

Four files at repo root carry the team's shared state across sessions.

- **Claim a ticket** in `FEATURES.md` and `ACTIVE-WORK.md` *before* writing any code.
- **Update tracking in the same commit as the merge** — this is a `team-charter.md` hard
  rule, not optional. A feature that's "done" but not reflected in these files isn't done.
- Multiple agents (or people) may work different tickets simultaneously — `ACTIVE-WORK.md`
  is what prevents two people claiming the same ticket without knowing it.

These four files are **instance data**, not part of the generic OS brain — they are never
overwritten by an `upstream/main` merge (see root `README.md`, "Receiving upstream
updates"). A derived engagement repo keeps its own backlog, claim board, test log, and
changelog independent of TbAIOS's.

## Branching

Adapt to your project's actual branching model, but the pattern this team assumes is:
- Feature work: branch from your trunk branch, merge back via PR
- Hotfix: same pattern, fast-tracked
- Promotion to production (if you have a separate production branch/environment): treat as
  a human decision, not something an agent does unprompted

## How to invoke the team

For a build commissioned by the AI Office team, work arrives via the **Engineering
Liaison** as an Engineering Brief (see `docs/team/dev-team-handoff.md`) and lands with the
**Engineering Manager** — no dev-team role takes direction from any AI Office agent except
through the Engineering Manager.

For work directly on this OS's own code (scripts, skills, harness), start the same way —
address the Engineering Manager directly:

```
Use the engineering-manager agent to [request]
```

EM will classify, route, and coordinate from there. Don't invoke specialist agents directly
for anything beyond a narrow, already-scoped question — the EM briefs them with the right
context, and skipping that step is how roles end up working from incomplete information.

## Adopting this workflow on a codebase that already exists

If you're bringing this team onto a codebase that was already built — especially one built
quickly without much formal process, such as a newly onboarded derived engagement repo —
don't start new feature work at the implementation stage. Run a one-time baseline pass
first:

1. **Baseline architecture pass (Software Architect).** A current-state design doc
   describing what actually exists today — not the idealized version. This becomes your
   first ADR and the reference point every future design doc diffs against.
2. **Baseline security pass (Security Engineer).** A first threat model and vulnerability
   pass against the app as it stands. Triage into a backlog; escalate anything severe
   (exposed secrets, missing auth checks, injectable input) immediately rather than letting
   it sit.
3. **Baseline test pass (QA Engineer).** An honest assessment of current test coverage.
   Flag critical paths with zero coverage — those are your highest regression risk the
   moment anyone starts changing code nearby.

Log the findings from all three into `FEATURES.md` (as backlog items) and `TEST-ISSUES.md`
(for known gaps), so they enter the normal tracking system instead of living only in a
one-time conversation. Once the baselines exist, every new piece of work enters the flow
above at the Product Manager stage, like normal.
