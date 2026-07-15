"""Tests for H-HOOKS increment 4: C-6 dispatch composition, commit-block,
atomic-tracking, flip-state, and the default-deny clickup-gate.

Modules are exercised through core.dispatch with explicit (config-bound)
registries, proving they are config-driven (no engagement specifics hardcoded).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import contract as C   # noqa: E402
import core            # noqa: E402
import hooks           # noqa: E402


def envelope(payload, event_type, requested_mode="block"):
    return {
        "contract_version": "1.0", "event_id": "evt-hooks",
        "event_type": event_type, "occurred_at": "2026-07-14T00:00:00Z",
        "harness": {"name": "test"}, "requested_mode": requested_mode,
        "payload": payload,
    }


# --- synthetic specs for isolating C-6 composition ------------------------
def _floor(name, hit):
    def handler(event):
        return core.ModuleResult(hit=hit, module=name,
                                 reasons=[{"code": name.upper()}] if hit else [],
                                 annotations=[{"severity": "error", "module": name,
                                               "message": "floor %s" % name}] if hit else [])
    return core.ModuleSpec(name, lambda e: e["event_type"] == "feature-merge",
                           handler, immutable_floor=True)


def _warn_only(name):
    def handler(event):
        return core.ModuleResult(hit=True, module=name,
                                 reasons=[{"code": "%s_WARN" % name.upper()}],
                                 annotations=[{"severity": "warn", "module": name,
                                               "message": "warn from %s" % name}])
    return core.ModuleSpec(name, lambda e: e["event_type"] == "feature-merge",
                           handler, immutable_floor=False)


class TestC6Composition(unittest.TestCase):
    """C-6: a matching+allowing floor must NOT suppress a co-matching warn-only
    module; decisions are composed and a warn is never silently dropped."""

    def test_allowing_floor_still_surfaces_co_matching_warn(self):
        reg = [_floor("floor-allow", hit=False), _warn_only("dummy-warn")]
        dec = core.dispatch(envelope({}, "feature-merge"), registry=reg)
        self.assertEqual(dec.decision, "warn")             # not silently allowed
        self.assertEqual(dec.exit_code, C.EXIT_ALLOW)      # warn proceeds (exit 0)
        self.assertIn("dummy-warn", dec.module)
        self.assertTrue(any(a.get("module") == "dummy-warn" for a in dec.annotations))

    def test_blocking_floor_still_records_the_warn(self):
        reg = [_floor("floor-block", hit=True), _warn_only("dummy-warn")]
        dec = core.dispatch(envelope({}, "feature-merge"), registry=reg)
        self.assertEqual(dec.decision, "block")            # floor block wins
        self.assertIn("floor-block", dec.module)
        # the co-matching warn is still recorded (not dropped)
        self.assertTrue(any(a.get("module") == "dummy-warn" for a in dec.annotations))

    def test_warn_hardens_to_block_post_flip_and_composes_with_floor(self):
        reg = [_floor("floor-allow", hit=False), _warn_only("dummy-warn")]
        dec = core.dispatch(envelope({}, "feature-merge"), registry=reg,
                            flip_state={"dummy-warn": "block"})
        self.assertEqual(dec.decision, "block")

    def test_real_security_gate_allow_plus_atomic_tracking_warn(self):
        # Integration: security-gate (floor) ALLOWS a non-sensitive feature-merge
        # while atomic-tracking (warn-only) WARNS that the tracking file is
        # missing -> composed WARN (pre-C-6 this warn was silently dropped).
        atomic = core.make_atomic_tracking_spec(
            {"event_types": ["feature-merge"],
             "tracking_file_patterns": ["**/harness-tracking.md"]})
        reg = [core.SECURITY_GATE_SPEC, atomic]
        payload = {
            "ticket": {"ticket_id": "HN-2", "sensitivity_flags": []},
            "changeset": {"files": [{"path": "docs/readme.md",
                                     "content": "notes"}]},
        }
        dec = core.dispatch(envelope(payload, "feature-merge"), registry=reg)
        self.assertEqual(dec.decision, "warn")
        self.assertIn("atomic-tracking", dec.module)

    def test_real_security_gate_block_still_records_atomic_warn(self):
        atomic = core.make_atomic_tracking_spec(
            {"event_types": ["feature-merge"],
             "tracking_file_patterns": ["**/harness-tracking.md"]})
        reg = [core.SECURITY_GATE_SPEC, atomic]
        payload = {   # sensitive, unsigned -> security-gate blocks
            "ticket": {"ticket_id": "HN-2", "sensitivity_flags": []},
            "changeset": {"files": [{"path": "src/auth/login.py",
                                     "content": "password check"}]},
        }
        dec = core.dispatch(envelope(payload, "feature-merge"), registry=reg)
        self.assertEqual(dec.decision, "block")
        self.assertIn("security-gate", dec.module)
        self.assertTrue(any(a.get("module") == "atomic-tracking" for a in dec.annotations))


class TestCommitBlock(unittest.TestCase):
    CFG = {"event_types": ["pre-commit", "pre-push"],
           "protected_branches": ["main", "release/*"]}

    def _spec(self):
        return core.make_commit_block_spec(self.CFG)

    def test_protected_branch_warns_pre_flip(self):
        dec = core.dispatch(envelope({"branch": "main"}, "pre-commit"),
                            registry=[self._spec()])
        self.assertEqual(dec.decision, "warn")
        self.assertEqual(dec.exit_code, 0)

    def test_protected_branch_blocks_post_flip(self):
        dec = core.dispatch(envelope({"branch": "main"}, "pre-commit"),
                            registry=[self._spec()],
                            flip_state={"commit-block": "block"})
        self.assertEqual(dec.decision, "block")

    def test_config_driven_glob_branch(self):
        dec = core.dispatch(envelope({"branch": "release/1.2"}, "pre-push"),
                            registry=[self._spec()])
        self.assertEqual(dec.decision, "warn")

    def test_unprotected_branch_allows(self):
        dec = core.dispatch(envelope({"branch": "feature/x"}, "pre-commit"),
                            registry=[self._spec()])
        self.assertEqual(dec.decision, "allow")

    def test_refs_heads_prefix_normalized(self):
        dec = core.dispatch(envelope({"ref": "refs/heads/main"}, "pre-commit"),
                            registry=[self._spec()])
        self.assertEqual(dec.decision, "warn")

    def test_no_hardcoded_default_branches(self):
        # DEFAULT config protects nothing -> 'main' allows unless configured.
        default_spec = core.make_commit_block_spec(hooks.DEFAULT_COMMIT_BLOCK_CONFIG)
        dec = core.dispatch(envelope({"branch": "main"}, "pre-commit"),
                            registry=[default_spec])
        self.assertEqual(dec.decision, "allow")


class TestAtomicTracking(unittest.TestCase):
    CFG = {"event_types": ["feature-merge"],
           "tracking_file_patterns": ["docs/**/harness-tracking.md"]}

    def _spec(self):
        return core.make_atomic_tracking_spec(self.CFG)

    def _merge(self, files, ticket_id="HN-2"):
        return {"ticket": {"ticket_id": ticket_id},
                "changeset": {"files": files}}

    def test_missing_tracking_file_warns_pre_flip(self):
        dec = core.dispatch(
            envelope(self._merge([{"path": "src/x.py", "content": "code"}]),
                     "feature-merge"), registry=[self._spec()])
        self.assertEqual(dec.decision, "warn")

    def test_missing_tracking_file_blocks_post_flip(self):
        dec = core.dispatch(
            envelope(self._merge([{"path": "src/x.py", "content": "code"}]),
                     "feature-merge"), registry=[self._spec()],
            flip_state={"atomic-tracking": "block"})
        self.assertEqual(dec.decision, "block")

    def test_tracking_touched_but_entry_missing_warns(self):
        files = [{"path": "docs/dev-team/harness-tracking.md",
                  "content": "| HN-1 | ... |"}]   # no HN-2 row
        dec = core.dispatch(envelope(self._merge(files), "feature-merge"),
                            registry=[self._spec()])
        self.assertEqual(dec.decision, "warn")

    def test_tracking_updated_with_entry_allows(self):
        files = [{"path": "docs/dev-team/harness-tracking.md",
                  "content": "| HN-2 | commit-block module | ... |"}]
        dec = core.dispatch(envelope(self._merge(files), "feature-merge"),
                            registry=[self._spec()])
        self.assertEqual(dec.decision, "allow")

    def test_unconfigured_is_noop(self):
        default_spec = core.make_atomic_tracking_spec(
            hooks.DEFAULT_ATOMIC_TRACKING_CONFIG)
        dec = core.dispatch(
            envelope(self._merge([{"path": "src/x.py", "content": "c"}]),
                     "feature-merge"), registry=[default_spec])
        self.assertEqual(dec.decision, "allow")


class TestClickupGate(unittest.TestCase):
    CFG = {"event_types": ["pre-pr"], "allowed_read_verbs": ["GET"],
           "targets": ["clickup.com"]}

    def _spec(self):
        return core.make_clickup_gate_spec(self.CFG)

    def test_allowed_get_passes(self):
        dec = core.dispatch(
            envelope({"clickup_ops": [{"verb": "GET"}]}, "pre-pr"),
            registry=[self._spec()])
        self.assertEqual(dec.decision, "allow")

    def test_write_verb_blocks(self):
        dec = core.dispatch(
            envelope({"clickup_ops": [{"verb": "POST"}]}, "pre-pr"),
            registry=[self._spec()])
        self.assertEqual(dec.decision, "block")

    def test_unknown_verb_blocks_default_deny(self):
        dec = core.dispatch(
            envelope({"clickup_ops": [{"target": "clickup.com/task/1"}]}, "pre-pr"),
            registry=[self._spec()])
        self.assertEqual(dec.decision, "block")

    def test_malformed_op_blocks(self):
        dec = core.dispatch(
            envelope({"clickup_ops": ["not-a-dict"]}, "pre-pr"),
            registry=[self._spec()])
        self.assertEqual(dec.decision, "block")

    def test_no_clickup_ops_allows(self):
        dec = core.dispatch(envelope({}, "pre-pr"), registry=[self._spec()])
        self.assertEqual(dec.decision, "allow")

    def test_generic_calls_filtered_by_target(self):
        # a write to a ClickUp target via the generic `calls` list -> block;
        # a write to a non-ClickUp target is ignored.
        payload = {"calls": [{"verb": "POST", "target": "https://api.clickup.com/v2/task"},
                             {"verb": "POST", "target": "https://example.com/other"}]}
        dec = core.dispatch(envelope(payload, "pre-pr"), registry=[self._spec()])
        self.assertEqual(dec.decision, "block")

    def test_floor_precedence_requested_mode_cannot_soften(self):
        dec = core.dispatch(
            envelope({"clickup_ops": [{"verb": "DELETE"}]}, "pre-pr",
                     requested_mode="warn"),
            registry=[self._spec()], flip_state={"clickup-gate": "warn"})
        self.assertEqual(dec.decision, "block")       # floor: unconditional
        self.assertEqual(dec.exit_code, C.EXIT_BLOCK)


class TestClickupDefaultDenyAirtight(unittest.TestCase):
    """HK-1: the SHIPPED default clickup-gate must catch ClickUp writes on BOTH
    the clickup_ops and the calls path, with no config, and an empty
    clickup_ops must not suppress the calls check."""

    def test_default_config_blocks_write_via_calls(self):
        p = {"calls": [{"target": "https://api.clickup.com/api/v2/task/1",
                        "verb": "DELETE"}]}
        dec = core.dispatch(envelope(p, "pre-pr"), registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

    def test_empty_clickup_ops_does_not_suppress_calls_check(self):
        p = {"clickup_ops": [],
             "calls": [{"target": "https://app.clickup.com/x", "verb": "POST"}]}
        dec = core.dispatch(envelope(p, "pre-pr"), registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "block")

    def test_default_config_allows_get_via_calls(self):
        p = {"calls": [{"target": "https://api.clickup.com/api/v2/task/1",
                        "verb": "GET"}]}
        dec = core.dispatch(envelope(p, "pre-pr"), registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "allow")

    def test_non_clickup_write_ignored(self):
        p = {"calls": [{"target": "https://example.com/x", "verb": "POST"}]}
        dec = core.dispatch(envelope(p, "pre-pr"), registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "allow")

    def test_uppercase_and_mixed_case_host_still_blocks(self):
        # HK-4: HTTP hostnames are case-insensitive; a write to an upper/mixed
        # case ClickUp host must still be identified and blocked.
        for host in ("https://API.CLICKUP.COM/api/v2/task/1",
                     "https://Api.Clickup.Com/api/v2/task/1"):
            p = {"calls": [{"target": host, "verb": "DELETE"}]}
            dec = core.dispatch(envelope(p, "pre-pr"), registry=[core.CLICKUP_GATE_SPEC])
            self.assertEqual(dec.decision, "block", host)

    def test_case_insensitive_does_not_overbroaden_non_clickup_host(self):
        # A genuinely non-ClickUp host (upper-cased) must still NOT be treated
        # as ClickUp -> the write is ignored by this gate.
        p = {"calls": [{"target": "https://EXAMPLE.COM/x", "verb": "POST"}]}
        dec = core.dispatch(envelope(p, "pre-pr"), registry=[core.CLICKUP_GATE_SPEC])
        self.assertEqual(dec.decision, "allow")


class TestDispatchErrorPosture(unittest.TestCase):
    """HK-2/C-8: dispatch never raises; a floor crash fails closed (block), a
    non-floor crash fails to warn (pre-flip); co-matching reasons preserved."""

    @staticmethod
    def _raising(name, floor):
        def handler(event):
            raise RuntimeError("%s exploded" % name)
        return core.ModuleSpec(name, lambda e: e["event_type"] == "feature-merge",
                               handler, immutable_floor=floor)

    def test_raising_floor_fails_closed_block(self):
        dec = core.dispatch(envelope({}, "feature-merge"),
                            registry=[self._raising("bad-floor", floor=True)])
        self.assertEqual(dec.decision, "block")

    def test_raising_nonfloor_fails_to_warn_pre_flip(self):
        dec = core.dispatch(envelope({}, "feature-merge"),
                            registry=[self._raising("bad-nonfloor", floor=False)])
        self.assertEqual(dec.decision, "warn")
        self.assertEqual(dec.exit_code, 0)

    def test_raising_nonfloor_blocks_post_flip(self):
        dec = core.dispatch(envelope({}, "feature-merge"),
                            registry=[self._raising("bad-nonfloor", floor=False)],
                            flip_state={"bad-nonfloor": "block"})
        self.assertEqual(dec.decision, "block")

    def test_co_matching_reasons_preserved_when_one_module_raises(self):
        def hit_handler(event):
            return core.ModuleResult(hit=True, module="keep-floor",
                                     reasons=[{"code": "KEEP_ME"}],
                                     annotations=[])
        keep_floor = core.ModuleSpec("keep-floor",
                                     lambda e: e["event_type"] == "feature-merge",
                                     hit_handler, immutable_floor=True)
        dec = core.dispatch(envelope({}, "feature-merge"),
                            registry=[keep_floor, self._raising("bad", floor=True)])
        self.assertEqual(dec.decision, "block")
        codes = {r.get("code") for r in dec.reasons}
        self.assertIn("KEEP_ME", codes)        # co-matching module not discarded
        self.assertIn("MODULE_ERROR", codes)   # the crash contributed too

    def test_dispatch_does_not_propagate_on_handler_crash(self):
        try:
            core.dispatch(envelope({}, "feature-merge"),
                          registry=[self._raising("boom", floor=False)])
        except Exception as exc:  # noqa: BLE001
            self.fail("dispatch() propagated %r instead of failing closed" % exc)


class TestAtomicTrackingWordBoundary(unittest.TestCase):
    """Security nit: ticket-id 'entry present' is a word-boundary match, so a
    prefix collision (HN-2 vs HN-21) does not falsely satisfy the check."""

    def test_prefix_collision_does_not_satisfy(self):
        spec = core.make_atomic_tracking_spec(
            {"event_types": ["feature-merge"],
             "tracking_file_patterns": ["**/harness-tracking.md"]})
        p = {"ticket": {"ticket_id": "HN-2"},
             "changeset": {"files": [{"path": "docs/harness-tracking.md",
                                      "content": "| HN-21 | other feature | ... |"}]}}
        dec = core.dispatch(envelope(p, "feature-merge"), registry=[spec])
        self.assertEqual(dec.decision, "warn")   # HN-2 entry genuinely missing

    def test_exact_token_satisfies(self):
        spec = core.make_atomic_tracking_spec(
            {"event_types": ["feature-merge"],
             "tracking_file_patterns": ["**/harness-tracking.md"]})
        p = {"ticket": {"ticket_id": "HN-2"},
             "changeset": {"files": [{"path": "docs/harness-tracking.md",
                                      "content": "| HN-2 | this feature | ... |"}]}}
        dec = core.dispatch(envelope(p, "feature-merge"), registry=[spec])
        self.assertEqual(dec.decision, "allow")


class TestMatchingIsPlatformIndependent(unittest.TestCase):
    """HK-5: _matches_any is case-SENSITIVE on every platform (fnmatchcase),
    matching git's canonical case-sensitivity; glob metacharacters preserved."""

    def test_differently_cased_branch_not_matched(self):
        self.assertFalse(hooks._matches_any("Main", ["main"]))
        self.assertTrue(hooks._matches_any("main", ["main"]))

    def test_differently_cased_path_not_matched(self):
        self.assertFalse(hooks._matches_any("DOCS/X.MD", ["docs/x.md"]))
        self.assertTrue(hooks._matches_any("docs/x.md", ["docs/x.md"]))

    def test_glob_metacharacters_preserved(self):
        self.assertTrue(hooks._matches_any("docs/dev/harness-tracking.md",
                                           ["docs/**/harness-tracking.md"]))
        self.assertTrue(hooks._matches_any("release/1.2", ["release/*"]))
        self.assertTrue(hooks._matches_any("v3", ["v?"]))
        self.assertTrue(hooks._matches_any("main", ["m[af]in"]))
        self.assertFalse(hooks._matches_any("feature/x", ["release/*"]))
        # glob is still case-sensitive
        self.assertFalse(hooks._matches_any("RELEASE/1.2", ["release/*"]))


if __name__ == "__main__":
    unittest.main()
