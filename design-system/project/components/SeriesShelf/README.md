# SeriesShelf

One series in recorded order: a Literata heading with credit and an honest shelf summary, then a row of book entries.

Source: `Library.tsx` (`.series-shelf`, `.shelf-heading`, `ShelfSummary`, `.shelf-row`, `.shelf-entry`), `LibraryBookArt.tsx`, `reading-room.css`.

- Heading: `shelf-heading` h2 (one line with ellipsis on desktop, wrapping at 1.25rem below 960px), then shelf context in `label` `muted` (credit · summary), then `All N →` in `accent`. A `soft-line` rule closes the heading.
- Row: `--shelf-columns` equal columns with `space-shelf` gaps. Below 960px it becomes a horizontal scroll-snap strip; each entry snaps to the start.
- Entry: a `button` with `aria-pressed`. Art first (admitted cover with `shadow-art`, or the title-led **BookFolio**), then the caption: `caption-title`, author in `muted`, and the library state with its dot. Selected art gets a 3px `accent` outline at 3px offset.
- Screen-reader text in the caption announces position, title, author and state as sentences; keep it when restyling.
- Summary wording comes from `ShelfSummary` in `Library.tsx`; its claims follow **UX standards**. Never show a bare ratio.

The consumer provides the shelf (name, credit, counts, works with state and position) and the selection handler. Entries keep source order; never re-sort a series.
