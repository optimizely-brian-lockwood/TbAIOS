# File Organization — TbAI OS

## Governing principle

Every file has a type. Every type has exactly one home. When a new file is created — by a human or an agent — it goes in the right folder with the right name, no exceptions. This document is the authoritative reference.

---

## Directory tree

```
docs/
  records/
    program/              ← Living program records (updated continuously, no date in filename)
    pending/              ← Ingest captures awaiting consolidation into living records
    waves/
      wave1-diagnosis/    ← Wave 1: Current-state diagnosis artifacts
      wave2-design/       ← Wave 2: AI design, feasibility, governance, journey, value
      wave3-enablement/   ← Wave 3: Change management and enablement
    milestones/           ← Workshop and event packages (one folder per event)
      YYYY-MM-DD-[event]/ ← e.g. 2026-06-01-kickoff/
    inputs/               ← Raw source material — immutable provenance files
      YYYY-MM/            ← e.g. 2026-05/, 2026-06/
    data/                 ← Raw data exports (CSV, XLSX, JSON)
    reference/            ← Stable reference material (guides, rosters, infographics)
  distribution/
    YYYY-MM/              ← Polished shareable deliverables organized by month
  team/                   ← AI Office team operational docs (unchanged)
  dev-team/               ← Dev team operational docs (unchanged)

context/                  ← Initiative and human-team context files (unchanged)
scripts/                  ← All Python and shell scripts
initiatives/              ← Phase registry and initiative templates (unchanged)
.claude/                  ← Agent system prompts and skills (unchanged)
```

---

## Artifact types and routing rules

### 1. Program records → `docs/records/program/`

**What:** Documents that are the living, continuously-updated institutional record of the
engagement. No date in the filename because they are never "done" — they accumulate.

**Naming:** `[record-name].md`

**Standard program records:**
- `artifact-index.md` — master index of all artifacts and their status
- `decision-log.md` — all decisions (D-series), append-only
- `plan-of-record.md` — the current plan, updated when scope changes
- `progress-tracker.md` — agent and milestone completion tracking
- `risk-register.md` — all risks (R-series), updated as risks change state
- `stakeholder-map.md` — stakeholders, roles, influence, sentiment

**Rule:** If a document is consulted and updated in every session, it is a program record.

---

### 1b. Pending extractions → `docs/records/pending/`

**What:** Structured extractions from ingest captures, awaiting consolidation into the 6
living program records. Created automatically by Phase 1 of the two-phase ingest. Never
edited manually.

**Naming:** `YYYY-MM-DDTHHMMSS-[who]-[topic].md` (UTC timestamp, no colons, author first
name, kebab topic slug)

**Examples:**
- `2026-06-02T143022-alex-day2-morning-brief.md`
- `2026-06-02T160500-jordan-product-signals.md`

**Rule:** Created only by `/ingest`. Processed only by `/ingest consolidate`. Files with
`status: pending` are awaiting consolidation; files with `status: processed` have been
applied to living records and are retained for provenance. Do not write to living program
records directly during a normal ingest — use the pending file.

---

### 2. Wave artifacts → `docs/records/waves/wave[N]-[label]/`

**What:** Phase-based analysis and design artifacts produced by the specialist agentic team
during a specific wave. Essentially frozen after the wave closes — new information is ingested
as updates, not new files.

**Naming:** `[topic].md` — the wave folder provides the phase context, so no wave prefix in
the filename.

**Wave folders:**
- `wave1-diagnosis/` — current-state diagnosis (ops, workflow, data, product)
- `wave2-design/` — AI feasibility, governance, journey mapping, value baseline
- `wave3-enablement/` — change management and enablement plan

**Rule:** If it was produced by a specialist agent as a wave deliverable, it belongs here.
If a wave closes and new evidence requires updating a wave artifact, update the file in place
and increment the version header — do not create a new file in a different location.

---

### 3. Milestone packages → `docs/records/milestones/YYYY-MM-DD-[event]/`

**What:** All artifacts created for a specific workshop, offsite, or program milestone.
Grouping by event makes the complete package easy to find and share.

**Naming:** `[artifact-type].md` within the event folder. The date and event name are in the
parent folder, so filenames are short and descriptive.

**Example milestone folders:**
- `2026-05-18-wave1-complete/` — wave 1 engagement state snapshot
- `2026-06-01-kickoff/` — kickoff workshop package (agenda, pre-read, playbook, synthesis)

**Rule:** If an artifact was created specifically for a workshop, event, or milestone review —
not for ongoing use — it belongs in a milestone folder.

---

### 4. Inputs → `docs/records/inputs/YYYY-MM/`

**What:** Raw source material ingested into the knowledge system. Transcripts, Teams chats,
interviews, external research, briefings. These files are immutable provenance — they record
what was said or found, not what the team concluded. Never edit an input file; create a new
one if a correction is needed.

**Naming:** `YYYY-MM-DD-[source-type]-[description].md`

Source type labels:
- `transcript` — meeting or workshop recording transcript
- `teams` — Microsoft Teams chat export
- `interview` — practitioner interview notes
- `research` — external research or benchmarking
- `briefing` — one-pager or briefing document
- `analysis` — data analysis output

**Examples:**
- `2026-06-01-transcript-kickoff-day1.md`
- `2026-05-26-transcript-team-weekly-sync.md`
- `2026-06-01-research-ai-economics.md`

**Rule:** Every `/ingest` invocation that processes new source material creates one input
file. The input file is the raw provenance record. The wave artifacts and program records are
then updated separately to reflect the new evidence.

---

### 5. Data exports → `docs/records/data/`

**What:** Raw data files exported from systems (CRM, support platforms, BI tools, etc.).
CSV, XLSX, JSON, or other structured formats.

**Naming:** `YYYY-MM-DD-[system]-[description].[ext]`

**Examples:**
- `2026-06-01-supportdesk-phase1-segment.csv`
- `2026-06-01-sfdc-account-health.xlsx`

**Rule:** If it came out of a system export and has not been processed into a markdown
artifact, it goes in `data/`.

---

### 6. Reference → `docs/records/reference/`

**What:** Stable documents that don't change often and are consulted as background material
rather than updated as part of the engagement. Guides, rosters, infographics, OS documentation.

**Naming:** `[descriptive-name].[ext]` — no date needed.

---

### 7. Distribution deliverables → `docs/distribution/YYYY-MM/`

**What:** Polished, shareable outputs for specific audiences — PDFs, Word docs, PPTX,
packages. Organized by the month they were produced. These are snapshots generated from
the living records, not the records themselves.

**Naming:** `YYYY-MM-DD-[audience]-[description].[ext]`

Audience label examples:
- `leadership` — executive / sponsor audience
- `team` — internal transformation team
- `workshop` — workshop package
- `ic` — individual contributor (broader comms)

**Examples:**
- `2026-06-02-leadership-90day-plan.pdf`
- `2026-06-01-workshop-kickoff-package.zip`

**Rule:** Scripts that generate distribution files always write their output into
`distribution/YYYY-MM/`. No scripts live in the distribution folder.

---

### 8. Scripts → `scripts/`

**What:** Python and shell scripts that produce or process artifacts. Never deliver a script
as a standalone deliverable — it belongs in `scripts/`.

**Naming:** `[verb]-[description].[ext]`

**Examples:**
- `generate-pdf.py`
- `build-workshop-package.py`
- `md-to-docx.py`
- `setup-corporate-auth.sh`

---

## Decision tree — where does this file go?

```
Is it raw source material (transcript, Teams chat, interview, external research)?
  → records/inputs/YYYY-MM/

Is it a structured extraction from an ingest capture (status: pending or processed)?
  → records/pending/

Is it a living program record updated every session (decisions, risks, plan, etc.)?
  → records/program/

Is it a phase-based analysis artifact from a specialist wave?
  → records/waves/wave[N]-[label]/

Was it created for a specific workshop or milestone event?
  → records/milestones/YYYY-MM-DD-[event]/

Is it a raw data export (CSV, XLSX, JSON)?
  → records/data/

Is it a stable reference document (guide, roster, infographic)?
  → records/reference/

Is it a polished deliverable for sharing (PDF, Word, PPTX)?
  → distribution/YYYY-MM/

Is it a script that generates or processes files?
  → scripts/
```

---

## Naming quick reference

| Type | Pattern | Good example | Bad example |
|---|---|---|---|
| Program record | `[name].md` | `decision-log.md` | `2026-05-decision-log.md` |
| Wave artifact | `[topic].md` | `ops-diagnosis.md` | `wave1-ops-diagnosis-v2.md` |
| Milestone artifact | `[type].md` | `pre-read-pack.md` | `kickoff-pre-read-2026-06-01.md` |
| Input | `YYYY-MM-DD-[source]-[desc].md` | `2026-06-01-transcript-day1.md` | `input-day1.md` |
| Data export | `YYYY-MM-DD-[system]-[desc].[ext]` | `2026-06-01-supportdesk-phase1-segment.csv` | `supportdesk-export.csv` |
| Deliverable | `YYYY-MM-DD-[audience]-[desc].[ext]` | `2026-06-02-leadership-90day-plan.pdf` | `90day-plan-v2-FINAL.pdf` |
| Script | `[verb]-[desc].[ext]` | `generate-pdf.py` | `generate_pdf_v3_NEW.py` |

---

## Hard rules

1. **No files directly in `docs/records/`** — everything must be in a named subfolder.
2. **No scripts in `distribution/`** — scripts go in `scripts/`, outputs go in `distribution/`.
3. **No dated filenames for program records** — they are living documents; the git history is the audit trail.
4. **No wave prefix in wave artifact filenames** — the folder provides the phase context.
5. **Input files are immutable** — never edit an input file after it is created. Create a new one if a correction is needed.
6. **Distribution files are named for audience** — always include the audience segment in the filename.
7. **One milestone = one folder** — all artifacts for a workshop go in the same dated folder, not spread across the tree.

---

## What does NOT change

- `docs/team/` — AI Office team operational docs (charter, workflow, boundaries, journey, context, handoff)
- `docs/dev-team/` — Dev team operational docs (charter, workflow, boundaries)
- `context/` — Initiative and human-team context files
- `initiatives/` — Phase registry and initiative templates
- `.claude/` — Agent system prompts and skills

These directories have their own internal logic and are not covered by this spec.

---

*This document is owned by the Program Manager. Updates require approval from the Transformation Lead.*
