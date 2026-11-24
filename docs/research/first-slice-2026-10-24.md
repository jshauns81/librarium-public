# First application slice: collection, evidence and durable inspection

Date: 2026-10-24 (America/Chicago). Owner: Librarium. Local implementation under L007; no production architecture approval or migration-parity claim.

## Recommendation and scope

Use Django, React/TypeScript, PostgreSQL and independent Python workers for the bounded experiment. Combine collection discovery, work/edition evidence and progress in one experience; retain existing catalogue engines and library writers. Build a read-only metadata-comparison journey using explicitly fictional records at collection scale. This is enough to test interactive state, command acknowledgement and durable ownership without importing library content. It does not establish engine migration viability.

The working implementation is `backend/librarium/` plus `frontend/`. It has 5,522 synthetic works, separate edition IDs, catalogue/library title claims, an invalid-ISBN/title-disagreement fixture, and an intentional first-attempt source failure. The worker compares actual saved fixture values; it never opens books, validates EPUBs, repairs content or calls an upstream service. Four checkpoints demonstrate protocol behavior, not four production engine stages.

## Journeys and ownership

| User action / datum | Canonical owner | Librarium's role |
|---|---|---|
| Search collection; inspect a work and its editions | BLC published catalogue and versioned read API | Read projection with namespaced IDs and source version; preserve aliases/merged IDs |
| Understand source disagreement and provenance | BLC source records/claims/resolver | Display claims, observation dates and uncertainty separately from resolved values |
| Choose an actual library item | Calibre through established read boundaries | Bind library UUID, edition/work mapping, metadata fingerprint and original file hash; never equate ISBN with identity |
| Follow or cancel a requested comparison | Librarium job/intent state | Transactional intent, fenced worker ownership, durable checkpoint/result and revision |
| Prepare/repair a book | Existing Library Finish engines and per-book evidence | Later explicit adapter; preserve evidence and original content, with job semantics separate from storage reads |
| Import/replace metadata, cover or book | Calibre bridge / CWA and their existing approval contracts | No writer route in this experiment; replacement requires concrete authorization and verification |
| Continue browsing on another screen | URL for collection query/selection; server for job truth | URL restores filters, page and selected work; server returns durable progress. No cross-device preference sync is claimed |

Retain BLC harvesting, append-only evidence semantics (including `last_seen_at` currentness), identity resolution, published immutable SQLite snapshots, catalogue API and plugin/CWA consumers. PostgreSQL holds Librarium-owned state; it does not replace BLC's evidence database or Calibre's database. Retain LF content inspection/repair and writer boundaries. Adapt read contracts and user interaction; replace the polling/DOM replacement pattern and request-bound long work in Librarium. Retire neither upstream service.

## Committed evidence and source capture

`upstream/sources.json` supplies refreshed local observations and the delta from the kickoff anchors. Initial dated captures remain preserved: BLC `a8f274487f09399a6fe90f4210bb50fc0c3a0701` (`src/bl_catalog`, `integrations/calibre`) and LF `6e460de94030d2f0d96c043b751904dde6a7bcee` (`services/bookindex/app`). Independent review found LF had advanced to local `master` `4c9ed6d4686c75a388d3a87a13d821ed2d52579d`: 18 commits and 41 changed paths. A new capture includes `bin/` writer/queue owners, application code, decisions/codemap and browse tests. BLC's expanded capture also includes CWA, integration docs and tests. Captured archives remain ignored; reviewed inventories are under `upstream/manifests/`. Each inventory records repository, requested ref, resolved commit, file Git object/mode/size/SHA-256, selected paths, exclusions and archive SHA-256. These are source selections, not complete repository mirrors or live production snapshots.

`python scripts/capture_source.py REPOSITORY COMMIT NEW_DIRECTORY --include PATH` reads the committed tree/blobs without executing checkout code, imports, hooks, extraction or filters. Source-type allowlisting excludes runtime/binary/private paths; links/submodules and unsafe selectors fail. Capture fails rather than overwriting. Repeat captures compare exactly, including after dirty/untracked checkout changes. `verify()` checks archive and every member. Refresh by naming another commit and new ignored destination, reviewing inventory changes before updating anchors. Never schedule refreshes implicitly. Filename filtering cannot prove arbitrary committed code contains no secrets; inspect the selected inventory/content before sharing it. No archive is published here.

Verified source examples: BLC `src/bl_catalog/db/store.py:54` preserves historical evidence while `last_seen_at` selects the current observation; `src/bl_catalog/publish.py:128` publishes a read-only copy before atomic `current` replacement; `README.md` API section specifies `catalog_version`, `X-Catalog-Version`, and merged-ID behavior. LF anchor `services/bookindex/app/pipeline_status.py:37` performs storage aggregation on status computation; `status():130` caches but still touches storage; `pilot_control.py` separates desired state, per-book results and content-bound freshness. LF's working graph points into a nested historical checkout, so its path prefix is not the anchor tree layout; committed paths were verified with Git. Independent contract findings belong in [private engineering record](../agent-environment.md#private-context-discovery).

## Why this stack wins the experiment

| Approach | Benefit | Cost / decision |
|---|---|---|
| Django + React + PostgreSQL + independent Python workers | Transactional domain/intent model, migrations and existing Python engine fit; React preserves mounted controls while independent queries update; SQL leases avoid a second durability system | More explicit API/state work than server-rendered pages. Selected to test the hard concurrent journey; a small DB queue is an experiment, not a mature general task platform |
| Retain LF service/UI architecture wholesale | Lowest engine adaptation cost; current research jobs already demonstrate durable intents, leases and checkpoint cancellation | Does not by itself establish the combined collection/evidence interaction. Retain those contracts and useful job semantics; test a new interaction/orchestration boundary rather than implying all LF jobs need replacement |
| Django templates + HTMX | Lower JS/build complexity; good for conventional record forms | Viable for calmer pages, but collection selection, ongoing progress, reconnects and out-of-order commands still require a carefully managed client state layer. React makes that state explicit and testable for this journey |
| FastAPI + React + PostgreSQL | Good typed APIs and Python reuse | Adds separate ORM/migration/auth/domain assembly for owned relational state without a demonstrated gain for this workload. Credible if later adapters dominate and Django domain features stay unused |
| Next.js / Node backend + Python workers | Integrated frontend routing/rendering | Extra runtime and cross-language domain boundary without a current SSR/public discovery need. Node remains useful build tooling; React does not require a Node production backend |
| Celery + broker/result store | Established routing/retry/operations ecosystem for large task graphs | Extra operational and transaction-outbox boundary before this slice needs fanout. Reassess before adopting real repair/catalogue jobs; do not infer Django's Tasks API supplies a production worker |

Angular and Vue are credible UI alternatives; neither provides an automatic correctness advantage over the tested state/intent protocol. Avoid overlapping application frameworks. React's cache/mutation behavior is provided by TanStack Query rather than a handwritten generic fetch/cache framework; the small revision merge remains domain logic.

## Dated support and pin rationale

Official sources checked on 2026-10-24, with package registries used to confirm installable patch releases. Pin exact resolved dependencies in `uv.lock` and `frontend/package-lock.json`; use `uv sync --frozen` and `npm ci`.

| Component | Experiment pin / evidence | Reason and upgrade path |
|---|---|---|
| Python | 3.14.9; [release](https://www.python.org/downloads/release/python-3149/), [lifecycle](https://devguide.python.org/versions/) | Current security maintenance patch on a bugfix line through 2027, security through October 2030. Python 3.15 is newer, but Django 6.1.2's published compatibility only adds 3.15 in 6.1.3; avoid an unconfirmed combination. Move after Django/driver/tests support it |
| Django | 6.1.2; [download/support](https://www.djangoproject.com/download/), [6.1 compatibility](https://docs.djangoproject.com/en/6.1/releases/6.1/) | Current mainstream line rather than reusing archived 5.2. Mainstream through April 2027, extended through December 2027. Plan 6.2 LTS evaluation before mainstream ends; patch updates promptly. Django's [task framework](https://docs.djangoproject.com/en/6.1/topics/tasks/) does not run durable production work by itself |
| PostgreSQL | 18.6; [version policy](https://www.postgresql.org/support/versioning/), [release](https://www.postgresql.org/docs/release/18.6/) | Current stable supported major; 19 was still an RC at assessment. Supported through November 2030. Minor updates after release-note/test review; major update requires dump/restore or pg_upgrade and recovery rehearsal |
| React / React DOM | 19.3.1; [official 19.3 release](https://react.dev/blog/2026/09/09/react-19-3), npm stable tags | Current stable client UI. No React Server Components runtime. React publishes no Django-style fixed support calendar: follow official advisories, compatible patches and tested major updates |
| TypeScript | 7.0.2; [official release](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/) | Stable native typechecker, invoked as CLI independently of Vite transforms. No compiler-API-dependent plugin. Recheck plugin compatibility before adding any tool requiring the 6.x programmatic API |
| Vite / Node | 8.3.5 / 24.22.1; [Vite support](https://vite.dev/releases), [Node lifecycle](https://nodejs.org/en/about/previous-releases), [security update](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases) | Supported current Vite minor with a patched Node 24 LTS build toolchain; Node 26 current offers no needed capability. Node is build/dev only. Node 24 planned EOL April 2028; upgrade build images deliberately, follow Vite's sliding minor support policy |
| PostgreSQL driver / HTTP / static assets | psycopg 3.3.6, Gunicorn 26.2.0, WhiteNoise 6.12.0; PyPI package metadata and lock | Current installable releases, tested together. A search result suggested Gunicorn 26.2.2, but the registry had no such release; selected confirmed 26.2.0. Patch via lock refresh plus API/security/build checks |
| Query/test/style tooling | TanStack Query 5.104.5, Vitest 5.0.5, exact formatter/type packages in npm lock | Current stable compatible tools. Initial Vitest 4.1.0 had audit findings; replaced before delivery. No frontend utility framework or second UI framework |
| Typefaces | Literata via Fontsource 5.3.0; [upstream OFL-1.1](https://github.com/googlefonts/literata) | Self-hosted variable serif for work/display titles, platform sans for controls. Font assets have `font-display: swap`; preserve package license in distributed assets |

Local toolchain installation is isolated under ignored `.local/toolchain/`.
The official `node-v24.22.1-linux-x64.tar.xz` SHA-256 was
`6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6`;
`postgresql-18.6.tar.bz2` was
`555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f`.
Both matched their publishers' checksum files. PostgreSQL was built unprivileged
with `--without-icu --without-readline --without-zlib` for this Unix-only instance;
Debian Bison/Flex/m4 packages were extracted locally as build prerequisites.
No system packages or host Python/global agent installations were replaced.
System Python 3.13.5 is not the application runtime.

## Job and interaction contract

`POST /api/jobs` accepts one work and a UUID idempotency key. Enqueue commits an immutable input/version/fingerprint before acknowledgement; it does no comparison work. The same key/work returns the same job; reuse for another work fails; a second active intent for the same work fails. Browser retains an unconfirmed request key across reload in local storage and clears it after a POST acknowledgement or a matching request reference observed through polling. There is no automatic retry of a potentially consequential new intent.

Independent workers claim rows with `SELECT FOR UPDATE SKIP LOCKED`, checkpoint progress in PostgreSQL, and renew ten-second leases. Each ownership generation gets a new UUID token; expired/replaced tokens cannot write. An expired lease resumes its checkpoint, with a three-claim limit and explicit failure after repeated crashes. This is at-least-once execution with fenced publication, not exactly-once side effects. Synthetic comparisons are safe to repeat. Before real engines are connected, each adapter needs durable idempotency, bounded external call timeouts, cancellation checkpoints and any transactional outbox it requires.

Cancellation commits a terminal state and invalidates the lease under the same row lock. It cannot undo external effects and no external writer exists here. Result writes and cancel serialize; if work already completed, the endpoint returns that actual terminal state. This immediate fenced cancellation is safe for pure fixture comparisons; real engine adapters require cooperative acknowledgement and must retain uncertain outcomes. Every changed job increments its revision. Browser revision merging refuses older responses and preserves mounted form controls. Query keys and combined cancellation/deadline signals isolate searches and bound every read to five seconds; URL carries filters/page/selection. An interrupted connection retains cached content and explains recovery. Explicit refresh always refetches. Reads return every active inspection, the thirty newest terminal records, and the selected work's latest result even outside that history window. Large active queues still need pagination/backpressure before production.

## Response to independent upstream findings

H1: every experiment result binds an immutable source version and input hash. A real BLC adapter must additionally pin one version across requests, treat author/series IDs as version-scoped, follow stable work/edition aliases, and make catalogue refresh explicit. H2: no published catalogue snapshot is downloaded here; a future reader must check embedded version/schema/SQLite integrity and distinguish its own byte hash from publisher authentication. The API's historical-version header is insufficient evidence. H3: this experiment holds no LF base URL, bridge socket, credential or writer capability; a future GET-only adapter needs a route/method allowlist tested independently of LF's Origin guard.

M1 to M5 remain explicit adapter requirements: derived/unconfirmed ownership, API-computed flags absent from raw snapshots, schema-contract tests against committed real definitions, checkpoint-aware cancellation, and verified/refused/uncertain writer outcomes. None is represented as a completed integration. M6/M7 are addressed by refreshed LF provenance/delta and expanded source captures including the missing contract owners. LF's D084 to D086/undo-replace and browse changes remain LF-owned; no writer exception transfers to Librarium. There is no unresolved objection to the synthetic experiment boundary; real integration acceptance remains open.

Observability: worker logs job ID/attempt/checkpoint/revision/state, and HTTP access logs record request duration in microseconds without fixture payloads. Inspection record exposes source version, input fingerprint, revision and last update. No fabricated percentage, ETA, quality score or confidence is displayed. Progress records completed, persisted comparison steps; worker recovery is observable in attempt count.

## Acceptance, rollback and limits

Pre-build criteria and visual direction live in [the surface brief](../design/collection.md). Final executed commands/results belong in the [private engineering record](../agent-environment.md#private-context-discovery), including RED/GREEN checkpoints, HTTP/interaction measurements, desktop/phone/failure checks and independent review dispositions.

Revert experiment source to a prior local checkpoint to retire it; retain its isolated PostgreSQL data directory for inspection rather than deleting it. The initial migration has a reversible empty-schema path, but reverting a migration containing retained jobs is destructive and is not the ordinary rollback. Releases must keep backward-compatible schema/worker semantics, test dump/restore and migration recovery, and keep state outside images. Container builds, image digests, production authentication, backup/restore and Dockhand/fresh-host acceptance require actual evidence before release. No deployment is authorized by this assessment.

No real upstream integration, production/libraries, Kindle delivery, engine equivalence, real-device keyboard, screen-reader study or load claim is established. A collection of generated titles cannot prove search semantics or disambiguation against actual catalogue diversity. Next slice should introduce one reviewed versioned read adapter and contract fixtures, then execute real engine evaluation in a separately approved data boundary. Reassess the job substrate before real repairs, fanout or multi-user authorization.

## Response to implementation review

The independent [private engineering record](../agent-environment.md#private-context-discovery) reproduced
reachable defects rather than relying only on passing initial tests. The parent
addressed the local experiment's findings as follows; a fresh verdict checks the
final implementation rather than granting production acceptance.

| Finding | Response and evidence |
|---|---|
| H1, stalled reads | Every fetch combines caller cancellation with a five-second deadline. Polls retry after interruption; Refresh always settles; a stale-poll indicator also detects missing updates without calling a paused tab a connection failure. Failed session reads recover automatically alongside progress polls. Mounted component tests stall progress alone and both progress/session reads, check interruption/Refresh, restore polling and resume a paused tab. |
| H2, lost-response replay | Job JSON includes its request reference. Polling clears only a matching persisted key; one subsequent Inspect again creates a fresh intent. Component tests simulate a committed job whose POST response was lost before or after polling confirmed it; a late transport error cannot revoke that durable confirmation. An older response also cannot clear a newer stored key. |
| H3, cancel/completion race | Actual terminal state drives acknowledgement; mounted test verifies completion wins without a false cancellation notice. |
| M1, control characters | Bounded text validation rejects NUL/control/surrogate characters with JSON 400 before PostgreSQL; tests cover all five inputs. HTTP errors retain status and their message instead of claiming transport failure. |
| M2, checkpoint claims | Source binding, title finding and ISBN finding are persisted at their own checkpoints. Recovery test crashes after title comparison and forbids recomputing that finding while completing the remaining stages. |
| M3, short desktop | The accepted visual correction uses a focused detail page below 680 px height. Back restores exact list position and row focus. Independent visual R3 checked 1366x650, tablet and phone; the list is not left beside an off-screen panel. |
| M4, Back history | Marked list/detail entries let in-app Back use browser history; popstate restores row focus/scroll. Direct-link close replaces the current entry. Mounted journey verifies a following system Back reaches the preceding list state. |
| M5, integration checks | Default npm tests mount the actual App with fetch stubs for stalled reads, request reconciliation, cancellation race, error focus, delayed selection/search, Back/history and semantic axe. API cancellation/error tests and PostgreSQL series/409/WSGI checks supplement them. Coverage includes App and API, with a separate state-module gate. |
| L1, L2, fingerprints/labels | Fixture failure control has its own model field and is excluded from new input hashes. Row/collection/detail provenance comes from record data; tests change a version and compare retry fingerprints. Historical results keep their original input hashes. |
| L3, focus/errors | Settle restores the originating control only when the user has not moved to another view/control. Route changes clear errors. A current-route reference also prevents delayed failures leaking into a newer selection; both start and cancel failure paths have mounted tests. |
| L4, worker edges | Exhausted leases are cleared while claiming the next ready job; continuous workers retry database interruptions. Lease deadlines use PostgreSQL time. A held-row-lock test proves skip-locked behavior deterministically. |
| L5, headers/key | One outer WSGI wrapper applies CSP/frame/referrer/nosniff headers to static and API responses and validates Host. Non-test settings require an explicit random key; tests cover static/API headers and missing-key refusal. Only loopback-HTTP HTTPS warnings remain. |
| L6, LAN context | LAN access remains unsupported. HTTPS, reviewed host/CSRF settings and authentication are explicit release prerequisites; no plain-HTTP LAN compatibility is claimed. |
| L7, package/log | Access logs include duration_us; runtime context excludes backend tests. Web restart/healthcheck are defined. Docker remains unavailable, so shared-image build behavior is unverified. |
| L8, hygiene | Root Ruff excludes the preserved experiment. Current handoff/map/status/development reflect the app. Copy uses no en/em dashes in newly authored prose. Impeccable surface discovery/schema migration remains a tooling follow-up, not silently repaired global state. |
