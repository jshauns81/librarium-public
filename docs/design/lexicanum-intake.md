# Lexicanum intake and Update from Lexicanum

Status: approved design (maintainer, 2026-11-13), accompanying [L090](../decisions.md#l090-native-reference-catalogue-storage-and-absorbed-harvest-controls).
This is a design, not implemented endpoints, migrations or activation approval.
Scope: S7 (BLC-046 through BLC-051, BLC-203, RT-055, NEW-006), plus the owner's
in-app Update action. Ledger closure requires implementation and verification.

## Scope and dependencies

The owner has decided that the shared server browser is the primary Lexicanum
route. The Zen/Firefox extension port stays parked unless challenges justify
revisiting it. CWA metadata integration (S13) is excluded. ISBNdb
(NEW-001) is retired; keyless Lexicanum intake does not depend on it.

Reuse BLC's export validator, publication parser, evidence/resolver rules and
inbox/archive/audit behavior under L058. Librarium already retains an offline
BLC engine in `backend/bl_catalog/`; extend its verified rules rather than
introducing another parser or matching by title alone. Library Finish's cover
provider behavior is already reused by the picker and PR #160. It provides no
replacement for BLC's catalogue intake. New code is limited to native storage
adaptation, durable jobs, client credential ownership and the in-app workflow;
reuse the existing job, image-child and HTTP boundaries. No new external service
or XML parser framework is proposed.

PR #160 supplies retrieval for cover choices, including current export XML. It
adds no intake, Update action or native catalogue storage. PR #161 supplies the
trusted-operator ingress design (L088); it is default-off and separately reviewed.
Native harvest foundations (S0/S3), stable catalogue identity/publication and the
native reader adapter in L090 must land before an update can become visible in
catalogue search and matching. No code in this PR changes today's snapshot reads.

## Verified source baseline

BLC citations below are relative to its repository at `a8f274487f09399a6fe90f4210bb50fc0c3a0701`.
PR #160 was checked on `origin/feat/source-browser` at `7dddcaa`; its file paths
below are relative to Librarium. Recheck that dependency when implementation
starts. These source observations are not production availability guarantees.

Today `backend/librarium/catalogue.py` reads immutable SQLite publications pinned
by version and SHA-256. `backend/bl_catalog/native.py` retains bounded offline
SQLite staging; it is not a PostgreSQL harvester. `LibraryReadModel` and its book
relations describe Calibre's observed library, not reference Works/Edition models.
`PreparedCover`, `CoverSearch` and `CatalogueStatus` already exist in PostgreSQL;
the native Work, Edition, SourceRecord and IntakeJob models below do not.

BLC's actual table families are listed in L090. `source_record.content_hash` hashes
normalised claims, not XML bytes (`src/bl_catalog/db/store.py:66-106` and
`src/bl_catalog/record.py:206`). `parsed_json` holds `Record.raw`, not a complete
export. Its evidence content remains unchanged on repeats, but `last_seen_at` is
mutable (`src/bl_catalog/db/store.py:54-61`). Do not label every field append-only.

## Proposed storage and ownership

Use PostgreSQL for catalogue evidence, jobs, publication metadata and caches;
use immutable owned artifact storage for export and cover bytes. Preserve L076's
Calibre ownership, one-way library observation and independent broker exception.
No reference update writes a Calibre book, cover or `metadata.db`.

The implementation must define migration names and L062 runtime grants for these
logical records; this table is a contract, not executable Django model code:

| Record | Required data and invariant | Writer |
|---|---|---|
| IntakeJob | UUID; authenticated actor; actor-scoped UUID idempotency key and request digest; validated requested URL; optional library/book UUID, inventory and catalogue pin; state; safe result; attempts, retry deadline, lease token/expiry and timestamps | Web creates a bounded request; worker claims and finishes with lease fencing |
| PageObservation | Supported wiki, requested and canonical article identity, page/revision ID when supplied, fetch time, export SHA-256, parser policy, reach method and job/actor reference; immutable accepted payload reference | Worker |
| SourceRecord and Claim | Preserve BLC semantic identities, claim hash and resolver semantics, with observation links and separately mutable last-seen data | Worker |
| CatalogueGeneration | Complete resolved generation, stable anchors/aliases, baseline pin, policy and publication state; atomic visibility with historical pin resolution | Worker |
| Cover evidence | Immutable original blob digest and raster facts, observation/source relationship and optional derivative; mutable URL-to-latest projection is distinct from immutable provenance | Worker |
| ClientCredential | Client ID, scope, token hash, created/revoked times and safe last-used projection; raw token returned only at issuance | Authenticated operator issues/revokes; intake checks scope |

Store the actual authenticated principal, never a default `actor="operator"` or
an actor supplied by JSON. Ingress may map clients to `operator` under L088; the
application must still require the established trusted principal. Web reads safe
status projections and enqueues commands; only workers publish reference data.
The browser receives no database credentials. Enforce any separate SQL-role claim
with grants/tests; current shared runtime access does not establish isolation.

Publication state must distinguish validated/stored evidence from served results.
A shadow job cannot report that catalogue search has updated. Recovery after a
worker crash must reclaim a lease without duplicating accepted evidence or
publishing an older job over a newer observation.

## Export validation to carry from BLC

All locations in this table refer to the pinned BLC revision above. Port `_scalar`
as well as `_validate_export`; scalar cardinality and child checks prevent shadow
values from reaching a more permissive importer.

| Validation | Actual source and behavior |
|---|---|
| Safe XML | `src/bl_catalog/api/intake.py:46-53`: defusedxml with `forbid_dtd`, `forbid_entities`, `forbid_external`; failure `invalid_xml` (422), including UTF-16 attacks |
| Export root | `src/bl_catalog/api/intake.py:27-28,55-58`: exact MediaWiki namespace (scheme `http`, authority `www.mediawiki.org`, path `/xml/export-<version>/`); failure `invalid_export` (422) |
| One page/site | `src/bl_catalog/api/intake.py:59-65`: exactly one namespaced siteinfo and page, plus exactly one local-name page anywhere in the tree |
| Exact wiki origin | `src/bl_catalog/api/intake.py:66-79`: nonempty scalar base without Unicode category Cc controls; HTTP/HTTPS and both netloc and hostname equal the selected wiki host (no credentials or explicit port); mismatch `wiki_mismatch` (422) |
| Scalars and namespaces | `src/bl_catalog/api/intake.py:37-43,81-85,98-100`: one scalar with no nested children; direct page/revision fields in the export namespace |
| Main article/title | `src/bl_catalog/api/intake.py:86-94`: title nonempty and not whitespace-only, at most 512 Python characters (not bytes or stripped length), no Cc controls; stripped ns equals `0` |
| One revision/wikitext | `src/bl_catalog/api/intake.py:95-106`: one revision; absent model or `wikitext`; nonblank scalar text; parser must yield records, otherwise `no_importable_pages` (422) |
| Supported wikis | `src/bl_catalog/sources/lexicanum.py:50-52` and `src/bl_catalog/api/intake.py:143-144`: `wh40k`, `whfb`, `ageofsigmar`, `catalogue`; otherwise `invalid_wiki` (422) |
| Authenticate first | `src/bl_catalog/api/intake.py:131-147`: unset token disables intake (403), constant-time Bearer check (401), then wiki and raw XML media type validation (415) |
| Bound reads | `src/bl_catalog/api/intake.py:27,148-165`: 5 MiB (5,242,880 bytes); validate declared length without huge integer conversion; enforce actual stream size even with absent/false length; overflow 413 |
| Atomic filesystem visibility | `src/bl_catalog/api/intake.py:110-128`: hidden temporary file, flush/fsync then `os.replace`, server-generated UUID filename and cleanup; this is BLC's inbox protocol, not PostgreSQL queueing |

Port book/short-story, edition, series and redirect behavior, not only lines
723-780. BLC `src/bl_catalog/sources/lexicanum.py:723-780` rejects comics and
unqualified catalogue hobby products, dispatches series and supports typed books
with body ISBNs; `:782-894` builds the actual records. `_editions` starts at
`:422`; series parsing and its helpers must be carried with `parse_page`.
An export may yield multiple records, including native IDs suffixed by ISBN or
`#audiobook` (`:888-894`). Preserve those IDs and work/edition associations;
`{wiki}:{title}` alone is a page identity, not every evidence record's ID.

Proposed additional intake defenses: run untrusted XML/wikitext parsing in a fresh
resource-limited child using Librarium's existing isolation boundary. Enforce
memory, CPU/time, node/depth, record and relation budgets before database
publication; the implementation must fix and test exact budgets. Parse once and
pass the validated representation to extraction; never hand untrusted XML to an
unguarded second parser. Bind export wiki/title to the browser's validated
canonical article; record requested-to-canonical redirects explicitly. Validate
revision IDs when present; absent revision IDs remain unknown and use content
identity, without fabricated values. Neither a browser's `ok` nor its cover parser
establishes full intake validity.

## Shared source-browser contract (PR #160)

Reuse `backend/librarium/cover_browser_sources.py:28-94` (`browser_call`) and
`backend/librarium/cover_source_protocol.py`, not a new public browser proxy.

| Lane | Implemented contract |
|---|---|
| Control | Internal HTTP `source-browser:8126`, listener bound to the `source-browser-control-listener` alias on the internal control network; `compose.source-browser.yaml` publishes no host port |
| Request | POST `/lexicanum` with exactly `{"url": article_url}`; JSON content type, nonempty Content-Length at most 4096 bytes, no Transfer-Encoding |
| Authentication | `X-Source-Time` decimal epoch seconds and `X-Source-Signature` lower-case hex HMAC-SHA256 over `POST\n<path>\n<stamp>\n<body>` with actual LF separators; accepted within 30 seconds, constant-time comparison |
| Success | JSON `{"state":"ok","html":...,"url":canonical_url,"xml":...,"cover_url":url_or_null}`; HTML/XML each at most 2 MiB UTF-8; worker must bound the JSON envelope too |
| Cover | POST `/image` with exactly `{"url": cover_url}`, same signing; success is raw `application/octet-stream`, at most 16 MiB; failure is state JSON, never image bytes |
| Failures | JSON states `challenged`, `timed_out`, `rate_limited`, `empty`, `failed`, `unavailable`; saturated control may answer HTTP 503 with `busy`; helper maps other non-200 responses to unavailable |
| Deadlines | Existing helper: 85 seconds for page/export, 20 for image; defaults to 6 MiB envelope, while current Lexicanum caller passes `6 * MAX_PAGE`; browser parent has an 80-second bound and 24 MiB serialized child-output ceiling |

HMAC authenticates the control lane, not the web operator, and its timestamp is
not a one-use replay guard. Durable job idempotency and quotas remain required.
Keep the request key outside source/history and never forward it to providers.
The browser's loopback CONNECT proxy is `127.0.0.1:8127`, not an intake endpoint.

Article inputs must pass `browser_url(url, "lexicanum")`: encoded ASCII HTTPS,
at most 4096 characters, one of the four exact wiki hosts, no credentials,
fragment, query or nonstandard port; current `/wiki/<title>` paths only, no
traversal, slashes inside decoded title, residual percent escapes, controls or
excluded namespaces. Reject history/edit/diff URLs before queueing. These
restrictions are stronger than the XML base check and do not accept arbitrary URLs.
For example, combine the supported `wh40k.lexicanum.com` host with a path such
as `/wiki/Example_(Novel)`; this illustrative title is not a verified article.

`services/source-browser/browser.cjs:49-111` uses headed Chrome under Xvfb with
page scripts disabled, GET-only interception and same-wiki navigation. It paces
Lexicanum requests by at least one second, uses the canonical article URL with
current-URL fallback and fetches
`/mediawiki/index.php?title=Special:Export/<title>&curonly=1`. The thumbnail helper
recognises the original same-wiki image layout and skips `Book2.jpg`; it can
return null for unrecognised artwork. It does not guarantee a cover for every
series page. Challenges are reported, not solved. Public-address DNS pinning,
redirect checks, native Chrome sandboxes and network/mount separation remain
requirements of that role. Do not import desktop cookies or profiles.

After full export validation, fetch an eligible original with `/image`. Validate
same-wiki provenance again and send bytes through the existing isolated image
child for size, dimensions, format, digest and safe metadata-free picker output.
Keep original evidence separate from prepared derivatives. A missing/challenged
cover does not erase good metadata or old art: report metadata publication and
cover availability independently. Archived covers remain labelled fallback
choices; archive data cannot masquerade as a current article update.

PR #160's six-hour PostgreSQL `SourceBrowserPage` cache is for Goodreads HTML.
Update must make a fresh current-export request and cannot use that cache as a
revision observation. Proposed generic HTTP-cache tables are future native
harvest work, not tables already provided by BLC or this PR.

## Proposed web API and job flow

These routes are proposals, separate from the implemented internal browser API:

- `POST /api/catalogue/lexicanum/update` accepts either `{"url": article_url}` or
  an exact catalogue work identity with its generation pin. A book-context request
  also carries library/book UUID and current inventory; the server resolves its
  already-recorded, unambiguous Lexicanum page rather than guessing by title.
- Require the existing authenticated operator and Django CSRF before browser
  requests can enqueue work; authenticate before costly parsing/reads. Bound JSON
  to 8 KiB, reject unknown/contradictory fields, require an actor-scoped UUID
  `Idempotency-Key`, and reuse quotas with tested per-actor/global queue ceilings.
  Same key plus same request replays its job; changed payload returns 409.
- Return 202 with job UUID and status URL, then poll
  `GET /api/catalogue/lexicanum/update/<uuid>`. Require operator access, constrain
  visibility to the authorised actor and return no-store safe projections. Never
  expose raw XML/HTML, credentials, paths or exception bodies through this API.
- Worker claims a bounded job with a lease under row lock, releases the database
  transaction before network/parsing work, and fences every later publication by
  lease and current page observation. States are `queued`, `fetching`, `validating`,
  `importing`, `stored` (shadow evidence only), `updated`, `challenged`,
  `not_supported`, `failed`, with explicit outcome/retry/cover detail.
- Commit accepted evidence, page observation, resolved generation and final
  publication outcome atomically, with crash-safe artifact custody. Store blobs
  by digest before referencing them, refuse changed bytes and use existing
  recovery conventions; BLC's file rename alone does not make a DB commit atomic.
  Show `updated` only once that generation is available to reads. Reclaiming
  interrupted work must resume the same request without a second publication.

An optional external client-upload route retains the strict single-page validator
and 5 MiB actual-stream cap, separate from the browser's 2 MiB export limit.
Use scoped, revocable Librarium-issued credentials (NEW-006), authenticate before
body consumption, accept only raw XML media types and rate-limit clients. Cookie
requests retain CSRF; machine Bearer auth must never silently accept cookies or
reuse scan/control credentials. BLC's `INTAKE_KEY` fallback is a compatibility
behavior to account for in BLC-050, not authority to adopt one global legacy token
or ship the parked extension. Credential issue/rotation/revocation requires real
API tests before NEW-006 is closed.

## Revision, conflict and selection rules

Serialize acceptance per canonical wiki/page and use a complete observation set
for that page's records, so removed editions do not remain current through stale
`last_seen_at` values. Preserve earlier evidence, source disagreement, anchors and
aliases. Reuse BLC's resolver and evidence semantics, including A to B to A
observations; do not overwrite records merely because their XML changed.

Track export SHA-256 separately from semantic claim hashes. For the browser lane,
hash the received XML string encoded as UTF-8; PR #160 returns decoded text, not
a byte-for-byte HTTP response capture. For client uploads, hash the exact accepted
bytes and record that distinction in provenance. Export wrappers
may change without bibliographic changes. An unchanged export can still reference
changed artwork, so XML equality cannot skip the cover observation. Deduplicate
unchanged evidence/claims while recording a fresh observation and cover outcome.
Older or out-of-order revision fetches cannot replace a newer accepted revision;
when ordering cannot be established, hold a conflict and refetch rather than
choose by job finish time. A same-revision/different-content discrepancy needs
review. A later current revision that reverts claims is valid new provenance.

Resolve exact source IDs/aliases and supported identifier/author evidence; do not
merge on title or ISBN alone. Ambiguous identity leaves a visible conflict, with
no automatic library match or native field override. Book-context refresh rechecks
its original identity and pin before presenting a result for that book; changed
context requires reselection.

Existing PreparedCover records and blobs remain immutable (L086). An update may
add a candidate, but cannot silently replace a selected artifact. Revalidation
can mark a saved selection stale when its catalogue pin, identity or source
binding no longer qualifies. The draft's claim that selections always remain
valid would bypass the existing safety contract. Retain historical generations
and artifacts as long as saved evidence requires them. Neither selection nor
intake grants delivery approval or writes a library cover.

## Interface placement and copy

Use the existing Catalogue/Reference route (`/catalogue`) for a persistently
labelled article-link field with action `Update from Lexicanum`. Help text:
`Paste a book or series article link from a supported Lexicanum wiki.` Keep the
job available after navigation/reload; preserve text, focus and return context.
Do not describe database roles or upstream projects in product copy.

Offer one-click Update on a work/book with a recorded unambiguous Lexicanum page
and exact identity context, including the existing CoverPicker comparison where
appropriate. A potential match must first be selected and confirmed; guessing an
article is not a one-click update. A series without artwork remains importable.

| Outcome | Proposed copy and recovery |
|---|---|
| Queued/fetching | `Queued` / `Fetching article from Lexicanum` |
| Validating/importing | `Checking article data` / `Updating catalogue` |
| Stored in shadow mode | `Article stored; catalogue publication pending` (do not offer production Update until serving is ready) |
| Published | `Updated from Lexicanum`; counts and cover result come from the committed job |
| Unchanged | `Catalogue up to date`; show cover result separately |
| Challenge | `Cloudflare challenged the Lexicanum request. Try again later.` |
| Busy/rate limited | `Lexicanum update is waiting`; show a retry time only if a bounded retry is scheduled |
| Invalid address | `Use a current book or series article link from a supported Lexicanum wiki.` |
| Unsupported content | `This article has no supported publication data.`; use a narrower reason only when the parser actually records one |
| Failed/conflict | Explain the recorded failure safely and offer `Retry` or `Review match`; never promise an unscheduled retry |

BLC currently returns generic `no_importable_pages`, not a reliable classification
of lore versus hobby versus absent infobox. New structured parser reasons need
tests before those explanations appear. Never suggest uploading through an
extension while its port is parked. UI copy never names BL Catalog, BLC or
Library Finish. Reading-room layout, wrapping at 320px/doubled text, visible
labels, keyboard operation, focus preservation and live-region status follow
[UX standards](../ux-standards.md); design prose does not establish rendered acceptance.

## Tests and implementation sequence

Carry all 25 test functions in BLC `tests/test_intake.py` at the pinned revision,
including parametrized variants. Important exact locators:

- Authentication/disabled: `test_intake_is_disabled_without_its_own_token`,
  `test_missing_or_wrong_token_never_writes`,
  `test_auth_is_checked_before_wiki_media_type_and_payload`.
- Streaming/XML: `test_stream_limit_applies_without_or_with_a_false_length`,
  `test_exact_byte_limit_is_allowed`,
  `test_dtd_and_entities_are_rejected_including_utf16`,
  `test_structurally_invalid_exports_never_create_the_inbox`.
- Origin/content: `test_export_site_must_match_exact_wiki_host`,
  `test_catalogue_export_requires_its_exact_host`,
  `test_catalogue_rulebook_is_rejected_without_creating_an_inbox`.
- Custody/concurrency: `test_title_never_controls_the_queued_filename`,
  `test_disk_failure_leaves_no_partial_or_final_file`,
  `test_hidden_temporary_file_is_fsynced_before_atomic_visibility`,
  `test_concurrent_uploads_have_distinct_complete_files`.
- End to end: `test_uploaded_real_book_imports_deduplicates_resolves_and_is_published`,
  `test_catalogue_export_enriches_the_same_work_from_an_existing_wiki`.

Also carry `tests/test_lexicanum.py` parser/inbox/archive/quarantine cases.
BLC's offline importer accepts multipage XML and `.txt`/`.wiki` drops, with the
last revision per page (`src/bl_catalog/sources/lexicanum.py:904-931`), collision-safe
archive/quarantine (`:955-985`) and per-file/page reports/retriable I/O failures
(`:988-1082`). Preserve that operator-only bulk capability separately from the
single-current-page web validator. Harden bulk XML with the same isolation and
DTD/entity policy plus explicit bulk budgets; do not expose its permissive
local-name reader as a public upload route. Port `tools/lexicanum_audit.py` with
its own offline test evidence, not as a UI feature assumed to exist.

Expected three implementation PRs, after the shared storage/publication prerequisites:

1. Intake validator, durable queue/custody and scoped client credentials. Targets
   BLC-049, BLC-050 and NEW-006. Include CSRF/operator refusals, authentication
   before reads, real stream limits, key replay/conflict, revoke/rotate and parser
   resource-exhaustion cases. BLC-050 must explicitly record the scoped replacement
   for the legacy key fallback rather than claim unchanged compatibility.
2. Parser/import/resolver wiring, isolated bulk importer and offline audit. Targets
   BLC-046, BLC-047, BLC-048, BLC-051 and BLC-203. Include stable-ID migration,
   whole-page revision replacement, archive collisions, quarantine sidecars,
   transient I/O/DB retry, rollback, deduplication and A/B/A behavior. Port existing
   helpers completely, not a line-range fragment. This work depends on S3 and
   the native generation adapter; a SQLite-only importer does not close NEW-003.
3. In-app URL/one-click workflow over PR #160, visible publication and audit status.
   Targets RT-055 and the owner's Update requirement. Verify both endpoint paths,
   exact signed payloads, envelope/XML/image caps, every browser failure state,
   canonical/export mismatch, optional cover failures, image-child admission,
   stale leases/revisions/pins, reload, privacy and accessible narrow-screen UI.
   An archived-cover fallback cannot turn a challenged update into current success.

Rows close only when the integrated behavior passes, including external intake
if RT-055's browser-export purpose is claimed. Server retrieval adds the preferred
path without silently claiming the parked extension is implemented. Hosted checks
remain required; all fixtures are synthetic and CI makes no live source calls.
This proposal authorizes no deploy, recurring job, service retirement, library
write, billing change or installed beta update.
