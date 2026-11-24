# WorkRow

A list entry for a work in Catalogue and series lists: a readable title with separate author and series context.

Source: `.work-row`, `.bibliography`, `.series-work-row`, `.edition-count` in `style.css`; `App.tsx`, `Catalogue.tsx`.

- Padding 0.85rem × 0.75rem, at least 82px tall, growing freely; `radius-flat`, `soft-line` bottom rule.
- Title in `list-title` (Literata 1.2rem / 1.4); author in `author` `ink`; series and kind in `meta` `muted`, the series separated by a `soft-line` hairline. Edition count right-aligned in tabular `meta`.
- Series rows add a 2rem `series-position` column (Literata, tabular). Write unknown positions as announced `No position`; never invent a sequence.
- Selected: `selection-fill` with the inset `line` edge. Hover: `pressed-fill`.

The consumer provides the work and the selection handler; selecting keeps the list's place.
