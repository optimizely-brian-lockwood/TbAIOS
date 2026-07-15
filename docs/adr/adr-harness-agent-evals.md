# ADR — Agent-Behavior Eval Harness

**Status:** Accepted (base-layer architecture)
**Scope:** The eval runner that grades each dev-team *role* on whether it caught the failures it exists to catch, measured against a human-ratified answer key, with the LM judge never inventing ground truth.
**Depends on:** `adr-harness-portability-contract.md` (the runner and judge cross the same `contract-v1`) and `adr-harness-hooks-obs-substrate.md` (the eval harness *consumes* the shared fail-closed PII-scrub control at its egress boundary; it does not build its own).

---

## 1. Context

A product test suite proves the *product* compiles and behaves; it says nothing about whether an *agent role* did its job — whether the reviewer caught the injected bug, whether the security engineer flagged the planted PII exposure. This harness grades role **behavior**, not product correctness.

The core guarantee is that a human sets truth and the machine applies it: the judge never invents ground truth, never sees the answer key, and never writes a label. It is functionally downstream of the PII-scrub control — no fixture may be imported and no judge egress may be finalized until that control exists and is reviewed.

The harness grades against generic dev-team roles (engineering-manager, product-manager, software-architect, ux-designer, tech-lead, senior-developer, developer, qa-engineer, code-reviewer, security-engineer, devops-engineer), so it promotes upstream and any derived engagement inherits it.

---

## 2. Decision

### 2.1 Four components behind the contract

```
  FIXTURE STORE        RATIFIED LABEL STORE       PER-ROLE RUBRICS
  (two classes)        (human sets once,          (named, versioned,
        │               immutable at eval time)    per-line expectations)
        │  contract-v1 eval-run event (fixture + rubric ref + label ref)
        ▼
  EVAL RUNNER (core module)  ──── answer-free GradingRequest ───►  LM-JUDGE ADAPTER
  resolve rubric → refuse-if-unlabelled → scrub-before-egress                (swappable)
  → call judge → score proposed-vs-ratified LOCALLY   ◄──── proposed per-line booleans
        ▼  per-role score: trajectory + output (distinct fields)
```

The runner is a core module behind the contract: an `eval-run` event in, a score result on stdout plus a conformant exit code, no harness dependency. It is a **reporter, not an enforcement floor** — it is not registered in the core's enforcement registry. The judge is an **adapter behind the same contract**, so swapping the LM changes no runner interface, rubric format, or score schema.

### 2.2 Per-role rubrics keyed to the generic dev-team roles

A rubric is a named, versioned set of testable expectation lines for one role (rubrics are **data** — JSON files; the module is the loader). Each line carries `id`, `assert` text (what it asserts, in outcome terms), `defect_class`, `dimension` (`trajectory` | `output`), a `weight` (reserved), and a `signal` token used only by a deterministic test judge.

- **Per-line scoring, never one opaque verdict** — the runner emits a score per rubric line, so *which* expectation failed is visible.
- **Versioned as roles evolve** (`role.vN`): a fixture's label is bound to the rubric version it was ratified against. Changing a line is a new version, not a silent re-score; old ratified labels remain valid against the version they were set on and surface as needing re-ratification otherwise.

### 2.3 Two fixture classes

| Class | Ground truth | Purpose |
|---|---|---|
| **Real historical** | label reconstructed from what actually happened | fidelity — reproduce known-good history |
| **Synthetic planted-defect** | label = "defect present, role X owns catching it" | sensitivity — prove the eval catches a miss |

Real-historical fixtures alone cannot test "caught the planted bug" (a role could pass every real fixture and stay blind to a defect class), so synthetic planted-defect fixtures are first-class ground truth. A fixture carries at minimum `fixture_id`, `class`, `role_under_test`, the role's **trajectory** (ordered steps/decisions), the role's **final output**, and a reference into the label store — never an inline label.

### 2.4 Immutable, human-ratified label store — judge never invents truth

- Labels are set **once by a human ratifier** and are immutable at eval time, keyed by `(fixture_id, rubric_id, line_id) → ratified_value`. Ratification is set-once: re-ratifying a key to a different value raises; once the store is frozen, all writes raise (the frozen store is swapped to a read-only proxy as cheap defense-in-depth).
- **The judge gets an answer-free view.** The runner holds the store; the judge is constructed with no store reference and the grading request carries no labels. There is no code path by which the judge can write, alter, or create a label — the judge never sees a "write label" interface because none is passed to it.
- **Unlabelled fixture → refuse to grade.** If a fixture is not fully labelled for its rubric, the runner returns `not-graded` and never falls back to judge-generated truth. This check runs *before* any egress or judge call.
- A ratified label that disagrees with a reconstructed outcome surfaces for human re-ratification; the runner does not silently pick one.

*Scope note:* these guarantees are structural against the threat model — untrusted `contract-v1` input, and the judge boundary (the judge receives no store/label/answer). They are not absolute in-process tamper-proofing; code executing inside the trusted harness process is out of scope. Defense-in-depth is applied where free (the request-minting key lives in a closure with no module-level name; labels freeze to a read-only proxy).

### 2.5 Structural scrub-before-egress to the LM judge

- The grading request — the only object a judge grades — is minted **only** by an egress gate, and only **after** the full egress view passes the shared fail-closed PII-scrub control at the `eval-egress` boundary. A scanner hit returns nothing → no request → the judge is never called. Across the whole surface there is no path from a raw fixture to a judge that skips the scrub.
- **Scrub coverage equals egress content exactly.** The egress view is the full fixture with answer-encoding keys stripped at every depth, plus a rubric view of `{id, assert-text}` only (no `signal`, no `defect_class`). So the judge sees the substance but neither a ratified label (none is passed) nor the answer key (stripped) — it can neither read nor inflate the truth — and everything that egresses (including nested/ad-hoc fields) is exactly what the scrub inspected.
- The scrub control is **consumed, not rebuilt** — one shared control, two consumers (fixture import and judge egress), one audit surface. No fixture may be imported and no judge egress finalized until that control is reviewed.

### 2.6 LM judge as a swappable adapter

- The judge interface is `GradingRequest → {line_id: bool}` (proposed per-line judgments). Swapping the LM is an adapter swap; the runner interface, rubric format, and score schema are unchanged.
- A real-LM adapter is activation-gated (wired with a client + credentials at activation, never invoked in library/tests); it egresses only the gate-cleared answer-free request, maps LM output to per-line booleans (else the run is `incomplete`), and receives no labels. A future non-LM-vendor judge is a sibling adapter implementing the same interface. A deterministic test judge and an always-raising judge exercise the runner without a network.
- **Judge unavailable / errors mid-run → `incomplete`, never a default pass.** Failure resolves toward "not graded," never toward "passed." An empty fixture set resolves to `no-fixtures` cleanly, not an error-producing-scores state. The runner never raises: any internal exception fails closed to `incomplete` with no raw content in the result.

### 2.7 Scoring model — trajectory vs. output, general threshold + exact-100% for security

- The runner emits **two distinct score fields**, `trajectory_score` and `output_score`, never collapsed into one.
- **Rubber-stamp / drift detection is trajectory-based, not output-only.** A role that produced the correct output via a flawed trajectory (approved the right answer with no evidence of review) raises a `rubber-stamp` signal *even when the output label matches* — the signal is a function of trajectory-line failures, independent of output correctness.
- **General fidelity threshold ≥ 0.90** for trajectory and output, computed over **non-security** lines only.
- **Security-defect classes (pii / authz / authn / secret) are held to an exact 100% bar** — any single security-line mismatch fails the run and is surfaced individually, never averaged into the general band. A matching security line can never mask a general miss, and a general miss can never be averaged away by security matches.
- A rubric with no trajectory-dimension line reports a `null` trajectory score (not a vacuous 1.0 that would silently disable rubber-stamp detection); such a run never passes. `not-graded` / `incomplete` / `blocked` / `no-fixtures` never pass.

### 2.8 Data model

| Store | Written by | Read by |
|---|---|---|
| Fixtures (cleaned only) | the scrub control (cleaned copies only; raw never committed) | runner |
| Ratified labels | human ratifier only | runner (read-only); judge never |
| Per-role rubrics | authored content, versioned | runner, judge (assert-text view only) |
| Score output | runner | operator (CLI/stderr/log; no dashboard) |

No datastore and no CI wiring in the base design — the harness runs on demand; grading role behavior is distinct from the product test suite and does not grade product correctness.

---

## 3. Consequences

- **The judge cannot cheat by construction.** It is handed no label store and an answer-stripped view; ground truth is human-set and immutable, and the runner compares locally.
- **Sensitivity and fidelity are both tested.** Planted-defect fixtures prove the eval catches a miss; real-historical fixtures prove it reproduces known-good behavior.
- **Rubber-stamping is detectable.** Separating trajectory from output surfaces the "right answer, no review" failure that output-only scoring hides.
- **Security misses cannot be averaged away.** The exact-100% security bar sits outside the general band.
- **Vendor-independent.** The LM judge is an adapter swap; nothing else moves.
- **No PII reaches the repo or the judge.** Both fixture import and judge egress route through the same reviewed fail-closed scrub, and failure always resolves toward "not graded," never "passed."

---

## 4. Alternatives considered

1. **Judge establishes ground truth (rejected — circular).** A judge grading against its own labels tests nothing; the whole guarantee is human-sets-truth / machine-applies-it.
2. **Real historical fixtures only (rejected).** Cannot test "caught the planted defect"; synthetic planted-defect fixtures are first-class.
3. **Single opaque verdict per fixture (rejected).** Hides which expectation failed and defeats the trajectory-vs-output split; per-line scoring is required.
4. **Output-only scoring (rejected).** Misses rubber-stamping; trajectory scoring is the drift detector.
5. **The eval harness builds its own PII-scrub path (rejected).** Two controls = two audit surfaces and drift risk; one shared control, two consumers.
6. **Averaging security-defect lines into the general threshold (rejected).** A matching security line could mask a miss; security classes are held to an exact bar, scored separately.
