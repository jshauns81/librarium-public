# Contents planner removal: inspection v11

[L091](../decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them)
now also removes the contents planner. The review-copy generator that consumed
contents plans is gone, and a book's table of contents is rebuilt at the source, so
a proposal to rebuild navigation could not be acted on. Inspection reads and checks a
table of contents and reports a problem; it proposes nothing. This entry stacks on the
review-copy removal.

## Removed

- `contents_planning`, `contents_rules` and `contents_observations` (2,177 lines) and
  their use in `epub_inspection` (the plan step, the observation attach/detach and
  record budgeting, the per-document `blocks`) and `file_inspections` (plan validation,
  the compact `result.contents_plan` and its summary for new reports).
- The tests that only covered the planner (`test_contents_planning`,
  `test_contents_plan_integration`, `test_contents_rebuild`, 955 lines) and the planner
  cases in the empty-navigation, source-position and file-inspection tests.
- The interface: the contents-plan status line and panel, their types, styles and test,
  and the stale wording that promised a contents plan in the full report.

## Inspection v11

`librarium.epub-structure.v11` (v10 and earlier stay readable history). A new report
has no `contents_plan`, `contents_observations` or document `blocks`. Evidence only the
planner read is no longer captured: word and media offsets, body and non-heading word
counts, media counts, per-document anchor lists, link `ancestor_sources` and
`heading_index`, heading `word_count`, `has_id` and `only_link`, and `contents_signals`.
Headings (level, id, chapter number, label, source index), links (target, fragment,
source index; anchors keep label and ancestry), `source_element_count`, navigation
entries and every finding stay: checks, source attribution and the report view read them.

`empty_navigation` stays an error. It was downgraded to a warning only when the planner
proposed a rebuild, so a book with an empty table of contents now fails the structural
check and says so ("This book has no usable table of contents: its navigation lists no
entries."). A wax seal no longer looks at a plan: it needs a passed, complete check with
no flagged finding, which an empty table of contents still prevents.

## Older reports

Reports of v4 to v10 are immutable artifacts. They keep their stored plan (and, for v10,
observations), pass the same shape and binding checks as before without importing the
planner, and are served unchanged. The deeper v2 check that recomputed plan measures and
findings is dropped. A v11 report that carries a plan or observations is refused, and
pending v10 jobs refuse rather than run under v11, as in earlier policy bumps. The report
view shows no plan for any report; the preserved JSON still holds an old one.

## Release record

The compatibility record reads the policy constant, so it now names v11; the build-identity
and release tests were updated. No model change and no migration.

## Verified

- Python suite: 3,708 passed, 13 skipped (3,791 passed, 13 skipped on the base branch; the
  difference is the removed planner tests). It also passes under `-W error`. Ruff, mypy
  (including the upgrade scripts), `manage.py check` and `makemigrations --check --dry-run`
  (no changes) pass.
- Frontend: 887 tests (907 on the base branch), coverage thresholds met, type check, format
  check and production build pass.
- A search finds no kept reference to the removed modules, component, types or report fields
  except the stored-report handling kept on purpose: the old-plan shape checks, their tests and
  the decision, status and review records.
- A v11 report built from the synthetic fixtures has no `contents_plan`, no
  `contents_observations` and no document `blocks`; a stored v10-shaped report with a plan is
  served unchanged; an empty table of contents fails the structural check.
- The public-content gate passes.

There is nothing for the owner to test: no behaviour outside inspection reports and their view
changed.
