# Cover search admission and history

Metadata results with no admissible artwork now finish as empty. Provider errors
and incomplete coverage retain their distinct states. Hardcover search parsing
also accepts JSON-encoded result objects and keeps missing artwork empty.
Hardcover artwork is admitted from its published `assets.hardcover.app` host;
the previous allowlist named a host Hardcover does not serve covers from, so
every Hardcover image was refused before fetch.

Catalogue suggestions no longer suppress the plain “No exact catalogue entry”
line. Exact title and alias matches retain their normal state. Suggestions keep
their confidence, explicit selection and anthology restrictions.

Web history deduplicates newest first by admitted image digest, with normalized
HTTPS source URLs as a fallback for older records without digests. Different
digests remain different choices, even at one URL. Saved selections can point
at the newest byte-equivalent display record without rewriting their evidence.
An explicit unsaved web choice also follows the same admitted image across
search refreshes; different image bytes never acquire that selection.

Image admission runs in parallel with a shared ceiling of three tasks per worker
process. Queued tasks recheck leases and deadlines; source completion still
publishes independently. Apple requests one 1600px artwork rendition instead of
trying an oversized original before a second rendition. Existing source-host,
redirect, byte, pixel, sandbox and artifact checks remain in force.

Reuse review covered the retained Library Finish provider/ranking ports, BL
Catalog matching and alias evidence, pinned catalogue choices, durable search
history and the existing sandboxed image admission path. This change extends
those owners and adds no dependency, provider or service.

Verification includes failing-first regressions, warning-strict Python tests,
the full frontend suite, production build, Python types, lint, formatting and
privacy checks. Synthetic Chromium checks cover weak suggestions, empty results
and exact matches in both themes at desktop, phone and 320px widths, including
explicit selection, preview return and Escape. Offline recorded-timing replay
checks scheduling only; it does not measure current provider latency or claim a
live speedup. No installed application, provider search or library write is part
of this change. Physical devices and screen-reader audio remain unverified.
