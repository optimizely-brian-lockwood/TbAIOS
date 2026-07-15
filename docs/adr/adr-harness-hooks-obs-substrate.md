# ADR — Shared Hooks + Observability Substrate

**Status:** Accepted (base-layer architecture)
**Scope:** The lifecycle-event modules that live *inside* the harness-agnostic core — the guardrail hooks, the fail-closed PII-scrub control, the security gate, the ClickUp-style write gate, and the metadata-only observability emitter.
**Depends on:** `adr-harness-portability-contract.md` (the `contract-v1` envelope, response protocol, precedence model, dispatch rule, and git/CI floor). This ADR designs the modules; it does not re-specify the contract.

---

## 1. Context

Lifecycle rules that would otherwise live as prose ("don't commit direct to a protected branch", "a sensitive change needs sign-off", "never log transcript content") need to become executable modules behind one contract. All of them share the same core dispatch, the same two-channel response, and the same precedence model. This ADR fixes the module taxonomy, the hardness posture of each class, and the two security-sensitive controls (PII-scrub and the observability emitter) whose guarantees must be structural rather than conventional.

Everything here ships as **mechanism**; each engagement declares its own **values** via config (protected branch names, tracking-file paths, sensitivity rulesets, sink paths, role enums). No engagement-specific path, filename, ticket system, or flag is hardcoded.

---

## 2. Decision

### 2.1 Module taxonomy and hardness posture

Modules are pure functions of `(payload + recorded repo state) → contract-v1 decision`. No module knows any harness; none writes repo state except the obs emitter (metadata only, gitignored, fail-open).

| Module | Hardness | Error posture | Rationale |
|---|---|---|---|
| `pii-scrub` | **immutable floor** (fail-closed always) | error → **block** | A warn is not a control for real data exposure. |
| `security-gate` | **immutable floor** (fail-closed) | error → **block** | A sensitive change proceeds only with valid sign-off; ambiguity is unsafe. |
| `clickup-gate` | **immutable floor** (default-deny) | error/ambiguity → **block** | Failure to *prove* a write is a read is treated as a write. |
| `commit-block` | warn-only → flip | error pre-flip → **warn** | Low-risk hook; do not spuriously block before the rule is proven. |
| `atomic-tracking` | warn-only → flip | error pre-flip → **warn** | Same. |
| `obs` emitter | **fails open** | error → no-op, write nothing | Must never block an invocation; content leak is prevented structurally instead. |

The split is deliberate: fail-closed for the controls that guard real exposure, fail-to-warn for the low-risk hooks that would otherwise produce a false-block storm before their rules have earned hardness, and fail-open for observability so it can never gate work.

### 2.2 The flip mechanism (warn-only → block)

- **Flip is a single recorded config value** the two warn-only modules read at evaluation time — one auditable action, not a code change. The core's `resolve_policy` reads a `flip_state` map: `<module> == "block"` post-flip, else warn.
- A flip is earned by evidence (a run of real events with zero false-positive blocks and at least one confirmed true-positive) or by a recorded backstop date, whichever comes first. The engagement owns the exact criterion and authority; the mechanism only reads the recorded state.
- **Silence defaults to secure:** the backstop is enforced in-code (the module reads the current date and hardens to block on/after the recorded date unless a recorded extension exists), so the flip cannot be forgotten.

### 2.3 security-gate — independently-derived sensitivity + content-hash-bound sign-off

The gate decides ALLOW/BLOCK for a gate event given a `changeset`, a `ticket` descriptor, and an optional sign-off record. A sensitive change proceeds only with a valid, covering, current sign-off; anything ambiguous, malformed, or uncovered on a sensitive path fails closed.

- **Independently-derived sensitivity (no downward spoof).** The gate derives sensitivity itself from a config ruleset (path globs + content signals, optionally strengthened by reusing the PII-scrub detectors to catch real PII/secret *shapes* a keyword list misses). It then reconciles with the ticket's self-declared flags as a **union** — self-declaration may only *add* flags, never remove a derived one.
- **Ambiguity → sensitive.** A file whose content was not actually inspected (absent/empty/whitespace) and whose path is not provably safe cannot be proven safe, so it is treated as sensitive.
- **Content-hash-bound sign-off.** Every sensitive file must be bound in the sign-off record by a content hash. The gate recomputes the current-side hash from the file's **actual** content (it never trusts an adapter-supplied hash for the current side) and compares it against the record's reviewed-side hash. An unbound sensitive file → unreviewed surface → block; a hash mismatch → approval drift → block. The record must also match the ticket, carry an `APPROVED` verdict with all conditions closed, cover every required flag, and pass a schema check — any failure → block.
- **Every gate event_type is a gate event.** A gate event carrying no gate-shaped payload (neither ticket nor changeset) → block. A data-boundary flag on a gate event_type is not honored and cannot route the event around the gate.

### 2.4 commit-block and atomic-tracking (config-driven, warn-only)

- **commit-block** warns/blocks a direct commit to a config-declared protected branch. Unconfigured → nothing protected → no-op (safe default). Branch matching is case-**sensitive** on every platform (git refs are canonically case-sensitive; platform-dependent case folding would be a portability defect).
- **atomic-tracking** asserts that a feature-merge changeset touched a config-declared tracking file **and** recorded an entry for the ticket in the same change. Not updated → hit (warn pre-flip / block post-flip). Ticket-id matching is word-boundary-anchored so one id is not matched inside a longer one. Unconfigured → no-op.

### 2.5 clickup-gate — default-deny write gate (generic mechanism)

- On the relevant enforcement event, every operation against the target service must be **provably an allowed read** (a read verb). A write verb, an unknown/missing verb, or a malformed op → block (default-deny; ambiguity → block). No ops → allow.
- Detection inspects **call shape** (the HTTP verb and target host substring), not a live network probe, so it is harness-agnostic. The target-host signal and allowed-read-verb list are config; a gate for a specific service inherently knows that service's host shape, which keeps a useful default without becoming engagement-specific.
- Because default-deny is the invariant, this is registered as an **immutable floor** — `requested_mode`/flip cannot soften it.

### 2.6 pii-scrub — fail-closed, two independent engines, high-precision + human recall

One control, reused wherever an artifact crosses a trust boundary — repo-in (`import-into-repo`) and repo→judge (`eval-egress`). Both leak paths use the same audited module.

**Detection contract — high-precision machine + human-ratification recall backstop:**

- The **machine** layer is high-precision, known-shape. It detects only well-defined PII *shapes* with a low false-block rate and hard-blocks on any hit. It deliberately does **not** chase every long digit run, high-entropy token, or cross-field reassembly — that path produces both leaks and an over-block storm.
- The **human** layer is the recall backstop: whole-artifact human ratification (already mandatory for eval fixtures) catches the shapes/encodings/cross-field splits the precision mandate skips. "Raw is never committed" bounds the residual.
- Machine must-detect shapes (hard block) include: email; Luhn-valid + issuer-prefixed card (after Unicode normalization); delimited and context-gated contiguous national-ID numbers; cloud access keys; known-vendor API-key prefixes; PEM private-key headers; JWTs; a high-entropy value only under a secret-labeled key; formatted/E.164 phone. Must-not-block values (passed byte-for-byte, never silently redacted): ISO-8601 datetimes, git SHAs (including the control's own hashes), semver, plain integers/config numbers, UUIDs.

**Two-stage, fail-closed, independent engines:**

```
  raw candidate → SCRUBBER (regex-substitution ruleset A) → cleaned copy
                → INDEPENDENT SCANNER (structural token/validator ruleset B,
                  its own checksum/entropy math, no shared pattern table)
     any must-detect hit by EITHER engine → BLOCK (non-zero exit)
         raw never written; cleaned copy NOT saved/graded; result carries
         neither cleaned nor raw content
     no hit → ALLOW → byte-for-byte copy lands in-repo / goes to judge
```

- **Independence is load-bearing.** The two engines share no detection ruleset or pattern state — each duplicates its detection math — so blinding one engine to a class cannot blind the other. The only shared code is a mandated pre-detection Unicode normalization step (NFKC + separator stripping), which is explicitly not a detection rule.
- **Any hit blocks — no warn.** A false-block on a genuinely clean artifact holds; human spot-check is the backup, never a bypass. Scanner error → block. Coverage is full-surface: filename, every nested field, the rubric, the judge payload, the commit message, and every dict key (a key can itself be PII) — each scalar leaf scanned as one unit. Cross-leaf reassembly is human recall, not machine-required.
- **No-echo:** reasons/annotations carry a fixed allow-list of surface names plus category+count only; no matched value or caller-supplied key is ever echoed.

### 2.7 Observability emitter — metadata-only by construction, error-path leak-free, fails open

The one module that *writes* on the hot path of every invocation, so it is the highest accidental-leak risk. Its content guarantee is structural.

- **Metadata-only by construction.** The record is *built* field-by-field from a closed allow-list of named scalars (event_id, ts, role, ticket_id, tokens{in,out}, latency_ms). The raw event/payload is never copied, serialized, or iterated — a content field (prompt/transcript/message) is structurally unreachable because no code reads it. Content cannot be persisted because there is no field to hold it, not because a filter chose to drop it.
- **Value validation.** Each allow-listed key is type/format/enum validated so it cannot become a free-text smuggle channel: `role` is a strict closed enum (no free-text/slug path — a slug is name-shaped PII); `ticket_id` a length-bounded id pattern or null; `event_id` a bounded id; `ts` ISO-8601/epoch; tokens/latency finite numeric ≥ 0. Anything that does not validate becomes **null**, never truncated free text (a truncated prompt is still a prompt).
- **Write-time key validator** (defense in depth): any record with an out-of-allow-list key is rejected, so a future accidental field addition fails loudly rather than leaking.
- **Error-path no-leak.** Any error is swallowed to a content-free marker; no event, payload, exception message, or stack trace is ever written or returned. There is no `dumps`/`repr`/`str` of the event on any path.
- **Fails open on availability.** An unavailable/raising sink is a no-op; emission never raises and never blocks. Availability fails open, content fails closed by construction — orthogonal axes, so there is no "preserve the raw data" branch to reach.
- **Gitignored local sink, no external egress.** Append-only to a gitignored path verifiably excluded from version control; no external telemetry path exists (that would be a new PII-egress surface requiring separate review). The library default sink is a no-op so no live log directory is created until activation wires a real file sink.

### 2.8 Config-driven throughout

The mechanism ships upstream; each engagement declares its own values. Config-supplied inputs include: protected branch patterns; tracking-file patterns; the sensitivity ruleset (path globs + content signals), safe-path allow-list, and ambiguity-flag name for the gate; the target-host signal and allowed-read verbs for the write gate; and the sink path, role enum, and ticket-id pattern for the emitter. Config bound to a module is bound at registration (trusted) and never read from the event payload.

---

## 3. Consequences

- **The controls that matter are structural, not conventional.** PII cannot leak through obs because no field holds it; a scrubber blind spot does not become a scanner blind spot because the engines are independent; a sensitive change cannot ship unreviewed because the gate derives sensitivity itself and binds sign-off to content hashes.
- **Low-risk hooks earn hardness with evidence.** The flip mechanism avoids a day-one false-block storm while guaranteeing the hooks harden (the backstop is in-code and cannot be forgotten).
- **One PII control, two consumers.** The scrub is built and reviewed once and consumed unchanged at both boundaries, so there is one audit surface, not two that can drift.
- **Fully portable and reusable.** Every module is a pure function behind the contract; each engagement supplies values via config with safe (no-op or fail-closed) defaults.
- **Observability is safe by default.** The emitter fails open on availability and closed on content, and writes nothing until a sink is explicitly wired.

---

## 4. Alternatives considered

1. **Uniform warn-only for the whole hook set (rejected).** Leaves the PII/authn gate advisory — a warn in a scrolling transcript is not a control for real exposure.
2. **Uniform fail-closed day one for every hook (rejected).** Produces a false-block storm on low-risk hooks before their rules are proven. The dual flip criterion earns hardness with evidence.
3. **Scrubber and scanner sharing detection rules (rejected).** A shared blind spot means the independent re-check catches nothing the scrubber missed — independence is the whole point.
4. **Obs record built by filtering the event down (rejected).** A filter is a convention that can regress; a closed allow-list built field-by-field makes content capture structurally impossible.
5. **Obs external telemetry (rejected / out of scope).** Would create a new PII-egress surface on the highest-risk module; local gitignored-only, and any external sink triggers a separate vendor/PII review.
6. **Chasing every high-entropy/long-digit token in pii-scrub (rejected).** Low precision — it both leaks and over-blocks (colliding with the control's own hash/commit fields). High-precision machine + human-recall backstop is the ratified split.
