"""contract-v1 core: dispatch/runner + policy precedence resolution (F1).

Reads one contract-v1 event, validates the envelope, resolves the module,
runs it, resolves the final decision by the ADR precedence order, and returns
the two-channel response (structured stdout + human stderr + exit code).

Harness-agnostic: this module imports no harness. A per-harness adapter (added
in a LATER, separate activation step -- not here) is the only thing that knows
Claude/Codex/git/CI.

Precedence order for the final decision on a module HIT
(portability ADR sec.2.2):

    1. IMMUTABLE MODULE FLOOR   (code, not config)  -- fail-closed modules
       (security-gate, pii-scrub) resolve to `block` on a hit and NO
       requested_mode / flip state can soften them.
    2. RECORDED FLIP STATE      (config)            -- warn-only modules read a
       recorded value: pre-flip -> warn, post-flip -> block.
    3. ADAPTER requested_mode   (hint)              -- may only narrow toward
       `warn` for NON-floor modules.

LIBRARY-ONLY: `main()` exists for future adapters to call, but nothing wires it
to a live hook / git / CI / settings.json in this increment.
"""

import sys

# Support both package import and direct-on-path import (tests / future adapter).
try:  # pragma: no cover - import shim
    from . import contract as C
    from . import pii_scrub
    from . import security_gate
    from . import hooks
    from . import obs
except ImportError:  # pragma: no cover - import shim
    import contract as C
    import pii_scrub
    import security_gate
    import hooks
    import obs


# --------------------------------------------------------------------------
# Module model
# --------------------------------------------------------------------------

class ModuleResult:
    """What a module handler returns to the policy resolver.

    `hit` True  -> the module found something actionable; policy decides warn
                   vs block (or block-always for a floor module).
    `hit` False -> `base_decision` is returned as-is (allow / no-op / not-graded).
    """

    def __init__(self, hit, module, base_decision=C.DECISION_ALLOW,
                 reasons=None, annotations=None):
        self.hit = hit
        self.module = module
        self.base_decision = base_decision
        self.reasons = reasons or []
        self.annotations = annotations or []


class ModuleSpec:
    """Registration record for a core module.

    `immutable_floor` True marks a fail-closed module whose hit ALWAYS resolves
    to block -- this is the code-level floor (precedence #1).
    `matches(event)` selects the module for an event.
    """

    def __init__(self, name, matches, handler, immutable_floor=False, obs=False):
        self.name = name
        self.matches = matches
        self.handler = handler
        self.immutable_floor = immutable_floor
        self.obs = obs


# --------------------------------------------------------------------------
# pii-scrub module -- claims DATA-BOUNDARY event types only
# --------------------------------------------------------------------------
# Data-boundary flows are FIRST-CLASS event types,
# not a bare `payload.boundary` riding on a gate event. `boundary` is honored
# ONLY here. This is what decouples SG-3 from QA-9 (a scrub no longer travels on
# a gate event_type). The event_type IS the boundary:
_DATA_BOUNDARY_EVENTS = {
    "import-into-repo": "import-into-repo",   # source repo -> this repo
    "eval-egress": "egress-to-judge",         # this repo -> LM judge
}


def _pii_scrub_matches(event):
    """pii-scrub claims ONLY data-boundary event types. A `boundary` key on a
    gate (or any other) event_type is a category error and is NOT honored here
    -- it cannot route a payload around the security-gate (SG-3)."""
    return event.get("event_type") in _DATA_BOUNDARY_EVENTS


def _pii_scrub_handler(event):
    payload = event.get("payload") or {}
    boundary = _DATA_BOUNDARY_EVENTS[event["event_type"]]   # from event_type, not payload
    # The fixture is the structured full-surface artifact; fall back to the
    # whole payload (minus the vestigial `boundary` key) if none given.
    fixture = payload.get("fixture")
    if fixture is None:
        fixture = {k: v for k, v in payload.items() if k != "boundary"}

    result = pii_scrub.evaluate(fixture, boundary)
    if result.blocked:
        return ModuleResult(
            hit=True,
            module="pii-scrub",
            reasons=result.reason_summary(),      # categories/counts only
            annotations=result.annotations(),
        )
    return ModuleResult(hit=False, module="pii-scrub", base_decision=C.DECISION_ALLOW)


PII_SCRUB_SPEC = ModuleSpec(
    name="pii-scrub",
    matches=_pii_scrub_matches,
    handler=_pii_scrub_handler,
    immutable_floor=True,
)

# --------------------------------------------------------------------------
# security-gate module (HK2) -- immutable floor, fail-closed, config-driven
# --------------------------------------------------------------------------
# Config is bound at registration (repo-side/trusted), NEVER read from the event
# payload -- otherwise an attacker could supply a permissive config to soften
# the gate. Tests build a spec with their own config via make_security_gate_spec.

def make_security_gate_spec(config):
    """Build a security-gate ModuleSpec bound to a trusted config."""
    gate_types = tuple(config.get("gate_event_types") or ("pre-pr", "feature-merge"))

    def matches(event):
        # SG-3 CLOSED (security ruling: option b):
        # EVERY gate event_type is a security-gate event, period. A gate event
        # carrying no gate-shaped payload (neither ticket nor changeset) is a
        # malformed gate event and BLOCKS (security_gate.evaluate -> TICKET_MISSING;
        # ambiguity -> block). This is safe for QA-9 ONLY because scrub/eval
        # flows now travel on DISJOINT data-boundary event types (sec.6.1), so a
        # scrub no longer arrives as a gate event. `boundary` is not honored on a
        # gate event_type, so it cannot route a gate event around the gate.
        return event.get("event_type") in gate_types

    def handler(event):
        res = security_gate.evaluate(event.get("payload") or {}, config)
        if res.blocked:
            return ModuleResult(
                hit=True, module="security-gate",
                reasons=res.reason_summary(),      # codes + flag names only
                annotations=res.annotations(),
            )
        return ModuleResult(hit=False, module="security-gate",
                            base_decision=C.DECISION_ALLOW)

    return ModuleSpec("security-gate", matches, handler, immutable_floor=True)


SECURITY_GATE_SPEC = make_security_gate_spec(security_gate.DEFAULT_CONFIG)


# --------------------------------------------------------------------------
# H-HOOKS modules (increment 4) -- config-bound at registration (trusted),
# never from the event payload. Tests build specs with their own config.
# --------------------------------------------------------------------------

def _hook_spec(name, config, evaluate, immutable_floor, default_types):
    gate_types = tuple(config.get("event_types") or default_types)

    def matches(event):
        return event.get("event_type") in gate_types

    def handler(event):
        res = evaluate(event.get("payload") or {}, config)
        return ModuleResult(hit=res.hit, module=name,
                            reasons=res.reasons, annotations=res.annotations,
                            base_decision=C.DECISION_ALLOW)

    return ModuleSpec(name, matches, handler, immutable_floor=immutable_floor)


def make_commit_block_spec(config):
    return _hook_spec("commit-block", config, hooks.commit_block_evaluate,
                      immutable_floor=False, default_types=("pre-commit", "pre-push"))


def make_atomic_tracking_spec(config):
    return _hook_spec("atomic-tracking", config, hooks.atomic_tracking_evaluate,
                      immutable_floor=False, default_types=("feature-merge",))


def make_clickup_gate_spec(config):
    # DEFAULT-DENY invariant -> immutable floor (requested_mode/flip cannot soften).
    return _hook_spec("clickup-gate", config, hooks.clickup_gate_evaluate,
                      immutable_floor=True, default_types=("pre-pr",))


COMMIT_BLOCK_SPEC = make_commit_block_spec(hooks.DEFAULT_COMMIT_BLOCK_CONFIG)
ATOMIC_TRACKING_SPEC = make_atomic_tracking_spec(hooks.DEFAULT_ATOMIC_TRACKING_CONFIG)
CLICKUP_GATE_SPEC = make_clickup_gate_spec(hooks.DEFAULT_CLICKUP_CONFIG)


# --------------------------------------------------------------------------
# H-OBS emitter (increment 5) -- NON-floor, side-effect, FAILS OPEN.
# --------------------------------------------------------------------------
def make_obs_spec(config, sink=None):
    """Build the obs emitter spec. `sink` defaults to obs.NullSink (library-safe:
    no live log directory is created); activation wires an obs.FileSink; tests
    inject obs.ListSink. The handler NEVER hits (it observes, never gates) and
    obs.emit NEVER raises -- so obs composes as no-contribution (allow/no-op)
    and can never affect a floor's block."""
    ev = tuple(config.get("event_types") or ("obs-emit",))

    def matches(event):
        return event.get("event_type") in ev

    def handler(event):
        obs.emit(event, config, sink=sink)   # side effect only; never raises
        return ModuleResult(hit=False, module="obs", base_decision=C.DECISION_NOOP)

    return ModuleSpec("obs", matches, handler, immutable_floor=False, obs=True)


# Library default: NullSink (no disk write). Activation registers with a FileSink.
OBS_SPEC = make_obs_spec(obs.DEFAULT_OBS_CONFIG)

# Default registry. Registry ORDER does not determine whether a module runs:
# dispatch evaluates ALL matching modules and COMPOSES their decisions (C-6;
# floors "all floors, any-block-blocks"; non-floor warns surfaced). Order only
# affects the reported module string when several modules contribute.
#
# --- REGISTRATION SEAM -------------------------------------------------------
# Wired: pii-scrub (HK1), security-gate (HK2), clickup-gate + commit-block +
# atomic-tracking (HK, this increment). Remaining: obs.emit registers
# here the same way (immutable_floor / non-floor as appropriate).
DEFAULT_REGISTRY = [
    PII_SCRUB_SPEC,            # floor
    SECURITY_GATE_SPEC,        # floor
    CLICKUP_GATE_SPEC,         # floor (default-deny)
    COMMIT_BLOCK_SPEC,         # non-floor, warn-only + flip
    ATOMIC_TRACKING_SPEC,      # non-floor, warn-only + flip
    OBS_SPEC,                  # non-floor, side-effect emitter, FAILS OPEN
]


# --------------------------------------------------------------------------
# Dispatch + policy resolution
# --------------------------------------------------------------------------

def resolve_policy(spec, result, flip_state, requested_mode):
    """Resolve the final decision string for a NON-FLOOR module.

    (Floors do not pass through here: a floor hit is unconditionally BLOCK,
    resolved directly in dispatch -- see the module-selection note. This
    function only decides warn vs block for warn-only/flip modules.)
    """
    if not result.hit:
        return result.base_decision

    # Immutable floor would be block, but floors never reach here.
    if spec.immutable_floor:
        return C.DECISION_BLOCK

    # Recorded flip state (config): pre-flip warn, post-flip block.
    flipped = (flip_state or {}).get(spec.name) == "block"
    hardened = C.DECISION_BLOCK if flipped else C.DECISION_WARN

    # Adapter requested_mode may only narrow toward warn (non-floor only).
    if requested_mode == "warn" and hardened == C.DECISION_BLOCK:
        return C.DECISION_WARN
    return hardened


# --- MODULE SELECTION SEMANTICS (refines portability ADR sec.2.2; SG-2, C-6) --
# COMPOSITION: dispatch evaluates ALL matching modules -- every floor AND every
# non-floor -- and COMPOSES their decisions. It never short-circuits after a
# floor, so a co-matching warn-only module is never silently dropped (C-6).
#
#   * IMMUTABLE FLOORS ("all floors, any-block-blocks"): every matching floor
#     runs; a floor hit is unconditionally BLOCK (no requested_mode / flip_state
#     can soften it). Floors are non-bypassable: a payload matching two floors
#     must satisfy BOTH.
#   * NON-FLOOR modules: every matching one runs; resolve_policy decides warn vs
#     block (flip_state, requested_mode). Its output is COMPOSED in even when a
#     floor also matched.
#
# Compose to the strongest outcome: any BLOCK (floor or non-floor) -> block;
# else any WARN -> warn (surfaced, exit 0); else allow. Reasons/annotations from
# EVERY contributing module are aggregated, so a warn is recorded even under a
# floor block.

def dispatch(event, registry=None, flip_state=None):
    """Validate + route a parsed event to a COMPOSED Decision. Assumes
    envelope-valid.

    Callers that read untrusted stdin should use `run()`, which wraps this with
    the fail-closed/no-op error posture. `dispatch` validates the envelope too
    (defence in depth) and lets contract errors propagate.
    """
    registry = DEFAULT_REGISTRY if registry is None else registry
    C.validate_envelope(event)

    event_type = event["event_type"]
    event_id = event.get("event_id")
    requested_mode = event.get("requested_mode")

    floors = [s for s in registry if s.immutable_floor and s.matches(event)]
    nonfloors = [s for s in registry if not s.immutable_floor and s.matches(event)]

    if not floors and not nonfloors:
        # Nothing claims the event: block on enforcement, no-op on obs.
        if event_type == "obs-emit":
            return C.Decision(C.DECISION_NOOP, "core.unhandled", event_id=event_id)
        return C.Decision(
            C.DECISION_BLOCK, "core.unhandled",
            reasons=[{"code": "UNHANDLED_EVENT_TYPE"}], event_id=event_id,
        )

    reasons, annotations = [], []
    block_modules, warn_modules, matched_modules = [], [], []

    # ALL matching floors: any hit -> block (unconditional). A floor handler
    # that RAISES fails CLOSED -> block (ADR sec.2.1 posture, HK-2/C-8). The
    # exception is contained per-module so co-matching modules still aggregate
    # and dispatch() never propagates.
    for spec in floors:
        matched_modules.append(spec.name)
        try:
            res = spec.handler(event)
        except Exception:  # noqa: BLE001 -- floor error -> fail-closed block
            block_modules.append(spec.name)
            reasons.append({"code": "MODULE_ERROR", "module": spec.name})
            annotations.append({"severity": "error", "module": spec.name,
                                "message": "floor handler error -> fail-closed block"})
            continue
        if res.hit:
            block_modules.append(res.module)
            reasons.extend(res.reasons)
            annotations.extend(res.annotations)

    # ALL matching non-floor modules, COMPOSED. A warn is surfaced even when a
    # floor matched/allowed -- never silently dropped (C-6). A non-floor handler
    # that RAISES fails to WARN pre-flip / block post-flip via its flip-state
    # (ADR sec.2.1 posture, HK-2) -- NOT an event-level hard block.
    for spec in nonfloors:
        matched_modules.append(spec.name)
        try:
            res = spec.handler(event)
        except Exception:  # noqa: BLE001 -- non-floor error posture
            if getattr(spec, "obs", False):
                # obs FAILS OPEN: a crash is a no-op, never a
                # warn/block -- distinct from the enforcement fail-to-warn below.
                continue
            res = ModuleResult(   # warn-only enforcement -> fail-to-warn/flip
                hit=True, module=spec.name,
                reasons=[{"code": "MODULE_ERROR", "module": spec.name}],
                annotations=[{"severity": "warn", "module": spec.name,
                              "message": "handler error -> fail-to-warn (flip-state governs)"}])
        if not res.hit:
            continue
        decision = resolve_policy(spec, res, flip_state, requested_mode)
        if decision == C.DECISION_BLOCK:
            block_modules.append(res.module)
        elif decision == C.DECISION_WARN:
            warn_modules.append(res.module)
        reasons.extend(res.reasons)
        annotations.extend(res.annotations)

    if block_modules:
        return C.Decision(C.DECISION_BLOCK, "+".join(block_modules),
                          reasons=reasons, annotations=annotations, event_id=event_id)
    if warn_modules:
        return C.Decision(C.DECISION_WARN, "+".join(warn_modules),
                          reasons=reasons, annotations=annotations, event_id=event_id)
    return C.Decision(C.DECISION_ALLOW, "+".join(matched_modules) or "core",
                      reasons=reasons, annotations=annotations, event_id=event_id)


# --------------------------------------------------------------------------
# Runner: raw stdin -> (stdout, stderr, exit_code). Never raises.
# --------------------------------------------------------------------------

def _refuse_safely(event, code, event_id=None):
    """Enforcement -> block; obs-emit -> no-op. Ambiguity is unsafe on a gate."""
    event_type = (event or {}).get("event_type")
    if event_type == "obs-emit":
        return C.Decision(C.DECISION_NOOP, "core.refuse", event_id=event_id)
    return C.Decision(
        C.DECISION_BLOCK, "core.refuse",
        reasons=[{"code": code}], event_id=event_id,
    )


def run(raw, registry=None, flip_state=None):
    """Full protocol. Returns (stdout_str, stderr_str, exit_code). Never raises."""
    try:
        event = C.load_event(raw)
    except C.MalformedEventError:
        # Cannot read event_type from unparseable JSON -> default to block
        # (ambiguity is unsafe on a gate; a well-formed obs adapter never hits
        # this). ADR failure table: malformed enforcement -> block.
        dec = C.Decision(C.DECISION_BLOCK, "core.malformed",
                         reasons=[{"code": "MALFORMED_EVENT"}])
        return dec.to_stdout(), dec.human_message(), dec.exit_code

    event_id = event.get("event_id")
    try:
        # dispatch() validates the envelope (which loads the schema file) and
        # runs the module. Any failure here -- contract error OR an infra error
        # such as the schema file being unreadable -- must resolve to a
        # fail-closed decision, never propagate (ADR failure table: "core
        # crashes mid-eval -> block"; QA-2).
        dec = dispatch(event, registry=registry, flip_state=flip_state)
    except C.UnsupportedContractError:
        dec = _refuse_safely(event, "UNSUPPORTED_CONTRACT_MAJOR", event_id)
    except C.EnvelopeValidationError:
        dec = _refuse_safely(event, "ENVELOPE_INVALID", event_id)
    except Exception:  # noqa: BLE001 -- infra/core error -> fail-closed BLOCK
        dec = _refuse_safely(event, "CORE_ERROR", event_id)
    return dec.to_stdout(), dec.human_message(), dec.exit_code


def main(argv=None):  # pragma: no cover - CLI entry, not wired live this increment
    raw = sys.stdin.read()
    out, err, code = run(raw)
    if out:
        sys.stdout.write(out + "\n")
    if err:
        sys.stderr.write(err + "\n")
    sys.exit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
