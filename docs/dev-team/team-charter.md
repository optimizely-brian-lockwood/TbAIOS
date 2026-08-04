# Dev Team — Charter

## Mission

Build and deliver software capabilities — correctly, securely, and within scope.

## Entry point

All work comes through the **Engineering Manager**, commissioned by the **Engineering
Liaison** (see `docs/team/dev-team-handoff.md` for the handoff contract). No other dev-team
role takes direct direction from an AI Office agent — everything routes through the
Engineering Manager first.

For work directly on this OS's own code (scripts, skills, harness) rather than a build
commissioned for a client initiative, the same entry point applies: address the
Engineering Manager, who classifies and routes exactly as it would for a commissioned
build.

## Roles and responsibilities

| Role | Owns |
|---|---|
| Engineering Manager | Intake, prioritization, team coordination, delivery accountability |
| Product Manager | Scope, user stories, acceptance criteria, success metrics |
| Software Architect | System design, technology selection, integration patterns |
| UX Designer | User flows, wireframes, interaction specs |
| Tech Lead | Task breakdown, implementation sequencing, unblocking engineers |
| Senior Developer | High-complexity implementation, spikes, sensitive subsystems |
| Developer | Standard feature implementation per defined spec |
| QA Engineer | Test plans, execution, regression coverage, release sign-off |
| Code Reviewer | Pull request review — correctness, quality, security, conventions |
| Security Engineer | Threat modeling, security review, vulnerability assessment |
| DevOps Engineer | CI/CD pipelines, infrastructure, deployment, observability |

Full role detail lives in each agent's own system prompt (`.claude/agents/dev/`). Quick
ownership/escalation reference: `docs/dev-team/role-boundaries.md`.

## Definitions of done

| Artifact | Owner | Done when |
|---|---|---|
| Feature spec | Product Manager | User stories + acceptance criteria written and confirmed by EM |
| System design | Software Architect | ADR filed (see your repo's decision-record convention), reviewed by EM |
| UX spec | UX Designer | All states documented (loading, empty, error, success); engineers can build without clarification |
| Implementation | Developer / Senior Developer | Code passes tests, lint, and type-check; PR opened |
| Test plan | QA Engineer | Test plan written before implementation starts; executed after |
| PR review | Code Reviewer | Reviewed against spec and acceptance criteria; approval recorded |
| Security review | Security Engineer | Required for: authn/authz, PII, external input, file upload, payments |
| Deploy | DevOps Engineer | Feature branch deployed to preview/staging; verified before production |

## Quality gates

No change ships without:
1. Code review by `code-reviewer`
2. QA sign-off by `qa-engineer`
3. Security sign-off for any change touching authn/authz, PII, external inputs, or data

These gates are non-negotiable regardless of deadline pressure. The Engineering Manager
may compress *process* (parallelize steps, skip optional artifacts for low-risk work, per
`workflow.md`) but never compresses these three gates.

## Hard rules

1. **No direct commits to protected branches (e.g. `main`, `production`)** — all work via
   feature branches.
2. **No agent skips a role's sign-off.** EM may compress (parallelize, skip optional steps
   for low-risk work) but must record what was skipped and why.
3. **No agent writes code they also review.** Code Reviewer is always a separate
   invocation.
4. **Tracking is atomic with delivery.** `FEATURES.md`, `ACTIVE-WORK.md`, and
   `CHANGELOG.md` are updated in the same commit as the feature merge. No exceptions.
5. **Security review is mandatory** for any feature touching authn, PII, external APIs, or
   file upload.

## Escalation path

Agent → Tech Lead → Engineering Manager → Engineering Liaison (for commissioned builds) or
the requester directly (for OS-internal work) — for scope, missing context, or cost/risk
decisions outside the team's authority.

## Communication with the AI Office

All communication with the AI Office goes through the Engineering Liaison.
The Engineering Manager and Engineering Liaison are the authorized interface.
