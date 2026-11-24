# Read-only cover census backend

PR1 adds an explicit, authenticated whole-library cover census to the existing
worker. It reads the library read model in bounded batches, persists inventory,
cursor, lease and counts, and resumes after interruption. Unresolved reads and
unknown book identities produce partial results. Requests never write to Calibre
or activate recurring scanning.

Cover facts port the Calibre JPEG-comment and dimension-specific flatness rules
from Library Finish `services/bookindex/app/cover_facts.py` and blank detection
from `services/coverart/app/server.py`, at commit
`72bdf39eb986f7e4dc52eb9e0fb528afe767e01d`. The corresponding
`tests/cover_facts_test.py` cases are adapted to byte inputs and isolated decoding.
The maintained Pillow decoder runs in a fresh, bounded child using the existing
Landlock/seccomp and pipe-exchange primitives. SVG, animated, excessive and
unreadable inputs remain unresolved.

PostgreSQL owns UUID-paired review entries and authenticated, idempotent
compare-and-set skip/unskip actions. Cover changes retain skips with a visible
changed-since-skipped indication. Local preview reads recheck the library/book UUID pair, cover observation
and exact image bytes, independently of unrelated inventory edits. Missing, generated, blank, width below 1000 and height below
1200 are independent reasons. Equality passes its respective floor. Read-only
observations never mark a book Done; that state is reserved for verified delivery.

Backend tests cover generated and real art, strict dimensions, hostile images,
whole-library pagination, resume, leases, cancellation, changing inventories,
identity replacement, concurrent devices, request validation, local preview,
populated upgrades and runtime grants. Required CI supplies remote acceptance.
UI integration waits for design selection. No beta deployment or library write
belongs to this change; there is no owner product test yet.


The review fix round keeps the census cursor through inventory edits and retries
interrupted metadata snapshots. A final file-observation pass reconciles changed,
added and removed books; unchanged covers reuse their saved detector facts.
Completion requires an observation for every present identity. Unknown identities
remain partial, with at most 100 stored diagnostic rows and an exact separate count.
Null and duplicate UUIDs retire stale queue entries.

Cover fingerprints exclude titles and paths, so metadata renames preserve skip
revisions. Restoring the same book UUID in the same library intentionally inherits
its skip; reusing a numeric ID with a new UUID does not. Skip and preview requests
verify the selected book and cover at request time. Migration 0013 also installs
always-enabled action immutability and truncate guards, covered with the runtime
insert-only/mutable grant matrix.

The fix round adds regression cases for unrelated edits, ongoing edits and snapshot
interruption, cover-only changes behind the cursor, renamed/restored books,
identity replacement and invalidation, and bounded identity diagnostics. The 100
focused census/guard tests pass on PostgreSQL. Required remote checks remain the
acceptance gate; no merge or installed application change belongs to this round.

The second fix round replaces completion-time forced imports with live cover-stat
checks. Unchanged completion preserves the serving read model; changed covers are
reobserved in bounded batches. Census refreshes share the worker's configured
interval, including failed imports. Unavailable models and inventory conflicts
retain distinct error labels; stale/unavailable models retry the same census, and deadline-bounded validation persists its own cursor.

Skip verification completes its identity snapshot, byte checks and decoder before
taking database locks. The transaction rechecks metadata/cover stats and the entry
revision. Busy snapshot slots receive a bounded wait before locks are acquired.
Entry inventory tokens are removed from unmerged migration 0013 and the entry API;
queue and census inventory tokens remain. Regression tests cover unchanged
completion availability, unresolved decoding and concurrent publish, preflight
races, snapshot contention, refresh retry intervals and error labels.
