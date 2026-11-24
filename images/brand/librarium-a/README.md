# Supplied Librarium A family

the maintainer supplied `Librarium-A-Logo-Family.zip` on 2026-10-25 as the replacement
for the earlier emblem/trace. Archive SHA-256:
`6acd8cab620e81675d374f3b2bc787b631c9d782a641c2a66cf70e17554d860d`.
All 113 entries in the supplied checksum manifest were independently verified.

This is a selected source copy, not the entire archive: the six themeable SVG
originals, palette JSON and the three favicon source files used by the site.
Those files are byte-for-byte copies. `source-manifest.json` records their
checksums. The source archive, overview PNGs and offline preview remain outside
tracked code in the attachment/staged verification copy.

The package names Concept A / Ornate sigil and supplies an emblem, separate
outlined lettering, horizontal/stacked compositions and small/micro drawings.
The full emblem has 16 paths; the small icon has five; the micro has four;
the wordmark has eleven paths in nine letter groups. Use the small drawing for
the 48px masthead, the detailed drawing for 128px evidence decoration and the
micro drawing for favicons. Keep aspect ratios and transparent openings.

The source SVGs use an embedded stylesheet to map three classes to CSS color
variables. The application's derived `frontend/src/assets/librarium-symbols.svg`
contains only geometry and symbols: the embedded style is converted to
`fill="var(--librarium-ink, ...)"`, `--librarium-accent` or
`--librarium-wordmark` presentation attributes. Original path data, transforms
and fill rules remain identical. IDs are prefixed by variant to avoid collisions.
No new tracing, font substitution or image-generation step was performed.

The default brand uses the supplied ivory/brass values. Mocha, Macchiato, Nord
and Parchment map to their supplied brand colors. Other site palettes inherit
their text/heading colors unless `Theme.brand` specifies separate roles.
The warm Parchment page background is `#f4eddf`; the rest of the site treatment
adds accessible control/text roles around that supplied palette. the maintainer explicitly
approved adding Parchment while keeping the existing Librarium default.

The two runtime micro SVG favicon files and multi-resolution ICO are unchanged
copies of the supplied ready-colored files. Browser light/dark appearance
selects those independently from the site's saved theme. The earlier supplied
PNG, its WebP and rejected trace remain historical source; none is loaded by
the current application.

Current behavior and verification belong to
[private engineering record](../../../docs/agent-environment.md#private-context-discovery).
