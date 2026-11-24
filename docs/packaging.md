# Container release contract

Accepted decision: [L006](decisions.md#l006-reproducible-container-releases).
[Release policy](releases.md) owns versions, beta/stable promotion, cadence and
activation gates.
Librarium must support versioned Docker releases with Compose managing cooperating
services where needed. [The Dockhand candidate](dockhand.md) defines the portable
persistent stack and private-origin configuration. The Dockerfile is digest-pinned;
the container acceptance workflow exercises it separately from publication or
activation. Verify exact-source checks before claiming acceptance. Current installed
versions, runtime roles and target recovery evidence belong in private context.
Stable promotion and target activation retain their explicit acceptance gates.

- Build images from reviewed source, locked dependencies, and reproducible base
  image pins. Update the pins deliberately; do not maintain production by upgrading
  packages inside running containers.
- Turn supported runtime/framework updates into tested Librarium releases.
  Automated update proposals, compatibility tests, and image checks precede publication.
- Keep books, database contents, and durable job state on explicit persistent
  storage outside replaceable containers. Exclude secrets from images/source and
  preserve established library writers.
- If Node only builds frontend assets, keep it in the build stage rather than
  adding a Node backend. Choose services from the assessed application needs.
- Test upgrades, migrations, backup/restore, and supported rollback paths.
  Reverting an image does not reverse database migrations. Account for worker/job
  compatibility during deployment.
- Support Dockhand deployments on a Linux kernel that meets the [runtime requirements](decisions.md#l079-deployment-kernel-requirements). Document architecture, installation and upgrades for published images.

## Populated historical-source acceptance

[The populated upgrade procedure](populated-upgrade.md) composes existing initializer,
worker, immutable-artifact and recovery owners into one isolated schema-0005-to-0012
transition. It pins sanitized historical source/tree and candidate identities,
completes genuine old-engine work, stops admission and exact-owned old roles before
coordinated capture, migrates, reopens historical evidence and completes current
work. Separate retained generations prove current recovery and old-compatible
pre-upgrade recovery with an explicit post-upgrade loss boundary. Image-only rollback
to the old source is refused by orchestration; deleting evidence or reverse-migrating
is not a substitute.

[Verification scope](populated-upgrade.tdd.md) distinguishes source-runtime proof from
mandatory affected baseline/candidate image acceptance. A rebuilt sanitized baseline
is no original-release-image equivalence claim. Existing same-revision replacement,
EPUB restore and the retained writer core's delivery/no-resend gates remain required. This adds
no deployment, writer admission, release publication or target evidence claim;
issue #25 and issue #26 retain their unperformed target and human gates.

## Packaged application identity

The ordinary application image packages `backend/librarium/build-identity.json`
from the `identity-build` stage. `scripts/release.py build-identity` uses the same
compatibility extraction as release manifests, now shared with the runtime in
`librarium.build_identity`. It records migration leaves and the inspection and
validation policies; the generation, preservation and output-validation policies
were dropped with corrected-copy generation (L091). Runtime reads need neither
Git nor an ambient checkout. A missing, malformed, oversized or unsafe record stays
unknown; an unbuilt source checkout does not gain an image identity.

`application-source-and-assets.v1` computes SHA-256 over sorted relative names and
exact file bytes, each framed with its byte length (four bytes for names, eight for
contents, unsigned big endian). Its scope is backend runtime files, built frontend
assets, `Dockerfile`, hash-locked `requirements.txt` and the release/native-build/
EPUBCheck installer source. Tests, `__pycache__` and the generated identity record
are excluded. It binds these application inputs, rather than claiming a Git commit,
complete image-layer digest or reproducible native-binary output. The build refuses
missing required inputs, symlinks and unsupported entries. File and byte budgets
are 10,000 files and 100 MiB per file. This adds no dependency or release gate bypass.

Operator reports distinguish this packaged record, compatibility with the current
packaged policy source, and `LIBRARIUM_DECLARED_IMAGE_DIGEST`. That environment value
is a declaration only. The application cannot independently observe its container
image digest and reports it as unknown. An operator must compare the approved
release manifest and immutable digest with independent container-host inspection;
never copy a declared digest into an observed field. Release acceptance still tests
the actual built image and promotion still copies the accepted image unchanged.

## Schema 0003: catalogue review jobs

Local only; no target has run it. Migration `0003_catalogue_review_jobs` adds
`Job.kind`/`target_id`, makes `work` nullable, backfills targets and adds the
active-review and kind/target constraints. The owned job table is small (32
synthetic rows locally), so it runs as one atomic migration; tests cover the
backfill, the reverse guard and concurrent enqueue.

Roll it out as one coordinated change:

1. Drain and stop old workers before any catalogue job can be created. An old
   image cannot process the new kind.
2. Back up PostgreSQL, then migrate.
3. Start the new worker and web images together.

Reversing 0003 refuses while catalogue jobs exist. Preserve those jobs and fix
forward, or ship a new compatible image; do not delete records to roll back.
Captured metadata review jobs need no catalogue mount. The optional automatic
replica is a separate idle-worker task: see the
[catalogue sync setup](development.md#automatic-catalogue-replica). Its explicit
override grants worker catalogue writes while web keeps a read-only mount.

## Schema 0004 and preserved EPUB inspection

The local file-inspection slice adds the `epub` job kind and its active-source
constraint. Source EPUBs and full structural reports live in separate immutable,
digest-addressed app artifacts; PostgreSQL holds their bindings and compact job
results. Migration 0004 refuses reversal while EPUB jobs remain. Keep the jobs
and fix forward; deleting evidence is not a rollback procedure.

The base Compose files keep file inspection disabled. To enable it on an
explicitly selected environment, combine the chosen base with `compose.files.yaml`.
That override mounts `${LIBRARIUM_DATA_ROOT}/artifacts` at `/artifacts` for web
and worker and sets `LIBRARIUM_ARTIFACT_DIR` there. The existing catalogue mount
stays read-only and the application root filesystem remains read-only. The
artifact directory must already exist, be owned by runtime UID/GID 10001, and
have mode 0700; the application refuses unsafe ownership, symlink ancestors,
overlap with catalogue/cover inputs, and unsafe artifact entries. No library,
Calibre or source-service storage belongs in this mount.

The operator's reviewable commands are:

```sh
docker compose -f compose.dockhand.yaml -f compose.files.yaml config --quiet
docker compose -f compose.dockhand.yaml -f compose.files.yaml up -d --build
```

These are future activation instructions, not an executed deployment. Before
activation, drain old workers, back up PostgreSQL, migrate and start the compatible
web/worker pair together. New EPUB kinds must never reach an older worker. The
optional web command allows 130 seconds for a bounded upload, matching the
browser's 120-second upload deadline; normal GET requests retain their separate
five-second client deadline. Verify the selected proxy's body/time limits on the
target before claiming upload acceptance. No existing proxy is changed here.

Artifact storage also requires working POSIX inode `flock` support. A publisher
holds an exclusive lock through atomic linking, temporary-link cleanup and
directory sync; readers validate a safe file before locking, then hold a shared
lock across fresh metadata snapshots and hashing. This prevents equal uploads
from confusing legitimate link-count metadata changes with corruption. Size,
digest, ownership, mode, mtime and ctime checks remain; advisory locks cannot
replace integrity checks against noncooperative changes. Lock failures refuse
storage access. Verify this protocol on the actual selected filesystem before
file-role activation under #25; local/runner success is not target acceptance.

Back up PostgreSQL first, then copy the complete private artifact directory,
preserving modes and ownership. Artifacts are created and synced before their
database bindings, are never overwritten, and have no automatic garbage
collection. That order retains all files referenced by the database snapshot;
extra unreferenced files do not become jobs. Restore both stores into an isolated
target and verify source/report digests before serving requests. A database-only
restore cannot reconstruct original EPUB bytes or report artifacts.

The container acceptance workflow now includes an explicitly synthetic EPUB,
same-key replay, independent worker completion, source/report bindings after
web/worker replacement, and a separate database-plus-artifact backup/restore.
The helper uses only standard-library code inside the actual built image.
Verify container acceptance on the exact release revision.

Compose merges environment mappings and preserves volume entries by target;
the optional command replaces the base command. See the primary
[Compose merge rules](https://docs.docker.com/reference/compose-file/merge/).

## Maintained archive reader and policy v2

[L027](decisions.md#l027-maintained-archive-reader-and-bounded-inspection-process)
replaces the custom ZIP directory scan and Python ZIP reader with
`libarchive-c==5.3` and libarchive **3.8.10**. The binding is hash locked in the
runtime export. `scripts/build_libarchive.py` verifies native source SHA-256
`56cad765459d5ee25a3b761f90c47d99379d28297fbfb72d908880d6b875fb96`, builds
a shared zlib-enabled library without extra codecs/tools, verifies its version
and zlib capability, and retains the upstream license. The image uses the same
digest-pinned Python bookworm baseline for builder/runtime, with signed Debian
build packages frozen at snapshot `20261027T000000Z`. It sets an explicit
`LIBARCHIVE` path; the adapter refuses another native version. Source dates and
temporary build paths are normalized. Two complete builds at the same prefix on
`dev` produced identical library digests; this is not a cross-platform or Docker
reproducibility result. [Debian snapshot](https://snapshot.debian.org/) explains
dated archive selection and validity handling.

Upgrade the native version/source hash, binding lock/export, absolute runtime
path, capability assertion, report reader metadata and regression evidence
together. Recheck supported Python/OS compatibility and publisher advisories,
then run exact-revision image/linkage, worker replacement and restore acceptance.
The local rebuild does not replace those container gates.

Production file jobs execute the complete inspection in a fresh Linux Python
child: 512 MiB address space, 10-second CPU budget, 15-second parent wall deadline,
disabled core dumps, bounded input and at most 1 MiB of report transport. Limits
precede domain/native imports; abnormal exit, timeout or overflow produces a safe
job failure without publishing a success report. Before archive bytes are read,
the child also installs the [Python sandbox](development.md#python-child-sandbox):
no filesystem grants, no new privileges and denied network/io_uring syscalls.
Direct `inspect_bytes` calls do not acquire these process limits or restrictions.
Calibrate capacity on the selected deployment before activation.

Reader policy `librarium.epub-structure.v2` checks the library-exposed member names
and effective metadata, drains admitted members, counts actual expansion, and
refuses non-success native statuses. ZIP64 is supported within these bounds.
Libarchive can normalize names and accept differences between central/local
names, method or flags. It can also accept incorrect CRC metadata on an empty
stored member. Reports therefore disclose `names=library_exposed`,
`metadata=library_exposed`, `empty_member_crc=not_verified` and
`raw_header_conformance=not_checked`. Do not claim universal raw-header or CRC
validation. EPUBCheck remains `not_run`, content acceptance `not_checked` and
`ready=false`.

Drain old workers when upgrading. New jobs capture policy v2 and reader identity;
pending v1 jobs refuse processing rather than receiving newer assurance under an
old capture. Saved v1 reports remain readable with their original policy and
digest. Preserve them; reinspection is a new explicitly requested job.

## Contents evidence policy v3

The v3 contents-evidence slice kept the same maintained reader, native build,
process limits, job kind, schema and artifact mounts. New jobs capture
`librarium.epub-structure.v3`; the immutable report adds bounded plain-text heading
and anchor labels plus NAV/NCX ancestor labels. No archive, book or navigation
document is rewritten. Existing field/record/XML/output limits cover the new data.

Drain older workers before enabling new-policy jobs. The new worker refuses
pending v1/v2 captures rather than reinterpreting them; saved v1/v2 reports remain
readable without adding the new fields. Preserve their bytes and reader bindings.
A later native-reader upgrade must preserve historical reader identities rather
than comparing all saved reports with a newly selected native version.

The v3 image helper asserted the captured heading, target label and hierarchy
after worker completion, web/worker replacement and database-plus-artifact restore.
The current v4 gate extends those assertions below. No production installation
or file-role activation is part of either slice.

## Contents planning policy v4

The read-only planner uses the same EPUB job, immutable artifact stores, schema,
maintained archive reader and resource-limited worker. New jobs capture inspection
policy v4 and store `librarium.contents-plan.v1` inside their structural report.
Source positions, word/media counters, anchors and group-label provenance support
the proposal; no EPUB, navigation or library record is rewritten. No new runtime
dependency, service role, migration or release flow is added.

Drain older workers before enabling v4 captures. The v4 worker refuses pending
v1/v2/v3 jobs; preserve their records and request a new inspection explicitly.
Saved reports retain their original policy, bytes and reader bindings. Preserve
historical identities during later reader upgrades rather than comparing every
saved capture with a future native version.

The v4 actual-image helper verified the embedded plan's source,
inspection-policy/planner identity and `ready=false`, and checks that the compact
job summary matches the immutable plan. Its deterministic one-chapter fixture
must keep supported recorded navigation. The same checks run after initial
worker completion, web/worker replacement and database-plus-artifact restore.
The v4 slice passed exact-head `1b2bad5` image CI before PR #12 merged as
`07137e9`; local checks and browser acceptance are recorded in
[private engineering record](agent-environment.md#private-context-discovery). Later changes still require
their own exact-head acceptance. Base Compose
continues to leave file inspection disabled; no production activation occurs.

## Identifier declaration policy v5

New jobs capture `librarium.epub-structure.v5` using the same maintained archive
reader, isolated worker, job kind and persistent artifact stores. Reports add
bounded raw package identifier declarations and exact package-document hashes;
the separate read-only comparison advances to schema/policy v3. No migration,
runtime dependency, service role or mount is added.

Drain older workers before enabling v5 captures. The new worker refuses pending
v1–v4 jobs instead of silently upgrading their observations. Preserve those job
records and explicitly request any new inspection. Completed v1–v4 reports keep
their original bytes and assurance, including historical native-reader and v4
contents-plan bindings. Missing historical declarations do not mean that the
package declared none. Keep source/report/database backups together.

The current actual-image helper expects v5, asserts the exact package byte hash,
raw identifier fields, source index and root pointer/prefix capture, and retains
the existing native-reader, contents-plan and EPUBCheck checks. These assertions
must hold after initial worker completion, web/worker replacement and isolated
PostgreSQL-plus-artifact restore. Docker is unavailable on the local development
host; exact-head image CI remains a publication/merge gate. This contract records
requirements, not a completed v5 image result or production activation.

## Schema 0005 and explicit EPUBCheck validation

Migration `0005_epub_validation_jobs` adds the separate `epub_validation` kind,
its target constraint and one-active-validation-per-source-digest constraint.
An explicit request captures the completed inspection's job/input fingerprint,
source digest/size, structural report digest and policy, plus the validator and
processing profile. It preserves the original structural report, including
`epubcheck=not_run`. Normalized validation reports use the existing immutable
`report-<digest>` artifact store; PostgreSQL holds their bindings and compact
summaries. No extra mount, service role or library writer is introduced.

The image pins the full official **EPUBCheck 5.4.0** distribution and
**Temurin 21.0.13+9** Linux x64 JRE. Installation verifies the archive SHA-256 and
exact 40-JAR manifest and retains upstream licenses/notices. The JRE download is
checksum-pinned; signed Debian snapshot `20261027T000000Z` supplies `libseccomp2`,
font support and certificates. Runtime paths are
`LIBRARIUM_EPUBCHECK_DIR=/opt/epubcheck` and
`LIBRARIUM_JAVA=/opt/java/openjdk/bin/java`. See the
[runtime research](research/epubcheck-runtime-2026-10-27.md) for official sources,
hashes, Java 21 support and the coordinated upgrade procedure.

Validation requires Linux x86_64 with libseccomp and **Landlock ABI >= 3** on the
selected host/kernel. Failure to install either guard refuses execution. A fresh
checker process receives 2 GiB address space, 60 CPU seconds, a 90-second parent
wall deadline, a fixed 256 MiB heap and 2 MiB per-thread stack. Its environment
contains only fixed locale values; inherited JVM options, credentials and network descriptors
are absent. Seccomp denies socket creation/connections and io_uring setup.
Landlock restricts filesystem reads to pinned runtime/JAR inputs and named OS
support paths, with writes confined to private scratch and standard JVM device
files. The source and JARs are rechecked after execution. Cleanup kills the whole
owned process group before scratch removal, including remaining descendants of
an already exited checker. A parent-death guard sends the checker SIGKILL when
its worker dies. Target acceptance must exercise these guards inside the image;
installing a userspace library does not establish host kernel support.

Policy `librarium.epub-validation.v1` distinguishes completed conformance findings
from execution failure. Both `passed` and `failed` conformance outcomes complete
the job successfully; fatal/error counts determine failure and warning-only
checks pass. Bounded displayed diagnostics do not replace aggregate counts.
EPUBCheck 5.4.0 has no aggregate INFO count, so `counts.info=null` means unknown.
Unusable output, unavailable guards, cancellation or runtime limits cannot
publish conformance success. Content acceptance remains `not_checked` and
`ready=false`; no EPUB, library content or Calibre record is changed.

For an authorized rollout, drain and stop older workers, back up PostgreSQL and
the complete artifact store, migrate, then start the compatible web/worker pair
together. Older images cannot process the new kind. Pending jobs whose captured
validation profile differs from the worker refuse execution; saved completed
reports retain their original identity and source/inspection/report bindings.
Reversing 0005 refuses while any validation jobs exist. Preserve them and fix
forward; neither deleting evidence nor reverting an image reverses the schema.

The actual-image helper now submits an explicit empty-JSON validation request,
checks its own UUID-key replay/recovery, waits for the independent worker and
binds the normalized report to the original source job and structural report.
Its unchanged synthetic EPUB deliberately lacks required modified metadata:
the job must complete successfully with a failed conformance outcome and an
`RSC-005` finding. The same source/report/profile/count bindings are asserted
after web/worker replacement and isolated PostgreSQL-plus-artifact restore.
These are executable acceptance requirements, not an executed image result.
Docker remains unavailable locally; record the exact-head CI result before
claiming image acceptance. No deployment or production activation is claimed.

## Native reference state

The image includes the retained offline engine and `reference_import` command;
no dependency, database migration, startup import or scheduled updater is added.
`LIBRARIUM_REFERENCE_STATE_DIR` is empty by default. No base Compose stack gains
a writable reference mount. An explicit operator import requires a dedicated
app-owned 0700 persistent state directory outside original library/artifact/cache
inputs. The web role only reads producer health; it exposes no import endpoint.

Back up the complete reference-state directory while the producer is idle:
`requests` holds exact packets and UUID receipts, `generations` retains evidence
history, and `published` holds immutable reader snapshots plus `current`.
Preserve permissions and all root bookkeeping/lock files. Restore the directory
as a unit and verify its recorded pins before allowing another import. Retain
old generations; automatic pruning/retention and target restore acceptance are
outside this milestone. Browsers keep their explicit snapshot pins across an
update; selecting native `published` for reads is a separate configuration step.

Container CI exercises the command inside the exact built image with ephemeral
synthetic state, stable-ID/history checks, fresh-process replay, rejected inputs
and socket creation denied. This is neither production state nor actual-library
beta acceptance. The [private engineering record](agent-environment.md#private-context-discovery) records
real-catalogue local evidence and the remaining activation boundary.

## Static responses

HTML is served `no-cache` with a SHA-256 content ETag, so a browser revalidates
the shell after a release instead of requesting assets from an old build (which
returned 404). Other static-asset caching and security headers are unchanged.

Containers simplify deployment; small regular upgrades and tests control ongoing
compatibility work. See [Docker build guidance](https://docs.docker.com/build/building/best-practices/),
[persistent data](https://docs.docker.com/get-started/docker-concepts/running-containers/persisting-container-data/),
and [Django upgrades](https://docs.djangoproject.com/en/stable/howto/upgrade-version/).

## Schema 0006: saved library reconciliation

`0006_library_reconciliation` adds one application-owned report table. It does
not alter existing work/job rows, native reference state, library data or worker
protocols. Reports contain private recorded library metadata, full matching
observations and explicit inventory deltas; PostgreSQL backup/restore must retain
them with the existing app state. No new volume, dependency or service role is
required. Old web/worker code does not use this additive table. Release manifests
derive the new migration leaf from source.

Reversing 0006 is supported only when its table is empty. With saved reports,
the migration refuses to discard evidence; preserve backups and fix forward.
Image rollback alone does not remove the table or reverse migrations. This
backend change introduces no beta or production activation. Exact-image hosted
acceptance remains required before merge/release; separately verify backup and recovery on the selected target.


## Schema 0007: durable library checks

`0007_library_check_jobs` adds the `library_reconcile` and `book_assessment` job
kinds, the valid kind/target constraint and one active job per captured intent.
The existing job table stores captured engine policy, immutable input binding,
progress/lease and historical assessment results. Reconciliation publication and
job completion share one PostgreSQL transaction; cancellation or an obsolete
worker cannot publish a saved report. Reverse migration refuses while either
new kind exists. Preserve evidence and fix forward; do not delete jobs to roll back.

Drain and stop older workers before migrating. Back up the application database
and private artifacts together; migrate and start a compatible web/worker pair.
An old worker interprets unknown kinds as synthetic work and must never consume
these rows. Rehearse [populated migration/restore](populated-upgrade.md) with the
selected release before any deployment; this source change does not activate a new
image or role.

Unlike captured catalogue metadata reviews, these selected checks require current
read-only source access in the worker: native library metadata and EPUBs plus the
explicit catalogue snapshot pin; assessments also require preserved artifacts.
Existing base Compose roles are unchanged. Enabling this capability on a target
requires an explicit worker read-only library/catalogue configuration and the
existing artifact role, with source/artifact path separation and the native-reader
runtime verified. Unavailable mounts produce a durable failed check, never a
partial or admitted result. There is no schedule or automatic source scan.


## Inspection v6 and assessment v2 compatibility

The content-evidence continuation adds no schema/dependency/mount/default-role
change. Drain old workers and start compatible web/worker images together when
this source is released. Newly captured v6 inspections and v2 assessments require
their exact engine; pending older engines refuse reinterpretation. Completed
v1–v5 inspections and saved v1 assessments remain historical readable evidence.
Do not delete old jobs or artifacts to upgrade. Existing coordinated database and
artifact backups/recovery apply. Source publication does not enable beta's file
role or authorize production/library changes.


### Assessment v3 compatibility

The all-recorded-format byte census and selected shared-resource leads advance
only `librarium.book-assessment` to v3. Inspection stays v6. No schema, dependency,
configuration, mount or default-role change is introduced. Pending v1/v2 checks
refuse reinterpretation; completed v1/v2 assessments retain their original scope
and historical readability. Coordinate compatible web/worker versions and retain
existing database/artifact backups. Source publication does not activate these
roles on beta or establish writer admission.


## Inspection v7 and assessment v4 compatibility

The source-attribution slice changes captured inspection/assessment policies only;
no migration, dependency, artifact location or configuration changes. Deploy web
and worker from one reviewed image after draining old workers. Completed inspection
v1–v6 and assessment v1–v3 records remain readable. Pending old-policy work refuses
reinterpretation; explicitly request a new check instead. Older images cannot read
v7 source capture or execute v4 assessment reliably, so preserve new artifacts/jobs
and fix forward rather than dropping evidence. The existing container acceptance
asserted v7 and its bound source-attribution envelope. See
[the development contract](development.md#source-title-and-credit-attribution).

## Inspection v8 and assessment v5 compatibility

Document source-text capture and overlap advance only the captured policies.
There is no schema, dependency, configuration, mount or default-role change.
Use a compatible web/worker pair and drain older workers before an authorized
upgrade. Completed v1–v7 inspections and v1–v4 assessments remain historical
readable evidence. Pending older engines refuse reinterpretation and need an
explicit new check. Preserve new jobs/artifacts and fix forward rather than
attempting to read v8 captures with an old image. Database and artifact backups
remain coordinated. The actual-image acceptance helper now asserts v8 and exact
per-document source/resource/text binding alongside existing whole-text and
attribution assertions; changing the helper alone is not a container run receipt.
See [the document comparison contract](development.md#normalized-document-text-overlap).
No installed beta update or library mutation follows from source verification.

## Candidate assessment roles and curated references

Assessment v6 introduces the optional curated-reference result without a database
schema, dependency or inspection-policy change. Saved v1–v5 assessments remain
historical; pending v5 engine work requires a new explicit request. Coordinate
the web and worker upgrade so both understand v6 pins and saved results. Keep
registry/manifests/evidence/artifacts backed up separately from application state;
restoring an older trust configuration does not turn a saved result into current
authorization. [Development](development.md#curated-reference-authentication-and-assessment-history)
owns authentication, discovery and history API behavior.

Durable reconciliation/assessment needs the same selected read-only library and
catalogue in the web and worker, plus shared writable application artifacts. The
explicit `compose.assessments.yaml` override adds worker input access alongside
`compose.files.yaml` and `compose.library.yaml`. It configures `/library`,
`/catalogue` and `/artifacts`; it does not select a real target or restart a role.
The same worker mount lets `LIBRARIUM_LIBRARY_READ_MODEL=refresh` or `serve` keep
the library read model current (L075); set the value identically in web and worker.
`LIBRARIUM_DB_CONN_MAX_AGE` (default 60) keeps database connections open between
requests; 0 restores a connection per request.
The registry configuration gate requires matching source paths and rejects
writable inputs, missing mounts and mismatched artifact storage.

Curated-reference authentication is separately optional. Bare processes configure
`LIBRARIUM_CONTENT_TRUST_REGISTRY` and
`LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256` together. For containers,
`compose.content-trust.yaml` mounts an explicitly selected
`LIBRARIUM_CONTENT_TRUST_HOST_PATH` at `/content-trust` read-only in both reading
roles, using `registry.json` and one identical independently approved digest.
The store must be separate from all library and application state. Its manifests,
evidence and reference artifacts use fixed digest-derived leaves. The resolved
registry gate rejects missing/mismatched pins, writable mounts, reader-store
disagreement and overlapping state or source paths.

Validate the resolved model before an independently authorized activation:

```sh
docker compose -f compose.registry.yaml -f compose.files.yaml \
  -f compose.library.yaml -f compose.assessments.yaml \
  -f compose.content-trust.yaml config --format json | python3 scripts/registry_config.py
```

No reference is selected when the trust override/settings are absent. A request
without an explicit reference pin never reads the trust configuration. Enabling
these source roles or curating/approving real references remains an explicit
operator action, separate from source publication and synthetic acceptance.

## Schema 0008: retired corrected output

Migration `0008_corrected_epub_jobs` added immutable `CorrectedEpub` bindings,
`epub_correction`/`output_validation` job kinds, active-intent uniqueness and protected
source/generation/initial-validation relationships. [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them)
retired corrected-copy generation, but the tables, constraints, triggers and
migrations 0008 to 0010 are unchanged: deploying the retiring release changes no
stored data and needs no migration. Existing rows, `corrected-<sha256>` artifacts and
their reports stay as history. The worker never claims or advances the retired kinds
(its claim list omits them), so a row left queued or running stays inert; the
cancel route ends it. The database's lease guards for those kinds are unchanged and
still admit a worker from an earlier release, so stop every earlier web, worker and
delivery process before treating retired rows as inactive.

Back up every source, corrected artifact and report together with the database binding
rows, as before. Restore into an explicitly isolated database/artifact fixture and
verify every digest and reader binding. Artifact-only or database-only restore is
incomplete. Unreferenced digest artifacts can survive interrupted publication; no
retention or automatic garbage collection is introduced. Reversal of 0008 refuses while
either job kind or any output row exists; preserve evidence and fix forward.

The release manifest derives migration leaves from source and records the inspection
and validation policy versions. The default Compose files, role mounts and
disabled-by-default file role are unchanged. Web captures requests; the worker needs
existing application artifact storage and native inspection/checker runtimes.

Hosted `epub_container_acceptance.py` runs inspection and EPUBCheck validation in
the actual image and checks the preserved source, reports and bindings after
replacement and coordinated restore. Its backup helper still includes the
`corrected-` prefix so existing artifacts are kept. The Java
checker retains its pinned offline syscall set and Landlock grants; shared
libseccomp setup now refuses unresolved mandatory syscall names. The Python
inspection child installs the shared
network filter plus Python-only process controls and grant-free Landlock before
reading untrusted bytes.
Trusted modules/native libraries and all supported Linux codecs are preloaded;
late imports terminate with `sandbox_late_import`. No runtime or scratch directory
is granted; output remains pipe-only and parent-published. Resource/lifecycle
limits and all orchestration deadlines remain unchanged.

Python requires Linux x86-64, the already pinned image `libseccomp2` and Landlock
ABI 3+ on the host. Newer ABIs reuse the ABI-12 masks; parent runtime evidence
records observed/effective ABIs. ABI 4+ denies TCP bind/connect, ABI 6+ scopes
signals and abstract UNIX sockets, and ABI 10+ handles UDP rights. ABI masks have unit and header checks.
Missing isolation fails with a safe `sandbox_*` reason and no verdict. No image package, checksum,
mount, schema, environment bypass or policy-version change is introduced.
Historical results retain their original assurance; this source hardening does
not retroactively certify a saved run. Deploy compatible web/worker images only
under separate activation authority. Re-run actual-image replacement/restore and
kernel denial tests on the selected host; userspace packages alone cannot supply
Landlock support.

## Synthetic writer role

The separate `Dockerfile.writer` target contains Calibre/Qt; the ordinary image
and default Compose roles remain unchanged. The writer is disabled by default.
It serves only loopback (default port 8133) and one operator-configured synthetic library.
There is no production Compose activation or supported live writer topology.

The official 9.17.0 Linux x86_64 archive is pinned at SHA-256
`953e4512a6482848cd803c88b6d942e6afca65dc3b67c7d1353ae048d616de53`.
That digest was calculated after the downloaded archive matched the upstream
HTTPS SHA-512 checksum, before extraction. The
[runtime checksum manifest](../scripts/calibre_delivery_runtime.json) records both
digests, archive size and the exact upstream source. The base-Python launcher verifies the archive and complete extracted file set
before executing Calibre. Added files, hardlinks and changed files/symlinks refuse.
The entrypoint repeats verification before connecting to the content server. This does
not defend a writable installation against a malicious same-user process racing
verification; the image supplies the read-only, root-owned distribution boundary. Preserve upstream licenses
and change runtime/API/lock profiles together with mandatory native acceptance.

Only synthetic setup may supply these environment variables:

| Setting | Role and boundary |
|---|---|
| `LIBRARIUM_DELIVERY_ENABLED` | Explicit opt-in; default off |
| `LIBRARIUM_WRITER_SYNTHETIC_ONLY` | Writer requires `1` and a matching private synthetic ownership marker |
| `LIBRARIUM_WRITER_LIBRARY_ROOT` / `LIBRARIUM_WRITER_LIBRARY_UUID` | Fixed writer destination; never accepted from HTTP |
| `LIBRARIUM_WRITER_STATE_DIR` | Private durable broker journal, identity and isolated Calibre configuration |
| `LIBRARIUM_WRITER_ARCHIVE` / `LIBRARIUM_WRITER_RUNTIME_SHA256` | Verified distribution and exact supported pin |
| `LIBRARIUM_ARTIFACT_DIR` | Existing immutable originals, corrected files and reports; read-only to writer |
| `LIBRARIUM_WRITER_TOKEN_FILE` | Private client/writer transport credential; absent from web and ordinary workers |
| `LIBRARIUM_DELIVERY_SIGNING_KEY_FILE` | Private grant-verification key for the writer; no application role signs grants now |
| `CALIBRE_CONFIG_DIRECTORY` | Fresh writer-state configuration, with no inherited user plugins |

Calibre writes its configuration as it starts. Before runtime verification or
any Calibre start, the launcher therefore refuses `writer_state_unavailable` unless
`LIBRARIUM_WRITER_STATE_DIR` and its `config` directory already exist as private
directories that the writer user owns and can write on a writable filesystem.
Symlinks, files and shared modes refuse; the launcher creates neither directory.
Structured launcher refusals print one plain line naming the code, without
configured values, and exit non-zero. A refusing writer never listens, and the refusal code never reaches an interface.

Private roots must be owned directories with mode 0700; credential files must be
owned regular no-follow files with mode 0600. Roots cannot overlap. A matching
synthetic marker and native UUID are required; a reachable port or caller boolean
is insufficient. The writer holds an exclusive no-follow flock on the validated
synthetic ownership marker before connecting to the configured content server.
The marker excludes cooperating Librarium writers; it cannot exclude other clients
of the server. The server owns the library cache. The writer needs only read access
to the synthetic root/marker, read access to artifacts and write access to its own
journal/configuration. Web, worker and writer need no library write mount.
Only the synthetic Calibre server role in the acceptance proof can write books.
An operator-confirmed session is required for every approval; the application
cannot inspect or stop other tools. Production coordination/activation remains
unapproved. See [L060](decisions.md#l060-delivery-through-the-owning-calibre-content-server).

Additional protected configuration:

| Setting | Role and boundary |
|---|---|
| `LIBRARIUM_CALIBRE_URL` / `LIBRARIUM_CALIBRE_LIBRARY_ID` | Fixed server origin/prefix and explicit served-library ID; loopback HTTP or HTTPS |
| `LIBRARIUM_CALIBRE_CREDENTIALS_FILE` | Owned mode-0600 JSON (required unless the environment pair is set); the password must be a generated secret of 32+ characters, e.g. `secrets.token_urlsafe(32)` containing `username` and `password`; writer only |
| `LIBRARIUM_CALIBRE_USERNAME` / `LIBRARIUM_CALIBRE_PASSWORD` | Environment alternative; never logged; file takes precedence |
| `LIBRARIUM_DELIVERY_SESSION_FILE` | Protected per-book operator confirmation for a grant session; no application role reads it now |

Digest authentication is used over loopback HTTP; Basic is answered only over HTTPS,
so a process squatting on the loopback port never receives the password. No Authorization header
is forwarded across a redirect and environment proxy settings are ignored. The
server account must permit export and writes without per-library book restrictions.
The marker/config profile remains synthetic-only and disabled by default. No live
server credentials, container control or production Compose activation is supplied.
Server storage/free-space and hardlink policy cannot be certified remotely; broker
journal capacity is checked locally. Read-back is byte evidence, not remote fsync.

Transport accepts no redirects or proxy
configuration, arbitrary commands or caller-selected destinations. Requests and
receipts are bounded at 1 MiB, EPUBs at 32 MiB, and authenticated requests at
120/minute with at most eight handler threads. New sends hold below 16 MiB of free
journal space or above the 128 MiB journal limit; retained evidence is not pruned.
The active server adapter cannot inspect remote free space, hardlinks or fsync.
Those checks remain in the historical native test oracle and are not claims about
server delivery. The pinned server may recompute derived page counts and full-text
indexes. Derived `pages` is excluded from metadata comparisons; authored fields,
cover, other formats and exact EPUB bytes remain guarded. Physical power-loss,
filesystem recovery and remote durability still need a separately approved rehearsal.

Migration `0009_epub_delivery` adds append-only intents, approvals, target bindings,
events, receipts and Undo intents plus a mutable target reservation/state projection.
It adds the four delivery job kinds and a separate database lease capability guard.
All source/output/validation/assessment links are protected. Rows contain digest
references and native identities, with no library path or credential columns.
Row triggers reject evidence UPDATE/DELETE. The owner database role can still
TRUNCATE or alter/disable triggers; production database roles are undesigned. A
statement-level TRUNCATE guard is deferred until privileged maintenance and role
separation are designed, since the same owner can disable it and current fixture
flush/restore uses privileged maintenance. Reversal refuses while any
new-kind job or delivery evidence exists; preserve evidence and fix forward. The four
delivery job kinds are retired (L091): the worker never claims them and no dispatcher
exists, but their rows and the database lease guard remain.

Keep PostgreSQL, every artifact, the broker database/WAL/identity and the synthetic
library together in a coordinated stopped-role backup. Restore only into a new
isolated fixture, reopen receipts and exact request keys, verify original bytes,
start a fresh writer epoch and reconcile before any new review. A missing,
truncated or rolled-back journal never authorizes a repeated write. Never restore
broker journal/WAL/identity independently of PostgreSQL, artifacts and the library.
An independent restore loses send evidence and can otherwise produce false
never-sent classifications. When an absent operation observes its output digest
instead of its before digest, every absent-operation seal path returns
`unobservable output_already_present` without consuming the operation. This guard
does not detect every rollback or ABA restoration; only a coordinated backup and
restore preserves the evidence boundary. This synthetic
restore procedure does not approve restoring or replacing any real library.
New content-server actions additionally require the verified offline baseline
described in [the recovery contract](delivery-recovery.md), configured through
`LIBRARIUM_DELIVERY_RECOVERY_DIR` and mounted read-only for the writer. A durable
operation manifest binds retained artifacts to that baseline before send intent.
Historical reconciliation still works without a current baseline; backup
verification never releases an uncertainty hold or grants a resend.
Originals, outputs and all evidence have indefinite retention; no cleanup job is
introduced. Browser disconnect cancels nothing, and post-send cancellation checks
an outcome instead of killing native copying.

`Synthetic writer acceptance` builds this target, checks its disabled entrypoint,
and runs actual-image native/cache and process-death vectors without a network or
library mount. It must pass before merge. Local runtime proof does not certify an
unbuilt image, hosted CI, deployment, production database privileges or live writer
coordination. Real-library use and activation require separate design and approval.

The separate native-role CI job also runs the native gate, kill vectors and
content-server proof against fresh synthetic libraries. The earlier end-to-end HTTP
role proof needed the removed web, dispatcher and correction roles and is gone. Missing
namespace/kernel prerequisites fail the job. The actual-image job checks disabled
startup, enabled-launcher refusal and native/kill vectors. With delivery enabled,
a mounted state volume and config directory, and synthetic-only opt-in absent, the
image must refuse `synthetic_only_required` after base-Python runtime verification
and native exec. Without a state volume it must refuse `writer_state_unavailable`
as one plain line, with no traceback, before Calibre starts. This proves the
enabled launcher path, not HTTP topology. Hosted execution, image scanning/SBOM and
registry digest acceptance remain integration gates; no hosted result is claimed.

Synthetic roles share an effective user because artifact readers require owner
identity. Separation depends on mounts, secrets and kernel filesystem/network
rules, not different Unix users. Proxy authentication must strip untrusted
REMOTE_USER input and restrict forwarding as described below. No production
proxy/authentication topology is approved.

## Optional trusted operator identity for the beta

The beta may map a successfully verified client certificate at its Librarium-owned
mTLS ingress to the fixed principal `operator` ([L088](decisions.md#l088-default-off-trusted-operator-identity)).
This implementation does not configure or activate that ingress. Production
proxy/authentication topology remains unapproved.

Identity forwarding defaults off. Set `LIBRARIUM_OPERATOR_PROXY_IPS` **only on
web** to a comma-separated list of the ingress's exact peer IP addresses as seen
by web's TCP socket. An absent or empty value disables it. Literal IPv4/IPv6
addresses are accepted; wildcards, CIDRs, hostnames, scoped IPv6 and empty list
members refuse WSGI startup and registry validation. Do not trust a whole bridge
subnet or use a forwarded client address. Pin the ingress address privately and
verify it after network recreation; address drift must fail closed. The beta's
internal edge must retain only ingress and web, and web must have no published
port or alternate unprotected route. Identity trusts that network boundary.

Add these environment entries to a private **web-only** override, preserving
the existing application environment. The documentation address is a reserved
example; substitute the actual ingress peer IP, and use the same list in both
IP settings:

```yaml
services:
  web:
    environment:
      LIBRARIUM_OPERATOR_PROXY_IPS: "192.0.2.10"
      FORWARDED_ALLOW_IPS: "192.0.2.10"
      GUNICORN_CMD_ARGS: "--forwarder-headers= --proxy-protocol=off"
```

Set Gunicorn `forwarder_headers` to an empty list: Librarium uses no path prefix,
and a `SCRIPT_NAME` header forwarded by the trusted peer would otherwise rewrite
the request path. Never add `REMOTE_USER`, `HTTP_REMOTE_USER`, identity headers or `*`. Restrict
`forwarded_allow_ips` to the same peers, never `*`. Keep PROXY protocol off so
`REMOTE_ADDR` describes the TCP peer. The application consumes only the ordinary
`X-Librarium-Operator` header and does its own peer/value checks. Gunicorn's
forwarder settings alone do not enforce the principal length/character rules or
provide this named-header-to-REMOTE_USER mapping. No dependency is added.

In nginx's `http` context, derive the value only from certificate verification:

```nginx
map $ssl_client_verify $librarium_operator {
    default "";
    ~^SUCCESS$ operator;
}
```

Keep these directives in the beta's existing TLS `server` context, retaining its
protected certificate paths and existing TLS configuration:

```nginx
ssl_verify_client on;
ssl_client_certificate /run/secrets/operator-client-ca.pem;
underscores_in_headers off;
ignore_invalid_headers on;
```

In **every** location that proxies to beta web, keep its existing `proxy_pass`,
Host and HTTPS forwarding and add this header block:

```nginx
proxy_set_header X-Librarium-Operator $librarium_operator;
proxy_set_header X_Librarium_Operator "";
proxy_set_header Remote-User "";
proxy_set_header REMOTE_USER "";
```

The first directive replaces all client-supplied copies, including duplicate and
case-varied copies, with the ingress-derived value; an empty value omits the
upstream header. Do not forward `$http_x_librarium_operator`, a certificate DN,
or a client-supplied username. nginx inherits `proxy_set_header` directives only
when a location defines none of its own: include the complete existing proxy
header set in each affected location rather than accidentally dropping Host or
HTTPS forwarding. Keep the current mTLS access restriction and unauthenticated
request rejection intact.

The outer WSGI adapter always removes ambient `REMOTE_USER`, HTTP `Remote-User`
and the consumed identity header before Django/static handling. A trusted peer
with one valid identity receives WSGI `REMOTE_USER`. Names must match
`[A-Za-z0-9][A-Za-z0-9_.@-]{0,255}` exactly; missing, empty, oversized,
non-ASCII/non-printable, whitespace-bearing and separator-bearing values grant
no identity. Duplicate headers become a comma-bearing invalid value. No value is
trimmed or normalized. IPv6 address spelling is canonicalized for comparison;
IPv4 and IPv4-mapped IPv6 are distinct configured addresses.

All beta clients admitted by this CA act as the same operator. Cover review,
cover search and the retired-work cancel route reuse their current principal gates and
actor comparisons. A writer grant session's `confirmed_by` must equal `operator`
exactly; its HMAC binding, writer enablement and explicit approval checks remain
required. Identity alone does not authorize a library write.

Before a separately authorized beta activation, validate resolved Compose with
`scripts/registry_config.py`, validate nginx configuration, and verify successful
mTLS requests reach operator gates while unauthenticated requests remain rejected.
Direct web requests from an untrusted peer must remain unauthenticated with either
identity header, and spoofed HTTP `Remote-User` must never establish identity.
Removing the web-only setting disables the handoff after web reload. This PR
performs no beta/ingress change, certificate change, deployment or library write.

## Schema 0010 and runtime database credentials

Migration 0010 installs ALWAYS row/TRUNCATE guards and the protected maintenance
record described by [L062](decisions.md#l062-postgresql-guards-and-a-separate-runtime-login).
Apply it as the existing schema/database owner before provisioning runtime access.
It adds no dependency or background service. Its rollback refuses once any guard
maintenance is recorded; preserve evidence and fix forward rather than removing
guards to downgrade a running installation.

Create a dedicated login through protected administrator configuration, without
SUPERUSER, CREATEDB, CREATEROLE, REPLICATION, BYPASSRLS, memberships or owned objects.
Supply its authentication separately; the provisioning command neither creates
roles nor handles passwords. With PGUSER/PGPASSWORD selecting the owner:

```sh
env -u LIBRARIUM_RUNTIME_DB_USER -u LIBRARIUM_RUNTIME_DB_PASSWORD \
  uv run python backend/manage.py migrate --noinput
env -u LIBRARIUM_RUNTIME_DB_USER -u LIBRARIUM_RUNTIME_DB_PASSWORD \
  uv run python backend/manage.py provision_runtime_role "$LIBRARIUM_RUNTIME_ROLE"
```

Provisioning is atomic and repeatable for a dedicated Librarium database using the
public schema. It revokes PUBLIC privileges in that database/schema, so do not use
it in a database shared with other applications. It refuses unclassified tables,
non-owner connections and unsafe login attributes/memberships/ownership. Re-review
the table matrix and run it again after future migrations. New objects have no
automatic runtime grants; do not grant ALL or make runtime a member of the owner.

Web and workers accept LIBRARIUM_RUNTIME_DB_USER and
LIBRARIUM_RUNTIME_DB_PASSWORD, overriding PGUSER/PGPASSWORD. Give these processes
only the runtime credential; owner credentials must remain in a separate migration
job. PGDATABASE/PGHOST/PGPORT still identify the same application database. With
runtime overrides unset, existing single-user development works as before. Existing
Compose files retain their single-user defaults: a role-separated deployment must
supply a protected service-environment override for runtime services and retain
owner-only migration credentials. This change does not activate a deployment or
provision production credentials.

PostgreSQL trigger functions remain security-invoker. Runtime gets no schema
CREATE, database CREATE/TEMPORARY, table TRUNCATE/TRIGGER/REFERENCES, sequence or
function EXECUTE grants. Evidence gets SELECT/INSERT; mutable application tables
get SELECT/INSERT/UPDATE/DELETE; maintenance records and Django metadata are
read-only. Table/sequence/function grants inherited from PUBLIC are revoked;
owner default grants on future public tables, sequences and functions are revoked
for PUBLIC and the runtime login. The owner remains able to run migrations and the separately authorized
[recorded maintenance procedure](development.md#delivery-evidence-database-guards).


## Fixed-upstream catalogue relay

The opt-in [catalogue sync overlay](../compose.catalogue-sync.yaml) reuses the
existing assessment mounts and the official digest-pinned HAProxy image. The
worker stays on the internal default network; only `catalogue-relay` joins the
outbound `catalogue-egress` bridge. The relay has no host ports, a non-root user,
a read-only root filesystem/config, dropped capabilities, no-new-privileges and
small CPU/memory/PID limits. No application or database state is mounted there.

Set `LIBRARIUM_CATALOGUE_RELAY_CONFIG` to an absolute file outside the checkout.
Copy this configuration, replace `BLC_LAN_HOST` and `BLC_API_PORT` with the selected
literal host and numeric port, then set its permissions to `0444`. Keep real
infrastructure values in protected configuration. No shell or runtime environment
substitution is supported inside this file.

```text
global
  maxconn 32
  nbthread 1

defaults
  mode tcp
  timeout connect 3s
  timeout client 15s
  timeout server 15s

listen catalogue_api
  bind :12404
  server blc BLC_LAN_HOST:BLC_API_PORT check inter 30s fall 2 rise 1
```

The validator admits this configuration with one literal upstream and rejects
extra listeners, upstreams, resolvers, proxy rules and administration sockets.
The `configs` mount uses mode `0444`; standalone Compose ignores file-backed mode
settings, so the host file must also be read-only. Resolve Compose with the sync
overlay last, and pipe its JSON to `python3 scripts/registry_config.py` before
separately authorized activation. That check reads the selected config file
locally and reports only a generic refusal on invalid configuration. The relay
keeps its own pinned image rather than sharing the application digest.

The config healthcheck checks syntax; HAProxy's backend check probes the selected
TCP endpoint. Deployment acceptance must separately verify upstream reachability,
worker network isolation and unchanged read-only inputs. The relay has an outbound
route; fixed forwarding does not filter the relay process at the network layer.
No firewall changes or service activation are included in source validation.

Image provenance: [official HAProxy image](https://github.com/docker-library/haproxy).

## Optional web cover sources

`compose.cover-sources.yaml` is an explicit last overlay on the registry/runtime,
file-storage and assessment inputs. It reuses the application image and starts
no source role unless `--profile cover-sources` is supplied. Set
`LIBRARIUM_COVER_SOURCES_ENABLED=true` explicitly for web and worker as well;
the default is false. Apply migration 0015 and rerun runtime-role provisioning
through the existing owner-controlled admission chain before starting the new
image. No configuration or deployment is performed by opening the picker.

The overlay preserves web's `edge` attachment and proxy alias and requires that
network, the default network and `cover-control` to be internal. Before activation,
verify the existing edge network is internal and the authenticated proxy can reach
web on it; an existing public bridge is not an equivalent configuration. Worker
joins default and `cover-control`; only `cover-sources` joins `cover-control` and
external `cover-egress`. Catalogue relay connectivity remains a separate role.
The source role has no persistent mounts or database/writer/approval configuration.
Set a protected random `LIBRARIUM_COVER_SOURCES_SECRET` of at least 32 ASCII
characters on worker and source only. The source refuses startup without it,
compares the `X-Cover-Control` header in constant time and binds port 8124 only to
its `cover-control-listener` alias address. Never put this value on web or in Git.
Optional `HARDCOVER_TOKEN` belongs only to that role's protected environment and
its Hardcover search child. Missing credentials produce Not configured and no
source retry action; rejected credentials remain Unavailable. Optional
`GOOGLE_BOOKS_API_KEY` also belongs only to the source role's protected environment
and its Google search child. An empty value preserves unkeyed requests. Operators
supply any key separately; no key is created or installed by this overlay. Keyed
Google requests refuse redirects, and no key reaches image requests or other roles.
Google's Books API guide
describes its application key parameter; a key does not guarantee quota availability.
This overlay does not install host firewall rules. Host/LAN routing restrictions
beyond the application public-address policy require a separately approved host
change; the container proof does not claim those restrictions are installed.

Search destinations are `itunes.apple.com`, `www.googleapis.com`,
`openlibrary.org`, `api.hardcover.app` and `web.archive.org`.
Provider image hosts are checked independently in the worker and role, including
every redirect: Apple `mzstatic.com` and its subdomains; Google `books.google.com`
and `books.googleusercontent.com`; Open Library `covers.openlibrary.org`;
Hardcover `assets.hardcover.app`; Lexicanum archived copies `web.archive.org`.
Only the explicit pasted-image lane accepts other public HTTPS hosts. Live
Lexicanum hosts are refused before DNS in every lane, including pasted URLs and
redirects. Archived wiki hosts occur only as Wayback query/path data. Live art
requires the browser extension planned for PR3b; stored catalogue Original and
Enhanced choices remain available. All DNS
answers must also be global, with explicit special-purpose network exclusions
independent of Python's address registry. Embedded/mapped addresses are refused;
connections use a checked address with verified original TLS hostname. Only port
443 is accepted. Non-ASCII URLs must be percent-encoded before submission. No
ambient proxy, cookies or image-host authorization is sent. Idle socket reads cap
at five seconds, with a separate total-deadline watchdog covering dripping headers.

The closed source interface offers search for one bounded provider and image
fetching, with no paths, database IDs or writer operations. Source requests use
fresh resource-limited children, 90-second parent deadlines and a two-connection
admission limit. Complete search results alone enter the bounded six-hour cache;
shared provider pacing and Wayback backoff survive child exits. The Lexicanum
source queries archives only when other matches score strictly below 0.75.
Wayback HTTP 429 reports Rate limited; persistent HTTP 503 reports Unavailable
after one bounded retry. Neither becomes a successful empty result.
Archived lookups prioritize setting/series terms in the search title (for example,
Age of Sigmar or Gotrek and Felix), with the usual 40K-first order for ambiguous
titles. The likely wiki receives three quarters of the remaining budget; other
wikis run only while time remains. Pacing, network reads and retries share those
deadlines. Partial coverage preserves any covers found, stays outside the complete
cache and never proves absence. Open Library search retains title/author filtering
and tries bounded work/edition cover IDs, edition OLIDs and valid ISBN cover URLs
with `default=false`, following its Covers API.
Web choices sort by descending title/author score; scores below 0.75 or unknown
scores carry Possible match in the picker and remain selectable subject to the
existing admission rules. This similarity score does not verify edition identity.
The role emits one JSON stderr record per authenticated search, including cached
searches and failures: source ID, closed state, candidate count and duration in
milliseconds. Queries, titles, authors, identifiers, URLs, credentials, request IDs
and exception text stay out of these records. Standard HTTP access logs remain off.
Downloads cap at 16 MiB; worker image calls cap at 20 seconds and search calls
at 95 seconds, above the role's 90-second child kill. Different providers can run
concurrently; only cache access takes the cache lock. Raster children cap at
25 million pixels, 512 MiB address space, eight CPU seconds and twelve wall
seconds. A 24-megapixel fixture exercises this budget. Both image opens admit
only JPEG/PNG/GIF/WebP. Embedded ICC profiles convert to sRGB before a new
metadata-free JPEG is made; invalid profiles refuse admission. Small, blank,
malformed, animated or wrongly shaped images are refused.

Only derivatives are persisted, in the dedicated disposable `web-` artifact
namespace; original bytes are hashed for provenance without a retained copy.
Each actor may have two active searches and twenty starts per rolling day,
including cancelled searches. Replay of an accepted request key does not consume
a slot. A pasted-image request must send `sources: []`; mixing provider selection
and a pasted URL is rejected. Provider ISBN values must be strings or absent.
The idle source worker reclaims terminal searches and unreferenced web derivatives
after seven days, checking at most once per five minutes and deleting at most
64 rows/files per pass. Every append-only PreparedCover reference is retained,
including superseded choices; selection and reclamation share an advisory lock.
Fresh orphan derivatives from interrupted admission have the same seven-day grace.
Other artifact namespaces are never reclaimed by this job. The CoverSearch DELETE
grant supports this retention task. Provider jobs checkpoint separately and resume
expired leases; cancellation prevents late publication.

Run the image-level proof with
`python3 .github/scripts/cover_sources_container_acceptance.py --image=<candidate-image>`.
It first asserts network/mount/environment/DB facts on the untouched resolved
Compose model. Its owned fixtures use local listeners on egress, ingress and DB
networks, preserve the edge attachment, and prove authenticated control-only
binding. No internet availability, live provider, library mount, installed service
or host firewall change is involved.
## Source browser role

`services/source-browser/Dockerfile` builds a separate image from the same
digest-pinned Chrome distribution used by the retained browser adapter. It runs
as UID/GID 999, with headed Chrome under Xvfb, dropped capabilities,
no-new-privileges, a read-only root and bounded temporary storage, CPU, memory
and processes. `services/source-browser/provenance.json` records the image's
source reuse and the Apache-licensed seccomp profile origin.

Build with the repository root as context:

```sh
docker build -f services/source-browser/Dockerfile -t librarium-source-browser:candidate .
```

Activation is a separate reviewed step. The default-off
`compose.source-browser.yaml` follows `compose.cover-sources.yaml`, and requires
the `source-browser` profile, `LIBRARIUM_SOURCE_BROWSER_ENABLED=true`, a dedicated
`LIBRARIUM_SOURCE_BROWSER_SECRET` of at least 32 ASCII characters, and
`LIBRARIUM_SOURCE_BROWSER_IMAGE` pinned as
`ghcr.io/jshauns81/librarium-source-browser@sha256:<approved-digest>`.
The browser key must differ from the cover-source key. Only worker and browser
receive it. The beta publisher exports the exact accepted browser image alongside
the application image. The v2 release manifest records each immutable registry
reference, tested config digest, source commit and platform. Stable promotion
copies both existing manifests without rebuilding. A local build or a partial
registry pair is not an installable release. Activation remains separate.

For a manager-installed stack, stage the overlay and exact seccomp profile from
the same reviewed source snapshot into the manager's stack directory before
enabling the profile. Keep the nested path; the profile is a host-side Docker
input, so putting it inside the browser image does not supply it to Docker:

```sh
install -m 0644 "$SOURCE_DIR/compose.source-browser.yaml" "$STACK_DIR/compose.source-browser.yaml"
install -D -m 0644 "$SOURCE_DIR/services/source-browser/seccomp.json" "$STACK_DIR/services/source-browser/seccomp.json"
cmp "$SOURCE_DIR/services/source-browser/seccomp.json" "$STACK_DIR/services/source-browser/seccomp.json"
```

`SOURCE_DIR` is the extracted, reviewed source snapshot for the selected release;
`STACK_DIR` is the manager's existing stack directory, outside any Git checkout.
Select the existing registry and cover-sources files before the source-browser
overlay. The manager's Compose working/project directory must be `STACK_DIR`
(equivalent to `docker compose --project-directory "$STACK_DIR" ...`). Do not
rewrite seccomp to a development checkout path. Published paired releases attach
`stack-assets.zip` containing registry Compose files, overlays and the exact
seccomp profile, provenance and license. Before extraction, verify the archive's
SHA-256 against `stack_assets.sha256` in the selected release manifest; verify the
extracted files against `stack_assets.files`. The ZIP preserves the nested paths
with fixed timestamps/modes and no host ownership metadata. These assets permit
installation without cloning source. Set `LIBRARIUM_IMAGE` from
`images.application.image` and `LIBRARIUM_SOURCE_BROWSER_IMAGE` from
`images.source-browser.image` in that same manifest; config digests are acceptance
identities, not registry pull references. The browser stays opt-in.
No manager stack is changed by the acceptance test.

Acceptance copies the three Compose files and the profile into a disposable
installed-stack directory, checks the resolved isolation model and refuses a
missing profile. It starts that stack without a seccomp-path substitution and
requires both Chrome sandboxes. Keep the profile's additional
namespace syscall allowances: Chrome must report namespace and Seccomp-BPF
sandboxes without sandbox-disabling flags. Some host policies also restrict user
namespaces. Acceptance must fail there; host policy changes need separate review.
Never replace this with privileged mode, added capabilities, an unconfined
seccomp profile or a disabled Chromium sandbox.

The sole persistent browser mount is the project-owned named volume
`source-browser-profile` at `/data`. It contains only this role's profile, never
an imported personal profile or cookies. An exclusive owner lock prevents a second
role from sharing the profile. The browser joins `cover-egress` and
`source-browser-control`, with its API bound only to the latter. It has no ports,
database network, application mounts or writer configuration. The private
control bridge is added only to worker. The registry validator admits this exact
role, resource, volume, image and secret shape and refuses extra overrides.

The API accepts authenticated POSTs containing only an allowlisted HTTPS URL:
`/goodreads` returns bounded rendered search/book HTML; `/lexicanum` returns
current article HTML, canonical/current article URL, GET current export XML and
original cover URL when present; `/image` returns bounded artwork bytes.
Lexicanum article requests accept the four supported wikis' current article
views only. Export requests remain GETs with `curonly=1`. Intake/import is absent.
There is one navigation at a time, at most one queued request, and an explicit
busy response. Lexicanum GETs are paced at least one second apart. Challenge
pages stop retrieval; scripts, solvers, stealth changes and UA spoofing are absent.

The proxy limits tunnels to public addresses on `goodreads.com`,
`www.goodreads.com`, `i.gr-assets.com`, `images.gr-assets.com`,
`images-na.ssl-images-amazon.com`, `m.media-amazon.com` and the four supported wiki hosts
(`wh40k`, `whfb`, `ageofsigmar`, `catalogue` under `lexicanum.com`). Browser
interception further restricts navigation paths and selected-wiki resources,
including every redirect. The image URL policy restricts `m.media-amazon.com` to
`/images/S/compressed.photo.goodreads.com/books/` image paths.
Each tunnel has a 20 MiB/80 second limit, with at most
16 concurrent tunnels; returned HTML/XML is limited to 2 MiB each and image bytes
to 16 MiB. Transport limits complement the existing sandboxed image validator.
This does not claim an external firewall prevents a compromised browser process
from using the role's egress network.

Goodreads pages live in worker-side PostgreSQL, not in the browser volume:
128 query-keyed rows, six-hour expiry and 2 MiB per page. Empty completed searches
are cached; challenges, unavailable responses and errors are not. Refresh
Goodreads bypasses that cache. Migration `0016_source_browser_page` adds only
replaceable application state. Populated upgrade verifies the new schema.
Browser HTML and export XML are parsed in a fresh credential-free application
child with 256 MiB address space, five CPU seconds and eight elapsed seconds,
so hostile markup cannot hold the worker in a provider regex.

The container workflow builds and exercises this image against disposable local
fixtures, without live provider calls. Its acceptance script is
`.github/scripts/source_browser_container_acceptance.py`; the original resolved
overlay is validated before any fixture-only rewrite.
