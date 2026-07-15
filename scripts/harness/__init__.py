"""contract-v1 harness core (library only).

This package is LIBRARY-ONLY. Nothing here is wired to a live hook, git config,
CI, or .claude/settings.json. Importing it has no effect on repo/commit/session
behaviour; the modules run only when a caller (a test, or a future adapter added
in a separate activation step) invokes them.

Modules:
  contract   - contract-v1 event envelope model, validation, response protocol.
  core       - dispatch/runner: envelope -> module -> policy resolution -> decision.
  pii_scrub  - fail-closed PII-scrub control (scrubber -> independent scanner).
"""
