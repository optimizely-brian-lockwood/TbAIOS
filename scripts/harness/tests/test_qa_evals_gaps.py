"""QA-authored scratch tests (independent adversarial verification, increment 3).

These are NOT part of the developer's delivered suite for the evals/ subpackage.
They encode gaps found while independently, adversarially probing the
H-EVAL harness for INCREMENT 3. Each test asserts the SECURE/SPEC'D behavior.
Where a test currently FAILS, that failure is the reproduction of a filed
finding -- do not "fix" it by loosening the assertion. See
docs/dev-team/qa/2026-07-14-harness-increment3-qa.md for the write-up
(EV-1 through EV-5).

QA does not modify contract.py / core.py / pii_scrub.py / security_gate.py /
evals/*.py to make these pass.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evals import rubrics, labels, judge, scoring, runner  # noqa: E402

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HARNESS, "evals", "data")


class EV1_GateTokenReachableBypassesEgressGate(unittest.TestCase):
    """Finding EV-1 (MEDIUM -- real, but bounded by threat model): the
    structural guarantee "no code path from a raw fixture to a judge that
    bypasses the scrub -- not by convention, by construction" rests on a
    module-private sentinel, `judge._GATE_TOKEN`, that is reachable by any
    caller with ordinary Python attribute access (`import judge;
    judge._GATE_TOKEN`) -- a single leading underscore is a naming
    convention in Python, not an enforced access boundary. A caller who
    imports the module (no exotic tricks: no ctypes, no ctypes ptr chasing,
    no ABI-level object surgery) can construct a `GradingRequest` carrying a
    raw, UN-scrubbed, genuinely PII-laden fixture and hand it directly to a
    judge, completely bypassing `EgressGate.clear()` and the pii_scrub
    egress-to-judge boundary it enforces.

    EVERY probe through the INTENDED public interface (`EgressGate.clear()`)
    -- PII in rubric assert_text, PII nested 4 levels deep in the fixture,
    PII in an ad-hoc `filename` key -- correctly blocks (see EV-1's sibling
    tests and the dev's own `TestScrubBeforeEgress`). This finding is
    specifically about the claim's absolute wording ("not by convention, by
    construction") being stronger than what a bare Python sentinel actually
    enforces.

    THREAT-MODEL SCOPING (why this is MEDIUM, not CRITICAL): exploiting this
    requires the ability to import `evals.judge` and read a module attribute
    -- i.e. running Python code inside the same trusted process/codebase as
    the harness itself. The named threat actor throughout this whole build
    (a buggy or malicious per-harness adapter) acts
    over the contract-v1 JSON boundary (stdin), which has NO way to reach a
    Python module attribute. An actor with actual Python code-execution
    inside the harness process could do far worse than this specific bypass.
    So: real, demonstrable, worth tightening -- but not reachable from the
    adapter/JSON attack surface this system is otherwise built to resist.

    Recommended hardening (not QA's to implement): mint the token inside a
    closure that is never bound to a module-level name (e.g. generate it
    inside `EgressGate.__init__` and never expose it as `_GATE_TOKEN` at
    module scope), so there is no name to import at all.
    """

    def test_direct_gate_token_access_should_not_be_possible(self):
        self.assertFalse(
            hasattr(judge, "_GATE_TOKEN"),
            "the gate token must not be reachable as a module attribute -- "
            "a caller with ordinary `import judge; judge._GATE_TOKEN` access "
            "can currently construct a GradingRequest with a RAW, unscrubbed "
            "fixture, bypassing EgressGate.clear() entirely",
        )

    def test_raw_pii_fixture_should_not_reach_the_judge_via_direct_construction(self):
        raw_pii_fixture = {
            "fixture_id": "ev1-hack",
            "trajectory": [{"step": "contact jane.doe@acme.com immediately",
                             "flags": []}],
        }
        rub = rubrics.Rubric("ev1.v1", "code-reviewer",
                              [rubrics.RubricLine("L1", "x", "general",
                                                  "trajectory", 1.0, "x")])
        token = getattr(judge, "_GATE_TOKEN", None)
        if token is None:
            self.skipTest("no module-level token to test against (EV-1 already fixed)")
        with self.assertRaises(
            TypeError,
            msg="a raw, unscrubbed PII fixture must never be usable to "
                "construct a GradingRequest, even via a module attribute",
        ):
            judge.GradingRequest(raw_pii_fixture, rub, token)


class EV2_LabelStoreMutableByDirectAttributeAccessAfterFreeze(unittest.TestCase):
    """Finding EV-2 (MEDIUM -- same class/threat-model scoping as EV-1): the
    "labels are immutable at eval time" guarantee is enforced by `ratify()`
    checking `self._frozen`, but `_labels` (a plain dict) and `_frozen` (a
    plain bool) are both ordinary, mutable instance attributes. A caller with
    direct attribute access can rewrite a ratified label after `freeze()`
    (`store._labels[key] = new_value`) or simply flip `_frozen` back to
    `False` and re-ratify through the public API. As with EV-1, this
    requires Python-level access to the LabelStore object, not anything
    reachable from the contract-v1/JSON adapter boundary.

    Recommended hardening: wrap `_labels` in `types.MappingProxyType` at
    freeze time (assigning a NEW read-only view, not just flipping a flag),
    so a direct-attribute mutation attempt raises rather than silently
    succeeding.
    """

    def test_label_store_should_resist_direct_post_freeze_mutation(self):
        st = labels.LabelStore()
        st.ratify("ev2-fx", "ev2.v1", "L1", True)
        st.freeze()
        try:
            st._labels[("ev2-fx", "ev2.v1", "L1")] = False
        except Exception:
            pass  # a TypeError/AttributeError here would mean it's protected
        self.assertTrue(
            st.ratified_value("ev2-fx", "ev2.v1", "L1"),
            "a ratified label must not be mutable via direct attribute "
            "access after the store is frozen -- found the label flipped "
            "to %r" % st.ratified_value("ev2-fx", "ev2.v1", "L1"),
        )


class EV3_ZeroTrajectoryLinesProduceVacuousPerfectTrajectoryScore(unittest.TestCase):
    """Finding EV-3 (MEDIUM, confirmed, not exploitable against the two
    shipped rubrics as-is): `scoring._mean([])` returns `1.0` for an empty
    match list -- the vacuous-truth convention. A rubric authored with ZERO
    trajectory-dimension lines (e.g. a rubric that only asserts output
    checks) therefore ALWAYS reports `trajectory_score == 1.0`, even for a
    completely empty trajectory (the role did nothing), because there is
    nothing to average. This vacuously satisfies `passes()`'s
    `trajectory_score >= 0.90` requirement, and the rubber-stamp signal
    (`output_score>=0.90 and trajectory_score<0.90`) can never fire for such
    a rubric -- trajectory scrutiny is silently and completely disabled, and
    the resulting "1.0" score looks identical to "the trajectory was
    reviewed and it was excellent."

    Both shipped rubrics (`code-reviewer.v1`, `security-engineer.v1`) DO
    include trajectory-dimension lines, so this is not live against them
    today -- it is a latent footgun for a FUTURE rubric authored without any
    trajectory lines (accidentally or otherwise), which would silently lose
    the entire "rubber-stamp detection is trajectory-based, not
    output-only" guarantee this build states as a design goal.

    Recommended hardening: either (a) validate at rubric-load time that
    every rubric has >=1 trajectory-dimension line, refusing to load one
    that doesn't, or (b) have `score()` report `trajectory_score = None`
    (not 1.0) when a rubric defines no trajectory lines, and have
    `passes()` refuse to pass a result whose trajectory_score is None.
    """

    def test_rubric_with_no_trajectory_lines_and_empty_trajectory_should_not_score_perfect(self):
        output_only_rub = rubrics.Rubric("ev3.v1", "code-reviewer", [
            rubrics.RubricLine("O1", "x", "output", "output", 1.0,
                                "verdict-recorded"),
        ])
        st = labels.LabelStore()
        st.ratify("ev3-fx", "ev3.v1", "O1", True)
        st.freeze()
        empty_traj_fixture = {
            "fixture_id": "ev3-fx", "rubric_id": "ev3.v1",
            "trajectory": [], "output": {"flags": ["verdict-recorded"]},
        }
        run = runner.EvalRunner({"ev3.v1": output_only_rub}, st)
        r = run.run({"fixture": empty_traj_fixture})
        self.assertEqual(r.status, scoring.GRADED)
        self.assertNotEqual(
            r.trajectory_score, 1.0,
            "a rubric with ZERO trajectory-dimension lines must not report "
            "a vacuous PERFECT trajectory_score for a completely empty "
            "trajectory -- this silently disables trajectory scrutiny and "
            "rubber-stamp detection for any role scored against it",
        )


class EV4_EgressGateScrubCrashPropagatesInsteadOfFailingClosed(unittest.TestCase):
    """Finding EV-4 (MEDIUM, bounded -- the shipped/default scrub never
    raises): the established, repeatedly-applied principle across this whole
    build is "core crashes mid-eval -> block" (the same failure mode QA-2
    fixed in increment 1's `core.run()`). `EvalRunner.run()` wraps the JUDGE
    call in try/except (judge error -> incomplete, per spec) but does NOT
    wrap the EGRESS-GATE/SCRUB call (`self._gate.clear(...)`) in any
    try/except. If the scrub step itself raises -- which the shipped
    `pii_scrub.evaluate()` never does (it has its own internal fail-closed
    try/except), but a caller-injected `EgressGate(scrub=...)` adapter could
    -- the exception propagates all the way up through `run()`, and even
    through `run_event()`, which explicitly documents itself as
    "(stdout_json, stderr_text, exit_code). Never raises." That claim is
    false for this path.

    Bounded severity: the ONLY shipped scrub implementation is the real
    `pii_scrub` module, which is exception-safe by its own design (proven in
    increment 1's QA report) -- so this is not live against the delivered
    system as configured today. It is a genuine gap relative to this
    codebase's own stated invariant and a real risk for any future adapter
    swap of the scrub dependency.
    """

    class _BrokenScrub:
        def evaluate(self, payload, boundary):
            raise RuntimeError("scrub subsystem exploded")

    def _fixture_and_runner(self):
        rub = rubrics.Rubric("ev4.v1", "code-reviewer",
                              [rubrics.RubricLine("L1", "x", "general",
                                                  "trajectory", 1.0, "a")])
        st = labels.LabelStore()
        st.ratify("ev4-fx", "ev4.v1", "L1", True)
        st.freeze()
        fixture = {"fixture_id": "ev4-fx", "rubric_id": "ev4.v1",
                   "trajectory": [{"step": "s", "flags": ["a"]}], "output": {}}
        gate = judge.EgressGate(scrub=self._BrokenScrub())
        run = runner.EvalRunner({"ev4.v1": rub}, st, gate=gate)
        return fixture, run

    def test_scrub_crash_should_fail_closed_not_raise(self):
        fixture, run = self._fixture_and_runner()
        try:
            r = run.run({"fixture": fixture})
        except Exception as exc:  # noqa: BLE001
            self.fail(
                "EvalRunner.run() raised %r instead of failing closed "
                "(BLOCKED/INCOMPLETE) when the egress-gate scrub step "
                "crashed -- matches the 'core crashes mid-eval -> block' "
                "principle this codebase applies everywhere else "
                "(QA-2, increment 1)" % exc
            )
        self.assertIn(r.status, (scoring.BLOCKED, scoring.INCOMPLETE))

    def test_run_event_should_never_raise_even_on_scrub_crash(self):
        fixture, run = self._fixture_and_runner()
        ev = {
            "contract_version": "1.0", "event_id": "ev4-e", "event_type": "eval-run",
            "occurred_at": "2026-07-14T00:00:00Z", "harness": {"name": "test"},
            "requested_mode": "annotate", "payload": {"fixture": fixture},
        }
        try:
            out, err, code = run.run_event(json.dumps(ev))
        except Exception as exc:  # noqa: BLE001
            self.fail(
                "run_event() raised %r, violating its own docstring "
                "'Never raises' when the egress-gate scrub step crashed"
                % exc
            )


class EV5_IntendedInterfaceCoverageControls(unittest.TestCase):
    """Controls confirming the INTENDED public interface (EgressGate.clear())
    correctly blocks PII in every surface tried -- isolating EV-1/EV-2 to
    specifically the "direct module/attribute access" bypass, not a gap in
    the scrub coverage itself."""

    def test_pii_in_rubric_assert_text_blocks(self):
        dirty_rubric = rubrics.Rubric("ev5-a.v1", "code-reviewer", [
            rubrics.RubricLine("L1", "flag contact at jane.doe@acme.com",
                                "general", "trajectory", 1.0, "x"),
        ])
        clean_fixture = {"fixture_id": "ev5-a",
                          "trajectory": [{"step": "nothing sensitive", "flags": []}]}
        gate = judge.EgressGate()
        self.assertIsNone(gate.clear(clean_fixture, dirty_rubric))

    def test_pii_nested_four_levels_deep_in_fixture_blocks(self):
        deep_fixture = {
            "fixture_id": "ev5-b",
            "trajectory": [{"step": "ok", "flags": [],
                             "meta": {"reviewer_contacts": [
                                 {"name": "x", "email_hint": "jane.doe@acme.com"}]}}],
            "output": {"verdict": "ok", "flags": []},
        }
        clean_rub = rubrics.Rubric("ev5-b.v1", "code-reviewer",
                                    [rubrics.RubricLine("L1", "x", "general",
                                                        "trajectory", 1.0, "x")])
        gate = judge.EgressGate()
        self.assertIsNone(gate.clear(deep_fixture, clean_rub))

    def test_pii_in_ad_hoc_filename_key_blocks(self):
        filename_fixture = {
            "fixture_id": "ev5-c",
            "filename": "acme-jane.doe@acme.com-ticket-notes.md",
            "trajectory": [{"step": "ok", "flags": []}],
        }
        clean_rub = rubrics.Rubric("ev5-c.v1", "code-reviewer",
                                    [rubrics.RubricLine("L1", "x", "general",
                                                        "trajectory", 1.0, "x")])
        gate = judge.EgressGate()
        self.assertIsNone(gate.clear(filename_fixture, clean_rub))


if __name__ == "__main__":
    unittest.main()
