"""Tests for the H-OBS observability emitter (increment 5).

Covers: metadata-only-by-construction; out-of-allow-list key rejected; value
validation (role/ticket_id/tokens sanitized; PII-bearing values dropped, not
truncated); error-path no-leak (raising sink + malformed event -> no content,
no raise, no block); fails-open; the standing gitignore assertion; and dispatch
composition (obs is non-floor, never affects a floor's block).
"""

import json
import os
import subprocess
import sys
import unittest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HARNESS)
import contract as C   # noqa: E402
import core            # noqa: E402
import obs             # noqa: E402

# A PII-laden invocation event: prompt/transcript content + PII in metadata
# fields. None of it may reach the sink, on any path.
PII_EVENT = {
    "contract_version": "1.0", "event_id": "evt-obs-1", "event_type": "obs-emit",
    "occurred_at": "2026-07-14T09:00:00Z", "harness": {"name": "test"},
    "requested_mode": "annotate",
    "payload": {
        "role": "security-engineer", "ticket_id": "HN-2",
        "tokens": {"in": 120, "out": 340}, "latency_ms": 1500,
        # --- content / smuggle attempts that must NEVER be persisted ---
        "prompt": "customer john.doe@acme.com SSN 123-45-6789 wants a refund",
        "transcript": "full chat transcript with card 4111111111111111",
        "message": "secret token sk-ant-abcdefghijklmnopqrstuvwxyz012345",
    },
}
PII_STRINGS = ["john.doe@acme.com", "123-45-6789", "4111111111111111",
               "sk-ant-abcdefghijklmnopqrstuvwxyz012345", "transcript", "prompt"]


def _blob(records):
    return json.dumps(records, sort_keys=True)


class TestMetadataOnly(unittest.TestCase):

    def test_record_has_exactly_the_allow_list_keys(self):
        sink = obs.ListSink()
        obs.emit(PII_EVENT, obs.DEFAULT_OBS_CONFIG, sink=sink)
        self.assertEqual(len(sink.records), 1)
        rec = sink.records[0]
        self.assertEqual(set(rec.keys()),
                         {"event_id", "ts", "role", "ticket_id", "tokens", "latency_ms"})
        self.assertEqual(set(rec["tokens"].keys()), {"in", "out"})

    def test_no_content_reaches_the_sink(self):
        sink = obs.ListSink()
        obs.emit(PII_EVENT, obs.DEFAULT_OBS_CONFIG, sink=sink)
        blob = _blob(sink.records)
        for pii in PII_STRINGS:
            self.assertNotIn(pii, blob, "content leaked into obs record: %s" % pii)

    def test_metadata_values_preserved(self):
        sink = obs.ListSink()
        obs.emit(PII_EVENT, obs.DEFAULT_OBS_CONFIG, sink=sink)
        rec = sink.records[0]
        self.assertEqual(rec["role"], "security-engineer")
        self.assertEqual(rec["ticket_id"], "HN-2")
        self.assertEqual(rec["tokens"], {"in": 120, "out": 340})
        self.assertEqual(rec["latency_ms"], 1500)
        self.assertEqual(rec["ts"], "2026-07-14T09:00:00Z")

    def test_out_of_allow_list_key_rejected_by_write_validator(self):
        # Simulate a future field addition: _keys_ok must reject it -> no write.
        self.assertFalse(obs._keys_ok({"event_id": "x", "ts": None, "role": None,
                                       "ticket_id": None, "tokens": {"in": None, "out": None},
                                       "latency_ms": None, "transcript": "leak"}))
        self.assertFalse(obs._keys_ok({"event_id": "x", "ts": None, "role": None,
                                       "ticket_id": None,
                                       "tokens": {"in": None, "out": None, "raw": "leak"},
                                       "latency_ms": None}))


class TestValueValidation(unittest.TestCase):

    def _emit(self, payload):
        ev = dict(PII_EVENT)
        ev["payload"] = payload
        sink = obs.ListSink()
        obs.emit(ev, obs.DEFAULT_OBS_CONFIG, sink=sink)
        return sink.records[0]

    def test_pii_bearing_ticket_id_dropped_to_null(self):
        rec = self._emit({"ticket_id": "HN-2: customer john@acme.com asked",
                          "role": "code-reviewer"})
        self.assertIsNone(rec["ticket_id"])
        self.assertNotIn("john@acme.com", _blob([rec]))

    def test_free_text_role_dropped_to_null(self):
        rec = self._emit({"role": "security-engineer reviewing john@acme.com's PR"})
        self.assertIsNone(rec["role"])          # not in the enum

    def test_role_is_strict_enum_only(self):
        # F-OBS-1: role must be a value in the configured enum. NO slug/free-text
        # path -- a name-shaped slug ('john-smith') is dropped, not stored.
        self.assertEqual(self._emit({"role": "code-reviewer"})["role"], "code-reviewer")
        for not_a_role in ("custom-role-x", "john-smith", "jane-doe-acme", "SECURITY-ENGINEER"):
            self.assertIsNone(self._emit({"role": not_a_role})["role"],
                              "non-enum role must be dropped: %s" % not_a_role)

    def test_role_enum_is_config_extensible(self):
        cfg = dict(obs.DEFAULT_OBS_CONFIG)
        cfg["role_enum"] = list(cfg["role_enum"]) + ["new-role-added-via-config"]
        ev = dict(PII_EVENT); ev["payload"] = {"role": "new-role-added-via-config"}
        sink = obs.ListSink()
        obs.emit(ev, cfg, sink=sink)
        self.assertEqual(sink.records[0]["role"], "new-role-added-via-config")

    def test_oversized_ticket_id_dropped_to_null(self):
        # OB-1: length-bounded like event_id/role.
        big = "A" * 5000 + "-" + "9" * 5000
        self.assertIsNone(self._emit({"ticket_id": big})["ticket_id"])
        self.assertEqual(self._emit({"ticket_id": "HN-2"})["ticket_id"], "HN-2")

    def test_negative_and_nonnumeric_tokens_rejected(self):
        rec = self._emit({"tokens": {"in": -5, "out": "lots"}, "latency_ms": -1})
        self.assertIsNone(rec["tokens"]["in"])
        self.assertIsNone(rec["tokens"]["out"])
        self.assertIsNone(rec["latency_ms"])

    def test_non_finite_numerics_rejected(self):
        # OB-2: inf/nan -> null (else json.dumps emits non-standard Infinity/NaN).
        rec = self._emit({"tokens": {"in": float("inf"), "out": float("nan")},
                          "latency_ms": float("inf")})
        self.assertIsNone(rec["tokens"]["in"])
        self.assertIsNone(rec["tokens"]["out"])
        self.assertIsNone(rec["latency_ms"])
        # the emitted record serializes as strict JSON (no Infinity/NaN token)
        strict = json.dumps(rec)
        self.assertNotIn("Infinity", strict)
        self.assertNotIn("NaN", strict)

    def test_bad_ts_dropped(self):
        rec = self._emit({"ts": "yesterday-ish john@acme.com"})
        self.assertIsNone(rec["ts"])

    def test_missing_role_and_ticket_are_null_not_inferred(self):
        rec = self._emit({"tokens": {"in": 1, "out": 2},
                          "prompt": "role: security-engineer per the text"})
        self.assertIsNone(rec["role"])          # never inferred from content (F-6)
        self.assertIsNone(rec["ticket_id"])


class TestErrorPathNoLeak(unittest.TestCase):

    class RaisingSink:
        def write(self, record):
            raise RuntimeError("sink exploded")

    def test_raising_sink_no_leak_no_raise(self):
        sink = self.RaisingSink()
        try:
            r = obs.emit(PII_EVENT, obs.DEFAULT_OBS_CONFIG, sink=sink)
        except Exception as exc:  # noqa: BLE001
            self.fail("obs.emit raised %r instead of failing open" % exc)
        self.assertEqual(r.error, "OBS_EMIT_ERROR")
        self.assertIsNone(r.written)
        # nothing content-bearing anywhere in the result
        blob = json.dumps({"error": r.error, "written": r.written})
        for pii in PII_STRINGS:
            self.assertNotIn(pii, blob)

    def test_malformed_event_no_raise_no_content(self):
        for bad in (None, "not-a-dict", 42, {"payload": "not-a-dict"}, {}):
            sink = obs.ListSink()
            r = obs.emit(bad, obs.DEFAULT_OBS_CONFIG, sink=sink)
            # never raises; any written record is content-free with allow-list keys
            for rec in sink.records:
                self.assertEqual(set(rec.keys()),
                                 {"event_id", "ts", "role", "ticket_id", "tokens", "latency_ms"})

    def test_pii_injection_on_error_path_leaks_nothing(self):
        # PII in payload + a sink that raises -> zero PII in sink or result.
        sink = self.RaisingSink()
        obs.emit(PII_EVENT, obs.DEFAULT_OBS_CONFIG, sink=sink)
        # RaisingSink stores nothing; confirm the result carried no content
        r = obs.emit(PII_EVENT, obs.DEFAULT_OBS_CONFIG, sink=sink)
        self.assertIsNone(r.written)


class TestFailsOpen(unittest.TestCase):

    def test_dispatch_obs_emit_is_non_blocking(self):
        sink = obs.ListSink()
        spec = core.make_obs_spec(obs.DEFAULT_OBS_CONFIG, sink=sink)
        dec = core.dispatch(_env(PII_EVENT), registry=[spec])
        self.assertEqual(dec.exit_code, 0)           # never blocks
        self.assertNotEqual(dec.decision, "block")
        self.assertEqual(len(sink.records), 1)        # side effect happened

    def test_raising_obs_handler_fails_open_not_warn(self):
        # obs handler that raises must fail OPEN (no-op), not fail-to-warn.
        def boom(event):
            raise RuntimeError("obs handler exploded")
        spec = core.ModuleSpec("obs", lambda e: True, boom,
                               immutable_floor=False, obs=True)
        dec = core.dispatch(_env(PII_EVENT), registry=[spec])
        self.assertEqual(dec.exit_code, 0)
        self.assertNotEqual(dec.decision, "warn")
        self.assertNotEqual(dec.decision, "block")

    def test_obs_never_affects_a_floor_block(self):
        # A floor that blocks + obs on the same event -> block stands; obs still
        # runs its side effect and contributes no decision.
        sink = obs.ListSink()

        def blocking_floor(event):
            return core.ModuleResult(hit=True, module="test-floor",
                                     reasons=[{"code": "FLOOR_BLOCK"}], annotations=[])
        floor = core.ModuleSpec("test-floor", lambda e: True, blocking_floor,
                                immutable_floor=True)
        obs_spec = core.make_obs_spec(obs.DEFAULT_OBS_CONFIG, sink=sink)
        dec = core.dispatch(_env(PII_EVENT), registry=[floor, obs_spec])
        self.assertEqual(dec.decision, "block")
        self.assertIn("test-floor", dec.module)
        self.assertEqual(len(sink.records), 1)        # obs side effect still ran


class TestGitignoreAssertion(unittest.TestCase):
    """F-3: the configured sink path must be gitignored (standing check)."""

    def test_sink_path_is_gitignored(self):
        sink_path = obs.DEFAULT_OBS_CONFIG["sink_path"]
        abs_path = os.path.join(
            os.path.dirname(os.path.dirname(HARNESS)), sink_path)  # repo-root-relative
        # `git check-ignore` exits 0 iff the path is ignored.
        proc = subprocess.run(["git", "check-ignore", sink_path],
                              cwd=os.path.dirname(os.path.dirname(HARNESS)),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         "obs sink path %r is NOT gitignored (F-3)" % sink_path)

    def test_no_file_under_sink_is_tracked(self):
        root = os.path.dirname(os.path.dirname(HARNESS))
        proc = subprocess.run(["git", "ls-files", "scripts/harness/.obs"],
                              cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "",
                         "a file under the obs sink is tracked -- must never be")

    def test_library_default_creates_no_sink_dir(self):
        # The registered DEFAULT obs spec uses NullSink -> no directory created.
        obs_dir = os.path.join(HARNESS, ".obs")
        core.dispatch(_env(PII_EVENT), registry=[core.OBS_SPEC])
        self.assertFalse(os.path.exists(obs_dir),
                         "library default obs must not create a live sink dir")


def _env(event):
    return event  # events here are already full contract-v1 envelopes


if __name__ == "__main__":
    unittest.main()
