# ADR — Harness Portability Contract (`contract-v1`)

**Status:** Accepted (base-layer architecture)
**Scope:** The single portability seam shared by every harness subsystem — the lifecycle hooks/guardrail substrate, the observability emitter, and the agent-behavior eval runner all sit behind this one contract.
**Related:** `adr-harness-hooks-obs-substrate.md` (the modules that live inside the core), `adr-harness-agent-evals.md` (the eval runner and judge, which cross the same contract).

---

## 1. Context

The harness subsystem must run under more than one agent harness (for example a Claude-style CLI, a Codex-style tool runner, an Antigravity-style agent, plus git hooks and CI). Each harness emits its own native lifecycle events with its own shapes. Writing enforcement, scrubbing, evals, and observability once per harness would duplicate policy N times, guarantee drift between copies, and make any fail-closed guarantee unverifiable (every copy would need to be audited).

The design constraint is therefore portability as a first-class property, not a later retrofit: a harness-agnostic **core** that holds all policy, plus thin, disposable per-harness **adapters** that hold none. A specific harness is just the first adapter, never the design center.

The mechanism is deliberately minimal — JSON on stdin, a decision on stdout, and an exit code — because that primitive is present on every harness (every harness can run a subprocess and read its exit code) and needs no bespoke plugin API or framework.

---

## 2. Decision

### 2.1 Three concentric layers

Data crosses boundaries as JSON on stdin/stdout; control crosses as an exit code.

```
  HARNESS (any: CLI / tool-runner / agent / git / CI)  — emits a NATIVE event
        │  native event
  ADAPTER (thin, disposable, NO policy)  — native → contract-v1 on stdin;
        │                                   contract response → native allow/warn/block
        │  contract-v1 event JSON on stdin
  HARNESS-AGNOSTIC CORE (standalone)     — validate envelope → dispatch by event_type
        │                                   → run module(s) → resolve/compose decision
        │  contract-v1 decision JSON on stdout + exit code (+ human text on stderr)
  (adapter maps the exit code back to the harness's native allow/warn/block)
```

**Invariant:** the core never imports, names, or branches on a harness. It receives a `contract-v1` event and returns a `contract-v1` decision. Everything harness-specific is confined to an adapter that does event wiring only and is designed to be discarded and rewritten per harness.

### 2.2 The event envelope

Every event, regardless of source or type, is one JSON object on stdin. The envelope is fixed across event types; only `payload` varies — this is what lets one core serve hooks, scrub, eval, and obs without any event type knowing about the others.

```json
{
  "contract_version": "1.0",
  "event_id": "uuid-v4",
  "event_type": "pre-tool-use | pre-commit | pre-push | feature-merge | pre-pr | import-into-repo | eval-egress | eval-run | obs-emit",
  "occurred_at": "ISO-8601 UTC",
  "harness": { "name": "<label>", "adapter_version": "x.y.z" },
  "requested_mode": "warn | block | annotate",
  "payload": { }
}
```

| Field | Required | Meaning |
|---|---|---|
| `contract_version` | yes | Semver of the contract the adapter speaks. Core rejects a MAJOR it does not implement (§2.6). |
| `event_id` | yes | Correlates the response to the event; used by obs and audit. |
| `event_type` | yes | Selects the module(s). Unknown type → `block` on enforcement, `no-op` on obs. |
| `occurred_at` | yes | ISO-8601 UTC. |
| `harness.name` | yes | Free-form audit label ONLY. The core must not branch on it. |
| `requested_mode` | yes | The posture the *adapter* can surface. Policy may **harden** it (warn→block); it may never **soften** a fail-closed module. |
| `payload` | yes | Event-type-specific body. Per-type schemas live in the substrate and eval ADRs. |

A single checked-in JSON Schema file is the source of truth for the envelope; both core and adapters validate against it. To keep the core dependency-free, envelope validation is a small stdlib validator implementing the draft-07 subset the envelope uses (type / required / properties / enum / additionalProperties / pattern / nested objects) — the schema file remains authoritative.

### 2.3 The response protocol — two channels

The core answers on two channels simultaneously, so both a machine (git, CI) and a human (transcript reader) get an actionable signal:

1. **Exit code — the load-bearing control signal.** `0` = allow (this includes `warn`: the action proceeds); non-zero = block. Only the 0-vs-nonzero distinction is contractual. Exit code is the portable enforcement primitive present on every harness.
2. **stdout — the structured, machine-readable decision:**

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

3. **stderr — the same content in human-readable form**, so a warn is visible in a scrolling transcript even when the adapter discards stdout.

`reasons`/`annotations` carry **categories and counts only — never a matched substring** (the no-echo invariant, so a detector can never echo the sensitive value it matched into logs).

**One core, both hardness modes by config.** Whether a module *warns* or *blocks* is not baked into a code path — it is a policy resolved at evaluation time. A warn-only module and a fail-closed module share one code path; `warn`+exit 0 and `block`+exit 1 come out of the same module by resolving policy.

### 2.4 Precedence model (resolution on a module hit)

Resolved in strict order:

1. **Immutable module floor (code, not config).** Fail-closed modules resolve to `block` on a hit. No `requested_mode` and no recorded flip state can soften them. This floor is code.
2. **Recorded flip state (config).** Warn-only modules read one recorded value: pre-flip → `warn`, post-flip → `block`.
3. **Adapter `requested_mode` (hint).** May only *narrow toward* `warn`, and only for **non-floor** modules, on harnesses that cannot surface a block in-editor.

The config bound to a module is bound at registration (repo-side, trusted) and is **never** read from the event payload — otherwise an untrusted adapter could supply a permissive config to soften a gate.

### 2.5 The dispatch rule — all matching floors, any-block-blocks; non-floor decisions composed

Registry order does not determine whether a module runs. Dispatch evaluates **all** matching modules and **composes** their decisions; it never short-circuits after the first match.

- **Immutable floors — "all floors, any-block-blocks."** Every floor whose `matches()` is true is evaluated on an event, not just the first. A floor hit is unconditionally `block`. Floors are therefore non-bypassable by construction: a payload matching two floors must satisfy both, and matching one floor can never route *around* another. (A first-match selection was rejected: a payload shaped like one floor's event but carrying an extra key could route entirely to a different module and skip the intended floor.)
- **Non-floor modules** run only their warn/flip policy (§2.4) and are composed in even when a floor also matched — a co-matching warn is never silently dropped.
- **Compose to the strongest outcome:** any `block` (floor or non-floor) → block; else any `warn` → warn (exit 0, surfaced); else allow. `reasons`/`annotations` from every contributing module are aggregated, so a warn is still recorded under a floor block.
- A floor handler that raises fails **closed** (→ block); a non-floor enforcement handler that raises fails **to warn** (flip-state governs); the obs emitter that raises is a **no-op** (fails open). Exceptions are contained per module so co-matching modules still aggregate and dispatch never propagates.

### 2.6 Event-type categories

Event types fall into **disjoint categories**. `event_type` alone decides which floor may claim an event; a data-boundary flag is honored only on a data-boundary type. Disjoint categories are what let a gate harden safely without a data-boundary flow being able to disguise itself as a gate event (or vice-versa):

| Category | `event_type` | Payload | Floor |
|---|---|---|---|
| Enforcement / gate | `pre-commit`, `pre-push`, `pre-pr`, `feature-merge` | gate-shaped (`ticket` + `changeset`) | security-gate (+ commit/tracking modules) |
| Data-boundary / scrub | `import-into-repo`, `eval-egress` | `fixture`; never a ticket | pii-scrub |
| Other | `obs-emit`, `eval-run` | as defined per subsystem | obs / eval runner (not floors) |

### 2.7 Contract versioning

- **Semver on `contract_version`:** MAJOR = breaking envelope/field change; MINOR = additive optional field; PATCH = clarification.
- The core declares the highest MAJOR it implements. An event whose MAJOR exceeds that is refused safely: `block` on enforcement types, `no-op` on `obs-emit`.
- **Additive-only within a MAJOR.** Missing optional fields are treated as absent, never inferred. A field's meaning is frozen for the life of a MAJOR; renames are a MAJOR bump.
- Adapters advertise `harness.adapter_version` for audit; the core keys compatibility off `contract_version` only.

### 2.8 The enforcement floor — git/CI universal backstop

- The git layer (`pre-commit`/`pre-push`) and CI both invoke the **same core** on enforcement event types. This is the universal hard backstop, because every harness commits to git.
- **Enforcement never falls below "blocked at the git boundary."** In-editor interception is *additive* — it catches violations earlier and more pleasantly — but is never the only line. A harness with no interception event loses earliness, not enforcement.
- **Fail-closed modules cannot be softened by an adapter or by `requested_mode`.** The floors are code; the worst an adapter can do is fail to surface a warning in-editor.
- **CI is the third floor.** Even if local git hooks are bypassed, the CI invocation of the core on the PR/merge event re-runs the fail-closed modules. The git/CI adapters derive the enforcement `event_type` from the actual git operation and never trust a stdin-supplied `event_type` for enforcement classification.

### 2.9 The adapter pattern

An adapter is a thin shim with exactly two jobs and **zero policy**:

- **In:** capture the harness's native event, map it onto the envelope, fill `harness.name` / `adapter_version` / the best honorable `requested_mode`, pipe the JSON to the core on stdin.
- **Out:** read the core's exit code (and optionally stdout) and translate it to the harness's native allow / warn / block.

The test for "is this really an adapter": deleting it and writing a new one for a different harness must lose **no** enforcement logic. If an adapter contains a policy check (`if ticket.is_sensitive: …`), that is a design defect — the logic belongs in the core. For any new harness the only net-new artifact is an event-mapping table; the core, all policy, all modules, and the git/CI floor are reused unchanged. If a harness exposes no interception event, enforcement degrades to the git/CI floor but never below it.

---

## 3. Consequences

- **One place to audit.** All policy lives in the core; a fail-closed guarantee is verified once, not per harness.
- **Cheap harness onboarding.** A new harness costs one event-mapping table plus reuse of the git/CI adapters; portability is demonstrable on paper before any harness-specific code is written.
- **Graceful degradation is a property, not a hope.** A weak harness with no in-editor hook still gets full enforcement at the git+CI floor and full observability via an invocation-complete callback.
- **Stateless and reproducible.** The core is a pure request/response over stdin/stdout plus recorded repo state it reads but (except the obs emitter) never writes; given an event and a repo commit, the decision is reproducible.
- **Bypass resistance is layered.** In-editor, local git hooks, and server-side CI are three tiers; only the CI tier is truly unbypassable, and the design leans on it as the final floor.
- **Small surface.** stdin/stdout+exit adds no new attack surface and no dependency; the core runs on a bare interpreter.

---

## 4. Alternatives considered

1. **Per-harness reimplementation of the guardrail logic (rejected).** Fastest to a single-harness demo, but duplicates policy, guarantees drift, and makes the fail-closed guarantee unverifiable across copies.
2. **A bespoke portability framework / plugin API (rejected).** More expressive than stdin/stdout+exit, but adds surface and a dependency for no gain; the minimal primitive is provably sufficient.
3. **In-editor enforcement only, no git/CI floor (rejected).** Cleaner UX, but harnesses with no interception event would have zero enforcement — the security gate would be advisory on exactly the harnesses that need it most.
4. **Exit code carries all information, no stdout JSON (rejected).** Simpler, but obs and audit need structured, correlatable output, and warn/annotate need a message channel. Two channels cost little and serve both machine and human.
5. **First-match module selection (rejected).** Bypassable: an event shaped like one floor but carrying an extra key can route around another floor. Replaced by "all matching floors, any-block-blocks."
