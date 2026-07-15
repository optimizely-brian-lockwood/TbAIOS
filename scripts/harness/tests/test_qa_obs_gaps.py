"""QA-authored scratch tests (independent adversarial verification, increment 5).

These are NOT part of the developer's delivered suite for obs.py (H-OBS).
Findings write-up: docs/dev-team/qa/2026-07-14-harness-increment5-qa.md
(OB-1, OB-2, OB-3).

QA does not modify contract.py / core.py / obs.py to make these pass.
"""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import obs  # noqa: E402


class OB1_TicketIdHasNoLengthBound(unittest.TestCase):
    """Finding OB-1 (LOW) -- STATUS: FIXED, re-verified 2026-07-14. `_valid_str`
    now takes a `max_len` bound (default `_MAX_ID_LEN = 64`, matching the
    bound already applied to `event_id`) and rejects anything longer before
    even checking the shape pattern. Re-derived independently below: a
    10,001-character shape-valid `ticket_id` -> `null`; a normal `ticket_id`
    ("HN-2") still passes; the boundary is exact -- a 64-character shape-valid
    value is accepted, a 65-character one is rejected.

    Original filing: `event_id` and `role` both had an enforced maximum
    length; `ticket_id`'s default pattern had none at all, so a shape-valid
    but arbitrarily long string was accepted and stored verbatim. Not a PII
    leak (the character set excluded `@`/spaces/free text), but a
    data-integrity/log-bloat inconsistency between sibling fields.
    """

    def test_oversized_ticket_id_now_rejected_to_null(self):
        big = "A" * 5000 + "-" + "9" * 5000
        r = obs.emit({"payload": {"ticket_id": big}}, obs.DEFAULT_OBS_CONFIG,
                     sink=obs.ListSink())
        self.assertIsNone(r.written["ticket_id"])

    def test_normal_ticket_id_still_accepted(self):
        r = obs.emit({"payload": {"ticket_id": "HN-2"}}, obs.DEFAULT_OBS_CONFIG,
                     sink=obs.ListSink())
        self.assertEqual(r.written["ticket_id"], "HN-2")

    def test_boundary_is_exact_64_accepted_65_rejected(self):
        s64 = "A" * 10 + "-" + "9" * 53   # 10 + 1 + 53 = 64
        s65 = "A" * 10 + "-" + "9" * 54   # 65
        self.assertEqual(len(s64), 64)
        self.assertEqual(len(s65), 65)
        r64 = obs.emit({"payload": {"ticket_id": s64}}, obs.DEFAULT_OBS_CONFIG,
                       sink=obs.ListSink())
        r65 = obs.emit({"payload": {"ticket_id": s65}}, obs.DEFAULT_OBS_CONFIG,
                       sink=obs.ListSink())
        self.assertEqual(r64.written["ticket_id"], s64)
        self.assertIsNone(r65.written["ticket_id"])

    def test_control_event_id_is_bounded(self):
        # Isolates OB-1's original finding: event_id's existing bound
        # correctly rejects an oversized value (unchanged behavior).
        r = obs.emit({"event_id": "A" * 5000, "payload": {}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertIsNone(r.written["event_id"])


class OB2_NonFiniteFloatsProduceNonStandardJson(unittest.TestCase):
    """Finding OB-2 (LOW) -- STATUS: FIXED, re-verified 2026-07-14. `_valid_num`
    (and `_valid_ts`'s numeric branch) now require `math.isfinite(value)` in
    addition to `value >= 0`. Re-derived independently below: `float('inf')`,
    `float('-inf')`, and `float('nan')` all now resolve to `null`; a normal
    finite positive number still passes; the full emitted record, once
    serialized with `json.dumps`, contains neither the literal token
    `Infinity` nor `NaN` anywhere -- confirmed by searching the serialized
    output, not just the individual field values.

    Original filing: `float('inf') >= 0` is `True` in Python, so positive
    infinity passed validation and serialized to the non-standard JSON token
    `Infinity` (not valid per RFC 8259). `float('nan') >= 0` was already
    `False` (NaN comparisons are always false), so NaN was already correctly
    rejected before this fix; the fix closes the remaining infinity case
    (and negative infinity, confirmed below) with the same `isfinite` check.
    """

    def test_positive_infinity_now_rejected_to_null(self):
        r = obs.emit({"payload": {"latency_ms": float("inf")}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertIsNone(r.written["latency_ms"])

    def test_negative_infinity_also_rejected_to_null(self):
        r = obs.emit({"payload": {"tokens": {"in": float("-inf"), "out": 1}}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertIsNone(r.written["tokens"]["in"])

    def test_nan_still_correctly_rejected(self):
        r = obs.emit({"payload": {"latency_ms": float("nan")}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertIsNone(r.written["latency_ms"])

    def test_emitted_record_is_strict_rfc8259_json_no_infinity_or_nan_tokens(self):
        r = obs.emit({"payload": {"latency_ms": float("inf"),
                                  "tokens": {"in": float("nan"), "out": float("-inf")}}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        blob = json.dumps(r.written)
        self.assertNotIn("Infinity", blob)
        self.assertNotIn("NaN", blob)

    def test_normal_finite_numbers_still_accepted(self):
        r = obs.emit({"payload": {"latency_ms": 1500, "tokens": {"in": 10, "out": 20}}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertEqual(r.written["latency_ms"], 1500)
        self.assertEqual(r.written["tokens"], {"in": 10, "out": 20})


class OB3_ShapeOnlyValidationCannotDistinguishANameFromAnIdentifier(
    unittest.TestCase
):
    """Finding OB-3 (LOW, informational) -- role slug half RECONCILED
    2026-07-14 to the ratified strict-enum resolution (F-OBS-1, Code Review +
    Security). `_valid_role` no longer has a free-text/bounded-slug fallback
    at all -- `role` must be an exact member of the closed `role_enum`
    config list, full stop. A name-shaped slug that used to pass
    (`"jane-doe"`) now correctly resolves to `null`, the same as any other
    non-enum string. This closes the `role` half of OB-3's original
    "shape-only validation can't distinguish a name from an identifier"
    concern outright, by removing the shape-only path for `role` entirely
    rather than trying to make the shape check smarter.

    The `ticket_id` half of OB-3 is UNCHANGED and remains an accepted,
    informational residual: `ticket_id`'s pattern is still shape-based (now
    also length-bounded per OB-1, but still not semantic), so a name
    rendered in the `Letters-Digits` shape (`"JohnDoe-123"`) still passes
    through unmodified. This is intentional and was not part of this round's
    remediation -- `ticket_id` inherently needs to accept arbitrary
    engagement-specific identifiers a closed enum cannot express, unlike
    `role`, which has a genuinely closed, enumerable universe of values
    (the 11 generic dev-team roles + engagement extensions). Filed for
    visibility only, consistent with the same shape-vs-semantic trade-off
    already accepted elsewhere in this engagement (e.g. security-gate's
    `ticket_id` field).
    """

    def test_name_shaped_role_slug_now_correctly_rejected_to_null(self):
        # RECONCILED: role is now a strict closed enum (F-OBS-1); the old
        # bounded-slug fallback that let "jane-doe" through is gone.
        for name_slug in ("jane-doe", "john-smith", "sam-jones"):
            with self.subTest(role=name_slug):
                r = obs.emit({"payload": {"role": name_slug}},
                             obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
                self.assertIsNone(
                    r.written["role"],
                    "role must be null for a non-enum, name-shaped value "
                    "under the strict-enum resolution -- found %r"
                    % r.written["role"],
                )

    def test_control_real_enum_role_still_accepted(self):
        # Confirms the strict-enum path still works for genuine roles.
        r = obs.emit({"payload": {"role": "security-engineer"}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertEqual(r.written["role"], "security-engineer")

    def test_name_shaped_ticket_id_still_passes_through_unchanged_accepted_residual(self):
        # UNCHANGED: ticket_id remains shape-based, not enum-based -- this is
        # intentional (see class docstring), not part of this round's fix.
        r = obs.emit({"payload": {"ticket_id": "JohnDoe-123"}},
                     obs.DEFAULT_OBS_CONFIG, sink=obs.ListSink())
        self.assertEqual(r.written["ticket_id"], "JohnDoe-123")


if __name__ == "__main__":
    unittest.main()
