# Local catalogue cover picker

The Review cover wall opens one **Choose a cover** dialog. Current and selected
covers share a comparison frame; absent current art stays visibly absent.
Stored catalogue originals retain their measured dimensions. A verified stored
Enhanced derivative is the default at width 1000 or greater; otherwise the
original is the default. Safe smaller originals remain an explicit choice.
Different or disputed work evidence is visible but cannot be selected.

The picker reuses the native metadata matcher, pinned catalogue original and
derivative readers, and the isolated cover-facts decoder. The retained BL Catalog
cover projection, Library Finish comparison/preparation contracts, related plans
and changeover inventory were checked. No new search, matching, image engine or
provider dependency is introduced. Product copy uses Librarium and source names.

**Use this cover** creates an append-only PreparedCover record in the application
database. Its request, actor, catalogue pin, candidate digest, original/derivative
relationship, method, target identity, current-cover digest or confirmed absence,
and policy stay bound together. Compare-and-set selection identity and request
idempotency protect concurrent devices and uncertain retries. Fresh catalogue
reads revalidate a saved choice; unrelated snapshot changes preserve it while
changed artwork, policy, book identity or current cover refuses it with a reason.
Unresolved current covers can be compared but cannot produce a saved choice.
The wall reads saved selections once per page and compares the full book binding,
policy and current catalogue provenance before showing a pending selection.
Wall polling does not decode artwork. The book stays in To do until its existing
cover observation changes. Selection alone never changes queue completion.

The dialog provides original/Enhanced choice buttons, keys 1–9 that only select,
current/selected preview modes, per-choice reasons and source/method details.
Only selectable choices receive shortcut numbers. Comparison stays side by side
on phones; the key hint is hidden on narrow or touch screens. Missing current art
has one absence label, and blocked choices give their recorded reason. Source names
come from the recorded URL host, falling back to “Recorded source”.
Native modality, scoped shortcuts, focus trapping and preview return preserve the
task. The wall alone restores opener focus. Save refusals focus Refresh choices.
Confirmed status appears once in the dialog as
“Selected; awaiting approval”, beside a secondary close action. There are no
upscale, external search, Apply or other unimplemented controls. Library detail
has no existing cheap census-entry hook; its picker entry remains later work.

Migration 0014 adds a new table and index without changing existing review rows.
Always-enabled immutability and truncate guards and insert-only runtime grants
match retained evidence custody. Synthetic upgrade/reverse/reapply checks cover
the populated prior schema. This is selection custody, not delivery authority.

The library snapshot closes before catalogue inspection and inventory/source
revalidation follows inspection. Known pixel facts use a bounded process cache
keyed by content hash and policy, while every use still verifies the bytes and
fresh catalogue relationships. Unselectable candidates skip pixel decoding.
Transient decoder/sandbox failures return retryable 503 responses with recovery
copy; missing source rows report unavailable evidence.

Verification uses synthetic catalogue/library fixtures, focused PostgreSQL
candidate/census/matching/image/runtime-guard journeys, frontend mounted and
response-decoder journeys, frontend coverage, types, lint and build. Private
rendered evidence checks desktop, phone, 320px reflow and enlarged text in both
rooms, keyboard containment, preview return, saved-choice reload and axe. Source
and fixture-render checks do not certify an installed service or a real library.
Required PR checks provide remote acceptance.

All 337 focused backend/release tests and 1,265 frontend tests pass; frontend
line coverage is 92.29%. Types, lint, production
build, Django checks, migration drift, workspace integrity and the staged private
denylist gate pass. Twelve rendered samples pass after fixing selected-text
contrast, enlarged-text wrapping and the modal header reflow. The finish review
is scoped in-thread rather than independent approval. Review regressions cover
snapshot release with simulated slow inspection, changed source revalidation,
transient retries, byte-checked cache reuse, full-binding wall invalidation,
one saved-selection query per page, shortcut numbering and focus ownership.

No deployment, provider request, image enhancement or library writer is added or
activated. The installed application is unchanged; there is nothing for the owner
to test there. Review the PR and private evidence. Future work adds source and
preparation options, then a separately approved cover delivery/Undo boundary.
