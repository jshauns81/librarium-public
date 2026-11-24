# Masthead

The calm branded header: Librarium A brand, workspace navigation, the library search and the theme picker.

Source: `App.tsx` (`.masthead`, `.brand`, `.navigation`), `Identity.tsx`, `reading-room.css`.

- `surface` band with a `soft-line` bottom rule, padding 0.7rem 3rem, wrapping with gaps of 0.5rem 1.4rem. It may wrap at enlarged text; a one-line header is not a constraint.
- Brand: the `small` emblem at `emblem` (2.6rem; 2.2rem on phones) and the outlined wordmark at `wordmark` (8rem; 7rem). `.brand` maps `--librarium-*` to the theme's brand roles.
- Navigation items are transparent, `muted`, at least `control-min`. The current place has `aria-current`, `accent` text and a 2px `accent` underline with square corners. A running-job count may follow in tabular figures.
- Below 960px (or 680px tall) navigation becomes a full-bleed band between `soft-line` rules, and search drops to its own full-width row at 44px.
- The masthead may show `Offline`, `Request failed` or `Refresh progress` in `small` `muted`, never a coloured badge.

The consumer provides the navigation destinations, the active one, and the search form for the Library view.
