# Operational support and recovery readiness

Issue #28 has a source and synthetic readiness increment. Target ownership,
capacity, physical durability and activation remain separate acceptance gates.
The operator owns incident decisions and capture coordination; the source
maintainer owns the report/receipt contract and reproducible image. A backup
custodian and recovery decision maker must be named privately before activation.
No monitoring, backup, retention cleanup or rehearsal schedule is enabled here.

## Read a bounded support report

From a source checkout root, run `python backend/manage.py support_report`
with the existing role's runtime configuration. In the packaged container the
working directory is already the backend, so use `python manage.py support_report`
(for example, `docker compose -f compose.dockhand.yaml -f compose.files.yaml exec -T web python manage.py support_report`). The command emits one JSON
object using `librarium.support-report.v1`. It requires local operator execution;
there is no diagnostics HTTP endpoint. The anonymous `/api/health` contract still
only checks database availability with `SELECT 1`.

Keep runtime configuration outside Git. `LIBRARIUM_DECLARED_IMAGE_DIGEST` may
supply a declared `sha256:` image digest. It is never evidence of the actual
running image. `LIBRARIUM_RECOVERY_RECEIPT` may select one retained private
rehearsal receipt, mounted read-only in the application. Its parent directory must
be mode `0700` and its file mode `0600`, both owned by the executing application
user (UID 10001 in the image). Provision these permissions outside the running
app under the approved configuration scope; the command never repairs them. A
root-owned or group/world-accessible receipt returns unavailable. Unconfigured values
remain unknown/missing. Store reports and evidence privately; review any selected
summary before sharing it. A report contains no books, library paths, endpoints,
accounts, credentials, job IDs, messages or raw errors.

| Signal | Meaning and limits | Operator response |
|---|---|---|
| Database available | One successful read on the configured application database | Availability only; does not prove worker, storage or upstream health |
| Database unavailable | Connection/read failed; raw error suppressed | Check private connection/credential/service evidence under incident authority |
| Jobs observed | At most 200 queued/running rows plus one truncation sentinel | Counts describe this sample, with no time window; never infer complete backlog when incomplete |
| Expired running lease | A sampled running job has an expired lease | Observation only; worker liveness remains unknown. Use existing exact-job recovery/cancellation contracts |
| Queued age/retries | Oldest queued age and jobs attempted more than once within the sample | Investigate sustained changes using private job evidence; no automatic retry or worker restart |
| Schema compatible | Applied application migration names exactly match packaged migration names | Does not validate table contents, constraints, grants or older releases |
| Schema incompatible/incomplete/unavailable | Missing/unexpected migration names, bound exceeded, or read failed | Action required before an upgrade decision; never auto-migrate from this command |
| Storage observed | Filesystem total, process-available bytes and available inodes for configured artifact/reference-state roots | Capacity observation, not a write test, library inventory, quota guarantee or database-volume measurement |
| Storage unknown/unavailable | Root unconfigured or capacity read refused/failed | Resolve privately; never create a directory or remount as diagnosis |
| Build known | Strict packaged source/assets fingerprint and release-owned compatibility | Source identity is distinct from independently observed image identity |
| Runtime compatibility incompatible | Packaged build policies/schema leaves differ from runtime source | Action required; inspect deployment provenance before new work |
| Recovery recorded | Retained compatible isolated rehearsal evidence inside the rehearsal freshness limit | Read its exact scope; grants no admission, writer or resend authority |
| Recovery stale/future/invalid/unsupported/incompatible/incomplete | Evidence cannot support a current compatible rehearsal observation | Action required for readiness claims; preserve evidence and arrange an approved isolated rehearsal |

The database reader uses a separate connection (three-second connection timeout),
a repeatable-read read-only transaction, two-second per-statement/lock deadlines,
and at most 257 migration rows. A failed schema read does not erase available job
observations. The job query filters queued/running work using the existing indexed state
predicate without counting or sorting finished history. It selects only states,
leases, creation timestamps and attempt counts. Finished jobs never crowd out
active observations. With more than 200 active jobs the arbitrary sample remains
incomplete; there is no ordering guarantee or exhaustive activity census. Job
ages and future creation counts use the database snapshot statement clock, taken
after connecting, rather than the earlier report-start time. Ages never become negative.

Capacity reads use no-follow directory descriptors and `fstatvfs`; they never
list artifacts, traverse libraries, create files or probe writers/upstream services.
Configured roots can share one filesystem, so their capacities must not be added.
Filesystem calls and connection name resolution have no guaranteed whole-command
deadline. A stalled network filesystem needs host-level incident handling. Database
capacity and external library/backup volumes remain unknown in this report.
The command returns JSON even when an observation is unavailable; callers must
inspect states rather than interpreting exit zero as all systems healthy. Failures
before Django command initialization remain the operator's private runtime errors.

## Bind build and recovery evidence

[Packaging](packaging.md) owns `librarium.build-identity.v1`, its source scope and
release compatibility. An unpackaged checkout has unknown build identity. There
is no runtime Git or ambient checkout dependency. The declared image digest and
`running_image_digest` are separate; the latter stays unknown. Before activation,
an operator must independently inspect the container runtime's immutable image
and reconcile it with the accepted release manifest. An environment value alone
cannot supply that observation.

The existing isolated EPUB and coordinated delivery restore harnesses retain
`librarium.recovery-rehearsal.v1` only after their actual restore assertions pass.
The record binds the tested build identity, compatibility, capture start,
recovery start/end and monotonic recovery duration. The capture timestamp describes
the start of that coordinated synthetic capture, not the oldest original change
or an assured recovery point. Backup age at recovery and current age remain separate.
Whole-harness elapsed time is never reported as recovery duration. A retained
duration that differs from its wall-clock start/end interval by more than two
seconds is invalid; clock steps require a fresh trustworthy rehearsal.

The EPUB interval begins before creating the disposable restore database and
restoring its dump/artifacts, and ends after source/report/validation
reopening. The coordinated delivery interval includes its separate database and
component restore, historical exact-key reads, original-byte checks, fresh writer
epoch and no-duplicate-operation assertions. It does not measure operator response,
new-host provisioning, remote transfer or real-library scale.

The reader accepts one strict, bounded (16 KiB) private regular file using existing
safe-file primitives. Unsupported versions, extra fields, duplicate keys, malformed
numbers/timestamps, unsafe files, mismatched source/build/compatibility, future
captures and stale rehearsals cannot become a current recorded success. Missing
build identity gives incomplete evidence. The report separately evaluates a
30-day rehearsal freshness limit and 24-hour capture currency; these are reporting limits, not delivery
admission rules or approved recovery objectives. Operator-controlled retained
records are evidence, not signed third-party attestation.

[Verified delivery recovery](delivery-recovery.md) remains the sole baseline and
admission owner. This report does not generate backups, verify a live baseline,
refresh supervision, remove a hold, reconcile by resending, or grant Undo.
Originals and historical receipts remain preserved under existing retention.

## Capacity and incident ownership

Before activation, record privately the application database/artifacts/reference
state and coordinated library/broker backup owners, volumes, available capacity,
restore destination and access/credential recovery method. Database dumps must
match the captured generation of preserved sources/reports/corrected copies,
reference registry/state, broker journals, operation manifests and library bytes.
Retain immutable image/release manifests and exact checker/policy/schema identity.
Protect configuration/keys separately with recovery access; exclude credentials
from reports, source control and shared evidence.

Provision enough room for the live state, one full isolated restore and retained
backup generations without deleting originals. A provisional warning threshold is
20% available space; urgent review is below 10% or when the next full capture plus
restore cannot fit. Those thresholds require target sizing and growth observations.
Do not add duplicate filesystem figures or assume compressed dump size predicts
artifact/library space. Reserve inode and temporary restore capacity as well.

For an incident, record the first failed observation and accepted runtime identity
privately. Preserve immutable evidence and backups. Establish who owns the failed
component and whether the symptoms are availability, capacity, compatibility or
uncertain external outcome. Inspect only the relevant private logs after that
scope is approved. Keep uncertain deliveries held, use exact historical keys,
and never resend because a support report is unavailable. Stop/restart, rollback,
real-library reads/restores and deployment require their existing authorization.
A restore must target a separately approved destination with writers excluded and
must prove usable database/artifacts, exact keys, originals and historical evidence
before any cutover decision. Do not overwrite the only usable generation.

## Proposed cadence and initial objectives

These proposals require concrete approval before any recurring work is enabled:

| Proposal | Retained components and location class | Proposed retention |
|---|---|---|
| Five-minute bounded support observation | Small sanitized JSON in protected operator storage; alert routing selected privately | Seven days of samples; no book/log payloads |
| Daily coordinated capture and before migration/writer activation | Existing backup tooling, database/artifacts/reference state plus coordinated library/broker generation; encrypted independent storage | Seven daily and four weekly generations, subject to measured capacity |
| Monthly isolated restore and after recovery-affecting changes | Existing acceptance/restore owners, separate destination; strict receipt plus private detailed evidence | Latest three successful rehearsal receipts and associated recoverable captures |

Indefinite originals and operation evidence retention is unchanged. This proposal
never authorizes deletion, replacement or retention cleanup. Approval must name
custodians, destination/storage budget, coordination/quiescence window, encryption
and key recovery, alert recipient/escalation, exact schedule, retained components,
retention exceptions and who can authorize a real restore/cutover. Source changes
and this document enable none of them.

A reasonable first synthetic objective is a successful exact-byte isolated restore
with capture age under 24 hours and the measured recovery interval under five
minutes on the same prepared fixture environment. Evaluate the retained measurement
and separately identify setup/transfer/operator time. This is a test objective, not
a target RTO or RPO guarantee. Production objectives need a target-scale rehearsal,
measured capture frequency/consistency, host/storage/kernel acceptance and owner
approval. Physical storage loss and device/audio reading remain unverified here.

## Reuse and verification

This increment composes the existing Job model, release compatibility owner,
private-file primitives and actual EPUB/delivery restore assertions. Retained LF
health/baseline concepts (`a2a3692`, `bin/calibre_bridge.py`) and BLC health/version
concepts (`a8f2744`, `src/bl_catalog/api/app.py`) informed the signal split. Their
network probes, paths and raw errors are unsuitable for this projection. The
existing recovery/changeover evidence supplies the backup authority; no second
backup or job algorithm is introduced. Python/Django/PostgreSQL and standard
filesystem primitives provide the missing bounded glue without a new dependency.

[Verification evidence](operational-support.tdd.md) owns the actual local checks
and limits. Hosted exact-image acceptance and issue #28's unperformed target gates
remain open until independently verified.
