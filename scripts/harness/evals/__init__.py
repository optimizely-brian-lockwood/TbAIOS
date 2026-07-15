"""H-EVAL agent-behavior eval harness -- LIBRARY-ONLY.

Grades each GENERIC dev-team role on whether its recorded trajectory + output
caught the failures it exists to catch, against a HUMAN-ratified answer key,
with the judge never inventing ground truth.

Components (spec: docs/dev-team/architecture/2026-07-13-harness-evals-architecture.md):
  rubrics  - per-role rubric structure (DATA-driven; rubrics are files/config).
  labels   - human-ratified, immutable-at-eval-time label store (no judge write path).
  judge    - judge INTERFACE + deterministic StubJudge + activation-gated Claude adapter;
             the EgressGate is the ONLY producer of a GradingRequest (structural
             scrub-before-egress via the shared pii_scrub egress-to-judge floor).
  scoring  - trajectory-vs-output split, rubber-stamp signal, thresholds
             (>=0.90 general; exact-100% for security-defect classes).
  runner   - loads a fixture, applies the rubric, runs the judge, compares to the
             ratified labels; contract-v1-shaped where it crosses the core.

Generic + config-driven for TbAIOS promotion: rubrics key to the generic 11
dev-team roles, not to any engagement. No engagement-specific data. No live
external API calls (the real Claude adapter is activation-gated).
"""
