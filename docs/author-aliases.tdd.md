# Recorded author discovery evidence

Issue 40 extends the reading room's existing pinned catalogue and source-bound
comparison. BLC owns canonical names and `author_alias`; LF's changeover requires
BLC aliases first while preserving original credits. Reuse the existing
`package_comparison.name_owners` collision check and complete-credit comparison,
not another resolver or nickname heuristic. No new dependency is needed.

## Contract and compatibility

Catalogue work search includes recorded aliases using literal, bound SQL
parameters and `EXISTS`, preserving canonical work order, 24-row pagination and
one row per work. Selected author and series filters remain intersections.
Original EPUB/library credits and source reports are never rewritten.

Additive `librarium.author-groups.v1` evidence carries the same version, digest
and fixture flag as its enclosing response. Listing groups describe the selected
author and alias-matching authors on the current page; detail groups describe
credited authors. Global normalized ownership checks include authors outside
the chosen work. Shared spellings show owner counts and ambiguity, without
merging authors or establishing person, work, ISBN or whole-file identity.

Presentation is capped at 64 groups, 32 aliases and eight matched spellings per
group, with exact recorded counts and explicit truncation. Matched spellings
outside the ordinary alias display cap still receive global collision checks.
These display caps never become comparison evidence or relax complete-coauthor,
admission, generation or writer gates.

Snapshot admission remains compatible with older catalogues without aliases.
Missing tables, incompatible schemas/views and malformed names, IDs, duplicates
or orphan aliases produce explicit unavailable states while canonical browsing
remains usable. They cannot produce alias agreement. Queries retain the existing
read-only immutable snapshot connection, trusted-schema restriction and two-second
deadline; no second snapshot is fetched to fill missing evidence.

Strict frontend decoding rejects malformed counters, groups, ownership counts,
cross-version names and mismatched snapshot pins. An older response without the
additive field reports that groups were not supplied. The source-comparison
continuation carries work/version/digest in the route, requires explicit source
and comparison choices, survives reload and preserves the catalogue return
context. Explicit reconnect discards the old version-owned work choice.

## Verification

The real pre-change discovery regression returned zero works for a recorded
alias where one canonical work was required. The RED checkpoint precedes the
implementation. Synthetic tests cover literal wildcard characters, injection
strings, deterministic pagination, global canonical/alias collisions, invalid
evidence, groups beyond display caps, coauthor coverage, exact old snapshots
and changed-byte 409 refusal. Existing title/surname, historical capture,
source/report binding and admission tests exercise the reused comparison.

The new group module has 100% statement coverage in the focused backend run.
A synthetic 8.8-MB snapshot with 50,001 authors and 100,001 aliases completed
alias/canonical/absent searches in 1.385/0.970/0.827 seconds under the unchanged
two-second query deadline. Statement counts were 17/17/15. A 25-coauthor
regression verifies one global ownership call per response. These measurements
are fixture observations, not a guarantee for every admitted 512-MB snapshot.

Final source checks passed 238 warning-strict backend tests, including catalogue
reviews/API, snapshot isolation, comparison, attribution and library matching.
The frontend suite passed 975 tests with 90.67% statement and 87.01% branch
coverage. Build, Python types (97 modules), Ruff, formatting, 23 workspace/privacy
tests plus 11 subtests, 18 archive hashes and owned-document links passed.
The existing bundle-size and progressive-document-adoption warnings remain.

Independent review found stale target state after discard and malformed work
titles passing decoding. Both were corrected with mounted regressions. Further
failing-first tests verify control/surrogate rejection and return focus/scroll.
No remaining actionable finding was reported in the independent pass; hosted
exact-head review remains separate.

The synthetic fixture and browser harness used for the rendered acceptance
below were removed after [the 2026-11-07 suite review](research/orphaned-acceptance-suites-2026-11-07.md);
mounted and backend tests own these journeys per PR, and the harness remains in
Git history. Its receipts below are historical for this block, not current checks.

```sh
uv run pytest -W error backend/tests/test_author_discovery.py \
  backend/tests/test_catalogue.py backend/tests/test_package_comparison.py \
  backend/tests/test_attribution_comparison.py backend/tests/test_library_matching.py -q
```

## Rendered acceptance and design gates

The frozen built app and separate worker passed four real synthetic journeys:
keyboard alias discovery through author/work/group inspection and explicit saved
source selection; reload with the same source and work pins; a real server 409
followed by explicit reconnect and rediscovery; and return with the original
query, work, author, focus, window/pane scroll and native disclosures restored.
API readback confirmed both original alias credits agree while `ready` remains
false. All synthetic input hashes remained unchanged.

164 rendered samples covered discovery, author, selected-work continuation,
source-choice controls and comparison at 1280/390/320 pixels and 320-pixel doubled
text. Discovery/author/comparison cover all shipped themes including system
light/dark; continuation/source controls cover the default theme. All samples
passed Axe, overflow, accessible-label and coarse-pointer 44-pixel checks.
No browser exceptions or console errors occurred. Representative mobile and
doubled-text captures were visually inspected.

A harness DOM-object truthiness error and initial catalogue-control route were
corrected without product changes. The full run then exposed disclosure collapse
clamping restored scroll; a failing mounted regression drove bounded disclosure
restoration in the exact pinned return context. Affected tests/build and the
complete rendered journey were repeated after that final product change.

Anti Slop during-mode delivery gates:

- Hard gate PASS: actual controls/journeys, 164 Axe/overflow/label/target samples;
  truthful empty/error/compatibility states; no fabricated identity claims.
- Purpose gate PASS: native disclosures keep recorded spellings beside authors;
  existing type, palette and controls preserve the reading room's hierarchy.
- Liveliness PASS: ENERGY 1 / RHYTHM 2 / MOTION 1; canonical author/work is the
  focal point, with the existing literary motif, spacing and selective accent.
- Craftsmanship PASS: mounted and rendered failure/recovery paths, all-theme
  checks and narrow/doubled-text inspection support the unchanged visual world.

Staged protected-denylist and outgoing secret scans passed. The complete payload
scan's three official checker checksum matches are byte-identical to the base;
they are not new credentials. Raw audit evidence remains private.

Chromium emulation does not establish physical-device or screen-reader audio
acceptance. Accounts remain planned separately. No deployment, installed-beta
update, real-library read/write or service restart belongs to this block.

## Parent review correction

Hosted review found that the source-comparison round trip dropped an earlier
Library or Reviews return origin. Two mounted regressions failed before the fix.
The comparison return now retains those origins through source selection, reload
and discard, then restores the original return actions and their saved context.
The browser also exposed the existing desktop-only hiding of the Reviews return
button; it now uses persistent return-action styling at every width.

After the correction, all 977 frontend tests and the production build pass.
The parent backend smoke passes all 20 discovery tests. The real synthetic
backend/worker journey was repeated: six journeys pass, with 104 fresh rendered
samples covering both restored return contexts across every theme, 1280/390/320
pixels and doubled text. These samples include the entire workspace and pass
Axe, overflow, labels and coarse-pointer targets. The incoming origins are seeded
saved browser contexts; mounted tests also execute both final return actions.
The earlier 164-sample discovery/comparison matrix remains its separately scoped
receipt, rather than a claim that those samples were rerun after this correction.

The first parent fixture run started before the new bundle completed, leaving
the disposable server's static index stale. Restarting that owned fixture after
the build corrected the blank startup. A later rendered failure established the
hidden desktop return button before its fix. Both failure receipts remain
private; no installed service was restarted. Format, workspace/archive, privacy
and manual Impeccable checks pass. Outgoing changes receive a separate redacted
secret scan before push.

## Results-list continuation

A further hosted review found that returning to the selected work still lost
the earlier results-list scroll and focused row. The saved list context now
travels with the comparison return, bound to its snapshot, query, filters and
page. The final Back action restores the list instead of revisiting Files.
Restoration waits for delayed results and yields to a newer user focus choice.

Three Catalogue/author/series regressions failed before transport was fixed;
delayed-result variants exposed the additional focus timing gap. The final
four-case regression also covers a reader focusing search while results load.
All 981 frontend tests, the production build/types, formatting, workspace/archive,
privacy and manual Impeccable checks pass after the correction.

The final synthetic backend/separate-worker browser run passes 12 journeys and
eight fresh default-theme render samples. Six journeys cover list-to-work-to-
comparison, reload, work and original list focus/scroll at 390px, 320px and
doubled text for Catalogue and author rooms. Series return has mounted coverage;
this fixture has no series and supplies no rendered series claim. The other six
journeys repeat the existing discovery, comparison, conflict and incoming-origin
paths. The new renders pass Axe, overflow, labels and coarse-pointer targets;
there are no browser or console errors. The earlier 164- and 104-sample matrices
remain separately scoped, with unchanged styles in this correction.

The first new browser attempt clicked Back before the detail's deferred focus
and scroll restoration finished. Waiting for that established restoration point
fixed the harness without another product change; the failed receipt is retained
privately. Physical-device/audio acceptance and installed services remain outside
this proof.

## Newer interaction during selected-work return

Hosted review exposed the same delayed-data concern in the selected-work return:
a later detail response could move focus away from search and restore an older
scroll position. Two failing-first cases cover newer focus and wheel input; a
positive case verifies normal restoration without a newer action. The pending
return now yields to focus, pointer, keyboard and scrolling interaction, cancels
its queued frame, and removes its listeners on cancellation, success or cleanup.

All 984 frontend tests and the production build/types pass. The frozen built
backend/separate-worker proof passes 15 journeys and eight fresh default-theme
render samples. Three desktop journeys hold the actual detail request across a
source-page reload, then verify newer search focus, wheel intent or uninterrupted
restoration when the request is released. The other twelve repeat the prior
comparison, recovery and list-return paths. Product-source fingerprints before
and after this run match; there are no browser or console errors. The existing
rendering and physical-device scope limits above still apply. Formatting,
workspace/archive, privacy and manual Impeccable checks pass; outgoing changes
receive their separate redacted secret scan before push.

## Shared cancellation for delayed returns

A further hosted finding showed that list restoration still needed cancellation
for scroll input that leaves focus on the body. App and Catalogue now share
`return-intent.ts`: a pending restoration becomes permanently inactive after
newer focus, pointer, keyboard, wheel or touch input. List cancellation survives
the later data-render effect and releases its listeners on completion or cleanup.
Four new failing-first wheel/touch/keyboard/pointer regressions cover this gap.

All 988 frontend tests and the production build/types pass. The final frozen
backend/separate-worker browser proof passes 18 journeys and twelve fresh
default-theme render samples. Three new narrow-screen journeys hold the actual
results request across source reload and Back, then verify wheel input, synthesized
touch movement or uninterrupted list restoration. The first two retain reader
focus and make no late programmatic scroll call; native gesture movement is not
misclassified as restoration. The prior fifteen journeys repeat, including the
delayed selected-work cases. Product-source fingerprints match before/after;
there are no browser or console errors. Existing all-theme and physical-device
scope limits above still apply; this correction changes no styles.
