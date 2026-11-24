# Cover search: renditions, title fit and fair admission

Apple serves one artwork at several sizes under one path ending in
`/<width>x<height>bb.<ext>`. The picker merged history with each new search, so
the 3000px record and the later 1600px record of one artwork appeared as two
choices; their bytes differ, so the digest rule kept both.

Choices are now computed from the whole record set at once (`choose_images`),
never incrementally, so the result cannot depend on the order records are met.
Records with the same canonical bytes (legacy records without a digest: the
same normalised URL) are one image, always. The images on one Apple artwork
path (host, query and path apart from the size-and-format segment) merge into one
choice, keeping the newest record, only when every one of them lives entirely on
that path and no two different byte groups have the same size and the same format. A
byte match that also appears under another path never path-merges. The same size
and format with different bytes means the artwork was replaced, not that this is
another rendition, so both images stay. The same size in two formats (jpg and webp) is one artwork in two encodings and
does merge. Nothing chains. Different paths, queries or hosts never merge, a
distinct image is never dropped for deduplication, and the cap evicts the oldest
other choice. No other provider currently requests a size-variant path (Open
Library asks for `-L`, Google Books for `zoom=0`, and Goodreads strips its size
suffix), so none is normalised without evidence.

A saved selection is always present and selected, represented by its exact
record whenever that record is a member of its choice, including beside a newer
record with identical bytes (this replaces the earlier rule that a selection
followed the newest byte-equivalent record). A saved record outside the history
window is added to its choice by the same rules. The saved evidence is never
rewritten and a selection never moves to different bytes; at the 24-choice cap a
saved selection that already belongs to a shown choice costs no other choice.

Provider hits whose title names a clearly different work are not fetched or
offered. The check is the BL Catalog edition-key matcher, a spelling heuristic
that is lenient about decorated or truncated titles but is not a translator. A
zero gets one more chance from catalogue evidence, resolved once per search and
only when some source needs it: the canonical title and recorded aliases of the
one catalogue work this book exactly matches (the match the picker's catalogue
choices use, author included). A hit is kept only when its whole normalised title
equals one of those titles; there is no partial or fuzzy fit on that path, so a
short alias cannot admit a longer unrelated title and a homonymous work by someone
else contributes nothing. Kept hits that do not fit the searched title are
labelled "Weak title match" and are never eligible to be the recommended pick; the
best eligible candidate is recommended even when a weak one ranks first. A
collection word is ignored on both sides, so an omnibus of the same title stays
visible for the existing kind rule to refuse. ISBN lookups, pasted images and blank
query titles are not filtered.

Known limit: with no exact catalogue match (for example a book the catalogue does
not list), or an unavailable or empty snapshot, there is no alias evidence and a
result whose title scores zero is dropped, even if it is a genuine translated
edition. That is the trade for not offering unrelated books. A drop is never
silent: each source records how many metadata results it returned (`title_results`)
and how many it dropped for title mismatch (`title_mismatch`), counts only and no
titles, exposed in the search API. A source whose results were all dropped keeps its
upstream state (`empty`, or `partial` when coverage was incomplete), so an older
picker still decodes the response. The picker says "Results found, but none matched
this title." only when `title_results` is above zero and equals `title_mismatch`
(nothing was fetched, so the source has no choices from that run), for `empty` and
`partial` sources alike; a partial source also keeps its partial-coverage text.
In every other case, including one matching title whose image was inadmissible,
and rows stored without the counts, the ordinary text shows.

Each source now records its metadata time and image-admission time, and each
image records slot wait, fetch time, decode and ingest time, bytes and request
attempts (its fallback URLs), with the final outcome. The records hold no URLs or
titles, are capped at the six candidates a source may return, and live in the
existing `source_timings` JSON, so no migration is needed. Redirect hops happen
inside the isolated fetcher and are not visible to the web process; they stay
unmeasured.

The three admission slots were a plain semaphore shared by every source in the
worker process. With sources reaching the queue at different times, the source
that arrives last finishes last however few images it has. Slots are now granted
round-robin by source, least recently served first, with the same total of three
and every host, redirect, byte, pixel and sandbox limit unchanged. A
virtual-time replay and a worker-level test cover this; the replay is a model with
stated assumptions, not live latency.

Reuse review: BL Catalog title matching, the Library Finish ranking port, the
existing candidate history, selection and `source_timings` storage were reused.
The slot scheduler is new because neither BL Catalog nor Library Finish
schedules image admission, and the standard library semaphore has no fairness.
