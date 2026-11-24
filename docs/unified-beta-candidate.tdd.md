# Unified beta candidate preparation

## Executed startup and fresh-cluster follow-up

The configuration now chains owner migrations, create-only PostgreSQL login setup,
the existing grant owner and a read-only effective-runtime check before foreground
admission. The scripts are read-only configuration mounts, leaving packaged app
inputs unchanged. The checker binds these roles, dependencies and execution
contracts, rejects environment shadows by presence and preserves production
credential/mount isolation. Seven shadow/missing-chain regressions failed before
the correction; verification-command refusal cases cover bypass attempts.

An owned two-cluster PostgreSQL 18 proof verified effective runtime grants, refused
the old ACL restore when the login was absent, then restored without ACLs and
reprovisioned the login in the different cluster. Historical job IDs/keys survive.
An empty-password regression caught psql's successful quit behavior; the corrected
guard fails under ON_ERROR_STOP. With transaction sampling enabled beforehand,
generated plaintext passwords were absent from server logs. Both owned clusters
and socket directories were stopped; captures remain private.

Mandatory actual-image acceptance resolves the real workspace entry, validates
it, and derives execution configuration with only explicit image/pull-policy and
isolated-network changes. It runs the deployed PGUSER path in web and worker,
real SQL denials, failed-provision/wrong-password/elevated-role admission failures,
and the existing EPUB source/report/held-output checks after fresh-cluster restore.
Both the current built image and the separately pinned released-image digest are
required. Promotion refuses missing/skipped proof steps. No local Docker or target
execution is claimed; runner and target acceptance remain distinct.

Independent read-only review found include/override composition, incomplete cleanup,
transaction-sampling logging, verification-command bypass and duplicated-entry
proof gaps. These were corrected before publication. Cleanup attempts all exact
owned projects and verifies containers gone before publishing a success result.
[The rollout procedure](runtime-rollout.md) records separate capture/rollback state
and actual-kernel holds rather than inferring them from the startup dependency graph.

## Startup proof review follow-ups

The first composed runtime run failed during startup. Its generic exception hid
the failed service, so startup failures now emit bounded, credential-redacted
service status and recent logs. Runtime admission reports fixed refusal reasons
or an exception type without connection details. Redaction runs before truncation;
regressions cover both retained service failures and suppressed credential values.

The elevated-login case now uses the correct runtime password. It must fail in
the owner provisioner before runtime admission runs; the wrong-password case must
finish provisioning and fail in runtime admission. Phase assertions prevent one
case from being credited for the other's refusal. SQL-denial proof requires the
insufficient-privilege SQLSTATE, rather than counting any database exception.
The checker also pins the login helper's command and PostgreSQL user. Actual
container reruns remain required; these corrections alone prove no image or
target compatibility.

The diagnostic rerun identified an empty synthetic catalogue mount: migration,
login, provisioning and runtime-ready completed, then the web process correctly
refused catalogue admission. Before starting each disposable stack, the harness
now uses the existing offline native-reference bootstrap builder in the selected
image to seed its fresh catalogue mount. The entry's catalogue setting and
read-only serving mounts remain enabled. Regressions exercise ordinary unpinned
startup admission, the stdin preparation command and refusal to replace a
nonempty fixture directory. Full composed-image acceptance remains required.

## Initial configuration validation

The candidate reuses existing registry, native-library, preserved-file and
assessment Compose owners and the existing runtime grant provisioner. One include
entry selects those roles; a small override separates owner initialization from
web/worker credentials. No application UI, book engine, job protocol, schema,
runtime dependency, account or library writer is added.

The previous resolved-config checker required every application role to share
PGPASSWORD, so a correctly separated initializer/runtime configuration refused.
Two executable CLI regressions failed on that implementation: valid separated
credentials, and valid separated beta/production credentials. The checker now
requires matching web/worker login/password, owner credentials bound to the
database service, independent owner/runtime passwords and one selected database.
Legacy shared-login configurations retain the same owner/endpoint checks without
acquiring a claim of least-privilege runtime grants. Independent review exposed
an initial conditional-check gap for shared logins and empty owner passwords;
four additional executable cases failed before those bindings were corrected.

Credential-overlap checks compare both candidate passwords against all observed
production database credentials. Negative cases cover mismatched runtime/owner
bindings, shared passwords, foreign database/host and missing login, plus each
owner/runtime cross-environment credential pairing. Output remains generic and
does not print either password. All 55 focused tests and the 232-test affected
release/configuration suite pass with warnings treated as errors. Helper types,
host-Python compilation, Ruff and changed-workflow Actionlint pass. The initial
relevant red run also encountered cleanup warnings from
unrelated earlier pytest temporary directories; the final run uses its own fresh
temporary root and has no warnings. No unrelated directories were changed.

Actual Compose resolution of the combined entry is required in the existing
container acceptance job, using synthetic masked credentials and its accepted
image identifier as a configuration fixture. This only resolves configuration;
it neither pulls that fixture as a registry digest nor proves runtime grants.
Local Docker is unavailable, so no local Compose or image pass is claimed.
Exact-head hosted source, image, populated-upgrade, writer/native gates and final
review remain required before the candidate source is accepted.

Target login provisioning follows owner migrations and precedes web/worker start.
Actual database privileges, kernel isolation, storage, capacity, coordinated
restore, image observation and authenticated/human journeys remain separate
target evidence. Registry publication, installation and stable acceptance are
not performed by this source preparation. The protected candidate packet owns
actual proposed version, source/image pins and operational continuation.
