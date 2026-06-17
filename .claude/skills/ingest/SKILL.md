---
name: ingest
description: Ingest new source information into any initiative's operating system — meeting notes, Teams chats, decisions, stakeholder inputs, documents — then audit and update all affected plans, records, and artifacts. Triggers on "ingest this", "update the plans with this", "feed this in", "here's new info", or when the user provides source material. Also triggers on "audit the docs", "refresh the plans", "are the records up to date".
---

## Response contract

This skill must honor the **Response contract** in `.claude/CLAUDE.md` for all
interstitial chat output (status, prompts, summaries). Headline + `Decisions needed:`
block + bullets. The structured artifact blocks below (Ingest Summary, pending file,
Capture Complete) keep their own formats — they are the artifact, not the chat.

## What this skill does

This is the continuous integration pipeline for the AI OS knowledge system. It operates in
two phases to support concurrent use by multiple team members without git conflicts:

- **Phase 1 — Capture** (`/ingest`): Files the raw source and creates a pending extraction
  file. Zero writes to shared living records. Everyone can do this simultaneously.
- **Phase 2 — Consolidate** (`/ingest consolidate`): Applies all pending extractions to the
  6 living program records in sequence. Run by one person at a time.

## Invocation modes

| Input | Behavior |
|-------|----------|
| `/ingest` or "here are the notes..." | Phase 1: classify, extract, file raw input, create pending file |
| `/ingest teams <chat-name>` | Phase 1: harvest Teams chat first, then capture |
| `/ingest consolidate` | Phase 2: apply all pending files to living records |
| `/ingest audit` | No new input — audit records for staleness and consistency |
| `/ingest status` | Show pending file count, input file inventory, next D/R numbers |

---

## Phase 1 — Capture

### Step 0: Classify the initiative — MANDATORY FIRST STEP

Before anything else, determine which initiative this input belongs to. The initiative
registry is defined in the client `CLAUDE.md`. Read it before proceeding.

**If clearly one initiative:** proceed, route records to that initiative's record path.
**If ambiguous or touching multiple initiatives:** STOP. Ask the user which initiative this
belongs to. Do not proceed until confirmed.

Initiatives must never be merged. Every ingest, artifact, decision, and routing action
belongs to exactly one initiative.

---

### Step 1: Classify the input

| Input type | Examples | Classification |
|-----------|----------|----------------|
| **Meeting notes** | Notes from a call, weekly sync, transcript | `meeting` |
| **Teams chat** | Chat thread export, request to harvest a chat | `teams-chat` |
| **Decision** | "We decided X", "Sponsor approved Y" | `decision` |
| **Stakeholder update** | "Lead finished their journey map" | `stakeholder-update` |
| **Document/artifact** | PDF, spreadsheet content, email, report | `document` |
| **Status update** | "M1 is done", "Legal cleared item L-3" | `status-update` |
| **Audit request** | "Are the plans up to date?", "audit the docs" | `audit-only` |

If the input is ambiguous, ask ONE clarifying question. If it clearly maps, proceed.

### Step 2: If Teams harvest needed, confirm before fetching via corp-data

If classification is `teams-chat` and the user specified a chat name:

1. **Stop and ask** — corp-data is explicit-only. Surface:
   `Decisions needed: [A] harvest <chat-name> via corp-data  [B] skip — paste content manually  [C] cancel`
2. Only on `[A]` (or if the user's original invocation said "harvest Teams chat X"
   explicitly), use the corp-data skill pattern to harvest the chat
3. Search for messages and any shared files
4. Return all content before proceeding to Step 3

### Step 3: Extract structured information from the input

Parse the input and extract:

- **New decisions** — any statement of the form "we decided", "agreed to", "approved", "confirmed"
- **New risks** — any concern, blocker, dependency, or uncertainty raised
- **Stakeholder updates** — new people mentioned, role changes, status of people's work
- **Action item updates** — completions, new assignments, deadline changes
- **Evidence that affects scored candidates or deliverables** — anything that changes priorities
- **Timeline changes** — dates moved, new deadlines, milestone completions
- **Sensitivity flags** — any content marked confidential, IC-sensitive, or embargoed

Present the extracted information to the user for confirmation:

```
## Ingest Summary

**Source:** {description}
**Classification:** {type}
**Initiative:** {initiative ID and name}

**Extracted:**
- X new decisions
- Y risk updates
- Z stakeholder changes
- W action item updates

Shall I proceed with capture?
```

Wait for confirmation unless the user pre-authorized.

### Step 4: File the raw input

Create an input file at `docs/records/inputs/YYYY-MM/YYYY-MM-DD-[source]-[description].md` with:

```markdown
# Input: {Title}

**Source:** {where it came from}
**Ingested:** {today's date}
**Initiative:** {initiative ID and name}
**Classification:** {from Step 1}
**Extracted:** {count of decisions, risks, stakeholder updates, action items}

---

{Full raw content, preserving structure and attribution}

---

## Key Extracted Information

{Structured extraction — what was found, what it means for the initiative}
```

### Step 4b: Create a pending file

Create a pending file at `docs/records/pending/YYYY-MM-DDTHHMMSS-[who]-[topic].md` using
UTC timestamp (no colons), author first name, and kebab topic slug.

**Do not assign D-numbers or R-numbers here.** Numbers are assigned at consolidation time.

```markdown
---
status: pending
captured_by: [first name]
captured_at: [ISO 8601 UTC — e.g. 2026-06-02T14:30:22Z]
source_input: docs/records/inputs/YYYY-MM/[input-filename].md
topic_slug: [kebab-case-topic]
initiative: [initiative ID]
sensitivity: [none | confidential | ic-sensitive]
---

## Decisions

[One paragraph per decision — what was decided, by whom, why, downstream impact.
No D-number. Consolidation assigns it.]

## Risks

[One paragraph per risk — description, severity, owner, target resolution.
No R-number. Consolidation assigns it.]

## Stakeholder changes

[New people or updates to existing stakeholders. Include role, context, sensitivity if any.]

## M-series / progress updates

[Status changes: "M-19 → Done", "M-21 → In Progress", new M-series items needed.]

## Artifact index entry

[The table row to add to artifact-index.md, verbatim — date, description, owner, path, status.]

## Plan-of-record updates

[Any scope, phase, version, or anchor-decision changes needed.]

## Notes for consolidator

[Cross-references, sensitivity callouts, judgment calls that need a human eye before applying.]
```

Omit any section that has nothing to add.

### Step 5: Report capture complete

```
## Capture Complete

**Source filed:** docs/records/inputs/YYYY-MM/[input-filename].md
**Pending file:** docs/records/pending/[pending-filename].md
**Extracted:** [N decisions] | [N risks] | [N stakeholder changes] | [N M-series updates]

Pending files awaiting consolidation: [total count in docs/records/pending/ with status: pending]

Run `/ingest consolidate` when ready to apply to living records.
```

Commit both files (input + pending) together and push.

---

## Phase 2 — Consolidate

Run `/ingest consolidate` to apply all pending files to the 6 living program records.
**Run one person at a time. Announce in Teams before starting ("consolidating now — 2 mins").**

### Step C1: Scan for pending files

Read all files in `docs/records/pending/` with `status: pending` in their frontmatter.
If none, report "Nothing to consolidate." and stop.

### Step C2: Sort chronologically

Sort pending files by `captured_at` timestamp, oldest first. This is the order for
number assignment — preserves causality.

### Step C3: Read current high-water marks

Before assigning any numbers:
- Scan `docs/records/program/decision-log.md` for the highest `D-NNN` → that is the
  current D-number ceiling
- Scan `docs/records/program/risk-register.md` for the highest `R-NNN` → that is the
  current R-number ceiling

Increment from these marks during processing. Never hardcode a starting number.

### Step C4: Process each pending file in chronological order

For each pending file:

1. **decision-log.md** — assign next sequential D-number(s), format entries to match
   existing conventions, append
2. **risk-register.md** — assign next sequential R-number(s), append new risks or update
   existing entries that are resolved/modified
3. **stakeholder-map.md** — add new stakeholders or update existing entries
4. **progress-tracker.md** — update M-series rows, add new M-series items
5. **plan-of-record.md** — apply scope/phase/version changes, update "Last updated" date
6. **artifact-index.md** — append the artifact index entry row

Respect sensitivity flags — if a pending file is marked `ic-sensitive` or `confidential`,
apply the same flag rules as if the content had been ingested directly.

### Step C5: Mark pending files as processed

Update each processed pending file's frontmatter:
```yaml
status: processed
consolidated_at: [ISO 8601 UTC timestamp]
consolidated_by: [first name]
```

Do not delete processed pending files — they are the audit trail.

### Step C6: Single commit

```
consolidate: apply [N] pending ingest(s) — D-[from]–D-[to] R-[from]–R-[to]
```

### Step C7: Report consolidation complete

```
## Consolidation Complete

**Pending files processed:** [N]
**Decisions assigned:** D-[range]
**Risks assigned:** R-[range]
**Stakeholder changes:** [N]
**M-series updates:** [N]

### Flags for human review:
[Any "Notes for consolidator" items that need a human decision]
```

---

## Audit-only mode (`/ingest audit`)

1. Read every file in `docs/records/program/`
2. Check for internal consistency:
   - Decisions referenced in one file but not in decision-log.md
   - Risks mentioned but not in risk-register.md
   - People mentioned but not in stakeholder-map.md
   - Action items with past-due dates not marked done or updated
3. Check for cross-file consistency:
   - Decision counts match across files
   - Risk counts match across files
   - Stakeholder lists match between files
4. Report findings as a gap list with specific file:line references

## Status mode (`/ingest status`)

1. List all files in `docs/records/program/` with their "Last updated" dates
2. List pending files with `status: pending` and their `captured_at` timestamps
3. Count: decisions, risks, stakeholders, input files, pending files
4. Show the next expected D-number, R-number, and input file sequence

---

## Critical rules

1. **Never delete content from existing records.** Append, update status, or mark as superseded.
2. **Preserve file format conventions.** Each file has its own structure. Match it exactly.
3. **Always file raw input.** Every capture creates an `inputs/YYYY-MM/` file for provenance.
4. **Convert relative dates to absolute.** "Next Thursday" becomes the actual ISO date.
5. **Confirm before capturing** unless the user pre-authorized.
6. **Don't change wave/phase artifacts** unless new evidence directly contradicts a stated finding.
7. **Don't change scored items** without flagging for human review.
8. **Always update "Last updated" dates** on every living record touched during consolidation.
9. **Update the artifact index** for every new input file created.
10. **If Teams data is needed,** use the corp-data skill pattern. Always Sonnet model.
11. **Respect sensitivity flags.** If content is marked confidential, carry that flag through.
12. **In normal capture mode, never write to the 6 living records directly.** All updates to
    living records flow through `/ingest consolidate` only.
