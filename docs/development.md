# Development and verification

All host-local locations in historical examples are illustrative. Use private
environment configuration for actual values; see [privacy](privacy.md).
Run `python3 scripts/check_public_content.py` before committing, with
`LIBRARIUM_PRIVATE_TERMS_FILE` configured privately for operator-specific terms.

Local implementation is authorized by L007. The first component is the shared
VS Code/development verification environment. It uses Git and Python 3.11+ with
no third-party dependencies. This is a tooling compatibility floor, not a product
runtime selection.

## Editor and local checks

Open [Librarium.code-workspace](../Librarium.code-workspace) using
[the editor guide](vscode.md). The same commands work in its remote terminal:

```sh
python3 scripts/dev.py doctor
python3 scripts/dev.py check
python3 -m unittest discover -s tests -p '*_test.py' -v
```

These commands report actual host/checkout/tool capabilities, validate editor
JSON and Git whitespace, and verify the 18 archived source/configuration hashes.
The six black-box CLI tests exercise preservation, same-size tampering, unsafe
paths, symlinks, missing files, and execution from a different cwd. They do not
execute the archived app or use production data. VS Code's default build task
runs workspace validation and tooling tests sequentially.

Use the installed ECC documentation audit after documentation/structure changes.
On the inspected host:

```sh
python3 /home/developer/.codex/plugins/cache/ecc/ecc/2.2.3/skills/docs-governance/scripts/audit-docs.py --root . --scope full
```

The full auditor does not honor Git ignores: after installing the local Node
archive it also reports missing links in that archive's release notes. The final
handoff distinguishes that raw result from the successful owned-document run,
which extends the auditor's in-process ignored-directory set without editing the
installed skill. Inspect its optional warnings; it validates structure/links, not application
readiness or the semantics of custom decision-log headings. New/untracked files
also need review because ordinary Git diff omits them. Keep check output concise
and replaceable under ignored `.local/verification/`.

## CI execution contract

All tools follow [the shared CI contract](ci.md). `CI_RUNS_ON` selects the
external runner pool or hosted fallback; the trusted policy job stays hosted.
Local pre-push checks are optional and do not replace GitHub acceptance.

## Git history and review

Start with `git status --short`, `git branch --show-current`, `git rev-parse HEAD`
and `git remote -v` to identify the checkout. Compare branch work with
`git diff origin/main...HEAD` and inspect uncommitted changes separately with
`git diff` and `git diff --cached`. Do not reset or discard work to inspect it.

Follow the [privacy guidelines](privacy.md) before publishing changes.
Ordinary branch history has been rewritten; use current refs rather than old
checkpoint IDs. Keep author and committer identities consistent with the privacy
contract, and review them before pushing.

GitHub runs `Source quality` and `Container acceptance` for pull requests.
`Source quality` also runs on main pushes; run `Container acceptance` explicitly
when verifying main. Verify both checks against the exact proposed head, resolve
review findings and preserve main protections. Passing CI verifies its tested
scope; it does not authorize deployment, library writes or public visibility.

## Claude Code cloud sessions

Use a disposable environment with the required Python, Node, PostgreSQL and native dependencies.

`.claude/settings.json` runs `scripts/cloud_session_start.sh` at session start.
It exits immediately unless `CLAUDE_CODE_REMOTE=true`, so other sessions are unaffected. In the cloud it fetches full history (required by the
populated-upgrade baseline checks), starts the PostgreSQL 18.6 container on
127.0.0.1:5432, builds missing native inputs and runs `uv sync --frozen` and
`npm ci` when the lockfile changed. Output goes to
`/tmp/librarium-session-start.log`. Cloud sessions run as root, so the packaged
reference-producer probe, which requires a non-root user, fails there; it belongs
to `Container acceptance`.

## Application experiment

### Automatic catalogue replica

The worker can copy published BLC snapshots and all referenced original and
upscaled cover blobs into `LIBRARIUM_CATALOGUE_DIR`. It is off by default; set
`LIBRARIUM_CATALOGUE_SYNC_ENABLED=true` on the worker only and configure the
existing `LIBRARIUM_CATALOGUE_STATUS_URL` (an operator-selected origin, also
accepting its `/v1/status` URL). The web process reads local data only.

`LIBRARIUM_CATALOGUE_COVER_DIR` and
`LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR` default to `covers` and `upscaled` under
the catalogue directory when omitted or empty. Sync requires separate directories
inside that root. Keep them separate from artifacts, the authoritative library and
reference-producer state. Set the same catalogue/cover settings in web and worker.

Each idle worker slice verifies at most 32 blobs, with a ten-second transfer/scan
budget and a one-second minimum interval. Snapshot integrity validation has its
own existing ten-second SQLite budget. Polls and failed attempts wait one minute.
The worker checks the deadline before each cover probe and resumes from a saved
scan cursor. Partial progress is recorded even when a later cover fails. Active
snapshot backfill finishes across slices before staging a newer snapshot, unless
a failed active cover requires moving on.
An interprocess lock and an atomic progress journal coordinate multiple workers
and interruption recovery. Existing blobs are checked against SHA-256, media
type, dimensions and raster limits before reuse. The added-work dashboard
candidates and upscale examples lead the initial backfill; remaining art follows.
Snapshots are capped at 512 MiB and manifests at 100,000 cover references.
JPEG metadata payloads are skipped by their declared lengths, with a separate
marker-traversal budget; image bodies and pixel dimensions retain their caps.

New snapshots stay hidden in staging until every referenced cover is verified.
The worker then installs the immutable snapshot and atomically replaces `current`;
the served predecessor and one further snapshot remain for comparisons/recovery.
Superseded staging snapshots are removed rather than accumulating behind failures.
Snapshot versions never move backwards. BLC serves covers by current work ID;
if its bytes change during a pull, digest mismatch holds cutover for retry.
An obsolete active cover does not prevent staging a newer complete snapshot.
There is no cover garbage collection or authenticated upstream transport in this
phase. The snapshot endpoint supplies no independent digest/signature; local
integrity and schema validation do not authenticate an HTTP publisher.

The dashboard's existing attention reasons show published-versus-served lag,
publication age when reported, missing local cover progress and sync failures.
The API's `librarium.catalogue_sync` projection carries bounded progress and last
verification time. Unknown completeness remains unknown; a saved observation is
not a live filesystem audit. Cached comparisons refresh their artwork on reads
so late cover arrivals become visible without restarting web.

For registry deployments with assessment inputs, apply
[`compose.catalogue-sync.yaml`](../compose.catalogue-sync.yaml) last, after
`compose.assessments.yaml`. It explicitly grants the worker `/catalogue:rw`, keeps
web `/catalogue:ro`, and keeps the worker exclusively on the internal default
network. Only the pinned HAProxy `catalogue-relay` joins `catalogue-egress`.
Web retains its existing edge network and never joins catalogue egress. Both roles
use `catalogue-relay` on port `12404` for status/sync reads; web still makes no
upstream requests. Set the operator-facing `LIBRARIUM_CATALOGUE_STATUS_PAGE_URL`
separately. [Packaging](packaging.md#fixed-upstream-catalogue-relay) owns relay
configuration and deployment checks. No mount or running-service change is
performed by tests or by this implementation.
Prepare writable catalogue storage for the existing container runtime user before
activation. The registry configuration validator admits only this opted-in
catalogue write boundary; authoritative library and curated inputs stay read-only.

Run `backend/tests/test_catalogue_sync.py` with the catalogue, status, health,
cover, artifact and registry-configuration tests. Use disposable catalogue state,
never an installed application's mounted store, for a live read-only API proof.

The assessed local experiment uses Python 3.14.9, Django 6.1.2, PostgreSQL 18.6,
React 19.3.1 and TypeScript 7. Node 24.22.1 is build/dev tooling. See the
[assessment](research/first-slice-2026-10-24.md) for alternatives, official support
evidence, pin rationale and upgrade path. The seeded collection and its
inspections are fictional. Optional read-only BLC/LF connections are described
below; no library writer is connected.

Install with `uv sync --frozen` and, from `frontend/`, `npm ci` using the pinned
Node line. `.python-version` and the package engine constraint identify runtimes;
do not replace the host's global Python/Node settings.

EPUB inspection uses a pinned native reader. On Linux with a compiler, make and
zlib development headers available in the selected build environment:

```sh
uv run python scripts/build_libarchive.py \
  --prefix "$PWD/.local/native/libarchive-3.8.10" \
  --build-dir "$PWD/.local/native/build"
export LIBARCHIVE="$PWD/.local/native/libarchive-3.8.10/lib/libarchive.so.13.8.10"
```

The script verifies the source digest and refuses a library lacking zlib support.
Keep `LIBARCHIVE` absolute and set before importing the reader. The tests and
file worker require it; the web upload path queues work without loading the
native reader. Build prerequisites may be supplied through `CPPFLAGS` and
`LDFLAGS` without installing anything globally. On `dev`, the ignored research
directory recorded in the [private engineering record](agent-environment.md#private-context-discovery)
contains the extracted zlib development package used for the local build.
The container builds its own native library. Pin and upgrade details belong to
[packaging](packaging.md#maintained-archive-reader-and-policy-v2).

Explicit EPUBCheck validation also needs the complete pinned software distribution
and Java 21. Install only into the ignored local directory:

```sh
uv run python scripts/install_epubcheck.py --prefix "$PWD/.local/epubcheck-5.4.0"
export LIBRARIUM_EPUBCHECK_DIR="$PWD/.local/epubcheck-5.4.0"
export LIBRARIUM_JAVA=/usr/lib/jvm/java-21-openjdk-amd64/bin/java
```

That Java path identifies the existing OpenJDK 21 installation on `dev`; select
an absolute, verified Java 21 executable on another host. The image pins Temurin
21.0.13+9. The installer verifies the official EPUBCheck 5.4.0 archive and exact
40-JAR manifest, preserves licenses and refuses a changed installation. The
[runtime research](research/epubcheck-runtime-2026-10-27.md) records official pins,
support evidence and upgrades. Java validation requires Linux x86_64, libseccomp
and Landlock ABI 3 or later; unavailable isolation refuses execution. Python
inspection, generation and preservation also require these guards; see
[Python child sandbox](#python-child-sandbox). No global Java
installation or runtime selection is changed by these commands.

On this checkout, select the isolated Node binary for an individual command with
`PATH=/home/developer/Developer/librarium/.local/toolchain/node-v24.22.1-linux-x64/bin:$PATH npm --prefix frontend run build`
(or replace `run build` with the required npm command). This changes no profile
or global runtime selection.

On `dev`, verified toolchains live under ignored `.local/toolchain/`. Node is
`.local/toolchain/node-v24.22.1-linux-x64/bin/node`. PostgreSQL executables are
`.local/toolchain/postgres/bin/`; its user-owned instance uses
`.local/postgres-data`, Unix socket `.local/postgres-socket`, port 55432 and no
TCP listener. Local Unix trust authentication is only for fictional test state.
The assessment/handoff records download integrity and the local source build;
neither is a system service installation.

If this isolated instance is stopped, start it with:

```sh
.local/toolchain/postgres/bin/pg_ctl -D .local/postgres-data \
  -l .local/verification/postgres.log \
  -o '-k /home/developer/Developer/librarium/.local/postgres-socket -p 55432 -h ""' start
```

Create an ignored local secret once (do not print it or commit the file):

```sh
mkdir -p .local
python3 -c 'from pathlib import Path; import secrets; p=Path(".local/experiment.env"); p.open("x").write("LIBRARIUM_SECRET_KEY="+secrets.token_urlsafe(60)+"\n"); p.chmod(0o600)'
```

The exclusive create refuses to overwrite an existing environment file. Tests
use a separate fixed test key; application commands require the explicit random
key above. Initialize only Librarium's own database and fictional projection:

```sh
uv run --env-file .local/experiment.env python backend/manage.py migrate --noinput
uv run --env-file .local/experiment.env python backend/manage.py seed_demo
```

Run web and worker in separate terminals:

```sh
uv run --env-file .local/experiment.env gunicorn --chdir backend librarium.wsgi:application \
  --bind 127.0.0.1:8123 --workers 2 --access-logfile - --no-control-socket \
  --access-logformat '%(t)s %(h)s %(r)s %(s)s %(b)s duration_us=%(D)s'
uv run --env-file .local/experiment.env python backend/manage.py inspection_worker
```

The frontend build is served by Python at `http://localhost:8123/`. Build it with
`npm run build` from `frontend/` before starting Gunicorn. WhiteNoise indexes the
asset tree at startup: after a local rebuild, reload only your own web process
before reviewing the compiled view. Do not replace its live dist during a review. For hot development, `npm run dev` there serves
5173 and proxies the API to 8123. Settings trust only the two loopback 5173 origins
and retain CSRF validation. `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and
`PGPASSWORD` select an explicitly prepared development database; defaults target
the isolated instance above. These settings are not production authentication.

The Last Orchard (`demo-00003`) deliberately fails its first inspection and
succeeds after an explicit new retry. A Map of Quiet Stars (`demo-00002`) has
conflicting titles and an invalid ISBN. Results describe metadata comparison
only, with exact values, input fingerprints and source versions. Catalogue
metadata reviews (below) share the job worker but never use these fixtures.

## Retired review-copy pipeline

[L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them)
retires EPUB correction and corrected-copy delivery. Librarium reads and checks
books and reports problems; it makes no corrected copy and delivers nothing. The
generation, output-preservation, stylesheet, paragraph and delivery-orchestration
modules, routes, worker, tests and acceptance scripts are gone. Inspection
(`librarium.epub-structure.v10`, with v9 and earlier kept as readable history),
EPUBCheck validation and the assessments are unchanged. A bad file is reported
by those checks and is never rewritten.

Stored rows of the retired job kinds, corrected-output records and delivery
evidence stay in the database as plain history. The worker never claims or
advances those kinds, `GET /api/jobs/history?kind=retired` lists them, and
`POST /api/jobs/<id>/cancel` still ends one left queued or running. See
[the status entry](status/2026-11-22-epub-repair-reduction.md).

## Application checks

### Read-only catalogue connection

The Catalogue navigation item reads BLC's published SQLite contract, separately
from the fictional Collection and its PostgreSQL inspections. With no directory
configured it shows an explicit connection state. Configure only a selected
development mount containing `current` (a version string) and immutable
`YYYY.MM.DD.N.sqlite` files:

```sh
LIBRARIUM_CATALOGUE_DIR=/absolute/development/snapshots \
  uv run --env-file .local/experiment.env gunicorn --chdir backend \
  librarium.wsgi:application --bind 127.0.0.1:8123 --workers 2 --no-control-socket
```

Do not point this at BLC's working database or Calibre. No automatic download,
refresh schedule, data copy or writer is configured. A real catalogue mount has
not been selected or tested. For fictional development snapshots only, set
`LIBRARIUM_CATALOGUE_FIXTURE=1`; this must stay unset for real data. The current
browser fixture lives under ignored `.local/catalogue-fixture/`. Tests build
their own temporary snapshots with the exact committed upstream schema at
`backend/tests/fixtures/blc-schema.sql`.

The API exposes `GET /api/catalogue`, `/api/catalogue/series`, `/api/catalogue/works`, and
`/api/catalogue/works/<work_id>`. Status/discovery returns a version and locally
computed SHA-256. Send both as `version`/`sha256` for subsequent reads; detail
and series-ID filters require the pair. Author/series identities include their
version. A missing or replaced pinned file returns 409; the UI requires explicit
Use current snapshot. No publisher-authenticated digest is claimed.

`/api/catalogue/series` requires the pin and accepts literal `q` plus `page`,
returning 24 series with work counts. Catalogue series IDs are JSON strings to
preserve SQLite's full integer range in JavaScript. `/works?series=<id>` returns
`selected_series` and orders the selected membership's nonzero numeric positions
first, then literal zero, then missing positions; ties use sort title and work ID.
Negative and fractional values remain exact. `position_counts` reports each
group over the filtered result, independently of pagination. Zero has no inferred
meaning. Unknown series retain
an explicit empty context. Other memberships cannot determine this order.
`selected_series.credit` carries `{names, others}` from canonical author-role
credits over the complete pinned series, independent of search, author filters
and page. Duplicate canonical names count a work once; editor roles do not count.
If both leading authors individually cover at least half of the series members,
retain both names. Otherwise one leading author must cover half, or the two
leading authors must cover half together by distinct work identity. With no
qualifying lead, `names` is empty; show Various authors only when at least two
canonical names are recorded, and omit unsupported credit for zero or one.
Ties use canonical author ID,
not alphabetical precedence. The aggregate returns at most two named rows and
retains the existing snapshot SQL deadline; it does not read LF credit strings.
`/works?author=<id>` (pinned; signed 64-bit, string IDs) lists that exact
author's `role='author'` works with type and first-published year as a
bibliography and returns `selected_author`. Names are never matched.
Duplicate/unsupported filters are rejected with 400. No series data is imported
into PostgreSQL. The UI stores browsing mode/series as `cb`/`cs`, with the existing
query/page/work/version/digest fields. Snapshot switches clear scoped IDs, and an
unpinned series link requires explicit recovery rather than assigning the ID to
today's snapshot. Library links retain its filters/check token and are offered
only for the same catalogue version.

Configured WSGI workers admit the current snapshot before accepting requests,
keeping validation outside the browser's read deadline. An invalid configured
snapshot fails worker startup. After admitting a new current version, recreate
web workers to validate it before use. Only the current version is prepared at
startup; cold reads of other retained versions need separate performance checks.
Integrity and fingerprint checks are unchanged. Actual installation timings,
snapshot inventories and machine details belong in private context.

Admission checks real tables/required columns, SQLite header and DELETE journal
format, quick integrity and matching embedded/filename version. Reads use
`mode=ro`, `immutable=1`, `query_only` and `trusted_schema=OFF`, with parameters
for user filters. Files must remain immutable after admission; publisher-style
versioned files are the input contract. Validation is cached by file identity,
size and nanosecond modification/change times (eight entries per process).
Snapshots over 512 MiB are refused; SQL has a two-second deadline, ten seconds
for initial validation. Hashing is bounded by the file limit, not a wall-clock
timeout. Search uses SQLite's literal substring matching, with its default
case-folding limits. Pages have 24 works; evidence shows at most 100 support rows
and 200 editions per work, with an edition truncation notice. Ownership stays
 unconfirmed. Alias redirects, library joins, full-text ranking and
automatic snapshot acquisition remain later work.

SQLite read-only URI behavior and trusted-schema controls were checked against
the [URI documentation](https://www.sqlite.org/uri.html) and
[PRAGMA documentation](https://www.sqlite.org/pragma.html#pragma_trusted_schema).

### Read-only original cover artwork

`LIBRARIUM_CATALOGUE_COVER_DIR` optionally selects an absolute local directory of
original BLC image bytes at `<directory>/<digest[:2]>/<digest>`. It is independent
of the snapshot mount and unset by default. Expose it read-only when configuring
a future container. The application never downloads covers,
follows a source URL or writes this directory.

Catalogue list/detail responses add `cover: {url, sha256, width, height, media_type}
| null`. The optional snapshot `work_cover` table must identify the exact work;
missing/unsupported metadata or unavailable local files leave a title-led entry.
`GET /api/catalogue/covers?work=<id>&work=<id>&version=&sha256=` returns
`{snapshot, covers: {<work-id>: <cover>}}` for up to 24 IDs. Unavailable entries
are omitted. Library uses this batch only for its matching catalogue version,
and independently checks the returned version/digest before displaying artwork.

Image URLs are same-origin
`/api/catalogue/covers/<work-id>/<cover-digest>?version=&sha256=`. They require the
exact snapshot pin and the work's original digest. Reads reject symlinks and
nonregular files, cap bodies at 8 MiB and concurrent reads at four, verify SHA-256,
and admit bounded raster headers whose actual dimensions agree with metadata
(20,000 pixels per side, 40 megapixels maximum). JPEG, PNG, GIF and still WebP
are supported; animated WebP is refused. This is header admission, not a complete
image-decoder validation. A failed image affects artwork only. Responses retain
the existing security headers and add a digest ETag, private immutable caching
and a same-origin resource policy. No arbitrary URL proxy or derivative service
is introduced.

`backend/tests/test_catalogue_covers.py` owns the admission and failure regressions.
The [private engineering record](agent-environment.md#private-context-discovery) records
real local byte checks and rendered acceptance. Cover identity never establishes
ownership, current verification, edition identity or reading progress.

### Read-only library connection

Set `LIBRARIUM_LIBRARY_URL` to a trusted LF origin (for example, `http://192.0.2.10:12402`). The optional value is passed through
`compose.dockhand.yaml`; it is unset by default and has no credential. Only
the web process needs it. Never use a public login URL or embed credentials.
`GET /api/library` projects the existing fixed browse GET into dated matches.
`/api/library/series?series=&version=&sha256=` and `/api/library/works/<id>?version=&sha256=`
first confirm the ID in the pinned catalogue, then read at most three LF pages.
They return only direct/contained/pending matches for that exact ID, with the
check date, coverage, loading and truncation state; version mismatches attach
nothing. Absence is never reported as missing. Leaving the Library for Catalogue
evidence keeps a browser-history return that restores the Library view.
No book mount, LF database, automatic library check or writer is configured.
[private engineering record](agent-environment.md#private-context-discovery) and
[private engineering record](agent-environment.md#private-context-discovery) describe source provenance,
response/deadline limits, changed-snapshot recovery and real-data acceptance.

Known saved-check conflicts return HTTP 409 with the local JSON reason
`code: "library_check_changed"`. Generic/catalogue-pin conflicts do not. The UI
allows one unpinned recovery read per episode, retaining search, page, order,
Copies and the exact catalogue pin. The budget spans token adoption and shelf
preparation; a successful completed read, new user intent or explicit retry
starts a new episode. Requests consume cancellation signals and obsolete intents
cannot publish results. Persistent churn stops with an actionable Reload library.
Retained matches are historical, current copies are unconfirmed and previous
absence becomes unknown. No automatic catalogue-pin switch is permitted.
Catalogue returns carry the exact version/digest and reconcile a changed check
only when that pin and selected work survive. The
[private engineering record](agent-environment.md#private-context-discovery) owns regression,
independent review and rendered evidence for this contract.

`GET /api/library/shelves?version=&sha256=&q=&ownership=&page=&snapshot=` adds
four matching shelves per page with five preview representatives apiece. It
requires the published local catalogue pin. Matching sets of at most 600 works
are grouped after a complete bounded LF read; larger sets prepare a complete
background match index under the same check token, filters and catalogue pin.
Polls return Preparing shelves until the bounded index is ready. A shelf requires
at least one non-null position in the pinned catalogue, and its name must not be
a setting value or a named Warhammer umbrella. Wholly unnumbered groups and
setting-level pseudo-series are not shelves. Works with no eligible memberships
form the complete, title-ordered closing **Standalone and collected** shelf.
Canonical position leads come from the whole pinned catalogue; a preview can
represent an unmatched lead with another matched work without changing its label.
Only nonzero numbered positions collapse to one lead. Zero and unpositioned
works remain individual, without cover chips or folio numerals. Canonical
author-role credits and ISO-prefix date comparison come from the pin.
The closing shelf's All N opens its matched titles in Title order with
`lg=standalone`; `/api/library/shelves?group=standalone` returns all such results,
24 per page, retaining query and Copies. Back restores the originating shelf.
Each gunicorn worker has its own four-entry derived index cache. Its first page
view prepares independently. Previous pages remain visible during preparation;
ready indexes survive token flips and can be reused when LF re-advertises them.
Incomplete reads never publish an alphabetical subset as recorded order;
Title/Author remain the recovery path when the bounded index cannot finish.
[L025](decisions.md#l025-bounded-pinned-library-shelves-and-the-reading-room-foundation)
owns the strategy and limits. Responses expose `finish_origin` from the configured,
validated LF origin for fixed Calibre-copy links; no upstream URL is forwarded.

Library route fields `lw`, `ls` and `ld` retain the selected work, its shelf and
focused detail separately. Returning from phone detail preserves selection; returning
from Catalogue also restores the originating window and horizontal shelf scroll.

For reading-room proof on the isolated review port, build first and run the
documented two-worker topology with real read-only data and admitted local covers:

```sh
LIBRARIUM_LIBRARY_URL=http://192.0.2.10:12402 \
LIBRARIUM_CATALOGUE_DIR="$PWD/.local/catalogue-live" \
LIBRARIUM_CATALOGUE_COVER_DIR="$PWD/.local/catalogue-covers" \
uv run --env-file .local/experiment.env gunicorn --chdir backend \
  librarium.wsgi:application --bind 127.0.0.1:8125 --workers 2 --no-control-socket
```

Stop only this owned preview when finished. Leave other previews and PostgreSQL
running. LF token changes can return 409 during the bounded read; Reload library
retries the check without changing source or library state.

### Catalogue metadata reviews

`POST /api/jobs` with exactly `catalogue_work_id`, `version` and `sha256`
(plus `Idempotency-Key`) queues a review. The web process captures a compact,
read-only copy of that pinned work's metadata (64 KiB cap, source values kept
as bounded excerpts) into `Job.input`; errors are 400/404/409/422. The worker
reviews only that input: pin/fingerprint provenance, source agreement, edition
ISBNs and bibliography completeness, with partial-coverage notes. One review
per work may be active. Results state that library ownership, book files and
Calibre records were not checked. `GET /api/jobs?kind=catalogue` supplies the
live progress window. `GET /api/jobs/history` reads the complete stored history,
24 records per page, ordered by creation time and UUID descending. Optional
`q` is a literal, case-insensitive captured-title substring (200 characters),
`kind` is `catalogue` or `synthetic`, and `state` is `active`, `queued`, `running`,
`succeeded`, `failed` or `cancelled`; empty filters mean all. `active` includes
queued and running records. `page` is 1–10000. Unknown or repeated filters,
control characters and out-of-bounds values return 400 before querying.
The response is `{jobs, total, page, page_size}` with the existing job/provenance
shape and `no-store`. An empty page retains the filtered total; clients can
return to the first page without inferring that stored reviews disappeared.
History reads never enqueue work or reach upstream services. Cancel uses the
existing job endpoint; an unconfirmed submit
retries with the same request key. Migration
0003 and rollout limits are in [packaging](packaging.md#schema-0003-catalogue-review-jobs).

### Preserved EPUB and catalogue comparison

A completed file inspection offers **Compare with catalogue**. Search and work
selection are explicit; no work is attached automatically by title. The comparison
is calculated on demand and does not alter the stored report or job.

`GET /api/epub-inspections/<job_id>/comparison` requires exactly one each of
`work`, `version`, `sha256`, `source_sha256` and `report_sha256`. Source/report
digests must match the selected completed job. The existing report reader
revalidates the captured policy, preserved bytes and published report before the
immutable catalogue reader opens the requested version/digest. Responses are
`no-store`; POST, unknown fields, duplicate parameters and malformed pins refuse.

Policy `librarium.package-metadata.v3` reports separate title and creator-name
states: `same`, `different`, `partial`, `ambiguous` or `unknown`. Normalization
uses NFC, case folding and collapsed whitespace while retaining punctuation.
Only canonical names and recorded aliases count; no nickname, surname, fuzzy
title or subtitle inference is used. Every creator must resolve to one distinct
author, and every selected work author must be covered. Normalized collisions
are checked across the whole pin, including authors outside the chosen work.
Editor/narrator credits do not substitute for catalogue author credits.

Up to 64 titles, creators and selected author credits, each up to 512 characters,
are admitted. Oversized or incompatible global canonical/alias names refuse with
422 rather than disappearing from collision detection. An absent compatible
`author_alias` table returns 503; existing catalogue browsing remains available.
SQL retains the existing two-second deadline and read-only snapshot limits.
Missing names, generic author placeholders, duplicate author coverage, multiple
distinct titles and incomplete inspections cannot establish complete agreement.

The saved inspector omits creator roles and title refinements. The UI therefore
compares **EPUB creator names / catalogue author credits**, preserving file
spellings and showing the recorded alias evidence. `metadata_agrees` describes
these names only; `ready` stays false. No EPUB is reopened or re-inspected by the
request. This does not replace LF's source-bound identity/admission assessment.
The [private engineering record](agent-environment.md#private-context-discovery) owns execution
evidence and remaining acceptance.

The v2 comparison introduced separate `isbn` evidence without changing an
inspection policy, source bytes or stored report. Historical v1–v4 inspection
reports permit only explicit `urn:isbn:` identifier text to be assessed; bare
numbers, UUIDs and uncaptured scheme/refinement declarations are unassessed.
The current v3 comparison also interprets v5 declarations described below.
Check digits and
supported 978/979 prefixes are verified, with 979-0 reserved for ISMN excluded.
ISBN-10 converts to its equivalent 978 ISBN-13; hyphens and a lowercase terminal
`x` normalize. Spaces and percent escapes are invalid for the supported ISBN
syntax; URN components remain unassessed, including valid fragment URNs. Publisher
allocation/range validity is not checked.

Lookup considers primary edition ISBN columns and `edition_ident` across the
entire selected pin. Disputed values, orphan/unassigned records and cross-work
collisions remain ambiguous. A unique other-work match is different; no match is
unknown, never proof the work has no ISBN or is absent from the catalogue. Multiple
editions of one work retain their individual formats without inferring EPUB
format equivalence or multiple independent identity votes. Incomplete inspections
cannot establish ISBN agreement. `metadata_agrees` continues to describe title
and creator names only; ISBN evidence has its own visible disposition.

The existing 64-value/512-character metadata bounds apply. Global ISBN fields
over 512 characters, more than 256 matching raw catalogue rows or 256 combined
returned edition references refuse with 422 rather than hiding possible
conflicts. A missing compatible `edition_ident` table refuses an attempted ISBN
comparison with 503; comparisons without a supported ISBN remain available.
Existing source/report/catalogue pins, read-only SQLite deadline and explicit
work choice remain. [private engineering record](agent-environment.md#private-context-discovery) owns
primary-source rationale, actual verification and publication.

### Source-declared ISBN evidence

New jobs capture inspection policy `librarium.epub-structure.v5`. Its
`identifier_evidence` object binds schema `librarium.epub-identifiers.v1` to
package path, version and SHA-256 of the exact package document. It preserves
raw root `unique-identifier`/`prefix`, identifier `id`/`xml:id`/qualified
`opf:scheme`, plain-text status, whole-package ID occurrence counts, and direct
OPF meta records whose property is exactly `identifier-type`. XML preorder
indexes are zero-based. Null attributes, empty attributes and absent historical
capture remain distinct. EPUB 2's single legacy `dc-metadata` container is
supported; mixed or ambiguous metadata containers refuse inspection.

Refinements bind only to unique, legal XML 1.0 NCNames on direct identifiers in
the selected DC metadata scope, through a same-package one-hop reference.
Same-element ID aliases count once. Other package targets, repeated IDs,
unresolved references and unsupported references retain their own association
states; they do not become identifier evidence. Existing `xml:base` refusal,
XML/record/output and isolated-process budgets continue to apply. XML whitespace
is ASCII space, tab, CR and LF; non-ASCII padding remains in the observed text.

Comparison schema `librarium.package-comparison.v3` adds `isbn.capture`
(`recorded`, `not_recorded`, `incomplete`) and per-entry `basis`, `reason_codes`,
`source_position` and raw `declarations`. A qualified OPF EPUB 2 scheme of ISBN
can type its value. EPUB 3 accepts only the unprefixed property
`identifier-type`, a scheme resolving exactly to
`http://www.editeur.org/ONIX/book/codelists/current.html#codelist5`, and code
`02` or `15`, with the corresponding ten/thirteen-digit payload. The reserved
ONIX prefix can be overridden; an alternative EPUB prefix resolving to the same
URI works. XML `xmlns` mappings supply no EPUB vocabulary meaning. Prefixes
require literal ASCII space after their colon, XML whitespace separators and
valid NCNames; scheme references must be path-relative before prefix expansion.

Unsupported schemes/codes remain unassessed. Multiple, conflicting or ambiguous
types cannot yield a favorable fallback match. Checksum failures and declared
length mismatches remain visible, and incomplete inspections cannot establish
agreement. Combined returned declaration references are capped at 256, alongside
the existing raw catalogue-row and edition-reference ceilings; overflow returns
422. This changes no source/report artifact and creates no job or association.

The full report exposes raw declarations and their recorded targets; the
comparison exposes the interpretation separately. A malformed current capture
refuses rather than acquiring legacy assurance. Saved v1–v4 artifacts remain
unchanged and readable with historical native-reader/plan bindings; pending
older captures refuse the new worker. [Packaging](packaging.md#identifier-declaration-policy-v5)
owns rollout; the [private engineering record](agent-environment.md#private-context-discovery) records
source references, verification and remaining gates.

### Labelled EPUB contents evidence

Policy `librarium.epub-structure.v3` introduced labelled contents evidence while
retaining the inspection limits and pinned archive reader. Heading records add `label`; anchor
link records add `label`; NAV/NCX target entries add `label`, `kind` and
`ancestors` (source group labels, outermost first, excluding the entry itself).
Unlinked source groups contribute ancestor labels without invented targets.
Labels collapse whitespace, remain plain text, and use the existing 512-character
field limit. Oversized labels refuse instead of being silently shortened.

The full report exposes contents observations alongside the recorded reading
order and navigation. Paths/fragments and document digests retain their original
binding. Empty captured labels and fields absent from historical reports stay
distinct. Source headings/links are evidence, not inferred novel groups, proposed
anchors, deletion candidates or readiness. EPUBCheck remains `not_run`, content
acceptance `not_checked`, and `ready=false`.

Reports from v1/v2 remain immutable and readable under their original policy;
reading one does not re-inspect it. An explicitly requested new inspection is
required to capture new fields. Pending v1/v2 jobs refuse the newer worker policy.
Reader/source/report bindings still apply to historical native-reader evidence.
[Packaging](packaging.md#contents-evidence-policy-v3) owns rollout and CI, and
the [private engineering record](agent-environment.md#private-context-discovery) records actual checks.

### Read-only EPUB contents plans

Policy `librarium.epub-structure.v4` introduced source positions. In the existing isolated
worker, the inspector records source element indexes, body/non-heading word
counts and offsets, media counts, existing anchor positions and literal
group-label provenance. These are XML source observations, not rendered
visibility or proof of narrative completeness; book prose remains absent.

The immutable report's `contents_plan` uses `librarium.contents-plan.v1`, bound
to the preserved source SHA-256 and captured inspection policy. It returns
`keep`, `propose` or `held`, reason codes, recorded navigation, replacement
entries, explicitly excluded targets and scope limits. Held plans have no
replacement entries; keeping navigation preserves its recorded list. Proposals
retain literal source labels, exact targets and document digests. A source
heading without an existing target anchor has `requires_anchor=true`, not a
fabricated fragment. No source or navigation document is rewritten.

The planner admits at most 2,048 recorded/proposed entries combined and eight
hierarchy levels, within the existing report record/output and child-process
limits. Unsupported ordering, conflicting targets, incomplete evidence and
ambiguous restarts hold the whole replacement list. Title-holder exclusions
must not discard independent text/media or real short chapters. This is a
bounded source-backed proposal, not LF preparation parity or content acceptance.

Inspection v10 and `librarium.contents-plan.v2`
([L061](decisions.md#l061-library-finish-contents-rebuild-and-text-empty-pages))
replace the v1 rules with Library Finish's contents rebuild. The report adds
bounded `contents_observations`: short title-like paragraph lines, per-page
store/backlist/copyright/OCR signals and heading id/link flags, never prose.
They yield to structure, the plan and document text when budgets run short; a
plan without them is `held/contents_evidence_unavailable`. v2 plans add
`measures` and up to three rule `problems`; reason codes name LF's keep, rebuild
and refusal branches. `backend/tests/test_contents_rebuild.py` re-runs LF's
synthetic rebuild cases through the real inspection, with `test_contents_planning.py`
for envelope, budget and determinism checks.

[L063](decisions.md#l063-validated-rebuilds-for-empty-navigation) treats
`empty_navigation` as a warning only after complete inspection finds no other
structural error and the planner proposes a non-empty replacement. Replanning
after an observation-budget fallback rechecks that condition. The finding still
prevents the existing navigation from being described as sound, including when
one of NAV/NCX is populated and the other empty. No proposal means a structural
failure and a held plan with its original reason. Output structure validation
rejects navigation left empty, even when source inspection can offer a rebuild.
`backend/tests/test_empty_navigation.py` covers NAV, NCX, both formats, historical
v10 reports, held sources, sandboxed correction, EPUBCheck and preservation.
The report contract and inspection v10 policy name stay unchanged.

The compact `Job.result.contents_plan` contains only `policy_version`, `decision`
and `reason_codes`; the report reader verifies it against the immutable plan and
the existing source/report/policy bindings. The report UI exposes source details
and keeps historical absence distinct from a held current plan. Saved v1/v2/v3
reports remain readable without reinspection or new claims; pending older-policy
jobs refuse the v4 worker. These structural reports retain `epubcheck=not_run`,
`content_acceptance=not_checked` and `ready=false`; separate validation does not
rewrite them. [Packaging](packaging.md#contents-planning-policy-v4) owns the
rollout/image gate; [private engineering record](agent-environment.md#private-context-discovery)
owns actual verification.

### Explicit EPUBCheck validation

`POST /api/epub-inspections/<source_id>/validations` takes an empty JSON object,
CSRF token and UUID `Idempotency-Key`. It queues a separate `epub_validation` job
from a preserved completed inspection. The capture binds the original job/input
fingerprint, source bytes and size, structural report digest, inspection policy,
validator archive/JAR identities and validation policy. The web process never
runs Java. Only one validation of a source digest may be active; replay with the
same key recovers the same intent, including after configuration changes.

`GET` on that route accepts either `request_key` for exact recovery or `page` for
20-row source-scoped history. The full immutable report is at
`GET /api/epub-validations/<job_id>/report`; its reader rechecks the original
inspection, both report bindings and preserved bytes. New processing captures
`librarium.epub-validation.v1`. Pending jobs with a different profile refuse;
completed historical captures remain readable under their saved identity. The
original structural report retains `epubcheck=not_run` and its exact assurance.

A completed checker run may report conformance `passed` or `failed`; both are
successful job execution. Fatal/error counts determine conformance failure;
warnings alone do not. Aggregate counts remain separate from bounded diagnostic
rows and locations. EPUBCheck 5.4.0 omits an aggregate INFO count, so `counts.info`
is `null`, never an inferred zero. Runtime, isolation, timeout or unusable-report
failures publish no conformance result. Content acceptance stays `not_checked`
and `ready=false`; validation changes no EPUB or library record.

The checker runs in a fresh process group with a 2 GiB address-space ceiling,
60-second CPU budget and 90-second parent wall deadline. Fixed JVM settings cap
heap at 256 MiB and per-thread stack at 2 MiB; callers cannot supply Java flags
or inherited JVM options/environment. Seccomp denies network creation/connections, and
Landlock limits reads to pinned runtime/JAR inputs and named OS support paths.
Only private scratch and standard JVM device files receive write access. Source,
report and log limits remain bounded; source bytes and JARs are rechecked after
execution. Cleanup kills the owned process group before removing scratch, even
if the direct checker already exited. The checker receives SIGKILL if its worker
parent dies. Missing guards fail closed.

Migration 0005 and coordinated web/worker upgrades are covered by
[packaging](packaging.md#schema-0005-and-explicit-epubcheck-validation). The
independent backend review passed. At this checkpoint, the implementing agent
ran the native filesystem checks after the isolation fix; those checks have not
received a second independent execution. Exact verification counts and remaining
gates belong in [current status](status.md), not in a claim of container acceptance.

### Automated checks

The required `source-quality` job in `.github/workflows/quality.yml` runs these
checks for PRs and main, and is reused for exact-source beta publication.
Python and frontend phases run independently after their frozen installs, so a
test failure does not suppress the other ecosystem's audit or build report.
The job remains failed when any phase fails. Native/checker setup is a
prerequisite for the warning-strict Python tests, not for frontend checks.
The 30-day `source-quality-reports` artifact includes the actual checked-out
commit, workflow/event/ref provenance, Python JUnit/coverage XML, frontend
coverage summary, dependency audit JSON and redacted secret findings.
Actions logs retain type/lint/build failure details; missing prerequisites are
reported as failed/skipped steps, never as passing checks.

Gitleaks 8.30.1 is downloaded from its official release with a checked-in archive
SHA-256. It scans history reachable from the tested HEAD with full redaction and
refuses findings or execution failures. Inline `gitleaks:allow` comments are
disabled. `.github/gitleaks.toml` allowlists three exact public JAR checksums only in the EPUBCheck distribution manifest. For a real credential finding, revoke/rotate the
credential through its owning service and retain only redacted evidence; do not
add an exception to make CI green. Exceptions need a reviewed finding-specific
reason, not a directory-wide exclusion. Dependency advisory or audit transport
failures also need triage; no audit failure is silently ignored.

Review upstream support and security advisories weekly during active development
and before every beta, as specified in [release policy](releases.md). This is a
review cadence, not an enabled scheduled job. Use small reviewed updates and
coordinate `pyproject.toml`/`uv.lock`/hash-locked `requirements.txt`,
`frontend/package.json`/`package-lock.json`, Python/Node/image pins and relevant
native libarchive/JRE/EPUBCheck identities. Re-run frozen installs, export
comparison, source checks and actual-image replacement/restore acceptance;
inspection-policy or captured-runtime changes retain their historical evidence
and worker-compatibility gates. Update action/scanner full-commit/archive pins
from official releases with the same review discipline. Never auto-merge an
update or patch a running container as the upgrade procedure.

```sh
uv run pytest -W error --cov=librarium --cov=scripts.capture_source --cov-report=term-missing -q
uv run --env-file .local/experiment.env mypy
uv run ruff check backend scripts/capture_source.py tests/test_capture_source.py
uv run --env-file .local/experiment.env python backend/manage.py check
uv run --env-file .local/experiment.env python backend/manage.py makemigrations --check --dry-run
uv run pip-audit
```

From `frontend/`, using Node 24.22.1:

```sh
npm run build
npm run coverage
npm audit
npx --no-install prettier --check src tests vite.config.ts index.html tsconfig.json
```

Pytest defaults to five xdist workers. Pass `-n 0`
for a serial local run. Keep test output quiet; verbose test IDs can stall the
runner log pipeline.

Python coverage includes the application, WSGI security wrapper and capture tool.
Frontend coverage includes API deadlines, revision/intent/announcement logic and
the mounted React application. Component journeys use fetch stubs and semantic axe
checks; those cannot prove browser layout, contrast or screen-reader behavior.
Use T3 preview for actual control/failure journeys. Keep screenshots, recordings
and replaceable command evidence outside tracked source.

For independent checks in a disposable development environment use `PGDATABASE=librarium_review`
with pytest so it creates `test_librarium_review` rather than colliding with the
parent's `test_librarium`. For isolated Vitest runs set `fsModuleCachePath` under
`/tmp`; Vite `cacheDir` alone does not relocate its module cache. Do not restart
PostgreSQL during another check.
The handoff records actual process recovery, dump/restore and empty-schema
migration reversal results.

## Container implementation and limits

Select runtime/framework versions from current official support and compatibility
information, record the rationale, and work in bounded, testable slices. Use
meaningful TDD, contract checks, and the actual project runner; do not copy a
skill's framework examples into this repository as requirements. For interactive
work test delays, duplicate actions, retries, reconnects, out-of-order responses,
focus/selection/input preservation, mobile layout, and accessibility.

The accepted [packaging contract](packaging.md) requires reproducible Docker
releases and durable state outside images. Run container acceptance in an environment with Docker.

Preserve the earlier experiment under `experiments/migration-baseline/`; its
old Python/Django pins are not the active application stack. Its original 18 tests
and Django system check passed after relocation. Root workspace verification
checks its bytes without activating that environment.

Before delivery use the relevant verification/security skills, review the diff,
update the map and decisions where facts changed, add a new dated file under
`docs/status/` when status changes (never edit another PR's entry), rebuild the
local graph after code changes, and refresh Developer context. Preserve the
selected ECC 2.2.3 files and native Claude plugin; load only task-relevant skills
as described in [the skill map](skills.md).

### Native read-only Calibre library

`LIBRARIUM_DIRECT_LIBRARY_ROOT` selects an operator-configured Calibre directory.
Configure its host path privately and verify a read-only mount before use. Never
resolve unapproved aliases or mount originals into workers. Native mode supersedes
saved LF browsing and suppresses its Catalogue ownership overlays.

The `/api/direct-library` list supports literal title/author search and 24-book
pages. Book detail and admitted covers retain the returned `inventory` token;
a changed observation gives `409 direct_library_changed` and explicit refresh.
The token binds database/WAL identities, not the contents of every recorded file.
Calibre's undefined publication dates (January 1, year 101, or earlier years)
project as null and display as Not recorded. Other recorded values remain exact;
the reader never substitutes reference dates or rewrites library metadata.
Private bounded database/WAL copies retain committed changes without allowing
SQLite to create SHM or recover journals in the authoritative library. Files and
covers use descriptor-relative no-follow reads; unavailable files remain visible.
Each web process retains at most one private metadata copy, keyed by library-root
and DB/WAL identities, so cover requests reuse metadata without recopying it.
Source checks still run before/after each request; changed input replaces and
removes the retained copy. Copy/replacement is serialized through connection close
and the request deadline bounds lock waits. Process shutdown removes the copy.

Library listings read the first 64 KB of each cover, and only covers that need
more read on to 256 KB, which is enough for type and dimensions;
`GET /api/direct-library/books/<id>/cover` reads the whole file. Each book's folder
is opened once, its recorded files are checked with a no-follow stat rather than
opened, and a page checks up to eight books at a time (`PROBES`), because every
file operation is a round trip on the shared library mount. Covers are sent with `Cache-Control: private, max-age=86400` and an ETag
(`304` on a match). Their address names the library inventory, and that changes
whenever Calibre changes a cover. Library reads in the browser allow 20 seconds
(`LIBRARY_TIMEOUT`) rather than the usual 5, because they cross the shared
library mount and can queue behind cover requests.

#### Library read model

[L075](decisions.md#l075-postgres-read-model-of-the-calibre-library) adds a Postgres
copy of what listings need. `LIBRARIUM_LIBRARY_READ_MODEL` selects `off` (default),
`refresh` or `serve`. In `refresh` and `serve` the inspection worker, while idle,
checks the inventory token every `LIBRARIUM_LIBRARY_READ_MODEL_SECONDS` (default 15)
and imports when it moved, then hashes unhashed recorded files, smallest first, for
up to 10 seconds, stopping mid-file when the slice runs out. A file too large for a
slice stays unhashed until `refresh --hash-seconds N` gives it longer.
The worker needs the read-only library mount from `compose.assessments.yaml`.
In `serve`, listing, search, recent and series come from Postgres with no file
access and the same JSON; otherwise, or when no current import exists, the direct
reader answers. Detail, cover and file routes always use the direct reader.
Calibre declares its sort and name columns `COLLATE NOCASE`, so title and series
order and series lookup fold ASCII case before comparing bytes, as SQLite does.

```sh
uv run python backend/manage.py library_read_model refresh [--force] [--hash-seconds N]
uv run python backend/manage.py library_read_model parity
```

`refresh` prints whether it imported and, when it did, how long the import took
and how many stat calls and cover header reads went to the share; the worker logs
the same as `library_read_model_imported`, and each hashing slice's file count as
`library_read_model_hashed`. `parity` prints a JSON report (per-book
`changes` in the reconciliation report's categories, the differing fields per book,
and whether title and recent order agree) and exits non-zero unless the model is
current and identical. Run it before switching to `serve`, and after any reader
change. Import failures are kept in `LibraryReadModel.error` and logged as
`library_read_model_refresh_failed`.

`GET /api/direct-library/series?name=<series>&inventory=<token>` lists the owned
books in one Calibre series (exact name, up to 200) in series order, read from the
same pinned snapshot. The book page merges them with the catalogue's order for that
series, once the book is matched to a catalogue work or carries its catalogue
identifier with agreeing authors. Each numbered place shows one book: yours, or
the earliest published work. Unplaced and position-zero works follow.

`GET /api/direct-library/books/<id>/file?inventory=<token>&format=EPUB` returns the
exact recorded file through the same pinned, no-follow read (`409` when the library
changed, `404` for an unrecorded format, `503` for a missing file as other library
reads report it). It is always an attachment
with `Content-Security-Policy: default-src 'none'; sandbox` and is never rendered by
the server. The reader page (`GET /read/<id>?inventory=<token>`, Vite entry
`frontend/reader.html`, code in `frontend/src/reader/`) unpacks that EPUB in the
browser with fflate inside the 256 MiB cap and renders it with the vendored
foliate-js engine ([L074](decisions.md#l074-foliate-js-reader-page-with-its-own-policy)):
real page turns, two-page spreads on wide screens and an optional scrolled mode.
Every book document is cleaned before the engine frames it (`src/reader/clean.ts`).
Only `/read/<id>` receives the reader policy, which allows inline and `blob:` styles,
`blob:` frames, fonts and images; `script-src` stays `'self'` there and everywhere.
The rest of the app keeps its strict policy. Old `?read=` links redirect to the page.
The reading place (an EPUB CFI plus the older section and fraction) and text settings
stay in that browser's local storage.

Explicit per-book matching pins `inventory`, catalogue `version` and `sha256`.
It distinguishes matched, ambiguous, disagreement and unmatched metadata with
literal identifiers, aliases and recorded editions. It establishes neither file
identity nor EPUB edition equivalence. Catalogue control reads saved snapshot
observations; native producer health is reported separately. Whole-library unmatched
coverage remains unknown until persistent reconciliation is implemented.

With private artifact storage enabled, `POST /api/direct-library/books/<id>/inspect`
takes `{"inventory":"<token>"}` plus the normal CSRF and UUID idempotency key.
It captures the recorded EPUB, checks file/metadata identities before enqueue,
and binds library/book origin to the existing durable inspection input. An exact
retry returns the recorded job without requiring the source to remain accessible.
The worker needs only private preserved artifacts; no original is modified.

`compose.library.yaml` adds only the web read-only `/library` mount and clears
its LF origin. Set `LIBRARIUM_LIBRARY_HOST_PATH` explicitly and combine with the
selected base, plus `compose.files.yaml` only for approved inspection activation.
The base stacks still mount no library by default. Registry configuration rejects
writable library mounts, worker library mounts and overlap with writable state.
The actual-image CI fixture covers committed WAL, covers, captured jobs, independent
worker processing, replacement and unchanged originals. Synthetic CI is separate
from actual-library beta acceptance and its concrete activation review.

### Native reference imports

`LIBRARIUM_REFERENCE_STATE_DIR` opts into manual offline reference production.
Create a dedicated app-owned directory with mode 0700, outside the authoritative
library, artifacts, cover cache and incumbent snapshot inputs. Leave it empty
by default. The command creates private receipts, preserved packets and immutable
generations; no PostgreSQL migration, provider credentials or old service is needed.

Use `reference_import <packet-file|-> --request-key <UUID>`. The initial import
also requires `--bootstrap-version <version> --bootstrap-sha256 <sha256>` for a
snapshot admitted by the existing `LIBRARIUM_CATALOGUE_DIR` reader. Bootstrap is
copied into native evidence before any changes; its source stays read-only.
Subsequent imports derive from native evidence and need no bootstrap configuration.
To browse native publications, select `<reference-state>/published` as
`LIBRARIUM_CATALOGUE_DIR`; existing explicit browser pins remain unchanged.

Packets use `librarium.reference-packet.v1`, one registered `source`, a UTC
`observed_at`, and up to 1,000 normalized `records` within 4MiB. Each record needs
a source-native ID; retained Record fields carry title, credits, identifiers and
evidence. Preserve the actual observation date when replaying historical records.
This command does not fetch providers, infer new observations or download covers.
The facade and its behavior tests own the precise field/type limits.

Preserve the exact packet bytes and request UUID. An exact replay returns the
recorded outcome; a different packet or bootstrap pin under that UUID conflicts.
After an interruption, recover the original UUID before starting another import.
A prepared publication can finish only while the expected previous current
generation still matches; an interrupted pre-publication attempt records failure
without changing current. A failed attempt requires a new UUID to attempt work
again. Do not delete receipts/markers or overwrite generations to bypass recovery.

Catalogue control exposes current native publication and last import outcome,
including preparing/prepared/failed states, separately from the selected queue
snapshot. Refresh reads health without switching the selected pin. Unavailable
producer state does not disable admitted catalogue browsing. The
[private engineering record](agent-environment.md#private-context-discovery) records actual proof,
review corrections and remaining provider/matching/beta work.

### Saved native library reconciliation

`library_reconcile` is an explicit backend operation after migration 0006. It
captures all recorded books and format relationships without opening book or
cover files, then uses the existing conservative matcher against one explicit
catalogue version/SHA-256. It saves a complete report in application PostgreSQL
only after both input fences pass. No request handler, recurring scan or worker
job is introduced. Run it outside the interactive web request path:

```sh
uv run --env-file .local/experiment.env python backend/manage.py library_reconcile \
  --request-key <UUID> --catalogue-version <version> --sha256 <sha256>
uv run --env-file .local/experiment.env python backend/manage.py library_reconciliation <UUID>
```

The first command prints the summary; the second returns the full historical
report without rechecking live inputs. Use the same UUID and exact pin/previous
report to recover a saved outcome even if sources become unavailable. Different
inputs under that UUID refuse. Interrupted attempts that saved nothing can be
rerun; no partial report is selectable. Failures leave prior reports intact.
Concurrent exact retries return the same winning report.

Pass `--previous <saved UUID>` to compare inventory metadata explicitly. Added
and removed numeric book IDs are relative to that prior report. A changed UUID
under the same ID is a replacement; missing identity is separately unknown.
Changed metadata includes recorded relative library paths and format names/sizes.
A recorded library UUID is required, and cross-library comparisons refuse.
Historical reports remain available; no “latest” pointer can silently replace a
newer observation with a slow earlier scan. Different catalogue pins are allowed
for the metadata delta; every match is recalculated against the newly named pin.

Limits are 10,000 books, 32 MiB of serialized report and 180 seconds of capture/
matching work. The library reader's existing short metadata-copy/SQL budgets
remain. Over-limit, changed or incompatible sources refuse the entire report.
Per-book malformed metadata and comparison-limit refusals are counted as held,
never unmatched. Exact evidence and scope are retained for all evaluated books.
Recorded format availability is unknown; no complete-file digest, duplicate
verdict, edition identity, correction admission or readiness is inferred.
Saved results remain backend-only. Without explicit report selection, Catalogue
control keeps unmatched coverage not assessed. The following readers expose it.

### Saved coverage readers

`GET /api/library/reconciliations?page=1` discovers historical report summaries
(24 per page, newest publication first, UUID tie-breaker). Discovery projects
summary fields in PostgreSQL instead of fetching every per-book JSON array.
`GET /api/library/reconciliations/<request-key>?status=unmatched&page=1` returns
24 exact saved entries, their original catalogue/inventory pins, full counts,
filtered total and inventory total. Status is optional; the five saved dispositions
remain separate. Reads work with source mounts unconfigured and always describe
historical observations. Pages are bounded to 1..10000; duplicate/unknown query
parameters refuse. Unknown report UUIDs return 404; reads never enqueue scans.

`GET /api/catalogue/control` additionally accepts `reconciliation=<request-key>`.
Only the explicitly named report is considered. Exact selected catalogue pin and
fenced native metadata token/library UUID must agree to expose current unmatched
counts (`matches_selected_sources`). Changed input is `historical`; unavailable
library reads are `unconfirmed`. In either case current unmatched is null while
original saved counts and pins remain available. Metadata tokens include file stat
identity and streamed SHA-256 digests of the complete database and WAL. Both WAL
reuse and checkpointed database pages can change beyond an unchanged fixed prefix.
Copying hashes the actual captured chunks and requires their digest to match the
observed source before admitting the private copy; final complete-source checks
retain the same identity. Hashing shares the existing 512 MiB aggregate metadata
cap and three-second deadline. It never opens original SQLite state for recovery
or writes source SHM. Warm requests reuse one private copy while re-reading both
source files to establish current metadata identity.
Pre-upgrade tokens remain in historical reports and need a new scan for current
claims. This is a check-time metadata
claim under the caller's selected catalogue, never a file-identity or active
producer claim. It does not switch the user's catalogue pin.


### Durable reconciliation and independent book checks

`POST /api/library/reconciliation-jobs` queues a complete metadata observation.
Send `Idempotency-Key: <UUID>` and a JSON object containing `version`, `sha256`,
`inventory: {"token": "<recorded token>", "library_uuid": "<recorded UUID>"}`,
and optionally `previous: "<saved reconciliation UUID>"`. No inventory scan or
catalogue/file read runs on this request path. The worker requires the selected
inventory to remain unchanged and publishes its complete report and job result
in one fenced transaction. The historical report UUID equals the request key;
existing `/api/library/reconciliations` readers expose its pages.

`POST /api/epub-inspections/<inspection UUID>/checks` queues independent declared
identity and original-EPUB duplicate observations. Its exact JSON fields are
`source_sha256`, `report_sha256`, `version`, `sha256`, `catalogue_work_id` and
`reconciliation` (one explicit saved reconciliation UUID). Optional
`comparison_inspections` selects at most eight distinct completed inspection pins,
each `{job_id, source_sha256, report_sha256}`. No latest report is inferred. The completed
inspection, reconciliation, selected catalogue bytes and current library inventory
must agree. Preserved uploads without a native origin instead use the explicitly
selected reconciliation as the target inventory and exclude no library record.
Package declarations supply work/edition evidence; a matched Calibre
record cannot replace missing or conflicting EPUB declarations. One globally
unambiguous ISBN ownership plus matching title/creators can support declared work
identity; edition support additionally needs one explicit EPUB edition. Neither
establishes content authentication or language/content equivalence.

Both endpoints return 202 with the existing job envelope. Recover a potentially
accepted request with `GET` on the same route and exactly `request_key=<UUID>`;
no implicit latest job is selected. Replay the same POST/key safely even when
sources are unavailable. A reused key with different inputs, another active
identical intent, changed sources, or incompatible engine policy refuses rather
than silently reinterpreting work. Normal `/api/jobs/<job UUID>` progress/cancel
and paged history support both `library_reconcile` and `book_assessment` kinds.
Requests require CSRF and JSON, reject repeated fields/parameters and exceedance
of the 4 KiB body limit, and return private `no-store` responses.

The independent worker renews its lease while observing sources. Cancellation,
expiry or replacement prevents publication; crashes retry the bounded observation
under a new lease, up to the existing three-attempt limit. Captured engine policy,
input fingerprint and source/report/catalogue/inventory bindings are retained.
Completed assessments have an additional result fingerprint. Generic Progress
recognizes the new kinds and opens their existing record rather than a synthetic
work; dedicated check controls and broader UI remain deferred.

The assessment v3 duplicate census covers all recorded formats in at most 10,000
library records and 20,000 format rows. It reads actual file sizes, hashes
same-size candidates only, and bounds total streamed bytes to 256 MiB and the
assessment to 120 seconds. `duplicates.scope=all_recorded_formats` includes
`recorded_files` and the EPUB subset `epub_files`; exact matches retain the literal
format. Only the native source's EPUB is excluded. Another format on that same
record remains a candidate. Missing, unsafe, changed, ambiguous or unreadable files
and exhausted budgets prevent a complete byte census claim. Unrecorded files are
outside this scope. Other-format `byte_comparison` reports whether the byte scan
completed, while `status=unconfirmed` retains their content/semantic uncertainty.
Different sizes/bytes exclude exact copies only; no PDF/MOBI/AZW3 text is parsed or
converted. Incoming files exclude no native record. Metadata UUID/token and final
file fences retain the observation's historical scope.

Preparation optionally takes `assessment=<completed check job UUID>` alongside
its existing exact source/report/catalogue/work query. It accepts only an explicitly
selected bound assessment, exposes its recorded conclusions and date, and keeps
current bytes `not_checked`. Selecting an assessment does not perform a live
recheck or choose the latest result. Content identity, semantic duplicates,
historical evidence and writer authority remain explicit admission blockers:
`correction_admission=held`, `ready=false`. No derived artifact or writer is added.

These jobs need schema 0007 and coordinated web/worker images. The worker now needs
explicit read-only native library and catalogue access for these selected checks,
and private artifact access for assessment. Base/default deployment roles remain
unchanged; follow [the packaging contract](packaging.md#schema-0007-durable-library-checks)
before enabling any target role.

### Preserved content evidence and incoming assessments

Inspection policy v6 adds `content_evidence` under
`librarium.epub-content-evidence.v1`. It records a SHA-256 of the ordered full
XHTML spine body source text and a length-framed hash of ordered spine resource
bytes. Unicode whitespace and block/document boundaries normalize to spaces;
case/punctuation and inline text joins remain. Non-linear, hidden and script/style
source text is included; no visibility inference or prose sample is returned.
The existing isolated parser and archive/XML/output budgets apply. Failed,
incomplete, ambiguous, unsupported or empty/media-only evidence has no fingerprint.
The saved-report boundary revalidates content binding, shape and bounded counters.
Completed policies v1–v5 remain readable; they do not acquire content fingerprints.
Pending older inspection/check engines refuse reinterpretation and require a new
explicit request. No schema change is needed.

Assessment policy v3 retains v2 incoming/native provenance and exposes selected
`content_identity` in historical preparation. Incoming `current_library_bytes`
is `not_applicable`; this is never a claim about a current source-library file.
Only native origins bound to the same reconciliation/library/inventory may exclude
their originating EPUB from exact-copy checks. Invalid/foreign origins refuse.

`duplicates.content` compares only the explicitly selected preserved inspections,
retaining their source/report/inspection/content-policy pins, historical origin
membership, declared work/edition support and `same`/`different`/`unconfirmed` text
relation. Candidate preserved-source reads share the 256 MiB assessment byte budget.
An orphan origin stays unconfirmed rather than supplying library membership.
Equal normalized text is a possible content duplicate; differing text does not
exclude another rendition, edition, preview, omnibus or semantic duplicate.
These selected reports never establish complete semantic coverage, current library
bytes, media equality, content authentication or writer admission.

Assessment v3 also derives `resource_overlap` from the existing v6 saved report's
source-bound spine/resource digests. It records exact shared XHTML resource bytes,
with both source paths/spine indexes and the common digest, one-to-one occurrence
counts, directional resource-multiset containment and `pairing_order_preserved`.
That order describes deterministic first-unused occurrence pairing, not an optimal
subsequence alignment. At most 64 matches are retained per comparison; full counts
and `truncated` disclose omitted details. No source prose or new extraction is
added. Missing/invalid digests, ambiguous paths, failed/incomplete captures or
historical policies leave resource evidence unconfirmed. Shared resources, including
boilerplate, supply possible duplicate leads even when whole-text hashes differ;
resource containment cannot establish narrative/whole-book containment. A repeated
inspection of the same validated native origin remains origin evidence and does
not count as another duplicate. No shared resources never clears semantic overlap.
Completed v1/v2 assessments remain readable under their saved policies; pending v2
assessments require a fresh request rather than silent upgrade.

Independent content authentication remains open. The [source-contract assessment](research/content-authentication-2026-10-29.md)
defines the next title/credit capture and corroboration slice, separately from
complete narrative authentication and an independently trusted review/reference.


## Source title and credit attribution

Inspection v7 adds `source_attribution` with observation policy
`librarium.epub-source-attribution.v1`. The isolated child consumes already bounded
XML trees, independent of package declarations/catalogue selection. At most eight
observations from the first four spine entries retain resource SHA-256, spine index,
preorder source element position and selection rule. `source_element_count` bounds
locators per document. Labels are at most 256 characters (and obey tighter captured
metadata limits); each observation retains at most 16 credits. Limits cause unknown
evidence rather than silent truncation or a partial identity claim.

Semantic `titlepage` blocks with marked title/author labels are candidate container
observations. Unclassified early headings are leads only. Narrative boundaries,
navigation, advertisements, previews and inline hiding prevent later story evidence
from being promoted. Explicit DPUB-ARIA narrative/navigation roles are also honored;
role definitions follow [W3C DPUB-ARIA 1.1](https://www.w3.org/TR/dpub-aria-1.1/).
CSS rendering, image/OCR, class-only titlepage interpretation and complete content
authentication remain unsupported. Failed structural inspections clear capture. Unsupported label characters use
the same capture/report-validation predicate: attribution becomes unconfirmed
without discarding an otherwise complete structural report.

The existing explicit package-comparison endpoint retains its v3 metadata contract
and adds independent `source_attribution` under
`librarium.source-attribution-comparison.v1`. It binds job/source/report,
observation policy, catalogue version/digest and selected work. Complete title and
all-author evidence can corroborate attribution; conflicting, repeated/ambiguous,
missing/partial and historical evidence retain their separate states. The catalogue
is one bibliographic lineage. `whole_file_identity` and `content_authentication`
always remain `unconfirmed`; no OPF agreement substitutes for source capture.

Assessment v4 and explicitly selected correction preparation carry this separate
result while preserving all content/semantic/writer holds. Content-text/resource
comparisons accept eligible v6 and v7 captures. Completed v1–v6 inspections and
v1–v3 assessments retain historical data; pending old engines refuse reinterpretation.
The browser binds/discloses new evidence and historical absence without requesting
new work implicitly. No migration, dependency, default role or deployment changes.

## Normalized document text overlap

Inspection v8 retains the existing whole-spine content and source-attribution
policies and adds `document_text_evidence` under `librarium.epub-document-text.v1`.
Each ordered XHTML spine body has a normalized source-text SHA-256, character
count, spine index, path and original XML resource SHA-256. Normalization follows
content-evidence v1: Unicode whitespace and block boundaries become spaces,
inline text joins remain, and case/punctuation remain significant. Non-linear,
hidden and script/style source text is included. This is source text, not rendered
appearance or narrative interpretation. Rows contain no prose.

The isolated parser charges each row to its existing record budget. XML, source,
process and output limits remain unchanged. Failed, incomplete, unsupported,
ambiguous, empty or over-limit captures retain no partial rows. Saved-report
validation checks exact source/policy/scope, spine order, paths, resource/media
binding, bounded typed counts and agreement with the whole-spine character total.
Completed v1–v7 reports keep historical absence; pending older inspections require
a new request rather than silent reinterpretation.

Document text is optional evidence. Structure, whole-spine fingerprints, source
attribution and contents planning use their budgets first. When the additional
document rows would exceed the remaining record/output budget, only that capture
becomes unconfirmed with `record_limit` or `output_bytes_limit`; it does not
manufacture a structural failure or erase existing evidence. The normal fatal
limit still applies when the required structural report envelope itself cannot fit.

Assessment v5 adds `duplicates.content.comparisons[].document_text_overlap` for
the existing at-most-eight explicit inspection pins. It pairs equal document text
digests and character counts one-to-one, retaining both source locations and
resource digests. This finds matching text after markup changes even when full
text and resource-byte comparisons differ. It records directional document-text
multiset containment and deterministic first-unused pairing order, rather than
an optimal subsequence alignment. At most 64 match details are returned; complete
counts and `truncated` disclose omitted detail. Historic/malformed/unconfirmed
capture produces no match claim. A same-native-origin inspection does not count
as another duplicate; repeated comparison candidates cannot inflate occurrences.

Matching document text, including boilerplate, contributes a possible duplicate
lead. Document boundaries can hide overlap when chapters are split or merged.
Neither equality, containment nor zero matches authenticates complete content,
excludes semantic duplicates or admits a writer. Other-format content remains
unconfirmed. Completed v1–v4 assessments retain their original scope and pending
older engines refuse upgrade. No schema, dependency, parser format, mount, role
or endpoint changes were introduced by v5 itself. The browser accepts and binds
v8 while retaining existing identifier/title-credit disclosure. The candidate
assessment workflow below supplies explicit comparison controls.

The maintainer selected locally curated references with documented provenance.
The following contract implements that route independently of text overlap.
Broader semantic and non-EPUB extraction and writer admission remain separate
work. The [corrected-output backend](#corrected-output-backend) independently
validates saved review copies without changing assessment claims.

## Curated-reference authentication and assessment history

Assessment v6 adds `reference_authentication` under
`librarium.content-reference-authentication.v1`. Ordinary checks remain usable
without a reference: the saved status is `not_requested` with
`reference_not_pinned`, and that execution never reads the trust configuration.

Configure `LIBRARIUM_CONTENT_TRUST_REGISTRY` and
`LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256` together outside the checkout. They
select exact independently approved registry bytes. A request can select only
`reference_id`, `registry_sha256` and `manifest_sha256`; its digest cannot create
a trust root. The registry's parent is the store. Its fixed leaves are
`manifests/<digest>.json`, `evidence/<digest>` and `artifacts/<digest>`.
The [trust record contract](research/whole-file-trust-and-format-evidence-2026-10-29.md#first-implementation-contract)
owns the exact fields; [packaging](packaging.md#candidate-assessment-roles-and-curated-references)
owns container configuration.

The verifier reads bounded regular files without following symlinks. Files must
have no write bits unless their filesystem is read-only. It refuses a store
overlapping application artifacts, the native library or catalogue-production
state, detects changes during reads, and validates strict JSON, exact field sets,
lowercase digests, aware times, authority scope, expiry and revocation. Reference
artifact bytes and every acquisition/publication/coverage evidence digest must
match present files. This verifies bindings to the operator's approved curation;
the application does not decide that arbitrary receipt text establishes provenance.

`authenticated_reference_match` requires exact reference bytes and supported
complete-work coverage. A standalone reference covers its selected work at
position one. Collections require at least two distinct constituent work IDs,
excluding the container, at consecutive positions; every constituent must exist
in the assessment catalogue. The original reference catalogue pin remains
provenance. The current assessment independently pins a catalogue containing
the same exact work ID; missing or merged IDs refuse association. Edition claims
are omitted when that edition no longer belongs to the current work, without
discarding otherwise valid whole-work authentication.

The saved result separates the current `catalogue` from original
`reference_publication`. It records exact source/report/reference/registry/manifest
pins, authority, supported claims and one execution-time `checked_at`.
`different_bytes` reports inequality with that reference; it cannot exclude
narrative equivalence. Unavailable, malformed, stale or unsupported references
yield `unconfirmed` with bounded reason codes. A positive result removes only
`content_identity_unconfirmed`: semantic duplicate and writer holds remain,
`ready` stays false and correction admission stays `held`.

`GET /api/content-trust/references?version=&sha256=&work=` requires exactly one
of each parameter. Discovery reads registry/manifests only, returns at most 64
advertised references, and distinguishes `available`, `not_configured` and
`unavailable`. Advertised claims are not authenticated claims. Paths, private
evidence, receipts and raw exceptions are never returned. The selected worker
check determines which claims actually hold.

The existing check POST accepts an optional exact `reference` pin alongside its
source/report/catalogue, saved reconciliation UUID and explicit comparison pins.
Keep the request UUID in `Idempotency-Key`. Enqueue and same-key recovery read no
trust files. Execution captures the authentication policy in the input fingerprint
and refuses pending v5 assessments; completed v5 results retain their historical
scope. Preparation carries the explicitly selected saved authentication result,
or `not_assessed`, without running authentication again.

Both `/api/epub-inspections/<source-id>/checks?page=N` and
`/api/library/reconciliation-jobs?page=N` expose explicit pages of 24 jobs.
The `page` parameter is required and cannot combine with `request_key`.
History rows contain `result_summary`, not full `result`; fetch a selected job
through `/api/jobs/<id>` or its existing request-key recovery endpoint. Captured
catalogue/source/reference fields are returned where available; sparse historical
fields remain `null`. `/api/library/reconciliations` additionally accepts paired
`version` and `sha256` filters with its existing page parameter. None of these
readers selects an implicit latest assessment or runs new checks.

### Candidate assessment review workflow

Open a preserved inspection and explicitly compare it with a selected catalogue
work. The assessment panel offers matching saved reconciliations, with paging,
or an explicit durable reconciliation against the current native inventory.
Choose a saved reconciliation before starting a check; the first row is never
selected automatically. Request history, progress and cancellation stay available
while a worker runs. Completed reconciliations refresh the saved choices without
replacing the reviewer's selection.

Select up to eight completed preserved inspection pins and, optionally, one
advertised curated reference. Inspections outside the loaded recent jobs can be
retrieved by their explicit inspection UUID. Loading a comparison does not select
it. Reference discovery lists advertised claims; only the recorded assessment
supports authentication claims. An unconfigured registry leaves ordinary checks
usable. Each changed selection requires a new request key.

The browser preserves uncertain request intent across reload. Request-key lookup
can recover an accepted request without sending another POST; an unrecorded
request remains explicitly unconfirmed and can retry the same captured intent.
Retrying that saved intent does not require choosing coverage again. Selecting
another historical record aborts local pending reads without cancelling server
work or losing its recovery key. Revision fences keep late responses from
replacing a newer cancellation or record choice.

Results show declared work/edition evidence, source attribution, reference claims
and original publication provenance, exact-byte/other-format observations and
explicit resource/document-text overlap leads. Historical absence remains
unrecorded. Preparation reads the chosen saved assessment and its captured
catalogue/work pins. A native byte recheck is an explicit action; incoming uploads
have no current native path to recheck.

Global Reviews exposes both check kinds through an explicit kind filter. Selected
check IDs are URL-backed even outside the visible page; a bound assessment reopens
its preserved inspection and exact saved check without repeating catalogue search.
Sparse historical records disclose missing context. Returning to Reviews restores
the originating row's keyboard focus, including on desktop. All these controls
write only application job state; no book transformation or library writer is
connected.

## Library write core (retained; no longer orchestrated)

[L055](decisions.md#l055-conditionally-replace-one-epub-through-a-synthetic-sole-owner-writer)
and [L060](decisions.md#l060-delivery-through-the-owning-calibre-content-server)
built a disabled synthetic writer boundary. [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them)
retired what fed it: corrected copies no longer exist, so the web and worker no
longer prepare, approve, dispatch, reconcile or undo a delivery, and the dedicated
`delivery_worker` and every delivery route are removed. The writer core stays,
unreached by the application, as Librarium's library-write path until the owner
decides it: `delivery_broker.py`, `delivery_writer.py`, `delivery_content_server.py`,
`delivery_session.py`, `delivery_authorization.py`, `delivery_client.py`,
`delivery_recovery.py`, `delivery_native.py`, `recovery_evidence.py` and the
separate `Dockerfile.writer` image. `delivery_contract.py` keeps only the policy
name the writer binds into grants and receipts. The stored delivery tables, their
append-only guards and the job-kind constraints are unchanged (migrations 0008 to
0010 are untouched), so no stored evidence is rewritten.


`delivery_broker.py` owns a separate SQLite journal, not Calibre library SQL.
FULL-synchronous transactions persist prepared/send-started/receipt evidence.
Server reads, the digest fence, added_formats replacement and read-back compose
under the broker's local lock; Calibre owns the remote cache lock. Comparisons use the target book identity, EPUB digest/size
and metadata baseline; the library inventory token is diagnostic evidence only.
Expired or restart-stale delivery grants and changed-source fences are durably
sealed as not applied before releasing reservations. A prepared record with no
send-started event also proves no send, even if the current target cannot be read.
Review expiry, writer identity and supervision freshness are checked again before
send intent and immediately after the final observation, before replacement.
Expiry during slow preflight reads seals a not-applied receipt without sending;
this remains true if send intent was already recorded. The operation and session
stay consumed. Failure to commit that receipt after send intent retains the normal
uncertain-send hold. `test_delivery_writer.py` covers these fences for delivery
and Undo with a controlled clock, including restart and exact-key replay.
Absence and timeouts alone never prove not applied. Recovery and explicit checks
use signed cancellation to seal absent operations before a late sender can run.
New Undo grants bind the durable journal identity, with a null boot nonce and signed approval time after this owner boot, so an
ordinary owner restart does not invalidate a new guarded Undo. Expiry, target
fences and consumed operation IDs still apply; old boot-specific grants seal.
Missing or torn journals hold. Before-send free-space and journal-size limits hold
without pruning. The broker retains uncertain target reservations independently
of application leases. Applied receipts are historical proof; later target EPUB or metadata drift is
separately reported. Never-sent receipts remain not applied after later edits.
Historical checks cannot recapture a released reservation or block a newer delivery.
An uncertain Undo keeps its existing reservation through explicit outcome checks.
A write job that exhausts its recovery attempts fails with `recovery_exhausted`,
keeps the reservation and still names its `delivery_id`, so a reload can run Check outcome.
A check records the projection revision before choosing what to observe. If a newer
delivery or Undo outcome advanced the projection before the check publishes, its
receipt is appended as historical evidence only; the current state, latest receipt
and reservation stay unchanged.
Dispatcher refusal seals preserve `error_code` and append a `writer_refused` event
with its reason; they never invent a reviewer `stop_requested`. Broker reasons
`sealed_after_refusal` and `sealed_before_send` distinguish refusal and automatic
sealing from reviewer `cancelled_before_send`. Saved evidence jobs can succeed
with a refusal code; classification and verified receipts still own the outcome.
Undo preserves the freshly reviewed current
metadata and refuses any different current EPUB. An unobserved or ABA outcome
never becomes a false negative receipt.

The active writer uses `delivery_content_server.py` through the existing broker
transport interface (`observe`, `prepare_write`, `replace`, `sync`). See
[L060](decisions.md#l060-delivery-through-the-owning-calibre-content-server).
LF's added_formats route replaces one EPUB through the existing server owner.
Read-only remote export returns original stored bytes; normal downloads rewrite
metadata. Observations bind server library UUID, book UUID, metadata, cover and
other formats. Derived `pages`, format size/mtime and download URLs are excluded
from the metadata digest because server maintenance recomputes them. All other
exposed metadata fields remain bound. The observation inventory describes this target, not the whole
library. Server startup housekeeping belongs to the incumbent server; the writer
never opens another cache. The old native adapter is a synthetic test oracle only.

Each content-server request shares one 45-second monotonic deadline across its
anonymous authentication probe, Digest/HTTPS Basic challenge retries, address
attempts, TLS handshake, response headers and bounded body read. Socket waits
also retain a maximum 15-second inactivity timeout. A request-scoped watchdog
shuts down registered sockets, including those retained by urllib's response
reader, and is cancelled and joined before return. Expiry is checked before
sending and after reading/decoding, so interrupted EOF cannot authenticate a
probe or turn a partial JSON response into success. Errors remain redacted as
`server_unavailable`; existing uncertain-send holds and no-resend recovery apply.
Synchronous system DNS resolution cannot be interrupted by this socket watchdog.
Expiry after resolution prevents a later connection/send, but the lookup itself
can exceed 45 seconds. Numeric loopback HTTP avoids this resolver limitation.
See the [deadline regression evidence](http-deadline.tdd.md).

Grant sessions are verified by the writer core. A session file is an owned
mode-0600 JSON file with exactly `session_id` (fresh UUID), `target` (library
UUID, book ID, book UUID), `confirmed_by` (the authenticated operator),
`confirmed_at` (timezone-aware ISO 8601, within five minutes), and
`other_writers_stopped: true`. Creating it is an explicit operator confirmation,
never inferred by the application. The broker consumes each session for one
operation. Originals, outputs and journals remain retained indefinitely. No
application role creates approvals or sessions now.


New content-server deliveries and Undo also require a verified recovery baseline
through `LIBRARIUM_DELIVERY_RECOVERY_DIR`. Offline verification binds the captured
backup to the session, library and journal; the writer persists operation recovery
evidence before intent and rechecks it before replacement. Historical outcome
checks remain observation-only without that baseline. See the
[recovery contract](delivery-recovery.md) for preparation and operator boundaries.

The server has no atomic digest compare-and-swap: supervision covers the remaining
read/write race. A mismatch or uncertain send latches a global journal hold across
all targets and restarts; reconciliation observes without resend and never clears
that hold. The independent read-only mounted-library check retries at most three
times for an inventory change or busy read, with a short bounded backoff. Persistent
uncertainty sends an authenticated `/v1/hold` to latch the writer too. Byte/identity mismatch is never retried.
Recovery release remains a reviewed offline procedure, with no reset endpoint.
Remote read-back cannot certify storage capacity, fsync or whole-library preservation. Plugins run on this route; a changed output digest diverges and holds.

The writer verifies the grant seal, expiry, runtime/epoch, retained original,
replacement and saved validation before a new operation. Requests cannot nominate
paths, formats, commands, library roots or trust authorities. See the
[role contract](packaging.md#synthetic-writer-role) for configuration and limits.


Native acceptance is explicit: set `LIBRARIUM_CALIBRE_RUNTIME` to the verified
isolated runtime and run `tests/test_calibre_delivery_gate.py`,
`tests/test_delivery_native_kills.py` and `tests/test_delivery_content_server_native.py`
(in an isolated network namespace with loopback enabled). The latter starts an
authenticated real server and proves transformed outputs, lost replies,
changed-byte refusal and SIGKILL during format copy for delivery and Undo.
Ordinary unit runs may skip these tests without the runtime. The required
`.github/scripts/delivery_native_acceptance.sh` gate refuses missing runtime,
libarchive, EPUBCheck, Java or PostgreSQL inputs. The native-role CI job downloads
Calibre, checks the official SHA-512 and reviewed SHA-256 before extraction, then
runs the proofs. A separate image job builds the writer target, checks its
disabled entrypoint and runs real cache/broker and SIGKILL vectors in that image.
Native gates never use the distro Calibre. Their synthetic EPUB comes from
`.github/scripts/synthetic_epub_fixtures.py`. The earlier end-to-end HTTP proof
needed the removed web, dispatcher and correction roles and is gone with them.
Native kill tests mirror all six boundaries for delivery and Undo, including the
actual copy loop. Deterministic fault tests cover failed durable transactions at
prepared/send/receipt publication and full storage; they are not physical power-loss proof.


A never-sent receipt can include a separate `present` observation and
`present_drift` without changing its historical classification. New Undo approval
time must fall between the current owner boot and its current clock time; old
pending grants seal after restart/restore. This synthetic same-host protocol
assumes a non-rolling-back shared wall clock; a distributed clock/fencing design
is part of the unapproved live topology.

Principal audit digests for new delivery and Undo approvals use
`HMAC-SHA256(K_sign, b"librarium.principal.v1\0" + principal_utf8)`, distinct from
grant signatures. Existing synthetic approvals keep their immutable historical
digests; they are never compared to authorize replay, reconcile or Undo. Grant
signatures and row fingerprints are unchanged, so no migration or reset is needed.

## Recorded author discovery

[Alias discovery evidence](author-aliases.tdd.md) owns the pinned group contract,
compatibility states, failing-first regression and unchanged query budgets.
Run `backend/tests/test_author_discovery.py` with the existing catalogue,
package-comparison, attribution and library-matching tests under warning-strict
pytest. Frontend author-group and source-comparison journeys exercise decoding,
request binding, return context and reconnect. The portable synthetic fixture
and browser helpers document fresh disposable-state acceptance without a writer.

## Python child sandbox

Inspection uses a fresh Python child (correction eligibility, generation and
independent preservation were retired by L091). Before reading archive bytes
from an owned stdin pipe, it preloads trusted domain modules, pinned libarchive,
XML/ZIP support and all 120 Linux encoding modules (Windows-only `mbcs`/`oem`
are excluded). ElementTree/pyexpat uses Python codecs for legacy single-byte XML;
these fixtures do not use libxml2, iconv or glibc gconv converters. The preloaded
codec registry preserves unknown-encoding `invalid_xml` findings without lazy
module probes. Existing unsupported multibyte declarations retain the same input
findings. No encoding policy or verdict is changed.

Children install seccomp, `no_new_privs` and Landlock with **zero filesystem
grants**. No interpreter, stdlib, site-packages, native library, scratch or state
directory remains readable or writable by pathname. Output is bounded pipe-only;
only the parent publishes artifacts. After restriction, a Python audit hook and
module-finder guard terminate any new import with `sandbox_late_import` (exit 24),
even when an optional-import handler catches exceptions. Cached imports remain
usable. This is a dependency-completeness guard, not protection against arbitrary
native code already executing inside the process.

The x86-64 implementation requires Landlock ABI 3+. It applies the rights masks
checked against upstream ABI 3–12 headers, clamping newer kernels to ABI-12 rights.
Parent preflight returns and logs observed/effective ABIs in runtime evidence.
Filesystem rights add device ioctl at ABI 5 and pathname UNIX socket resolution
at ABI 9; network rights cover TCP at ABI 4 and UDP at ABI 10. At ABI 6+ both signal
and abstract-UNIX-socket scopes are requested. ABI-12 generic namespace/capability
permissions are not requested; seccomp separately denies namespace creation and
joining. Other supported ABIs have
construction tests, including future ABI 13/99. See the
[kernel Landlock documentation](https://github.com/torvalds/linux/blob/master/Documentation/userspace-api/landlock.rst).

The shared seccomp filter returns EPERM for `socket`, `socketpair`, `socketcall`
where present, `connect` and `io_uring_setup`. It now refuses unresolvable mandatory
syscall names or an unavailable libseccomp library, including for Java. Java's
syscall set, runtime/scratch Landlock grants and captured policy stay unchanged.
Python additionally denies `setsid`, `setpgid`, `fork`, `vfork`, `execve`, `execveat`,
`unshare`, `setns`, credential-changing syscalls and `prctl(PR_SET_PDEATHSIG, ...)`.
`clone` without `CLONE_THREAD` returns EPERM; `clone3` returns ENOSYS so glibc can
fall back to inspectable `clone` flags. Threads remain possible, inherit the
restrictions and stay inside the process group. The fixture corpus also passes
with all clone calls denied: those tested native workloads do not need threads.

Parent platform/Landlock/seccomp preflight runs before launch and never restricts
the parent. Safe unavailable codes are `sandbox_platform_unavailable`,
`sandbox_landlock_unavailable` and `sandbox_seccomp_unavailable`. Child exits 20–22
after successful preflight mean `sandbox_setup_failed`, not proof that the host
is unsupported. Setup exit 23 and import exit 24 remain child-origin diagnostic
claims and can be forged by compromised native code; they never record a verdict.
There is no unsandboxed fallback or environment bypass. Direct domain helpers remain
unsandboxed; production paths use isolated launchers.

Resource ceilings, deadlines, heartbeats and attempt limits remain unchanged.
The FD-free watcher starts before restriction and kills the original process
group if its parser dies. Parent-death SIGKILL cannot be cleared via prctl or
credential changes after restriction, and children cannot fork or leave the
group. Cleanup covers that group and its threads; it is not a cgroup-wide process
sweep or protection from kernel compromise. On ABI 3–5, Landlock has no signal
scope, so same-UID signal isolation is weaker than on ABI 6+. Landlock does not
revoke inherited descriptors, hide all pathname metadata (`stat` may succeed),
or isolate memory from the kernel. Launchers close unrelated descriptors.
Runtime installation integrity remains a prerequisite.

Tests cover real-launcher file/socket denial, import-guard regressions, kernel
signal/process/exec/namespace denials, thread compatibility, failure jobs and
byte-identical results across 21 encoding/name fixtures. The same corpus runs with thread creation denied. Fresh-interpreter
measurements (nine runs, warm filesystem cache) gave median 85 ms for the prior
preload plus 51 ms for codec preloading and the frozen registry; cold-storage cost was not measured.
The kernel probe requires support in CI; local ABI-specific skips are explicit.
Hosted actual-image replacement/restore and selected-kernel acceptance remain
separate gates. [TDD evidence](python-child-sandbox.tdd.md) records local checks.

## Delivery evidence database guards

[L062](decisions.md#l062-postgresql-guards-and-a-separate-runtime-login) adds migration
0010. Raw TRUNCATE (including CASCADE), bulk UPDATE and bulk DELETE cannot erase
immutable delivery evidence. The six immutable tables keep SELECT/INSERT runtime
access; DeliveryState remains mutable but cannot be truncated. Migration 0010
reverses only while no guard maintenance has been recorded, so test and fresh
schemas can roll back but real maintenance history is never dropped. Existing
evidence needs no data rewrite.

Use a dedicated, disposable PostgreSQL cluster or databases for
backend/tests/test_evidence_guards.py. These real-PostgreSQL tests create and drop
roles prefixed librarium_guard, prove owner and runtime denials, and exercise
atomic Django flush and rollback. The suite needs an administrative login with
CREATEROLE and permission to grant SET on session_replication_role; by default it
uses the test connection's login. LIBRARIUM_TEST_ADMIN_USER optionally selects a
separate administrator on the same test database. Never run these checks against
an application database. Tests that use a custom test database name must configure
DATABASES.default.TEST.NAME explicitly.

Only librarium.test_settings enables the test PostgreSQL backend. It temporarily
disables the TRUNCATE guards within execute_sql_flush's transaction and restores
ENABLE ALWAYS before commit. Row guards stay active. Test bodies still exercise
the production guards, and failed cleanup rolls back the disabling. Ordinary
settings use Django's normal backend; manage.py flush refuses there. Keep test
settings and owner credentials out of application processes.

Owner maintenance requires separate authorization, a verified backup, stopped
runtime processes and a private external operation record. Record the intended
tables and purpose before making changes. The following SQL illustrates a single
table operation; substitute only the explicitly approved scope. No CASCADE or
DISABLE TRIGGER ALL is needed. The maintenance table's own guards stay enabled.

```sql
BEGIN;
LOCK TABLE librarium_deliveryevent IN ACCESS EXCLUSIVE MODE;
INSERT INTO librarium_evidence_maintenance(reason, tables)
VALUES ('Approved operation reference and purpose', ARRAY['librarium_deliveryevent']);
ALTER TABLE librarium_deliveryevent DISABLE TRIGGER librarium_evidence_no_truncate;
-- Perform only the approved maintenance or restore operation here.
ALTER TABLE librarium_deliveryevent ENABLE ALWAYS TRIGGER librarium_evidence_no_truncate;
-- Verify all affected guard states and restored evidence before COMMIT.
COMMIT;
```

Use psql with ON_ERROR_STOP=1. Any failure must roll back the entire transaction;
never commit disabled guards. Keep the external record of failed/rolled-back
attempts, which cannot survive in the same rolled-back database transaction.
Capture transaction_id, actor and affected tables from the committed maintenance
record privately. The owner can deliberately defeat database guards through DDL;
the runtime role cannot. No pruning or ordinary evidence deletion is authorized.

TDD evidence: the initial owner-TRUNCATE/guard-state run executed eight failing
regressions before implementation. The focused suite verifies empty-table and
CASCADE refusals, two-row UPDATE/DELETE refusal in origin/replica modes, runtime
DML and privilege denials, recorded maintenance, production flush refusal and
successful/failed test flush restoration. CI owns the full-suite run.


## Preserved book workspace

The preserved inspection UUID (`fj`) identifies one continuous book task. Existing
`fv` validation, `fa` assessment and `fcw`/`fcv`/`fch` prospective comparison pins
remain explicit. Selections never imply approval.

Saved routes can still name the pins of retired work (L091): `fg` (review copy),
`fo` (its output), `fov` (an output check), `fdp`, `fd` and `fdj` (delivery). They are
accepted and dropped, never served, so a saved book opens at its nearest kept
ancestor. `faj` and `fda` (an assessment shown beside a copy) become `fa` when that
assessment still matches the inspection and are dropped when it does not.
Malformed identifiers still refuse with 400.

`GET /api/epub-inspections/<source>/workspace` resolves supplied selections against
recorded source/report digests and related validation and assessment records.
Unknown, malformed, foreign or impossible combinations refuse visibly. It projects only
safe recorded context and the selected relations, without raw inputs, storage paths or
external Library reads. It no longer returns `output` or `delivery`.

`GET /api/book-workspaces/resolve?job=<uuid>` reconstructs exact recorded ancestors
for Reviews. A retired job (a review copy, an output check or a delivery record)
resolves to its preserved inspection, and to the assessment its request was bound to
when that still matches. It reads only the record's integrity-checked input and the
stored `CorrectedEpub`/`DeliveryIntent` source links, never a report. A missing or
changed record is refused with the usual not-found or changed message, never a 500.

`GET /api/direct-library/books/<book>/workspaces` pages recorded inspections by
Library UUID and book ID. An explicitly supplied inventory token distinguishes
matching recorded inventory from older work; neither establishes current file-byte
agreement. Resume reopens an exact preserved source. Starting an inspection remains
an explicit separate action under the existing idempotent capture contract.

An absent recorded Library identity remains honest historical context, readable
through Reviews. Resume pages retain their total historical count and disclose
the number of unavailable rows on that page; a bad row cannot hide valid sources.
Opening an unavailable source still refuses under the strict source checks.

Library, reference browsing and Reviews retain their return context. Active book
tasks display only source-scoped history, with global history and incoming upload
available through their own entry points. Historical results stay readable when
original inputs are unavailable; fresh comparison requests still require
valid explicit pins. See [verification](unified-book-workspace.tdd.md).

## Retired job records

Rows of `epub_correction`, `output_validation`, `delivery_prepare`, `epub_delivery`,
`delivery_reconcile` and `epub_undo` (`librarium.retired_jobs`) stay stored and are read
as plain history. `job_data` returns only the title and counters for them: `result` is
empty, and no input, report, receipt, locator or operator identity is returned, so job
detail, list and history need no operator gate for them. Work left queued or running
reads as `cancelled` with `stored_state` keeping the database value, and it is not
counted by the active filter or the active list. History accepts `kind=retired` for
all six kinds as well as each single kind, and `state=cancelled` includes the
unfinished ones. The worker's claim list omits these kinds, and `advance` only
handles `synthetic` and `catalogue` rows beyond the check kinds. `POST
/api/jobs/<job>/cancel` (operator identity, an empty JSON object) and the ordinary
`POST /api/jobs/<job>` cancel end one without calling any removed code; the database
guards of migrations 0008 to 0010 only fire when a retired row is leased, so cancelling
is permitted. `backend/tests/test_retired_jobs.py` builds such rows directly through
the models.

## Operator support observations

The read-only `support_report` management command composes bounded job/schema,
configured storage, packaged build identity and retained isolated recovery evidence.
[The support contract](operational-support.md) owns states, privacy, bounds and
approval limits; [verification](operational-support.tdd.md) owns actual checks.
It creates no endpoint, dashboard, backup engine or recurring work.

## Populated historical-source upgrade rehearsal

[The transition procedure](populated-upgrade.md) owns the pinned sanitized schema-0005
baseline, source/image proof distinction, stopped-role capture, migration through
0012 and separate pre-upgrade recovery. `scripts/populated_upgrade.py` composes
existing application and PostgreSQL owners; `scripts/upgrade_fixture.py` generates
and verifies synthetic old/current work, including one stored retired-kind row that the
current worker must leave untouched. Consult the harness `--help` for its
explicit isolated invocation. No target is discovered from ambient configuration.

Do not replace old-engine completed work with seeded successful rows. Seeded
obsolete pending jobs are negative cases and keep their original inputs. Verify
historical IDs/keys/policies/results and every retained artifact digest/mode/owner.
Capture pre-upgrade and current generations separately, keep incompatible workers
from overlapping, and disclose the post-upgrade work lost by an older recovery.
[Verification evidence](populated-upgrade.tdd.md) records actual runs; mandatory
image checks remain distinct from local source execution. Existing beta publication
reuses container acceptance and gains no duplicate recovery marker. No release
workflow, installed application or real library is activated by this rehearsal.

## Catalogue tool health and worker status cache

`LIBRARIUM_CATALOGUE_STATUS_URL` optionally selects BLC's unauthenticated API
base. Empty disables polling and leaves the live dashboard unavailable. The
inspection worker checks the durable singleton about once per minute; web
requests read Postgres only. A process-local monotonic timer avoids database
checks on each worker tick. HTTP reads run outside transactions, and a short
lock-and-compare publication preserves a newer concurrent worker result.
Both JSON responses have a five-second shared
request budget, a one-MiB cap per response and shape checks. No credentials,
proxy environment or HTTP redirects are used. The ingest projection discards
query text, error samples and raw failure reasons before persistence. Failures
retain the last good copy and its original fetch time; more than five minutes
without a valid poll is shown as last heard. A changed API base cannot serve
another source's previous copy.

`LIBRARIUM_CATALOGUE_STATUS_PAGE_URL` independently selects the optional BLC
status-and-controls link. Empty hides it. Controls remain in BLC and require its
own authentication; Librarium sends no control requests. Configure connectivity
only during a separately approved activation; no worker egress or mount changes
are implied by these settings.

The main view uses real site navigation, one seal/sentence, a selectable seven-day
cycle band, qualified added-work plates and cover-upscale progress. One Details
disclosure retains BLC's scrubbed observations and the existing snapshot, source,
size, jobs, sync and client diagnostics. All times use the viewer's local
12-hour clock. Missing data remains unavailable; fewer qualified covers remain
fewer plates. Snapshot work IDs and explicit containment determine cover identity;
no title match can substitute artwork. Shared collection art is deduplicated.

Optional `LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR` selects a separate read-only
local blob directory for verified upscaled examples. It defaults to empty and
does not infer a sibling directory or add a mount. Derivative associations come
from the pinned snapshot's `cover_derivative` table; the existing cover endpoint
accepts `variant=upscaled` and reuses raster, digest, size and path admission.
Original cover behavior is unchanged. A missing association or blob yields fewer
examples, without substituting original artwork under an upscale label.


## Read-only cover review API

The authenticated `/api/cover-reviews` API enumerates cover work across the
whole library. `state=todo|done|skipped`, `reason` and positive `page` select a
24-entry page. Reasons are `missing`, `generated`, `blank`, `width_below_1000`,
`height_below_1200`, `small` (either size floor) or `unresolved`. Default To do
includes deficient and unresolved covers. Done contains previously flagged covers
that pass a later census; initially healthy books do not enter Done. It is an
observation, not a delivery receipt. A new problem returns a Done entry to To do.
Counts cover all reasons, while the selected reason filters the requested page.
Pages are ordered missing, generated, small, then other reasons, with stable book
ordering inside each group. Entries include authors from the same read-model
snapshot. All responses are
no-store. Authentication uses the existing server-owned `REMOTE_USER` principal;
mutations retain CSRF checks.

`GET /api/cover-reviews/suggestions` accepts one inventory token, catalogue
`version` and `sha256`, and 1–24 repeated `entry=<UUID>:<revision>` values.
The authenticated page read shares one native metadata snapshot and global
title/alias and author-ownership scans. It reuses the exact matcher, including
identifier disagreement and ambiguous-credit refusal. Each result binds its
entry revision, library/book identity, inventory and catalogue pin. Stale inputs
or changes during the read refuse the whole batch. Cover metadata comes from
the existing pinned local catalogue; books and cover bytes are never written.
The wall calls this once per visible page with the library-read deadline, and
refreshes the catalogue pin with queue polling and snapshot-error recovery.

`POST /api/cover-reviews/census` accepts `{}` and a UUID `Idempotency-Key`.
It queues one census for the existing idle worker, with no recurring schedule
or settings change. GET returns the latest census; POST to
`/api/cover-reviews/censuses/<census UUID>/cancel` cancels remaining work.
A partial census can have remaining work or unresolved observations; only zero
remaining and zero unresolved can complete. Unknown identities are reported
separately and never receive fabricated book UUIDs.

Default census slices admit at most 64 books in eight-book chunks. Set
`LIBRARIUM_CENSUS_CONCURRENCY` (Django setting `COVER_CENSUS_OBSERVATION_WORKERS`)
to an integer from 1 through 8 to select concurrent decoders. The default is
`max(1, min(4, (os.cpu_count() or 1) // 2))`, giving two on a four-CPU host.
One executor belongs to the worker process and closes on worker exit.

The main thread reads bounded cover bytes through the no-follow library reader
and computes the complete metadata database/WAL/journal token before and after
each chunk. Nothing from a changed chunk is published. Each decode still uses a
fresh resource-limited, filesystem/network-denied child. Ordered publication
retains library/book identity, cancellation and lease checks, then rechecks each
cover's stat signature and available content digest after decoding. A mismatch
leaves that book before the cursor for retry, including during final validation.
Unchanged validation covers also receive a content check. The final full-token
completion fence remains; there is no stat-only metadata cache or shared decoder.

At the 12-second slice deadline the worker stops submitting, cancels queued work,
interrupts in-flight decoder transport (which kills and reaps its child), and waits
at most 250 ms for observation threads. A still-stopping thread prevents further
submission on later ticks until it exits. Cancellation is polled while waiting.
Observation waits reserve up to one second of the slice for the closing fence
and publication. A completed prefix can advance after those checks; the
unfinished suffix stays before the cursor, avoiding repeated whole-chunk retries.
Completed observations still publish after a slow closing fence exceeds the slice,
provided all metadata, cover, identity and cancellation checks pass. Decoder
transport failures and interruptions stay pending for retry rather than becoming
terminal unresolved cover facts. A later successful tick can complete the same
census without a new request.
This bounds decoder waits, not synchronous filesystem or database operations.
Eight inputs remain the buffer bound regardless of decoder concurrency; budget
decoder capacity within the deployment's existing role limits.

For an offline performance reproduction, use
`.github/scripts/cover_census_benchmark.py prepare --library <new-fixture-directory>`
with the locked Python environment. The default creates 2,000 books, four JPEG
sizes (600x900 through 1600x2400) and 32 KiB of synthetic comment data per book.
Run `run --library <fixture-directory> --profile <local-profile-file>` with
`PYTHONPATH=backend`, a fresh migrated disposable PostgreSQL database and the
normal protected environment. Each measured run starts without saved cover facts.
It measures active census ticks through completion, excluding fixture preparation,
read-model admission and idle-worker sleeps. Before/after full fixture hashes and
every saved book UUID, image digest and dimensions are checked outside the timed
region. These setup reads warm the filesystem cache; the harness reports this
explicitly along with configured workers. They are not cold-storage measurements.
`--require-read-only` additionally asserts a read-only library mount for
actual-image acceptance. Profiles and environment configuration stay outside Git.

POST to `/api/cover-reviews/<entry UUID>/skip` accepts an exact JSON object
with `revision` and boolean `skipped`, plus a UUID `Idempotency-Key`. Conflicts
return 409 and require refetching; replaying the same accepted request returns
its original response without repeating the mutation. Healthy hidden To do
observations cannot be skipped or unskipped into Done. Previously skipped covers can still be unskipped after
a later census finds them healthy. Entry identities pair
library UUID and book UUID. A changed skipped observation keeps its skip and
sets `changed_since_skipped`. The authenticated `/cover` route beneath the
entry reads local bytes only and refuses changed identity, inventory or hash.

`test_cover_facts.py`, `test_cover_process.py`, `test_cover_suggestions.py` and
`test_cover_reviews.py` cover image policy, actual sandbox denial and PostgreSQL journeys, including
populated schema upgrades. Use the same isolated PostgreSQL and kernel/native
configuration as the existing backend suite. Re-run runtime role provisioning
after applying the new migration; no provisioning runs on request or in tests
against an installed service.
