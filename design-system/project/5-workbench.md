# Design workbench

This page is where design work starts. Comment on any card or section to raise a question; Claude reads comments sent to it and replies on the page.

## How to work a design through

1. **Frame it.** Name the journey from `PRODUCT.md` it serves (explore a collection, understand a work, prepare a book, follow ongoing work, deliver a result, continue on mobile) and the hierarchy level it touches.
2. **Build from the system.** Compose with the tokens and the components here. A new treatment that needs a value no token has is a proposal: add it in `design-system/tokens.base.json` (or `frontend/src/themes.ts` for colour) on a branch.
3. **Check truth before beauty.** Status claims follow **UX standards**; use the strings in **Status labels** exactly.
4. **Check every theme.** Contrast floors are computed in **Themes**; a new pair goes into the build's `CONTRAST_PAIRS` so it stays checked.
5. **Accept in the app, not here.** These previews are static renditions; acceptance follows the paths in **UX standards**.

## Open threads

- **Admitted cover art.** Admission is governed by **UX standards** and the work-folio contract in `DESIGN.md`. Shelves and the pane already reserve a 2:3 art slot that falls back to the title-led folio.
- **Inspiration still to interpret.** The Collection Atlas, Book Atelier and Reading Room concepts carry atmosphere: confident typography, artwork and room to read. Their reader, statistics and claims are not scope.
- **Offline and stale states.** Browser-offline and content staleness are distinct product states still to verify in the running app.
- **Reference-only themes.** Dracula Alucard and Solarized Light and Dark ship in the app but sit outside the eight-theme token view; check them from the **Themes** tables.

## Keeping this page current

The page is rebuilt from the repository by `scripts/design_system.py`; see `docs/design/design-system-artifact.md`. Colours, the stylesheet, the font and the Themes, UX standards and Status labels pages come from their canonical sources on every sync. Prose and previews live in `design-system/project/` and change through Git, so edits made only on this page are carried back by the next sync's merge.
