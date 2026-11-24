# Layout and breakpoints

Breakpoints are thresholds to validate with real content, never a reason to compress book text.

| Width / condition | What changes |
| --- | --- |
| below 360px | The selected-book top stacks: art above the title. |
| below 620px | Navigation buttons flex to fill, the theme label is visually hidden, the connection note and experiment tag hide, `main` padding drops to 0.8rem, series links grow to 40px. |
| 620px+ | Comparisons, filters and provenance gain a second column; first-run sets the emblem at 128px beside the copy; gutters use clamp(1rem, 2.8vw, 3rem). |
| 740px+ | Catalogue Shelves uses two columns. |
| below 960px or below 680px tall | Masthead stacks: brand and theme picker, then a full-bleed navigation band, then full-width search. Controls are 44px. Shelf rows become a horizontal scroll-snap strip of min(8.5rem, 100vw − 3rem) entries. The check date, order description and shelf context hide. Detail is focused with Back. |
| 960px+ and 680px+ tall | Reading Room adds the 25rem selected-book column, sticky, scrolling independently below the masthead. Back is hidden. |
| 960–1280px (680px+ tall) | Shelf context wraps to its own line under the series title; library tools wrap. |
| 1280px+ | Catalogue collection/detail split becomes 1.25fr / minmax(350px, 1fr) with a 2.5rem gap; comparisons return to two columns. |
| 1400px+ | Catalogue Shelves uses three columns. |

## Surfaces

- **Masthead** (`surface`, `soft-line` bottom rule): brand, then workspace navigation, library search (22rem), theme picker. Padding 0.7rem 3rem.
- **Library heading**: `display` h1, the `list-summary` count, and the coverage summary with Details.
- **Library tools**: order description, the Order reading control, the Copies filter (inside `Options` on narrow screens), the Shelves/List group.
- **Series shelf**: `shelf-heading` h2, shelf context (credit · summary) and `All N →`; then a shelf row of `--shelf-columns` entries with 1.25rem gaps.
- **Selected book pane**: `surface`, `soft-line` border, `radius-control`, padding 1.25rem; art (9rem) beside title, author and bibliography; status well; synopsis; actions; disclosures.

## Container behaviour

Shelf art is a size container: below 150px the folio title drops to two lines at 0.95rem; from 200px folio type scales with `cqw` up to its token size. In Catalogue Shelves, entries under 20rem stack the cover above the text.
