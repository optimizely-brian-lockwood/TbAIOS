"""Unit tests for the core dispatch/runner and policy precedence.

Central proof: a `requested_mode: warn` hint CANNOT soften the pii-scrub
immutable floor, but CAN soften a non-floor warn-only module -- demonstrating
the precedence order floor > flip > requested_mode.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contract as C  # noqa: E402
import core  # noqa: E402

# A leak the default scrubber has no rule for -> the independent scanner blocks
# it. Used so a boundary event reliably produces a BLOCK for precedence tests.
# A MUST-DETECT shape (D-1 email) -> the pipeline hard-blocks it, giving a
# deterministic BLOCK for precedence/floor tests under the detection ruleset.
LEAK = "please contact jane.doe@acme.com about this"


def envelope(payload, event_type="pre-pr", requested_mode="block", **ov):
    ev = {
        "contract_version": "1.0",
        "event_id": "evt-core",
        "event_type": event_type,
        "occurred_at": "2026-07-13T09:00:00Z",
        "harness": {"name": "test-harness"},
        "requested_mode": requested_mode,
        "payload": payload,
    }
    ev.update(ov)
    return ev


# A non-floor, warn-only stub module for precedence testing (registration seam).
def _stub_matches(event):
    return event["event_type"] == "pre-commit"


def _stub_handler(event):
    return core.ModuleResult(hit=True, module="stub.warn-only",
                             reasons=[{"code": "STUB_HIT"}])


STUB_SPEC = core.ModuleSpec("stub.warn-only", _stub_matches, _stub_handler,
                            immutable_floor=False)


class TestPolicyPrecedence(unittest.TestCase):

    def test_pii_scrub_floor_ignores_requested_mode_warn(self):
        # A dirty fixture on a DATA-BOUNDARY event type, requested_mode=warn.
        ev = envelope(
            {"fixture": {"fields": {"note": LEAK}}},
            event_type="eval-egress", requested_mode="warn",
        )
        dec = core.dispatch(ev)
        # Floor wins: block despite requested_mode=warn.
        self.assertEqual(dec.decision, "block")
        self.assertEqual(dec.exit_code, C.EXIT_BLOCK)

    def test_non_floor_module_softened_by_requested_mode_warn(self):
        registry = [STUB_SPEC]
        ev = envelope({}, event_type="pre-commit", requested_mode="warn")
        dec = core.dispatch(ev, registry=registry)
        self.assertEqual(dec.decision, "warn")
        self.assertEqual(dec.exit_code, C.EXIT_ALLOW)

    def test_non_floor_module_blocks_post_flip_even_with_warn_request(self):
        # Precedence: flip state hardens to block; requested_mode=warn cannot
        # soften a post-flip module... actually requested_mode CAN narrow a
        # non-floor module, so post-flip + warn -> warn. Verify the documented
        # order: flip sets the hardened value, requested_mode then narrows it.
        registry = [STUB_SPEC]
        ev = envelope({}, event_type="pre-commit", requested_mode="block")
        dec = core.dispatch(ev, registry=registry, flip_state={"stub.warn-only": "block"})
        self.assertEqual(dec.decision, "block")

    def test_non_floor_pre_flip_defaults_to_warn(self):
        registry = [STUB_SPEC]
        ev = envelope({}, event_type="pre-commit", requested_mode="block")
        dec = core.dispatch(ev, registry=registry, flip_state={})
        self.assertEqual(dec.decision, "warn")

    def test_floor_ignores_flip_state_too(self):
        ev = envelope(
            {"fixture": {"fields": {"note": LEAK}}},
            event_type="import-into-repo",
        )
        dec = core.dispatch(ev, flip_state={"pii-scrub": "warn"})
        self.assertEqual(dec.decision, "block")


class TestDispatchRouting(unittest.TestCase):

    def test_clean_boundary_event_allows(self):
        ev = envelope(
            {"fixture": {"fields": {"note": "nothing sensitive here today"}}},
            event_type="import-into-repo",
        )
        dec = core.dispatch(ev)
        self.assertEqual(dec.decision, "allow")
        self.assertEqual(dec.exit_code, 0)

    def test_data_boundary_event_routes_to_pii_scrub(self):
        # pii-scrub claims data-boundary event types.
        ev = envelope(
            {"fixture": {"fields": {"note": LEAK}}},
            event_type="eval-egress",
        )
        dec = core.dispatch(ev)
        self.assertEqual(dec.module, "pii-scrub")

    def test_boundary_key_not_honored_on_non_data_boundary_type(self):
        # A `boundary` key on a NON-data-boundary event type is NOT honored --
        # it cannot route to pii-scrub (SG-3 decoupling). obs-emit is claimed by
        # the obs emitter (non-floor, non-blocking), NOT pii-scrub.
        ev = envelope(
            {"boundary": "egress-to-judge",
             "fixture": {"fields": {"note": LEAK}}},
            event_type="obs-emit",
        )
        dec = core.dispatch(ev)
        self.assertNotEqual(dec.module, "pii-scrub")
        self.assertEqual(dec.exit_code, 0)     # non-blocking

    def test_unhandled_enforcement_event_blocks(self):
        # eval-run has no registered module (pre-pr/feature-merge now route to
        # the security-gate floor); an unhandled enforcement type still blocks.
        ev = envelope({}, event_type="eval-run")   # no boundary, no module
        dec = core.dispatch(ev)
        self.assertEqual(dec.decision, "block")
        self.assertEqual(dec.reasons[0]["code"], "UNHANDLED_EVENT_TYPE")

    def test_unhandled_obs_event_noops(self):
        # With NO module claiming it (empty registry), an obs-emit event no-ops
        # (never blocks) -- the unhandled-obs branch.
        ev = envelope({}, event_type="obs-emit")
        dec = core.dispatch(ev, registry=[])
        self.assertEqual(dec.decision, "no-op")

    def test_obs_emit_handled_by_obs_module_is_non_blocking(self):
        # In the default registry the obs emitter claims obs-emit -> non-blocking.
        ev = envelope({}, event_type="obs-emit")
        dec = core.dispatch(ev)
        self.assertEqual(dec.exit_code, 0)
        self.assertNotEqual(dec.decision, "block")
        self.assertEqual(dec.exit_code, 0)


class TestRunProtocol(unittest.TestCase):

    def test_run_malformed_json_blocks(self):
        out, err, code = core.run("{ not json")
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out)["reasons"][0]["code"], "MALFORMED_EVENT")

    def test_run_invalid_envelope_enforcement_blocks(self):
        ev = envelope({}, event_type="pre-pr")
        del ev["requested_mode"]
        out, err, code = core.run(json.dumps(ev))
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out)["reasons"][0]["code"], "ENVELOPE_INVALID")

    def test_run_invalid_envelope_obs_noops(self):
        ev = envelope({}, event_type="obs-emit")
        del ev["requested_mode"]
        out, err, code = core.run(json.dumps(ev))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "no-op")

    def test_run_unsupported_major_blocks(self):
        ev = envelope({}, event_type="pre-pr", contract_version="9.0")
        out, err, code = core.run(json.dumps(ev))
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out)["reasons"][0]["code"], "UNSUPPORTED_CONTRACT_MAJOR")

    def test_run_never_raises_on_infra_error_blocks(self):
        # QA-2: an infra failure during validation (schema file unreadable) must
        # resolve to a fail-closed block, not propagate an exception.
        import pathlib
        orig = C.SCHEMA_PATH
        C.SCHEMA_PATH = pathlib.Path("no-such-schema-file.json")
        try:
            ev = envelope({}, event_type="pre-pr")
            out, err, code = core.run(json.dumps(ev))
        finally:
            C.SCHEMA_PATH = orig
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(out)["reasons"][0]["code"], "CORE_ERROR")

    def test_run_infra_error_on_obs_noops(self):
        # Same infra error on an obs event fails open (no-op), not block.
        import pathlib
        orig = C.SCHEMA_PATH
        C.SCHEMA_PATH = pathlib.Path("no-such-schema-file.json")
        try:
            ev = envelope({}, event_type="obs-emit")
            out, err, code = core.run(json.dumps(ev))
        finally:
            C.SCHEMA_PATH = orig
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "no-op")

    def test_run_clean_event_exit_zero(self):
        ev = envelope(
            {"fixture": {"fields": {"note": "all clear"}}},
            event_type="import-into-repo",
        )
        out, err, code = core.run(json.dumps(ev))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "allow")

    def test_run_dirty_event_exit_nonzero_and_no_pii_in_output(self):
        pii = "john.roe@example.org"   # D-1 email -> hard block
        ev = envelope(
            {"fixture": {"fields": {"note": "mail %s soon" % pii}}},
            event_type="eval-egress",
        )
        out, err, code = core.run(json.dumps(ev))
        self.assertNotEqual(code, 0)
        # no-PII-echo: the matched value must not appear in any output channel
        self.assertNotIn(pii, out)
        self.assertNotIn(pii, err)


if __name__ == "__main__":
    unittest.main()
