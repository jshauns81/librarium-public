---
name: Librarium
description: A personal Warhammer and Black Library reading room with readable title-led folios and engineering on demand.
colors:
  ground: "#1b1714"
  surface: "#15120f"
  ink: "#efe5d3"
  muted: "#bfb2a2"
  accent: "#9db6ef"
  accent-hover: "#bccdf5"
  on-accent: "#111a30"
  copper: "#ef9270"
  line: "#9a8b7b"
  soft-line: "#3f3731"
  selection-fill: "#2e2823"
  pressed-fill: "#27221e"
  evidence-well: "#221d19"
  progress-track: "#433a33"
  attention: "#f3a5ad"
  attention-line: "#d88d96"
typography:
  room-title:
    fontFamily: "EB Garamond Variable, EB Garamond, Georgia, serif"
    fontSize: "clamp(2.75rem, 5.6vw, 5.25rem)"
    fontWeight: 500
    lineHeight: 1
  room-body:
    fontFamily: "EB Garamond Variable, EB Garamond, Georgia, serif"
    fontSize: "1.125rem"
    lineHeight: 1.6
  numeral:
    fontFamily: "Cinzel, Georgia, serif"
    fontSize: "1rem"
    fontWeight: 600
  initial:
    fontFamily: "Cinzel Decorative, Cinzel, Georgia, serif"
    fontSize: "3.6em"
    fontWeight: 700
  display:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "clamp(1.65rem, 2.4vw, 2.15rem)"
    fontWeight: 550
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  work-title:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "clamp(1.65rem, 2.3vw, 2.25rem)"
    fontWeight: 550
    lineHeight: 1.25
  title-serif:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.15rem"
  title:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 550
    lineHeight: 1.25
  list-title:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.2rem"
    fontWeight: 550
    lineHeight: 1.4
  body:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    lineHeight: 1.55
  body-small:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.95rem"
  label:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.9rem"
  meta:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    lineHeight: 1.5
  caption:
    fontFamily: "ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    lineHeight: 1.6
  mono:
    fontFamily: "ui-monospace, monospace"
    fontSize: "0.8125rem"
rounded:
  control: "4px"
  flat: "0"
spacing:
  tight: "0.5rem"
  stack: "1rem"
  gutter: "1.5rem"
  gutter-wide: "2rem"
  section: "1.5rem"
  panel-gap: "2rem"
  panel-gap-wide: "2.5rem"
components:
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.5rem 0.8rem"
    height: "38px"
  button-secondary-hover:
    backgroundColor: "{colors.pressed-fill}"
  button-secondary-active:
    backgroundColor: "{colors.pressed-fill}"
  button-coarse:
    height: "44px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "0.5rem 0.8rem"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "0.5rem 0.8rem"
    height: "38px"
  nav-item-current:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    rounded: "{rounded.flat}"
  input-field:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0.4rem 0.6rem"
    height: "40px"
  theme-select:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    width: "9rem"
    height: "38px"
  disclosure-summary:
    textColor: "{colors.muted}"
    typography: "{typography.meta}"
    padding: "0.3rem 0"
    height: "36px"
  series-link:
    textColor: "{colors.accent}"
    typography: "{typography.label}"
    padding: "0.2rem 0.3rem"
    height: "38px"
  work-row:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.list-title}"
    rounded: "{rounded.flat}"
    padding: "0.85rem 0.75rem"
    height: "82px"
  work-folio:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.list-title}"
    rounded: "{rounded.flat}"
    padding: "1.15rem"
    height: "10rem"
  work-row-selected:
    backgroundColor: "{colors.selection-fill}"
  series-group:
    textColor: "{colors.muted}"
    rounded: "{rounded.flat}"
    padding: "0.5rem 0"
  job-state:
    textColor: "{colors.accent}"
  job-state-failed:
    textColor: "{colors.attention}"
  job-state-cancelled:
    textColor: "{colors.muted}"
  evidence-well:
    backgroundColor: "{colors.evidence-well}"
    textColor: "{colors.ink}"
    padding: "{spacing.stack}"
  progress-track:
    backgroundColor: "{colors.progress-track}"
    rounded: "{rounded.flat}"
    height: "0.45rem"
  error-notice:
    textColor: "{colors.attention}"
    rounded: "{rounded.control}"
    padding: "{spacing.stack}"
---

# Design System: Librarium

## Overview

### Illuminated direction (2026-11-03)

The owner approved the Illuminated direction; it supersedes the Reading Lamp
rules below wherever the two disagree. The book you are reading lights the room:
each cover gives a deep light for dark rooms and a pale light for light rooms
(computed in the browser, darkened until pale room text reads at 5:1, applied to
the root through CSSOM), plus a 12×18 haze. Every theme is a room built from its
own scheme (`frontend/src/room-tokens.ts`), so both rooms keep the light.

The rest is set like a manuscript. Covers are plates and a book without art is a
title page. Gaps in a series are dashed "not in your library" frames. Initials,
numerals and margin labels use a rubric (each theme's copper). EB Garamond carries
the text, Cinzel the numerals, and Cinzel Decorative appears only at 40px and up.
All three are self-hosted. A crimson wax seal marks a file whose latest inspection
passed. Home is the lit room: a silk ribbon at your chapter, a greeting from the
clock, real margin notes, the series in order with a rubric thread as far as you
have read, Lately received, a Chronicle of recorded events and a colophon.
Settings holds the rooms, room light and motion. Nothing shown may be invented:
counts, dates and states come from Calibre, the catalogue, jobs or the reader.

Creative north star: The Reading Lamp, opened into a personal reading room.
Librarium should feel like the maintainer's sophisticated Warhammer and Black Library
home. Literata titles, generous composition, the supplied archivist artwork and
coherent themes invite browsing. Engineering remains powerful and discoverable
from the book, series or active task.

The [UX standards](docs/ux-standards.md) own hierarchy, truth, disclosure,
composition, artwork admission, accessibility and acceptance. This file translates
that direction into visual treatments. The final L024 direction replaces the
compact-row mandate; it preserves Reading Lamp's identity and interaction quality.

The [Reading Room concept](images/inspiration/librarium-03-reading-room.png)
supplies literary atmosphere, reading comfort and a confident relationship between
book and artwork. Its reader layout, chapters, cover and claims are illustrative.
The target opens in Shelves: responsive book entries with admitted real art and
title-led folios where art is unavailable. A remembered List option supports
focused scanning. Both preserve the source series order. No cover availability
or reader feature is claimed by this design record.

The frontmatter and sidecar are the current **design target**, not a generated
inventory of shipping CSS or rendered acceptance. Their readable scale replaces
the earlier 15px/58px prescription. Frontend alignment and runtime verification
belong to the implementing task and [status](docs/status.md). Control height
values are minimums; text and wrapping may always increase them. The legacy
`work-row` token key now describes the folio treatment for existing consumers.

Key characteristics:

- Books, titles, authors and series carry the visual interest; ink surfaces,
  artwork and thematic color support them.
- Literata gives book and page titles a reading voice; system sans keeps controls
  and evidence precise.
- A 16px body target, larger book titles and generous folio padding support
  reading. Authors and series have their own readable space.
- Bounded reading measures, quiet navigation and useful grouping create rhythm.
- Selected-work detail preserves the route back to the same browsing position.
- Genuine supplied artwork and bounded folio motion keep the identity distinctive.

## Colors

The frontmatter records the Dark room, the default; `frontend/src/themes.ts`
owns the live values of both. Since 2026-11-03 there are two rooms. Dark is a candlelit
scriptorium: warm near-black ground, candlelit ink, a softened vermilion rubric
and pale lapis for focus and action. Light is vellum and lapis: warm vellum,
iron-gall ink, a vermilion rubric and lapis blue for action and focus. Gold
appears only in the emblem. Attention keeps its own rose or crimson, and colour
never carries a status alone.

### Theme contract

`frontend/src/themes.ts` owns the registry: Dark, Light and System. Dark is the
first-visit default. System follows the device live through Light and Dark.
Choices stored before the two rooms map to the nearer one: Parchment, Latte,
Alucard and Solarized Light become Light, and every other earlier id becomes Dark.
The id is rewritten once. In dark rooms the haze can only deepen the room
(`multiply`). In light rooms it only tints (`color`). The deep cover light is
darkened until pale room text reads at 5:1 and the dark rubric at 4.6:1.

Both rooms share composition and meaning; the historical `copper` role is the rubric. Browser storage uses `librarium.theme`, synchronized
across tabs; unavailable storage still allows switching for the visit. Preferences
do not synchronize across accounts or devices. Generated same-origin CSS and a
validated pre-paint script retain the existing CSP without remote theme code.
Published editor colors are adapted where contrast requires it.

The supplied Librarium A family owns the exact vector contours, outlined lettering
and small/micro drawings. Originals remain under `images/brand/librarium-a/`;
the application symbol asset uses CSP-compatible presentation fills. Theme brand
roles feed `--librarium-ink`, `--librarium-accent` and `--librarium-wordmark`.
Preserve geometry, transparency and the supplied matching brand colors. The
rejected trace and older raster derivatives remain historical assets. The favicon
uses the micro drawing and follows native browser appearance independently of
the selected site palette.

### Named Rules

**The Teal Means Here Rule.** Teal identifies action, focus, selection and live
state. Its meaning stays consistent through every theme.

**The One Fill Rule.** Selected Ink marks a selected work or browsing choice;
the current navigation destination uses an accent underline. Pressed Ink marks
hover/active interaction. Hover is gated by `(hover: hover)`.

**The Color Has a Job Rule.** Copper supports identity and headings, teal supports
interaction, and rose accompanies failure wording and recovery. Color alone
carries no status claim.

## Typography

Literata Variable 5.3 is bundled through `@fontsource-variable/literata` under
OFL-1.1, with Georgia/serif fallback. Controls and running text use the system
sans stack. Monospace serves exact identifiers and fingerprints.

The target root is 16px with body line height 1.55. Display headings use Literata
550 at `clamp(1.65rem, 2.4vw, 2.15rem)`; selected work titles use `clamp(1.65rem, 2.3vw, 2.25rem)`; folio
titles use 1.2rem and line height 1.4. Reviews titles use 1.15rem. Section headings
use system sans at 1rem/550. Authors use 0.95rem, with series and status at the
readable 0.875rem meta role (14px) and separate space to wrap. Synopsis uses 1rem
with 1.7 line height, labels about 0.85rem and occasional captions/mono
0.8125rem. None of these sizes fixes line count or truncates content. Descriptions
hold to approximately 65ch; long titles wrap naturally.

The supplied outlined SVG remains the wordmark, with its aspect ratio preserved.
Target emblem size is 2.6rem on desktop and 2.2rem on phones; wordmark width is
8rem/7rem respectively, with room to resize or wrap at enlarged text. It is
artwork, not text set in a substitute font.

### Named Rules

**The Reading Voice Rule.** Literata sets book and page titles; the supplied SVG
sets the wordmark. Controls, labels and figures use system sans.

**The Tabular Figures Rule.** Counts, recorded positions, pages and progress use
tabular numerals where stable alignment aids comparison.

**The Readable Core Rule.** Authors, series and meaningful status remain reading
content. Their legibility is not traded for more records in the viewport.

## Layout

Use a calm branded masthead and clear Library, Catalogue and Reviews navigation.
Allow breathing room and wrapping; a one-line header is not a constraint on zoom
or readable controls. Search sits with the collection it changes. Avoid an empty
comparison column before selection.

Shelves is the default responsive collection view; List is an explicit remembered
choice. Both keep source series order. The centered workspace has a 104rem maximum;
Shelves uses one, two or three columns as book entries gain sufficient space.
List browsing holds to 76rem and the series directory to 60rem. Selected detail
uses the wider workspace for its two readable columns. Give filters and folios
deliberate spacing rather than stretching a bare list across a large display.
Page gutters grow from about 1rem to 3rem. Section gaps are about 1.4rem;
selected-work detail has a 2 to 2.5rem separation from the list.

Retain the existing desktop split/focused-detail topology: side-by-side detail
is suitable from 960px when at least 680px tall and both columns stay readable.
The detail may scroll independently, reserving room for navigation and the footer.
Short windows and phones use focused detail with Back. Treat breakpoints as
layout thresholds to validate with actual content, never as a reason to compress
book text. Filters and comparison columns reflow when their content needs room.

### Named Rules

**The Keep Your Place Rule.** Selecting a work preserves the browsing context;
Back restores its query, page, scroll and focus. Polling does not reset the view.

**The Readable Folio Rule.** A work gets a prominent title and separate readable
author/series context. Shelves uses 1.15rem padding and a 10rem minimum; List uses
0.85rem by 0.75rem padding and an 82px minimum, growing freely for content.
Fixed two-line records and a single metadata
line are not requirements.

**The Recorded Order Rule.** Display recorded positions literally. Numbered
nonzero positions come first in ascending order, then records at 0, then records
without a position. Label the later groups with their real counts. An unknown
position is announced as No position. Never invent sequence or omit a work.

## Elevation & Depth

Retain ink surface layers, quiet rules and selected-state edges. Tonal separation
and space provide depth; avoid an ornamental card around each field. Existing
selected-edge treatment is `inset 0 0 0 1px var(--line)`. Keep the record silhouette
square and control radius at 4px. These treatments support a richer literary
composition without replacing the supplied identity.

## Components

### Controls and navigation

Use named controls with visible focus. The target fine-pointer button/navigation
minimum is 38px; inputs are at least 40px; coarse-pointer targets are at least
44×44px. Buttons use 0.5rem by 0.8rem padding. A 3px accent focus outline with
4px offset stays visible against every surface. A primary action belongs with
its task; secondary actions include refresh, retry, clear, cancel, Back and
pagination. Theme selection stays labelled and usable with enlarged text.

### Work folio

Keep the existing work-selection and Library disclosure semantics. Present a
Literata title, readable author and series, truthful status and the relevant
action with room to wrap. Counts and recorded position provide context without
competing with the title. Selected Ink and an inset edge identify selection;
Pressed Ink acknowledges hover. Real covers join the composition only through the admitted read contract under
UX standards. The scoped target reads an optional local cover directory, with
same-origin pinned-digest delivery and bounded batch lookup. It adds no HTTP
proxy, Unraid mount or redeployment. Where bytes or configuration are unavailable,
use title-led composition and supplied brand art, without fake cover frames or
invented thumbnails. Implementation and admission tests establish availability.

### Evidence and review

The selected work leads with title, bibliographic context and the available
synopsis, visible above engineering controls. Long synopses show a six-line preview
with a named expansion control; the full text remains available. Keep the review
action quieter than the book content. Group library evidence, editions,
reviews/progress and comparisons beneath it with
clear headings and breathing room. Comparisons use Evidence Ink with readable
source/value pairs, reflowing between one and two columns. UX standards decides
which provenance and diagnostic fields remain visible for the active task;
there is no blanket hidden-technical-information rule.

Progress retains distinct queued, running, failed and cancelled states, exact
server-confirmed results, and terminal announcements. Navigation and cancellation
stay available during jobs. Stored findings preserve source origin, object fields,
array values, zero, false, missing values and empty containers distinctly.
Synthetic inspections stay visibly separate from real catalogue metadata reviews;
neither makes ebook validation or ownership claims.

### Motion and recovery

The keyed selected-work folio settles once over 300ms with the existing bounded
perspective turn and 10px travel. Polling does not replay it. Hover fill uses
160ms; progress advancement 180ms. Reduced motion removes these effects without
removing focus or feedback. No reveal delay gates the task.

An error notice uses Attention Rose, a clear boundary and an inline recovery
control. Preserve saved content during connection failure. Unconfirmed commands
must offer retry/refresh without claiming success. Browser-offline and content
staleness remain distinct product states to verify; a design description does
not establish that every state is implemented.

## Application and verification

Use [UX standards](docs/ux-standards.md) for the single acceptance contract.
Preserve useful advanced capabilities as composition changes. Target tokens and
sidecar specimens are reviewable specifications; the implementation owner must
compare them against actual CSS and rendered real-content journeys. Do not claim
cover delivery, ownership, migration parity or production readiness from a design
record or a polished screenshot.
