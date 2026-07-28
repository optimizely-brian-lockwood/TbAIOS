# Transformation → Dev Team Handoff Contract

## Purpose

This document is the authorized bridge between the AI Office Transformation team and the Dev
team. The Engineering Liaison (`engineering-liaison`) is the only role permitted to cross this
bridge.

No AI Office agent may directly task a dev-team agent. The flow is:

```
AI Office (any role)
  → Transformation Lead (intake + routing)
    → Engineering Liaison (translate + commission)
      → Engineering Manager (dev team entry)
        → Dev team roles
```

---

## When to cross this bridge

The bridge is crossed when:
1. An AI Office design produces a capability the Transformation team cannot deliver with existing tools
2. The AI Solution Architect has confirmed AI is fit-for-purpose (not a process fix)
3. The Transformation Lead has approved commissioning a build
4. A solution brief exists (owned by AI Solution Architect)

The bridge is NOT crossed for:
- Exploration, research, or feasibility assessment (done within AI Office)
- Process-fix recommendations (Lens 1 — no build required)
- Prompt engineering or agent configuration (done within AI Office)

---

## Handoff artifact: Engineering Brief

The Engineering Liaison produces an **Engineering Brief** before engaging the dev team.
The brief must contain:

| Section | Content |
|---|---|
| **Initiative** | Which initiative this build serves (I-NNN) |
| **Problem statement** | What stakeholder or practitioner problem this solves |
| **Proposed capability** | What the system should do (not how — that's the dev team's job) |
| **Inputs and outputs** | What goes in, what comes out, what integrates with what |
| **Acceptance criteria** | How the Transformation team will know the build is correct |
| **Out of scope** | What the dev team should NOT build (prevents scope creep) |
| **Dependencies** | Data, systems, or decisions the build relies on |
| **Success metric** | How the value of this build will be measured (dual-metric discipline) |

---

## Feedback loop

After the dev team delivers:
1. Engineering Liaison carries the demo back to the AI Office team
2. Transformation team validates against acceptance criteria
3. Feedback goes back through Engineering Liaison → Engineering Manager
4. Program Manager logs the delivery in the artifact index and progress tracker

---

## Hard rules

- No AI Office agent bypasses the Engineering Liaison to reach the dev team.
- No dev team agent takes direction from the AI Office except through the Engineering Manager.
- The Engineering Liaison does not write code or manage the dev team's internal workflow.
- Scope changes after commission go through the Engineering Liaison — not directly to the dev team.
