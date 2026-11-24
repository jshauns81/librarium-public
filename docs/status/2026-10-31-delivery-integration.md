# Delivery integration, 2026-10-31

The delivery backend (including the security re-review fixes), its interface, the
Python child sandbox and the stylesheet operations now share one branch. Delivery
reads selected operations from the verified generation report: stylesheet operations
are source-derived and need no identity check, title and authors stay
catalogue-derived, a mixed copy keeps the stricter rule and any unknown operation or
kind holds the copy. Delivery code runs in the web and dispatcher roles, never in the
sandboxed Python children, and the writer modules stay importable by the pinned Calibre
runtime without application packages.

The interface now shows a writer refusal as its own plain-language reason beside the
sealed outcome, keeps "Cancelled before delivery" for reviewer stops only, treats an
output already present as uncertain, shows later drift beside a not applied outcome,
follows the active write job when an outcome check is refused, lists stylesheet
changes in the review and names the book in records opened from Reviews. The delivery
HTTP proof now requests held copies in correction options v2.

Verification: 2,715 warning-strict Python tests and 11 subtests pass with zero skips,
including the native gate, twelve kill vectors, the separate-process HTTP proof and
the sandbox late-import guard, at 85.94% statement coverage over the backend and all
scripts. The exact native CI command passes separately. Frontend checks pass 900 tests
at 92.48% line coverage, plus types, formatting, production build and dependency
audits; type, lint, Django, migration, workflow and workspace checks pass. A private
synthetic browser proof against the integrated roles passed eleven journeys, adding a
writer refusal and a not applied outcome with later drift to the earlier nine. Forty
samples in the default theme and Catppuccin Mocha at desktop, 390px, 320px and doubled
text had no accessibility-rule violations, overflow, unlabelled controls or small
touch targets. Actual-image acceptance, independent review and any real-library or
live-writer use remain separate gates.
