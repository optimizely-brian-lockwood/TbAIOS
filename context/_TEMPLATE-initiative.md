# Initiative Definition — [Initiative Name]

## About this file

This file defines the initiative(s) this engagement manages. Copy this template for each
initiative. The AI OS reads these definitions to route work, tag records, and enforce
initiative separation.

---

## Initiative registry

### [Initiative ID, e.g. I-001] — [Initiative Name]

| Field | Value |
|---|---|
| **Initiative** | [Full initiative name] |
| **Alias** | [e.g. I-001] |
| **Target** | [Primary goal — e.g., "30% efficiency gain in 18 months"] |
| **Scope** | [What is in scope — be specific about what is out of scope] |
| **Default posture** | [e.g., "Capacity redeployment, not headcount reduction"] |
| **Current phase** | [e.g., "Post-kickoff. Workshop scheduled for [date]"] |
| **Records** | [Path to this initiative's records — e.g., `docs/records/`] |

---

### [Initiative ID, e.g. I-002] — [Second Initiative Name]

*(Copy the block above for each additional initiative. If only one initiative, delete this block.)*

| Field | Value |
|---|---|
| **Initiative** | [Full initiative name] |
| **Alias** | [e.g. I-002] |
| **Target** | [Primary goal] |
| **Scope** | [What is in scope and out of scope] |
| **Default posture** | [Operating principle] |
| **Current phase** | [Current status] |
| **Records** | [Records path] |

---

## Initiative separation rules

When this engagement manages multiple initiatives:

- Every ingest, artifact, decision, and routing action must be tagged to exactly one initiative.
- Records for separate initiatives must live in separate directories.
- If initiative classification is ambiguous at intake, **stop and ask** — do not guess or blend.
- The `transformation-lead` owns initiative classification at intake.

---

## Notes

*Add any context about initiative history, sponsor relationships, or strategic dependencies
that would help the AI OS serve the engagement better.*
