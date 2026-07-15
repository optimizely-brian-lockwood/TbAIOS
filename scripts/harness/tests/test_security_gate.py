"""Tests for the security-gate module (HK2).

Covers sign-off verification (content half + binding),
independent derivation + no downward spoof + ambiguity->sensitive, the
fail-closed decision, the immutable-floor precedence guarantee (mirrors the
pii-scrub test), and no-PII-echo.

The gate is exercised through an explicit test CONFIG (not the built-in default)
to prove the mechanism is fully config-driven.
"""

import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contract as C          # noqa: E402
import core                    # noqa: E402
import security_gate as SG     # noqa: E402

CONFIG = {
    "gate_event_types": ["pre-pr", "feature-merge"],
    "ambiguous_flag": "sensitive",
    "safe_globs": ["docs/**", "**/*.md", "tests/**"],
    "sensitivity_rules": [
        {"flag": "pii",
         "path_globs": ["**/*user*", "**/*customer*"],
         "content_signals": ["email", "ssn"]},
        {"flag": "authn",
         "path_globs": ["**/auth/**", "**/*password*"],
         "content_signals": ["password", "oauth"]},
        {"flag": "external-input",
         "path_globs": ["**/api/**"],
         "content_signals": ["request.body"]},
    ],
}


def h(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def f(path, content=None, content_hash=None):
    e = {"path": path}
    if content is not None:
        e["content"] = content
    if content_hash is not None:
        e["content_hash"] = content_hash
    return e


def cs(*files):
    return {"files": list(files)}


def record(ticket_id, flags, artifacts, verdict="APPROVED", conditions="all-closed"):
    return {
        "review_id": "SEC-TEST-1",
        "ticket_id": ticket_id,
        "verdict": verdict,
        "sensitivity_flags_covered": list(flags),
        "reviewed_artifact": [{"path": p, "content_hash": hh} for p, hh in artifacts],
        "conditions_status": conditions,
        "reviewer": "security-engineer",
        "date": "2026-07-14",
    }


def payload(ticket_id, declared, files, signoff=None):
    p = {"ticket": {"ticket_id": ticket_id, "sensitivity_flags": list(declared)},
         "changeset": cs(*files)}
    if signoff is not None:
        p["signoff_record"] = signoff
    return p


class TestMustBlock(unittest.TestCase):

    def test_sensitive_without_signoff_blocks(self):
        p = payload("T1", ["pii"], [f("src/user_profile.py", content="load the email field")])
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.required_flags, ["pii"])

    def test_sensitivity_spoofed_downward_blocks(self):
        # declared [] but content/path derive pii -> required still {pii}.
        p = payload("T2", [], [f("src/customer_record.py", content="store email and ssn")])
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertIn("pii", r.required_flags)

    def test_declared_flag_not_derived_still_requires_coverage(self):
        # self-declaration ADDS: a clean doc change declared authn needs sign-off.
        p = payload("T3", ["authn"], [f("docs/notes.md", content="just notes")])
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertIn("authn", r.required_flags)

    def test_signoff_does_not_cover_a_derived_flag_blocks(self):
        pii_file = f("src/user_profile.py", content="email field")
        auth_file = f("src/auth/login.py", content="password check")
        rec = record("T4", ["pii"], [   # covers pii only, not authn
            ("src/user_profile.py", h("email field")),
            ("src/auth/login.py", h("password check")),
        ])
        p = payload("T4", [], [pii_file, auth_file], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "SIGNOFF_FLAG_UNCOVERED")

    def test_post_review_change_invalidates_signoff(self):
        # record bound an OLD hash; changeset now has NEW content -> drift.
        rec = record("T5", ["pii"], [("src/user_profile.py", h("OLD reviewed content email"))])
        p = payload("T5", [], [f("src/user_profile.py", content="NEW content email leaked")],
                    signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "APPROVAL_DRIFT")

    def test_new_sensitive_file_not_in_signoff_blocks(self):
        # a sensitive file added after review is unbound -> unreviewed surface.
        rec = record("T6", ["pii"], [("src/user_profile.py", h("email"))])
        p = payload("T6", [], [
            f("src/user_profile.py", content="email"),
            f("src/customer_new.py", content="email and ssn"),   # unbound
        ], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "SENSITIVE_SURFACE_UNREVIEWED")

    def test_ambiguous_sensitivity_blocks(self):
        # code file, no content available, not a known-safe path -> ambiguous.
        p = payload("T7", [], [f("src/engine.py")])   # no content, no hash
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertIn("sensitive", r.required_flags)

    def test_malformed_record_blocks(self):
        bad = {"ticket_id": "T8", "verdict": "APPROVED"}   # missing required fields
        p = payload("T8", ["pii"], [f("src/user_x.py", content="email")], signoff=bad)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "SIGNOFF_MALFORMED")

    def test_ticket_mismatch_blocks(self):
        rec = record("OTHER", ["pii"], [("src/user_x.py", h("email"))])
        p = payload("T9", [], [f("src/user_x.py", content="email")], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "SIGNOFF_TICKET_MISMATCH")

    def test_conditions_open_blocks(self):
        rec = record("T10", ["pii"], [("src/user_x.py", h("email"))],
                     verdict="APPROVED", conditions="open")
        p = payload("T10", [], [f("src/user_x.py", content="email")], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "SIGNOFF_CONDITIONS_OPEN")

    def test_missing_ticket_descriptor_blocks(self):
        r = SG.evaluate({"changeset": cs(f("docs/x.md", content="ok"))}, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "TICKET_MISSING")


class TestMustNotBlock(unittest.TestCase):

    def test_non_sensitive_safe_path_allows(self):
        p = payload("N1", [], [f("docs/readme.md", content="hello world")])
        r = SG.evaluate(p, CONFIG)
        self.assertFalse(r.blocked)
        self.assertEqual(r.required_flags, [])

    def test_non_sensitive_inspected_code_allows(self):
        # content present, matches no rule -> inspected-clean -> non-sensitive.
        p = payload("N2", [], [f("src/math_util.py", content="def add(a, b): return a + b")])
        r = SG.evaluate(p, CONFIG)
        self.assertFalse(r.blocked)

    def test_sensitive_with_valid_covering_current_signoff_allows(self):
        content = "customer email address handling"
        rec = record("N3", ["pii"], [("src/user_profile.py", h(content))])
        p = payload("N3", [], [f("src/user_profile.py", content=content)], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertFalse(r.blocked, r.reasons)

    def test_declared_superset_of_derived_allowed_when_covered(self):
        content = "email"
        rec = record("N4", ["pii", "authn"], [("src/user_x.py", h(content))])
        p = payload("N4", ["authn"], [f("src/user_x.py", content=content)], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertFalse(r.blocked, r.reasons)


def sg_envelope(pl, event_type="pre-pr", requested_mode="block"):
    return {
        "contract_version": "1.0", "event_id": "evt-sg",
        "event_type": event_type, "occurred_at": "2026-07-14T00:00:00Z",
        "harness": {"name": "test"}, "requested_mode": requested_mode,
        "payload": pl,
    }


class TestFloorPrecedence(unittest.TestCase):
    """The security-gate is an immutable floor: no requested_mode / flip_state
    can soften a block (mirrors the pii-scrub floor test)."""

    def _sensitive_payload_default_config(self):
        # DEFAULT_CONFIG derives authn from an auth path + password content.
        return {"ticket": {"ticket_id": "F1", "sensitivity_flags": []},
                "changeset": cs(f("src/auth/login.py", content="password check"))}

    def test_requested_mode_warn_cannot_soften(self):
        ev = sg_envelope(self._sensitive_payload_default_config(), requested_mode="warn")
        dec = core.dispatch(ev)
        self.assertEqual(dec.module, "security-gate")
        self.assertEqual(dec.decision, "block")
        self.assertEqual(dec.exit_code, C.EXIT_BLOCK)

    def test_flip_state_cannot_soften(self):
        ev = sg_envelope(self._sensitive_payload_default_config())
        dec = core.dispatch(ev, flip_state={"security-gate": "warn"})
        self.assertEqual(dec.decision, "block")

    def test_feature_merge_also_gated(self):
        ev = sg_envelope(self._sensitive_payload_default_config(),
                         event_type="feature-merge")
        dec = core.dispatch(ev)
        self.assertEqual(dec.module, "security-gate")
        self.assertEqual(dec.decision, "block")

    def test_non_sensitive_allows_through_core(self):
        pl = {"ticket": {"ticket_id": "F2", "sensitivity_flags": []},
              "changeset": cs(f("docs/guide.md", content="hello"))}
        dec = core.dispatch(sg_envelope(pl))
        self.assertEqual(dec.decision, "allow")


class TestContentAbsenceFailsClosed(unittest.TestCase):
    """SG-1 + M-1: content that is None, empty, or whitespace-only on a
    sensitive/unclassifiable path must fail closed (never 'inspected clean',
    never an adapter-supplied current-side hash)."""

    def test_empty_string_content_is_ambiguous(self):
        p = payload("A1", [], [f("src/engine.py", content="")])
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertIn("sensitive", r.required_flags)

    def test_whitespace_only_content_is_ambiguous(self):
        p = payload("A2", [], [f("src/engine.py", content="  \n\t ")])
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertIn("sensitive", r.required_flags)

    def test_usable_content_no_signal_still_allows(self):
        # regression guard: genuinely inspected clean content still passes.
        p = payload("A3", [], [f("src/engine.py", content="def add(a, b): return a + b")])
        r = SG.evaluate(p, CONFIG)
        self.assertFalse(r.blocked)

    def test_m1_content_hash_without_content_on_sensitive_path_blocks(self):
        # A path-sensitive file supplying only an adapter content_hash (no real
        # content) must NOT pass drift detection -- current hash is core-computed
        # from content, so no content => unhashable => block.
        rec = record("A4", ["pii"], [("src/user_x.py", "deadbeef")])
        p = payload("A4", [], [f("src/user_x.py", content_hash="deadbeef")], signoff=rec)
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        self.assertEqual(r.reasons[0]["code"], "SENSITIVE_FILE_UNHASHABLE")


class TestAllFloorsEvaluated(unittest.TestCase):
    """SG-2: adding a `boundary` key must not route a security-gate-shaped event
    away from the gate. dispatch evaluates ALL matching floors; the gate still
    blocks the sensitive, unsigned change."""

    def _sensitive_unsigned(self):
        return {"ticket": {"ticket_id": "SG2", "sensitivity_flags": []},
                "changeset": cs(f("src/auth/login.py",
                                   content="password = input(); grant_admin()"))}

    def test_boundary_key_does_not_bypass_gate(self):
        p = dict(self._sensitive_unsigned())
        p["boundary"] = "egress-to-judge"    # also matches pii-scrub floor
        dec = core.dispatch(sg_envelope(p))
        self.assertEqual(dec.decision, "block")
        self.assertIn("security-gate", dec.module)   # the gate DID run

    def test_baseline_without_boundary_still_blocks(self):
        dec = core.dispatch(sg_envelope(self._sensitive_unsigned()))
        self.assertEqual(dec.module, "security-gate")
        self.assertEqual(dec.decision, "block")

    def test_scrub_shaped_payload_on_gate_type_blocks(self):
        # SG-3 CLOSED (Security ruled option b): a scrub-shaped payload (no
        # ticket/changeset) arriving on a GATE event_type is a malformed gate
        # event -> BLOCK. `boundary` is not honored on a gate event_type, so it
        # cannot route around the gate.
        pl = {"boundary": "import-into-repo", "fixture": {"fields": {"note": "all clear"}}}
        dec = core.dispatch(sg_envelope(pl))     # sg_envelope uses pre-pr
        self.assertEqual(dec.decision, "block")
        self.assertIn("security-gate", dec.module)

    def test_scrub_on_data_boundary_event_type_runs_pii_scrub(self):
        # The correct home for a scrub: a DATA-BOUNDARY event type -> only the
        # pii-scrub floor runs (clean -> allow). The gate does not claim it.
        pl = {"fixture": {"fields": {"note": "all clear"}}}
        dec = core.dispatch(sg_envelope(pl, event_type="import-into-repo"))
        self.assertEqual(dec.module, "pii-scrub")
        self.assertEqual(dec.decision, "allow")


class TestOptionalPiiDetectors(unittest.TestCase):
    """Optional F-3 strengthening (config: use_pii_detectors) -- off by default,
    on demand reuses the pii_scrub detectors so a real PII shape the keyword
    list misses is still derived as sensitive."""

    def test_real_email_shape_caught_only_with_detectors_on(self):
        # 'john@acme.com' does NOT contain the literal keyword 'email'.
        files = [f("src/random_service.py", content="notify user at john@acme.com")]
        base = {"gate_event_types": ["pre-pr"], "ambiguous_flag": "sensitive",
                "safe_globs": [], "sensitivity_rules": [
                    {"flag": "pii", "path_globs": ["**/*user*"], "content_signals": ["email"]}]}
        # detectors OFF: path not user*, content has no 'email' keyword -> not pii
        off = SG.evaluate(payload("D1", [], files), dict(base, use_pii_detectors=False))
        self.assertNotIn("pii", off.required_flags)
        # detectors ON: pii_scrub sees the address shape -> pii -> needs sign-off
        on = SG.evaluate(payload("D2", [], files), dict(base, use_pii_detectors=True))
        self.assertTrue(on.blocked)
        self.assertIn("pii", on.required_flags)


class TestNoEcho(unittest.TestCase):
    """cond 7: no raw changeset content or file paths in any output channel."""

    def test_content_and_path_absent_from_reasons(self):
        secret = "SuperSecretToken_ZZ99"
        path = "src/auth/oauth_handler.py"
        p = payload("E1", [], [f(path, content="password = %s" % secret)])
        r = SG.evaluate(p, CONFIG)
        self.assertTrue(r.blocked)
        blob = (repr(r.reason_summary()) + repr(r.annotations())
                + repr(r.required_flags))
        self.assertNotIn(secret, blob)
        self.assertNotIn(path, blob)

    def test_reasons_are_codes_and_flags_only(self):
        p = payload("E2", [], [f("src/user_x.py", content="email")])
        r = SG.evaluate(p, CONFIG)
        for reason in r.reason_summary():
            self.assertIn("code", reason)
            for k in reason:
                self.assertIn(k, ("code", "flags"))


class TestConfigDriven(unittest.TestCase):
    """The mechanism carries no engagement-specific rules; the sample config
    file loads and drives detection."""

    def test_sample_config_loads_and_drives(self):
        sample = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "security_gate_config.sample.json")
        cfg = SG.load_config(sample)
        self.assertIn("sensitivity_rules", cfg)
        # a path only sensitive under the sample's rules
        p = payload("C1", [], [f("src/api/webhook.py")])   # no content -> ambiguous too
        r = SG.evaluate(p, cfg)
        self.assertTrue(r.blocked)

    def test_empty_ruleset_still_ambiguity_fail_closed(self):
        # With no rules AND no safe globs, an un-inspectable file is ambiguous.
        cfg = {"gate_event_types": ["pre-pr"], "ambiguous_flag": "sensitive",
               "safe_globs": [], "sensitivity_rules": []}
        r = SG.evaluate(payload("C2", [], [f("anything.bin")]), cfg)
        self.assertTrue(r.blocked)
        self.assertIn("sensitive", r.required_flags)


if __name__ == "__main__":
    unittest.main()
