# StatusWell

The library state of one work, in words, with the evidence needed to read it: copy, check coverage and date.

Source: `.library-status-well` and `.library-state` in `reading-room.css`; `LibraryBookPane.tsx`, `Library.tsx`.

- Well: `evidence-well`, `radius-control`, padding 0.75rem 0.85rem, `meta` size. The headline is weight 550 with a status dot; `accent` for `direct` and `contained`, `muted` otherwise.
- Context lines in `muted`: copy and match time, coverage label and date, and the honest caveats (`Not yet re-confirmed by a complete check.`, `Not confirmed either way.`).
- In a shelf caption the same state is a single `state` line with its dot.
- Use the strings in **Status labels**; the claims they may make are owned by **UX standards**. Colour supports the word; it never replaces it.

The consumer provides the work state, whether it is current, the first copy, and the listing's coverage and check time.
