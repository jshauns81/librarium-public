# Reading-room foundation: the Library as series shelves

Date: 2026-10-26. Amended after the final round-five polish. Owner: the maintainer. Status: **approved foundation**. the maintainer reviewed a
rendered proposal of the Library page and said: "I want what you showed me, this
is what the foundation of the app will be." This brief turns that render into an
implementation contract. Implement it exactly; where the render is silent, follow
[UX standards](../ux-standards.md) and [DESIGN.md](../../DESIGN.md).

This brief supersedes the "first viewport" paragraph of
[the collection brief](collection.md) for the Library page. Everything else in
that brief, L024 and the UX standards still applies.

## Reference artefacts

The approved render lives outside tracked source because it embeds catalogue
cover bytes:

- `.local/design/reading-room-render-2026-10-26.html` — self-contained page:
  the desktop Library at 1440px and the phone Library at 390px, with the exact
  CSS values used below. Open it in a browser; it needs no server.
- `.local/design/reading-room-render-desktop-1440.png` — screenshot of the above.

Every title, author, series position, synopsis, edition count, cover and
ownership state in the render came from real data on 2026-10-26: snapshot
`2026.10.24.2`, the local pinned cover cache, and a live read of Library Finish
(partial check taken 05:29 UTC). The render is therefore achievable with the data
the app already has. Nothing in it is a placeholder.

## What the page says

Librarium opens on the books, shelved by series in recorded order. Each shelf is
one series: its name, its author, a truthful one-line summary, the first few
books as real covers or composed folios, and a link to the full series. One book
is selected and its detail sits beside the shelves. Technical depth (editions,
evidence, record details, the metadata review) is one tap away, collapsed by
default, never hidden.

## Composition: desktop (≥ 960px wide and ≥ 680px tall)

Values are the render's CSS. Use theme tokens only; no new colours.
The page ground carries the reference's copper radial glow:
`radial-gradient(1200px 420px at 18% -10%, copper at 10% alpha, transparent 70%)`.
Keep its paint area at the first viewport and verify text contrast in all eleven themes.

**Masthead** (`surface`, 1px `soft-line` bottom, padding `.7rem 3rem`, gap 1.4rem)

- Emblem 2.6rem, wordmark 8rem (existing `ArchivistMark` and `LibrariumWordmark`).
- Navigation `Library · Catalogue · Reviews`: 38px items, muted text, current item
  in `accent` with a 2px `accent` underline (existing rule).
- Library search moves into the masthead on the Library page: 40px field, 22rem
  wide, right-aligned, search glyph, placeholder "Search titles, authors or
  series". It is the same control and query parameter as today.
- Theme picker at the far right, labelled "Theme", 38px, 9rem.

**Workspace** grid `minmax(0,1fr) 25rem`, column gap 2.5rem, padding
`1.5rem 3rem 2.5rem`, max width 104rem, centred.

**Heading row** (space-between, top-aligned, margin-bottom .9rem)

- `h1` "Your library": Literata 550, `clamp(1.65rem, 2.4vw, 2.15rem)`, copper,
  letter-spacing -.02em. Subline muted .95rem: "1,698 matching titles" (the real
  total from the listing).
- Right: check status, muted .875rem, copper dot .55rem: "Partial check · Oct 26,
  12:29 AM · Details". "Details" is a native disclosure that opens the existing
  check context: coverage explanation, catalogue version, snapshot token, and the
  Reload library control. Complete checks read "Complete check · date".
  Align the check line with the subline. Its content opens as a surface panel
  beneath the heading row; opening Details cannot move the h1 or subline.

**Tools row** (margin-bottom 1.6rem, gap .6rem)

- Left, muted .95rem: "Shelved by series, in recorded order" (changes with Order).
- `Order` select: **Series** (new, default), Title, Author. 38px, 1px `line`
  border, 4px radius, label in muted small text inside the control.
- `Copies` select: existing options, same control style.
- Shelves / List segmented control: existing behaviour and persistence; pressed
  segment uses `selection-fill` background and `accent` text.

**Shelf** (one per series, margin-bottom 2rem)

- Header: 1px `soft-line` rule beneath, padding-bottom .45rem, items on the
  baseline, gap 1rem. Series name Literata 550 1.4rem. Context muted .9rem, for
  example "Dan Abnett · 45 of 87 shelved with a saved match". Right-aligned
  accent link "All 87 →" to the existing series view.
  Count pinned author-role credits by deduplicated canonical name over matched
  works. Show the top author if they cover at least half; otherwise the top two
  joined with "and" if their unique works cover at least half; otherwise "Various
  authors". Never alphabetise credits or use raw LF credit strings. Cap credit
  width and keep the header and All N on one line at 1440px.
- Row: exactly one CSS grid row, gap 1.25rem. At a collection-workspace width
  of at least 1280px show five entries; at least 1100px show four; below that
  show three. No lone entry wraps. Keep a selected preview work visible when
  the row shrinks; the full-series link carries the rest.
- Preview: the first recorded positions, with one lead per nonzero numbered position.
  Choose a novel before other types, then earliest first publication, then title.
  Compare ISO YYYY / YYYY-MM / YYYY-MM-DD prefixes as tuples; unknown parts sort
  after known parts within the same year/month in both detail and shelves.
  Do not list alternates in the preview; give the lead a quiet muted
  "+1 at this position" or "+N at this position" line when needed. Position 0 is
  not a sequence position: zero and unpositioned works each remain individual
  entries in their recorded-order groups, without alternate collapse.
  All N retains every work in literal order.
  Canonical lead identity comes from every work in the pinned catalogue. A preview
  representative may come from the matched subset, while its Book N / Position N
  label remains consistent with catalogue detail and Title browsing.
- Entry caption: title Literata 550 1.05rem/1.35, margin-top .65rem; author muted
  .9rem; status line .8125rem in `accent` with a .5rem `accent` dot, margin-top
  .3rem. A second muted line carries candidate counts, e.g. "1 inbox candidate".
  Use deduplicated canonical names, at most two then "and N others"; use "1 other".
  Separate the accessible position/title/credit/status with punctuation.
- Cover entry: aspect 2/3, radius 2px, `0 10px 24px -14px rgba(0,0,0,.75)` plus a
  1px dark ring, `object-fit: cover`. Position badge top-left: .5rem inset,
  1.6rem tall, 4px radius, `surface` at 88% alpha, `ink` text, .8rem 550 tabular.
- Folio entry (no admitted cover): same 2/3 silhouette; 1px `soft-line` border,
  2px radius, gradient `surface` → `evidence-well`, padding `.85rem .9rem .9rem`;
  top block: series name .7rem uppercase, tracking .08em, muted; position numeral
  Literata 400 2.6rem copper, tabular; bottom block: 2rem × 2px copper rule,
  title Literata 550 1.05rem ink, author .8rem muted; the supplied emblem at 13%
  opacity, 78% of the width, offset to the bottom-right and clipped. This is a
  composed typographic folio, not an image frame or fake cover.
  At position 0 or without a recorded position, omit the numeral block entirely: series line,
  then rule, title and author, with room for the emblem. Keep No position in
  the accessible entry name, or Position 0 as appropriate. Neither zero nor
  unpositioned covers receive a chip. Display negative positions literally.
  Clamp folio titles to three lines (two on folios narrower than 150px, leaving
  room for the credit) and credits to two inside the fixed 2:3 silhouette.
  Clamped lines cannot shrink behind the credit; the full caption remains
  readable beneath. Separators use a no-break space before `·` and a normal
  space after, including folio credits.
  Insert a break opportunity after each slash wherever a series name renders;
  the small-caps folio series line wraps at those opportunities or spaces, never
  inside a word.
- Selected entry: 3px `accent` ring with 3px offset around the art, plus the
  existing selected-state semantics. Keyboard focus keeps the existing 3px outline
  with 4px offset so focus and selection stay distinguishable.

**Detail pane** (sticky, top 1rem, `surface`, 1px `soft-line`, 4px radius,
padding `1.25rem 1.25rem 1.5rem`, independently scrollable as today)

- Top: grid `9rem 1fr`, gap 1.1rem. Cover at 9rem (or the folio composition when
  no cover). Title Literata 550 1.9rem/1.15. Author 1rem. Bibliography muted
  .875rem on two lines: "Gaunt's Ghosts · Book 1" / "Novel · first published 1999
  · 15 editions".
- Status well: `evidence-well`, 4px radius, padding `.75rem .85rem`, .875rem.
  Line one strong in `accent` with dot: "Direct match · saved match". Lines two
  and three muted: "Calibre copy 152, last known · Partial check, Oct 26, 12:29
  AM" and "Not yet re-confirmed by a complete check." Use the existing truthful
  wording per state; only the composition is new.
- Synopsis: 1rem/1.7, max 65ch, six-line preview with the existing "Read the full
  synopsis" expansion.
- Actions: secondary button "Review metadata" (existing review entry point) and an
  accent link "Open in Library Finish ↗" (existing copy URL). Use a stable
  scrollbar gutter, reduced right padding and a .5rem gap so both actions fit
  on one line at 1440×900 and 1280×800 with space-taking scrollbars.
  When opened from a shelf, name that series; otherwise prefer the membership
  eligible for shelving with the most catalogue works, excluding setting umbrellas.
  List-thumbnail badge rules cannot affect pane art.
- Disclosures: 44px rows separated by `soft-line`, chevron, label left, muted
  summary right: "Editions · 15", "Library evidence · 1 copy · check date ·
  coverage", "Record details · snapshot 2026.10.24.2 · identifiers". Closed by
  default; contents are the existing sections unchanged.

## Composition: phone (< 960px or < 680px tall)

- Masthead wraps to brand plus theme picker; navigation on its own `surface` row.
- Search is a 44px field below the navigation, 1rem margins.
- Heading row: "Your library" at 1.65rem with the check chip ("Partial check ·
  Details") on the same line. Tools row: count, Order control (44px), Shelves /
  List. Copies stays inside the existing phone disclosure.
- Each shelf is a horizontal scroll-snap row: 136px entries, .9rem gap, 1rem side
  padding, all five preview works, partially visible next entry even at 320px
  with 200% text, keyboard reachable. Use a thin themed scrollbar. Header keeps the
  series name and "All N →".
- Selecting a book opens the existing focused detail with Back; the return path,
  scroll and focus preserve as today.
- Keep Previous page and Next page on one row. A Skip to selected book link
  follows desktop shelves; an earlier keyboard shortcut bypasses the shelf entries.

## Data and truth

- Ownership states keep their existing meanings and labels: direct, contained,
  pending, missing, unknown; current versus saved; candidates. The render's
  shelf line "Saved match" is a direct or contained match that the current partial
  check has not re-confirmed. A current match reads "Direct match" or "In a
  collection". Pending, unconfirmed and no-match keep their labels and muted
  colour. Never collapse unknown into missing or saved into current.
- Shelf summaries use the catalogue total: "45 of 87 shelved with a saved match".
  Count current direct/contained matches as "with a matched copy", historical
  matches as "with a saved match", and state both when mixed. Say "every one"
  only when complete shelved counts equal a catalogue total above one. A single
  title reads "1 shelved, with a saved match" as applicable. Incomplete counts
  state the catalogue total and what was read, without a match count.
- Series with matches only: unfiltered order is matched-work count descending,
  then normalized name (ignore leading punctuation and The/A/An). Search puts
  series whose names match the query first, then follows that order. No pinned
  series list. Page four shelves, with a complete title-ordered closing shelf
  last. Browsing shelves omit position-count and inspection-detail lines;
  position groups remain in All N.
- Recorded order follows the Recorded Order Rule: numbered positions ascending,
  then position 0, then unpositioned, labelled with real counts.
- A series is shelved only if the pinned catalogue has at least one non-null
  recorded position and its name is not a `work.setting` value (case and surrounding
  whitespace ignored). Warhammer, Warhammer 40,000, Warhammer Fantasy, Warhammer
  Age of Sigmar and Warhammer Horror are always umbrella groupings. Names containing
  `reading order` (case-insensitive) are reading lists, also excluded from shelves
  and preferred pane series; retain their catalogue memberships and complete
  All N views. Their works stay on real series shelves, or the closing shelf if
  no eligible series remains. An eligible series retains unpositioned works alongside numbered ones. A work in several
  eligible series appears on each; works whose only memberships are umbrellas,
  wholly unnumbered groups or none join the final **Standalone and collected**
  shelf, in title order with its complete catalogue count.
- Standalone and collected has an All N link using the matched total. It opens
  its complete paginated Title order, preserving query and Copies, with a status
  note such as "Showing all 573 standalone and collected titles". Back restores
  the shelf and scroll.
- Covers come only through the existing admitted pinned-digest reader and batch
  lookup. No proxy, no download, no production mount or redeploy.
- Order = Series uses `/api/library/shelves`: group complete small results and
  build a bounded background match index for results above 600 titles. While it
  builds, return Preparing shelves for the existing 2.5-second poll. Each gunicorn
  worker builds its own index; its first page view prepares. Keep a previous ready
  page visible, dimmed and inert with a status note during preparation. Cache by
  check token, filters and catalogue pin, retain ready indexes within the bounded
  cache and reuse a token LF re-advertises after verifying its metadata proof,
  and retain per-GET deadlines, body caps and snapshot checks. Never group an
  alphabetical subset or page the unfiltered series directory. [L025](../decisions.md#l025-bounded-pinned-library-shelves-and-the-reading-room-foundation)
  owns the exact bounds and cache design. Title and Author keep their listing.

## Not in scope

No reader, no "Open book", no progress bars, no series completion percentages,
no cover downloads, no production cover mount, no writer of any kind.

## Acceptance

Source checks: backend and frontend tests (TDD for the shelves read and the
grouping rules), TypeScript, Prettier, Ruff, mypy, mounted axe checks.

Rendered checks on real local data (catalogue snapshot `2026.10.24.2`, Library
Finish reachable, local cover cache configured): compare against the reference
PNG at 1440×900 and 1280×800, and the phone section at 390×844 and 320px with
200% text. Gaunt's Ghosts, Last Chancers and The Horus Heresy must appear as
shelves in that visual form. Verify: Shelves/List persistence, identical source
order, selection and return path, the Details disclosure, search from the
masthead, every ownership state's wording, all eleven themes, reduced motion,
keyboard traversal of the shelves and of the phone rows. Name viewport, theme and
data in the report. A design target is not proof it shipped; the screenshots are.

## Delivery

Branch `feature/reading-room-foundation` from `feature/series-explorer`. Small
conventional commits. Push both branches and open two pull requests: the series
explorer branch against `main`, and this branch stacked on it. Publishing was
authorised by the maintainer on 2026-10-26 for this work. No deployment, no release, no
production configuration change.
