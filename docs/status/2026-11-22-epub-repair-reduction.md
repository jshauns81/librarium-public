# EPUB repair reduction: Librarium reads, checks and reports

[L091](../decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them)
retires EPUB correction and corrected-copy delivery. EPUB remediation is performed outside Librarium. Librarium reads books and
checks them (inspection, EPUBCheck, comparison and assessment) and reports
problems instead of repairing them. This entry covers the backend and repository
plumbing; the matching interface removal lands separately.

## Removed

- The generation pipeline: lexical metadata, navigation, anchor, stylesheet and
  paragraph repairs, independent output preservation, saved-output validation and
  the corrected-output jobs and API (17 modules, 6,303 lines).
- The delivery orchestration that could only deliver a review copy: preparation,
  approval, dispatch, reconciliation and Undo, their API and the `delivery_worker`
  command (2 modules and a command, 1,349 lines).
- The routes for corrections, corrected copies, output validations, delivery
  preparations, deliveries, `preparation` and `source-check`. They now answer the
  ordinary 404.
- The matching tests, the two arm acceptance scripts, the unified-workspace proof,
  the typography measure tool and the stylesheet parser dependency.
- Settings and environment variables only those modules read, and the corrected-copy
  and preservation assertions of the recovery receipts.

## Kept, and why

- Reading and checking: inspection, EPUBCheck, the sandboxes, content, attribution and
  identifier evidence, the assessment stack, library, catalogue and cover code. Inspection
  keeps its policy version and report shape, including the contents planner, which a later
  task removes.
- The writer core (`delivery_broker`, `delivery_writer`, `delivery_content_server`,
  `delivery_session`, `delivery_authorization`, `delivery_client`, `delivery_recovery`,
  `delivery_native`, `recovery_evidence`, `Dockerfile.writer`, the Calibre scripts and their
  tests). It is Librarium's library-write path until the owner decides it; nothing in the web
  or worker reaches it. `delivery_contract.py` is trimmed to the policy name the writer binds.
- Database schema and data. No migration, no model change: the `CorrectedEpub` and delivery
  tables, their guards and the job-kind constraints are untouched.

## What a bad file produces now

The inspection report names structural findings, EPUBCheck reports its messages, and an
assessment states identity and duplicate evidence. Nothing is rewritten, no review copy is
offered and no delivery exists. The assessment scope no longer says that correction admission
is held; the stored `correction_admission`, `blockers` and `ready` fields remain (removing them
needs an assessment policy bump).

## Old rows

Rows of the six retired kinds stay stored. The worker never claims or advances them. Job
detail, list and history return each as a plain record (title, state, message, timestamps, no
result, report, receipt or operator identity). Unfinished ones read as `cancelled` with
`stored_state` showing the database value, so nothing polls them or counts them as active. History
accepts `kind=retired` for all six kinds and each single kind. `POST /api/jobs/<id>/cancel` and the
ordinary job cancel end one left queued or running; the database lease guards only fire when a
retired row is leased, so cancelling is permitted. A saved workspace route that names a retired
selection opens at the inspection or its assessment.

## Verified

The Python suite had 4,423 tests before this change (4,408 passed, 14 skipped, 1 failed) and has
3,804 after (3,790 passed, 13 skipped, 1 failed) at 90% line coverage; the suite enforces no coverage
threshold. The one failure is the same before and after: `tests/test_release.py` needs `python3` to be
3.14, and it passes (189 release and promotion tests) when it is. Ruff, mypy, Django checks,
`makemigrations --check` (no changes), `uv lock --check`, the workflow linter and the privacy gate pass.
A search finds no kept Python file, workflow, compose file or script that names a removed module. The
native writer proofs (kill vectors and content server) need the pinned Calibre runtime and an
isolated network namespace, so they run in the writer workflow and were not run here; the fixture module
they now use produces byte-identical EPUBs to the helper it replaced.

There is nothing for the owner to test from this change alone.
