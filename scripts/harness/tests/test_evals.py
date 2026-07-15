"""Tests for the H-EVAL agent-behavior eval harness.

Covers: rubric scoring on synthetic planted-defect fixtures (catch->pass,
miss->fail); trajectory-vs-output split + rubber-stamp; judge-can't-write-labels
(structural); scrub-before-egress (structural, PII blocked before the judge);
security-defect exact-100% vs general-0.90; unlabelled->refuse; judge-error->
incomplete; contract-v1 crossing; no-fixtures. Deterministic StubJudge only --
no live API.
"""

import json
import os
import sys
import unittest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HARNESS)

from evals import rubrics, labels, judge, scoring, runner  # noqa: E402

DATA = os.path.join(HARNESS, "evals", "data")
RUBRICS = rubrics.load_rubrics(os.path.join(DATA, "rubrics"))
LABELS = labels.LabelStore.from_dir(os.path.join(DATA, "labels"))


def load_fixture(name):
    with open(os.path.join(DATA, "fixtures", name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


ALL_FIXTURE_NAMES = ("fix-sqli-caught", "fix-offbyone-missed",
                     "fix-pii-caught", "fix-unlabelled")


def all_fixtures():
    return [load_fixture(n) for n in ALL_FIXTURE_NAMES]


def make_runner(judge_impl=None, gate=None):
    # Default StubJudge is oracle-backed (test-only): it reads answer signals
    # from the FULL fixtures/rubrics it is given here, NOT from the answer-free
    # GradingRequest a real judge would receive (e-2 test seam).
    j = judge_impl or judge.StubJudge(oracle_fixtures=all_fixtures(),
                                      oracle_rubrics=list(RUBRICS.values()))
    return runner.EvalRunner(RUBRICS, LABELS, judge=j, gate=gate)


class TestRubricScoring(unittest.TestCase):

    def test_all_caught_passes(self):
        r = make_runner().run({"fixture": load_fixture("fix-sqli-caught")})
        self.assertEqual(r.status, scoring.GRADED)
        self.assertTrue(scoring.passes(r))
        self.assertTrue(r.security_ok)

    def test_planted_bug_missed_is_reported_and_fails(self):
        r = make_runner().run({"fixture": load_fixture("fix-offbyone-missed")})
        self.assertEqual(r.status, scoring.GRADED)
        self.assertFalse(scoring.passes(r))
        # the miss is surfaced per-line
        miss = [ls for ls in r.line_scores if ls["line_id"] == "CR-OFFBYONE-01"][0]
        self.assertTrue(miss["ratified"])       # answer key: bug present
        self.assertFalse(miss["judged"])         # role did not catch it
        self.assertFalse(miss["match"])
        self.assertIn("miss:CR-OFFBYONE-01", r.signals)

    def test_planted_pii_caught_true_positive(self):
        r = make_runner().run({"fixture": load_fixture("fix-pii-caught")})
        self.assertEqual(r.status, scoring.GRADED)
        pii = [ls for ls in r.line_scores if ls["line_id"] == "SEC-PII-01"][0]
        self.assertTrue(pii["ratified"] and pii["judged"] and pii["match"])
        self.assertTrue(scoring.passes(r))


class TestTrajectoryVsOutputSplit(unittest.TestCase):

    def test_rubber_stamp_detected_when_output_correct_but_trajectory_flawed(self):
        r = make_runner().run({"fixture": load_fixture("fix-offbyone-missed")})
        # correct/complete output but empty review trajectory
        self.assertEqual(r.output_score, 1.0)
        self.assertLess(r.trajectory_score, scoring.GENERAL_THRESHOLD)
        self.assertIn("rubber-stamp", r.signals)


class TestJudgeCannotWriteLabels(unittest.TestCase):
    """Structural: judge-never-invents-truth."""

    def test_grading_request_cannot_be_constructed_outside_the_gate(self):
        with self.assertRaises(TypeError):
            judge.GradingRequest({}, RUBRICS["code-reviewer.v1"], object())

    def test_grading_request_carries_no_labels_field(self):
        self.assertEqual(set(judge.GradingRequest.__slots__), {"fixture", "rubric"})

    def test_stub_judge_has_no_label_store_reference(self):
        j = judge.StubJudge()
        # no attribute on the judge references a LabelStore
        for attr in vars(j).values():
            self.assertNotIsInstance(attr, labels.LabelStore)

    def test_judge_receives_only_fixture_and_rubric(self):
        gate = judge.EgressGate()
        req = gate.clear(load_fixture("fix-sqli-caught"), RUBRICS["security-engineer.v1"])
        self.assertIsNotNone(req)
        self.assertFalse(hasattr(req, "labels"))
        self.assertFalse(hasattr(req, "label_store"))

    def test_judge_view_is_answer_free(self):
        # e-2: the judge view must contain no answer-bearing fields --
        # no rubric `signal`/`defect_class`, no fixture answer `flags`, and none
        # of the answer tokens themselves.
        gate = judge.EgressGate()
        req = gate.clear(load_fixture("fix-sqli-caught"), RUBRICS["security-engineer.v1"])
        blob = json.dumps({"fixture": req.fixture, "rubric": req.rubric})
        for banned in ("signal", "defect_class", "flags",
                       "sql-injection", "authz-gap", "pii-exposure"):
            self.assertNotIn(banned, blob, "answer-bearing field/token leaked: %s" % banned)
        # n-3: rubric line ids ARE retained (needed to key judgments); assert is too
        self.assertIn("id", json.dumps(req.rubric["lines"][0]))
        self.assertIn("assert", json.dumps(req.rubric["lines"][0]))


class TestScrubBeforeEgress(unittest.TestCase):
    """Structural scrub-before-egress: a PII-carrying fixture is blocked before
    the judge ever sees it."""

    class SpyJudge(judge.Judge):
        def __init__(self):
            self.calls = []

        def grade(self, request):
            self.calls.append(request)
            return {}

    def _labelled_pii_fixture(self):
        # labelled so it passes the unlabelled gate and REACHES egress; carries
        # a real email in a trajectory step -> pii_scrub must block egress.
        store = labels.LabelStore()
        for lid in ("CR-OFFBYONE-01", "CR-REVIEW-EVIDENCE-01", "CR-VERDICT-01"):
            store.ratify("fix-pii-egress", "code-reviewer.v1", lid, True)
        store.freeze()
        fixture = {
            "fixture_id": "fix-pii-egress", "class": "synthetic",
            "role_under_test": "code-reviewer", "rubric_id": "code-reviewer.v1",
            "trajectory": [{"step": "emailed reviewer at jane.doe@acme.com",
                            "flags": ["review-evidence", "off-by-one"]}],
            "output": {"verdict": "changes-requested", "flags": ["verdict-recorded"]},
        }
        return store, fixture

    def test_pii_fixture_blocked_and_judge_never_called(self):
        store, fixture = self._labelled_pii_fixture()
        spy = self.SpyJudge()
        run = runner.EvalRunner(RUBRICS, store, judge=spy)
        r = run.run({"fixture": fixture})
        self.assertEqual(r.status, scoring.BLOCKED)
        self.assertEqual(len(spy.calls), 0, "judge must never see a PII fixture")

    def test_clean_fixture_reaches_judge(self):
        # control: a clean fixture DOES reach the judge and grades.
        spy = self.SpyJudge()
        run = runner.EvalRunner(RUBRICS, LABELS, judge=spy)
        run.run({"fixture": load_fixture("fix-sqli-caught")})
        self.assertEqual(len(spy.calls), 1)

    def test_egress_gate_returns_none_on_pii(self):
        gate = judge.EgressGate()
        _store, fixture = self._labelled_pii_fixture()
        self.assertIsNone(gate.clear(fixture, RUBRICS["code-reviewer.v1"]))


class TestThresholds(unittest.TestCase):
    """Security-defect classes exact-100%; general fidelity >= 0.90."""

    def _rubric_9general_1security(self):
        lines = [rubrics.RubricLine("G%d" % i, "general check", "correctness",
                                    "trajectory", 1.0, "g%d" % i) for i in range(9)]
        lines.append(rubrics.RubricLine("SEC-AUTHZ", "authz gap", "authz",
                                        "trajectory", 1.0, "authz"))
        return rubrics.Rubric("thresh.v1", "code-reviewer", lines)

    def _store(self, rubric):
        st = labels.LabelStore()
        for ln in rubric.lines:
            st.ratify("fx", rubric.rubric_id, ln.id, True)
        return st.freeze()

    def test_security_mismatch_fails_even_when_general_meets_090(self):
        # e-1: general band excludes the security line. 9 general lines all
        # match -> general trajectory = 1.0; the security line misses ->
        # security_ok False -> fails. A matching-general set cannot mask it, and
        # (crucially) a passing general band does not average the security miss.
        rub = self._rubric_9general_1security()
        store = self._store(rub)
        judged = {ln.id: True for ln in rub.lines}
        judged["SEC-AUTHZ"] = False            # the one security line misses
        r = scoring.score({"fixture_id": "fx"}, rub, store, judged)
        self.assertEqual(r.trajectory_score, 1.0)   # general = non-security only
        self.assertFalse(r.security_ok)             # exact-100% security fails
        self.assertFalse(scoring.passes(r))

    def test_all_match_passes(self):
        rub = self._rubric_9general_1security()
        store = self._store(rub)
        judged = {ln.id: True for ln in rub.lines}
        r = scoring.score({"fixture_id": "fx"}, rub, store, judged)
        self.assertTrue(r.security_ok)
        self.assertTrue(scoring.passes(r))

    def test_general_below_090_fails_even_with_security_ok(self):
        # e-1: 2 of the 9 GENERAL lines miss -> 7/9 ~= 0.78 < 0.90; the security
        # line matches (security_ok True) but cannot rescue the general band.
        rub = self._rubric_9general_1security()
        store = self._store(rub)
        judged = {ln.id: True for ln in rub.lines}
        judged["G0"] = False
        judged["G1"] = False                    # 7/9 general -> ~0.78
        r = scoring.score({"fixture_id": "fx"}, rub, store, judged)
        self.assertAlmostEqual(r.trajectory_score, 7.0 / 9.0)
        self.assertTrue(r.security_ok)
        self.assertFalse(scoring.passes(r))

    def test_matching_security_line_excluded_from_general_mean(self):
        # A matching security line must NOT inflate the general band: with 1
        # general miss out of 9 general lines, general = 8/9 (< 0.90), even
        # though the security line matches. (If security were averaged in, the
        # 10-line mean 9/10 = 0.90 would wrongly pass.)
        rub = self._rubric_9general_1security()
        store = self._store(rub)
        judged = {ln.id: True for ln in rub.lines}
        judged["G0"] = False                    # 8/9 general ~= 0.889
        r = scoring.score({"fixture_id": "fx"}, rub, store, judged)
        self.assertAlmostEqual(r.trajectory_score, 8.0 / 9.0)
        self.assertTrue(r.security_ok)
        self.assertFalse(scoring.passes(r))


class TestVacuousTrajectory(unittest.TestCase):
    """EV-3 (option b): a rubric with NO trajectory-dimension line must NOT
    report a vacuous 1.0 trajectory_score -- it scores None and never passes,
    so trajectory scrutiny / rubber-stamp detection is never silently disabled."""

    def test_output_only_rubric_scores_none_trajectory_and_never_passes(self):
        rub = rubrics.Rubric("vac.v1", "code-reviewer", [
            rubrics.RubricLine("O1", "verdict recorded", "output", "output", 1.0,
                               "verdict-recorded"),
        ])
        store = labels.LabelStore()
        store.ratify("vac-fx", "vac.v1", "O1", True)
        store.freeze()
        fixture = {"fixture_id": "vac-fx", "rubric_id": "vac.v1",
                   "trajectory": [], "output": {"flags": ["verdict-recorded"]}}
        j = judge.StubJudge(oracle_fixtures=[fixture], oracle_rubrics=[rub])
        r = runner.EvalRunner({"vac.v1": rub}, store, judge=j).run({"fixture": fixture})
        self.assertEqual(r.status, scoring.GRADED)
        self.assertIsNone(r.trajectory_score)     # not a vacuous 1.0
        self.assertFalse(scoring.passes(r))


class TestNeverRaises(unittest.TestCase):
    """EV-4: run() fails closed (incomplete) on any internal error; never raises."""

    class BoomScrub:
        def evaluate(self, fixture, boundary):
            raise RuntimeError("scrub blew up")

    def test_raising_scrub_fails_closed_incomplete(self):
        gate = judge.EgressGate(scrub=self.BoomScrub())
        r = make_runner(gate=gate).run({"fixture": load_fixture("fix-sqli-caught")})
        self.assertEqual(r.status, scoring.INCOMPLETE)
        self.assertFalse(scoring.passes(r))

    def test_raising_scrub_via_run_event_exits_zero_with_incomplete(self):
        # run_event still "ran" (exit 0), reporting incomplete -- never raises.
        gate = judge.EgressGate(scrub=self.BoomScrub())
        ev = {
            "contract_version": "1.0", "event_id": "e", "event_type": "eval-run",
            "occurred_at": "2026-07-14T00:00:00Z", "harness": {"name": "t"},
            "requested_mode": "annotate",
            "payload": {"fixture": load_fixture("fix-sqli-caught"),
                        "rubric_id": "security-engineer.v1"},
        }
        out, err, code = make_runner(gate=gate).run_event(json.dumps(ev))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], scoring.INCOMPLETE)


class TestRefuseAndIncomplete(unittest.TestCase):

    def test_unlabelled_fixture_refuses_to_grade(self):
        r = make_runner().run({"fixture": load_fixture("fix-unlabelled")})
        self.assertEqual(r.status, scoring.NOT_GRADED)
        self.assertFalse(scoring.passes(r))

    def test_judge_error_is_incomplete_never_a_default_pass(self):
        run = runner.EvalRunner(RUBRICS, LABELS, judge=judge.RaisingJudge())
        r = run.run({"fixture": load_fixture("fix-sqli-caught")})
        self.assertEqual(r.status, scoring.INCOMPLETE)
        self.assertFalse(scoring.passes(r))

    def test_empty_fixture_set_is_no_fixtures(self):
        results = make_runner().run_many([])
        self.assertEqual(results[0].status, scoring.NO_FIXTURES)


class TestContractCrossing(unittest.TestCase):

    def _envelope(self, payload, event_type="eval-run"):
        return {
            "contract_version": "1.0", "event_id": "evt-eval",
            "event_type": event_type, "occurred_at": "2026-07-14T00:00:00Z",
            "harness": {"name": "test"}, "requested_mode": "annotate",
            "payload": payload,
        }

    def test_run_event_emits_score_and_exit_zero(self):
        ev = self._envelope({"fixture": load_fixture("fix-sqli-caught"),
                             "rubric_id": "security-engineer.v1"})
        out, err, code = make_runner().run_event(json.dumps(ev))
        self.assertEqual(code, 0)
        obj = json.loads(out)
        self.assertEqual(obj["status"], scoring.GRADED)
        self.assertIn("trajectory_score", obj)
        self.assertIn("line_scores", obj)

    def test_malformed_event_exits_nonzero(self):
        out, err, code = make_runner().run_event("{ not json")
        self.assertNotEqual(code, 0)

    def test_wrong_event_type_exits_nonzero(self):
        ev = self._envelope({"fixture": load_fixture("fix-sqli-caught")},
                            event_type="pre-pr")
        out, err, code = make_runner().run_event(json.dumps(ev))
        self.assertNotEqual(code, 0)


class TestLabelImmutability(unittest.TestCase):

    def test_reratify_different_value_raises(self):
        st = labels.LabelStore()
        st.ratify("fx", "r.v1", "L1", True)
        with self.assertRaises(labels.LabelError):
            st.ratify("fx", "r.v1", "L1", False)

    def test_frozen_store_refuses_writes(self):
        st = labels.LabelStore().freeze()
        with self.assertRaises(labels.LabelError):
            st.ratify("fx", "r.v1", "L1", True)


if __name__ == "__main__":
    unittest.main()
