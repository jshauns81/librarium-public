# Catalogue dashboard redesign, 2026-11-10

PR #125 replaces the statistics-led Tool health page with the approved Illuminated
composition: one wax seal and field-derived sentence, a conditional source margin
note, a selectable week band, genuine added-work cover plates, and one quiet cover
progress bar with verified upscale examples. Existing details remain under one
native disclosure, including snapshot comparisons, source evidence, catalogue
size, jobs, sync and client reporting limits. Site navigation and the Catalogue
tabs retain their existing routes.

A disabled-by-default worker poll reads BLC's two unauthenticated status endpoints
into one latest-good Postgres row. Validation and field projection remove query
text and raw errors before persistence. Poll failures retain the last good fetch
time; observations older than five minutes use a muted seal and last-heard copy.
Requests never fetch BLC. Controls are a separately configured link to BLC's own
status page. The runtime grant matrix classifies the additive cache table.

Reuse includes BLC's status contract, Librarium's worker scheduling and read-model
pattern, snapshot comparison and digest-pinned local cover delivery. Added art
requires a work ID or explicit containment; shared collection art is labelled and
deduplicated, with no padding or title-based substitution. Optional derivative
examples use separately configured local blobs through the same admission path.
Library Finish's retained workflow and changeover boundaries remain intact.

Verification covers poll failures and shape limits, query/error scrubbing,
last-good retention, stale/unavailable/attention logic, direct and contained art,
exact derivative bytes and frontend rendering/disclosure. Rendered checks use
private read-only BLC observations and snapshot-bound art in both rooms at desktop,
phone and narrow reflow widths. Captures, actual observations and operational
continuation remain outside the repository. Final local and GitHub check results
are recorded in the PR; local verification does not replace server acceptance.

No merge, ready-for-review transition, deployment, production activation, beta
change or library mutation is included. Further work is independent review of the
proposed source and its server-side checks, followed by a separately authorized
activation if accepted. The installed application has nothing new for the user
to test from this PR alone.

The review fix round groups tripped sources by mapped reason and shows display
names with an unchanged-ID fallback. Other attention causes retain their own
rubric lines; the desktop cover sentence, progress and examples share one row.
Unavailable cycle history names its reason, while Details uses reported cycles
and budgets and labels cover figures as snapshot, live or last report with age.
Upscaled delivery checks its own directory setting, and a first remote snapshot
does not claim the whole catalogue as newly added. Polling now has a monotonic
throttle and performs HTTP outside the short compare-and-write transaction.
Regression coverage includes redirects, partial poll failure, concurrent updates,
embedded HTTP codes, source labels, unavailable history and cover-work states.
