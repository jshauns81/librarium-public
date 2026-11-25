# Decisions

Append durable choices with date, status, rationale, and evidence. Mark replaced
decisions explicitly; do not erase history. Technology recommendations belong in
the [architecture assessment](architecture.md) until accepted.

## L001: Librarium product name

Librarium combines library browsing and catalogue evidence.

## L002: Expert-led exploration before implementation

Assess upstream contracts and runtime compatibility before selecting dependencies.

## L003: Shared contributor instructions

Contributors can use either Claude or Codex with the same repository instructions.

## L004: Development setup

Keep local setup reproducible and document the development entry points.

## L005: Design quality

Use the [UX standards](ux-standards.md) to evaluate interface changes.

## L006: Reproducible container releases

Distribute versioned images and use Compose for cooperating services. Keep persistent data outside replaceable containers. The [packaging contract](packaging.md) covers upgrades and recovery.

## L007: Begin implementation with a reviewable development environment

Use a reviewable development environment and verify each bounded change.

## L008: Claude and Codex without Copilot

VS Code and command-line contributors can work without installing Copilot.

## L009: Optional development tools

Choose optional development tools according to the problem they solve.

## L010: A bounded read-only application experiment

Use Django/React/PostgreSQL with independent Python workers to test collection,
evidence and durable metadata inspection using fictional data. Keep BLC's engines,
published consumer contracts, and LF/Calibre/CWA writers separately owned. No
real service URL, library database or writer capability is configured. The
[dated assessment](research/first-slice-2026-10-24.md) owns the alternatives,
support/pin evidence, retained/adapted map and experiment limits. Continue with
version-pinned read adapters and contract tests before making integration claims.

## L011: Reading Lamp for the first working screen

Reading Lamp uses Literata for work titles, source comparisons and dedicated detail navigation on small screens.

## L012: Reviewed publication

Review source changes before publication.

## L013: Repository-owned conventions

Use repository-owned conventions and preserve the existing project stack.

## L014: container hosting behind an authenticated proxy

Package web, worker, migrations and PostgreSQL as a persistent Compose stack.
Keep state outside images and catalogue reads read-only. Protect access with an
authenticated reverse proxy. Set the origin and routing through private environment
configuration. This decision does not itself approve production activation,
shared-service changes or library writes. [Dockhand setup](dockhand.md) owns the
portable contract; exact targets and approvals are retained privately under L051.

## L015: coordinated target setup

Coordinate only the explicitly approved application roles and isolated persistent
state. Preserve existing services, routes, policy and library data. Distinguish
configured tool access from authority to modify a target. A reviewed setup record
must bind source/image, roles, recovery and target checks; source documentation
must not contain the operator's host inventory, session IDs or runtime paths.
The environment contract defines private discovery for that evidence.

## L016: Reading-room design direction

Use responsive layouts, a restrained reading-room palette and motion that respects reduced-motion preferences.

## L017: Independent pinned catalogue copy and admission before serving

Keep an independently verified read-only copy of the catalogue. Bind reads to its version and SHA-256. Admit the configured snapshot at worker startup, fail startup on an invalid configured snapshot, and restart workers after changing the current version.

## L018: Read saved library matches through the existing LF browse contract

Read saved library matches through the existing browse contract. Preserve the catalogue pin, source identity, check date and coverage.

## L019: Launch with selectable palettes and a theme-aware vector emblem

Provide selectable palettes and a theme-aware vector emblem with a dedicated small-screen mark.

## L020: Use the supplied A logo family; add Parchment and keep the default

Use the supplied Librarium A vector family and support the Parchment palette.

## L021: Review changes on the default branch

Use reviewed changes on the default branch.

## L022: Connect catalogue, library evidence and durable reviews locally

Link catalogue works, library evidence and durable reviews through source-bound identifiers. A source read grants no permission to modify a library.

## L023: Source and context provenance

Keep generated navigation and operational handoffs outside version control. Verify source provenance before relying on cached information.

## L024: A personal reading room with engineering on demand

Treat Librarium as a reading room. Lead with shelves and the selected book. Make source evidence available on demand. See [design](../DESIGN.md).

## L025: Bounded, pinned Library shelves and the reading-room foundation

The maintainer approved [the rendered foundation](design/reading-room-foundation-2026-10-26.md)
and authorized implementation and publication. Series is the remembered default;
Title/Author, Copies and Shelves/List remain available. Masthead search, admitted
covers or composed folios, desktop detail, phone focus/Back, evidence and metadata
reviews keep their established boundaries.

`GET /api/library/shelves` requires the local catalogue version and SHA-256 and
accepts search, Copies, page and LF check token. SQLite closes before network
access. Results of at most 600 titles retain the complete small-result path:
one title-ordered page plus at most two concurrent pages under the request's
three-second network deadline. The full matching listing, rather than the
catalogue-wide LF series facet, determines which shelves exist.

For larger results, the initial bounded listing read supplies check metadata and
the first 200 titles. A single background coordinator per web process reads the
remaining title pages once, with at most three concurrent GETs. Interactive reads
return **Preparing shelves** immediately while it builds; the existing 2.5-second
poll consumes the ready result. Each GET retains the same three-second read,
one-second connect and 2 MiB body bounds. The background run has a separate
30-second total deadline, at most 50,000 matched works, and no unbounded executor
or filter queue. Four completed/pending indexes at most are retained per process,
keyed by LF origin, catalogue directory/version/digest, check token, query and
Copies filter. A busy coordinator defers other filters to their next poll.
Each gunicorn worker builds its own index: the first page view handled by each
worker prepares independently. The per-process cache remains the local experiment's
design; no worker/deployment topology changed. During another preparation the
previous ready page stays visible, dimmed and inert, with a status note. Page and
evidence labels continue to describe that previous result until its replacement
is ready. Indexes are derived memory, never authoritative state.

Every page must agree on token, catalogue version, date, coverage, loading and
filtered total; duplicate work identities fail the entire build. The local
immutable pin is checked again before publication. A changed token selects its
own index; prior ready indexes remain within the same four-entry LRU bound. If LF
re-advertises an earlier token, reuse its ready index after checking the complete
metadata proof. An evicted in-flight build cannot publish. Cached results
also reject altered metadata under the same token. Errors reach the next poll;
a retry can rebuild after a transient failure. Oversize or incomplete reads never
publish a partial alphabetical shelf as recorded order. They retain explicit
recovery through Title/Author. Catalogue admission and SQL bounds remain unchanged;
local context caps are 50,000 works, 100,000 memberships and 100,000 author-role credits.

The complete listing is joined to the pinned local catalogue's memberships,
positions, work types, publication dates and canonical author-role names. Raw LF
credit strings never supply shelf credits or shelf-entry captions. Unlinked identities are reported and
remain accessible in Title/Author. A series is eligible for shelving only when
the pinned catalogue records at least one non-null position, including literal
zero or a negative value, and its name is not a `work.setting` value. Warhammer,
Warhammer 40,000, Warhammer Fantasy, Warhammer Age of Sigmar and Warhammer Horror
are always umbrella groupings. Names containing `reading order` (case-insensitive)
are reading lists and are also excluded from shelves and preferred pane series.
Their works remain on eligible series shelves (or Standalone and collected when
none qualify) and in the complete All N catalogue views; catalogue memberships
are preserved. Setting-name comparisons ignore case and surrounding whitespace.
Eligibility comes from the entire pin, not the matched subset; an
eligible series retains its unpositioned works. Only nonempty eligible shelves
are paged, **four per page**. A work in several eligible series appears on each.
Works with only umbrella/wholly unnumbered memberships, or no memberships, join
the complete **Standalone and collected** closing shelf in catalogue title order.
Its catalogue denominator counts that entire group. Series sort by matched-work count,
descending, then name ignoring leading punctuation and The/A/An. With a search,
series whose names contain the literal query lead that order. There is no pinned
opening-series list. The full result includes counts and a five-lead preview per
shelf: at most 20 unique preview covers fit the existing 24-work batch.

Recorded order remains numeric nonzero positions, then literal zero, then missing
positions. Position 0 is not a sequence position. The preview chooses **one
representative per nonzero numbered position**: novel before other types, then
earliest first publication, then title and identity. ISO prefixes YYYY, YYYY-MM
and YYYY-MM-DD compare as year/month/day tuples, with unknown parts after known
parts, in both catalogue detail and shelf selection. Zero and missing positions
each remain distinct entries, in their recorded-order groups. Only a nonzero
representative can carry the quiet `+N at this
position` caption reports alternates. All N opens the complete catalogue series
in its unchanged literal order, including alternates, and labels the catalogue
series total. `catalogue_context` computes canonical leads over all pinned works
once using the same query as catalogue detail. A shelf may choose a matched
representative when that canonical lead is unmatched, but never replaces the
canonical `lead_work_id` or `position_total`. The same work therefore says Book N
or Position N consistently when selected from a shelf or Title browsing.

An unpositioned or position-0 folio has no numeral block: its series line precedes the rule,
title and author, leaving room for the emblem. Its accessible entry name retains
No position or Position 0. Neither receives a cover chip. Negative numerals remain visible. Every rendered series
name permits a break after each slash; folio series text does not hyphenate or
break inside a word. The background coordinator catches every `Exception`, stores
a generic index error for the next poll and releases its slot; it cannot escape
as an unhandled thread failure. Snapshot-removal tests join network reads before
unlinking and await coordinator completion before fixture teardown.

The browsing row shows five leads at a collection-workspace width of at least
1280px, four at 1100px, three below, with no wrapped remainder. A selected preview
work remains visible when the row shrinks. Phones receive all five preview works,
retain horizontal scroll-snap, keyboard access and a visible next-book sliver at
320px with 200% text, and have no automatic initial selection. The full series carries the remaining
works. Position-count groups remain in the full series, not browsing shelves.

Shelf summaries use the catalogue total as denominator. They distinguish current
matched copies from saved, unconfirmed matches and state both on mixed shelves.
Every one is allowed only with complete counts covering a catalogue total greater
than one; a single title reads `1 shelved, with a saved match` where applicable.
An incomplete count states the catalogue total and how many entries were read,
without a match count. Pinned shelf totals count joined identities; raw LF totals
never overwrite them. Shelf credits count deduplicated canonical names over the
matched works: the leading author must cover at least half, otherwise the top two
must cover at least half together (unique works), otherwise say Various authors.
Rank by frequency, never alphabetically. Entry captions deduplicate names, show
at most two followed by `and N others`, and use `1 other`. Shelf credit text is
capped so All N stays beside the header at 1440px. A shelf entry's accessible name
separates position, title, author and status with punctuation. Route selection names
one shelf, including explicit `ls=none` for the no-series shelf. Catalogue returns
clear the phone-detail flag; history entries with `ld=1` restore focused detail.

The closing shelf's `All N` uses its matched total and opens Title order with
`lg=standalone`, preserving query and Copies. The pinned shelves read accepts
`group=standalone` and pages the complete closing group, 24 titles per page, from
the same bounded index. A status note names the exact total; browser Back restores
the shelf, scroll and link focus. Normal Order changes clear this scoped group.
The pane names the originating shelf; flat Title/Author browsing prefers the
eligible membership with the most catalogue works, so setting umbrellas cannot
displace The Horus Heresy in Title-order detail.

LF's `sort=catalogue` loses zero/negative positions and some memberships. This
reader therefore uses title pages for complete distinct matches and restores
bibliography locally. The digest remains a version-contract association with LF,
not LF byte attestation. Current/missing claims still require complete coverage;
trusted fixed-origin copy links and admitted digest-verified covers are unchanged.
No external writer, cover download, production mount or release is introduced.

The [private engineering record](agent-environment.md#private-context-discovery)
records actual checks, rendered proof, source provenance and remaining limits.

## L026: Sustained implementation toward LF and catalogue integration

Integrate the existing catalogue and library contracts in tested increments. Preserve source provenance and writer boundaries.

## L027: maintained archive reader and bounded inspection process

Replace the custom ZIP directory preflight and Python ZIP reader with
libarchive-c 5.3 and libarchive 3.8.10, forced to seekable ZIP with no filters.
Keep EPUB domain checks in Librarium. Do not add a second raw ZIP parser to
restore conformance claims the maintained reader cannot support. The selected
reader refuses the reproduced hidden-stream/size cases and supports bounded
ZIP64; a streaming-only candidate discarded directory metadata and did not
satisfy that contract. The [private engineering record](agent-environment.md#private-context-discovery)
owns comparative probes, pins, checks and source evidence.

Run the complete production inspection in a fresh resource-limited process,
because native directory allocation can precede member iteration. Capture
policy v2 and reader identity in new jobs/reports; refuse pending v1 jobs and
preserve saved v1 evidence without upgrading its assurance. Disclose normalized
names, effective metadata, empty-member CRC and raw-header limitations.
EPUB structure evidence cannot establish readiness, content completeness,
identity, ownership or authority to write library state.

The [packaging contract](packaging.md#maintained-archive-reader-and-policy-v2)
owns the native build, coupled upgrade path, operational limits and container
acceptance gate. This local implementation does not authorize activation,
deployment or retirement of incumbent writers.

## L028: explicit package metadata comparison against a pinned work

Connect completed EPUB inspections to catalogue evidence through an explicit
search and work choice. Calculate the comparison as a read-only GET bound to
the job, preserved source/report digests and catalogue version/digest/work ID.
Keep this separate calculation out of the immutable structural report and
worker input; it needs no new job kind or schema migration.

Reuse the captured BLC alias contract conservatively: canonical/recorded names
only, globally unique normalized ownership, distinct complete coauthor coverage
and preserved EPUB spelling. Name budgets refuse incomplete global evidence;
they cannot hide a collision and yield agreement. Do not infer nicknames,
surname matches or an automatic title-based association.

The existing report does not retain creator roles or title refinements. Expose
that limit and compare recorded names only, with incomplete, missing and
ambiguous states. Agreement is neither independent identity evidence nor
readiness, ownership or admission. LF's Calibre identity/duplicate changeover
work and all writer gates remain open. [Development](development.md#preserved-epub-and-catalogue-comparison)
owns the API/policy limits; the [private engineering record](agent-environment.md#private-context-discovery)
owns implementation and acceptance evidence.

## L029: sustained implementation and safe merges

Keep release and runtime activation separate. Review changes and require applicable checks before merge.

## L030: labelled contents evidence before repair planning

Status update (part): the repair-planning half of this decision is superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-23: the contents planner is removed (inspection v11). The labelled heading, link and NAV/NCX evidence that checks read stays; the evidence only the planner read (word/media offsets, anchor lists, group-label source positions) is no longer captured.

New EPUB inspections capture bounded heading and anchor labels plus recorded
NAV/NCX ancestor labels inside the existing isolated worker. Advance the captured
inspection policy to v3; keep v1/v2 reports readable with their original bytes,
policy and assurance. Pending older policies refuse processing rather than
silently acquiring new evidence. Preserve native-reader bindings on historical
v2 reports as well as current reports.

Display these observations in the full structural report, preserving source
paths, fragments, document digests, source order and repeated chapter numbers.
An absent historical field differs from a captured empty label. No inferred
novel grouping, new anchors, repair decision or content-readiness claim belongs
in this evidence slice.

Captured LF `plan_contents` is a filesystem/ZIP wrapper over a much broader
heuristic planner. Reuse the verified source contract progressively; importing
that wrapper would bypass the maintained archive/process boundary. Its printed
contents fallback is flat and does not itself solve the documented omnibus
grouping case. A later proposal needs further source-backed position/text
evidence and explicit held reasons. The [private engineering record](agent-environment.md#private-context-discovery)
owns source locators and actual acceptance; this decision adds no dependency,
job kind, migration, production activation or writer authority.

## L031: source-bound read-only contents proposals

Status update: superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-23: the contents planner is removed in inspection v11. Reports from v4 to v10 keep their stored plan as readable history.

Inspection policy v4 adds source element/word/media positions, existing anchors
and exact group-label provenance. Inside the existing isolated inspection, derive
`librarium.contents-plan.v1` and store it in the immutable report. Keep supported
recorded navigation, propose complete source-backed runs and literal groups, or
hold ambiguous/unsupported evidence with an empty replacement list. A needed
anchor remains `requires_anchor`; never present an invented ID as source evidence.

Title-holder exclusions require source-backed absence of independent text/media
and a known later start. Preserve real short chapters and intervening stories.
The proposal does not change source bytes, navigation or library records and
cannot establish EPUBCheck, content completeness or readiness. This bounded
adaptation does not claim parity with LF's full contents/preparation pipeline.

Bind the plan to its source digest and captured inspection policy inside the
report's existing provenance chain. The compact `result.contents_plan` disposition
must agree with that immutable report. Retain v1/v2/v3 reports under their original
policy; refuse pending old-policy jobs rather than silently upgrading their
evidence. Existing field/XML/record/output and process limits still apply, with
explicit planner entry/depth limits.

The [private engineering record](agent-environment.md#private-context-discovery) owns implementation,
review and acceptance. This adds no job kind, migration, dependency, writer,
release, production activation or service retirement authority.

## L032: explicit source-bound official EPUBCheck evidence

Run EPUBCheck only as a separate requested durable job against an already
preserved, completed EPUB inspection. Bind its captured input and saved report
to the source job, exact original source/report digests, processing profile and
checker identity. Retain the original structural report's `epubcheck=not_run`;
new validation evidence does not rewrite an older observation. Historical
captured profiles remain readable; pending changed profiles refuse processing.
Exact request-key recovery remains possible without accepting a new profile.

Select official EPUBCheck **5.4.0** and Java **21**, with Temurin **21.0.13+9**
in the image. Verify the complete distribution/archive and all 40 JAR hashes;
retain licenses and forbid caller-selected checker arguments. The current
production release and maintained Java patch were checked against primary
release/support sources in the [runtime assessment](research/epubcheck-runtime-2026-10-27.md).
That assessment owns digests, compatibility, known limits and the upgrade path.

The untrusted publication runs in a fresh Linux x86_64 child, with network
syscalls denied and Landlock ABI 3 or newer required. Filesystem access is
limited to the pinned checker/JRE, public runtime support files and private
scratch. Apply fixed resource/output limits, a clean environment, process-group
cleanup and parent-death kill. Fail closed when required isolation is absent.
No original artifact path or arbitrary host input is passed to Java.

Distinguish completed conformance failure from runtime failure, and keep
warning-only exit 0 as a pass. Report official grouped-message counts separately
from retained locations; an absent INFO aggregate is unknown, not zero. Bound
stored diagnostics and disclose omitted messages/locations. Conformance cannot
establish content completeness, identity, ownership or readiness.

Schema 0005 adds `epub_validation` to application-owned jobs with guarded
reverse migration. Coordinate worker/web upgrades and preserve database and
artifact backups. The [private engineering record](agent-environment.md#private-context-discovery) owns
implementation and acceptance; [packaging](packaging.md) owns actual-image
replacement/restore gates. This decision authorizes no production activation,
EPUB repair, Calibre/CWA write or incumbent-service retirement.

## L033: explicit ISBN evidence against the complete catalogue pin

Extend the explicit preserved-EPUB/catalogue comparison with a separate ISBN
disposition and recorded edition evidence. Existing reports retain identifier
text, so assess only explicit `urn:isbn:` values; do not infer a scheme for bare
numbers or acquire new facts from omitted historical attributes. Normalize valid
ISBN-10 to its 978 ISBN-13 representation and retain original spelling. Checksum
and supported prefix checks do not prove publisher allocation or source identity.

Compare against primary edition ISBNs and `edition_ident` over the entire pinned
snapshot. Preserve disputed, orphan/unassigned and cross-work ambiguity. Keep
no-match unknown, unique other-work evidence different, and recorded formats
literal. Name agreement stays separate; do not count equivalent ISBN forms or
several editions as independent identity votes. Explicit work selection, source
and report hashes, snapshot version/digest and bounded read-only execution remain.

This changes comparison schema/policy to v2 without a new inspection policy,
job kind, migration, dependency, source transformation or writer. The
[private engineering record](agent-environment.md#private-context-discovery) owns evidence and remaining gates.
Source-bound Calibre origin/duplicate assessment, complete-file identity and
preparation/admission remain separate work; production activation and all
established library-writer approvals are unchanged.

## L034: capture declarations before interpreting bare ISBN values

New inspections use policy v5 to retain raw package `unique-identifier` and
`prefix` attributes, qualified OPF schemes, identifier IDs and direct
`identifier-type` refinements. Bind observations to package path/bytes and XML
source indexes. Count IDs across the complete package, deduplicating aliases on
one element; resolve only unique, legal XML IDs on direct DC identifiers in the
same package. Support the single legacy EPUB 2 `dc-metadata` container without
inferring creator roles or title refinements.

Comparison schema/policy v3 may interpret a qualified EPUB 2 ISBN scheme, or an
EPUB 3 unprefixed `identifier-type` with the exact resolved ONIX codelist-5 URI
and code 02/15 for ISBN-10/13. Honor EPUB prefix overrides; XML namespace aliases
are not EPUB vocabulary declarations. Require the specified prefix/reference
grammar and XML whitespace rules. Preserve non-ASCII padding and malformed ID
references without manufacturing supported types. Multiple, conflicting or
ambiguous declarations cannot fall through to a favorable ISBN match.

Retain explicit ISBN URN support and complete pinned-catalogue collision checks.
Expose raw declarations, interpretation basis, reasons and source positions;
keep title/creator agreement separate from ISBN agreement. Unknown declarations
are unassessed, not a new conformance verdict. Enforce the combined 256-declaration
reference ceiling rather than truncating evidence.

Saved v1–v4 reports remain readable and byte-immutable, with historical capture
absence distinct from captured empty fields. Pending older policies refuse the
new worker; an explicit new inspection is required to acquire new facts. This
adds no migration, dependency, job kind, source transformation or writer. The
[private engineering record](agent-environment.md#private-context-discovery) owns verification and delivery;
production activation, identity/admission and library-writer gates remain.

## L035: GitHub owns delivery planning and beta/stable release gates

Use milestones and issues for delivery planning. Promote the exact accepted beta image digest to stable. The [release policy](releases.md) defines acceptance.

## L036: isolated beta pipeline and Dockhand release

An isolated beta requires separate state, credentials and a recoverable configuration. Scope and verify activation for each target.

## L037: Bind activation to an approved release

Bind an isolated activation to the approved source, image digest, roles and recovery procedure.

## L038: source-bound beta acceptance before digest-preserving promotion

Use a manual main-only promotion workflow sharing the beta publisher's release
concurrency group. Validate the existing annotated beta tag, source-derived
release manifest, recorded publication run and attempt-specific successful jobs,
plus exact registry bytes/digest. Stable publication reuses those manifest bytes
without rebuilding and retains source, beta, run and human-acceptance provenance.
Any existing stable Git/registry/Release identity refuses publication; partial
publication reserves its version and requires a new matching candidate line.

Elapsed time and CI cannot establish user acceptance. Require an unedited,
repository-owner-authored issue comment using strict
`librarium.beta-acceptance.v1`, bound to repository/beta/source/digest, a complete
48-hour observation window and evidence for authenticated representative
journeys and restart/reconnect, with no release blockers. Fetch evidence through
fixed repository APIs; recheck its hashes before publication. This is explicit
operator attestation, not generated human-use evidence. [Release policy](releases.md#explicit-beta-acceptance-record)
owns the schema, semantics, transport limits and remaining acceptance boundaries.

Initially require publication workflow SHA to equal selected source SHA. Older
main-reachable beta sources remain held until their selected input has separately
verified provenance. Historical source is compatibility data parsed as AST, never
executed under publication credentials. Permit only the documented credential-free
single GitHub release-asset redirect and verify asset size/SHA-256. No target
credentials, deployment call, automatic acceptance comment, shorter-observation
override or library writer belongs to this tooling.

2026-11-13 extension: release schema v2 binds the application and source-browser
images to one accepted source, with each registry/config digest and a deterministic
checksummed stack archive. Acceptance schema v2 additionally binds the browser
registry digest. Promotion verifies both existing manifests and the source-exact
archive before copying either role, and verifies both stable images before creating
Git/Release identities. Partial registry publication reserves its version and cannot
be retried as complete. Historical v1 manifests/attestations remain history and do
not authorize paired promotion. This extends the existing release owners rather
than adding a separate deployment or registry system.

## L039: bounded saved-check recovery with historical view provenance

Only a typed local `LibraryCheckChanged` exception exposes HTTP 409 with
`code: "library_check_changed"`. Catalogue-pin conflicts remain distinct and
cannot trigger an automatic pin switch. Preserve the existing bounded LF reader
and its response validation; do not forward upstream error bodies or codes.
Older responses without the explicit reason keep manual recovery.

The browser may read a fresh check once during a recovery episode under the
same catalogue pin. Keep that budget across token adoption and preparing polls;
require explicit retry after another conflict or terminal failure. A valid
complete read or newer user intent can begin another episode. Consumed abort
signals and intent-scoped query keys prevent obsolete responses from changing
newer browsing state. Mount and reconnect must revalidate cached saved checks.

Retain only a compatible displayed view with its actual filters, page, token and
catalogue pin. Old positive matches become historical, current copies are
unconfirmed, and old absence becomes unknown. Known-invalid cache entries cannot
regain current claims after cancellation/remount. Actions on retained rows capture
the displayed provenance; a newer book choice supersedes an older pending page.
Catalogue return can reconcile a changed token only under the same exact pin and
a surviving work identity. Phone detail retains visible recovery and retry, with
meaningful keyboard focus after completion.

[Development](development.md#read-only-library-connection) owns the adapter's
read contract, [UX standards](ux-standards.md) owns truth/context semantics, and
[private engineering record](agent-environment.md#private-context-discovery) records
actual verification. No source content, upstream service, library writer,
dependency, migration, job kind or target activation changes in this slice.

## L040: Catalogue and author browsing share the room and retain search intent

Catalogue, author and series browsing reuse the established reading-room folios,
List presentation, masthead search and selected-book hierarchy. General Catalogue
rows remain bibliographic and make no ownership claim. Keep per-work evidence,
source disputes, synopsis, editions, metadata reviews and recovery available.
Directory credits may show only fields its actual API provides.

Works/Series switching retains both the committed query and unsubmitted draft,
while resetting page and incompatible selection/filter IDs. Author identity is
its page heading; All works clears author scope while preserving applicable
query/series context. Return controls name the author/series/catalogue context.
Explicit snapshot switching clears scoped IDs; automatic pin switching remains
forbidden. Catalogue order, 24-item paging and source admission remain unchanged.

Theme changes update the browsing controls' foreground/background together to
preserve contrast. List rows reflow under enlarged text in both Catalogue and
Library because their presentation preference is shared. No new theme, motion
system, API, dependency, policy, writer or target activation is introduced.
[private engineering record](agent-environment.md#private-context-discovery) owns actual checks;
full #42 and #27 retain unperformed device acceptance.

## L041: native read-only library access leads the combined-service migration

Librarium reads the authoritative Calibre metadata and recorded book files itself.
Prefer that native source when configured; it needs no Index/LF HTTP intermediary.
Keep the established Calibre/CWA writer boundaries. Mount originals read-only in
web only; workers inspect preserved app artifacts and receive no library mount.

Live Calibre metadata uses WAL. Copy bounded database/WAL bytes into private
transient storage under before/after source identity fences, then query only the
private copy with SQLite read-only/query-only/trusted-schema controls. Never use
immutable snapshot semantics to silently discard live WAL changes. Refuse unsafe
paths, symlinks, changed observations, malformed inputs and resource overruns.
The observation token covers metadata, not every library file's content identity.

Actual-file inspection captures only a selected recorded EPUB under the same
observation, rechecks source/file identities before publication, preserves bytes
in the existing private artifact store and binds library UUID/book ID/observation
into the job input fingerprint. Matching pins both observations and catalogue
bytes; preserve alias, ISBN, collision, disputed and incomplete evidence without
turning name agreement into complete-file identity or correction authority.

Catalogue control exposes saved-source observations and attention queues ahead
of supporting browsing. Until native production and whole-library matching run,
show updater not configured and unmatched not assessed. Same-title groups are
possible duplicates only. The [private engineering record](agent-environment.md#private-context-discovery)
and [private engineering record](agent-environment.md#private-context-discovery) own remaining parity,
producer, consumer, activation and recovery work. This decision authorizes no
library write or service retirement.

## L042: retain the reference engine behind private native publication

Bring BLC's evidence store, canonical resolver and immutable snapshot projection
into Librarium from pinned source `a8f2744`, retaining source history, stable
anchors, aliases and field provenance. A checked source/adaptation manifest owns
the retained code. Do not substitute a simplified matcher or fabricate fresh
observations during migration.

Start with explicit bounded offline packets and app-owned private state. Copy an
admitted pinned bootstrap once; subsequent updates use native retained evidence.
Serialize imports, preserve exact request bytes and UUID outcomes, build each
generation separately and cut over only an admitted immutable publication.
Recover an interrupted UUID against its original expected current generation.
Keep snapshots, receipts and evidence together for recovery; no automatic pruning.

The web surface reports manual update health and outcomes without accepting
imports or silently moving a browser's selected snapshot. Provider acquisition,
automatic scheduling, persistent full-library reconciliation and real beta proof
remain next stages. The [private engineering record](agent-environment.md#private-context-discovery) records
actual independence evidence and its limits. No library writer, provider network
access, production activation or service retirement is authorized by this decision.

## L043: Operational handoffs

Keep operator-specific handoffs and deployment observations outside the repository.

## L044: Source publication

Publishing source code and activating a deployment are separate decisions. See [privacy](privacy.md).

## L045: backend delivery before deferred series and interface work

Continue backend delivery while series controls and broader UI refinement remain
deferred. The next slice persists complete native metadata inventory and matching
coverage against an explicit catalogue pin. Use the already tested matcher and
source fences, retain historical observations, hold unsupported records, and
publish only complete reports. Explicit commands keep the batch outside web
requests; a durable worker/schedule and visible queues are subsequent delivery.

An explicit prior report defines inventory changes; library UUID and per-record
UUID uncertainty remain distinct from catalogue/name agreement. This slice does
not assess complete file identity or duplicates and does not admit corrections.
Provider acquisition, preparation, consumer parity, target acceptance, established
writers and retirement retain their separate remaining work and boundaries.
[private engineering record](agent-environment.md#private-context-discovery) owns
implementation, actual-data evidence and continuation. No frontend or installed
beta behavior changes as part of this slice.

## L046: saved coverage and selected-file bytes keep separate evidence boundaries

Expose complete saved coverage through explicit report UUIDs and bounded historical
pages. Catalogue control may use a selected report's unmatched count only after
both selected catalogue bytes and native metadata token/library UUID agree.
Changed sources retain historical observations; unavailable reads leave current
claims unconfirmed. Source tokens include complete streamed database and WAL
digests plus file stats. Prefixes cannot fence checkpointed pages or recycled WAL
frames when filesystem timestamps coincide. Copied chunks must match the observed
digest, and final source checks retain that identity. Existing size/time limits
bound evidence reads; exhaustion leaves claims unconfirmed.
Historical stat-only tokens are not promoted without rescanning. Never choose an
implicit latest report or infer file identity.

Selected-file byte rechecks are explicit, bounded, source-fenced observations
against the captured native origin and saved inspection digest. They do not
change the saved inspection. Correction preparation composes already bound
comparison/contents evidence, preserves held/absent plans, and keeps work identity,
duplicates and correction admission unassessed/held. No writer, whole-file census,
new schema/policy for inspections, scheduler, frontend or target activation is
introduced. [private engineering record](agent-environment.md#private-context-discovery) owns
scope, proof and continuation. Evidence: the maintainer's current request to finish PR
delivery, expose saved coverage, then advance identity and preparation.

## L047: durable checks and independent identity evidence precede admission

Queue complete reconciliation and selected native EPUB assessment as explicit,
idempotent durable jobs, capturing source selections and engine policy. Renew
leases during bounded observations and publish only under the current lease;
commit complete reconciliation evidence with job completion atomically. Recover
by the exact request key without depending on source availability. No scheduler
or implicit latest report is introduced.

Independently assess preserved EPUB declarations against the selected catalogue
work/edition, and census original EPUB copies under the selected reconciliation
and library inventory. Metadata matching cannot substitute for package evidence;
byte equality cannot establish bibliographic/content identity. Distinguish declared
work/edition support, exact-byte copies and possible semantic duplicates. Missing,
changed or unsupported evidence holds admission. Preparation may consume one
explicitly selected historical assessment, retaining its source binding and limits.
Content authentication, semantic duplicate clearance and writer authority remain
separate blockers; this change introduces no correction artifact, library writer,
production activation or source-service retirement. Minimal existing Progress
compatibility is included; broader series/UI work remains deferred.


## L048 — Preserve incoming provenance and bound content duplicate leads

A preserved uploaded EPUB may be assessed against one explicitly selected complete
native reconciliation without manufacturing a Calibre origin or excluding a
library record. Native origin exclusion requires the same library, inventory and
record identity. Keep declared bibliographic support separate from content
authentication, following captured LF identity/changeover contracts.

Versioned ordered spine source-text/resource fingerprints provide reproducible
content comparison facts within existing isolated parser budgets. Compare at most
eight explicitly pinned preserved inspections; do not choose latest evidence or
claim whole-library semantic coverage. Equal normalized text supplies a possible
duplicate lead, and different text is not an exclusion. Historic reports without
capture, orphan/unsupported/partial evidence and other formats remain unconfirmed.
All content/semantic/writer admission boundaries remain held. This adds no writer,
format conversion, output artifact, schema, default role or deployment.


## L049 — Broaden duplicate evidence without promoting authentication

Assessment v3 checks exact bytes against every recorded native format, bounded by
20,000 format rows as well as the existing book/byte/time limits. Exclude only the
selected native EPUB; another format on the same record remains a candidate.
Different size/bytes exclude exact copies only. Other-format content equivalence
stays unconfirmed; no format parser/converter or library writer is introduced.

Compare existing source-bound spine XML resource digests from explicitly pinned
eligible v6 reports. One-to-one occurrence matching supplies bounded overlap leads,
including boilerplate; directional resource containment is not narrative
containment. Preserve text comparisons, native-origin handling and historical
absence. No implicit latest report, all-library content scan or semantic clearance
is added. Retain historical v1/v2 assessments; refuse pending old engine work.

Independent investigation of captured LF contracts recommends source-located
printed title/credit capture and separate pinned corroboration as the next slice.
It implements no authentication: complete narrative identity still needs a concrete
independently trusted reference or attributable whole-file review. Metadata, bytes,
resource overlap and a caller's assertion cannot establish that trust.

## L050 — Source attribution remains separate from whole-file authentication

Inspection v7 captures source-located short title and credit labels without an OPF
or catalogue search prompt. Bound the first four spine entries, labels, observations
and credits; stop at narrative context and retain semantic titlepage candidates
separately from unclassified heading leads. Exclude navigation, advertisements,
previews and inline hidden/script content. Markup describes source only; external
CSS rendering is not established. No source prose goes into job input or logs.

A separate pinned comparison uses complete catalogue author credits and globally
unambiguous aliases to corroborate attribution, disclose conflicts or leave it
ambiguous/unconfirmed. Repeated candidate blocks stay ambiguous. An internal
story title cannot identify a collection. Whole-file identity and content
authentication remain unconfirmed even when attribution corroborates; bibliographic
catalogue fields share one lineage. Assessment v4 retains content/semantic/writer
holds. Completed old policies stay historical; pending old policies need a new
request, and no report acquires observations retroactively.

Full narrative authentication still requires a concrete independently trusted
reference or attributable complete-artifact review with source lineage and coverage.
No caller boolean, arbitrary URL, OPF agreement or provider name supplies it. No
external book delivery, owner attestation import, format converter or library writer
is introduced. [Development](development.md#source-title-and-credit-attribution)
owns the contract and [private engineering record](agent-environment.md#private-context-discovery) owns checks.

## L051: keep personal and operational context out of published material

Keep personal data, private hostnames, network details, host paths, environment inventories and real-library observations outside published material. Preserve third-party attribution. Review Git history and hosting surfaces before publication.

## L052: compare normalized document text and prepare curated references

Inspection v8 captures complete ordered XHTML body text fingerprints per document
inside existing isolated parser and record/output limits. Assessment v5 pairs
explicitly selected historical captures one-to-one, preserving both source
locations/resource digests and bounded detail with complete counts. Identical
normalized text can expose overlap after markup changes; boilerplate, case and
punctuation, changed document boundaries and unsupported media limit the claim.
Document text equality or containment never authenticates the narrative, clears
semantic duplicates or grants writer authority. Historical capture absence and
saved old assessment scope remain intact; pending engines refuse reinterpretation.

Optional document rows have lower budget priority than existing structural,
whole-spine, attribution and contents evidence. Exhausted optional capacity yields
unconfirmed document text without changing a valid structural verdict. Reference
catalogue pins record original provenance; current assessments pin a current
snapshot and require the same explicit work ID, without fuzzy rebinding.

The maintainer selected locally curated reference copies with documented provenance
as the next whole-file authentication route. Prepare an independent authority and
acquisition/coverage contract; no real reference, issuer, acquisition receipt or
trust configuration is activated here. Metadata, caller assertions and text hashes
cannot supply that trust. Non-EPUB extraction needs its own immutable format/parser
boundary. No external book delivery, library mutation or deployment is authorized.

See the [document comparison contract](development.md#normalized-document-text-overlap),
[compatibility contract](packaging.md#inspection-v8-and-assessment-v5-compatibility)
and [trust/format design](research/whole-file-trust-and-format-evidence-2026-10-29.md).

## L053: authenticate curated copies through an explicit saved assessment

Use an independently configured registry path and exact digest outside upload,
library and writable application state. Request pins select registered immutable
manifests; they cannot nominate an authority or trust root. Validate complete
reference bytes and all curation evidence bindings, authority scope, validity and
revocation before recording an authenticated exact-reference match. No real
authority or reference corpus is selected by source implementation or fixtures.

Keep original reference catalogue pins as provenance. A current assessment must
resolve the same exact current work ID and, for collections, every constituent.
Do not remap aliases or titles. Support an edition claim only while that edition
belongs to the work. Preserve current and original pins separately. Ordinary
checks without a reference do not read trust configuration.

Complete the candidate-assessment workflow as one group: explicit saved coverage,
comparison/reference choices, durable check/recovery/cancellation, readable results
and history, with whole-workflow verification before delivery. Assessment v6 may
clear only the content-identity hold on a supported exact-reference match.
Semantic duplicate and writer holds remain; correction admission stays held.
Separate corrected EPUB generation/validation and approved delivery/recovery are
later work. Broader semantic and non-EPUB evidence still need their own contracts.

See [development](development.md#curated-reference-authentication-and-assessment-history)
and [read-only role configuration](packaging.md#candidate-assessment-roles-and-curated-references).
No production activation, library mutation or external book delivery is authorized.

## L054: generate held review copies and validate the saved output

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

The corrected-output arm follows these twelve decisions:

1. Explicit held-copy requests may carry the closed set of identity, duplicate,
   historical and writer holds. Source-integrity, pin mismatches and unknown
   blockers refuse. Generation never clears delivery or writer admission.
2. Support a single simple title, the complete author set under verified role
   partitioning, and replacement of a proposed contents plan. The author block
   replaces the first original author in place; other creator nodes keep order
   and bytes, independently verified against the full creator sequence. EPUB3 gets a new
   non-spine nav beside the old nav (otherwise beside the package); the old nav
   bytes remain and only its designation changes. Update existing NCX consistently;
   EPUB2 replaces or creates NCX. Heading changes insert IDs only. Disclose EPUB3
   modification time and navigation wiring. Typography, junk pages, OCR text,
   cover, identifiers and series are always `not_attempted` in v1; L057 adds
   the selected stylesheet operations in v2.
3. Require a passed v8 inspection and complete document-text evidence. Refuse
   protected containers, multiple renditions, case/Unicode normalization aliases,
   fixed layout and media overlays for every selection. Scripted content,
   in-spine navigation and auxiliary navigation cut only navigation replacement;
   preparation advertises those same gates.
4. Read untrusted source ZIPs only through pinned libarchive in children. The
   parent may use bounded stdlib ZIP reads of generated stylesheet members solely
   to recompute report digests. Re-encode with `zipfile`: mimetype
   first and stored without extras; other members deflated at level 6, or stored
   when deflation would exceed the captured inspection expansion-ratio limit;
   disclose the deterministic rule and each member's choice in the report. Keep original
   order; sorted UTF-8 additions; DOS epoch timestamps, UTF-8 names, 0600 attributes
   and no comments. Verify logical bytes, lengths and hashes. Report `re_encoded`;
   compressed streams are not preserved. The same capture/runtime gives identical
   output. Equal source/output digests refuse as `no_effective_change`.
5. Fresh Python generation/preservation children use isolated interpreter mode,
   clean environments, closed unrelated descriptors, new sessions and resource
   limits, plus parent-death termination, process-group cleanup and interruptible
   transport. Output leaves by a bounded owned pipe; only the parent publishes.
   Inspection, eligibility, generation and preservation now preload trusted
   runtime modules/native libraries, then install shared seccomp network/io_uring
   denial and grant-free Landlock before reading untrusted payloads. All supported
   filesystem rights are handled, with TCP denial at ABI 4+ and UDP at ABI 10+.
   Linux x86-64, libseccomp and Landlock ABI 3+ are mandatory. Newer ABIs reuse
   the masks checked against ABI-12 headers; observed/effective ABIs are logged.
   ABI 6+ scopes signals and abstract UNIX sockets. Python-only seccomp denies
   process/group escape, exec, namespaces and clearing parent-death signalling,
   while preserving thread creation. Trusted codecs are preloaded; a late import
   terminates with a stable sandbox code. ABI masks and layouts have construction tests. Unavailable isolation fails with
   no verdict.
   No fallback, writable scratch or new mount is introduced. Java's existing
   runtime/scratch grants remain unchanged. Historical evidence gains no new
   isolation claim; deployment-kernel acceptance remains required.
6. EPUBCheck checks output bytes through a neutral subject binding. Fatal/error
   findings fail; warnings remain visible on a pass; INFO may be null. Runtime
   failure has no conformance verdict. Original validation remains independent.
7. Migration 0008 adds `CorrectedEpub`, protected evidence links and the two job
   kinds `epub_correction`/`output_validation`. Corrected artifacts have their own
   prefix and a 32 MiB cap. Output rows have no path, mutable verdict or delivery
   column. Reversal refuses while either kind or any output exists. A database
   capability guard prevents older workers from leasing these jobs.
8. Publish artifacts first, then atomically bind exactly one output, its mandatory
   initial validation and the generation result under the live lease. Refusal is
   successful execution with `outcome=refused`; runtime failure is a failed job.
9. Expose one combined output-validation report with bounded check details.
   Separate full per-check readers are deferred.
10. Replay exact keys and normalized intent before accessing live inputs. Changed
    intent conflicts; another active equivalent intent conflicts with a locator.
    Freeze catalogue values and the output timestamp at first acceptance.
11. Keep child limits at 10 CPU seconds, 15 wall seconds and 1 MiB of report,
    with a 30-second generation job deadline,
    a 150-second validation deadline, two-second heartbeats and three crash attempts.
    Never raise limits automatically.
12. The frontend consumes the frozen additive preparation/options, selection,
    recovery, progress, result and history contracts. A pass reads “Selected
    corrections validated; held for delivery”. Download, device-ready claims,
    library writing and delivery remain outside this arm.

See [development](development.md#corrected-output-backend) and
[packaging](packaging.md#schema-0008-corrected-output). Backend checks do not claim
that the concurrent frontend or hosted-image acceptance has run.

## L055: conditionally replace one EPUB through a synthetic sole-owner writer

Status update (2026-11-22): [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) removed this decision's orchestration (web approval, dispatcher, routes and worker). The writer core it describes remains, unreached by the application, pending a later owner decision.

1. Build a dedicated, disabled-by-default writer using the pinned Calibre 9.17.0
   database/cache API. Its first feasibility gate must prove identity checks,
   expected-byte comparison, hooks-disabled replacement and byte-identical
   read-back under the actual cache lock. Use only synthetic libraries. This
   authorizes no deployment, real library, incumbent-service change or writer
   credential provisioning.
2. Replace only the existing EPUB of one exact library UUID, book ID and book
   UUID. Do not add a format or book. Each action has one immutable reviewed
   intent, its own request key and one operation-bound result. No batch route is
   introduced.
3. Write validated EPUB bytes only. Library title, authors and cover stay as
   requested; internal EPUB corrections do not synchronize library metadata.
   Preserve other formats and disclose this distinction in the preparation.
4. Classify holds per selected operation. Catalogue title and complete author
   changes require fresh, source-bound authenticated exact-reference identity,
   supported work/edition and corroborated attribution under current pins.
   Source-derived navigation needs no identity assessment. Mixed selections use
   the stricter rule. Every selection requires exact-output mandatory validation,
   supported policies, intact evidence, native origin, a fresh reviewed observation
   and the expected-source digest fence. Unknown holds, missing required evidence,
   revoked trust and changed sources hold delivery. Duplicate uncertainty,
   including no current or complete duplicate assessment, stays unresolved and
   requires explicit per-request acknowledgement; it never blocks this in-place
   replacement. Contents uncertainty is acknowledgeable only when navigation is
   kept and validation passed. Historical writer holds are superseded only for
   the authenticated frozen operation and verified writer capability.
5. Retain originals, corrected outputs, evidence, approvals, journals and receipts
   indefinitely. Full storage holds before send and never triggers pruning.
   Undo is a separate conditional EPUB-only operation: current bytes must equal
   the delivered digest. Preserve later metadata, cover and other-format edits.
   Undo has its own journal and receipt and never erases delivery history.
6. Persist application acceptance and writer send intent before mutation. A lease
   expiry or lost reply causes observation-only reconciliation of the same
   operation, never an automatic repeated replacement. Distinguish applied,
   not applied with authoritative no-send evidence, diverged and unobservable.
   Original bytes after an uncertain send cannot disprove an ABA write/restoration.
   Cancellation after send remains an outcome check, not a no-change claim.
7. Prove sole-owner synthetic operation now. Independent GUI, CWA, calibre-web,
   Library Finish and catalogue plugin writers are unsupported and cannot be
   admitted by a caller flag. Live coordination remains a separate design and
   approval. Keep Calibre/Qt in a separate writer image; ordinary web and workers
   gain no writable library or writer credential by default.

The active transport is superseded by [L060](#l060-delivery-through-the-owning-calibre-content-server).

Evidence and boundaries belong to [development](development.md#conditional-epub-delivery)
and [packaging](packaging.md#synthetic-writer-role). Held-copy generation and its
immutable validation reports retain their L054 claims. No production activation
or installed beta update follows from these synthetic proofs.

Security review refinement: web recomputes approval holds from bound evidence and
limits expiry. Target-scoped comparisons exclude unrelated inventory drift.
Broker-authoritative never-sent operations remain not applied and release their
reservation; timeout or journal absence alone is insufficient. Historical outcome
checks cannot recapture released targets. New Undo grants bind the durable journal
identity and require a signed approval time after the current owner boot; target fences and operation consumption remain.
A held library marker flock checks cooperating synthetic owner exclusion and new
EPUB/database bytes are fsynced before applied receipts. Namespace/user limits,
physical power-loss gaps and privileged database maintenance remain explicit;
live coordination remains undesigned and unapproved.

A never-sent receipt can include a separate `present` observation and
`present_drift` without changing its historical classification. New Undo approval
time must fall between the current owner boot and its current clock time; old
pending grants seal after restart/restore. This synthetic same-host protocol
assumes a non-rolling-back shared wall clock; a distributed clock/fencing design
is part of the unapproved live topology.

Integration with L057 (2026-10-31): item 4 reads the selected operations from the
verified generation report. The three stylesheet operations are source-derived and
need no identity assessment; title and complete authors stay catalogue-derived, and
a copy mixing them keeps the stricter rule. Delivery applies its own kind table:
a v2 report must carry exactly the kinds it knows, a v1 report has no stylesheet
operations, and any other operation, field or kind adds the blocking
`operation_kind_unknown` hold. Preparations report `operations.typography`.

## L057: bounded stylesheet values in held corrected EPUBs

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

Extend L054 with three explicitly selected source-derived operations on linked
manifest stylesheets: replace positive absolute `line-height` with `normal`,
`text-align: justify` with `left`, and eligible near-black text/opaque white
background values with `inherit`/`transparent`. Retain declaration position,
surrounding comments, whitespace and importance. Comments inside a replaced
function value are part of that value and are removed. Do not change inline styles, text nodes,
fonts, margins or document structure. Typography alone keeps story, navigation,
SVG and image logical bytes identical; EPUB3 modification-time housekeeping is
still disclosed. Existing explicitly selected metadata/navigation operations keep
their own contracts when combined with typography.

Use tinycss2 1.5.1, hash pinned with its dependency in the lock and runtime export.
Verify it on pinned Python 3.14; map normalized parser positions to original UTF-8
bytes, retaining a BOM and CRLF. Refuse parser error tokens, detected EOF recovery, unsupported encodings, nesting
and unresolved imports; this is not a complete selector-validity checker. Adapter
exceptions become `stylesheet_unparseable`. Any typography failure affects only
typography, preserving the existing metadata/navigation gates. Script gates keep
parse-failure codes distinct. Any element's RTL direction, CSS RTL direction or
unsupported writing mode blocks left alignment. Colour refuses uncovered or
uncertain text colours (including link colours, escapes and unsupported functions),
legacy/inline colours, SVG stylesheet linkage including processing instructions,
and unsupported backgrounds. White backgrounds are editable only on literal
`html`, `body` or `:root` selectors. These conservative gates do not claim reader
rendering acceptance.

Refinement, 2026-10-31: synthetic scale evidence raises the ceilings to 512
stylesheets, 128 KiB per sheet, 192 KiB combined CSS, 6,000 declarations, 1,024
edits, 1,024 inline styles, 512 style elements, 512 documents, 4 MiB combined
document bytes, 32,768 elements, 15 MiB logical book bytes, 1,280 members and
256 KiB ASCII-escaped plan JSON. Samples and CSS nesting remain bounded as before.
Exhaustion still gives `typography_budget_exceeded` for typography alone.

Keep every child resource limit fixed. Accept new ceilings only when all measured
phases stay within the configured child limits, reserving
headroom for slower deployment hardware. An initial 8 MiB/65,536-element combined
candidate exceeded that CPU margin and was reduced. Resolve imports once and walk
reachable sheets once per document, replacing the repeated whole-sheet closure. Skip empty declaration parsing, use
constant-space ASCII offsets, and reuse identical-byte parse facts within one
child call while counting every occurrence against the shared census.
[The dated budget evidence](typography-budgets.tdd.md) records tiers, five-run
medians, observed maxima, binding constraints, RED/GREEN checks and limitations.
No real-library survey or service activation is authorized by this refinement.

Derive `librarium.typography-plan.v1` in the preparation child without changing
inspection v8. Include bounded samples in that plan, derive options without
reading EPUBs in the parent, and strictly validate child shape, types, vocabulary,
bounds and bindings. Capture its digest and full entries for selected operations.
Generation rederives the plan and applies only listed value spans. Independent
preservation rederives source evidence, checks exact expected splices before
parsing output, compares unchanged members and document text, and requires no
remaining eligible selected declarations. It shares the planner/parser with
generation, so it is independent of generator claims, not an independent CSS
detector. Exact splices preserve all unlisted structure and importance. The parent
checks summary counts and pins and recomputes output stylesheet digests. Report changed stylesheet/declaration
counts and byte-identical document counts.

Advance options, capture, generation, generation report and preservation to v2.
New requests carry typography selection and its nullable plan pin. Old request
bodies may replay existing intents before live reads; v1 records remain readable
history. New revalidation requires the exact current generation policy/runtime;
there is no compatibility exception. Options and results expose catalogue-derived
metadata and source-derived navigation/typography for later delivery decisions.
All outputs remain held; this adds no delivery, download or library writer.

The review interface adds explicit stylesheet choices with bounded samples,
pinned requests, in-place reload after pin drift, per-operation results and
history summaries, and a byte-identical statement only from preservation proof.
No device rendering, real-library survey, hosted-image verification or
installed-service activation is claimed.

## L058: reuse before building

Librarium merges BL Catalog and Library Finish; Library Finish stopped at its
1.28.0 release so its work could move here. Before creating any capability,
check in this order and build only what remains:

1. BL Catalog and Library Finish: their code, decisions, plans, lab results and
   Library Finish's changeover list of fixes still to carry over.
2. Maintained open-source projects, including the pinned Calibre runtime's own
   modules. Borrow or adopt under a compatible licence; running a tool as a
   separate process is preferred over copying code whose licence does not fit.
3. New code, for what neither provides.

This is a reuse check, not an approval gate: development continues autonomously
within it. Briefs and pull requests state what was checked, what was reused and
why anything was built new.

## L059: source-derived LF structural repairs

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

Reuse LF revision `72bdf39`'s `bin/epub_content.py` rules from `kindle_fixes`, `_markup_fixes` and
`_normalize_structure`, checked with `services/bookindex/app/file_repair.py` and
`tests/kindle_ready_epubcheck_test.py`. The existing contents planner, anchor
insertion, timestamp handling, EPUBCheck and complete document-text proof remain
the foundation. Adapt the narrow lexical edits rather than vendoring LF's writer,
intake, HTML parser or broader content removal rules. BL Catalog owns bibliographic
resolution and supplies no equivalent EPUB repair path.

Advance inspection to v9; retain v8 as readable historical evidence.
Accept HTML5 `<!DOCTYPE html>` and the canonical XHTML 1.0 Strict, Transitional,
Frameset and XHTML 1.1 public/system identifier pairs. Never load their DTDs.
Refuse internal subsets, entity declarations, parameter entities and all other
DOCTYPEs before parsing document content, including across XML encodings.
HTML4 named character references use Python's fixed local table and are reported
as findings; corrected output writes numeric references. Unknown names still fail.
Comments, processing instructions and CDATA retain their literal bytes.

A local XHTML hyperlink to an absent resource is a warning, regardless of its
filename extension, and can lose only its `href`; its words and markup stay. Required images,
stylesheets, manifest resources and unsupported navigation remain refusals.
Align an existing or missing NCX `dtb:uid` with the package's selected identifier;
ambiguous identifier structures do not qualify for navigation replacement.
Housekeeping also normalizes EPUB 3 XHTML DOCTYPEs, replaces conversion-path/PDF
page titles with the source package title, removes empty guides and adds missing
EPUB 3 SVG manifest flags. Existing EPUB 3 modification-date handling is reused.

| Operation | L055/L057 delivery kind | Review and proof |
|---|---|---|
| `source_repairs` (links, character references, NCX and housekeeping) | source-derived | Disclosed automatic housekeeping; recomputed lexical deltas and complete ordered story-text equality |
| Selected title/creators | catalogue-derived | Existing current identity requirements |
| Selected navigation/typography | source-derived | Existing source plans and preservation checks |

Repair-only requests can generate a held copy. Reports retain v2 compatibility
with earlier records and add the closed `source_repairs` kind/status. Delivery
uses its own kind table, retains unknown-operation holds and applies catalogue
identity requirements to any mixed metadata change. No writer, import, library
mutation or deployment authority changes. Preservation recomputes repairs from
source bytes and pinned inspection evidence, rather than trusting the generator's
edit report; it shares the lexical rules with generation. EPUBCheck 5.4.0 must
validate actual corrected bytes before delivery can proceed. A passed structural
inspection alone establishes neither EPUB conformance nor readiness.

## L060: delivery through the owning Calibre content server

Status update (2026-11-22): [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) removed this decision's orchestration (web approval, dispatcher, routes and worker). The writer core it describes remains, unreached by the application, pending a later owner decision.

Keep L055's delivery core: reviewed approvals, operation holds, retained originals
and outputs, persist-before-send journal, verified receipts, observation-only
reconciliation and guarded Undo. Replace its operational cache owner with a
content-server adapter. The launcher never opens the library database or takes
Calibre's program lock. The historical native adapter remains a synthetic test
oracle, unreachable through the writer launcher.

L058 reuse check: adapt Library Finish's calibre-bridge `replace_book`,
`undo_replace` and `reconcile_replacement` added_formats route, retained-copy and
pause pattern. Its `snapshot` and `backup_ready` checks informed the boundary;
Librarium keeps its digest artifacts and does not import LF's deployment paths
or claim a coordinated backup from a remote read. BL Catalog's Calibre plugin
contributes compare-before-write, undo-last and fsynced-evidence patterns.
Librarium's existing full-synchronous journal already supplies durable evidence.
The cancelled safe-open work is unnecessary because the server owns the cache.

Use `/cdb/set-fields` with exactly one EPUB in `added_formats`. Immediately
before send and after reply, fetch actual stored bytes through the read-only
`/cdb/cmd/export/0` command, checking library UUID, book ID and book UUID. The
normal `/get/epub` route rewrites download metadata and cannot prove exact bytes.
Use the existing maintained MessagePack dependency for binary export responses.

Calibre 9.17.0 [set-fields](https://github.com/kovidgoyal/calibre/blob/v9.17.0/src/calibre/srv/cdb.py)
calls `add_format` with the default `run_hooks=True` in
[cache.py](https://github.com/kovidgoyal/calibre/blob/v9.17.0/src/calibre/db/cache.py).
Import and post-import file-type plugins therefore run. Changed EPUB bytes,
identity or observed authored metadata fail verification. Calibre-derived page
counts, format sizes and modification times may update asynchronously and are
excluded from the metadata digest; all other exposed fields remain bound.
No plugin-disable claim applies to this transport; later asynchronous changes remain a supervision constraint.

There is no server-side atomic digest precondition. Every approval binds a fresh
protected operator confirmation that all other library writers are stopped,
with principal HMAC, confirmation time, exact target and single-use session UUID.
One book per session/action; Undo requires a new confirmation and exactly the
delivered bytes still present. Review expiry, writer identity and supervision
are rechecked before send intent and after the final observation immediately
before replacement. Expiry during preflight seals a durable not-applied result
while consuming the operation and session; it cannot authorize a later resend.
Librarium gains no shell or container access.
A mismatch, uncertain send, server failure after send intent or unreconciled
restart latches a durable global hold. A refusal before send intent (changed
source, unavailable format) writes nothing and stays with its own request, so an
unauthenticated pre-send answer cannot pause every target. Successful reconciliation never clears
that hold. Recovery release requires a separately reviewed offline procedure;
this implementation exposes no automatic reset. Never resend under a new key.
Retain originals, outputs, sessions and evidence indefinitely.

Authentication uses a protected credential file or environment, with HTTP Digest
challenges; Basic is answered only over HTTPS. Credentials are mandatory and the password must
be a generated secret of at least 32 characters (Digest still allows offline
guessing by a port squatter); the writer refuses a server that answers an
unauthenticated request, since an open writable
server would let any local process bypass Librarium's approvals. HTTP is restricted to literal
loopback; other destinations require HTTPS. Redirects and environment proxies are disabled. Server responses
are bounded; credentials and remote error bodies are never logged or returned.
Remote read-back proves observed bytes, not server fsync, disk capacity, exclusion
of arbitrary clients or backup completeness. Synthetic real-server proofs cover
byte fences, plugin transformation, lost reply, death during format copy and Undo.

## L061: Library Finish contents rebuild and text-empty pages

Status update: its generation part is superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22, and the contents planner it introduced is removed under L091 on 2026-11-23 (inspection v11; the stored v10 plans and observations stay readable history).

Reuse (L058): LF revision `72bdf39` `bin/epub_content.py` contents rebuild (KC
candidates, gap filling, stubs, levels, nesting and omnibus books; `_contents_plan`
keep, rebuild and refuse; the KCa/KCb rules of D086-D088), its synthetic
`tests/contents_rebuild_test.py` cases and `scripts/kindle_lab.py`'s library report
as the acceptance reference. The rules are copied and adapted, not imported. BL
Catalog has no contents planner. Supersedes L031's v1 rules for new inspections;
v1 plans stay readable.

Advance inspection to v10; v9 remains readable history. Content evidence v2 and
document text v2 record a text-empty spine document, such as an image-only or blank
page, as a zero-character row with the empty-text digest and count it in
`empty_spine_documents`, instead of refusing the whole capture. A spine with no text,
and unreadable or unsupported documents, still refuse. Empty pages stay in the
resource hash, and preservation still compares every row, so a page that gains or
loses text fails. Duplicate document comparison skips text-empty rows.

`librarium.contents-plan.v2` applies LF's rules to bounded observations: headings
plus short title-like lines (styled chapter lines, bare numbers, numbered titles,
story titles over bylines, part subtitles), per-page store, backlist, copyright and
OCR signals, and heading id and link flags. Prose is never recorded. The plan keeps
LF's keep tests (clean own list, far-shorter or too-short rebuild), refusals (too few
or unlinkable headings, unsettled numbering, a section that missed its chapters, OCR
scans) and short-book fallbacks (printed contents, one entry named by the title).
Plans add `measures` and up to three rule `problems`. A heading LF would demote as
prose is read as a paragraph; its markup is not edited.

Kept from Librarium: the source-bound plan with exact positions, the 2,048-entry and
eight-level limits, the sandboxed inspection child, budget order (observations yield
to structure, the plan and document text), held corrected copies, EPUBCheck and
preservation. A heading within 50 words of its file's start links to that start, as
in LF. A deeper heading without an id is `requires_anchor`: an id is added only to
an h1-h6, p, div, b or strong start tag with no id attribute (an empty one still
blocks), and the output must match the byte splice and complete document text (KCa).
A rebuild equal to the book's own list is `keep/existing_matches_rebuild`.

Not reproduced: LF's library-wide author names, so anthology bylines that only the
library knows stay headings; LF's Calibre title for a single-story entry (the
package title is used); LF's store-page removal and stub deletion before planning,
approximated by front-page skips and stub exclusion; and LF's oversized-section
measure from the top of a file for newly anchored chapters (Librarium measures from
the heading). Empty or missing navigation failed inspection at this decision;
L063 subsequently admits qualifying empty-navigation rebuilds.

Acceptance oracle, 2026-10-31: a read-only pass ran every library EPUB within the
archive limit through the sandboxed inspection and eligibility children (no metadata
database opened, no book bytes written) and paired each book with LF's lab report. Where LF rebuilt and
Librarium's inspection passes, 99.6% of decisions agree: a proposal, or a rebuild
equal to the book's own list. Where both rebuild, 99.7% of entry counts and 99.2% of
ordered label lists match. Every LF keep that passes inspection is kept for the same
reason, and 93% of such LF refusals are held for the same reason. Text-empty pages
occur in most books; recorded document text rose from under 1% to 89% of inspected
books, and replacement became available for 45% of LF's rebuilds (none before). The
largest remaining gap is proposals blocked only by empty navigation (5% of LF's
rebuilds). Per-book detail stays private.

This decision changes no writer, import, library record, deployment or release.
A proposal is not readiness: generated copies stay held for EPUBCheck, preservation
and delivery approval.

## L062: PostgreSQL guards and a separate runtime login

Adopt PostgreSQL built-ins from the L058 capability-5 reuse check. BL Catalog's
SQLite evidence store and Library Finish's retained-copy/receipt pattern do not
provide PostgreSQL role isolation. Retain migration 0009's row guards, enable them
ALWAYS, and add BEFORE TRUNCATE statement guards, also ALWAYS. No Django trigger
package is needed; the assessed django-pgtrigger/pghistory releases do not support
the pinned Django 6.1 line.

Migration 0010 protects DeliveryIntent, DeliveryApproval, DeliveryTargetBinding,
DeliveryEvent, DeliveryReceipt and UndoIntent. DeliveryEvent carries outcome
observations; supervised-session confirmations live inside the immutable
approval/intent payloads, with no separate PostgreSQL session table. Protect the
mutable DeliveryState reservation projection from TRUNCATE too. The independent
SQLite broker operations/events/consumed-session ledger remains under its existing
SQLite boundary.

A dedicated runtime login owns no objects, belongs to no other role and has no
elevated attributes. The owner-run provision_runtime_role command grants only
SELECT/INSERT on evidence, ordinary DML on mutable application tables and SELECT
on migration/content-type/maintenance records. It removes PUBLIC DDL, temporary
object, table, sequence and function privileges within the owned database/schema.
Unknown tables refuse provisioning until their access is reviewed; future tables
receive no automatic runtime grants. Runtime cannot TRUNCATE, create triggers,
alter/drop tables, become the owner or SET session_replication_role. Migration
credentials stay outside runtime processes. Unset runtime overrides preserve
single-login development.

Owners retain PostgreSQL's inherent DDL authority. An approved maintenance action
must record its reason, affected tables and transaction identity in the new
append-only maintenance table, disable only the needed TRUNCATE guards, perform
the approved operation and restore ENABLE ALWAYS inside one transaction. There
is no runtime flag, custom session setting or guard function that bypasses this
protection. Migration reversal is refused; preserve history and fix forward.
This is an operational maintenance contract, not tamper-proof auditing against a
malicious owner or superuser. Retention under L055 still applies.

Django TransactionTestCase and pytest transactional cleanup use TRUNCATE. Only
test_settings selects a backend that disables/restores the TRUNCATE guards inside
atomic flush, restricted to the configured test database. It leaves row guards
active and installs the production migration unchanged. A failed flush rolls
back guard disabling; production flush still refuses. This tests the real guards
without weakening migration installation through a test-only migration switch.

See [development](development.md#delivery-evidence-database-guards) for maintenance
and test procedures and [packaging](packaging.md#schema-0010-and-runtime-database-credentials)
for credential separation. PostgreSQL documents
[statement-level TRUNCATE triggers](https://www.postgresql.org/docs/current/sql-createtrigger.html)
and [ENABLE ALWAYS and owner-only ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html).

## L063: validated rebuilds for empty navigation

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired. The planner whose proposal downgraded `empty_navigation` is removed on 2026-11-23 (inspection v11): the finding is an error again and fails the structural check.

Reuse (L058): Library Finish's `bin/epub_content.py` `_contents_plan` rebuilds
an empty list from source headings, printed contents or a short story's start
under D086-D088. L061 already ports those rules and NAV/NCX generation; BL Catalog
has no navigation writer. Reuse that planner, lexical writer and preservation
proof, with L059's structure-to-correctable-finding pattern. No new rebuilding
engine or dependency is needed.

After complete, untruncated inspection, `empty_navigation` becomes a warning only
when no other structural error remains and the planner proposes non-empty
replacement entries. This retains the source text evidence needed for correction
preparation. Without a proposal the defect stays an error, the plan stays held
with its reason, and replacement is unavailable. Other structural refusals,
archive/XML limits and the correction container/navigation gates still apply.
A warning still marks the existing list as unsound; a populated NAV cannot hide
an empty NCX, or vice versa. Budget-triggered replanning rechecks admission.

The existing writer replaces EPUB 3 NAV and existing NCX, or EPUB 2 NCX, as
appropriate. Output structure validation independently rejects any remaining
`empty_navigation` finding. EPUBCheck on actual output and the existing logical
member, authorized XML-delta and complete ordered document-text proof remain
required. Synthetic regressions cover both navigation formats, missing heading
ids, mixed populated/empty lists, held sources and text tampering. Real-library
comparison is read-only, EPUB-only and parsed through sandboxed children;
per-book evidence stays private.

Keep inspection v10: finding severity changes, but no report fields, plan shape,
text evidence or capture contract change. Saved v10 failures remain readable as
recorded; no historical evidence is rewritten. Navigation remains source-derived
for delivery holds. Metadata selections retain their own classification, and
writer approval, library ownership and deployment boundaries do not change.

## L064: Source-derived generation repairs

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

Apply L058 reuse to Library Finish's package timestamp normalization and NCX
first-occurrence target numbering (`bin/epub_content.py`). A selected correction
may replace one simple EPUB 3 `dcterms:modified` value carrying the legacy
`scheme="dcterms:W3CDTF"` attribute, removing that attribute. Duplicate timestamps,
unknown schemes, children and other attributes still refuse. Independent
preservation proves the timestamp value and exact attribute removal.

Simple, unqualified package metadata with exactly `name` and `content` attributes
and no children receives the OPF namespace when its text is empty or repeats
the exact `content` value. Redundant text is removed only when that attribute
retains the value byte for byte; conflicting text remains untouched. This narrows
LF's namespace repair without dropping distinct metadata values. Only plain text
qualifies for removal; comments, processing instructions and CDATA stay intact.

NCX housekeeping repairs declared `playOrder` numbers by resolved target in
first occurrence order across navMap, pageList and navList. Repeated targets share
a number; an entirely absent optional sequence stays absent. Only those attributes
change; labels, links, ordering and document words remain intact. Rebuilt NCX maps emit the same numbering. Malformed or external
NCX targets receive no speculative renumbering and still face output validation.
This extends the disclosed source-derived repair-only operation, without selecting
contents replacement implicitly.

Synthetic failing-first tests cover the defects, unknown metadata refusals,
forged output rejection, repeated targets, cross-list order, sandboxed generation
and preservation, and actual EPUBCheck 5.4.0. Runtime source fingerprints change
with these rules; earlier saved evidence remains readable, while launching a new
validation still requires its exact generator runtime. No report schema changes.
EPUBCheck, ordered document-text proof and delivery holds remain required.

## L065: Bounded repairs for held EPUBCheck defects

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

Reuse (L058): Library Finish's `bin/epub_content.py` `_normalize_structure` and
`_markup_fixes` supply the package and XHTML rules. BL Catalog provides no EPUB
repair writer. Extend the existing lexical source-repair operation and independent
preservation proof; no new dependency or alternate generator is needed.

Remove only empty, attribute-free `dc:coverage`, `dc:relation` and `dc:source`
children of package metadata. Preserve comments, processing instructions, CDATA,
referenced elements and every nonempty value. Conflicting legacy metadata values
remain unchanged. Encode spaces in package item/guide URLs without double-encoding
existing escapes. Declare LF's Calibre vocabulary URI only for EPUB 3 properties
that use that undeclared prefix; preserve existing declarations.

Add an empty `alt` attribute only to XHTML images lacking one. In EPUB 2, wrap
blockquote contents requiring a block container in one XHTML `div`, preserving
all inner bytes, including empty contents and annotations. Existing alternatives,
valid block containers and EPUB 3 quotes remain unchanged. Resource bytes and
navigation selections remain intact. No image replacement, metadata-value loss
or implicit contents replacement is authorized by these repairs.

The existing source-derived operation classification, generator runtime binding,
actual EPUBCheck policy, complete ordered document-text comparison and independent
rederivation of allowed byte deltas remain mandatory. Synthetic failing-first
fixtures cover checker failures, preservation, forged text and protected metadata.
The checker policy advances to `librarium.epub-validation.v2`. Its per-file
scratch ceiling is 8 MiB, matching the inspection member ceiling, so Java ImageIO
can cache valid images larger than the separate 1 MiB report ceiling. The parent
still admits report JSON at 1 MiB and logs at 64 KiB. Filesystem/network isolation,
heap, CPU and time limits remain active. A valid synthetic PNG larger than 1 MiB
reproduces the former false `PKG-021` failure and passes under the revised limit.
Historical reports keep their captured policy; new checks require the current
profile. Report schema and inspection policy are unchanged. Original files, delivery approval,
writer boundaries and the installed application remain unchanged.

## L066: repair proven printed-line paragraphs in held EPUBs

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

Reuse (L058): Library Finish planned paragraph unwrapping as K2 task 3, with a
whitespace-folded word check, but did not implement it. Its conversion assessments
show why whole-book reconversion is unsuitable for word preservation. BL Catalog
has no content-repair engine. Calibre's maintained
[heuristic processing](https://github.com/kovidgoyal/calibre/blob/v9.17.0/manual/conversion.rst)
provides line-length and punctuation prior art. Adopt those ideas, not GPL source
code; Librarium had no selected repository licence at the time. The maintained
[EbookLib API](https://github.com/aerkalov/ebooklib) provides EPUB manipulation,
but no ready paragraph-unwrapping primitive with this preservation contract.
Reuse Librarium's archive, lexical XML, correction planning and child sandbox.

Offer a separate, opt-in correction for adjacent sibling paragraphs with repeated
positional styles and incomplete printed lines. Generator metadata alone grants
nothing. Evidence is bounded to 512 spine documents and 4 MiB of document bytes;
plans contain positions and counts, never prose. Admit only understood flat class
styles, and reuse the dominant long, complete body-paragraph class already used
by that book, with verified neutral alignment and horizontal margins. An otherwise
eligible book without that class stays held. No stylesheet or inline style is added. Source block classes may contain only
block display, margin, alignment and indent declarations; italic, hidden and other
semantic styles remain separate. Heading checks inspect each inline class token.
Documents with embedded/inline style or RTL evidence are excluded from repair.

Stop at headings, images, tables, lists, quotes, scene separators, document
boundaries, numbered clauses and hyphen ends. Numbered clauses may absorb only
their own continuation lines. Require at least three lines, or two for a numbered
clause, and a complete final sentence. Preserve literal hyphens; do not guess
whether they are discretionary. Keep all inline markup and characters. Move IDs
from absorbed paragraphs, including empty page-anchor paragraphs, to empty inline
spans at the corresponding text position. Retain first-paragraph IDs. No paragraph
language or unrecognised attributes may be discarded.

Sentence endings normally stop a run. A join across one additionally requires a
unique paragraph-start class demonstrated after at least two preceding complete
paragraphs in the same sibling group, no conflicting uses after incomplete lines,
that marker at the run's start and absent on the next positional line, and a
previous-line length between 85% and 125% of the group's median incomplete line.
This rule uses no introduction-specific text. Count and disclose these joins
separately. Short or ambiguous sentence-final paragraphs remain separate.

The new source-bound paragraph plan is v1. Correction options and captures advance
to v3; v1/v2 captures and historical generation/validation reports remain readable.
Inspection stays v10 because no inspection schema changes. Generation report v2
and preservation v2 gain the optional selected paragraph operation; source/runtime
fingerprints change, so old runtime captures cannot launch new validation. No
compatibility allowlist bypass is added.

Generation rederives the plan and verifies its exact pin. Preservation independently
rederives it from the original, checks exact lexical deltas alongside existing
operations, and constructs the expected merged tree separately from the lexical
writer. It verifies inline attributes/structure, every original ID, folded
characters, and complete ordered document text. A synthetic shared-writer bug
must fail this separate tree proof. Output reinspection and actual EPUBCheck remain
mandatory. This proves preservation and allowed structure, not reader rendering.

Starting a shared-document introduction on a separate screen is deferred: the
existing correction mechanism adds no suitable page-break style. No document split,
new CSS, library write, deployment or writer activation is included.

## L067: verified recovery baselines before delivery

Status update (2026-11-22): [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) removed this decision's orchestration (web approval, dispatcher, routes and worker). The writer core it describes remains, unreached by the application, pending a later owner decision.

Continue supervised single-book delivery with LF's `backup_ready` gate. Reuse
Librarium's immutable originals, outputs, validation/evidence artifacts and broker
journal, and existing PostgreSQL dump/restore tools for the stopped-fixture
rehearsal. Add no backup controller, duplicate book-copy writer or hold-release
procedure.

New content-server delivery and Undo require a protected verified baseline tied
to the exact library, journal and supervised session. Bind manifest, component
evidence and immutable journal cursor; refuse missing, altered or incomplete
evidence. Full inventory hashing belongs to offline verification; runtime checks
selected evidence and required artifacts. Verification precedes fresh operator
confirmation, with existing review/session deadlines and no arbitrary age rule.

Persist and fsync an immutable operation recovery manifest before send intent.
Recheck admission, saved bindings and authority before replacement. Pre-intent
refusals send nothing; post-intent failures retain uncertainty. Historical replay
and reconciliation need no fresh baseline and cannot resend or clear a hold.
Preserve all existing indefinite retention.

The [recovery contract](delivery-recovery.md) separates verified bytes from
operator-confirmed coordination, actual isolated restore evidence and unproven
physical durability/currency. Synthetic restore proves retained receipts, exact
keys, originals and a fresh writer epoch in separate state. No live backup,
library mutation, deployment, account feature or service restart is activated.

## L068: source-bound literal hyphens and scoped paragraph repair

Status update: Superseded by [L091](#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them) on 2026-11-22: correction and corrected-copy generation are retired.

Extend L066's existing planner/writer/tree proof rather than adding a conversion
engine. Paragraph-plan v2 binds each boundary's original offsets, separator and
reason. Admit only clear ASCII letter-hyphen/letter joins inside a proven run;
retain the hyphen and remove only proven XML boundary whitespace, including around
empty page anchors. Keep unknown whitespace, discretionary hyphens, dashes,
quotations, headings, lists and document boundaries held.

Closed numbered clauses may contain short lowercase interior continuation
fragments when at least two long fragments establish the run. Complete sentence
or semicolon/and-or endings close it; distinct numbered starts stay separate.
Unsupported or unresolved stylesheets hold affected documents. Identical flat
rules can agree; ambiguous cascade, semantic, inline/embedded and RTL styles stay
held. Disclose removed breaks, sentence joins, literal-hyphen joins, numbered-clause
joins and changed/held document counts in choices, saved results and history.

Keep inspection text evidence unchanged. Independent tree reconstruction computes
the expected normalized text only for selected v2 document edits; actual output
must match that evidence as well as folded characters, IDs and exact allowed
member deltas. A shared lexical writer fault must fail preservation. Strict
parent/child and saved-report checks bind separators, counts and source pins.
Retain historical v1 plan/report reads while requiring the exact current generator
runtime for new validation. No compatibility bypass, delivery/recovery change,
new CSS, account flow, library write or deployment is authorized.

See [regression evidence](paragraph-boundaries.tdd.md) for reuse, checks and limits.

## L069: discover recorded author spellings within one snapshot

Reuse BLC's canonical author/alias records and the existing global ownership and
complete-credit comparison. Search recorded aliases in the reading room without
duplicating works, guessing nicknames or changing source credit spelling.
Present bounded, snapshot-bound groups with exact counts, shared-name ambiguity
and truthful missing/incompatible/invalid/truncated states. Preserve older
snapshot admission and canonical browsing when optional aliases are unusable.

Carry the chosen work/version/digest into an explicit inspected-EPUB comparison,
preserve catalogue return context and reloadable source selection, and discard
version-owned work IDs on explicit reconnect. Strict decoding rejects malformed
or mixed-pin evidence. Display groups are not identity, admission or writer
authority; full coauthor coverage and existing comparison/generation holds remain.
No new resolver, dependency, account flow or library operation is introduced.

See [regression evidence](author-aliases.tdd.md) for contracts, budgets and limits.

## L070: one reloadable preserved-book workspace

The owner clarified that catalogue and preparation form one Librarium application,
organized around a book and its task. Preserve the current visual world. Reuse
native Library capture and the existing comparison, assessment, correction, output
validation, delivery and recovery engines. Legacy compatibility remains deferred.

Resolve durable selected jobs/artifacts against one preserved inspection before
displaying results beneath its header. Refuse malformed, foreign or incompatible
relations; never infer lineage by title or select a latest global result. Project
only bounded safe recorded origin and related IDs, without raw inputs or paths.
Historical reads require no original Library mount. Delivery reads retain operator
authentication; selections confer no approval or writer authority.

Library and Reviews resume exact preserved work. Reference browsing retains the
origin and newer-input cancellation contract. Catalogue entry defaults to reference
browsing, with production controls still available as secondary operations. No
new reader, format, account feature, engine, service or activation is introduced.
See [workspace evidence](unified-book-workspace.tdd.md).

Captured assessment, assessment review and delivery-time assessment are separate
pins. A later delivery assessment must succeed against the exact source/report
and generation comparison; queued or failed review never grants delivery authority.
Pending selections retain the prior confirmed view and drafts, with new work
blocked until verification and cancellation/recovery still available. Missing
recorded Library identity and unavailable Resume rows remain explicit historical
limits rather than blocking unrelated preserved work.

## L071: bounded operator support and measured isolated recovery

Compose the durable Job model, release compatibility extraction, safe private-file
reader and existing restore assertions into a local read-only support command.
Keep anonymous health lightweight. Diagnose no writer/upstream network and expose
no books, identifiers, paths, endpoints, accounts or raw exceptions. Explicit
bounds and unknown/incomplete states belong to the report contract.

Package a deterministic source/assets build identity using the existing release
compatibility owner. A configured image digest remains a declaration; independently
observed running image identity remains unknown until a separate runtime check.
Unbuilt source has no fabricated package identity.

Retain strict source/build/compatibility-bound synthetic rehearsal evidence only
after actual isolated restore assertions pass. Measure recovery separately from
whole-harness time and disclose capture age. Reuse delivery recovery as the sole
baseline/admission owner; reporting never releases a hold or authorizes resend.
LF/BLC health/version and current carry-over decisions supply reuse context;
standard Python/Django/PostgreSQL primitives supply bounded glue without a new
engine or dependency.

[Operational support](operational-support.md) owns signals, incident/capacity
ownership, freshness limits and proposed cadence/retention. [Verification](operational-support.tdd.md)
owns measured scope and limits. Enable no recurring work. Target RTO/RPO,
capacity/owner acceptance, physical recovery and activation remain unperformed
gates; issue #28 stays open for them.

## L072: populated historical-source upgrade rehearsal

Public CI uses a manifest-pinned subset of the historical schema-0005 runtime.
It materializes that fixture from the tested commit, completes representative
work through the old engine and rehearses stopped-role capture, migrations,
historical evidence reopening and new compatible work. Keep seeded negative
pending cases distinct from genuine old-engine results.

Reuse retained LF/BLC contracts and changeover evidence, the existing initializer,
durable worker protocol, immutable artifacts, PostgreSQL dump/restore, release/build
identity and recovery receipt owners. Add transition orchestration and fixture
proof rather than another backup, job or book engine. Require affected exact-image
acceptance without weakening existing gates or duplicating beta's container caller.

Refuse incompatible worker overlap and old-image-only rollback in the rehearsal.
Do not attribute this orchestration guard to an unchanged historical application.
Restore retained pre-upgrade state into a separate old-compatible generation, keep
current evidence, and disclose post-upgrade work that the earlier recovery excludes.
Reverse migration or evidence deletion is not an accepted rollback procedure.

[The procedure](populated-upgrade.md) owns source/image labels, state sequence and
private activation-packet fields; [verification](populated-upgrade.tdd.md) owns actual
proof and limits. The sanitized baseline does not prove an original release image
or observe today's installed state. Target image/kernel/storage/capacity/custody,
access/session acceptance and human observation remain unperformed gates in issues
#25 and #26. This grants no target survey, installed update, library/service change,
account change, recurring task or release publication authority.

## L073: checked-copy download and exhaustive frontend refinement

The owner selected existing authenticated website access for downloading a checked
generated EPUB. Keep library replacement separately gated by verified operator
identity, approvals and recovery evidence. The website does not supply that identity;
explain that boundary without inventing an account flow.

Reuse the existing immutable corrected artifact store, output descriptors and strict
saved output-validation reader. A GET selects one exact output and validation UUID,
requires their recorded binding and passing structure, EPUBCheck and preservation
checks, then rechecks retained size/digest bytes. Serve only the corrected namespace,
as a no-store attachment with a neutral generated filename. The browser also bounds
the response and verifies its size/digest before handing it off. Downloads create
no delivery intent and grant no writer authority. Original-source export is outside
this change. No new package, merger or validation engine is introduced.

Frontend completion means exercising each control and evaluating the entire content
it reveals, including conditional, disabled, failure and recovery states. A screenshot
of a representative page is insufficient. Keep source checks, installed observations,
real synthetic worker journeys and mocked transport evidence distinct, with gaps
recorded per permanent control ID. Refine the existing reading-room identity and all
themes; retain technical depth through useful hierarchy and explicit raw-evidence
access. [The inventory](frontend-control-inventory.md) owns coverage;
[the findings register](frontend-findings.md) owns triage and acceptance.

## L074: foliate-js reader page with its own policy

The first in-page reader scrolled one section at a time, showed faint page controls
and closed Contents after each link. Replace its renderer with foliate-js (MIT),
vendored unchanged from a pinned commit of the maintained readest fork with its
licence and hashes (`frontend/vendor/foliate-js/README.md`). BL Catalog and Library
Finish provide no browser reader. Readium needs a streamer and permits frame scripts,
epub.js is stagnant with a past XSS advisory, and the other maintained readers are
GPL/AGPL applications rather than separable engines. Nothing is taken from the AGPL
Readest app, and the unrelated npm package named `foliate-js` is not used.

The engine runs on its own page, `/read/<id>`, because it needs inline and `blob:`
styles and `blob:` frames. Content-Security-Policy is per document, so only that
route receives the reader policy; `script-src` remains exactly `'self'` and the main
application's policy is unchanged. The policy is the barrier: engine frames share
the page's origin, and Chrome verification shows blob and srcdoc frames inherit it
and refuse inline, blob, attribute, nested-frame and `eval` script. Our fflate loader
replaces the engine's zip, PDF and other format modules, which cannot enter the
build, and removes script, handlers, active elements, unsafe URLs, `base` and
`meta http-equiv` from every document first. External links open only as http(s)
or mail links in a `noopener,noreferrer` tab.

Places keep the older section and fraction beside a CFI so places saved by the first
reader still open. Search, highlights, read-aloud and fixed-layout books are deferred.

## L075: Postgres read model of the Calibre library

The worker imports a read-only PostgreSQL model of Calibre metadata. The model binds each import to a library identity and source token. It reproduces Calibre’s ASCII case-insensitive title and series ordering. Compare book fields and ordering with the direct reader before enabling the model. Detail and file routes continue to check original files.

## L076: Storage ownership is settled before the first production release

Calibre owns the library catalogue, and its content server owns mutations. PostgreSQL owns Librarium’s reviews, evidence, jobs and rebuildable read projections. Data flows from Calibre to the read model. Require field and ordering parity, migration compatibility and rehearsed restore before removing a fallback or enabling a new writer.

## L077: GitHub orchestrates externally managed CI compute

Updated 2026-11-24 for the public repository. GitHub hosts all CI jobs on Ubuntu 24.04. The trusted policy requires workflows to declare the runner explicitly. See the [CI contract](ci.md).

## L078: CI requires the kernel sandbox it tests

Updated 2026-11-06: CI no longer skips Landlock-dependent work. A runner kernel
without Landlock ABI 3+ fails the source, container and populated-upgrade jobs
instead of reporting a pass with that coverage missing. The GitHub-hosted
runner must satisfy the same requirement. The local
`conftest.py` skip list is a development convenience only. See
[the CI contract](ci.md#kernel-sandbox-requirement).

## L079: Deployment kernel requirements

Use a deployment kernel that supports the Landlock and seccomp restrictions required by the processing roles. Verify isolation on the actual target and keep the host Docker socket inaccessible to untrusted jobs.

## L080: Required CI workflows preserve the trusted harness

Decided 2026-11-06: replace whole-workflow equality with the harness comparison
in [the CI contract](ci.md#trust-and-policy-enforcement). Requiring every parsed
workflow/job field to equal the trusted base made required-workflow edits a dead
end: PR #136 adds Landlock enforcement through run text and job env, yet the old
`ci-policy` rejects it. Required checks must pass without ruleset bypasses; the
maintainer ruled bypasses out. Equality also cannot stop candidate test code or
pytest configuration from weakening coverage.

Bind every workflow field to the trusted base except `name`, `concurrency` and
`jobs`; bind every job field except `name`, `timeout-minutes`, `env` and `steps`.
Keep the complete job-key set fixed. Job concurrency and future fields therefore
remain bound without extending a harness allow-list. Step fields are free except
action references and checkout credential persistence. A non-empty execution
step list is mandatory, but run-step hollowing is accepted and owned by
workflow-diff review. Step actions require clean local paths or full GitHub
commit pins; new action references in required jobs require pins. Malformed data
refuses, and unexpected validation errors publish a generic failure check.
Checkout matching ignores case. Existing runner/event/token,
checkout-credential and status-shadowing checks remain. Root and job harness
drift retain `required_workflow_changed` and `required_job_changed`; unpinned
step actions report `step_uses_unpinned`.

Required policy acceptance uses the Actions job check `Inspect CI policy`; `ci-policy` remains its candidate-commit summary.

The privileged policy continues executing only its trusted-base validator and
reading candidate workflows as data. This decision authorizes no ruleset,
repository-variable, runner, production or library changes. Source/container
acceptance and human review remain necessary; the harness is not a coverage
guarantee. Reuse the existing validator, parser and tests; no new CI framework
or upstream-library capability is needed.

## L081: Container acceptance follows contract changes

Decided 2026-11-06 from the CI job audit, PR #142:
retain source safety checks and the required `container` result on every PR,
select candidate-image acceptance for packaging/runtime contracts, and select
populated upgrade for migrations, compatibility and recovery. A selected upgrade
also selects the exact candidate image it consumes. Run both tiers on main
pushes, manual dispatch and beta calls with the existing image export; no nightly
schedule is added. Unrelated PR acceptance is explicitly deferred, while failed,
cancelled, missing or inconsistent selected results fail the aggregate summary.

Preserve the locked job harness through step selection and the existing `code`
output. Reuse `changed_areas.py`, its tests, existing image/rehearsal jobs and the
audit's cadence analysis; this is repository-specific orchestration, with no new
product capability to borrow from BL Catalog, Library Finish or an upstream tool.
The narrow additive-trigger policy landed in PR #146.
Raise source-quality's timeout from 20 to 30 minutes because the
parallel suite takes 16 to 25 minutes under shared-compute contention. No source
test coverage, writer workflow, beta publication, promotion, runner configuration
or production behavior changes. Actual occupancy savings remain unmeasured.

## L082: One rendered end-to-end suite earns a nightly slot

Decided 2026-11-07: delete the paragraph-repair and author-alias acceptance
helpers and browser harnesses. Keep the unified workspace pair, repair it and
propose it for the nightly tier. No workflow ran any of the six scripts. Per-PR
mounted and backend tests prove every journey the two deleted pairs assert. Their
only unique coverage was the rendered axe, overflow and touch-target matrix,
which the unified suite also runs over the workspace and catalogue. The unified
suite is the only proof of the browser-to-worker-to-EPUBCheck-to-held-delivery
journey, real reload/Back and disconnect recovery. Wiring it into a schedule is
a separate, policy-reviewed workflow PR after a repair PR makes it pass. See
[the suite review](research/orphaned-acceptance-suites-2026-11-07.md).

## L083: Worker-polled BL Catalog status for Tool health

Tool health reads a latest-good Postgres copy of BL Catalog's read-only
`/v1/status` and `/v1/covers/status` responses. The existing worker polls about
once a minute with a shared five-second request budget, a response size cap,
shape validation and an explicit field projection. Query fields and error samples
are discarded before storage; tripped reasons become short status-code phrases.
Failures keep the previous validated copy and its fetch time. After five minutes
it is shown as last heard, with a muted seal; absent or disabled data is unavailable.
Interactive requests never fetch BLC. Configuration defaults to disabled.

Reuse BLC's status contract, Librarium's worker scheduling and singleton read-model
pattern, existing snapshot comparisons and pinned local cover delivery. Added-work
art must belong to that work or an explicitly containing collection, labelled as
such; title matching cannot supply an unrelated work's cover. Optional upscaled
examples use the snapshot's derivative association and separately configured local
blobs through the same digest-checked delivery boundary. No maintained upstream
component is needed for this application-specific projection; HTTP and JSON use
the standard library. Library Finish's local pipeline-status reader and changeover
list were also checked; they provide no BLC status cache to adopt. Its retained
workflow and changeover boundaries remain unchanged. All controls stay on BLC's
own configured status-page link.

## L084: idle-worker catalogue snapshots include verified local cover bytes

Librarium consumes BLC's existing read-only snapshot listing/download and work
cover endpoints. It reuses the worker status transport, snapshot validator and
digest-bound raster reader. Library Finish's cover cache and BLC fetch adapter,
retained plans and changeover list were checked; LF's interactive lazy cache does
not supply a background, cover-complete snapshot cutover. New code coordinates
these existing contracts with standard-library streaming, flock and atomic files;
no BLC change, new image decoder or dependency is required (L058).

The disabled-by-default worker task runs bounded slices only after queued work
has been claimed. Catalogue storage owns its snapshot staging, progress journal
and separate original/upscaled stores, outside artifact custody. Web remains a
local read-only consumer. All cover digests and dimensions referenced through
`work_cover` and its derivatives must verify before an atomic `current` switch.
Keep three snapshots including the served predecessor. Explicitly opted-in worker
replica writes are the narrow exception to read-only catalogue mounts; library
and curated-reference mounts retain their existing boundaries. The worker stays
on the internal default network. Only a hardened, independently digest-pinned
HAProxy relay joins catalogue egress, forwarding to one configured TCP upstream.

The existing dashboard attention reasons carry lag, age and incomplete/failed
sync evidence; the dashboard composition is unchanged. HTTP cover endpoints can
race publication, so mismatch holds cutover and retries rather than substituting
new bytes. No cover garbage collection, publisher authentication or installed
beta change is part of Phase 1. Setup and limits live in
[development](development.md#automatic-catalogue-replica).
See the [implementation status](status/2026-11-10-catalogue-cover-sync.md).

## L085: Cover review is a read-only wall with exact catalogue suggestions

Review adds a Covers section while existing history remains reachable. The wall
reuses the cover census, shared compare-and-set skips, native metadata matcher
and pinned local catalogue cover delivery. It adds no provider search, picker,
image preparation or library writer. A suggestion requires one exact supported
work match for the same book UUID, inventory and catalogue snapshot. Ambiguous,
changed or unavailable evidence falls back to current art or an honest empty
frame with “No suggestion yet”. Current-cover previews remain read-only.
Suggestions are batched for at most 24 visible entries, sharing native metadata
and global match scans while retaining revision, inventory and catalogue pins.
Only a readable current-cover thumbnail opens the preview; large art has no
action in this slice. Polling preserves focused Skip controls.

The queue orders missing, generated, then small observations before other reasons,
across pages. Counts describe all reasons; the selected reason filters the page.
Done means a previously flagged observation now passes a later census. Initially
healthy books do not populate Done; a new problem returns a Done entry to To do.
Skips survive changed observations until explicitly removed. This observation
meaning supersedes the earlier reservation of Done for delivery receipts; it makes
no claim that Librarium saved a cover. Partial or stale checks never prove absence.

See [the implementation status](status/2026-11-11-cover-review-wall.md).

## L086: Catalogue cover choices are staged before writer approval

The owner chose the cover wall for display and one comparison modal for changes.
Local choices use the exactly matched catalogue work, retaining the original and
its verified stored derivative. Enhanced is the default only at width 1000 or
greater. Known-placeholder originals disqualify their derivatives; digest, actual
pixel dimensions, original relationship and identity evidence are all required.
Smaller safe originals remain a manual choice. Disputed or different-work/kind
candidates cannot be selected.

A confirmed choice is an append-only PreparedCover record, bound to the target,
current-cover digest or confirmed absence, catalogue pin, policy and immutable
candidate provenance. Selection uses idempotency and compare-and-set custody;
reload revalidates rather than remapping a saved artifact. Unrelated catalogue
refreshes may preserve a still-valid selection. No selection writes a cover,
authorizes delivery or completes the queue. “Selected; awaiting approval” is
status text with a secondary action. External sources, enhancement execution and
Apply remain outside this slice, without dead controls in the modal.

Image inspection starts after the short library snapshot closes. Inventory and
source evidence are checked again before returning choices or recording a selection.
Known pixel facts use a bounded process cache keyed by content and policy; every
use still verifies the bytes and current provenance. Unselectable artwork does not
start a decoder. Transient inspection failures return a retryable 503.
Wall selection labels compare the complete stored book binding and current
catalogue provenance in a page batch without decoding pixels during polling.

Reuse: native matching, pinned catalogue cover readers, the retained image-facts
decoder and evidence guards. The prior cover/preparation plans and retained
Library Finish/BL Catalog contracts were checked; no replacement source engine
or dependency is needed. See [implementation status](status/2026-11-11-cover-picker.md).

## L087: opt-in Librarium-owned web cover sources

The owner authorized web cover sources with Librarium-owned bounded internet
access. Port the retained provider, identity/ranking and image-admission rules
into Librarium, with the source commit/functions recorded in the provenance
manifest. Do not retain an LF facade or expose engine project names as UI modes.
Reuse local catalogue evidence and append-only PreparedCover selections.

Only the optional source role joins a public network. It has no database login,
library mount, writer socket or approval secrets. Web and worker remain internal;
a separate worker/source lane carries closed, bounded search/image requests.
HTTPS connects to a checked public DNS address using the original TLS hostname;
all answers and each redirect are checked. The source token stays source-side. Worker and source authenticate with a protected
shared secret; the listener binds only to the internal control address. Web keeps
its proxy alias on an internal edge network. Provider image hosts are allowlisted
per source and redirect; only pasted URLs accept other public HTTPS hosts.
The archive source uses Wayback copies, labelled "Lexicanum (archived copy)".
The original below-0.75 fallback order is superseded by the owner-approved
parallel-search refinement below.
The source role refuses live Lexicanum hosts in all lanes, including paste and
redirects. Live access needs the browser session and extension planned for PR3b;
the extension does not bypass Cloudflare. Existing catalogue Original/Enhanced
art remains available. Search egress destinations are the Apple, Google Books,
Open Library and Hardcover APIs plus Wayback; [packaging](packaging.md#optional-web-cover-sources)
owns the exact host list. Archive pacing, deadlines and Book2.jpg exclusion stay.
Pasted-image access follows the same public-only policy. Raster admission and
metadata removal reuse the isolated child boundary.

Provider progress persists independently with cancellation/lease fencing.
Candidates bind target identity, current cover and query, and remain preparatory.
No search, number key or selection writes a library cover. The feature defaults
off behind a setting and compose profile. Setup, destination scope and ingress
requirements live in [packaging](packaging.md#optional-web-cover-sources).
See [implementation status](status/2026-11-12-web-cover-sources.md).

Catalogue-first/parallel refinement (2026-11-13): the picker checks the pinned
local snapshot before offering web search. Without an exact link it can offer
bounded title/author and recorded-alias suggestions, plus recorded containment
relationships. Similarity is evidence for manual review, never an automatic
selection or a new catalogue link. Conflicting identifiers, ambiguous identity,
publication-kind mismatches and known placeholders retain their refusal rules.
The [implementation status](status/2026-11-13-catalogue-parallel-covers.md) records
verification. Exact wall suggestions remain unchanged. Catalogue absence is
reported even when web results exist; unavailable or incomplete checks cannot establish absence.

Every requested web source starts in the same leased worker attempt. Per-source
locks and host pacing remain in the source roles; completed sources checkpoint
independently with start/finish timestamps and elapsed milliseconds. Recovery
retries unfinished sources; cancellation and lease replacement fence late results.
Explicitly requested live/archive wiki lanes run alongside the other sources,
regardless of another source's score. This replaces the original sequential
weak-match scheduling rule without changing library-write authority.

PR #158 review refinement: per-actor search quotas and seven-day retention bound
disposable web evidence. Raw downloads are not retained; derivatives have their
own artifact namespace. PreparedCover references are never reclaimed, and
selection shares the retention lock. Host firewall enforcement remains a separate
approval; the local-listener container proof establishes topology only.
## L088: default-off trusted operator identity

The Librarium-owned beta mTLS ingress maps successfully verified certificates to
the stable principal `operator`. All clients admitted by that ingress share this
principal. The ingress replaces client identity input; web accepts exactly
`X-Librarium-Operator` from explicitly configured literal peer IPs, consumes it,
and supplies WSGI `REMOTE_USER`. The outer WSGI boundary discards ambient identity
and HTTP `Remote-User` on every request, including when the feature is off.
Malformed names never create a principal. A web-only empty-by-default allowlist
enables the handoff without broad subnet, wildcard or forwarded-client trust.

Reuse review covered BLC's token-gated API, LF's HTTP handlers, retained plans and
changeover list, and Librarium's principal, actor and supervised-delivery contracts.
Neither retained engine provides this WSGI ingress handoff. Gunicorn's pinned
forwarder settings do not validate bounded principal names or map the chosen
ordinary header to `REMOTE_USER`. A small standard-library WSGI adapter supplies
that boundary while reusing the existing Django API gates. nginx supplies client
certificate verification and replacement headers; no new authentication service,
dependency, user database or certificate-DN parser is introduced.

The fixed name preserves exact actor/idempotency comparisons, search quotas and
delivery supervision's `confirmed_by`/principal HMAC binding. Existing CSRF,
explicit approval, writer and evidence checks remain in force. Network isolation
and exact ingress peer provenance are prerequisites, not claims made by unit
tests. No deployment, beta/ingress change, library write or production activation
is part of this PR. Exact directive shapes and validation steps live in
[packaging](packaging.md#optional-trusted-operator-identity-for-the-beta).
See [implementation status](status/2026-11-13-trusted-operator-identity.md).

## L089: one opt-in source browser for Goodreads and current Lexicanum covers

A Librarium-owned headed Chrome runs under Xvfb in a separate default-off role.
It has an owned profile volume and its own worker request key, with no database,
library, writer or application credentials. Requests use the shared cover protocol
module's HMAC binding of method, path, time and body. Its listener binds only the
private control lane. Web and worker retain their internal networks.

Chrome keeps its namespace and Seccomp-BPF sandboxes. The pinned Docker-default
seccomp profile additionally admits namespace syscalls needed by unprivileged
Chrome; all capabilities stay dropped and no-new-privileges stays enabled.
Hosts that cannot run this combination must fail acceptance. No sandbox-disabling
flag, privileged mode, host policy change or personal profile is an alternative.
A loopback HTTPS CONNECT proxy checks every DNS answer and connects a checked
numeric address. Browser interception checks every GET and redirect against the
source's closed host/path vocabulary; page scripts and decorative resources are
disabled. Chrome still has bounded process-level egress, so this is application
transport enforcement, not a host firewall claim.

Goodreads reuses retained ISBN/title fallback, parser layouts and original-image
rules. Its replaceable six-hour query cache lives in worker-owned PostgreSQL,
with 128 rows and bounded page bytes; challenges and failures never populate it.
Explicit refresh bypasses the cache. Live Lexicanum returns current single-page,
single-revision export XML and original same-wiki artwork. The article API remains
usable by later intake work without creating intake or an Update action here.
Archived-copy Lexicanum remains a separate, honestly labelled fallback. Missing
exact live article titles may use a bounded,
GET-only Special:Search on the same allowlisted wiki, with title and author and
main-namespace results. At most two matching article links continue through the
existing current export and cover path. Search failures stay distinct from valid
empty results; cross-host links, action parameters and revision-history routes
remain refused. Search states distinguish challenge, busy, unavailable and valid
empty results.
Images retain the existing sandboxed byte admission and append-only selection
boundary, with server browser/API/archive reach methods in provenance.

See [source-browser status](status/2026-11-13-source-browser.md) and
[packaging](packaging.md#source-browser-role).

Review refinement: the manager stages the exact host-side seccomp profile beside
its stack files; disposable acceptance proves this without a checkout path.
Browser-image builds compile the copied stdlib modules with their Python 3.12.
The live Goodreads response also requires its current `m.media-amazon.com` CDN,
restricted to the Goodreads book-image prefix. Known book search/navigation
parameters are accepted; action and unknown parameters remain refused.
Multi-image beta publication and exact-byte stable promotion are a named release
follow-up before installation; this feature does not publish or activate an image.

## L090: Native reference catalogue storage and absorbed harvest controls

L026 and L058 carry BL Catalog's purposes into Librarium. This proposal covers
NEW-003 (harvest/reference storage) and NEW-004 (native controls). L088 is used by
PR #161 for trusted operator identity; L089 is used by PR #160 for the source
browser. These dependencies are separate reviews, not approvals granted here.

1. Storage ownership (NEW-003):
   PostgreSQL will own Librarium's harvest evidence, reference catalogue, queues
   and bounded caches under L076 point 2. This reference catalogue describes
   publications; it does not replace Calibre's library catalogue of record,
   L075's rebuildable library read model, or L060's content-server-only writer.
   L076's independent delivery-broker SQLite exception remains. Existing BLC
   SQLite snapshots and retained offline engines remain transitional inputs;
   this proposal does not pretend those paths have already been migrated.

   The following are logical table families adapted from BLC's
   `src/bl_catalog/db/schema.sql` at `a8f2744`, not existing Librarium PostgreSQL
   tables. Implementation migrations must choose explicit names, constraints and
   grants without colliding with library-read-model or evidence tables:
   - Harvest/evidence: `source`, `source_record`, `claim`, `harvest_log`.
     Preserve immutable record/claim content, semantic claim hashes and the
     separately mutable last-seen projection; add raw export digests separately.
   - Reference projections: `work`, `edition`, `edition_ident`, `work_ident`,
     `author`, `author_alias`, `work_author`, `series`, `work_series`, `work_alias`,
     `work_tag`, `work_contains`, `field_support`, `record_link`, `work_cover`.
     Preserve `id_anchor`, `id_alias` and publication metadata (`meta`) too;
     stable IDs and old-ID redirects must survive rebuild and import.
   - Cover state: `cover_asset`, `cover_upscale_job`, `cover_derivative`.
     Immutable raster bytes live in owned content-addressed artifact storage,
     outside images and the library mount; PostgreSQL owns their associations.
   - New intake jobs, revision observations and HTTP-cache tables are proposed
     additions. BLC's HTTP cache is file-backed, not an existing
     `harvest_http_cache` table. PR #160 separately adds `SourceBrowserPage`
     (`librarium_sourcebrowserpage`), a six-hour, 128-row Goodreads HTML cache;
     reuse its owner rather than inventing a second browser-page table.

   Web may enqueue authenticated commands and read safe job/status projections;
   workers alone publish harvest evidence and resolved reference generations.
   The browser has no database credentials. Existing runtime grants do not prove
   separate web/worker SQL privileges: implementation must extend L062's explicit
   table classification and establish/test grants before claiming that boundary.

2. Migration coexistence and precedence:
   BLC continues publishing read-only snapshots; L084's idle-worker replica
   task still verifies complete cover bytes before switching its local pointer.
   Librarium never writes back to BLC or its snapshots. Calibre-to-PostgreSQL
   library observations remain one-way under L076; native reference changes
   cannot edit a library record or imply ownership of a book.

   Proposed native generations import evidence and stable ID anchors/aliases
   from a pinned BLC baseline before accepting native revisions for those entities.
   Within a native generation, the latest accepted observation for the same source
   and page replaces that page's earlier contribution; other sources still use
   the resolver's agreement/disagreement rules. A native title or ISBN alone
   cannot override identity, conceal a conflict or replace all fields of a work.
   Unmigrated records remain from the pinned baseline. Do not merge arbitrary
   rows from a moving replica into a request or duplicate the same evidence.

   Today catalogue reads and PreparedCover bindings require a SQLite version and
   digest. Keep serving that complete pinned generation while native jobs are
   shadowed. Serving native updates requires a separately implemented generation
   adapter with atomic publication, stable IDs, equivalent search/matching/cover
   contracts and preserved historical pins. Before that adapter lands, jobs must
   distinguish stored evidence from a published update. No immediate per-row
   PostgreSQL fallback is claimed by this docs-only proposal.

   Cutover (S16/NEW-002) requires imported evidence, anchors/aliases, verified
   original/derivative bytes, source and control parity within the owner's retained
   scope, recovery rehearsal and independently reviewed differences. Freeze a
   baseline and reconcile the final delta; a title-count comparison is insufficient.
   After explicit approval, select the complete native generation, verify readers
   and retained selections, then disable the replica sync and external status poll.
   L084 and `compose.catalogue-sync.yaml` specify HAProxy for the catalogue relay;
   verify actual deployed roles before retiring it and its route under their own
   approval. Retain predecessor
   snapshots/blobs and rollback evidence while pins need them. Unmounting or
   deleting them, stopping BLC or removing services is never an automatic step.

3. Native harvest and cover controls (NEW-004):
   At an approved cutover, native queue/cycle telemetry replaces the worker-polled
   `CatalogueStatus` projection and native management jobs replace L083's external
   status-page controls. Until then L083 remains in force. Port BLC's actual
   `control.py` and `upscale_control.py` semantics: harvester start/pause/resume/end
   with replay protection, and the separately persisted upscale pause. Do not
   promise new breaker-reset or reprocess operations as existing parity. All mutations require the trusted authenticated
   operator, CSRF for browser requests, bounded inputs and idempotent jobs. L088
   in PR #161 describes the default-off ingress dependency; L060 still governs
   any library writer. User-facing copy names Librarium operations, never BL
   Catalog, BLC or Library Finish. No activation or retirement follows here.

4. Owner scope:
   CWA metadata integration (S13) is excluded by the owner's 2026-11-13 direction.
   The shared server browser is the primary Lexicanum route; the Zen/Firefox
   extension port stays parked unless challenges justify revisiting it. Neither
   is an open decision. ISBNdb (NEW-001) is retired by the maintainer's
   2026-11-13 decision: Librarium does not port the ISBNdb source or the ISBN grid
   that depends on it, and relies on keyless sources (Open Library, Google Books,
   Wikidata) instead.

5. Background work: harvest, cover preparation and prebake run on demand only
   (when a book or the review page asks for them). Library-wide recurring sweeps
   are not authorized by this decision and need their own maintainer approval.

The [Lexicanum intake design](design/lexicanum-intake.md) owns the approved jobs,
validation, source-browser contract, UI behavior and staged implementation plan.

## L091: Librarium reads and checks books and no longer repairs them

EPUB remediation is performed outside Librarium. Librarium stops producing corrected ("review") copies of books and stops delivering
them into the library. It keeps reading books and checking them (inspection, EPUBCheck
validation, comparison and assessment), and it reports problems instead of fixing them.
A bad file is named by those checks and is never rewritten.

1. Removed: the generation pipeline (lexical metadata, navigation, anchor, stylesheet
   and paragraph repairs, independent output preservation, saved-output validation and
   the corrected-output jobs and API) and the delivery orchestration that could only
   deliver a review copy (preparation, approval, dispatch, reconciliation, Undo and the
   dedicated `delivery_worker`), with their routes, settings, tests, acceptance scripts,
   the stylesheet-parser dependency and the documents that only described them.
2. Superseded by this decision: L054, L057, L059, L061 (its generation part, and from
   2026-11-23 the contents planner it introduced), L063, L064, L065, L066 and L068. L055, L060
   and L067 keep their writer core, but their orchestration (web approval, dispatcher
   and routes) is removed.
3. Deliberately left for later decisions:
   - The writer core (`delivery_broker`, `delivery_writer`, `delivery_content_server`,
     `delivery_session`, `delivery_authorization`, `delivery_client`, `delivery_recovery`,
     `delivery_native`, `recovery_evidence`, `Dockerfile.writer` and their tests) stays as
     Librarium's library-write path until the owner decides it. Nothing in the web or
     worker reaches it now.
   - The stored tables, their append-only guards, the job-kind constraints and migrations
     0008 to 0010 are unchanged: no migration, no model change, no data change on deploy.
     Old rows of the six retired job kinds, corrected-output records and delivery
     evidence remain readable history. The worker never claims or advances them, history
     lists them (`kind=retired` selects all six), and `POST /api/jobs/<id>/cancel` still
     ends one left queued or running. They carry no result, report or link.
4. Reports and release identity: new assessment reports no longer say correction
   admission is held (the stored `correction_admission`, `blockers` and `ready` fields
   keep their meaning so earlier reports still validate; removing them needs an
   assessment policy bump). The release compatibility record drops the generation,
   preservation and output-validation policy versions. The populated-upgrade and
   container receipts drop their corrected-copy and preservation assertions; the
   upgrade rehearsal proves retired history stays readable instead.
5. L058 reuse check: this change builds nothing new; it removes code and keeps the
   inspection, EPUBCheck, assessment and writer-core owners.
6. Contents planner removed (2026-11-23). Inspection advances to `librarium.epub-structure.v11`
   (v10 and earlier stay readable history). New reports carry no `contents_plan`, no
   `contents_observations`, no document `blocks` and none of the evidence only the planner
   read (word and media offsets, body counts, anchor lists, `ancestor_sources`,
   `heading_index`, heading id/link flags, per-page signals). Headings, links, source element
   indexes and counts, navigation entries with their ancestry and the findings they back stay.
   `empty_navigation` is an error again: a book with an empty table of contents fails the
   structural check and is named by that finding; nothing downgrades it. Stored v4 to v10
   reports keep their plan and observations, are served unchanged after shape and binding
   checks and are never recomputed; the report view shows no plan for any report. The planner
   still proposed rebuilds for books whose table of contents had already been rebuilt at the
   source, proposals nothing in Librarium can act on. No model change, no migration.
   L058: removal only.

## L092: license Librarium's original source under AGPL-3.0-only

The project adopts version 3 of the [GNU Affero General Public License](../LICENSE) for its original source code. Upstream components retain their respective licenses and notices.

## L093: publish public-source betas from a reviewed image pair

Build both images from the public main tip. Rehearse the populated upgrade on the
candidate runner and seal release exports to the operator’s review certificate.
After review, stage the identical image pair in private GHCR packages. The
finalization workflow checks the original run, source, configs, package visibility
and reviewed archive before publishing the prerelease. See [releases](releases.md).
