# BookPane

The selected book, side by side with the shelves on desktop and focused with Back on phones: book first, evidence after, review quieter than both.

Source: `LibraryBookPane.tsx`, `Synopsis.tsx`, `reading-room.css` (`.library-detail`, `.reading-book-top`, `.reading-disclosures`).

Order is fixed by the hierarchy:

1. **Top**: 9rem art (cover or BookFolio) beside the `pane-title` in `ink`, author, and bibliography in `meta` `muted` (series · position, kind · first published · editions).
2. **StatusWell**: the library state in words, with copy and check context.
3. **Synopsis**, visible above any engineering control. `No synopsis recorded` when absent.
4. **Actions**: `Review metadata` as a secondary button, then outbound links with `↗`.
5. **Disclosures**: Editions, Library evidence, Record details.

The pane is `surface` with a `soft-line` border and `radius-control`, sticky at `detail-pane` width from 960 × 680, scrolling on its own with a thin `line` scrollbar. The folio settles once over 300ms when the selection changes; polling never replays it. The title takes focus on selection (`tabindex=-1`) and Back returns focus to the entry.

The consumer provides the work, catalogue book (synopsis, editions), library evidence and check metadata.
