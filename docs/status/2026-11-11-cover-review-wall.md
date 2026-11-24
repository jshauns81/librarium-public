# Review cover wall

Review now opens a cover wall for native libraries, with the real application
header and a separate History section. To do, Done and Skipped counts, reason
filters, keyboard previous/next/skip, authenticated compare-and-set skips and a
read-only current-art preview use the existing census API. Missing current art
has an honest empty frame. Explicit Check again starts a census; opening the
screen does not start one. Partial, interrupted, unavailable and stale results
retain their limits.

Suggestions reuse the existing exact native metadata matcher, bound to book UUID,
library inventory and catalogue snapshot. A bounded authenticated suggestions
endpoint reads the visible page through one native snapshot and shared global
matching scans, then reuses local catalogue cover metadata. The client uses the
library deadline and refreshes the catalogue pin on polling and snapshot errors.
Unmatched or ambiguous evidence and unavailable art show “No suggestion yet”,
with current art where available. No source search, picker, Apply, library write,
recurring scan or deployment is introduced. The census continues to reuse the
ported Library Finish detectors; no new classification or image engine is built.

The API adds bounded-page author projection, global tab counts and server-side
missing/generated/small ordering. Done now records a previously flagged cover
that passes a later census, rather than implying a delivery receipt. Initially
healthy books remain outside that queue. [L085](../decisions.md#l085-cover-review-is-a-read-only-wall-with-exact-catalogue-suggestions)
records the presentation and observation semantics.

Verification uses synthetic data: focused PostgreSQL census/image/matching/cover
journeys, mounted frontend and decoder journeys, frontend coverage, type checking,
lint, production build and rendered desktop/phone checks in both rooms. Private
rendered evidence includes narrow reflow, enlarged text, desktop zoom, axe,
44-pixel targets and native preview focus return. These fixtures establish UI
behavior, not current library condition or installed-service acceptance. Local review verification passed 198 focused backend tests and all 1,252
frontend tests, with types, lint, build, migration and privacy checks. Fourteen
rendered samples have no document overflow, axe violations or undersized targets.
A held browser poll preserves Skip focus and availability. Required PR checks
supply remote acceptance.

Review fixes place the read-only preview on the current-cover thumbnail only;
missing or unreadable current art has no preview action. Large artwork is plain
and its accessible name identifies suggested or current art. Counts appear once
in the tabs. Background polling preserves Skip availability and focus. Shortcuts
ignore shifted keys and toolbar controls, and S applies within tiles only. Done
clears and hides the reason filter. Hidden healthy observations refuse skip and
unskip so neither action can manufacture Done. Default To do state stays out of
unrelated URLs. Synthetic rendered evidence uses genuinely blank art for the
blank-cover case and checks the existing phone navigation reflow separately
from document overflow.

There is no installed product test for the owner in this PR. After a separately
authorized installation, open Reviews → Covers, filter observations, skip/unskip,
preview current art and return to History. The picker and cover writes remain
later work.
