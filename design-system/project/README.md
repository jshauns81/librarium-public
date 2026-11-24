Librarium is a personal Warhammer and Black Library reading room: readable, title-led folios first, engineering on demand. The creative north star is **the Reading Lamp, opened into a reading room**. Books, titles, authors and series carry the visual interest; ink surfaces, the supplied archivist emblem and the theme colours support them.

Use this system to design and build Librarium surfaces. Tokens are the shipping values from `frontend/src/themes.ts`; `components/bundle.css` is the application's own stylesheet, so a preview built on its class names renders the way the app does. When this page and the code disagree, the code wins and the next sync corrects the page.

## Rules this book does not own

The **UX standards** section is copied word for word from `docs/ux-standards.md`, the single owner of interface hierarchy, status semantics, disclosure, composition, cover admission, the accessibility floor and UI acceptance. Read it before any design. This book covers only the visual and copy treatment that implements it, from `DESIGN.md`.

## Content fundamentals

- **Status wording** follows **UX standards**. Use the exact strings in **Status labels**, which are generated from the app's label maps.
- **Say what is missing in plain words**: `Author not recorded`, `No synopsis recorded`, `No position`, `Standalone and collected`, `Various authors`.
- **Sentence case** for headings, buttons and labels: `Review metadata`, `Reload library`, `Finding details`. Book and series titles keep their own casing.
- **Verbs on actions, nouns on places.** Buttons say what happens (`Review metadata`, `Reload library`, `Retry`); navigation names the place (`Library`, `Catalogue`, `Reviews`).
- **Progress uses an ellipsis character**: `Reading library…`. Outbound links end with `↗` (`Open in Library Finish ↗`); shelf links end with `→` (`All 54 →`).
- **Middle dots join context**: `The Horus Heresy · Book 3 · first published 2006`. Counts use locale grouping and tabular figures.
- No emoji, no exclamation marks, no marketing voice. Address the reader only when an action needs it.

## Colour

Each theme supplies the same sixteen roles, plus three brand roles that recolour the emblem. Use the role, never a hex value.

- Set the page on `ground`; raise the masthead, shelf folios and the selected-book pane to `surface`.
- Text is `ink`. Authors, series, counts and labels are `muted`. Both are reading content and both clear 4.5:1 on every surface they sit on.
- **The Teal Means Here Rule.** `accent` marks action, focus, selection and live state, with the same meaning in every theme. Labels on an accent fill use `on-accent`.
- **The Colour Has a Job Rule.** `copper` is identity and headings (page `h1`, detail-section `h3`, folio numerals). `attention` sits beside failure wording and recovery. Colour alone never makes a status claim; a word always goes with it.
- **The One Fill Rule.** `selection-fill` marks a selected work or browsing choice; `pressed-fill` acknowledges hover and press. Hover is gated by `(hover: hover)`.
- `line` draws control edges and meets 3:1. `soft-line` separates related material and is never the only edge of a control.
- `evidence-well` groups comparisons, source claims and the library status well.

Two rooms ship: Dark (a candlelit scriptorium, the first-visit default) and Light (vellum and lapis), plus System, which follows the device through Light and Dark. Each is lit by the open book's cover. **Themes** lists every value with computed contrast.

## Type

- **The Reading Voice Rule.** Literata Variable sets book and page titles (`display`, `pane-title`, `shelf-heading`, `list-title`, `caption-title`). Controls, labels and figures use the system sans. Monospace (`mono`, `hash`) is only for exact identifiers and fingerprints.
- The root is 16px with `body` at line height 1.55. The synopsis uses `synopsis` (1rem / 1.7) at a 65ch measure.
- **The Readable Core Rule.** Authors (`author`), series and meaningful status (`meta`, 0.875rem) are reading content; never trade their size for more records per screen. `small` and `eyebrow` are for genuinely secondary annotation.
- **The Tabular Figures Rule.** Counts, positions, pages and progress use `font-variant-numeric: tabular-nums`.
- Long titles wrap naturally. Clamping is allowed only inside a folio (three lines of title, two of author), where the full title is repeated in the caption or the pane.
- The wordmark is the supplied outlined SVG, never text set in a substitute face.

## Space and layout

- Gutters grow from 1rem to `space-gutter-max` (3rem). Section gaps are about 1.4rem; detail sits `space-panel` to `space-panel-wide` from the list.
- `main` centres at `workspace-max`. List browsing holds to `list-max`, the series directory to `directory-max`, running text to `measure`.
- Shelves is the default view: one, two or three columns as entries gain room, with `space-shelf` between books. List is a remembered choice. Both keep the source series order.
- Side-by-side detail needs at least `split-min-width` by `split-min-height`; below that, detail is focused with Back. The pane is `detail-pane` wide in the Reading Room.

## Shape, depth and edges

- Records stay square (`radius-flat`). Controls, wells and the pane use `radius-control` (4px). Art and folios use `radius-art` (2px). Only dots are round.
- Depth comes from tone and rules, not shadows. `shadow-art` is reserved for admitted cover art, `shadow-popover` for the check-details popover.
- The selected-edge treatment is `inset 0 0 0 1px` in `line`. Do not wrap every field in an ornamental card.

## Interaction and accessibility

- Every interactive element is a named control with a visible focus ring: `focus-ring` (3px) in `accent`, offset 4px, visible on every surface.
- Fine-pointer buttons and nav items are at least `control-min`; inputs at least `input-min`; under `(pointer: coarse)` and below 960px every target is `target-coarse` square.
- **The Keep Your Place Rule.** Selecting a work preserves the browsing context; Back restores query, page, scroll and focus. Polling never resets the view.
- The accessibility floor and what to check are in **UX standards**. **Themes** computes the contrast of every token pair on each build.

## Imagery and iconography

- The **Librarium A** family is the identity anchor: emblem, separate outlined wordmark, horizontal and stacked lockups, and small and micro drawings. Use the small drawing for the masthead, the detailed emblem for large decoration and empty states, the micro drawing for favicons. Keep aspect ratios and transparent openings; never retrace, redraw or recolour outside the brand roles.
- In code, reference `brand/librarium-symbols.svg#emblem`, `#small` or `#wordmark` through `<svg><use>`; its fills read `--librarium-ink`, `--librarium-accent` and `--librarium-wordmark`, which `.brand` maps to the theme's brand roles.
- Covers follow the cover admission rules in **UX standards**. Without an admitted cover, the entry is the title-led **BookFolio**: series eyebrow, copper position, emblem watermark, copper rule, title and author.
- There is no icon set. Glyphs are typographic (`→`, `↗`, `·`, the disclosure chevron drawn in CSS) plus status dots. Do not add an icon library or emoji.
- The images under **Inspiration** are aspirational atmosphere; **UX standards** says how far they bind.

## Motion

The selected-work folio settles once over 300ms with a bounded perspective turn and 10px travel (`cubic-bezier(0.16, 1, 0.3, 1)`); polling never replays it. Hover fills take 160ms, progress advancement 180ms. Reduced motion removes all of these without removing focus or feedback. No reveal delay gates a task.

## Components

Previews are static renditions using the shipping class names and `components/bundle.css`. Each component's guidelines name its source file. There is no JavaScript bundle: the React components live in `frontend/src/`.
