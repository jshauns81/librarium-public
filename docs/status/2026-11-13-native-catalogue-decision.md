# Approved native catalogue storage and Lexicanum intake, 2026-11-13

This docs-only PR proposes [L090](../decisions.md#l090-native-reference-catalogue-storage-and-absorbed-harvest-controls)
for native reference/harvest state (NEW-003) and native controls (NEW-004).
The [intake design](../design/lexicanum-intake.md) describes S7 and in-app
Update from Lexicanum. No endpoint, model, permission boundary or UI is implemented
here; no service or installed beta is activated.

The proposal keeps Calibre as the library catalogue of record under L076, with
one-way observations into PostgreSQL and L060's existing writer boundary. Native
reference data uses PostgreSQL with immutable external artifact bytes, stable
source/work/edition identities and retained generation pins. BLC SQLite snapshots
remain transitional read inputs until a complete native reader/publication
adapter is verified. The proposal does not introduce immediate per-row fallback
or claim native tables already exist.

At cutover, parity and recovery evidence plus explicit approval must precede
switching readers and retiring replica/status tasks. L084 specifies HAProxy for
the catalogue relay. Deployment discovery and separate retirement approval remain
necessary; retained snapshots and prepared selections cannot be discarded blindly.
Native controls supersede L083 only at that approved cutover.

The intake plan reuses BLC's pinned validator, parser, evidence and inbox/audit
behavior, existing Librarium jobs and image admission, and PR #160's implemented
internal `/lexicanum` and `/image` contract. It separates XML hashes from semantic
claim hashes, page identity from edition-native IDs, evidence acceptance from
published updates, and immutable prepared choices from their current validity.
It requires authenticated operator/CSRF gates, bounded streams and parsing,
lease/idempotency fencing and explicit conflict outcomes. The three planned
implementation PRs target the S7 ledger; no row is closed by this design alone.

## Decided scope and open question

The owner excluded CWA metadata integration (S13) on 2026-11-13. The shared server
browser is the primary Lexicanum route; the Zen/Firefox extension port is parked
unless challenges justify revisiting it. These are decisions, not owner questions.
No live account state or billing action is inferred from source code. The maintainer approved L090 on 2026-11-13, retired ISBNdb and kept background work on demand.

## Review and verification

The review checked origin/main and the decision-heading diffs of PR #160 (L089)
and PR #161 (L088), then assigned L090. It checked BLC revision `a8f2744` and PR
#160 revision `7dddcaa`, corrected source-line citations and regression names,
and removed invented tables, unconditional selection-validity claims and UI
promises about the parked extension or unscheduled retries.

Documentation checks cover relative links/anchors, decision references, source
citations/test locators and whitespace. The tracked-content and staged privacy
gates use the protected external denylist; verification results are recorded in
the private review handoff. No application tests or rendered UI acceptance are
claimed for prose changes. Hosted PR acceptance remains separate.

The installed application has nothing new to test. Next work is maintainer review
of L090, followed by native schema/generation prerequisites and the three intake
implementation PRs. ISBNdb remains an owner decision; source-browser image release
and any activation retain their own approvals.
