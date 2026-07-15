# `contract-v1` harness core

The portable enforcement seam shared by all harness builds (hooks, evals, obs).
A **harness-agnostic core** reads a versioned JSON event on stdin and answers on
two channels — an exit code (the load-bearing control signal) and a structured
stdout decision (plus a human message on stderr). Everything harness-specific
lives in a thin, disposable **adapter** that does event wiring only.

> **Status: LIBRARY-ONLY.** This package is tested Python modules. Nothing here
> is wired to a live hook, git config, CI, or `.claude/settings.json`. Importing
> or running it has no effect on repo/commit/session behaviour. Activation
> (adapters, git hooks, CI tier) is a later, separate step. See
> "Deferred to activation" at the end.

Spec of record:
- `docs/dev-team/architecture/2026-07-13-harness-portability-contract-adr.md`
- `docs/dev-team/architecture/2026-07-13-harness-hooks-obs-substrate-adr.md`

---

## Layers

```
HARNESS (Claude / Codex / git / CI)  --native event-->  ADAPTER (thin, no policy)
                                                             |
                                          contract-v1 event JSON on stdin
                                                             v
                                     HARNESS-AGNOSTIC CORE (this package)
                                     validate envelope -> dispatch -> module
                                     -> resolve policy -> decision
                                                             |
                              contract-v1 decision JSON on stdout + exit code
                                                             v
                        adapter maps exit code back to native allow / warn / block
```

**Invariant:** the core never imports, names, or branches on a harness. An
adapter that contains policy (`if ticket.is_sensitive: ...`) is a defect — that
logic belongs in the core.

---

## The event envelope (stdin)

One JSON object. Fixed across every `event_type`; only `payload` varies. Source
of truth: [`hook-event.schema.json`](./hook-event.schema.json).

```json
{
  "contract_version": "1.0",
  "event_id": "uuid-v4",
  "event_type": "pre-tool-use | pre-commit | pre-push | feature-merge | pre-pr | eval-run | obs-emit",
  "occurred_at": "2026-07-13T09:00:00Z",
  "harness": { "name": "claude", "adapter_version": "1.0.0" },
  "requested_mode": "warn | block | annotate",
  "payload": { }
}
```

| Field | Required | Meaning |
|---|---|---|
| `contract_version` | yes | Semver. Core rejects a MAJOR it does not implement. |
| `event_id` | yes | Correlates the response; used by obs/audit. |
| `event_type` | yes | Selects the module. Unknown → `block` (enforcement) / `no-op` (obs). |
| `occurred_at` | yes | ISO-8601 UTC. |
| `harness.name` | yes | Audit label ONLY. Core must not branch on it. |
| `requested_mode` | yes | Posture the adapter can surface. Policy may HARDEN it; never SOFTENS a floor module. |
| `payload` | yes | Event-type-specific body. A PII-scrub-guarded event carries `boundary` + `fixture` (see below). |

---

## The response protocol

Answered on two channels simultaneously (a machine and a human both get a
signal):

**1. Exit code — the load-bearing control signal (only 0-vs-nonzero is contractual):**
- `0` = allow. **This includes `warn`** — the action proceeds.
- non-zero = block. The action is stopped.

**2. stdout — the structured decision (machine-readable):**
```json
{
  "contract_version": "1.0",
  "event_id": "uuid-v4",
  "decision": "allow | warn | block | no-op | not-graded",
  "module": "pii-scrub",
  "reasons":     [ { "code": "PII_DETECTED", "category": "EMAIL", "count": 1 } ],
  "annotations": [ { "severity": "info|warn|error", "message": "…" } ]
}
```
`reasons` / `annotations` carry **categories and counts only — never a matched
substring** (no-PII-echo invariant).

**3. stderr — the same content in human-readable form**, so a warn is visible in
a scrolling transcript even when the adapter discards stdout.

| `decision` | exit code |
|---|---|
| `allow`, `warn`, `no-op`, `not-graded` | `0` |
| `block` | non-zero |

---

## Precedence — how the final decision is resolved on a module hit

Resolved at evaluation time, in strict order (portability ADR §2.2):

1. **Immutable module floor (code, not config).** Fail-closed modules
   (`pii-scrub`, and future `security-gate`) resolve to `block` on a hit. No
   `requested_mode` and no flip state can soften them.
2. **Recorded flip state (config).** Warn-only modules read one recorded value:
   pre-flip → `warn`, post-flip → `block`.
3. **Adapter `requested_mode` (hint).** May only *narrow toward* `warn`, and only
   for **non-floor** modules on harnesses that cannot surface a block in-editor.

So `warn`+exit 0 and `block`+exit 1 come out of the *same* module by resolving
policy — a warn-only module and a fail-closed module share one code path.

---

## Writing a new harness adapter

An adapter has exactly two jobs and holds **zero policy**:

- **In:** capture the harness's native event, map it onto the envelope above,
  fill `harness.name` / `adapter_version` / the best honourable `requested_mode`,
  and pipe the JSON to the core on stdin.
- **Out:** read the core's exit code (and optionally stdout) and translate it to
  the harness's native allow / warn / block.

The test for "is this really an adapter": deleting it and writing a new one for a
different harness must lose **no** enforcement logic. If a harness exposes no
in-editor interception event, enforcement degrades to the git/CI floor but never
below it (the floor runs the identical core on the commit/PR boundary).

No Claude-specific assumption exists in the core. The `git` and CI adapters
(deferred to activation) invoke the same core with an `event_type` derived from
the actual git operation — they never trust a stdin-supplied `event_type` for
enforcement classification.

---

## Event-type convention

Event types fall into **disjoint categories**; `event_type` alone decides which
floor may claim an event, and `boundary` is honored **only** on a data-boundary
type (this is what decouples SG-3 from QA-9 and lets the gate harden safely):

| Category | `event_type` | Payload | Floor |
|---|---|---|---|
| Enforcement / gate | `pre-commit`, `pre-push`, `pre-pr`, `feature-merge` | `ticket` + `changeset` (gate-shaped) | security-gate |
| Data-boundary / scrub | `import-into-repo`, `eval-egress` | `fixture` (+ implied boundary); never a ticket | pii-scrub |
| other | `obs-emit`, `eval-run` | — | obs / eval runner (not a floor) |

## Modules in this increment

| Module | Hardness | Trigger | Status |
|---|---|---|---|
| `pii-scrub` | **fail-closed floor** | data-boundary event types: `import-into-repo`, `eval-egress` | **implemented** |
| `security-gate` | **fail-closed floor** | gate event types (`pre-pr`, `feature-merge`); a gate event with no `ticket`/`changeset` → BLOCK (SG-3) | **implemented** |
| `commit-block` / `atomic-tracking` | warn-only → flip | `pre-commit` / `feature-merge` | registration seam only |
| `obs.emit` | fail-open | `obs-emit` | registration seam only |

### `pii-scrub` payload shape

```json
"payload": {
  "boundary": "import-into-repo | egress-to-judge",
  "fixture": {
    "filename": "...",
    "fields": { "...": "..." },
    "rubric": "...",
    "payload": { "...": "..." },
    "commit_message": "..."
  }
}
```

Detection contract is **high-precision machine detection + a human-ratification
recall backstop**. The
machine does **not** try to catch all PII; it detects only well-defined,
low-false-block PII *shapes* and hard-blocks on any hit. Per-fixture human
ratification (already mandatory for eval fixtures) is the recall backstop for
shapes/encodings/cross-field splits the machine deliberately skips; "raw is
never committed" bounds that residual.

Machine MUST-DETECT shapes (hard block): email; Luhn-valid + IIN-prefixed
credit card (after Unicode normalization); delimited SSN and context-gated
contiguous SSN; AWS AKIA/ASIA keys; known-vendor API keys (sk-/ghp_/glpat-/xox*/
AIza/Stripe); PEM private-key headers; JWTs; a high-entropy value **only** under
a secret-labeled key; formatted/E.164 phone. **IP is out** (human recall), as
are bare 10-digit numbers and bare high-entropy strings in non-secret fields.

MUST-NOT-BLOCK, passed byte-for-byte (never silently redacted): ISO-8601
datetimes, git SHAs (incl. the control's own `reviewed_commit`/`content_hash`),
semver, plain integers / 8-digit dates / config numbers, UUIDs.

Two-stage, fail-closed, independent engines: a **scrubber**
(regex-substitution ruleset A) feeds a cleaned copy to an **independent
scanner** (structural token/validator ruleset B, its own checksum/entropy math,
no shared pattern table). A MUST-DETECT hit by **either** engine hard-blocks;
the blocked result carries neither cleaned nor raw content. Coverage is
full-surface with Unicode normalization (NFKC + separator stripping)
applied before digit-shape checks: the filename, every nested field, the
rubric, the judge payload, the commit message, **and every dict key** (a key can
itself be PII) are scanned — each scalar leaf as one unit; cross-field
reassembly across separate keys/array items is **not** machine-required
(human recall). `surfaces_hit` uses a fixed allow-list of surface names (or
`"other"`) and reasons carry category+count only, so no matched value or
caller-supplied key is ever echoed (no-PII-echo invariant).

---

## Running the tests

Stdlib `unittest` (no third-party dependency; the repo runs bare `python`):

```
python -m unittest discover -s scripts/harness/tests -p "test_*.py"
```

The same tests are discovered by `pytest` if it is later added (dev-only).

---

## Deferred to activation (NOT done here)

- No `adapter-claude.py`, no `.claude/settings.json` hook entries.
- No git hooks / `core.hooksPath` / CI workflow (the universal enforcement floor
  and the `--no-verify`-proof CI tier are DevOps activation
  tasks).
- `security-gate`, `commit-block`, `atomic-tracking`, `clickup-readonly`,
  `obs.emit` modules: registration seam is in `core.py`; not built this
  increment.
- Flip-state config file (HK6): `resolve_policy` accepts a `flip_state` dict; no
  file is created or read live.
- Git-context-derived enforcement `event_type`: the core
  already routes any boundary-carrying payload to the `pii-scrub` floor
  regardless of the stdin `event_type`; deriving the enforcement type from the
  actual git operation is the git-adapter's job (activation).
