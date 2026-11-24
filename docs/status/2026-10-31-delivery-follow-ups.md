# Delivery follow-ups, 2026-10-31

The writer launcher now refuses `writer_state_unavailable` in one plain line, before
runtime verification or any Calibre start, when its state directory or that directory's
`config` folder is missing, not a private directory, a symlink, read-only or not
writable by the writer user. Structured launcher refusals no longer print a traceback.
A refusing writer never listens, so the dispatcher and interface keep reporting
`writer_unavailable` or `writer_capability_unconfirmed`. The image acceptance workflow
mounts the config directory for the enabled-launcher step and adds a step without a
state volume; neither has run on hosted CI yet.

Request notices in the delivery panel stay with the delivery, held-copy state or
review they were made for. A pending, refused or unconfirmed check or Undo, a stop
notice and an open Undo confirmation no longer appear beside another delivery, and
returning restores them with their original request key. A refused delivery request
shows only beside the review it was sent from.

The separate-process HTTP proof now delivers a stylesheet-only copy of a second
synthetic book: source-derived scope with no identity hold, an explicit duplicate
acknowledgement, a verified receipt whose library bytes equal the held copy and differ
from the original only in the stylesheet and the EPUB 3 modification time, then
guarded Undo to the original bytes. A mixed title and stylesheet copy stays held.

Verification: 2,744 warning-strict Python tests and 11 subtests pass with no skips at
85.89% statement coverage over the backend and scripts, including the native gate,
kill vectors and HTTP proof against the pinned runtime; the exact native CI command
passes separately. Frontend checks pass 917 tests at 92.26% line coverage, plus types,
formatting, production build and dependency audits. A private synthetic browser proof against the real web, dispatcher
and writer roles passed thirteen journeys, adding the stylesheet-only delivery with
Undo and a lost outcome-check reply that stays with its own delivery. Seventy-two
samples in the default theme and Catppuccin Mocha at desktop, 390px, 320px and doubled
text had no accessibility-rule violations, overflow, unlabelled controls or small
touch targets. Actual-image acceptance and real-library or live-writer use remain
separate gates.
