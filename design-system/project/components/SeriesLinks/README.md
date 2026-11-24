# SeriesLinks

A wrapping row of underlined `accent` links from a work to each series it belongs to.

Source: `.series-links` in `frontend/src/style.css`; rendered by `LibraryBookPane.tsx` and Catalogue detail.

The consumer provides one link or button per membership, labelled with the series name exactly as recorded. Links are `filter-label` (0.85rem), at least 32px tall (40px below 620px, 44px on coarse pointers), and wrap anywhere so long series names never overflow. In a work's introduction the first list renders in `ink` at 1rem.
