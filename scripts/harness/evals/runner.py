"""Eval runner (ADR sec.2) -- loads a fixture, applies the role rubric, runs the
judge through the structural egress gate, compares to the ratified labels.

Order of operations enforces the guarantees:
  1. resolve the rubric for the fixture's role;
  2. UNLABELLED -> not-graded, BEFORE any egress/judge (never ask the judge for
     truth on an unlabelled fixture);
  3. structural scrub-before-egress: the EgressGate is the only producer of a
     GradingRequest; a scanner hit -> None -> judge NOT called -> blocked;
  4. judge error -> incomplete (never a default pass);
  5. score judge-proposed vs ratified locally.

Contract-v1 crossing (H-EVAL 13): `run_event(raw)` validates a contract-v1
`eval-run` envelope and emits the score schema on stdout + a conformant exit
code (0 = ran; non-zero = malformed/wrong event or runner error), mirroring the
core response protocol. The runner is NOT an enforcement floor/gate -- it
reports; it is not registered in the core DEFAULT_REGISTRY. Wiring eval as an
on-demand core tool is a clean activation seam.
"""

import json

try:  # pragma: no cover - import shim
    from . import scoring
    from .judge import EgressGate, StubJudge
except ImportError:  # pragma: no cover - import shim
    import scoring
    from judge import EgressGate, StubJudge

try:  # pragma: no cover - import shim
    from .. import contract as C
except ImportError:  # pragma: no cover - import shim
    import contract as C


class EvalRunner:
    def __init__(self, rubrics_by_id, labels, judge=None, gate=None):
        self._rubrics = dict(rubrics_by_id or {})
        self._labels = labels
        self._judge = judge if judge is not None else StubJudge()
        self._gate = gate if gate is not None else EgressGate()

    def _resolve_rubric(self, payload, fixture):
        # inline rubric object, or a rubric_id looked up in the store
        rubric = payload.get("rubric")
        if rubric is not None and hasattr(rubric, "lines"):
            return rubric
        rubric_id = payload.get("rubric_id") or fixture.get("rubric_id")
        return self._rubrics.get(rubric_id)

    def run(self, event):
        """Grade one fixture. `event` is a contract-v1 eval-run envelope or a
        bare payload dict ({fixture, rubric_id|rubric}).

        EV-4: NEVER raises. Any internal exception (scrub step, judge, scoring,
        malformed input) fails closed to `incomplete` with no raw content in the
        result -- same class as increment-1 QA-2 ("core crashes mid-eval ->
        block"). Neither `incomplete` nor `blocked` ever `passes()`."""
        fid = rid = role = None
        try:
            payload = event.get("payload", event) if isinstance(event, dict) else {}
            fixture = payload.get("fixture")
            if not isinstance(fixture, dict) or not fixture.get("fixture_id"):
                return scoring.EvalResult(None, None, None, scoring.INCOMPLETE,
                                          reason="malformed-fixture")
            fid, role = fixture.get("fixture_id"), fixture.get("role_under_test")

            rubric = self._resolve_rubric(payload, fixture)
            if rubric is None:
                return scoring.EvalResult(fid, role, None, scoring.INCOMPLETE,
                                          reason="unknown-rubric")
            rid, role = rubric.rubric_id, rubric.role
            line_ids = [ln.id for ln in rubric.lines]

            # (2) unlabelled -> refuse to grade, before egress/judge.
            if not (self._labels.has_labels_for(fid, rid)
                    and self._labels.all_lines_labelled(fid, rid, line_ids)):
                return scoring.EvalResult(fid, role, rid, scoring.NOT_GRADED,
                                          reason="unlabelled -- cannot grade")

            # (3) structural scrub-before-egress: no request => judge never called.
            request = self._gate.clear(fixture, rubric)
            if request is None:
                return scoring.EvalResult(fid, role, rid, scoring.BLOCKED,
                                          reason="pii-scrub blocked egress-to-judge")

            # (4) judge error -> incomplete (never a default pass).
            try:
                judged = self._judge.grade(request)
            except Exception:  # noqa: BLE001
                return scoring.EvalResult(fid, role, rid, scoring.INCOMPLETE,
                                          reason="judge-error")

            # (5) score proposed vs ratified locally.
            return scoring.score(fixture, rubric, self._labels, judged)
        except Exception:  # noqa: BLE001 -- EV-4: fail closed, no raw content
            return scoring.EvalResult(fid, role, rid, scoring.INCOMPLETE,
                                      reason="runner-error")

    def run_many(self, events):
        events = list(events or [])
        if not events:
            return [scoring.EvalResult(None, None, None, scoring.NO_FIXTURES,
                                       reason="no fixtures")]
        return [self.run(e) for e in events]

    # ---- contract-v1 crossing (H-EVAL 13) --------------------------------
    def run_event(self, raw):
        """(stdout_json, stderr_text, exit_code). Never raises."""
        try:
            event = C.load_event(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
            C.validate_envelope(event)
        except Exception:  # noqa: BLE001 -- malformed contract event
            return json.dumps({"status": "error", "reason": "malformed-event"}), \
                "eval: malformed contract-v1 event", 1
        if event.get("event_type") != "eval-run":
            return json.dumps({"status": "error", "reason": "wrong-event-type"}), \
                "eval: not an eval-run event", 1
        result = self.run(event)
        return json.dumps(result.to_stdout(), sort_keys=True), result.human(), 0
