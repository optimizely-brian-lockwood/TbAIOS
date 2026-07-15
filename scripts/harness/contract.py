"""contract-v1 core primitives: event envelope, validation, response protocol.

Harness-agnostic by construction. Nothing in this module imports, names, or
branches on a specific harness (Claude/Codex/git/CI). It reads a contract-v1
event (a dict parsed from stdin JSON), validates it against the checked-in
`hook-event.schema.json`, and produces a contract-v1 Decision that carries the
two-channel response protocol (exit code + structured stdout + human stderr).

Spec: `docs/dev-team/architecture/2026-07-13-harness-portability-contract-adr.md`
      sections 2.1 (envelope), 2.2 (response protocol), 6 (versioning).

Implementation note: to keep the core dependency-free (the repo runs bare
`python`), envelope validation uses a small stdlib validator over the JSON
Schema file rather than a third-party `jsonschema` package. The schema file is
still the single source of truth; this validator implements the subset of
draft-07 the envelope uses (type / required / properties / enum /
additionalProperties / pattern / nested objects).
"""

import json
import re
from pathlib import Path

# --------------------------------------------------------------------------
# Contract constants
# --------------------------------------------------------------------------

CONTRACT_VERSION = "1.0"          # the version this core emits on responses
SUPPORTED_MAJOR = 1               # highest contract MAJOR this core implements

# Exit-code semantics are CONTRACTUAL (portability ADR sec.2.2): only the
# 0-vs-nonzero distinction is fixed. 0 = allow (incl. warn); non-zero = block.
EXIT_ALLOW = 0
EXIT_BLOCK = 1

# Decision vocabulary (portability ADR sec.2.2 stdout schema).
DECISION_ALLOW = "allow"
DECISION_WARN = "warn"
DECISION_BLOCK = "block"
DECISION_NOOP = "no-op"
DECISION_NOT_GRADED = "not-graded"

# Which decisions let the action proceed (exit 0).
_ALLOWING_DECISIONS = frozenset(
    {DECISION_ALLOW, DECISION_WARN, DECISION_NOOP, DECISION_NOT_GRADED}
)

REQUESTED_MODES = frozenset({"warn", "block", "annotate"})

SCHEMA_PATH = Path(__file__).with_name("hook-event.schema.json")


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class ContractError(Exception):
    """Base for all contract-v1 envelope problems."""


class MalformedEventError(ContractError):
    """stdin content was not valid JSON, or not a JSON object."""


class EnvelopeValidationError(ContractError):
    """Envelope failed schema validation. Carries a list of problem strings."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class UnsupportedContractError(ContractError):
    """Event's contract MAJOR exceeds what this core implements."""

    def __init__(self, major):
        self.major = major
        super().__init__(
            "contract major %r exceeds supported major %d" % (major, SUPPORTED_MAJOR)
        )


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def load_event(raw):
    """Parse raw stdin bytes/str into an event dict. Raise MalformedEventError."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if raw is None:
        raise MalformedEventError("no stdin content")
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MalformedEventError("invalid JSON: %s" % exc)
    if not isinstance(obj, dict):
        raise MalformedEventError("event root is not a JSON object")
    return obj


def contract_major(version):
    """Return the integer MAJOR of a semver string, or raise EnvelopeValidationError."""
    try:
        return int(str(version).split(".")[0])
    except (ValueError, AttributeError, IndexError):
        raise EnvelopeValidationError(["contract_version is not semver: %r" % version])


# --------------------------------------------------------------------------
# Minimal JSON-Schema (draft-07 subset) validator
# --------------------------------------------------------------------------

_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, json_type):
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = _JSON_TYPES.get(json_type)
    if py is None:
        return True  # unknown type keyword -> don't fail on it
    if json_type == "object":
        return isinstance(value, dict)
    if json_type == "boolean":
        return isinstance(value, bool)
    return isinstance(value, py)


def _validate(instance, schema, path, problems):
    """Recursively collect schema-violation strings into `problems`."""
    json_type = schema.get("type")
    if json_type is not None and not _type_ok(instance, json_type):
        problems.append("%s: expected %s, got %s" % (path or "<root>", json_type, type(instance).__name__))
        return  # can't meaningfully recurse on a type mismatch

    if "enum" in schema and instance not in schema["enum"]:
        problems.append("%s: value %r not in enum %r" % (path or "<root>", instance, schema["enum"]))

    if "pattern" in schema and isinstance(instance, str):
        if re.search(schema["pattern"], instance) is None:
            problems.append("%s: %r does not match pattern %s" % (path or "<root>", instance, schema["pattern"]))

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                problems.append("%s: missing required field %r" % (path or "<root>", req))
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    problems.append("%s: unexpected field %r" % (path or "<root>", key))
        for key, subschema in props.items():
            if key in instance:
                _validate(instance[key], subschema, "%s.%s" % (path, key) if path else key, problems)

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            _validate(item, schema["items"], "%s[%d]" % (path, i), problems)


def _load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_envelope(event, schema=None):
    """Validate an event dict against the contract-v1 envelope schema.

    Raises EnvelopeValidationError (bad shape) or UnsupportedContractError
    (contract MAJOR too new). Returns the event unchanged on success.
    """
    schema = schema if schema is not None else _load_schema()
    problems = []
    _validate(event, schema, "", problems)
    if problems:
        raise EnvelopeValidationError(problems)

    # Version gate: refuse a MAJOR we do not implement (ADR sec.6).
    major = contract_major(event["contract_version"])
    if major > SUPPORTED_MAJOR:
        raise UnsupportedContractError(major)
    return event


# --------------------------------------------------------------------------
# Response protocol
# --------------------------------------------------------------------------

class Decision:
    """A contract-v1 decision: the machine-readable stdout object + exit code.

    The human-readable stderr message is derived from the same content, so a
    warn is visible in a scrolling transcript even if the adapter discards
    stdout (portability ADR sec.2.2, channels 2 and 3).

    Invariant (no-PII-echo): `reasons` and `annotations` carry
    hit CATEGORIES / COUNTS only. Callers must never place a matched PII
    substring into a reason/annotation; this object does not add content.
    """

    def __init__(self, decision, module, reasons=None, annotations=None,
                 event_id=None, contract_version=CONTRACT_VERSION):
        self.decision = decision
        self.module = module
        self.reasons = list(reasons) if reasons else []
        self.annotations = list(annotations) if annotations else []
        self.event_id = event_id
        self.contract_version = contract_version

    @property
    def exit_code(self):
        return EXIT_ALLOW if self.decision in _ALLOWING_DECISIONS else EXIT_BLOCK

    @property
    def blocks(self):
        return self.exit_code != EXIT_ALLOW

    def to_dict(self):
        return {
            "contract_version": self.contract_version,
            "event_id": self.event_id,
            "decision": self.decision,
            "module": self.module,
            "reasons": self.reasons,
            "annotations": self.annotations,
        }

    def to_stdout(self):
        return json.dumps(self.to_dict(), sort_keys=True)

    def human_message(self):
        head = "[%s] %s -> %s" % (self.module, self.event_id or "-", self.decision.upper())
        lines = [head]
        for r in self.reasons:
            code = r.get("code", "?")
            cat = r.get("category")
            cnt = r.get("count")
            extra = ""
            if cat is not None:
                extra = " category=%s" % cat
            if cnt is not None:
                extra += " count=%s" % cnt
            lines.append("  - %s%s" % (code, extra))
        for a in self.annotations:
            lines.append("  * [%s] %s" % (a.get("severity", "info"), a.get("message", "")))
        return "\n".join(lines)

    def __repr__(self):
        return "Decision(%s, module=%s, exit=%d)" % (self.decision, self.module, self.exit_code)
