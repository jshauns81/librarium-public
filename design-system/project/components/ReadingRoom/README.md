# ReadingRoom

A showcase of the Library page at desktop size: masthead, library heading with check context, reading tools, a series shelf, and the selected book beside it.

Source: `Library.tsx`, `LibraryBookPane.tsx`, `App.tsx`, `reading-room.css`.

Use it as the starting canvas for page-level design work. It composes the cards in this system exactly as the app nests them, so a change to a token or to `bundle.css` shows here in context. The two-column layout (shelves plus a `detail-pane` column) needs at least 960 × 680; below that the pane is focused with Back, and shelves become a horizontal strip. Counts and statuses are specimen values, not library evidence.
