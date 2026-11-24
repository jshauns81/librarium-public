# UX standards

This is the single owner of Librarium's interface hierarchy, status semantics,
disclosure, composition, cover admission, accessibility floor and UI acceptance
for Codex, Claude and Antigravity. `PRODUCT.md` owns outcomes; `DESIGN.md` owns
visual tokens and component treatments; [the skill map](skills.md) routes the
installed suites. Tokens and surface briefs implement these priorities. Resolve
contradictions here and reconcile dependent guidance in place, rather than adding
another overriding instruction. Refine the existing application incrementally.

## Experience and hierarchy

Librarium is a sophisticated, visually rich personal Warhammer and Black Library
home with powerful engineering available on demand. Generous readable composition
serves browsing and close examination. Screenfuls of database rows, maximum density
and small type are not success criteria.

1. Books and artwork where admitted, titles, authors, series and recorded order
   establish the first impression. Give them readable scale and breathing room.
2. Keep the relevant ownership or evidence status and common next action with
   their book or series. Search and navigation remain easy to find and use.
3. Editions, comparisons, match proof, reviews, history and technical detail open
   naturally from that context. Engineering tasks may make their evidence and
   controls primary while that task is active. A selected work's available synopsis
   is visible above engineering controls; its review action stays visually secondary
   to the book content.

The Reading Room inspiration is aspirational: carry its literary atmosphere,
visual richness and reading comfort into real workflows. Its chapter reader,
illustrated covers and quality claims are not implementation requirements or
proof. Preserve the supplied identity, all supported themes and useful motion.

## Truth, status and actions

- Status is short, true and specific: `Queued`, `Checking 3 of 12`, `Failed:
  snapshot changed`. Never show complete, matched or no issues without the
  underlying result. Unknown, stale and unavailable are separate states.
- Confirmed current ownership requires supporting current evidence. Historical
  matches retain their check date and source; direct, contained, pending and
  unknown retain their meanings. Historical positive evidence is not a current
  ownership guarantee.
- Incomplete, partial or truncated checks cannot prove absence. Show no match
  only within the scope of a completed check that supports it. Catalogue-only
  records establish bibliographic knowledge, not ownership or missing books.
- Put a failure or warning beside the affected object or action. Explain what
  happened, its effect and the available recovery. When no recovery exists, say
  what remains usable or what condition must change. Never collapse an actionable
  failure merely because its explanation is technical.
- Keep matching, history, refresh, reviews, search, integrations and diagnostics.
  Context and progressive disclosure organize their presentation; they do not
  remove functionality or obstruct a common action.

## Disclosure and composition

Choose disclosure by the user's task, rather than by whether a field sounds
technical. Keep source, check date, coverage limits and uncertainty visible when
needed to interpret a claim. A diagnostic required to recover from failure stays
with that failure. Long fingerprints, raw payloads and low-frequency details can
sit behind clearly labelled native disclosures; a single disclosure may group
related fields. Avoid nested caveat accordions and repeated boilerplate.

Default to responsive Shelves, with a remembered List option. Both preserve
source series order. Native Library Shelves places upright covers above the
book's text in a responsive grid; List uses compact horizontal rows with small
thumbnails. Retain title, author, series and formats in both. Allow fewer grid
columns and wrapped controls when narrow screens or enlarged text need room.
Use real admitted artwork where available and title-led
folios otherwise, with room for authors, series, status and action to wrap
naturally. Author and series are useful reading content, not tiny metadata to
squeeze onto one line. Compact controls can serve a task without making the whole
application compact. Tables or dense comparison layouts remain appropriate inside
an engineering task where alignment improves understanding.

Bound text measure on wide screens and give selected-work detail sufficient room.
Do not stretch a bare list across the viewport simply to consume width. Keep
search, selection, scroll and focus through updates and navigation; desktop
side-by-side detail and focused mobile detail must preserve the return path.

## Artwork and cover admission

Artwork and real covers are part of the visual ambition. Show covers only through
an admitted, reviewed read contract, such as BLC's content-addressed cover bytes,
with provenance, safe delivery and truthful fallback behavior. Where that contract,
configuration or verified bytes are unavailable, use composed title-led folios and
the supplied brand artwork. Do not fabricate cover images, imply a cover is
available, or introduce a proxy service as a side effect of a layout refinement. Missing cover data must not
make a book harder to identify or operate.
The dedicated cover-review task reserves honest empty frames for missing current
art, so absence stays visible beside catalogue suggestions. In ordinary browsing,
the entry itself is the title-led folio when artwork is absent; it does not need
a reserved image slot, fabricated book cover or simulated spine. Compose its
typography and context deliberately instead of showing an empty artwork frame.

## Accessibility floor

Keep body text, authors, series, statuses and controls comfortably readable; small
text is reserved for genuinely secondary annotation. On coarse pointers, every
target is at least 44×44px. Check keyboard order and visible focus, 200% zoom,
320px reflow, reduced motion and every shipped theme, including device light/dark
mode. Truth labels and recovery controls must survive narrow viewports and zoom.
Text contrast is at least 4.5:1; meaningful control edges and focus at least 3:1.

## Acceptance

Exercise Library browse, Catalogue search, a series in source order, a work with
editions/evidence, and a catalogue review including progress, cancel and failure.
Verify author/series navigation, matching, history, refresh and integration entry
points remain usable. Check current-supported ownership, historical evidence,
incomplete coverage, supported no-match and catalogue-only states without changing
their meaning. No visual improvement may turn unknown into missing or historical
into current.

Verify Shelves/List persistence, identical source order, visible available synopsis,
admitted-cover and no-cover fallback behavior. Review rendered hierarchy and
reading comfort at phone, tablet and desktop widths:
books and their context must lead before technical chrome. Report source checks
(tests, types, axe) separately from rendered runtime checks, naming viewport, theme
and data. Source tests do not establish rendered quality, fixture data is not
real-library evidence, and a design target is not proof it has shipped.
