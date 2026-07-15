"""Unit tests for contract-v1 envelope validation + response protocol."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contract as C  # noqa: E402


def valid_event(**overrides):
    ev = {
        "contract_version": "1.0",
        "event_id": "evt-1",
        "event_type": "pre-pr",
        "occurred_at": "2026-07-13T09:00:00Z",
        "harness": {"name": "claude", "adapter_version": "1.0.0"},
        "requested_mode": "block",
        "payload": {},
    }
    ev.update(overrides)
    return ev


class TestLoadEvent(unittest.TestCase):
    def test_valid_json_object(self):
        ev = C.load_event('{"a": 1}')
        self.assertEqual(ev, {"a": 1})

    def test_bytes_input(self):
        ev = C.load_event(b'{"a": 1}')
        self.assertEqual(ev, {"a": 1})

    def test_malformed_json_raises(self):
        with self.assertRaises(C.MalformedEventError):
            C.load_event("{not json")

    def test_non_object_root_raises(self):
        with self.assertRaises(C.MalformedEventError):
            C.load_event("[1, 2, 3]")


class TestEnvelopeValidation(unittest.TestCase):
    def test_good_envelope_passes(self):
        ev = valid_event()
        # returns the same object unchanged on success
        self.assertIs(C.validate_envelope(ev), ev)

    def test_good_envelope_returns_event(self):
        ev = valid_event()
        self.assertEqual(C.validate_envelope(ev)["event_id"], "evt-1")

    def test_missing_required_field(self):
        ev = valid_event()
        del ev["event_type"]
        with self.assertRaises(C.EnvelopeValidationError) as cm:
            C.validate_envelope(ev)
        self.assertTrue(any("event_type" in p for p in cm.exception.problems))

    def test_bad_event_type_enum(self):
        with self.assertRaises(C.EnvelopeValidationError):
            C.validate_envelope(valid_event(event_type="not-a-real-type"))

    def test_bad_requested_mode_enum(self):
        with self.assertRaises(C.EnvelopeValidationError):
            C.validate_envelope(valid_event(requested_mode="maybe"))

    def test_harness_missing_name(self):
        with self.assertRaises(C.EnvelopeValidationError):
            C.validate_envelope(valid_event(harness={"adapter_version": "1.0.0"}))

    def test_payload_wrong_type(self):
        with self.assertRaises(C.EnvelopeValidationError):
            C.validate_envelope(valid_event(payload="should-be-object"))

    def test_bad_version_pattern(self):
        with self.assertRaises(C.EnvelopeValidationError):
            C.validate_envelope(valid_event(contract_version="v1"))

    def test_unsupported_major_refused(self):
        with self.assertRaises(C.UnsupportedContractError):
            C.validate_envelope(valid_event(contract_version="2.0"))

    def test_supported_major_minor_ok(self):
        # additive MINOR within supported MAJOR is accepted
        C.validate_envelope(valid_event(contract_version="1.7"))


class TestDecision(unittest.TestCase):
    def test_allow_exit_zero(self):
        self.assertEqual(C.Decision("allow", "m").exit_code, C.EXIT_ALLOW)

    def test_warn_exit_zero(self):
        # warn proceeds -> exit 0 (contractual)
        self.assertEqual(C.Decision("warn", "m").exit_code, C.EXIT_ALLOW)

    def test_noop_and_not_graded_exit_zero(self):
        self.assertEqual(C.Decision("no-op", "m").exit_code, 0)
        self.assertEqual(C.Decision("not-graded", "m").exit_code, 0)

    def test_block_exit_nonzero(self):
        d = C.Decision("block", "m")
        self.assertNotEqual(d.exit_code, 0)
        self.assertTrue(d.blocks)

    def test_stdout_is_valid_json_with_contract_fields(self):
        import json
        d = C.Decision("block", "pii-scrub", reasons=[{"code": "X", "category": "EMAIL", "count": 1}], event_id="e1")
        obj = json.loads(d.to_stdout())
        self.assertEqual(obj["decision"], "block")
        self.assertEqual(obj["module"], "pii-scrub")
        self.assertEqual(obj["event_id"], "e1")
        self.assertEqual(obj["contract_version"], C.CONTRACT_VERSION)


if __name__ == "__main__":
    unittest.main()
