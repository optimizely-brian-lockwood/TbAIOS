"""Scoring: trajectory-vs-output split, rubber-stamp signal, thresholds.

Score schema (ADR sec.2.4), stable across judge swaps:
  { fixture_id, role, rubric_id, trajectory_score, output_score,
    line_scores:[{line_id,defect_class,dimension,ratified,judged,match}],
    signals:[...], status:"graded|not-graded|incomplete|blocked|no-fixtures",
    security_ok }

Thresholds:
  * general trajectory/output fidelity >= 0.90
  * security-defect classes (pii/authz/authn/secret) held to EXACT 100% -- any
    single security-line mismatch fails the run and is surfaced individually,
    never averaged into the 0.90 band.
Unlabelled -> not-graded; judge error -> incomplete. Neither ever "passes".
"""

try:  # pragma: no cover - import shim
    from . import rubrics
except ImportError:  # pragma: no cover - import shim
    import rubrics

GENERAL_THRESHOLD = 0.90

# run statuses
GRADED = "graded"
NOT_GRADED = "not-graded"
INCOMPLETE = "incomplete"
BLOCKED = "blocked"
NO_FIXTURES = "no-fixtures"


class EvalResult:
    def __init__(self, fixture_id, role, rubric_id, status,
                 trajectory_score=None, output_score=None, line_scores=None,
                 signals=None, security_ok=None, reason=None):
        self.fixture_id = fixture_id
        self.role = role
        self.rubric_id = rubric_id
        self.status = status
        self.trajectory_score = trajectory_score
        self.output_score = output_score
        self.line_scores = line_scores or []
        self.signals = signals or []
        self.security_ok = security_ok
        self.reason = reason

    def to_stdout(self):
        return {
            "fixture_id": self.fixture_id,
            "role": self.role,
            "rubric_id": self.rubric_id,
            "status": self.status,
            "trajectory_score": self.trajectory_score,
            "output_score": self.output_score,
            "line_scores": self.line_scores,
            "signals": self.signals,
            "security_ok": self.security_ok,
            "reason": self.reason,
        }

    def human(self):
        return "[eval] %s / %s -> %s (traj=%s out=%s sec_ok=%s) signals=%s" % (
            self.fixture_id, self.rubric_id, self.status,
            self.trajectory_score, self.output_score, self.security_ok,
            ",".join(self.signals) or "-")


def _mean(matches):
    return 1.0 if not matches else sum(1 for m in matches if m) / len(matches)


def score(fixture, rubric, labels, judged):
    """Compare judge-proposed per-line values to the ratified labels.

    Assumes the fixture is labelled for this rubric (the runner checks this and
    short-circuits to not-graded otherwise). Never consults the judge for truth.
    """
    fixture_id = fixture["fixture_id"]
    line_scores = []
    traj_matches, out_matches = [], []
    security_ok = True
    signals = []

    for line in rubric.lines:
        ratified = labels.ratified_value(fixture_id, rubric.rubric_id, line.id)
        proposed = bool(judged.get(line.id, False))
        match = (proposed == bool(ratified))
        line_scores.append({
            "line_id": line.id,
            "defect_class": line.defect_class,
            "dimension": line.dimension,
            "ratified": bool(ratified),
            "judged": proposed,
            "match": match,
        })
        # e-1: the general (0.90) band is computed over NON-security lines only.
        # Security-defect lines are judged separately at exact-100% via
        # security_ok, so a matching security line can never mask a general miss
        # and a general miss can never be averaged away by security matches.
        if line.is_security:
            if not match:
                security_ok = False
        elif line.dimension == "output":
            out_matches.append(match)
        else:
            traj_matches.append(match)
        # a defect the answer key says is present that the role did not surface
        if bool(ratified) and not proposed:
            signals.append("miss:%s" % line.id)

    # EV-3: a rubric with NO trajectory-dimension line must NOT report a vacuous
    # 1.0 trajectory_score (that would silently disable rubber-stamp detection).
    # Report None instead; passes() then refuses to pass such a result.
    has_traj_dim = any(ln.dimension == "trajectory" for ln in rubric.lines)
    trajectory_score = _mean(traj_matches) if has_traj_dim else None
    output_score = _mean(out_matches)

    # Rubber-stamp: correct output reached via a flawed trajectory -- raised even
    # when the output label matches (trajectory-based, not output-only).
    if (trajectory_score is not None
            and output_score >= GENERAL_THRESHOLD
            and trajectory_score < GENERAL_THRESHOLD):
        signals.append("rubber-stamp")

    return EvalResult(
        fixture_id=fixture_id, role=rubric.role, rubric_id=rubric.rubric_id,
        status=GRADED, trajectory_score=trajectory_score,
        output_score=output_score, line_scores=line_scores, signals=signals,
        security_ok=security_ok)


def passes(result, general=GENERAL_THRESHOLD):
    """A run passes only if it graded AND every security-defect line matched
    (exact 100%) AND trajectory/output fidelity both meet the general bar.
    not-graded / incomplete / blocked / no-fixtures NEVER pass."""
    if result.status != GRADED:
        return False
    if result.security_ok is False:
        return False
    # EV-3: no trajectory scrutiny (rubric had no trajectory line) -> never a
    # pass. Likewise a missing output score.
    if result.trajectory_score is None or result.output_score is None:
        return False
    return (result.trajectory_score >= general
            and result.output_score >= general)
