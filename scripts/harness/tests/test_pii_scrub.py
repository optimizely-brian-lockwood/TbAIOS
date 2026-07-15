"""Acceptance tests for the fail-closed PII-scrub control (HK1).

Implements the detection test matrix: 12 MUST-BLOCK rows, 9
MUST-NOT-BLOCK rows (pass byte-for-byte), and the 3 independence/hygiene tests
(F-INDEP, F-ECHO, F-HYGIENE). MUST-BLOCK and MUST-NOT-BLOCK are exercised at
BOTH boundaries (import-into-repo, egress-to-judge), per AC-1/AC-2.

Non-ASCII separators used in inputs are built with chr() so this test source
stays free of invisible literals too.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pii_scrub as P  # noqa: E402

BOUNDARIES = ("import-into-repo", "egress-to-judge")

THIN = chr(0x2009)          # U+2009 thin space
NBSP = chr(0x00A0)          # U+00A0 no-break space
IDEO = chr(0x3000)          # U+3000 ideographic space

# High-entropy >=32-char value (for D-8; assigned under a secret-labeled key).
HI_ENTROPY = "Ab3Xy9Zq1Mn7Kp2Ws5Vt8Rc4Bd6Fg0Hj2Ll4Nn6"     # 40 chars
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc_DEF-123sig"

# (id, fixture, expected-category). Each blocks at BOTH boundaries.
MUST_BLOCK = [
    ("B-1 email",        {"fields": {"body": "jane.doe@acme.com"}}, "EMAIL"),
    ("B-2 card",         {"fields": {"body": "4111111111111111"}}, "CREDIT_CARD"),
    ("B-3 card thin-sp",
        {"fields": {"body": THIN.join(["4111", "1111", "1111", "1111"])}}, "CREDIT_CARD"),
    ("B-4 card dash",    {"fields": {"body": "4111-1111-1111-1111"}}, "CREDIT_CARD"),
    ("B-5 ssn delim",    {"fields": {"body": "123-45-6789"}}, "SSN"),
    ("B-6 ssn ctx",      {"fields": {"ssn": "123456789"}}, "SSN"),
    ("B-7 aws",          {"fields": {"body": "AKIA1234567890ABCDEF"}}, "AWS_KEY"),
    ("B-8a sk-ant",      {"fields": {"body": "sk-ant-" + "a" * 24}}, "API_KEY"),
    ("B-8b ghp",         {"fields": {"body": "ghp_" + "b" * 30}}, "API_KEY"),
    ("B-8c AIza",        {"fields": {"body": "AIza" + "c" * 35}}, "API_KEY"),
    ("B-9 pem",          {"fields": {"body": "-----BEGIN RSA PRIVATE KEY-----"}}, "PRIVATE_KEY"),
    ("B-10 jwt",         {"fields": {"body": JWT}}, "JWT"),
    ("B-11 d8 entropy",  {"fields": {"api_key": HI_ENTROPY}}, "SECRET_HIGH_ENTROPY"),
    ("B-12a phone e164", {"fields": {"body": "+14155550123"}}, "PHONE"),
    ("B-12b phone nanp", {"fields": {"body": "(415) 555-0123"}}, "PHONE"),
]

# (id, fixture, label, original-value). Pass untouched, byte-for-byte.
MUST_NOT_BLOCK = [
    ("N-1 iso8601",  {"fields": {"body": "2026-07-13T09:00:00Z"}}, "fields.body", "2026-07-13T09:00:00Z"),
    ("N-2a sha40",   {"fields": {"body": "9f8c1e2a4b6d3f7e0c5a1b2d4e6f8a0c1b2d3e4f"}}, "fields.body", "9f8c1e2a4b6d3f7e0c5a1b2d4e6f8a0c1b2d3e4f"),
    ("N-2b sha7",    {"fields": {"reviewed_commit": "7b2a2d5"}}, "fields.reviewed_commit", "7b2a2d5"),
    ("N-3 semver",   {"fields": {"body": "v1.4.0 then 2.11.3-rc.1"}}, "fields.body", "v1.4.0 then 2.11.3-rc.1"),
    ("N-4 int/date", {"fields": {"body": "date 20260713 port 8443 tokens 15234"}}, "fields.body", "date 20260713 port 8443 tokens 15234"),
    ("N-5 uuid",     {"fields": {"id": "550e8400-e29b-41d4-a716-446655440000"}}, "fields.id", "550e8400-e29b-41d4-a716-446655440000"),
    ("N-6 b64 nonsecret", {"fields": {"note": HI_ENTROPY}}, "fields.note", HI_ENTROPY),
    ("N-7 bad luhn", {"fields": {"body": "4111111111111112"}}, "fields.body", "4111111111111112"),
    ("N-8 bare 10",  {"fields": {"body": "4155550123"}}, "fields.body", "4155550123"),
    ("N-9 ip",       {"fields": {"body": "192.168.1.10"}}, "fields.body", "192.168.1.10"),
]


class TestMustBlockMatrix(unittest.TestCase):
    """AC-1: every MUST-BLOCK row hard-blocks at both boundaries."""

    def test_all_rows_block_both_boundaries(self):
        for rid, fixture, expected_cat in MUST_BLOCK:
            for boundary in BOUNDARIES:
                with self.subTest(row=rid, boundary=boundary):
                    r = P.evaluate(fixture, boundary)
                    self.assertTrue(r.blocked, "%s must block" % rid)
                    self.assertIsNone(r.cleaned, "%s block carries no content" % rid)
                    self.assertIn(expected_cat, r.categories,
                                  "%s expected category %s" % (rid, expected_cat))


class TestMustNotBlockMatrix(unittest.TestCase):
    """AC-2: every MUST-NOT-BLOCK row passes byte-for-byte at both boundaries."""

    def test_all_rows_pass_unmodified_both_boundaries(self):
        for rid, fixture, label, original in MUST_NOT_BLOCK:
            for boundary in BOUNDARIES:
                with self.subTest(row=rid, boundary=boundary):
                    r = P.evaluate(fixture, boundary)
                    self.assertFalse(r.blocked, "%s must NOT block (%s)" % (rid, dict(r.categories)))
                    self.assertIsNotNone(r.cleaned)
                    self.assertEqual(r.cleaned[label], original,
                                     "%s must pass byte-for-byte (no silent redaction)" % rid)


class TestNormalizationVariants(unittest.TestCase):
    """AC-3 / QA-6: mandatory pre-detection normalization catches cards
    grouped by NBSP, thin space, and ideographic space (not only ASCII space)."""

    def test_unicode_separated_card_blocks(self):
        for label, sep in (("nbsp", NBSP), ("thin", THIN), ("ideographic", IDEO)):
            card = sep.join(["4111", "1111", "1111", "1111"])
            for boundary in BOUNDARIES:
                with self.subTest(sep=label, boundary=boundary):
                    r = P.evaluate({"fields": {"body": "card %s ok" % card}}, boundary)
                    self.assertTrue(r.blocked)
                    self.assertIn("CREDIT_CARD", r.categories)

    def test_ssn_with_unicode_and_context_blocks(self):
        ssn = NBSP.join(["123", "45", "6789"])
        r = P.evaluate({"fields": {"ssn_value": ssn}}, "egress-to-judge")
        self.assertTrue(r.blocked)
        self.assertIn("SSN", r.categories)


class TestFullSurfaceAndKeys(unittest.TestCase):
    """Per-leaf full-surface coverage, keys included (no cross-leaf reassembly)."""

    def test_pii_in_filename_blocks(self):
        r = P.evaluate({"filename": "jane.doe@acme.com-review.md",
                        "fields": {"note": "ok"}}, "import-into-repo")
        self.assertTrue(r.blocked)
        self.assertIn("filename", r.surfaces_hit)

    def test_pii_in_commit_message_blocks(self):
        r = P.evaluate({"fields": {"note": "ok"},
                        "commit_message": "import for +14155550123"}, "import-into-repo")
        self.assertTrue(r.blocked)
        self.assertIn("commit_message", r.surfaces_hit)

    def test_pii_in_nested_key_blocks(self):
        r = P.evaluate({"fields": {"jane.doe@acme.com": "benign"}}, "import-into-repo")
        self.assertTrue(r.blocked)
        self.assertIn("EMAIL", r.categories)

    def test_clean_fixture_import_renames_file(self):
        r = P.evaluate({"filename": "notes.md", "fields": {"note": "all clear"}},
                       "import-into-repo")
        self.assertFalse(r.blocked)
        self.assertTrue(r.cleaned_filename.startswith("fixture-"))
        self.assertNotIn("notes", r.cleaned_filename)


class TestCardTokenDedupAndLongIds(unittest.TestCase):
    """Clean-token card detection + n-1 dedup + the QA-10 guard.

    A card is detected only as a FULL contiguous 13-19-digit run (after
    separator normalization). Embedded/adjacent-run extraction is intentionally
    NOT machine-scope -- it is inherently low-precision (QA-10 over-block on long
    numeric IDs) and is left to human recall (same bucket as QA-7/QA-9).
    """

    CARD = "4111111111111111"

    def test_scrubber_alone_catches_clean_token_card(self):
        # Validates the _scr_luhn parity fix: with the scanner replaced by a
        # no-op, the SCRUBBER must independently detect a clean-token card.
        class NoScan:
            def scan(self, text, key_context=""):
                return []
        for boundary in BOUNDARIES:
            with self.subTest(boundary=boundary):
                r = P.evaluate({"fields": {"body": self.CARD}}, boundary, scanner=NoScan())
                self.assertTrue(r.blocked)
                self.assertIn("CREDIT_CARD", r.categories)

    def test_clean_token_card_blocks_both_boundaries(self):
        for boundary in BOUNDARIES:
            with self.subTest(boundary=boundary):
                r = P.evaluate({"fields": {"body": self.CARD}}, boundary)
                self.assertTrue(r.blocked)
                self.assertIn("CREDIT_CARD", r.categories)

    def test_dedup_count_is_one_for_single_card(self):
        # n-1: one standalone card detected by both engines counts once.
        r = P.evaluate({"fields": {"body": self.CARD}}, "egress-to-judge")
        self.assertEqual(r.categories["CREDIT_CARD"], 1)

    def test_luhn_invalid_16_digit_passes(self):
        r = P.evaluate({"fields": {"body": "4111111111111112"}}, "egress-to-judge")
        self.assertFalse(r.blocked)
        self.assertEqual(r.cleaned["fields.body"], "4111111111111112")

    def test_long_numeric_ids_pass_byte_for_byte(self):
        # QA-10 guard: long non-card numeric IDs must NOT be over-blocked by a
        # sliding-window card extractor; they pass byte-for-byte at both
        # boundaries. (16-digit non-Luhn, 24-digit, 40-digit.)
        ids = ["1234567890123456", "1" * 24, "9" * 40,
               "80000000000000000000000000000000000000"]
        for val in ids:
            for boundary in BOUNDARIES:
                with self.subTest(val=val[:8] + "...", boundary=boundary):
                    r = P.evaluate({"fields": {"id": val}}, boundary)
                    self.assertFalse(r.blocked, "%s must not block (%s)" % (val, dict(r.categories)))
                    self.assertEqual(r.cleaned["fields.id"], val)

    def test_embedded_card_is_human_recall_not_machine(self):
        # Pins the ratified contract: a card ADJACENT to another digit run in the
        # same leaf (merged into an over-length run) is deliberately NOT caught
        # by the machine (left to human recall). If a future change makes
        # the machine catch it, this test flags that the contract changed.
        r = P.evaluate({"fields": {"body": "Card %s 20260713 refund" % self.CARD}},
                       "egress-to-judge")
        self.assertFalse(r.blocked)
        self.assertEqual(r.cleaned["fields.body"], "Card %s 20260713 refund" % self.CARD)


class TestFIndep(unittest.TestCase):
    """F-INDEP: blind the SCRUBBER to a class; the INDEPENDENT SCANNER must
    still catch and block it (proves the two engines share no blind spot)."""

    def test_scrubber_blind_to_jwt_scanner_still_blocks(self):
        blinded = P.Scrubber(disabled_rules={"JWT"})
        r = P.evaluate({"fields": {"body": JWT}}, "egress-to-judge", scrubber=blinded)
        self.assertTrue(r.blocked)
        self.assertIn("JWT", r.categories)

    def test_scrubber_blind_to_card_scanner_still_blocks(self):
        blinded = P.Scrubber(disabled_rules={"CREDIT_CARD"})
        r = P.evaluate({"fields": {"body": "4111 1111 1111 1111"}},
                       "import-into-repo", scrubber=blinded)
        self.assertTrue(r.blocked)
        self.assertIn("CREDIT_CARD", r.categories)

    def test_scrubber_blind_to_email_scanner_still_blocks(self):
        blinded = P.Scrubber(disabled_rules={"EMAIL"})
        r = P.evaluate({"fields": {"body": "reach analyst@vendorcorp.io"}},
                       "egress-to-judge", scrubber=blinded)
        self.assertTrue(r.blocked)
        self.assertIn("EMAIL", r.categories)

    def test_engines_do_not_share_rules(self):
        import inspect
        scanner_src = inspect.getsource(P.Scanner)
        # The scanner references none of the scrubber's pattern constants/class.
        self.assertNotIn("_SCRUB_", scanner_src)
        self.assertNotIn("Scrubber", scanner_src)
        scrubber_src = inspect.getsource(P.Scrubber)
        self.assertNotIn("_SCAN_", scrubber_src)


class TestFEcho(unittest.TestCase):
    """F-ECHO (no-PII-echo): matched value appears in NO output channel."""

    def test_no_matched_value_in_any_channel(self):
        for rid, fixture, _cat in MUST_BLOCK:
            r = P.evaluate(fixture, "egress-to-judge")
            blob = (repr(r.reason_summary()) + repr(r.annotations())
                    + repr(list(r.categories)) + repr(r.surfaces_hit))
            for surface in fixture.values():
                values = surface.values() if isinstance(surface, dict) else [surface]
                for v in values:
                    if isinstance(v, str) and len(v) >= 6:
                        with self.subTest(row=rid):
                            self.assertNotIn(v, blob,
                                             "%s: matched value echoed in output" % rid)

    def test_reason_shape_is_category_and_count_only(self):
        r = P.evaluate({"fields": {"body": "jane.doe@acme.com"}}, "egress-to-judge")
        for reason in r.reason_summary():
            self.assertEqual(reason["code"], "PII_DETECTED")
            self.assertIn("category", reason)
            self.assertIn("count", reason)
            self.assertNotIn("value", reason)

    def test_caller_supplied_key_reported_as_other(self):
        # m-2 carried forward: a caller-added top-level key is reported under
        # "other", never echoed raw.
        r = P.evaluate({"jane.doe@acme.com": {"note": "x"}}, "import-into-repo")
        self.assertTrue(r.blocked)
        blob = repr(r.surfaces_hit) + repr(r.annotations())
        self.assertNotIn("jane.doe@acme.com", blob)
        self.assertIn("other", r.surfaces_hit)


class TestFHygiene(unittest.TestCase):
    """F-HYGIENE: pii_scrub.py source contains no non-ASCII literals; every
    non-ASCII code point is an explicit backslash-u escape."""

    def test_source_is_pure_ascii(self):
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pii_scrub.py")
        with open(src_path, "rb") as fh:
            data = fh.read()
        offenders = [(i, b) for i, b in enumerate(data) if b >= 0x80]
        self.assertEqual(offenders, [],
                         "pii_scrub.py has %d non-ASCII byte(s) -- use explicit "
                         "escapes, no invisible literals" % len(offenders))


class TestFailClosed(unittest.TestCase):
    """AC-5: scanner/scrubber error and invalid boundary -> block."""

    def test_invalid_boundary_blocks(self):
        r = P.evaluate({"fields": {"note": "clean"}}, "some-other-boundary")
        self.assertTrue(r.blocked)
        self.assertIn("INVALID_BOUNDARY", r.categories)

    def test_scanner_error_blocks(self):
        class Boom:
            def scan(self, text, key_context=""):
                raise RuntimeError("boom")
        r = P.evaluate({"fields": {"note": "clean"}}, "import-into-repo", scanner=Boom())
        self.assertTrue(r.blocked)
        self.assertIsNone(r.cleaned)
        self.assertIn("SCRUB_ERROR", r.categories)


if __name__ == "__main__":
    unittest.main()
