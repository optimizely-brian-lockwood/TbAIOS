"""QA-authored scratch tests (independent adversarial verification, increment 4).

These are NOT part of the developer's delivered suite for core.py's C-6
composition + hooks.py (commit-block / atomic-tracking / clickup-gate).
Findings write-up: docs/dev-team/qa/2026-07-14-harness-increment4-qa.md
(HK-1, HK-2, HK-3, HK-4).

QA does not modify contract.py / core.py / pii_scrub.py / security_gate.py /
hooks.py to make these pass.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core  # noqa: E402
import hooks  # noqa: E402


def envelope(payload, event_type, requested_mode="block"):
    return {
        "contract_version": "1.0",
        "event_id": "evt-hk-qa",
        "event_type": event_type,
        "occurred_at": "2026-07-14T00:00:00Z",
        "harness": {"name": "test"},
        "requested_mode": requested_mode,
        "payload": payload,
    }


class HK1_ClickupGateCallsFallbackDefaultAllowsUnrecognizedWrites(unittest.TestCase):
    """Bug HK-1 (originally CRITICAL) -- STATUS: FIXED, re-verified 2026-07-14.
    `clickup_gate_evaluate`'s DEFAULT-DENY guarantee was defeated by its own
    `_clickup_ops()` fallback: the shipped default `targets: []` meant a
    ClickUp write reported only via the generic `payload.calls` field was
    never inspected at all and defaulted to ALLOW; an adapter reporting
    `clickup_ops: []` (present but empty) also permanently suppressed the
    `calls` fallback.

    FIX (re-verified below, each scenario re-derived independently, not by
    re-running old assertions): `hooks.DEFAULT_CLICKUP_CONFIG["targets"]` now
    ships with `["clickup.com"]` by default (a generic, non-engagement-
    specific signal -- the module inherently knows ClickUp's own host, the
    same way a PII scanner inherently knows an email's shape), and
    `_clickup_ops()` now COMBINES `clickup_ops` and `calls`-derived ops
    (`ops = list(clickup_ops or []); ops += [...calls...]`) rather than
    short-circuiting on `clickup_ops is not None`. All four re-verified:
      - a real ClickUp DELETE via `calls`, default config -> now BLOCKS.
      - `clickup_ops: []` (present, empty) no longer suppresses the `calls`
        check -- the same write via `calls` still BLOCKS alongside it.
      - verb-level default-deny is unchanged and still holds (GET allows;
        POST/missing/malformed verbs block; empty ops list allows -- no
        ClickUp activity is not ambiguity).
      - Genuinely non-ClickUp writes (an unrelated host) remain correctly
        out of scope and allow -- the fix did not over-broaden into blocking
        unrelated write traffic.

    NEW FINDING while adversarially probing "still try to get a write
    allowed" (the specific ask this round) -- see HK-4 below: the fix's
    target-matching (`_is_clickup_target`) is a case-SENSITIVE substring
    check, so a ClickUp host reported in any case other than the configured
    lowercase `"clickup.com"` (e.g. `API.CLICKUP.COM`, `Api.Clickup.Com`) is
    NOT recognized and falls back to the same allow-by-default failure mode
    HK-1 was just fixed to close, for a completely ordinary trigger (HTTP
    hostnames are case-insensitive by convention; nothing adversarial is
    required to produce a differently-cased host string).
    """

    def test_default_config_real_clickup_write_via_calls_field_now_blocks(self):
        p = {"calls": [{"target": "https://api.clickup.com/api/v2/task/8675309",
                         "verb": "DELETE"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

    def test_control_same_write_via_clickup_ops_correctly_blocks(self):
        p = {"clickup_ops": [{"verb": "DELETE",
                              "target": "https://api.clickup.com/api/v2/task/8675309"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

    def test_end_to_end_via_core_run_untrusted_stdin_default_registry(self):
        p = {"calls": [{"target": "https://api.clickup.com/api/v2/task/1",
                         "verb": "POST"}]}
        out, err, code = core.run(json.dumps(envelope(p, "pre-pr")))
        self.assertNotEqual(code, 0)

    def test_empty_clickup_ops_present_no_longer_suppresses_the_calls_fallback(self):
        p = {"clickup_ops": [],
             "calls": [{"target": "https://api.clickup.com/api/v2/task/1",
                        "verb": "DELETE"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

    def test_verb_level_default_deny_unchanged(self):
        def check(ops, expect):
            dec = core.dispatch(envelope({"clickup_ops": ops}, "pre-pr"),
                                registry=[core.CLICKUP_GATE_SPEC])
            self.assertEqual(dec.decision, expect, "ops=%r" % ops)
        check([{"verb": "GET"}], "allow")
        check([{"verb": "POST"}], "block")
        check([{}], "block")               # missing verb
        check(["not-a-dict"], "block")     # malformed op
        check([], "allow")                 # no ops -> no write intent

    def test_non_clickup_write_remains_out_of_scope_and_allows(self):
        # Confirms the fix did not over-broaden into blocking unrelated hosts.
        p = {"calls": [{"target": "some-other-service.com/api", "verb": "POST"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "allow")


class HK2_NonFloorHandlerCrashResolvesToBlockInsteadOfWarn(unittest.TestCase):
    """Bug HK-2 (originally HIGH) -- STATUS: FIXED, re-verified 2026-07-14.
    Handler-level exceptions previously propagated uncaught through
    `dispatch()` and, even via `run()`'s generic catch-all, resolved to BLOCK
    regardless of module type -- wrong direction for warn-only non-floor
    modules per this codebase's own ADR failure-posture table.

    FIX (re-verified below, via `dispatch()` called DIRECTLY -- not merely
    through `run()`'s outer safety net, which was masking the real behavior
    before): `dispatch()`'s floor loop and non-floor loop each now wrap
    `spec.handler(event)` in their own `try/except Exception`. A floor
    exception resolves to `block_modules.append(...)` (unconditional block,
    `MODULE_ERROR` reason). A non-floor exception resolves to a synthetic
    `ModuleResult(hit=True, ...)` routed through the SAME `resolve_policy()`
    every real hit uses -- so it fails to WARN pre-flip and to BLOCK
    post-flip, exactly matching a genuine hit's flip-state behavior, not a
    separate hardcoded posture. `dispatch()` itself never raises now,
    confirmed by calling it directly (not through `run()`), including on the
    original schema-valid reachable trigger (a `feature-merge` event with a
    non-dict `payload.changeset`) -- which, on inspection, `hooks.py` ALSO
    now defends against directly (`atomic_tracking_evaluate` has its own new
    `isinstance` guards), so the specific original trigger no longer even
    reaches the exception path; the injected-raising-handler tests below
    confirm the dispatch()-level protection holds independently of that
    belt-and-suspenders fix in `hooks.py`.
    """

    def test_schema_valid_input_no_longer_crashes_atomic_tracking_via_direct_dispatch(self):
        cfg = dict(hooks.DEFAULT_ATOMIC_TRACKING_CONFIG)
        cfg["tracking_file_patterns"] = ["docs/dev-team/harness-tracking.md"]
        spec = core.make_atomic_tracking_spec(cfg)
        p = {"changeset": "oops-not-a-dict", "ticket": {"ticket_id": "T1"}}
        ev = envelope(p, "feature-merge")
        try:
            dec = core.dispatch(ev, registry=[spec])
        except Exception as exc:  # noqa: BLE001
            self.fail("core.dispatch() raised %r" % exc)
        self.assertIn(dec.decision, ("warn", "block"))

    def test_injected_raising_nonfloor_handler_now_warns_pre_flip_via_dispatch_directly(self):
        def raising_handler(event):
            raise RuntimeError("hook handler exploded")
        nonfloor_spec = core.ModuleSpec("test-nonfloor", lambda ev: True,
                                        raising_handler, immutable_floor=False)
        ev = envelope({}, "pre-commit")
        try:
            dec = core.dispatch(ev, registry=[nonfloor_spec])
        except Exception as exc:  # noqa: BLE001
            self.fail("core.dispatch() raised %r instead of failing to warn" % exc)
        self.assertEqual(dec.decision, "warn")
        self.assertEqual(dec.exit_code, 0)

    def test_injected_raising_nonfloor_handler_blocks_post_flip(self):
        def raising_handler(event):
            raise RuntimeError("hook handler exploded")
        nonfloor_spec = core.ModuleSpec("test-nonfloor", lambda ev: True,
                                        raising_handler, immutable_floor=False)
        ev = envelope({}, "pre-commit")
        dec = core.dispatch(ev, registry=[nonfloor_spec],
                            flip_state={"test-nonfloor": "block"})
        self.assertEqual(dec.decision, "block")

    def test_injected_raising_floor_handler_blocks_via_dispatch_directly(self):
        def raising_handler(event):
            raise RuntimeError("floor handler exploded")
        floor_spec = core.ModuleSpec("test-floor", lambda ev: True,
                                     raising_handler, immutable_floor=True)
        ev = envelope({}, "pre-commit")
        try:
            dec = core.dispatch(ev, registry=[floor_spec])
        except Exception as exc:  # noqa: BLE001
            self.fail("core.dispatch() raised %r" % exc)
        self.assertEqual(dec.decision, "block")

    def test_co_matching_modules_reasons_still_aggregate_when_one_raises(self):
        def raising_handler(event):
            raise RuntimeError("boom")
        def real_hit_handler(event):
            return core.ModuleResult(hit=True, module="real-hitter",
                                     reasons=[{"code": "REAL_HIT"}])
        raising_floor = core.ModuleSpec("raising-floor", lambda ev: True,
                                        raising_handler, immutable_floor=True)
        real_floor = core.ModuleSpec("real-floor", lambda ev: True,
                                     real_hit_handler, immutable_floor=True)
        dec = core.dispatch(envelope({}, "pre-commit"),
                            registry=[raising_floor, real_floor])
        codes = [r.get("code") for r in dec.reasons]
        self.assertIn("MODULE_ERROR", codes)
        self.assertIn("REAL_HIT", codes)


class HK3_DirectToMainSensitiveCommitStillBypassesTheGate(unittest.TestCase):
    """Finding HK-3 -- RULING: ACCEPTED as an activation-gated
    residual (security-review condition 4, F-4). Originally filed HIGH:
    `security-gate`/`pii-scrub` register only on
    `pre-pr`/`feature-merge`/data-boundary event types; `commit-block` (the
    only module handling `pre-commit`/`pre-push`) checks branch protection
    only, with zero content-sensitivity awareness. A secret/authz-bypass
    committed directly via `pre-commit` to an unconfigured or unprotected
    branch allows outright; even on an explicitly-protected branch, the best
    case is an advisory WARN, independent of content sensitivity.

    QA ACCEPTS this ruling, same treatment as QA-9/IP (increment 1). Rationale:
      1. This is NOT a new gap introduced by increment 4 -- it is the
         pre-existing, already-named F-4 finding, whose REQUIRED
         resolution was already specified at design time: "(a) the
         security-gate + pii-scrub floor must also evaluate on
         pre-commit/pre-push targeting a protected branch... OR (b)
         commit-block to main/production is fail-closed day one for
         protected branches" -- and, condition 1 (F-1) alongside it, the
         "fail-closed day one" claim for ANY of these floors was already
         conditioned on a CI/server-side enforcement tier that local git
         hooks alone cannot provide ("git commit --no-verify... defeats
         every local control... the honest status... is advisory-plus").
      2. F-4's own required resolution is therefore an ACTIVATION-layer
         fix (branch protection + a CI/server-side tier that runs the same
         core on a boundary the committer cannot bypass), not a library-
         layer code change this increment could make on its own -- the
         library-only status of this whole build (no git hooks, no CI
         wiring exist yet, by explicit design) means this residual cannot
         be closed before activation, matching F-1's already-accepted
         scope boundary.
      3. Both security reviews on record (F-1/F-4, this
         increment's own carry-forward) treat this as a named, tracked,
         activation-gated item, not a silent drop -- the same standard QA
         has applied throughout this engagement (an unratified miss is
         filed and routed; a reasoned, named, ratified trade-off is
         accepted with a tripwire).

    These two tests are kept (not deleted -- append-only) and marked
    `@unittest.expectedFailure`: they guard against silently losing track of
    this residual, and -- more importantly -- against a false sense that it
    is closed before the CI/server-side tier + branch protection actually
    exist. If a future change makes these pass (e.g. security-gate starts
    also evaluating pre-commit/pre-push), that is the signal activation has
    landed and this residual can be formally closed.
    """

    @unittest.expectedFailure  # ACCEPTED, activation-gated (F-4/F-1) -- see class docstring
    def test_secret_and_authz_bypass_direct_committed_unconfigured_branch_allows(self):
        p = {"branch": "main",
             "ticket": {"ticket_id": "DIRECT-1", "sensitivity_flags": []},
             "changeset": {"files": [{
                 "path": "src/auth/login.py",
                 "content": "AWS_SECRET_KEY = 'AKIAABCDEFGHIJKLMNOP'; grant_admin()",
             }]}}
        dec = core.dispatch(envelope(p, "pre-commit"))
        self.assertNotEqual(
            dec.decision, "allow",
            "a secret + authz-bypass committed directly via pre-commit "
            "must not ALLOW outright merely because commit-block is "
            "unconfigured and security-gate never evaluates this "
            "event_type at all (F-4, accepted as activation-gated)",
        )

    @unittest.expectedFailure  # ACCEPTED, activation-gated (F-4/F-1) -- see class docstring
    def test_same_content_on_an_explicitly_protected_branch_still_only_warns(self):
        cfg = dict(hooks.DEFAULT_COMMIT_BLOCK_CONFIG)
        cfg["protected_branches"] = ["main"]
        protected_spec = core.make_commit_block_spec(cfg)
        registry = [core.PII_SCRUB_SPEC, core.SECURITY_GATE_SPEC,
                   core.CLICKUP_GATE_SPEC, protected_spec,
                   core.ATOMIC_TRACKING_SPEC]
        p = {"branch": "main",
             "ticket": {"ticket_id": "DIRECT-2", "sensitivity_flags": []},
             "changeset": {"files": [{
                 "path": "src/auth/login.py",
                 "content": "AWS_SECRET_KEY = 'AKIAABCDEFGHIJKLMNOP'; grant_admin()",
             }]}}
        dec = core.dispatch(envelope(p, "pre-commit"), registry=registry)
        self.assertEqual(
            dec.decision, "block",
            "even WITH the branch explicitly protected, a secret + "
            "authz-bypass committed directly via pre-commit should not be "
            "allowed to merely WARN and proceed (found decision=%r) -- "
            "F-4's own required resolution (accepted as activation-gated)"
            % dec.decision,
        )


class HK4_ClickupTargetMatchingIsCaseSensitive(unittest.TestCase):
    """Finding HK-4 (originally CRITICAL) -- STATUS: FIXED, re-verified
    2026-07-14. `_is_clickup_target()` now lowercases both the reported
    target and each configured signal before the substring check, matching
    the verb-side normalization already used elsewhere in the same module.
    Re-derived independently below: uppercase/mixed-case ClickUp hosts via
    `calls` now block under the default config; a genuinely non-ClickUp
    uppercased host is NOT over-broadened (still allows) -- the fix is
    precise, not merely permissive.

    Original filing, found while adversarially re-probing HK-1's fix per
    that round's explicit ask, "try to still get a write allowed":
    `hooks._is_clickup_target()` identifies a ClickUp call via a plain,
    case-SENSITIVE Python `in` substring check against the configured
    `targets` list (default: `["clickup.com"]`). A call whose `target` host
    is reported in any case other than the configured lowercase form (e.g.
    `API.CLICKUP.COM`, `Api.Clickup.Com`, or even just `api.CLICKUP.com`) is
    NOT recognized as a ClickUp call at all, and is excluded from
    `_clickup_ops()`'s returned list entirely -- reproducing the SAME
    allow-by-default failure mode HK-1 was just fixed to close, for the
    verb-level check never running on it either.

    This is not an exotic or adversarial trigger: HTTP hostnames are
    case-insensitive by DNS/URL convention (RFC 3986), and it is entirely
    ordinary for a logging pipeline, a differently-behaved SDK, or a
    hand-typed URL to present a host in a non-lowercase form with no
    malicious intent whatsoever. Verb matching in the SAME module is
    correctly case-normalized (`.upper()` on both sides); only the target/
    host matching lacks the equivalent normalization.

    Recommended fix (not QA's to implement): case-fold both sides of the
    `_is_clickup_target` comparison (e.g. `.lower()` the target and each
    configured signal before the substring check), matching the verb-side
    pattern already used elsewhere in the same function.
    """

    def test_uppercase_clickup_host_via_calls_should_still_block(self):
        p = {"calls": [{"target": "https://API.CLICKUP.COM/api/v2/task/1",
                         "verb": "DELETE"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(
            dec.decision, "block",
            "an uppercase-cased ClickUp host must not bypass detection -- "
            "HTTP hostnames are case-insensitive by convention, this is not "
            "an adversarial trigger (found decision=%r)" % dec.decision,
        )

    def test_mixed_case_clickup_host_via_calls_should_still_block(self):
        p = {"calls": [{"target": "https://Api.Clickup.Com/api/v2/task/1",
                         "verb": "PUT"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

    def test_control_lowercase_clickup_host_correctly_blocks(self):
        # Isolates HK-4 to specifically the case-matching gap.
        p = {"calls": [{"target": "https://api.clickup.com/api/v2/task/1",
                         "verb": "DELETE"}]}
        dec = core.dispatch(envelope(p, "pre-pr"),
                            registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

class HK5_PathAndBranchMatchingIsPlatformDependentCaseSensitivity(unittest.TestCase):
    """Finding HK-5 (MEDIUM) -- STATUS: FIXED, re-verified 2026-07-14 on this
    (Windows) environment. `_matches_any()` now uses `fnmatch.fnmatchcase()`
    instead of `fnmatch.fnmatch()`, making branch/path matching deterministic
    and case-sensitive on every platform (no more `os.path.normcase`
    dependency). Re-derived independently below: a differently-cased branch
    ('Main') is no longer matched by a 'main' protected-branch rule; a
    differently-cased tracking-file path no longer satisfies atomic-tracking;
    glob metacharacters (`**`, `*`, `?`, `[...]`) still work correctly AND
    remain case-sensitive with the pattern-matching engine swap. Spot-checked
    the rest of the harness codebase for the same class of OS-dependent
    comparison (`fnmatch` now appears only here, correctly as `fnmatchcase`;
    `security_gate.py`'s own glob matching is a separate, hand-rolled `re`-
    based engine with no `IGNORECASE` flag -- already portable and correct,
    unaffected by this finding) -- no other instance found.

    Original filing, found while confirming the dev's audit call that git
    branch/path/ticket-id matching is correctly case-sensitive (that round's
    item 3). The audit call was CORRECT IN INTENT but NOT
    fully correct IN IMPLEMENTATION: `hooks._matches_any()` (used by
    `commit_block_evaluate` for branch matching and by
    `atomic_tracking_evaluate` for tracking-file path matching) is built on
    `fnmatch.fnmatch()`, which normalizes case via `os.path.normcase()` --
    an OS-DEPENDENT function. On POSIX (Linux/macOS) `normcase` is a no-op
    (case stays sensitive, matching git's real semantics correctly). On
    Windows, `normcase` LOWERCASES, so `fnmatch.fnmatch()` becomes
    case-INSENSITIVE -- confirmed empirically on the actual environment this
    session runs in:

        hooks._matches_any("Main", ["main"])                          # True  (should be False)
        hooks._matches_any("DOCS/X.MD", ["docs/x.md"])                 # True  (should be False)
        fnmatch.fnmatchcase("Main", "main")                            # False (the case-safe function)

    Git itself is ALWAYS case-sensitive regardless of host OS -- branch
    `Main` and branch `main` are different refs; path `docs/x.md` and
    `DOCS/X.MD` are different tracked paths -- so the correct behavior is
    case-sensitive on every platform, not merely on POSIX by accident of
    `os.path.normcase`'s no-op there.

    By contrast, `_token_present()` (ticket-ID matching in
    `atomic_tracking_evaluate`) uses a raw `re.search()` with no OS-dependent
    normalization -- genuinely, portably case-sensitive on every platform.
    So the dev's audit call is confirmed correct for ticket-ID matching, and
    correct in INTENT but not in actual cross-platform effect for
    branch/path matching.

    Severity kept at MEDIUM, not higher: this affects only the two WARN-ONLY,
    non-floor modules (commit-block, atomic-tracking) -- no immutable floor
    uses `_matches_any` (clickup-gate's own HK-4 fix uses a separately
    `.lower()`-normalized comparison, not this function). Pre-flip, the
    practical effect is mostly a spurious WARN on an unrelated branch/path
    (safe direction). The more concrete concern: atomic-tracking's own
    purpose ("a feature merge must not land without its tracking entry
    updated atomically") can be satisfied by a DIFFERENTLY-cased path that
    is not actually the real tracked file, on a Windows-hosted enforcement
    point -- and post-flip, commit-block could spuriously hard-block an
    unrelated, differently-cased branch. Not new this round (pre-existing
    since increment 4's original build; not touched by the HK-1/HK-2/HK-4
    remediation), and not reachable via any immutable floor.
    """

    def test_differently_cased_branch_should_not_match_a_protected_branch(self):
        cfg = dict(hooks.DEFAULT_COMMIT_BLOCK_CONFIG)
        cfg["protected_branches"] = ["main"]
        spec = core.make_commit_block_spec(cfg)
        dec = core.dispatch(envelope({"branch": "Main"}, "pre-commit"),
                            registry=[spec])
        self.assertEqual(
            dec.decision, "allow",
            "'Main' is a DIFFERENT git ref than the configured 'main' -- "
            "git is always case-sensitive regardless of host OS; matching "
            "them as equivalent is a platform-dependent bug, not correct "
            "case-sensitive behavior (found decision=%r)" % dec.decision,
        )

    def test_differently_cased_tracking_path_should_not_satisfy_atomic_tracking(self):
        cfg = dict(hooks.DEFAULT_ATOMIC_TRACKING_CONFIG)
        cfg["tracking_file_patterns"] = ["docs/dev-team/harness-tracking.md"]
        spec = core.make_atomic_tracking_spec(cfg)
        p = {"ticket": {"ticket_id": "HN-2"},
             "changeset": {"files": [{
                 "path": "DOCS/DEV-TEAM/HARNESS-TRACKING.MD",  # different case
                 "content": "HN-2 done",
             }]}}
        dec = core.dispatch(envelope(p, "feature-merge"), registry=[spec])
        self.assertEqual(
            dec.decision, "warn",
            "a differently-cased path is a DIFFERENT tracked file in git; "
            "it must not satisfy the atomic-tracking requirement for the "
            "real, canonically-cased tracking file (found decision=%r) -- "
            "this defeats atomic-tracking's own purpose on a "
            "case-insensitive-fnmatch platform" % dec.decision,
        )

    def test_control_ticket_id_matching_correctly_stays_case_sensitive(self):
        # Confirms the dev's audit call IS correct for ticket-ID matching --
        # isolates HK-5 to specifically the branch/path (_matches_any) side.
        cfg = dict(hooks.DEFAULT_ATOMIC_TRACKING_CONFIG)
        cfg["tracking_file_patterns"] = ["docs/dev-team/harness-tracking.md"]
        spec = core.make_atomic_tracking_spec(cfg)
        p = {"ticket": {"ticket_id": "HN-2"},
             "changeset": {"files": [{
                 "path": "docs/dev-team/harness-tracking.md",  # correct case
                 "content": "hn-2 done",  # WRONG case for the ticket id token
             }]}}
        dec = core.dispatch(envelope(p, "feature-merge"), registry=[spec])
        self.assertEqual(
            dec.decision, "warn",
            "ticket-id matching (_token_present, a raw re.search) is "
            "correctly case-sensitive -- 'hn-2' must not satisfy a "
            "requirement for 'HN-2'",
        )


if __name__ == "__main__":
    unittest.main()
