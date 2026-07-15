"""QA-authored scratch tests (independent adversarial verification, increment 2).

These are NOT part of the developer's delivered suite for security_gate.py
(HK2). They encode gaps found while independently probing the security-gate
module for INCREMENT 2. Each test asserts the SECURE/SPEC'D behavior. Where a
test currently FAILS, that failure is the reproduction of a filed bug -- do
not "fix" it by loosening the assertion. See
docs/dev-team/qa/2026-07-14-harness-increment2-qa.md for the bug write-up
(SG-1, SG-2, SG-3).

QA does not modify contract.py / core.py / security_gate.py to make these pass.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core  # noqa: E402
import security_gate as SG  # noqa: E402


def envelope(payload, event_type="pre-pr", requested_mode="block"):
    return {
        "contract_version": "1.0",
        "event_id": "evt-sg-qa",
        "event_type": event_type,
        "occurred_at": "2026-07-14T00:00:00Z",
        "harness": {"name": "test"},
        "requested_mode": requested_mode,
        "payload": payload,
    }


class SG1_EmptyOrWhitespaceContentBypassesAmbiguityFailClosed(unittest.TestCase):
    """Bug SG-1 (CRITICAL): `_derive()`'s ambiguity fallback ("content
    unavailable AND path not provably safe -> ambiguous -> sensitive, fail
    closed") is gated on `content is None`. A file entry that reports an
    EMPTY STRING (or whitespace-only string) as `content` -- functionally
    identical to "we could not obtain real content" -- is NOT `None`, so the
    ambiguity branch is skipped entirely. Because an empty/whitespace string
    trivially matches no content_signal, the file is classified
    "inspected and clean" (non-sensitive) with ZERO actual inspection having
    occurred. This defeats the F-3 "ambiguity -> sensitive" guarantee for any
    file whose path does not happen to match a sensitivity-rule path glob --
    a sensitive ticket with genuinely sensitive (but unglobbed-path) content
    can be ALLOWED with no sign-off required, simply because the adapter
    (buggy or malicious -- the named threat actor in the security review)
    reported empty content instead of omitting the field or reporting the
    real content.

    Reproduced through `security_gate.evaluate()` directly AND end-to-end
    through the untrusted-stdin `core.run()` path.

    STATUS (re-verified 2026-07-14): FIXED. `_content_usable()` now gates
    both `_derive()`'s ambiguity check and `_current_hash()`'s binding check
    on "non-empty, non-whitespace string", closing the gap for both the
    sensitivity-derivation half (SG-1) and the sign-off-binding half (which
    Code Review separately flagged as M-1: an adapter-supplied
    `content_hash` with no real `content` no longer passes the binding
    check either -- `_current_hash()` no longer reads `content_hash` at all).
    Left as a permanent regression test.
    """

    def test_empty_string_content_on_non_glob_path_is_not_treated_as_ambiguous(self):
        payload = {
            "ticket": {"ticket_id": "SG1-A", "sensitivity_flags": []},
            "changeset": {"files": [
                {"path": "src/payments/charge_engine.py", "content": ""}
            ]},
        }
        r = SG.evaluate(payload, SG.DEFAULT_CONFIG)
        self.assertTrue(
            r.blocked,
            "a file reported with EMPTY content (content not actually "
            "verified) must be treated the same as unavailable content -- "
            "ambiguous, fail-closed -- not silently allowed as 'inspected "
            "and clean' (found required_flags=%r)" % r.required_flags,
        )

    def test_whitespace_only_content_same_bypass(self):
        payload = {
            "ticket": {"ticket_id": "SG1-B", "sensitivity_flags": []},
            "changeset": {"files": [
                {"path": "src/payments/charge_engine.py", "content": "   \n\t  "}
            ]},
        }
        r = SG.evaluate(payload, SG.DEFAULT_CONFIG)
        self.assertTrue(
            r.blocked,
            "whitespace-only content must not be treated as a verified, "
            "clean inspection result (found required_flags=%r)" % r.required_flags,
        )

    def test_control_missing_content_is_correctly_ambiguous(self):
        # Sanity control: the SAME path with content OMITTED entirely is
        # correctly caught by the existing ambiguous-fallback. This isolates
        # the bug to specifically the empty-string/None distinction.
        payload = {
            "ticket": {"ticket_id": "SG1-C", "sensitivity_flags": []},
            "changeset": {"files": [
                {"path": "src/payments/charge_engine.py"}
            ]},
        }
        r = SG.evaluate(payload, SG.DEFAULT_CONFIG)
        self.assertTrue(r.blocked, "control case: missing content must be ambiguous")
        self.assertIn("sensitive", r.required_flags)

    def test_end_to_end_via_core_run_untrusted_stdin(self):
        payload = {
            "ticket": {"ticket_id": "SG1-D", "sensitivity_flags": []},
            "changeset": {"files": [
                {"path": "src/payments/charge_engine.py", "content": ""}
            ]},
        }
        out, err, code = core.run(json.dumps(envelope(payload)))
        self.assertNotEqual(
            code, 0,
            "an unverified (empty-content) file on a non-glob-matched path "
            "must not allow through the full core.run() stack "
            "(stdout=%r)" % out,
        )


class SG2_BoundaryKeyHijacksDispatchAwayFromSecurityGate(unittest.TestCase):
    """Bug SG-2 (CRITICAL): `core.dispatch()`'s module resolution
    (`resolve_module`) returns the FIRST registered spec whose `matches()` is
    true. `DEFAULT_REGISTRY = [PII_SCRUB_SPEC, SECURITY_GATE_SPEC]` --
    pii-scrub is checked first (by design, so a spoofed `event_type` cannot
    route a boundary-crossing payload AROUND pii-scrub's own floor). But
    `_pii_scrub_matches()` only inspects `payload.get("boundary")` and does
    not care about anything else in the payload. Consequence: ANY
    security-gate-shaped event (a `pre-pr`/`feature-merge` event carrying
    `ticket` + `changeset`, exactly what the security-gate needs) that ALSO
    happens to carry a `boundary` key (`"import-into-repo"` or
    `"egress-to-judge"`) is routed ENTIRELY to pii-scrub instead --
    pii-scrub scans the payload for PII shapes (finding none, since the
    payload is a ticket/changeset descriptor, not a PII fixture) and
    ALLOWS -- and the security-gate is never consulted at all. A sensitive,
    un-signed-off ticket (e.g. a login-flow change with a hardcoded
    `grant_admin()` bypass) is fully approved with a single extra JSON field.

    This is not a heuristic-precision gap -- it is a structural dispatch
    ordering flaw. The values that trigger it (`import-into-repo` /
    `egress-to-judge`) are public (checked into `hook-event.schema.json` /
    README), not secret, so this requires no special knowledge to exploit --
    only control over the event payload, which the security review already
    names as a live threat ("a buggy or malicious per-harness adapter").

    Reproduced through `core.dispatch()` AND end-to-end through the
    untrusted-stdin `core.run()` path.

    STATUS (re-verified 2026-07-14): FIXED. `core.dispatch()` now evaluates
    ALL matching immutable floors ("all floors, any-block-blocks") rather
    than first-match-wins; `SECURITY_GATE_SPEC.matches()` also now requires
    a security-gate-SHAPED payload (`ticket`/`changeset`/`signoff_record`
    present), so a payload carrying `boundary` no longer excludes it from
    also matching the gate. A payload matching both floors must satisfy
    both. Left as a permanent regression test.
    """

    def _sensitive_no_signoff_payload(self):
        return {
            "ticket": {"ticket_id": "SG2-A", "sensitivity_flags": []},
            "changeset": {"files": [
                {"path": "src/auth/login.py",
                 "content": "password = input(); grant_admin()"}
            ]},
        }

    def test_baseline_without_boundary_key_correctly_blocks(self):
        # Control: without the extra field, this correctly routes to
        # security-gate and blocks (no sign-off for a sensitive change).
        dec = core.dispatch(envelope(self._sensitive_no_signoff_payload()))
        self.assertEqual(dec.module, "security-gate")
        self.assertEqual(dec.decision, "block")

    def test_adding_boundary_key_must_not_reroute_away_from_security_gate(self):
        hijacked = dict(self._sensitive_no_signoff_payload())
        hijacked["boundary"] = "egress-to-judge"
        dec = core.dispatch(envelope(hijacked))
        self.assertEqual(
            dec.decision, "block",
            "a security-gate-shaped event (ticket+changeset) must still be "
            "evaluated by security-gate even if it also carries a "
            "'boundary' key -- found module=%r decision=%r instead "
            "(dispatch was hijacked to pii-scrub, which allowed a "
            "sensitive, un-signed-off ticket through)"
            % (dec.module, dec.decision),
        )
        self.assertIn("security-gate", dec.module)

    def test_end_to_end_via_core_run_untrusted_stdin(self):
        hijacked = dict(self._sensitive_no_signoff_payload())
        hijacked["boundary"] = "egress-to-judge"
        out, err, code = core.run(json.dumps(envelope(hijacked)))
        self.assertNotEqual(
            code, 0,
            "a sensitive, un-signed-off ticket must not exit 0/allow merely "
            "because the payload carries an extra 'boundary' key "
            "(stdout=%r)" % out,
        )


class SG3_GateShapedEventDisguisedAsPureScrubEventSkipsTheGate(unittest.TestCase):
    """Finding SG-3 -- STATUS: CLOSED (2026-07-14, increment-3 consolidated
    remediation). Originally filed MEDIUM (dev-flagged residual, independently
    confirmed 2026-07-14): a payload on a gate `event_type` (`pre-pr` /
    `feature-merge`) that carried NEITHER `ticket`/`changeset`/`signoff_record`
    -- only a `boundary` + `fixture` (a pure PII-scrub-shaped payload) --
    matched only pii-scrub, so a sensitive CODE CHANGE (e.g. an authz bypass)
    containing no literal PII shape could slip through: pii-scrub finds
    nothing and ALLOWS, and the security-gate is never in the picture.

    RULING: Security ruled option (b) -- a DISJOINT event-type convention,
    not a residual acceptance. This is a real fix, not a ratified trade-off:
      * Gate event types (`pre-pr` / `feature-merge`) and data-boundary event
        types (`import-into-repo` / `eval-egress`) are now DISJOINT. The
        event_type itself IS the boundary for pii-scrub -- `core.py`'s
        `_pii_scrub_matches()` checks ONLY `event.get("event_type") in
        _DATA_BOUNDARY_EVENTS`; a `boundary` key in the payload is no longer
        read for routing at all (vestigial; stripped if present when building
        the fixture fallback).
      * `security_gate`'s `matches()` now fires on EVERY gate event_type,
        unconditionally -- no shape check. A gate event carrying no
        ticket/changeset is a malformed gate event and `security_gate.
        evaluate()` already blocks it (`TICKET_MISSING` / `CHANGESET_MISSING`
        -- pre-existing code, now reachable on every gate event since the
        shape gate that used to skip evaluation entirely is gone).
      * Net effect: a scrub/eval flow can no longer arrive labelled as a gate
        event_type at all (it must use a data-boundary type), so the
        cross-module shape confusion that created SG-3 cannot recur BY
        CONSTRUCTION of the event-type namespace, not by convention about
        what shape an adapter "should" produce.

    These tests are KEPT (not deleted -- append-only) and REPURPOSED as
    permanent regression tests for the fix and for the disjoint-convention
    guarantee: the disguise attempt (gate-type event + `boundary` key, no
    ticket/changeset) now MUST block, and a `boundary` key on a gate event
    must NOT route it around the gate.
    """

    def _sensitive_authz_bypass_fixture(self):
        body = ("def authorize(user):\n"
                 "    if user.role == 'admin_backdoor':\n"
                 "        return True\n"
                 "    return check_permissions(user)")
        return {
            "boundary": "egress-to-judge",
            "fixture": {"fields": {"body": body}},
        }

    def test_control_same_content_without_boundary_correctly_blocks(self):
        # Isolates the trigger: WITHOUT `boundary`, this shape matches no
        # floor and no non-floor module -> falls to core.unhandled -> block.
        p = {"fixture": self._sensitive_authz_bypass_fixture()["fixture"]}
        dec = core.dispatch(envelope(p))
        self.assertEqual(dec.decision, "block")

    def test_control_real_pr_shape_with_same_semantic_content_is_gated(self):
        # Isolates the trigger further: the SAME sensitive logic, shaped as a
        # real PR (ticket+changeset, no boundary), is correctly gated.
        real_pr = {
            "ticket": {"ticket_id": "SG3-REAL", "sensitivity_flags": []},
            "changeset": {"files": [{
                "path": "src/auth/authorize.py",
                "content": "if user.role == 'admin_backdoor': return True",
            }]},
        }
        dec = core.dispatch(envelope(real_pr))
        self.assertEqual(dec.module, "security-gate")
        self.assertEqual(dec.decision, "block")

    def test_sg3_closed_gate_shaped_event_disguised_as_pure_scrub_event_now_blocks(self):
        # SG-3 CLOSED: on the default gate event_type ("pre-pr"), the
        # `boundary` key is no longer honored for routing at all -- pii-scrub
        # doesn't match (wrong event_type namespace), and security-gate
        # matches unconditionally on the gate event_type and blocks the
        # ticketless/changesetless gate event as malformed.
        p = self._sensitive_authz_bypass_fixture()
        dec = core.dispatch(envelope(p))
        self.assertEqual(
            dec.decision, "block",
            "SG-3 regression: a gate-event-type payload disguised as a pure "
            "PII-scrub fixture (boundary key, no ticket/changeset) must "
            "block via security-gate's ticketless-gate-event check "
            "(found module=%r decision=%r)" % (dec.module, dec.decision),
        )
        self.assertIn(
            "security-gate", dec.module,
            "the block must come from security-gate's malformed-gate-event "
            "check, not merely an unrelated unhandled-event-type fallback",
        )

    def test_boundary_key_on_gate_event_does_not_reroute_around_the_gate(self):
        # Direct probe of the coordinator's ask: a `boundary` key on a gate
        # event_type must not let a SENSITIVE, un-signed-off ticket escape
        # the gate by giving pii-scrub something to "handle" instead. Uses a
        # genuine ticket/changeset shape (not disguised) PLUS a `boundary`
        # key, to prove the gate still fires and blocks even when a
        # `boundary` key is also present.
        sensitive_with_boundary = {
            "ticket": {"ticket_id": "SG3-NOREROUTE", "sensitivity_flags": []},
            "changeset": {"files": [{
                "path": "src/auth/login.py",
                "content": "password = input(); grant_admin()",
            }]},
            "boundary": "egress-to-judge",
        }
        dec = core.dispatch(envelope(sensitive_with_boundary))
        self.assertEqual(dec.decision, "block")
        self.assertIn("security-gate", dec.module)

    def test_gate_event_type_no_longer_routes_to_pii_scrub_at_all(self):
        # Structural confirmation of the disjoint convention: pii-scrub's own
        # matcher never fires on a gate event_type, regardless of payload
        # shape or a `boundary` key's presence -- the event_type namespaces
        # are disjoint, not merely "usually" disjoint by adapter convention.
        import core as core_module
        gate_event = envelope(self._sensitive_authz_bypass_fixture(),
                              event_type="pre-pr")
        self.assertFalse(
            core_module._pii_scrub_matches(gate_event),
            "pii-scrub must never match a gate event_type, even one "
            "carrying a `boundary` key",
        )


if __name__ == "__main__":
    unittest.main()
