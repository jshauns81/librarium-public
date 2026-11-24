# Orphaned acceptance suites, 2026-11-07

Six acceptance scripts under `.github/scripts` have no workflow caller (see the
[job audit's script inventory](ci-job-audit-2026-11-06.md#script-inventory-including-scripts-not-invoked-by-a-workflow)).
They come in three pairs: a Python helper that builds a disposable synthetic
library and seeds it over HTTP, and a Node script that drives headless Chrome
against the built app, a real backend and a separate worker. Each pair was
written to accept one feature and has not been run since.

**Recommendation.** Delete the paragraph-repair and author-alias pairs: every
behaviour they assert in the browser is already proved per-PR by component or
backend tests, and both have broken against the current interface. Keep the
unified-workspace pair. It is the only end-to-end journey through inspection,
comparison, assessment, correction, EPUBCheck, preservation and held delivery,
and no other suite runs that path. Repair it in a separate PR, then run it
nightly.

Deleting the two pairs saves no CI minutes, because nothing ran them. It removes
2,028 lines of harness that would otherwise need fixing after every interface
change. Running the unified suite nightly adds an estimated 15–25 pool minutes
per night (see [Cost](#cost)).

## Decision table

"Per-PR" means `backend/tests` and `tests/` under pytest, plus `frontend/tests`
under Vitest in jsdom, as `quality.yml` runs them. No per-PR job starts a
browser. axe runs in jsdom with colour contrast disabled. No per-PR check
measures overflow, 320-pixel layout, doubled text or 44-pixel touch targets on
rendered pages.

| Suite | Product promise it proves | Per-PR overlap | Needs | Passes on main? | Recommendation |
|---|---|---|---|---|---|
| `unified_workspace_acceptance.py` + `unified_workspace_browser.mjs` | Opening a book gives you one continuous workspace, from inspection through a checked, held corrected copy. Reload, Back and reopening return you to exactly your saved copy and choices, and never to another book's. | Backend lineage logic is covered (see [unified overlap](#unified-workspace)). The browser-to-worker-to-EPUBCheck path, real reload/Back/scroll, the offline/disconnect states and rendered layout/accessibility are not. | Built frontend; PostgreSQL; native libarchive, EPUBCheck and Java 21; Landlock; three web origins (main, ownership-truth, catalogue-only) plus a read-only truth server; inspection and delivery workers; reviewer Basic auth translated to `REMOTE_USER`; Chrome. | **No.** Theme selection is stale. With that patched, the run reaches the library correction and then stops at "Source history and recovery", a control the 2026-11-02 refinement replaced. A quiet rerun failed at the same step, so this is drift, not load. | **Keep. Repair, then nightly.** Manual command below until then. |
| `paragraph_repair_acceptance.py` + `paragraph_repair_browser.mjs` | When you opt into paragraph repair, Librarium joins only the broken printed-line paragraphs it can prove, shows you the counts before you choose, and the repaired copy still passes EPUBCheck and preservation. | Covered: counts and partial scope, pin drift, request pins, result/history counts (Vitest), real sandbox generation with real EPUBCheck (pytest). The budget `measure` action duplicates [the typography budget tool](../typography-budgets.tdd.md) and `test_inspection_process.py` limit enforcement. | Same single-origin stack as aliases, plus native imports in the client helper. | **No.** The browser run fails on four separate pieces of interface drift (below). Seed and `measure` pass. | **Delete.** |
| `author_alias_acceptance.py` + `author_alias_browser.mjs` | Searching the catalogue by a pen name or other recorded spelling finds that author's works without merging different people who share a name, and Back returns you to where you were. | Covered: every journey has a matching mounted test (see [alias overlap](#author-aliases)), and `test_author_discovery.py` covers search and ownership logic. Not covered: the rendered checks on author/comparison screens. | Built frontend; PostgreSQL; native libarchive, EPUBCheck and Java 21; one web origin; inspection worker; Chrome. | **No.** It expects the removed `librarium` theme and `#theme` dropdown. With a three-line theme fix, all 18 journeys and 100 rendered samples pass in 84 s. | **Delete.** The unified suite renders the catalogue and comparison rooms; alias-specific screens keep their mounted tests. |

### Why the two deletions

Both browser suites check behaviour that a mounted component test already
proves exactly. Their one unique contribution is the rendered matrix: axe with
contrast, overflow and touch targets at 1280, 390 and 320 pixels and at doubled
text. The unified suite runs that same matrix over the workspace and catalogue,
so one maintained harness keeps the rendered coverage. Three copies of the same
Chrome-driving code, each breaking separately, would cost more than they add.

The paragraph `measure` action records child margins, not a correctness
contract.

### What drifted

None of these is a product defect. Each is a harness assumption that later
interface work changed:

1. **Themes.** 2026-11-03, "two rooms, Light and Dark": theme IDs became
   `light`/`dark`, and with a library configured the `#theme` dropdown became a
   Settings gear. This affects all three suites.
2. **Search label.** "Search catalogue titles" became "Search catalogue titles
   or authors" when alias search shipped. This affects paragraph repair.
3. **Workspace layout.** 2026-11-01, unified workspace: the paragraph harness
   looks for results inside the assessment-free panel, but generated copies now
   live in a separate section. The real generation, EPUBCheck and preservation
   all passed; only the harness's lookup failed.
4. **History controls.** 2026-11-02, control and evidence refinement: the
   "Source history and recovery" disclosure became a "Generated-copy history"
   section, and "Open copy requested" became "Open copy updated". This stops the
   unified suite. The paragraph run separately stopped at "Back to review-copy
   history".
5. **Chrome startup.** Every harness gives Chrome 5 s to start, which fails on a
   loaded runner. This is environmental, but a nightly job needs a longer wait.

## Overlap detail

Test names are given as `file::test` or by their Vitest title. Coverage marked
"matched by title" is inferred from the test name rather than from reading the
test body.

### Unified workspace

- Exact saved selection reopens its source, and foreign IDs are refused:
  `backend/tests/test_book_workspace.py::test_generated_output_reopens_exact_ancestors_and_rejects_foreign_output`,
  `test_foreign_validation_same_bytes_and_title_is_refused` (matched by title).
- Malformed IDs return 400. Partial: `test_invalid_selection_is_not_ignored`
  covers `fg` and `fv`. The helper also checks `fo`, `fov`, `fa`, `faj` and `fda`.
- Captured, reviewed and delivery assessments stay distinct:
  `test_assessment_selection_is_bound_and_cannot_replace_generation_choice`,
  `test_later_delivery_assessment_is_independent_and_reconstructed`,
  `test_reviewed_later_assessment_survives_reload_without_delivery_authority`.
- Library resume: `test_library_resume_is_paged_scoped_and_reports_changed_inventory`.
- Unauthenticated delivery is refused:
  `backend/tests/test_delivery_api.py::test_delivery_routes_require_authenticated_reviewer`.
- UI logic, partial: `book-workspace-flow.test.tsx` "keeps confirmed progress and
  cancellation available after a transient poll failure";
  `corrected-output-flow.test.tsx` "recovers a saved intent after reload by key
  lookup only"; `candidate-assessment.test.tsx` "routes a queued later assessment
  separately from delivery and reopens its exact progress";
  `review-history.test.tsx` "restores filter/page on reload and Back…";
  `direct-library.test.tsx` "restores the departing %s control on browser Back…".
- Proved nowhere else:
  - EPUBCheck and preservation verdicts on jobs started from the browser and run
    by a separate worker;
  - real reload, Back/Forward and scroll positions;
  - workspace disconnect and offline recovery;
  - ownership-truth rendering;
  - the rendered matrix.

`tests/test_unified_workspace_acceptance.py` tests the helper's fixture cover
and manifest binding. It is the helper's only importer and stays with it.

### Paragraph repair

- Counts and partial scope before selection: `corrected-output-typography.test.tsx`
  "discloses literal hyphens, numbered clauses and partial document scope before selecting".
- Server pin drift and reload: "reloads a drifted paragraph pin and changed counts
  without retaining selection" and "explains pinned-value drift and reloads the
  choices before a new request".
- Exact plan pin in the request: "offers pinned paragraph repair without selecting
  it and preserves v2 history".
- Result and history counts: "shows actual paragraph counts in finished results and history".
- Reload recovery: "keeps a saved paragraph request and its pin across reload recovery".
- Real generation, EPUBCheck and preservation:
  `backend/tests/test_paragraph_repair.py::test_v2_hyphen_sandbox_and_actual_epubcheck`
  and `test_production_sandbox_round_trip`.
- Seeded options over HTTP:
  `backend/tests/test_paragraph_requests.py::test_paragraph_selection_plan_pin_replay_and_independent_output_check`
  and `test_paragraph_repair.py::test_css_holds_only_affected_document_and_accepts_agreeing_duplicates`.
- Child limits are enforced by
  `backend/tests/test_inspection_process.py::test_child_pid_and_limits_are_set_before_parser_import`,
  `test_wall_timeout_kills_and_reaps_child` and
  `backend/tests/test_typography_scale.py::test_measured_budget_policy`.
- Only missing: keyboard (rather than click) selection, and the rendered matrix.

### Author aliases

- Alias discovery through author, group, work and comparison: `author-groups.test.tsx`
  "discovers recorded spelling, retains alias query through author navigation, and
  passes exact work pins to source selection" (with jsdom axe);
  `package-comparison.test.tsx` "preserves multiple titles and ambiguous creator evidence".
- Conflict, reconnect and rediscovery: `author-comparison-target.test.tsx` "retries
  the selected pin after a conflict and only clears it on an explicit
  current-snapshot choice"; `author-groups.test.tsx` "uses explicit snapshot
  recovery and clears cross-version author IDs".
- Return context: `app.test.tsx` "returns from source selection to the same catalogue
  control, query, pins and scroll after discarding its target"; "retains the %s
  return path through source selection, reload and discard"; "respects %s intent
  while the selected-work return is waiting for detail"; "restores the %s list
  after comparison and reload, respecting newer %s input".
- Search, collision and ownership logic: `backend/tests/test_author_discovery.py`.
- Only missing: real touch scrolling at 390 and 320 pixels, and rendered checks
  on the author room.


## Cost

| Change | CI minutes |
|---|---|
| Delete paragraph and alias pairs | 0 saved; nothing ran them |
| Unified suite nightly, after repair | About 15–25 pool minutes per night (estimate), roughly 450–750 a month. Hosted fallback at $0.006 a minute would be $2.70–4.50 a month. |

## Proposed nightly workflow change (not made here)

This goes through the CI policy as its own reviewed PR, after a repair PR makes
the suite pass. The repair PR should:

- Update the theme selection to the current Light/Dark rooms and the Settings
  route.
- Lengthen the Chrome startup wait.
- Follow the "Generated-copy history" section and its "Open copy updated"
  buttons, which replaced the "Source history and recovery" disclosure.
- Add a committed stack launcher, `.github/scripts/unified_workspace_stack.py`,
  that starts the three origins, the truth server and the workers. Its reviewer
  role should mirror the `web` role in `delivery_arm_acceptance.py`.

The workflow change then adds a scheduled job, alongside the existing nightly
writer schedule, without changing any required check:

```yaml
# .github/workflows/delivery-writer.yml (already has schedule '17 3 * * *')
  rendered-workspace:
    if: ${{ github.event_name == 'schedule' || github.event_name == 'workflow_dispatch' }}
    runs-on: ubuntu-24.04
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@<pinned>   # persist-credentials: false
      - uses: astral-sh/setup-uv@<pinned>
      - uses: actions/setup-node@<pinned> # node-version: '24.22.1'
      # PostgreSQL 18.6 service as in quality.yml; Landlock check as in L078.
      - run: uv sync --frozen && npm --prefix frontend ci && npm --prefix frontend run build
      - run: |
          uv run python scripts/build_libarchive.py --prefix "$RUNNER_TEMP/libarchive" --build-dir "$RUNNER_TEMP/native-build"
          uv run python scripts/install_epubcheck.py --prefix "$RUNNER_TEMP/epubcheck"
      - run: uv run python .github/scripts/unified_workspace_stack.py --root "$RUNNER_TEMP/proof" -- \
               node .github/scripts/unified_workspace_browser.mjs --root="$RUNNER_TEMP/proof"
      # Upload results-full.json and failure captures as a short-retention artifact.
```

The job belongs in `delivery-writer.yml` because that workflow already carries
the nightly schedule and the policy permits that trigger. Open questions for that
PR:

- whether pool runners provide Chrome or need a pinned Chrome-for-Testing
  install;
- the artifact retention period;
- whether a nightly failure should notify the owner.

## Manual command until then

The [unified workspace evidence](../unified-book-workspace.tdd.md#running-the-browser-proof)
documents how to run the suite by hand.
