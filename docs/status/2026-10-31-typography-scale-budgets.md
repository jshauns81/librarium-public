# Typography scale budgets, 2026-10-31

L057 now admits larger synthetic novels and omnibuses using measured ceilings:
512 sheets/documents, 1,280 members, 15 MiB logical bytes, 4 MiB document bytes,
32,768 elements, 128 KiB per sheet, 192 KiB combined CSS, 6,000 declarations,
1,024 edits/inline styles, 512 embedded styles and 256 KiB plan JSON. All child
limits remain unchanged. Exhaustion affects typography alone. The
[dated scale evidence](../typography-budgets.tdd.md) records nine tiers, 275 child
measurements, medians and maxima. Worst CPU is 4.937/10 seconds; every measured
resource stays below half its child ceiling.

Import traversal, empty-rule parsing, ASCII byte mapping, repeated CSS and
source-text hashing have operation-count regressions. Shared text normalization
preserves existing digests and policies. Parent validation also enforces the new
source-sheet and combined-census byte bounds. The cancellation test uses a
PID-ready handshake rather than a startup-time assumption.

Full verification: 2,781 warning-strict tests plus 11 subtests, zero skips;
90.39% application/capture-tool line coverage (10,507/11,624 lines).
The complete collection ran in disjoint groups with isolated databases/network
namespaces; the non-root packaged-producer probe ran under its required identity.
Native Calibre, kill/recovery and HTTP coordinated-restore gates pass. Mypy,
Ruff check/format, Django/schema, dependency audit, workspace/archive integrity,
docs and protected privacy/secrets checks pass. Frontend source is unchanged;
its production build supplies the full-suite static assets. The typography HTTP
proof passes on the final backend source with real EPUBCheck and preservation.

Changes are committed locally without a push or installed-service activation.
No owner testing is needed for this implementation handoff. Parent review and any
separately authorized deployment-hardware, larger-book or reader pilot remain
follow-ups; no real library was surveyed.
