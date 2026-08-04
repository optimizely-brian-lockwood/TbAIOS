# Engineering Tickets

> **Workflow**: Claude Code reads this file and works on the first unchecked `- [ ]` item.
> For each feature:
> 1. Create and checkout a new branch from your trunk branch, using the branch name listed
> 2. Implement the feature, committing work to that branch
> 3. Merge back per your branching convention
> 4. Mark the item `- [x]` and add an **Implemented in:** note
>
> **To start:** Tell Claude: *"Read FEATURES.md. Work on the next unchecked feature."*
>
> Claim your ticket in `ACTIVE-WORK.md` before creating the branch — see that file for the
> parallel-work protocol. Update this file, `ACTIVE-WORK.md`, and `CHANGELOG.md` in the
> **same commit** as the merge (`docs/dev-team/team-charter.md` hard rule — no exceptions).

---

## Backlog

- [ ] **[Feature name]** — [One paragraph: what it does, why it matters, any constraints.]
  - **Branch**: `feature/[slug]`

<!--
Example of a completed entry:

- [x] **CSV export on the reports page** — lets a user download the current filtered view
  as a CSV. Client-side generation, no new backend endpoint.
  - **Branch**: `feature/csv-export`
  - **Implemented in**: `feature/csv-export` — merged to `main` (PR #12, 2026-08-01).
    - `src/components/reports/ExportButton.tsx` — new component
    - `src/lib/csv.ts` — `toCsv()` helper, unit tested
-->
