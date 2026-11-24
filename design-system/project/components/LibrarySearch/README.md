# LibrarySearch

The search field that sits in the masthead and filters the Library it belongs to.

Source: `.library-search` in `reading-room.css`; rendered by `Library.tsx` into `#library-search-slot`.

A full-width input at `input-min` (44px below 960px) on `ground` with a `line` edge and `radius-control`, a 2.35rem left inset for the 16px magnifier button (an inline SVG stroked in `currentColor`, `muted`), and an `accent` caret. The label is visually hidden but present. The slot is `search-width` (22rem) on desktop. Search sits with the collection it changes; never place a global search that searches something else.

The consumer provides the query and submit handler; Back restores the query.
