# Cover census performance

Round one makes decoder capacity configurable with `LIBRARIUM_CENSUS_CONCURRENCY`
(setting `COVER_CENSUS_OBSERVATION_WORKERS`, range 1 to 8). Its default is
`max(1, min(4, (os.cpu_count() or 1) // 2))`, or two on four CPUs.
The default batch remains 64 with eight buffered inputs per chunk. Full metadata
database/WAL/journal hashes run once before and once after each chunk on the main
thread, replacing the per-book parallel hashes. No results from a changed chunk
are published. Every image still gets a fresh sandboxed child with unchanged
resource and image limits. Ordered publication retains library/book UUID,
numeric ID/path, cancellation and lease checks, and rechecks both cover stat and
available content digest immediately before publishing. A cover replaced during
decode stays before the cursor for retry, including during validation. Unchanged
validation covers also receive a content check; completion keeps its full-token fence.

One executor is reused across ticks and closed on worker exit. Deadline or
cancellation cancels queued work and interrupts decoder transport, whose existing
cleanup kills and reaps the child. The main thread waits at most 250 ms for
in-flight observations and admits no new work while an old thread is stopping.
An observation cutoff reserves up to one second for the closing fence and
publication. Completed prefixes can advance after all checks; slow suffixes
remain before the cursor in both the initial and validation passes.
Synchronous filesystem/database work still adds latency outside this decoder-wait
bound. No stat-only metadata cache, pooled decoder, detector change or dependency
is added. See [the configuration and scheduling contract](../development.md).

Reuse review retained the Library Finish detector port and provenance, existing
direct-library no-follow readers, read-model hashes, and census publication/skip
protocol. Bounded `ThreadPoolExecutor` scheduling already exists in the read-model
file observer; this change applies that standard-library pattern to census work.

Tests first reproduced serialized decoding and publication after a metadata edit
during decode. The latter regression hides stat changes and requires the complete
metadata digest to catch the changed bytes. Existing cancellation, stale inventory,
UUID reuse/duplicates, cover mutation, skip/CAS, sandbox and resumable validation
checks remain required. The native-library image helper now also checks a census
against its preserved WAL fixture before and after replacement. The reproducible
benchmark additionally checks every saved UUID, image digest and dimensions and
all input hashes; its read-only-mount assertion supports actual-image acceptance.
