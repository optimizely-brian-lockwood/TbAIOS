---
name: os-briefing
description: "Generate a personalized repo-state briefing from git history. Shows decisions made, risks updated, items ingested, plan changes, and what's relevant for you specifically — without touching Teams or corporate data. Triggers on \"/os-briefing\", \"os briefing\", \"repo briefing\", \"what changed in the repo\", or \"catch me up on the OS\"."
---

## What this skill does

Reads the git log since your last session-marker, deep-reads program records and pending extraction files that changed, and produces a structured briefing scoped to what the OS knows. No Teams. No corporate data. Repo state only.

Output is:
1. Written to `reports/os-briefing-{YYYY-MM-DD}-{username}.md`
2. Displayed in conversation

---

## Step 1: Identify the invoker

Run:
```bash
git config user.name
```

Use the result as `{username}`. If the command returns nothing (git identity not configured), display:
> "Git identity not configured — run `git config user.name 'Your Name'` first, then re-run `/os-briefing`."

Stop. Do not proceed without `{username}`.

---

## Step 2: Check for unpulled commits

Run:
```bash
git fetch origin --quiet && git log HEAD..origin/main --oneline
```

If this returns any lines, display a warning **before** generating the briefing:

> **Warning:** {N} unpulled commits on origin/main. Run `git pull origin main` for a complete picture. Generating briefing from local HEAD only.

Continue with local HEAD regardless — do not auto-pull.

---

## Step 3: Determine the comparison baseline

Look for the session-marker file at `.briefing-markers/{username}.sha`.

**If the marker exists:** read its content as `{baseline_sha}`. This is the last commit the invoker acknowledged.

**If the marker does not exist:** fall back to 48 hours ago:
```bash
git log --since="48 hours ago" --format="%H" | tail -1
```
Use the oldest SHA from that range as `{baseline_sha}`. If that command returns nothing (no commits in 48h), the invoker is fully caught up. Skip to Step 8 (write marker with current HEAD, emit "caught up" message).

---

## Step 4: Get the commit list

Run:
```bash
git log {baseline_sha}..HEAD --format="%H %ae %s" --reverse
```

This gives you every commit since the baseline, in chronological order: `{sha} {author_email} {subject}`.

If no commits are returned: invoker is caught up. Skip to Step 8.

Determine the date span: subtract the date of the oldest commit from today. If span > 3 days OR commit count > 30, activate **overflow mode** (see Step 5b).

---

## Step 5: Classify and read changes

### Step 5a: Normal mode (≤ 3 days, ≤ 30 commits)

For every commit, run:
```bash
git diff {prev_sha}..{sha} --name-only
```

**Tier 1 files** (deep-read): `docs/records/program/` and `docs/records/pending/`
**Tier 2 files** (deep-read): any file in `docs/records/` not in Tier 1 that was added or modified
**Tier 3 files** (commit message only): `docs/records/waves/`, `docs/records/milestones/`, `.claude/agents/`, `.claude/skills/`
**Tier 4 files** (commit message only): everything else

For Tier 1 and 2 files, run:
```bash
git diff {prev_sha}..{sha} -- {filepath}
```
Read the actual added lines (lines starting with `+`) to extract the substance of the change.

For Tier 3 and 4, record only: commit SHA (short), commit subject, list of filenames changed.

### Step 5b: Overflow mode (> 3 days or > 30 commits)

**Last 3 days:** apply Step 5a (full deep-read for Tier 1/2).

**Older commits:** bucket by calendar day. For each day, record:
- Date
- Commit count
- List of commit subjects (no deep-reads)
- Rough category counts: decisions, risks, ingests, plan changes (inferred from subject lines)

Overflow bucket summary will appear as a collapsed section at the bottom of the briefing.

---

## Step 6: Apply personalization

For all Tier 1/2 diffs (the added lines), scan for `{username}`:

- **"Action required"** — username appears as: action owner ("**{username}**" near "to do", "owns", "action", "next step"), decision-maker, or assignee
- **"Be aware"** — username appears elsewhere in the diff, or the changed file is in an initiative the invoker owns (determined from `CLAUDE.md` initiative definitions)
- **No special flag** — all other changes

Build a list of flagged files/decisions with their urgency level.

---

## Step 7: Assemble the briefing

```markdown
# OS Briefing — {today's date}

**Invoker:** {username}
**Baseline:** {short baseline_sha} → HEAD ({short HEAD sha})
**Period:** {from_date} to {today}
**Commits reviewed:** {N}

{if unpulled warning: repeat warning here}

---

## Action Required for {username}

{list each item where username was flagged "action required" — what changed, which file, why it flags them}

*{If none: "Nothing requires your direct action."}*

---

## Be Aware

{list each item where username was flagged "be aware" — brief context on what changed and why it's relevant to them}

*{If none: omit this section.}*

---

## Decisions Made

{for each D-series entry added or updated in program records — decision number, one-line summary}

*{If none: "No new decisions."}*

---

## Risks Updated

{for each R-series entry added or updated — risk ID, one-line summary, status if changed}

*{If none: "No risk updates."}*

---

## Ingested

{for each pending extraction file added or program record updated via ingest — source, brief topic, initiative tag}

*{If none: "Nothing ingested."}*

---

## Plan Changes

{for each update to plan-of-record, roadmap, or initiative scope — what changed, in which record}

*{If none: "No plan changes."}*

---

## Other Changes

{Tier 1/2 changes not captured above — agent updates, skill updates, structural changes. One line each.}

{Tier 3/4 changes: list commit subjects only.}

---

{if overflow mode:}
## Earlier Changes (Bucketed)

| Date | Commits | Summary |
|------|---------|---------|
| {date} | {N} | {subject list, comma-separated} |
| ... | | |
```

---

## Step 8: Write marker and save report

**Write the session marker:**
Write the current HEAD SHA to `.briefing-markers/{username}.sha` (create the directory if it doesn't exist).

```bash
git rev-parse HEAD
```

Write that SHA as the sole content of `.briefing-markers/{username}.sha`.

**Write the report:**
Write the assembled briefing to `reports/os-briefing-{YYYY-MM-DD}-{username}.md`.

**Display** the briefing in conversation.

---

## Zero-change case

If Step 4 found no commits (invoker is fully caught up):

```markdown
# OS Briefing — {today's date}

**Invoker:** {username}
**Status:** Fully caught up — no changes since your last session ({short baseline_sha}).

Nothing to review.
```

Still update `.briefing-markers/{username}.sha` to current HEAD.

---

## Critical rules

1. **No Teams. No corporate data.** This skill is repo-native only. If you need Teams context, use `/morning-briefing` instead.
2. **Do not auto-pull.** Check for unpulled commits and warn; never run `git pull`.
3. **Tier 1/2 deep-reads only.** Do not deep-read Tier 3/4 — commit messages only. Token cost discipline.
4. **Personalization is additive.** The invoker-specific sections appear first; the full briefing still follows. Don't hide changes that don't flag the invoker.
5. **Zero-change is not an error.** Emit a clean "caught up" message. Always update the marker.
6. **Marker is per-user.** `.briefing-markers/{username}.sha` — one file per person. Never share or overwrite another user's marker.
7. **Report is local-only.** Both `.briefing-markers/` and `reports/os-briefing-*.md` are gitignored. These are consumption artifacts, not production records.
8. **Don't invent personalization signals.** Only flag the invoker if their name (as returned by `git config user.name`) literally appears in the diff. Don't infer.
9. **Initiative scope for "be aware"**: The initiatives an invoker owns are defined in the client `CLAUDE.md` human team table. Only apply if the invoker is listed there with an initiative association.
10. **If baseline_sha is ambiguous** (marker SHA not found in git log — e.g., history was rewritten): fall back to 48h and note in the briefing header that the marker was stale.
