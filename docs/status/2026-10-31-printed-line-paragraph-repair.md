# Printed-line paragraph repair, 2026-10-31

[L066](../decisions.md#l066-repair-proven-printed-line-paragraphs-in-held-epubs) adds a
separate offered correction for proven PDF-style paragraph fragments, retaining
inline markup, words and link targets and reusing a verified body class. Sentence
boundary joins require repeated book-internal paragraph-start and line-length
evidence and are counted separately. Unsupported styles and ambiguous boundaries
stay held. Options/captures v3 retain historical reads; independent lexical and
tree preservation, output inspection and EPUBCheck remain required. Private
corpus and rendering evidence do not activate library writes or deployment.
