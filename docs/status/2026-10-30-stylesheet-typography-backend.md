# Stylesheet typography backend, 2026-10-30

[L057](../decisions.md#l057-bounded-stylesheet-values-in-held-corrected-epubs)
implements the first three stylesheet operations in held corrected copies:
positive absolute line heights to normal, justified alignment to left, and gated dark text/white
background values to inherited/transparent values. Preparation pins a source-derived
plan without changing inspection v8. Generation and independent preservation prove
listed value splices, structure, completeness and unchanged documents/assets.
Versioned options/capture/results/reports preserve old history and replay;
old outputs cannot gain a new validation after the generator change.

Synthetic HTTP with a separate worker passes preparation, all three selections,
generation, mandatory real EPUBCheck/structural/preservation validation, exact
document-byte comparison, a colour refusal, replay, and a constructed v1 history
row with refused new revalidation. The v1 fixture proves contract readability,
not execution by a historical runtime. No real library or device was read/tested.
The review controls are implemented; reader rendering acceptance remains
a follow-up. No hosted image, deployment or library write is
claimed. Detailed local gate evidence and continuation remain private.

Before the independent-review corrections, local gates: 2,244 warning-strict Python tests plus 11 subtests pass at 90.51%
combined coverage; 713 frontend tests pass at 91.35% lines and 86.02% branches.

The integrated review interface for these operations is implemented. Choices show
each operation's effect, counts, bounded before/after sample and plain refusal
reasons; requests carry the exact plan pin; pin drift reloads the choices in
place; results and history report per-operation outcomes, changed stylesheets and
byte-identical document counts. Six Chromium journeys against the real web server
and a separate worker pass: all three offered with a subset generated and
validated, an unavailable colour operation, a real 409 after an in-flight pin
rewrite with reload and a new request, key replay after reload, keyboard-only
selection, and a constructed v1 history row whose new check the server refuses.
124 rendered samples across every theme plus System, desktop, 390/320px and
doubled text report no scoped axe, overflow, unlabelled-control, sub-44px coarse
target or runtime findings. One pre-existing coarse-pointer target gap found by
that proof has a fix. 776 frontend tests pass at 91.78% lines and 86.38%
branches; types, build, format and dependency audit passed for that UI revision.
Browser emulation is not physical-device, reading-app or screen-reader acceptance.
Mypy, Ruff check/format, Django/schema, lock/export parity, dependency audits,
frontend type/build/format, workspace integrity and the protected tracked-text
privacy gate pass. Those checks and the earlier rendered UI proof have distinct scopes; neither
establishes reader rendering or hosted-image acceptance.

Typography independent-review fixes now isolate adapter failures, bound all
additional scans, validate child plans without parent EPUB/CSS parsing on GET or
enqueue, and bind generation summaries to output bytes. Colour and RTL gates are
more conservative; escape tails and non-positive line heights are not offered.
The integrated sandbox preload correction is required: the first merge lacked
preloaded typography modules and could not run those jobs; the preload fix is
included. Current review verification and measured budgets are recorded in
[the TDD evidence](../typography-review.tdd.md). UI copy describes CSS changes without
promising reading-app behavior. These changes have no installed-service effect.

Review-fix gates: the warning-strict full Python suite passes 2,466 tests;
153 focused typography and real sandbox-guard tests pass with coverage appended,
including the last selector/prelude regressions. Combined backend/scripts line
coverage is 87.68%. All 780 frontend tests pass (91.78% lines, 86.38% branches).
Mypy, Ruff check/format, Django/schema checks, dependency audits, frontend format
and production build, workspace checks and the protected tracked-text privacy
gate pass. Separate-worker HTTP on the current source passes preparation,
selection, generation, real output validation, refusal and replay. These review
fixes have source/component and synthetic HTTP evidence; the earlier rendered
UI proof remains historical, and reading-app/device acceptance remains separate.
