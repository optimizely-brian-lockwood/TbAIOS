"""security-gate module (HK2) -- contract-v1 immutable-floor, fail-closed.

Spec: hooks-obs-substrate ADR sec.2.1/2.3. Security-review conditions enforced:
sign-off record integrity (the machine-checkable half); independently
derived + reconciled sensitivity (no downward spoof); and the record schema.

WHAT THIS MODULE DECIDES: given a changeset + a ticket descriptor + an optional
sign-off record, decide ALLOW / BLOCK. A sensitive ticket may proceed only with
a valid, covering, current sign-off; anything ambiguous, malformed, or
uncovered on a sensitive path fails CLOSED (BLOCK).

GENERIC + CONFIG-DRIVEN (promotes to TbAIOS upstream): this module hardcodes NO
engagement-specific paths, filenames, ticket systems, or flags. The sensitivity
ruleset (path globs + content signals), the safe-path allow-list, the gate
event types, and the ambiguity flag ALL come from config (see
security_gate_config.sample.json). The code below is pure mechanism.

MECHANISM (here) vs CONFIG (supplied):
  * mechanism: glob matching, content-signal scanning, derive->reconcile (union,
    no downward spoof), ambiguity->sensitive, record schema validation, content-
    hash binding comparison, fail-closed decision, no-echo reporting.
  * config: which globs/signals map to which flags, which paths are safe, which
    event types are gate events, the name of the ambiguity flag.

OUT OF SCOPE this increment (activation / other modules -- clean seams only):
  * CI enforcement tier, CODEOWNERS + branch protection (the WHO-may-create-a-
    record half of F-2) -- DEFERRED to activation; this module verifies record
    CONTENT, not who committed it.
  * commit-block, atomic-tracking, clickup-gate, direct-to-main wiring (F-4).

NO-ECHO (cond 7 discipline, reused): results carry codes + sensitivity-flag
NAMES + counts only -- never raw changeset content, diffs, or file paths.
"""

import hashlib
import json
import re
from pathlib import Path

try:  # pragma: no cover - import shim
    from . import contract as C
    from . import pii_scrub
except ImportError:  # pragma: no cover - import shim
    import contract as C
    import pii_scrub


_RECORD_SCHEMA_PATH = Path(__file__).with_name("signoff-record.schema.json")


def _load_record_schema():
    with open(_RECORD_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


_RECORD_SCHEMA = _load_record_schema()


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
# A conservative, generic default so the registered gate is functional without
# an external config file. An engagement overrides this with its own config
# (load_config); nothing here is engagement-specific.
DEFAULT_CONFIG = {
    "gate_event_types": ["pre-pr", "feature-merge"],
    "ambiguous_flag": "sensitive",
    "safe_globs": ["docs/**", "**/*.md", "**/*.txt", "tests/**", "**/test_*.py"],
    "sensitivity_rules": [
        {"flag": "authn",
         "path_globs": ["**/auth/**", "**/*auth*", "**/*login*", "**/*session*",
                        "**/*password*", "**/*credential*", "**/*token*", "**/*oauth*"],
         "content_signals": ["password", "passwd", "oauth", "authenticate",
                             "authorization", "set_cookie", "jwt", "bearer",
                             "private_key", "client_secret"]},
        {"flag": "pii",
         "path_globs": ["**/*customer*", "**/*user*", "**/*profile*",
                        "**/*account*", "**/*email*", "**/*contact*"],
         "content_signals": ["email", "ssn", "social_security", "phone_number",
                             "date_of_birth", "first_name", "last_name",
                             "home_address"]},
        {"flag": "external-input",
         "path_globs": ["**/api/**", "**/handlers/**", "**/routes/**",
                        "**/controllers/**", "**/*webhook*", "**/*endpoint*"],
         "content_signals": ["request.args", "request.body", "req.body",
                             "input(", "sys.argv", "os.environ", "unmarshal",
                             "deserialize", "pickle.loads", "eval("]},
    ],
}


def load_config(path):
    """Load a config JSON file (engagement-supplied). Pure I/O; no defaults
    merged so a partial config is the engagement's explicit choice."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Glob matching (supports **, *, ?) -- mechanism
# --------------------------------------------------------------------------
_GLOB_CACHE = {}


def _glob_regex(glob):
    rx = _GLOB_CACHE.get(glob)
    if rx is not None:
        return rx
    parts, i, n = [], 0, len(glob)
    while i < n:
        if glob[i:i + 3] == "**/":
            parts.append("(?:.*/)?"); i += 3
        elif glob[i:i + 2] == "**":
            parts.append(".*"); i += 2
        elif glob[i] == "*":
            parts.append("[^/]*"); i += 1
        elif glob[i] == "?":
            parts.append("[^/]"); i += 1
        else:
            parts.append(re.escape(glob[i])); i += 1
    rx = re.compile("^" + "".join(parts) + "$")
    _GLOB_CACHE[glob] = rx
    return rx


def _matches_any(path, globs):
    norm = str(path).replace("\\", "/")
    return any(_glob_regex(g).search(norm) for g in (globs or []))


def _content_hit(content, signals):
    low = content.lower()
    return any(sig.lower() in low for sig in (signals or []))


def _content_usable(content):
    """True only if `content` is a non-empty, non-whitespace string. None, an
    empty string, and whitespace-only all mean 'not actually inspected /
    verified' and must fail closed on a sensitive path (SG-1, M-1)."""
    return isinstance(content, str) and content.strip() != ""


def _current_hash(entry):
    """Core-computed current-side hash of a changeset file's ACTUAL content.

    Never trusts an adapter-supplied `content_hash` for the current side (M-1):
    on a sensitive path the current hash must be derived from real, non-empty
    content so a post-review change is detectable and a content-less "trust me"
    hash cannot pass unreviewed. Returns None when there is no usable content
    (-> SENSITIVE_FILE_UNHASHABLE). The record's OWN reviewed-side content_hash
    is still honoured -- that is what was reviewed, compared against this."""
    content = entry.get("content")
    if _content_usable(content):
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    return None


# --------------------------------------------------------------------------
# Independent sensitivity derivation (F-3)
# --------------------------------------------------------------------------
class _Derived:
    def __init__(self, flags=None, ambiguous=False, sensitive_paths=None, error=None):
        self.flags = set(flags or ())
        self.ambiguous = ambiguous
        self.sensitive_paths = set(sensitive_paths or ())
        self.error = error


# Optional pii_scrub-backed derivation (config: use_pii_detectors). Maps the
# pii_scrub detector categories to security-gate sensitivity flags.
_PII_CATS = frozenset({"EMAIL", "CREDIT_CARD", "SSN", "PHONE"})
_SECRET_CATS = frozenset({"AWS_KEY", "API_KEY", "PRIVATE_KEY", "JWT",
                          "SECRET_HIGH_ENTROPY"})


def _detector_flags(content):
    """Reuse the pii_scrub detectors over file content to derive pii/authn from
    real PII/secret SHAPES a keyword list would miss (e.g. an actual email
    address vs the literal word 'email'). Fail-safe: over-flags on any error."""
    out = set()
    try:
        res = pii_scrub.evaluate({"fields": {"_": content}}, "egress-to-judge")
        for cat in res.categories:
            if cat in _PII_CATS:
                out.add("pii")
            elif cat in _SECRET_CATS:
                out.add("authn")
    except Exception:  # noqa: BLE001 -- detectors must never crash derivation
        out.add("pii")
    return out


def _derive(changeset, config):
    """Derive sensitivity flags from the changeset via the config ruleset.

    A file is sensitive if its path matches a rule glob OR (usable content) a
    content signal. Ambiguity -> sensitive: if a file's content is NOT usable
    (absent, empty, or whitespace-only -- i.e. never actually inspected) AND its
    path is neither a known-safe path nor a matched sensitive path, we cannot
    prove it safe, so it is treated as sensitive (fail-closed direction, SG-1).
    A missing/malformed changeset or file entry is itself ambiguous -> error.
    """
    files = changeset.get("files")
    if not isinstance(files, list) or not files:
        return _Derived(error="CHANGESET_MISSING")
    flags, sensitive_paths, ambiguous = set(), set(), False
    for f in files:
        if not isinstance(f, dict) or not f.get("path"):
            return _Derived(error="MALFORMED_FILE_ENTRY")
        path, content = f["path"], f.get("content")
        usable = _content_usable(content)   # SG-1: None/empty/whitespace all unusable
        file_flags = set()
        for rule in config.get("sensitivity_rules", []):
            if _matches_any(path, rule.get("path_globs")):
                file_flags.add(rule["flag"])
            if usable and _content_hit(content, rule.get("content_signals")):
                file_flags.add(rule["flag"])
        # Optional F-3 strengthening (config: use_pii_detectors) -- reuse the
        # pii_scrub detectors to catch real PII/secret SHAPES the keyword list
        # misses. Off by default; adds flags only (fail-safe direction).
        if usable and config.get("use_pii_detectors"):
            file_flags |= _detector_flags(content)
        if file_flags:
            flags |= file_flags
            sensitive_paths.add(path)
        elif not usable and not _matches_any(path, config.get("safe_globs")):
            # content NOT actually inspected (absent/empty/whitespace) AND path
            # not provably safe -> ambiguous -> sensitive (SG-1, fail-closed).
            ambiguous = True
            sensitive_paths.add(path)
        # usable content w/ no signal, or a known-safe path -> non-sensitive
    return _Derived(flags=flags, ambiguous=ambiguous, sensitive_paths=sensitive_paths)


# --------------------------------------------------------------------------
# Sign-off record verification (F-2 content half + sec.7 schema + F-9 binding)
# --------------------------------------------------------------------------
def _validate_record_schema(record):
    problems = []
    C._validate(record, _RECORD_SCHEMA, "", problems)
    return problems


def _check_binding(record, sensitive_paths, files_by_path):
    """Every sensitive file must be bound in the record with a matching current
    content hash. Unbound sensitive file -> unreviewed surface; hash mismatch ->
    approval drift (F-9). Either -> BLOCK."""
    bindings = {}
    for item in record.get("reviewed_artifact") or []:
        if isinstance(item, dict) and item.get("path"):
            bindings[str(item["path"]).replace("\\", "/")] = item.get("content_hash")
    for path in sensitive_paths:
        cur = _current_hash(files_by_path.get(path, {}))
        if cur is None:
            return False, "SENSITIVE_FILE_UNHASHABLE"
        key = str(path).replace("\\", "/")
        if key not in bindings:
            return False, "SENSITIVE_SURFACE_UNREVIEWED"
        if bindings[key] != cur:
            return False, "APPROVAL_DRIFT"
    return True, None


def _verify_signoff(record, ticket_id, required_flags, sensitive_paths, files_by_path):
    if not isinstance(record, dict):
        return False, "SIGNOFF_MISSING"
    if _validate_record_schema(record):
        return False, "SIGNOFF_MALFORMED"
    if record.get("ticket_id") != ticket_id:
        return False, "SIGNOFF_TICKET_MISMATCH"
    if record.get("verdict") != "APPROVED":
        return False, "SIGNOFF_NOT_APPROVED"
    if record.get("conditions_status") != "all-closed":
        return False, "SIGNOFF_CONDITIONS_OPEN"
    covered = set(record.get("sensitivity_flags_covered") or [])
    if not required_flags <= covered:
        return False, "SIGNOFF_FLAG_UNCOVERED"
    return _check_binding(record, sensitive_paths, files_by_path)


# --------------------------------------------------------------------------
# Result + decision
# --------------------------------------------------------------------------
class GateResult:
    """No-echo (cond 7): reasons carry codes + sensitivity-flag NAMES + counts
    only; never raw content, diffs, or file paths."""

    def __init__(self):
        self.blocked = False
        self.reasons = []
        self.required_flags = []

    def block(self, code, flags=None):
        self.blocked = True
        reason = {"code": code}
        if flags:
            reason["flags"] = list(flags)
        self.reasons.append(reason)
        return self

    def allow(self):
        return self

    @property
    def decision(self):
        return "block" if self.blocked else "allow"

    def reason_summary(self):
        return list(self.reasons)

    def annotations(self):
        if not self.blocked:
            return []
        codes = ", ".join(r["code"] for r in self.reasons)
        return [{"severity": "error",
                 "message": "security-gate blocked (%s); required flags: %s"
                            % (codes, ", ".join(self.required_flags) or "none")}]


def evaluate(payload, config=None):
    """Pure function: (payload + config) -> GateResult. Fail-closed on any error
    or ambiguity on a gate/sensitive path."""
    config = config if config is not None else DEFAULT_CONFIG
    result = GateResult()
    try:
        if not isinstance(payload, dict):
            return result.block("MALFORMED_PAYLOAD")

        ticket = payload.get("ticket")
        if not isinstance(ticket, dict) or not ticket.get("ticket_id"):
            # a gate event with no ticket descriptor cannot be verified -> block
            return result.block("TICKET_MISSING")
        ticket_id = ticket["ticket_id"]

        declared = ticket.get("sensitivity_flags", [])
        if not isinstance(declared, list):
            return result.block("DECLARED_FLAGS_MALFORMED")

        changeset = payload.get("changeset")
        if not isinstance(changeset, dict):
            return result.block("CHANGESET_MISSING")

        d = _derive(changeset, config)
        if d.error:
            return result.block(d.error)   # ambiguity / malformed -> block

        # Reconcile: union of derived + self-declared. Self-declaration may only
        # ADD flags, never remove a derived one (no downward spoof, F-3).
        required = set(d.flags) | set(declared)
        if d.ambiguous:
            required.add(config.get("ambiguous_flag", "sensitive"))
        result.required_flags = sorted(required)

        if not required:
            return result.allow()          # non-sensitive -> allow

        # Sensitive: require a valid, covering, current sign-off.
        record = payload.get("signoff_record")
        files_by_path = {
            f["path"]: f for f in changeset["files"]
            if isinstance(f, dict) and f.get("path")
        }
        ok, code = _verify_signoff(record, ticket_id, required,
                                   d.sensitive_paths, files_by_path)
        if ok:
            return result.allow()
        return result.block(code, flags=result.required_flags)
    except Exception:  # noqa: BLE001 -- any error on a gate path fails closed
        return result.block("GATE_ERROR")
