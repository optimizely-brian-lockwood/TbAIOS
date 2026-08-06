---
name: challenge-me
description: >
  Stress-test a plan, design, feature, or decision by interviewing the user relentlessly — one
  question at a time — until every branch of the decision tree is resolved. After every answer,
  checkpoint the decision to a durable knowledge doc in brainstorms/. Use this skill whenever
  the user says "challenge me", "stress test this", "poke holes in my plan", "interrogate my
  design", "grill me", "ba questions", "question my approach", "push back on this", or whenever
  they share a plan or architecture and want it pressure-tested before building. Always invoke
  this skill proactively when the context is a plan or design that hasn't been fully stress-tested.
---

# challenge-me

Turn tacit knowledge into a durable, reusable knowledge doc by systematically challenging every
assumption. The goal isn't to find reasons to stop — it's to surface everything that needs to be
true for the plan to work, get those things confirmed or corrected, and record them so they
compound into better context, better skills, and better future builds.

## How It Works

```
[Topic in user's head]
        ↓
  Ask 1 question          ← with your recommended answer
        ↓
  User confirms or        ← wrong guesses are signal; push back if vague
  corrects
        ↓
  Checkpoint to .md       ← write this decision to the knowledge doc immediately
        ↓
  (repeat for every branch of the decision tree)
        ↓
  Final sweep             ← "What's missing, unclear, or potentially wrong
                              in what we just produced?" — one last pass
                              over the doc as a whole, not branch-by-branch
        ↓
  Durable knowledge doc   ← structured, reusable, the source of truth
```

## Step 0: Set Up the Knowledge Doc

Before asking a single question:

1. Infer the topic from context (the user's message, the current task, open files, etc.)
2. Create the file path: `brainstorms/{YYYY-MM-DD}--{topic-slug}.md`
   - Use today's date in YYYY-MM-DD format
   - Slug = 3-5 lowercase words joined with hyphens, e.g. `payment-retry-logic`
3. Write the skeleton (see **Doc Format** below)
4. Tell the user the file path so they know where it's accumulating

If you're in a git repo and can read the codebase, scan relevant files first before asking questions
that the code already answers — explore, don't interrogate.

## Step 1: Build the Decision Tree

Before asking the first question, mentally map out everything that needs to be resolved:

- Core intent / problem being solved
- Approach / algorithm choices
- Data model and state management
- Integration points and dependencies
- Edge cases and failure modes
- Rollback / escape hatches
- Performance, security, and maintainability implications
- What "done" looks like and how it'll be tested

You won't ask about all of these — some branches are answered by the codebase, some by what the
user already said. Prioritise the branches with the most downstream dependencies.

## Step 2: Question Loop

For each unresolved branch, in dependency order:

**Ask one question at a time.** Never bundle two questions.

Format each question like this:

> **Q[N]: [The question]**
> My take: [your concrete recommended answer, with brief reasoning]

The suggested answer is not optional — it serves two purposes:
1. It's faster for the user (confirm vs. compose)
2. Wrong guesses are signal — a correction tells you more than a blank answer

**Be genuinely challenging.** Don't accept the first answer if it's vague or hand-wavy. Push back:
- "That makes sense, but what happens when X fails?"
- "You said Y — does that still hold if Z is true?"
- "What's the rollback if this turns out to be wrong in production?"
- "Is that assumption safe to make, or does it need to be enforced somewhere in code?"

Reserve pushback for decisions that are load-bearing. Not every answer needs follow-up.

## Step 3: Checkpoint After Every Answer

Immediately after each confirmed or corrected answer — before asking the next question — update the
knowledge doc. Do not batch checkpoints at the end.

Append to the **QA Log** section and update the relevant **Key Decisions** or **Algorithms** section
if the answer is substantial. The doc should be useful mid-session, not just at the end.

## Step 4: Final Sweep

Once every branch from Step 1 is resolved, run one more pass — this catches gaps the decision
tree didn't anticipate, because it looks at the produced doc as a whole rather than branch by
branch.

Ask it as a single, explicit question, same format as any other:

> **Final sweep: What's missing, unclear, or potentially wrong in what we just produced?**
> My take: [your genuine read of the doc's weakest point(s) — a gap in coverage, a decision
> that still feels soft, an interaction between two answers that wasn't reconciled]

Treat whatever surfaces here like any other branch: push back if the answer is vague, and
checkpoint it into the doc (usually **Open Questions**, or **Key Decisions** if it resolves
cleanly) before closing out.

## Step 5: Close Out

When the final sweep is resolved (or the user says they're done):

1. Write a short **Summary** section at the top of the doc — 3-5 sentences capturing the plan as
   now understood
2. Confirm the file path to the user and note any open questions that were deferred
3. Optionally: flag whether any answers suggest the plan needs rethinking before building

---

## Doc Format

```markdown
# {Topic Title}

**Date**: YYYY-MM-DD  
**File**: brainstorms/{YYYY-MM-DD}--{topic-slug}.md  
**Status**: In Progress | Complete

---

## Summary

> [Written at close-out — 3-5 sentences capturing the agreed plan]

---

## Key Decisions

| # | Decision | Chosen Approach | Alternatives Considered |
|---|---|---|---|
| 1 | | | |

---

## Algorithms & Approaches

[Fill in as technical decisions are confirmed — data structures, flow, pseudocode if relevant]

---

## Open Questions

- [ ] [Anything deferred, unresolved, or flagged for follow-up]

---

## QA Log

### Q1: [Question text]
**Suggested**: [Claude's initial take]  
**Decided**: [User's confirmed or corrected answer]  
**Notes**: [Any pushback exchanged; why this matters]

### Q2: ...
```

---

## Scrutiny Checklist

Work through these lenses as you build the decision tree. Not all apply to every topic — use
judgment about which are load-bearing:

- **Correctness**: Does the logic actually produce the right result in all cases?
- **Edge cases**: What are the boundary conditions? What happens with empty, null, max, concurrent?
- **Failure modes**: What can go wrong at runtime? What's the blast radius?
- **Dependencies**: What does this rely on that could change or fail?
- **Reversibility**: Can this be rolled back? Is there a migration path?
- **Performance**: Are there hidden N+1s, unbounded loops, or scale cliffs?
- **Security**: Does this touch auth, user data, or external input? Where is it validated?
- **Testability**: How will this be verified? What makes a passing test meaningful?
- **Ownership**: Who maintains this? Will the next developer understand it without context?

---

## Example Opening

User: "challenge me on my plan to add optimistic UI updates to the order flow"

You:

> Starting a brainstorm doc at `brainstorms/2026-06-08--optimistic-ui-order-flow.md`.
>
> **Q1: Where does the optimistic state live — React local state, a Zustand store, or directly in the server cache layer (e.g. TanStack Query's cache)?**
> My take: TanStack Query's `setQueryData` is the right place — it keeps optimistic and server state co-located, handles rollback on error, and avoids a parallel state layer you have to sync manually.
