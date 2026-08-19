# TbAI Operating System

A reusable, upstream-synced base for AI-augmented transformation engagements built on
Claude Code.

## What it is

TbAI OS is the **generic layer** of an AI Operating System for transformation work. It
provides:

- A 15-role **AI Office** agentic team (strategy, diagnosis, design, measurement)
- An 11-role **Dev team** for build commissioning
- A continuous-integration **knowledge pipeline** (`/ingest`)
- A **corporate data conduit** (`/corp-data`)
- A **daily digest** skill (`/morning-briefing`)
- A **plan stress-tester** (`/challenge-me`)
- The **three-lens framework** and **dual-metric discipline**
- A **file organization spec** and record structure

## Works with (not just Claude Code)

TbAI OS is portable across agentic coding tools. The brain lives once in the CLAUDE files /
`.claude/`; each tool reads it through a thin adapter — no duplicated rules, no drift.

| Tool | Entry file |
|---|---|
| **Claude Code** | `CLAUDE.md` + `.claude/` (native — subagents, skills, hooks) |
| **OpenAI Codex** | `AGENTS.md` (native) |
| **Cursor 3** | `.cursor/rules/tbai-os.mdc` → `AGENTS.md` |
| **Devin** | `.devin/playbook.md` → `AGENTS.md` |
| **Intent** | `.intent/os.md` → `AGENTS.md` |
| **Google Antigravity** | `.antigravity/config.md` → `AGENTS.md` |

`AGENTS.md` is the portable brain read by the open-standard tools. Full guide and the
what-ports/what-doesn't matrix: [`docs/multi-tool-support.md`](docs/multi-tool-support.md).
Derived repos inherit this layer via `git merge upstream/main`.

## Architecture

TbAI OS uses a two-layer CLAUDE.md design:

| File | Owned by | Contains |
|---|---|---|
| `.claude/CLAUDE.md` | **TbAI OS** (this repo) | Generic OS brain: agent structure, routing, frameworks, hard rules |
| `CLAUDE.md` (root) | **Client repo** | Engagement identity: initiative definitions, human team, sensitivity constraints |

Claude Code reads both files every session. The client layer extends the generic layer.
Upstream syncs only touch `.claude/` — client records are never affected.

## Creating a derived OS

> **Important:** Clone TbAIOS first — don't create an empty repo and add upstream later.
> Cloning gives the new repo a shared git history, so future `git merge upstream/main`
> calls work without conflicts.

### Step 1 — Clone TbAIOS as your starting point

```bash
git clone https://github.com/optimizely-brian-lockwood/TbAIOS.git my-engagement-os
cd my-engagement-os
```

### Step 2 — Rewire the remotes

```bash
git remote rename origin upstream
git remote add origin <your-new-github-repo-url>
```

Create the new repo on GitHub first (**completely empty** — no README, no .gitignore),
then paste its URL above.

### Step 3 — Push to your new repo

```bash
git push -u origin main
```

### Step 4 — Fill in the client layer

Edit the root `CLAUDE.md`. It has placeholder sections for:
- **Initiative registry** — ID, target, scope, phase, records path
- **Human team** — names, roles, responsibilities
- **Tool stack** — ClickUp space ID, folder map, any dual-system rules
- **Sensitivity constraints** — redacted items, IC-confidential content, hard rules

Do **not** edit `.claude/CLAUDE.md` — that file is owned by TbAIOS and syncs from upstream.

### Step 5 — Configure your corporate email

```bash
cp .env.example .env
# edit .env and set CORPORATE_EMAIL=you@yourcompany.com
```

`.env` is gitignored. Every team member sets their own — it is never committed.

### Step 6 — Authenticate corporate data access (if needed)

```bash
bash scripts/setup-corporate-auth.sh
```

Required before using `/corp-data` or `/morning-briefing`. One-time per machine.

### Step 7 — Override agents as needed

Any agent in `.claude/agents/office/` that needs engagement-specific content: edit it in
your derived repo. Each agent has a `## Client-specific context` section at the bottom
as the designated place for engagement notes. These overrides are never touched by
upstream syncs.

### Step 8 — Create your records structure

```bash
mkdir -p docs/records/{program,pending,waves,milestones,inputs,data,reference}
mkdir -p docs/distribution context initiatives
```

The four dev-team tracking files (`FEATURES.md`, `ACTIVE-WORK.md`, `TEST-ISSUES.md`,
`CHANGELOG.md`) come along with the clone from Step 1, already blank — they're instance
data from the moment the dev team starts being used, so there's nothing further to
initialize here.

---

## Receiving upstream updates

```bash
git fetch upstream
git merge upstream/main
```

What gets updated: `.claude/CLAUDE.md`, agents, skills, `docs/team/` templates,
`docs/dev-team/` templates, `docs/FILE-ORGANIZATION.md`.

What is never touched: `docs/records/`, `docs/distribution/`, `context/`, `initiatives/`,
root `CLAUDE.md`, `.env`, and the four dev-team tracking files (`FEATURES.md`,
`ACTIVE-WORK.md`, `TEST-ISSUES.md`, `CHANGELOG.md`) — these are instance data (this repo's
own backlog, claim board, test log, and shipped-work record), not part of the generic OS
brain, so an upstream merge never overwrites them.

## Repo structure

```
TbAIOS/
  .claude/
    CLAUDE.md              # Generic OS brain — DO NOT EDIT IN DERIVED REPOS
    agents/
      office/              # 15 AI Office agent system prompts
      dev/                 # 11 dev team agent system prompts
      corp-data-agent.md   # Corporate data conduit agent
    skills/
      ingest/SKILL.md      # Knowledge pipeline skill
      corp-data/skill.md   # Corporate data access skill
      morning-briefing/SKILL.md  # Daily Teams digest skill
      challenge-me/SKILL.md      # Plan stress-test skill
  docs/
    FILE-ORGANIZATION.md   # Authoritative file placement rules
    team/                  # AI Office team operational doc templates
    dev-team/              # Dev team operational doc templates
  context/                 # Template context files (initiative.md, human-team.md)
  initiatives/
    _template/             # Cookie-cutter for new initiative directories
  scripts/                 # Utility scripts
  FEATURES.md              # Dev-team ticket backlog (instance data, never synced)
  ACTIVE-WORK.md           # Dev-team parallel-work claim board (instance data)
  TEST-ISSUES.md           # Dev-team test-failure log (instance data)
  CHANGELOG.md             # Dev-team shipped-work record, Keep-a-Changelog format (instance data)
  CLAUDE.md                # CLIENT TEMPLATE — fill this in for each engagement
  README.md                # This file
```

## Versioning

TbAI OS uses git tags for versions. To pin a derived repo to a specific OS version:

```bash
git fetch upstream --tags
git merge v1.2.0          # pin to a specific release
```
