"""H-OBS observability emitter (increment 5).

Writes METADATA-ONLY records for agent invocations to a gitignored local sink.
It is the single highest accidental-PII-leak risk in the program, so the
content guarantee is STRUCTURAL, not conventional:

  * METADATA-ONLY BY CONSTRUCTION (F-... / ADR 4.1). The record is BUILT
    field-by-field from a CLOSED allow-list of named scalars
    (event_id, ts, role, ticket_id, tokens{in,out}, latency_ms). The raw
    event/payload is NEVER copied, serialized, or iterated -- a content field
    (prompt/transcript/message) is structurally unreachable because no code
    reads it. A write-time key validator rejects any out-of-allow-list key
    (defence in depth against a future field addition).

  * VALUE VALIDATION (F-2). Every field is type/format/enum validated so an
    allow-listed key cannot be a free-text smuggle channel: role is a STRICT
    closed enum (no free-text/slug path); ticket_id a strict, length-bounded id
    pattern or null; event_id a bounded id; ts ISO-8601/epoch; tokens/latency
    finite numeric >= 0. Anything that does not validate becomes null -- never
    truncated free text (a truncated
    prompt is still a prompt).

  * ERROR PATH NO-LEAK (F-1, load-bearing). Emission is wrapped so ANY error is
    swallowed to a content-free marker ("OBS_EMIT_ERROR"). No event, payload,
    exception message, or stack trace is ever written to the sink or returned.
    There is NO dumps/repr/str of the event on any path.

  * FAILS OPEN ON AVAILABILITY (F-4). A sink that is unavailable/raising is a
    no-op: emit() never raises and never blocks. This is the ONE module that
    fails open (distinct from the fail-closed floors); it shares the F-1 error
    path so there is no "preserve the raw data" branch to reach.

Deterministic + testable: `ts` is taken from the event (payload.ts or the
envelope occurred_at) -- emit() never calls the clock.

Config-driven + generic (TbAIOS-promotable): sink path, role enum, and
ticket-id pattern come from config. The default role enum is the GENERIC
11-role dev-team, not any engagement's people.
"""

import json
import math
import os
import re

# The closed allow-list. The record has EXACTLY these top-level keys.
_ALLOWED_KEYS = ("event_id", "ts", "role", "ticket_id", "tokens", "latency_ms")
_ALLOWED_TOKEN_KEYS = ("in", "out")

# Maximum length for the bounded string metadata fields (event_id, ticket_id).
_MAX_ID_LEN = 64

_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")   # UUID or bounded slug
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$")


DEFAULT_OBS_CONFIG = {
    "event_types": ["obs-emit"],
    # Gitignored local sink (see scripts/harness/.gitignore). DevOps owns the
    # final path + retention at activation; nothing is written unless a real
    # FileSink is wired in (the library default sink is a no-op NullSink).
    "sink_path": "scripts/harness/.obs/obs-log.jsonl",
    # GENERIC TbAIOS dev-team roles (not engagement people). role must be one of
    # these (STRICT closed enum, F-OBS-1); anything else -> null. Add new roles
    # here -- the enum is extensible; there is no free-text/slug fallback.
    "role_enum": [
        "engineering-manager", "product-manager", "software-architect",
        "ux-designer", "tech-lead", "senior-developer", "developer",
        "qa-engineer", "code-reviewer", "security-engineer", "devops-engineer",
    ],
    # ticket_id must match this or be null (strict id, never free text).
    "ticket_id_pattern": r"^[A-Za-z]+-\d+$",
}


# --------------------------------------------------------------------------
# Sinks (injectable). Library default writes NOTHING (NullSink) so no live log
# directory is created; activation wires a FileSink; tests use ListSink.
# --------------------------------------------------------------------------
class NullSink:
    def write(self, record):
        return None


class ListSink:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


class FileSink:
    """Append-only JSONL to a gitignored path (activation sink)."""

    def __init__(self, path):
        self.path = path

    def write(self, record):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# Value validation (F-2). Invalid -> None (never truncated free text).
# --------------------------------------------------------------------------
def _valid_str(value, pattern, max_len=_MAX_ID_LEN):
    # OB-1: bound the length (a shape-valid but arbitrarily long id -> null).
    if not isinstance(value, str) or len(value) > max_len:
        return None
    return value if pattern.match(value) else None


def _valid_num(value):
    # OB-2: reject non-finite (inf/nan) so the record is always valid JSON.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return value
    return None


def _valid_ts(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return value
    if isinstance(value, str) and _ISO8601_RE.match(value):
        return value
    return None


def _valid_role(value, role_enum):
    # F-OBS-1: role is a STRICT closed enum (no free-text/slug)
    # path (a slug like 'john-smith' is name-shaped PII). New roles are added
    # via the config `role_enum` (extensible), never by relaxing to free text.
    return value if isinstance(value, str) and value in role_enum else None


# --------------------------------------------------------------------------
# Record construction -- metadata-only BY CONSTRUCTION.
# --------------------------------------------------------------------------
def _build_record(event, cfg):
    """Build the allow-listed record field-by-field from NAMED scalars. Never
    copies/serializes/iterates the event or payload -- content is unreachable."""
    payload = event.get("payload") if isinstance(event, dict) else None
    if not isinstance(payload, dict):
        payload = {}
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    role_enum = set(cfg.get("role_enum") or [])
    ticket_re = re.compile(cfg.get("ticket_id_pattern") or r"^[A-Za-z]+-\d+$")

    # ts: taken from the event (deterministic); prefer payload.ts, else envelope.
    ts_raw = payload.get("ts")
    if ts_raw is None and isinstance(event, dict):
        ts_raw = event.get("occurred_at")

    return {
        "event_id": _valid_str(event.get("event_id") if isinstance(event, dict) else None,
                               _EVENT_ID_RE),
        "ts": _valid_ts(ts_raw),
        "role": _valid_role(payload.get("role"), role_enum),
        "ticket_id": _valid_str(payload.get("ticket_id"), ticket_re),
        "tokens": {"in": _valid_num(tokens.get("in")),
                   "out": _valid_num(tokens.get("out"))},
        "latency_ms": _valid_num(payload.get("latency_ms")),
    }


def _keys_ok(record):
    """Write-time key allow-list (defence in depth): reject any out-of-allow-list
    key so a future field addition fails loudly rather than leaking."""
    if set(record.keys()) != set(_ALLOWED_KEYS):
        return False
    tokens = record.get("tokens")
    if not isinstance(tokens, dict) or set(tokens.keys()) - set(_ALLOWED_TOKEN_KEYS):
        return False
    return True


class ObsResult:
    """No content, ever. `written` is the (content-free) record or None;
    `error` is a content-free marker code or None."""

    def __init__(self):
        self.written = None
        self.error = None


def emit(event, config=None, sink=None):
    """Build + validate + write a metadata-only record. NEVER raises, NEVER
    blocks, NEVER writes content -- fails open on any error (F-1/F-4)."""
    result = ObsResult()
    try:
        cfg = config or DEFAULT_OBS_CONFIG
        record = _build_record(event, cfg)
        if not _keys_ok(record):               # defence in depth
            result.error = "OBS_SCHEMA_REJECT"  # content-free marker; no write
            return result
        (sink if sink is not None else NullSink()).write(record)
        result.written = record
        return result
    except Exception:   # noqa: BLE001 -- F-1: swallow to a content-free marker.
        # NOTHING about the event/payload/exception is referenced or written.
        result.written = None
        result.error = "OBS_EMIT_ERROR"
        return result
