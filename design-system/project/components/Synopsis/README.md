# Synopsis

The book's available synopsis, readable first: `synopsis` type at the 65ch `measure`, previewed to six lines with a named control for the rest.

Source: `Synopsis.tsx`; `.synopsis` in `style.css` and `reading-room.css`.

The expansion control appears only when the text is actually truncated, names its action (`Read the full synopsis` / `Show less`), and carries `aria-expanded` and `aria-controls`. In the Reading Room the text is `ink` and the heading is visually hidden; in Catalogue detail it is `muted` with a visible `About this book` heading. The full text always remains available.

The consumer provides the synopsis text; omit the component and show `No synopsis recorded` when it is empty.
