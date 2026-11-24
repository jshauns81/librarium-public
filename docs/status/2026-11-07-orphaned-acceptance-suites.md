# Orphaned acceptance suites, 2026-11-07

[L082](../decisions.md#l082-one-rendered-end-to-end-suite-earns-a-nightly-slot)
removes two browser/fixture pairs: paragraph repair and author aliases. Per-PR
mounted and backend tests already prove every journey they assert. The unified
workspace suite stays, for a nightly tier after a repair PR. All three failed on
current main because of interface drift.

The [suite review](../research/orphaned-acceptance-suites-2026-11-07.md)
records the measured runs, the overlap and the proposed nightly workflow
change. No workflow or required check changed.
