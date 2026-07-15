"""H-HOOKS warn-only + default-deny modules (increment 4).

Three modules, all GENERIC + CONFIG-DRIVEN (no engagement specifics hardcoded --
protected branch names, tracking-file paths, and ClickUp identification all come
from config; this module is pure mechanism, promotable to TbAIOS):

  commit_block    - warn/block a direct commit to a config-declared protected
                    branch. Warn-only under the flip-state.
  atomic_tracking - on a feature-merge, assert the changeset touched a
                    config-declared tracking file AND recorded the ticket entry.
                    Warn-only under the flip-state.
  clickup_gate    - DEFAULT-DENY: any ClickUp op that
                    is not provably an allowed read (GET) blocks; ambiguity ->
                    block. An immutable floor (registered via the floor seam).

Each `*_evaluate(payload, config) -> HookResult` is a pure function; core.py
wraps it into a ModuleResult/ModuleSpec and applies flip-state/precedence.

No-echo discipline: reasons carry codes + non-sensitive context (branch name,
tracking status, HTTP verb) -- never fixture/PII content.
"""

import fnmatch
import re


class HookResult:
    def __init__(self, hit, reasons=None, annotations=None):
        self.hit = hit
        self.reasons = reasons or []
        self.annotations = annotations or []


def _warn_annotation(module, message):
    # severity 'warn' is advisory; the flip-state (resolved in core) decides
    # whether this surfaces as a warn or hardens to a block.
    return {"severity": "warn", "message": message, "module": module}


def _matches_any(path, patterns):
    # HK-5: use fnmatchcase (NOT fnmatch) so matching is deterministic and
    # case-SENSITIVE on every platform. fnmatch() applies os.path.normcase,
    # which lowercases on Windows -> platform-dependent (a portability defect
    # for a TbAIOS-promoted harness). Git branch/ref names and repo paths are
    # canonically case-sensitive on all hosts, so 'Main' != 'main' and
    # 'DOCS/X.MD' != 'docs/x.md'. Glob metacharacters (* ? [...]) are unchanged;
    # only the case-normalization is dropped.
    norm = str(path).replace("\\", "/")
    return any(fnmatch.fnmatchcase(norm, p) for p in (patterns or []))


# ==========================================================================
# commit-block (warn-only) -- config: protected_branches
# ==========================================================================
DEFAULT_COMMIT_BLOCK_CONFIG = {
    "event_types": ["pre-commit", "pre-push"],
    # Empty by default: unconfigured => nothing is protected => no-op (safe).
    # An engagement declares its own protected branches (see sample config).
    "protected_branches": [],
}


def _branch_of(payload):
    b = payload.get("branch") or payload.get("target_branch") or payload.get("ref")
    if isinstance(b, str) and b.startswith("refs/heads/"):
        b = b[len("refs/heads/"):]
    return b


def commit_block_evaluate(payload, config):
    cfg = config or {}
    protected = cfg.get("protected_branches") or []
    branch = _branch_of(payload or {})
    if branch is not None and _matches_any(branch, protected):
        return HookResult(
            hit=True,
            reasons=[{"code": "DIRECT_COMMIT_TO_PROTECTED", "branch": branch}],
            annotations=[_warn_annotation(
                "commit-block", "direct commit to protected branch '%s'" % branch)],
        )
    return HookResult(hit=False)


# ==========================================================================
# atomic-tracking (warn-only) -- config: tracking_file_patterns
# ==========================================================================
DEFAULT_ATOMIC_TRACKING_CONFIG = {
    "event_types": ["feature-merge"],
    # Empty by default: unconfigured => nothing to enforce => no-op (safe).
    # Each engagement declares its own tracking file(s) (see sample config);
    # NEVER hardcode a FEATURES.md / ACTIVE-WORK.md filename in the mechanism.
    "tracking_file_patterns": [],
}


def _token_present(ticket_id, content):
    """Word-boundary match so 'HN-2' does not match 'HN-21' (Security nit).
    Lookarounds (not \\b) so ids containing hyphens still bound correctly."""
    return re.search(r"(?<!\w)" + re.escape(ticket_id) + r"(?!\w)", content) is not None


def atomic_tracking_evaluate(payload, config):
    cfg = config or {}
    patterns = cfg.get("tracking_file_patterns") or []
    if not patterns:
        return HookResult(hit=False)   # unconfigured -> nothing to assert

    payload = payload or {}
    changeset = payload.get("changeset")
    if not isinstance(changeset, dict):     # defensive: malformed payload shape
        changeset = {}
    files = changeset.get("files")
    if not isinstance(files, list):
        files = []
    ticket = payload.get("ticket")
    ticket_id = ticket.get("ticket_id") if isinstance(ticket, dict) else None

    tracking_files = [f for f in files
                      if isinstance(f, dict) and f.get("path")
                      and _matches_any(f["path"], patterns)]
    if not tracking_files:
        return HookResult(
            hit=True,
            reasons=[{"code": "TRACKING_FILE_NOT_UPDATED"}],
            annotations=[_warn_annotation(
                "atomic-tracking",
                "feature-merge did not update the declared tracking file")],
        )
    if ticket_id and not any(_token_present(ticket_id, f.get("content") or "")
                             for f in tracking_files):
        return HookResult(
            hit=True,
            reasons=[{"code": "TRACKING_ENTRY_MISSING", "ticket_id": ticket_id}],
            annotations=[_warn_annotation(
                "atomic-tracking",
                "tracking file updated but has no entry for ticket '%s'" % ticket_id)],
        )
    return HookResult(hit=False)


# ==========================================================================
# clickup-gate (DEFAULT-DENY floor) -- config: allowed_read_verbs, targets
# ==========================================================================
DEFAULT_CLICKUP_CONFIG = {
    "event_types": ["pre-pr"],
    "allowed_read_verbs": ["GET"],   # the ONLY provably-safe ClickUp op class
    # SAFE DEFAULT (HK-1): a *ClickUp* gate inherently knows ClickUp's API host,
    # exactly as a PII scanner knows an email's shape -- this is NOT
    # engagement-specific hardcoding, it stays generic for TbAIOS. The substring
    # "clickup.com" identifies any ClickUp host (api.clickup.com, app.clickup.com,
    # *.clickup.com), so a write reported via `payload.calls` is caught out of
    # the box with no config. The read-only-scoped ClickUp CREDENTIAL remains the
    # activation backstop (Security C-7); the library default no longer fails open.
    "targets": ["clickup.com"],
}


def _is_clickup_target(target, targets):
    # HK-4: hostnames are case-insensitive (RFC 3986). Normalize BOTH the op's
    # target and each configured signal to lowercase before the substring match,
    # mirroring the verb-side normalization -- so API.CLICKUP.COM / Api.Clickup.Com
    # are identified as ClickUp. A genuine non-ClickUp host (no "clickup.com"
    # substring) is still not matched, so this does not over-broaden.
    t = str(target or "").lower()
    return any(str(sig).lower() in t for sig in (targets or []))


def _clickup_ops(payload, cfg):
    """The ClickUp operations to police -- from BOTH sources, combined (HK-1):
      * adapter-pre-extracted `payload.clickup_ops` (all policed), AND
      * generic `payload.calls` entries identified as ClickUp by `targets`.
    An explicitly-empty `clickup_ops: []` means 'none pre-extracted', NOT 'skip
    the calls check' -- it must never suppress inspection of `calls`."""
    targets = cfg.get("targets") or []
    ops = list(payload.get("clickup_ops") or [])
    ops += [c for c in (payload.get("calls") or [])
            if isinstance(c, dict) and _is_clickup_target(c.get("target"), targets)]
    return ops


def clickup_gate_evaluate(payload, config):
    """DEFAULT-DENY: every ClickUp op must be provably an allowed read (GET);
    a write verb, an unknown/missing verb, or a malformed op -> BLOCK (ambiguity
    -> block). No ClickUp ops -> allow (no write intent)."""
    cfg = config or {}
    allowed = {str(v).upper() for v in (cfg.get("allowed_read_verbs") or ["GET"])}
    payload = payload or {}
    blocked = []
    for op in _clickup_ops(payload, cfg):
        if not isinstance(op, dict):
            blocked.append("MALFORMED")
            continue
        verb = str(op.get("verb") or "").upper()
        if verb not in allowed:      # missing/unknown/write -> deny
            blocked.append(verb or "UNKNOWN")
    if blocked:
        return HookResult(
            hit=True,
            reasons=[{"code": "CLICKUP_WRITE_DENIED", "verbs": sorted(set(blocked))}],
            annotations=[{"severity": "error", "module": "clickup-gate",
                          "message": "default-deny: non-read ClickUp op(s) blocked"}],
        )
    return HookResult(hit=False)
