# Design System artifact

The Librarium Design System artifact is the browsable reference set and design
workbench built from this repository. Retrieve its location from
[private agent context](../agent-environment.md#private-context-discovery).
The code stays the source of truth.

Authored pages never restate rules that `docs/ux-standards.md` owns (hierarchy,
status semantics, disclosure, composition, cover admission, the accessibility
floor, acceptance). They refer to its generated copy instead.

## Where each part comes from

| Artifact content | Source | How it updates |
|---|---|---|
| Colour tokens (eight launch themes, three brand roles) | `frontend/src/themes.ts` | generated |
| Themes page: all eleven themes, values and computed contrast | `frontend/src/themes.ts` | generated |
| UX standards page | `docs/ux-standards.md`, verbatim (relative links made absolute) | generated |
| Status labels page | label maps in `Library.tsx` and `JobProgress.tsx` | generated |
| `components/bundle.css` | `frontend/src/style.css` + `reading-room.css`, verbatim | generated |
| Brand sprite `brand/librarium-symbols.svg` | `frontend/src/assets/librarium-symbols.svg` | generated |
| Literata font | `@fontsource-variable/literata` (pinned 5.3.0) | copied from `node_modules` |
| Type, spacing, radius, shadow, size, layout, opacity tokens; colour usage notes | `design-system/tokens.base.json` | authored |
| Brand book, layout and workbench sections, component guidelines and previews, cover | `design-system/project/` | authored |
| Logos, favicons, inspiration, historical emblem | `images/` | uploaded assets, listed in `design-system/build/uploads.json` |

`scripts/design_system.py` writes `design-system/build/project/` (ignored by Git)
in the artifact's own layout, plus `report.json`: DESIGN.md colour drift against
`themes.ts`, CSS variables with no token, and any theme pair below its contrast
floor. `tests/test_design_system.py` covers the parser, contrast maths and output.

## Sync

Run after changes to themes, the stylesheets, brand art or `design-system/`:

```bash
uv run python scripts/design_system.py
```

In a worktree without `frontend/node_modules`, pass
`--fonts-dir <checkout>/frontend/node_modules/@fontsource-variable/literata/files`.
Resolve anything the report lists before publishing.

Then ask Claude to "sync the design system artifact". The procedure it follows
(from the type's own `SKILL.md`):

1. Read the live `project/design-system.json` and each file about to change.
   An edit made on the page that the repository lacks is reported and carried
   into `design-system/` first; never overwrite it silently.
2. Upload only assets whose `sha256` in `uploads.json` changed, and update their
   records in the index.
3. Publish only the changed `project/` files with `root` = `design-system/build`,
   then the index last with a `lastChange` naming the commit.

Previews are static renditions using the shipping class names. Frames shorter
than 680px get the app's compact layout (`max-height: 679px`), so desktop-only
specimens declare a taller `@dsCard` height. The artifact holds at most eight
themes; Dracula Alucard and both Solarized themes appear only on the Themes page.
