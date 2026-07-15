"""Per-role rubric structure (ADR sec.2.2). Rubrics are DATA (JSON files keyed
to the generic dev-team roles); this module is the mechanism that loads them.

A rubric line asserts one testable expectation for a role, scored individually
(never one opaque verdict). Each line carries:
  id           - stable line id (e.g. SEC-AUTHZ-01)
  assert_text  - human-readable expectation (PM owns the wording)
  defect_class - classification; security-defect classes are held to exact-100%
  dimension    - "trajectory" | "output" (feeds the trajectory-vs-output split)
  weight       - float (reserved; equal-weight scoring for now)
  signal       - the deterministic token a stub judge looks for (the real LM
                 judge ignores this and reasons over the fixture directly)

rubric_id is versioned (`role.vN`): a label is bound to the rubric version it
was ratified against; changing a line means a new version, not a silent re-score.
"""

import json
import os

# Security-defect classes held to an EXACT (100%) bar, never averaged into the
# general 0.90 band.
SECURITY_DEFECT_CLASSES = frozenset({"pii", "authz", "authn", "secret"})

_VALID_DIMENSIONS = frozenset({"trajectory", "output"})


class RubricLine:
    __slots__ = ("id", "assert_text", "defect_class", "dimension", "weight", "signal")

    def __init__(self, id, assert_text, defect_class, dimension="trajectory",
                 weight=1.0, signal=None):
        if dimension not in _VALID_DIMENSIONS:
            raise ValueError("bad rubric dimension: %r" % dimension)
        self.id = id
        self.assert_text = assert_text
        self.defect_class = defect_class
        self.dimension = dimension
        self.weight = float(weight)
        self.signal = signal

    @property
    def is_security(self):
        return self.defect_class in SECURITY_DEFECT_CLASSES


class Rubric:
    def __init__(self, rubric_id, role, lines):
        self.rubric_id = rubric_id
        self.role = role
        self.lines = list(lines)

    @property
    def has_trajectory_line(self):
        return any(ln.dimension == "trajectory" for ln in self.lines)

    @classmethod
    def from_dict(cls, d):
        lines = [RubricLine(
            id=ln["id"],
            assert_text=ln.get("assert", ""),
            defect_class=ln.get("defect_class", "general"),
            dimension=ln.get("dimension", "trajectory"),
            weight=ln.get("weight", 1.0),
            signal=ln.get("signal"),
        ) for ln in d.get("lines", [])]
        return cls(d["rubric_id"], d["role"], lines)


def load_rubric(path):
    with open(path, "r", encoding="utf-8") as fh:
        return Rubric.from_dict(json.load(fh))


def load_rubrics(directory):
    """Load every *.json rubric in a directory -> {rubric_id: Rubric}."""
    out = {}
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            r = load_rubric(os.path.join(directory, name))
            out[r.rubric_id] = r
    return out
