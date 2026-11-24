# Automatic catalogue snapshot and cover sync, 2026-11-10

The approved Phase 1 adds a disabled-by-default idle-worker replica task. It
backfills dashboard artwork first, then the remaining active catalogue. New BLC
snapshots remain staged until every referenced original and upscaled cover has
passed the existing digest, media, size and raster-dimension checks. Atomic
publication keeps the served predecessor and a third fallback snapshot.

Progress and failure evidence survive worker interruption, and competing workers
share an exclusive file lock. Digest mismatch from BLC's current-work endpoints
holds cutover. An obsolete active cover cannot permanently prevent a newer
complete snapshot. The web path makes no upstream requests. Existing cached
comparisons refresh artwork as local bytes arrive; the dashboard's existing
attention reasons report snapshot lag, publication age and incomplete covers.

Reuse (L058): BLC snapshot/cover API and publisher, LF's cover cache/fetch pattern,
retained plans and changeover list, and Librarium's status transport, snapshot
validation and content-addressed raster admission. Only worker coordination,
resume state and the publication barrier are new. No dependency or BLC change.

The optional compose overlay grants catalogue writes only to the sync worker,
via a hardened, digest-pinned fixed-upstream TCP relay. The worker stays on the
internal default network; only the relay joins catalogue egress. Web and
authoritative inputs stay read-only.
See [setup and limits](../development.md#automatic-catalogue-replica) and
[L084](../decisions.md#l084-idle-worker-catalogue-snapshots-include-verified-local-cover-bytes).
Review fixes add resumable deadline checks before cover probes, multi-slice
active backfill before staging, partial-error progress, version-bound publication
ages and empty-environment cover defaults. Relay admission verifies its mounted
read-only configuration and rejects extra upstreams or weakened isolation.
Regression coverage includes interrupted/partial copies, corrupt and oversized
downloads, redirects, digest/dimension mismatch, cutover and retention, throttling,
worker priority, path confinement, cache refresh, health evidence and web network
exclusion. A JPEG frame may follow large metadata payloads.
the existing parser now skips those payloads with bounded marker traversal while
keeping body and pixel limits. The full suite also exposed an imported-alias leak
in a parsing-guard test; that test now patches and restores both aliases.
Actual final verification and read-only end-to-end results are recorded
in the PR; private observations and connection details stay outside source control.
