# BookFolio

The entry itself when no real cover is admitted: a composed, title-led folio, never a fake cover or an empty frame.

Source: `LibraryBookArt.tsx` (`.book-folio`), `reading-room.css`.

- 2:3 `.shelf-art` slot, `radius-art`, `soft-line` border, a vertical gradient from `surface` to `evidence-well`.
- Top: the series as an `eyebrow` (uppercase, `muted`; `Standalone and collected` when there is none) and the recorded position as a `folio-position` numeral in `copper`. Position 0 and missing positions show no numeral.
- The detailed emblem sits bottom-right as a watermark at opacity `folio-mark`, masked to fade, recoloured by the brand roles.
- Bottom: a 2rem × 2px `copper` rule, the title (`caption-title` at 1.3 line height, three lines), then author · first-published year (`small`, two lines).
- The folio is a size container: type scales down with `cqw` and the title drops to two lines under 150px.
- When an admitted cover exists it replaces the folio, and the position moves to a `badge` over the art.

The consumer provides the work (title, authors, first published, series membership and position) and a cover only when **UX standards** admits one.
