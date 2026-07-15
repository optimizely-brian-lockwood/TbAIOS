"""Human-ratified label store (ADR sec.2.3) -- the judge-never-invents-truth
guarantee.

Labels are set once by a human (`ratify`) and immutable at eval time (`freeze`).
The store is NEVER handed to the judge: the judge is constructed with no store
reference and the grading request (judge.py) carries no labels. The runner holds
the store, reads ratified values, and compares the judge's PROPOSED values
locally.

SCOPE (EV-1/EV-2): the guarantee is STRUCTURAL against the threat model this
build defends -- untrusted contract-v1 JSON input, and the judge boundary (the
judge is passed no store/label, so nothing it receives can mutate truth). It is
NOT absolute in-process tamper-proofing: `_labels`/`_frozen` are ordinary Python
attributes, and code executing INSIDE the trusted harness process could reach
them -- that is outside the contract-v1 threat model. `freeze()` + set-once
`ratify` are the enforced controls at the trusted-input surface.
"""

import json
import os
from types import MappingProxyType


class LabelError(Exception):
    pass


class LabelStore:
    def __init__(self):
        self._labels = {}        # (fixture_id, rubric_id, line_id) -> bool
        self._frozen = False

    def ratify(self, fixture_id, rubric_id, line_id, value):
        """Human ratification. Set-once: re-ratifying a key to a DIFFERENT value
        raises (labels are immutable). Blocked entirely once frozen."""
        if self._frozen:
            raise LabelError("label store is frozen at eval time; no writes")
        key = (fixture_id, rubric_id, line_id)
        if key in self._labels and self._labels[key] != bool(value):
            raise LabelError("labels are immutable; refusing to re-ratify %r" % (key,))
        self._labels[key] = bool(value)

    def freeze(self):
        # EV-2 cheap defence-in-depth: swap in a READ-ONLY view, so a direct
        # `store._labels[k] = v` after freeze raises rather than silently
        # mutating a ratified label. (Scoped DiD, not absolute tamper-proofing:
        # the in-process harness is trusted; this hardens the obvious slip.)
        self._labels = MappingProxyType(dict(self._labels))
        self._frozen = True
        return self

    # ---- read-only surface (all the runner needs; the judge gets none of this)
    def ratified_value(self, fixture_id, rubric_id, line_id):
        """Ratified bool, or None if this line was never ratified."""
        return self._labels.get((fixture_id, rubric_id, line_id))

    def has_labels_for(self, fixture_id, rubric_id):
        return any(k[0] == fixture_id and k[1] == rubric_id for k in self._labels)

    def all_lines_labelled(self, fixture_id, rubric_id, line_ids):
        return all(self.ratified_value(fixture_id, rubric_id, lid) is not None
                   for lid in line_ids)

    @classmethod
    def from_dir(cls, directory):
        """Load ratified labels from JSON files, then FREEZE (immutable at eval
        time). Each file: {fixture_id, rubric_id, labels: {line_id: bool}}."""
        store = cls()
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(directory, name), "r", encoding="utf-8") as fh:
                d = json.load(fh)
            for line_id, value in (d.get("labels") or {}).items():
                store.ratify(d["fixture_id"], d["rubric_id"], line_id, value)
        return store.freeze()
