# Comparison

Readable source/value pairs from each source, side by side in Evidence Ink, so disagreements can be read rather than decoded.

Source: `.comparison`, `.source-claim`, `.evidence-fields`, `.evidence-values` in `style.css`; `EvidenceValue.tsx`, `LibraryEvidence.tsx`.

`evidence-well` ground, gap 1.2rem, padding `space-stack`. One column on phones and in the desktop split, two from 620px and again from 1280px. Each claim names its source in bold, then a definition list (`label` size, terms `muted`). Arrays are bulleted lists. Preserve zero, false, missing values and empty containers distinctly: write `0`, `false`, `Not recorded`, `None`. Never mark one side "correct" by colour.

The consumer provides one claim per source, already structured.
