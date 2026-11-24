# Delivery review fixes, 2026-10-31

Undo admission now refuses `409 active_intent` with the check's locator while an
outcome check of the same delivery is queued or running. A check also records the
projection revision before it observes; if a newer Undo or delivery outcome advanced
the projection first, the check's receipt is kept as historical evidence and the
current state, latest receipt and reservation stay as the newer operation left them.
Two-dispatcher tests reproduce both orderings. The panel now names a first read of
delivery evidence that failed, offers a retry, keeps history and shows no outcome
until it loads. Each running check or Undo stays with its own delivery when an earlier
delivery is opened from history, and an Undo refused as active follows the running
check.

Verification on the integrated branch: 2,722 warning-strict Python tests and 11
subtests pass with no skips, including the native gate, all twelve kill vectors and the
separate-process HTTP role proof against the pinned runtime. Frontend checks pass 907
tests at 92.2% line coverage, plus types, formatting, production build and dependency
audit. No browser proof was repeated; component tests cover both interface findings.
