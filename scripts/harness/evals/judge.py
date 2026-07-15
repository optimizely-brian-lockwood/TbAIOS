"""LM-judge interface + adapters, and the scrub-before-egress gate.

SCOPE (EV-1/EV-2): the guarantees below are STRUCTURAL against the threat model
this build defends -- untrusted contract-v1 JSON crossing the boundary -- and
against the judge boundary (the judge is handed no store/label/answer). They are
NOT absolute in-process tamper-proofing: code executing INSIDE the trusted
harness process can reach private attributes; that is out of scope. Cheap
defence-in-depth is applied where free (the minting key lives in a closure with
no module-level name; labels freeze to a read-only proxy), but no more is
claimed than Python can enforce.

* SCRUB-BEFORE-EGRESS. `GradingRequest` -- the ONLY
  object a judge grades -- is minted ONLY by `EgressGate.clear()`, and only
  AFTER the full egress view passes the fail-closed `pii_scrub` egress-to-judge
  boundary. A scanner hit returns None -> no request -> the judge is never
  called. Across the contract-v1 surface there is no path from a raw fixture to
  a judge that skips the scrub.

* JUDGE-NEVER-INVENTS-TRUTH + JUDGE-NEVER-SEES-THE-ANSWER (ADR 2.3; e-2/INC3-1).
  The GradingRequest carries EXACTLY the scrubbed, NON-answer-bearing egress
  view: the full fixture with answer-encoding `flags` stripped at every depth,
  and a rubric view of `{id, assert_text}` only (no `signal`, no
  `defect_class`). So "scrub covers exactly what egresses" is exact, and a real
  judge can neither read a ratified label (none is passed) nor read the answer
  key to inflate agreement. The runner holds the labels + full rubric and
  compares the judge's PROPOSED booleans locally.
"""

try:  # pragma: no cover - import shim
    from .. import pii_scrub
except ImportError:  # pragma: no cover - import shim
    import pii_scrub


# Answer-encoding keys stripped from the fixture before it can egress.
_ANSWER_KEYS = frozenset({"flags"})


def _strip_answer_keys(obj):
    """Recursively drop answer-encoding keys, preserving ALL other content (so
    the judge sees the substance AND the scrub covers everything that egresses,
    including deeply-nested/ad-hoc fields -- EV-5)."""
    if isinstance(obj, dict):
        return {k: _strip_answer_keys(v) for k, v in obj.items() if k not in _ANSWER_KEYS}
    if isinstance(obj, list):
        return [_strip_answer_keys(v) for v in obj]
    return obj


def _fixture_egress_view(fixture):
    """Non-answer-bearing fixture view: the FULL fixture with `flags` stripped at
    every depth. Nothing else is dropped, so nested/ad-hoc PII still egresses ->
    still scrubbed."""
    return _strip_answer_keys(fixture)


def _rubric_egress_view(rubric):
    """Non-answer-bearing rubric view: line `id` + `assert` text ONLY. No
    `signal`, no `defect_class` (n-3: id retained so the judge can key its
    per-line judgments)."""
    return {"rubric_id": rubric.rubric_id,
            "lines": [{"id": ln.id, "assert": ln.assert_text} for ln in rubric.lines]}


def _fixture_flags(fixture):
    """Answer-key flags -- read ONLY from a FULL fixture (an egress view has
    none). Used by the StubJudge's test-only oracle."""
    traj, out = set(), set()
    for step in fixture.get("trajectory") or []:
        if isinstance(step, dict):
            for fl in step.get("flags") or []:
                traj.add(fl)
    output = fixture.get("output") or {}
    if isinstance(output, dict):
        for fl in output.get("flags") or []:
            out.add(fl)
    return traj, out


def _make_gate_machinery():
    """Create GradingRequest + EgressGate sharing a minting key that lives ONLY
    in this closure -- there is no module-level `_GATE_TOKEN` name to import
    (EV-1 defence-in-depth). Reaching the key requires closure-cell
    introspection, not ordinary attribute access."""
    _key = object()

    class GradingRequest:
        """The sole object a judge grades. Minted only by EgressGate.clear();
        carries EXACTLY the scrubbed, non-answer-bearing egress view (dicts),
        never the live objects, never labels."""
        __slots__ = ("fixture", "rubric")

        def __init__(self, fixture_view, rubric_view, token):
            if token is not _key:
                raise TypeError(
                    "GradingRequest is minted only by EgressGate.clear() -- "
                    "there is no path from a raw fixture to the judge")
            self.fixture = fixture_view
            self.rubric = rubric_view

    class EgressGate:
        """The ONLY producer of a GradingRequest. Every request has passed the
        fail-closed pii_scrub egress-to-judge boundary and carries exactly the
        scrubbed non-answer-bearing view (scrub-coverage == egress-content)."""

        def __init__(self, scrub=None):
            self._scrub = scrub if scrub is not None else pii_scrub

        def clear(self, fixture, rubric):
            fixture_view = _fixture_egress_view(fixture)
            rubric_view = _rubric_egress_view(rubric)
            payload = {"fixture": fixture_view, "rubric": rubric_view}
            result = self._scrub.evaluate(payload, "egress-to-judge")
            if result.blocked:
                return None
            return GradingRequest(fixture_view, rubric_view, _key)

    return GradingRequest, EgressGate


GradingRequest, EgressGate = _make_gate_machinery()


# --------------------------------------------------------------------------
# Judge interface + adapters
# --------------------------------------------------------------------------
class Judge:
    """Judge interface: GradingRequest -> {line_id: bool} (proposed per-line
    judgments). Swapping the LM is an adapter swap; interface, rubric format,
    and score schema are unchanged (H-EVAL 14)."""

    def grade(self, request):  # pragma: no cover - interface
        raise NotImplementedError


class StubJudge(Judge):
    """Deterministic judge for tests -- NO network. It does NOT read the answer
    from the (answer-free) GradingRequest; it consults a TEST-ONLY ORACLE (full
    fixtures + rubrics WITH answer signals) supplied at construction, keyed by
    the fixture_id / rubric_id the request carries. A real judge has no oracle
    and reasons over the answer-free view alone (e-2 test seam)."""

    def __init__(self, oracle_fixtures=None, oracle_rubrics=None):
        self._fx = {f.get("fixture_id"): f for f in (oracle_fixtures or [])}
        self._rb = {r.rubric_id: r for r in (oracle_rubrics or [])}

    def grade(self, request):
        if not isinstance(request, GradingRequest):
            raise TypeError("judge only accepts a gate-cleared GradingRequest")
        full_fx = self._fx.get(request.fixture.get("fixture_id"))
        full_rb = self._rb.get(request.rubric.get("rubric_id"))
        if full_fx is None or full_rb is None:
            return {}   # unknown to the oracle -> propose nothing (safe)
        traj_flags, out_flags = _fixture_flags(full_fx)
        proposed = {}
        for line in full_rb.lines:
            pool = out_flags if line.dimension == "output" else traj_flags
            proposed[line.id] = line.signal in pool
        return proposed


class RaisingJudge(Judge):
    """Always errors -- exercises judge-error -> incomplete (never a pass)."""

    def grade(self, request):
        raise RuntimeError("judge unavailable")


class ClaudeJudgeAdapter(Judge):
    """ACTIVATION-GATED real-LM adapter (Claude first). NOT called in tests /
    library use. At activation it MUST egress ONLY the gate-cleared answer-free
    view carried by the GradingRequest, map the LM
    output to {line_id: bool} (else incomplete), and receive no labels. A future
    non-Claude judge is a sibling adapter implementing this same interface."""

    def __init__(self, client=None):
        self._client = client

    def grade(self, request):  # pragma: no cover - activation-gated
        raise NotImplementedError(
            "ClaudeJudgeAdapter is activation-gated: wire the Claude client + "
            "credentials at activation. Never invoked in library/tests. It "
            "receives only a gate-cleared answer-free GradingRequest and must "
            "return {line_id: bool}; it is given no labels and no answer key.")
