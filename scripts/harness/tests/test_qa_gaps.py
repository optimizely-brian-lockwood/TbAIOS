"""QA-authored scratch tests (independent verification, 2026-07-13).

These are NOT part of the developer's delivered suite. They encode gaps found
during independent QA probing of INCREMENT 1 (contract.py / core.py /
pii_scrub.py). Each test asserts the SECURE/SPEC'D behavior. Where a test
currently FAILS, that failure is the reproduction of a filed bug -- do not
"fix" it by loosening the assertion; the assertion encodes the acceptance
criterion / ADR requirement. See docs/dev-team/qa/2026-07-13-harness-increment1-qa.md
for the bug write-up (QA-1, QA-2, ... QA-10).

QA does not modify contract.py / core.py / pii_scrub.py to make these pass.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contract as C  # noqa: E402
import core  # noqa: E402
import pii_scrub as P  # noqa: E402


class QA1_SpaceSeparatedNumericPIISurvives(unittest.TestCase):
    """Bug QA-1 (CRITICAL): a real card/SSN number written with SPACE-separated
    digit groups is scrubbed by NEITHER stage. It reaches `cleaned` verbatim,
    which is the artifact the caller commits/egresses on `allow`. This directly
    violates the no-raw-PII-in-artifact intent (no raw PII in the artifact that
    proceeds) and the "does a real PII value ever survive as non-[redacted]"
    bar.

    Root cause: Scrubber PHONE/CUSTOMER_ID regexes' character classes do not
    include a space separator (`[\\d\\-().]`), and Scanner's digit-run counter
    treats any non `-()+` character -- including space -- as a run-reset.

    STATUS (post rebuild): FIXED and re-verified. Left as a permanent
    regression test -- passes against the current Scrubber/Scanner
    (D-2 card / D-3 SSN with pre-detection normalization).
    """

    def test_space_separated_card_number_not_redacted_and_not_blocked(self):
        card = "4111 1111 1111 1111"
        fixture = {"fields": {"body": "card on file %s for refund" % card}}
        r = P.evaluate(fixture, "egress-to-judge")
        # SECURE expectation: either the scrubber redacts it, or the scanner
        # blocks it. Today: neither -- r.blocked is False and the raw card
        # number is present verbatim in the cleaned artifact.
        if not r.blocked:
            self.assertNotIn(card, r.cleaned["fields.body"],
                              "raw card number reached the cleaned/allowed artifact verbatim")
        # This assertion is the one that currently fails end-to-end:
        self.assertTrue(
            r.blocked or card not in r.cleaned.get("fields.body", ""),
            "space-separated PII must not survive un-redacted in an allowed artifact",
        )

    def test_space_separated_ssn_not_redacted_and_not_blocked(self):
        ssn = "123 45 6789"
        fixture = {"fields": {"body": "ssn %s on file" % ssn}}
        r = P.evaluate(fixture, "import-into-repo")
        self.assertTrue(
            r.blocked or ssn not in r.cleaned.get("fields.body", ""),
            "space-separated SSN must not survive un-redacted in an allowed artifact",
        )


class QA2_CoreCrashOnInfraErrorDoesNotFailClosed(unittest.TestCase):
    """Bug QA-2 (HIGH): the portability ADR's own failure table states 'Core
    crashes mid-eval -> security-gate + pii-scrub -> block (fail-closed)', and
    core.run()'s docstring states 'Never raises'. Neither holds for an
    infra-level failure during envelope validation (e.g. the checked-in
    hook-event.schema.json becoming unreadable) -- run() raises an uncaught
    exception instead of returning a block Decision.

    STATUS: FIXED and re-verified (core.run() wraps dispatch() in try/except,
    fail-closed for enforcement, fail-open for obs-emit). Left as a permanent
    regression test.
    """

    def test_run_never_raises_even_if_schema_unreadable(self):
        orig = C.SCHEMA_PATH
        import pathlib
        C.SCHEMA_PATH = pathlib.Path("this-file-does-not-exist.json")
        ev = {
            "contract_version": "1.0",
            "event_id": "evt-qa2",
            "event_type": "pre-pr",
            "occurred_at": "2026-07-13T09:00:00Z",
            "harness": {"name": "test"},
            "requested_mode": "block",
            "payload": {},
        }
        try:
            out, err, code = core.run(json.dumps(ev))
            self.assertNotEqual(code, 0, "infra error on an enforcement event must resolve to block, not allow")
        except Exception as exc:  # noqa: BLE001
            self.fail(
                "core.run() raised %r instead of returning a fail-closed Decision "
                "(violates its own 'never raises' contract and the portability ADR "
                "failure table 'core crashes mid-eval -> block')" % exc
            )
        finally:
            C.SCHEMA_PATH = orig
# ==========================================================================
# RE-VERIFICATION ROUND 2 (2026-07-13, same day, post senior-dev fix) -- QA-1
# and QA-2 above now PASS unmodified against the fixed implementation (see
# docs/dev-team/qa/2026-07-13-harness-increment1-qa.md, "Re-verification").
# The classes below are NEW findings surfaced while independently pushing
# further on the same failure classes, per the coordinator's explicit ask.
# ==========================================================================


class QA6_UnicodeWhitespaceSeparatedNumericPIISurvives(unittest.TestCase):
    """Bug QA-6 (HIGH, new): the QA-1 fix bridges ASCII space/tab/dot/dash/
    parens/plus (plus, incidentally, U+00A0 NBSP -- see note below) but NOT
    other common Unicode space separators. A card/SSN number delimited by an
    en space (U+2002), em space (U+2003), thin space (U+2009), figure space
    (U+2007), or ideographic/fullwidth space (U+3000) reproduces the exact
    same failure mode as the original QA-1: neither stage fires, and the raw
    number survives verbatim in the artifact that proceeds on `allow`.

    NBSP (U+00A0) does NOT reproduce this -- but only because a literal NBSP
    character is embedded directly inside the `_DIGIT_BRIDGE` string literal
    in pii_scrub.py (invisible in a normal diff/editor). That is a fragile,
    undocumented-as-such reason for one variant to work; it is not evidence
    the class of Unicode separators is handled by design.

    STATUS (post rebuild): FIXED and re-verified. The pipeline mandates
    NFKC normalization (which folds NBSP and the en/em/thin/figure/
    ideographic spaces to U+0020) before any digit-shape/Luhn check, and
    F-HYGIENE (test_pii_scrub.TestFHygiene) now asserts the source file is
    pure ASCII, closing the invisible-NBSP-literal fragility this test class
    called out. Left as a permanent regression test.
    """

    UNICODE_SPACES = {
        "en-space-u2002": " ",
        "em-space-u2003": " ",
        "thin-space-u2009": " ",
        "figure-space-u2007": " ",
        "ideographic-space-u3000": "　",
    }

    def test_unicode_space_separated_card_survives_raw(self):
        for label, sep in self.UNICODE_SPACES.items():
            card_groups = ["4111", "1111", "1111", "1111"]
            card = sep.join(card_groups)
            r = P.evaluate({"fields": {"body": "card %s on file" % card}},
                           "egress-to-judge")
            with self.subTest(label=label):
                self.assertTrue(
                    r.blocked or card not in r.cleaned.get("fields.body", ""),
                    "%s: Unicode-space-separated PII must not survive un-redacted "
                    "in an allowed artifact (sep=%r)" % (label, sep),
                )


class QA7_CrossLeafSplitNumericPIISurvives(unittest.TestCase):
    """Bug QA-7 (MEDIUM): both stages evaluate one flattened leaf at a
    time. A numeric PII value split across separate dict keys or list items
    -- each fragment individually below both engines' per-leaf thresholds --
    is never reconstructed at the fixture level and survives raw, verbatim,
    in every fragment, regardless of boundary. Architectural (per-leaf
    scanning with no cross-leaf reassembly), not a parameter-tuning gap.

    RULING: ACCEPTED as a ratified contract change, not a bug. Cross-leaf
    reassembly is a HUMAN-RECALL responsibility (machine NOT required): the
    machine scans each scalar leaf value fully-normalized as one unit and does
    NOT reassemble candidate PII across distinct JSON keys or array elements.
    Documented, reasoned trade-off: cross-field reassembly is inherently
    low-precision (spurious Luhn/SSN matches on unrelated adjacent numbers) and
    would reintroduce the over-block storm (QA-8) that made the machine gate
    untrustworthy.

    Rationale for accepting (not a rubber stamp):
      1. The residual is EXPLICITLY named and reasoned in the detection spec,
         not silently dropped -- the difference between a ratified trade-off
         and an oversight.
      2. The safety argument ("raw never committed", per-fixture mandatory
         human ratification is the recall backstop) is structurally true in
         the current code: on a MUST-DETECT miss, `cleaned` is BYTE-FOR-BYTE
         the original content (AC-2) -- nothing is silently mangled to
         hide the miss from a human reviewer reading the fixture.
      3. The bar is the CURRENT ratified acceptance criteria, not a stale one
         once the contract is revised with a written rationale.

    CONDITION OF ACCEPTANCE (tracked, not code-owned by pii_scrub.py): this
    acceptance depends on the mandatory per-fixture human-ratification gate
    actually being enforced as a real, unbypassable step before any fixture
    is used/committed -- the entire safety argument for this residual rests
    on that gate being real, not aspirational. If that gate is ever made
    optional, skipped under schedule pressure, or the "raw never committed"
    property stops holding for some import path, this acceptance must be
    reassessed. This is a process/workflow dependency outside pii_scrub.py's
    code, owned by whoever builds the label store / import pipeline -- flagged
    here so it is not lost.

    These two tests are kept (not deleted -- append-only) and marked
    `@unittest.expectedFailure`: the assertion still encodes what a
    machine-only, no-human-backstop world would require, so a future change
    that removes the human-ratification gate without restoring machine
    detection would show as an unexpected PASS-turned-fail signal in CI
    (an expectedFailure that starts passing is flagged by unittest), which
    is a useful tripwire.
    """

    @unittest.expectedFailure  # ACCEPTED, human-recall -- see class docstring
    def test_card_split_across_dict_keys_survives_raw(self):
        fixture = {"payload": {"trajectory": [
            {"a": "4111"}, {"b": "1111"}, {"c": "1111"}, {"d": "1111"},
        ]}}
        r = P.evaluate(fixture, "egress-to-judge")
        self.assertTrue(
            r.blocked or all(
                frag not in "".join(r.cleaned.values())
                for frag in ("4111", "1111")
            ),
            "a card number split across separate leaves must not survive "
            "raw in every fragment of an allowed artifact",
        )

    @unittest.expectedFailure  # ACCEPTED, human-recall -- see class docstring
    def test_card_split_across_list_items_survives_raw(self):
        fixture = {"fields": {"card_groups": ["4111", "1111", "1111", "1111"]}}
        r = P.evaluate(fixture, "egress-to-judge")
        self.assertTrue(
            r.blocked or all(
                v not in ("4111", "1111") for v in r.cleaned.values()
            ),
            "a card number split across list items must not survive raw in "
            "every fragment of an allowed artifact",
        )


class QA8_OverBlockingOnOrdinaryEngineeringContent(unittest.TestCase):
    """Bug QA-8 (MEDIUM-HIGH, new -- usability/regression, not a leak): the
    QA-1 fix's separator-bridging digit-run counter (threshold >=7) now hard
    BLOCKS routine, non-PII engineering content: a full git commit SHA (via
    HIGH_ENTROPY_SECRET) and a plain 8+-digit integer such as a millisecond
    duration or a required `content_hash`/`reviewed_commit` value.
    This is a fail-SAFE direction (no leak), but it is a real "unusably
    strict" finding: sign-off records are required to carry
    a `reviewed_commit`/`content_hash` (i.e. exactly this shape), so any
    fixture that echoes one will be BLOCKED by the control meant to let
    clean review metadata through.

    STATUS (post rebuild): FIXED and re-verified. The precision-first
    MUST-DETECT list has no bare-entropy or bare-digit-run rule; git SHAs,
    plain integers, and 8-digit dates are on the explicit MUST-NOT-BLOCK list
    (rows N-2/N-4) and now pass. Left as a permanent regression test.
    """

    def test_full_git_sha_is_not_hard_blocked(self):
        sha = "9f8c1e2a4b6d3f7e0c5a1b2d4e6f8a0c1b2d3e4f"   # 40-hex commit id
        r = P.evaluate({"fields": {"body": "fixed in commit %s" % sha}},
                       "egress-to-judge")
        self.assertFalse(
            r.blocked,
            "a bare git commit SHA is not PII and should not hard-block the "
            "gate (found: %s)" % dict(r.categories),
        )

    def test_plain_millisecond_duration_is_not_hard_blocked(self):
        r = P.evaluate({"fields": {"body": "retry_after_ms: 86400000"}},
                       "egress-to-judge")
        self.assertFalse(
            r.blocked,
            "an 8-digit config integer is not PII and should not hard-block "
            "the gate (found: %s)" % dict(r.categories),
        )

    def test_yyyymmdd_date_is_not_hard_blocked(self):
        r = P.evaluate({"fields": {"body": "meeting on 20260713 at the office"}},
                       "egress-to-judge")
        self.assertFalse(
            r.blocked,
            "an 8-digit calendar date is not PII and should not hard-block "
            "the gate (found: %s)" % dict(r.categories),
        )


# ==========================================================================
# RE-VERIFICATION (post rebuild) -- QA-1,
# QA-2, QA-6, QA-8 above now PASS unmodified; QA-7 reclassified (see class
# docstring above). QA-9 below was a NEW finding surfaced while independently
# probing the residual flagged during the rebuild -- it is
# reclassified below (see its class docstring RULING).
# ==========================================================================


class QA9_AdjacentDigitRunMergeDefeatsCardDetectionWithinSingleLeaf(
    unittest.TestCase
):
    """Bug QA-9 (originally HIGH): within a SINGLE leaf, a Luhn-valid card
    number immediately adjacent to ANOTHER digit run (a date, amount,
    ticket/txn number) -- separated by nothing more than a space, tab,
    newline, or dash -- was missed by BOTH engines, even though the SAME
    card, standing alone, blocks every time. Not a hypothetical:
    `"Card 4111111111111111 20260713 refund"` -- ordinary ticket/log/CSV-row
    phrasing -- passed end-to-end through `core.run()` with exit code 0 and
    the raw card number verbatim in the allowed artifact.

    ROOT CAUSE (as originally filed): the pre-detection normalization
    that fixed QA-6 (stripping/bridging separators before digit-shape checks)
    merges an adjacent card + digit run into one out-of-range-length run, so
    neither engine's exact-length Luhn/IIN check ever fires on it.

    FIX ATTEMPT (sliding window) -- TRIED AND REVERTED: a sliding
    13-19-digit window over the merged run (both engines) correctly closed
    QA-9, confirmed by independent re-derivation (re-ran
    `"Card 4111111111111111 20260713 refund"` through `core.run()` by
    hand -- exit 1, block). But adversarial follow-through (QA-10)
    found the sliding window checks EVERY
    13-19-digit sub-window of ANY long digit run, so a long NON-card numeric
    ID (an order number, tracking number, invoice number -- ordinary,
    non-PII, common in support tickets) has a Luhn+IIN-valid window by sheer
    combinatorics with empirically measured false-block rates of 22.8% at 16
    digits, rising past 90% at 24-30 digits. That is not a rare edge case; it
    reintroduces the exact "unusably strict, invites bypass" failure class
    the precision-first design exists to eliminate, via a new mechanism (window
    combinatorics instead of a flat threshold). Resolution: revert the sliding
    window. QA-10 is now gone (re-verified) because its ROOT CAUSE
    (the sliding window) no longer exists.

    RULING: ACCEPTED as a ratified contract change, RECLASSIFIED to the SAME
    human-recall bucket as QA-7. This is not a new rule -- it is the EXISTING
    "human-recall, machine not required" ruling, now correctly recognized as
    covering the within-leaf-adjacent-digit-run case too, not only the
    cross-field case QA-7 named. The implementation-side test
    `test_pii_scrub.TestCardTokenDedupAndLongIds.test_embedded_card_is_human_recall_not_machine`
    pins this exact contract.

    QA ACCEPTS this reclassification. Rationale (QA-10 is QA's OWN evidence
    for why this is the right call, not a rubber stamp):
      1. QA-10 is a direct, empirically-measured demonstration of exactly the
         precision/recall bind already reasoned about for QA-7:
         there is no high-precision way to extract a "real" card from a
         longer digit run without either (a) missing merged-adjacent cards
         (QA-9's original failure) or (b) false-blocking on coincidental
         Luhn+IIN matches inside ordinary long IDs (QA-10). Machine precision
         cannot resolve this; it is structurally a human-recall problem, same
         as QA-7's cross-field case.
      2. The safety argument is unchanged from QA-7's: on a miss, `cleaned`
         is byte-for-byte the original content (AC-2) -- a human
         reviewing the full fixture can still catch an embedded card; nothing
         is silently mangled to hide it.
      3. The same CONDITION OF ACCEPTANCE from QA-7 applies here without
         modification: this rests on the mandatory per-fixture
         human-ratification gate being real, not aspirational. If that gate
         is ever weakened, QA must be looped back in.

    These three tests are kept (not deleted -- append-only) and marked
    `@unittest.expectedFailure`: they now guard against an accidental
    regression BACK to machine-side extraction (sliding window or
    equivalent) -- if a future change reintroduces it, these tests would
    start passing again, and `unittest` flags an `expectedFailure` that
    unexpectedly passes. That is the tripwire for "QA-10 came back."
    """

    @unittest.expectedFailure  # ACCEPTED, human-recall (same bucket as QA-7) -- see class docstring; guards against QA-10 regressing back in
    def test_card_immediately_followed_by_date_single_space_survives_raw(self):
        card = "4111111111111111"
        date = "20260713"
        r = P.evaluate({"fields": {"body": "%s %s" % (card, date)}},
                       "egress-to-judge")
        self.assertTrue(
            r.blocked or card not in r.cleaned.get("fields.body", ""),
            "a Luhn-valid card adjacent to another digit run in the same "
            "leaf must not survive raw merely because normalization merged "
            "them into an out-of-range-length run",
        )

    @unittest.expectedFailure  # ACCEPTED, human-recall (same bucket as QA-7) -- see class docstring; guards against QA-10 regressing back in
    def test_realistic_ticket_phrasing_end_to_end_via_core_run(self):
        # Full core.run() stack, not just pii_scrub.evaluate() in isolation --
        # confirms the miss is real all the way to exit code + stdout.
        #
        # UPDATED (increment-3 consolidated remediation):
        # pii-scrub now claims ONLY the disjoint DATA-BOUNDARY event
        # types ("import-into-repo", "eval-egress") -- the event_type IS the
        # boundary now, and a `boundary` key in the payload is vestigial/ignored
        # for routing. `event_type: "pre-pr"` is now a GATE type (security-gate
        # matches unconditionally on it, SG-3 CLOSED) and a gate event carrying no
        # ticket/changeset now BLOCKS as a malformed gate event -- so re-running
        # this exact repro on "pre-pr" would show core.unhandled/security-gate
        # blocking for a DIFFERENT reason (missing ticket), not QA-9's residual,
        # which would give a false read on QA-9's status. Retarget to
        # "eval-egress" (the correct data-boundary type for this content, which is
        # egress-to-judge fixture material, not a PR) so the event routes to
        # pii-scrub ONLY, exactly as QA-9's residual is scoped -- the merged-run
        # miss is still real on the correct event type.
        card = "4111111111111111"
        ev = {
            "contract_version": "1.0",
            "event_id": "evt-qa9",
            "event_type": "eval-egress",
            "occurred_at": "2026-07-13T09:00:00Z",
            "harness": {"name": "test"},
            "requested_mode": "block",
            "payload": {
                "fixture": {"fields": {"body": "Card %s 20260713 refund" % card}},
            },
        }
        out, err, code = core.run(json.dumps(ev))
        self.assertNotEqual(
            code, 0,
            "a Luhn-valid card in ordinary ticket phrasing "
            "('Card <card> <date> refund') must not exit 0/allow on the "
            "eval-egress data-boundary event_type "
            "(stdout=%r)" % out,
        )

    @unittest.expectedFailure  # ACCEPTED, human-recall (same bucket as QA-7) -- see class docstring; guards against QA-10 regressing back in
    def test_date_before_card_also_survives_raw(self):
        # Order-independence check: date-then-card reproduces the same miss.
        card = "4111111111111111"
        date = "20260713"
        r = P.evaluate({"fields": {"body": "%s %s" % (date, card)}},
                       "egress-to-judge")
        self.assertTrue(
            r.blocked or card not in r.cleaned.get("fields.body", ""),
            "order (date-before-card) must not change the miss -- both "
            "orderings currently leak",
        )


if __name__ == "__main__":
    unittest.main()
