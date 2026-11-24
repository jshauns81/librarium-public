# Disclosures

Native `<details>` groups that open evidence and technical detail from the book, each summary saying what is inside.

Source: `.reading-disclosures` in `reading-room.css`; `LibraryBookPane.tsx`. Elsewhere the base `summary` style (`muted`, underlined, `meta`).

- Each summary is at least 44px, `ink` at 0.95rem, with a CSS chevron in `muted` that turns when open, and a right-aligned `small` hint (count, or what the group holds).
- `soft-line` rules separate groups.
- What goes behind a disclosure, and what must stay visible, is decided by **UX standards** (Disclosure and composition).
- Missing values are written out: `Format not recorded`, `Date not recorded`, `ISBN not recorded`, `None recorded`.

The consumer provides the summary label, the hint and the contents.
