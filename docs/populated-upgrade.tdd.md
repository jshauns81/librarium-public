# Populated upgrade verification

This record covers the routine source/synthetic portion of issue #25.
[The procedure](populated-upgrade.md) owns historical-baseline labels, the state
sequence, recovery scope and the remaining activation packet.

The public fixture preserves the historical schema-0005 runtime. The tests verify its pinned manifest and input files. The candidate build and its source export are bound to the exact public commit. The private release pipeline owns verification against the released image digest.

## Evidence boundaries

The harness must distinguish old-engine completed work, seeded negative pending
jobs and work completed by the candidate. Retained IDs, request keys, captured
policies, result/report hashes, source bytes and artifact mode/ownership evidence
are checked at each applicable transition. A pre-upgrade recovery remains separate
from the current generation and discloses all post-upgrade work it excludes.

Failing-first negative coverage belongs to the executable regression suite and its
protected receipts. Required cases include wrong baseline/source/tree/policy,
incomplete/incoherent capture, changed artifact bytes/modes/ownership, obsolete
pending policies, incompatible worker overlap, failed migration, unsupported
image-only rollback and held unavailable target/kernel evidence. A unit snapshot
alone cannot certify a populated migration or restore.

## Earlier source rehearsal

The source/runtime rehearsal has run against a newly initialized, socket-only
PostgreSQL 18 cluster using matching 18-series clients and disposable database and
artifact roots. The old exported source completes real catalogue metadata,
structural inspection and EPUBCheck jobs. The checker finishes with expected
conformance findings; job completion does not mean the EPUB passed conformance.
A separate queued old-policy job supplies the pending refusal case.

Actual migrations reach 0010. Current roles use the existing least-privilege
provisioner, reopen unchanged old evidence and refuse the queued old policy without
rewriting its captured input. The execution owner must specifically refuse the captured policy in a preflight
against the unchanged input. The real worker retains its generic private-failure
message and publishes no report. New current inspection/checker work runs through native children, and
one stored retired-kind row (L091) is verified to stay unclaimed and readable as history. Fresh actors reopen those
results after web replacement and after coordinated PostgreSQL/artifact restore.
The retained pre-upgrade generation reopens separately under the old source.

The source runs emit strict receipts through the existing recovery owner for
`isolated_populated_upgrade` and `isolated_pre_upgrade_generation`, with measured
capture age and recovery duration. Local unbuilt source has null packaged-identity
bindings and remains incomplete as package evidence. Only the current-generation
scope includes the retired-history assertion (the corrected-copy and preservation
assertions were removed with the generation pipeline); neither scope attests
to a writer, no-resend operation, original released image or target-scale RTO/RPO.

Failing-first evidence includes missing harness/adapter imports, altered capture
bytes/modes/ownership, wrong baseline pins/policy and direct launcher attempts
before migration or after unsupported image-only rollback. The real rehearsal
injects a relation conflict into a separate restored database: migration fails
there, and current work is never admitted on that failed state. All ordinary
accepted state and both retained generations remain intact. An integration run
caught an overly strict pre-current artifact inventory after corrected-copy
creation; the adapter now permits added current artifacts while verifying every
retained artifact and recording the complete new inventory.

Python types, Ruff, workflow syntax, schema/lock/runtime-export consistency,
workspace integrity and private-denylist/public-content checks are part of the
source delivery. Independent review identified image-file exclusions, interpreter installation,
container readiness, failure classification, loss disclosure and cleanup gaps.
The fixes apply the exported `.dockerignore`, install the pinned CI interpreter,
probe the final TCP database server, require the injected relation conflict and
exact applied migration prefix, guard each database independently, enumerate lost
jobs/results/artifacts and pending-state changes, and retain per-resource cleanup
outcomes without masking the original error. Source exports must contain the exact
tested harness/adapter; safety checks remain active with Python optimization.
Exact counts, revision hashes, measurements and superseding failures are retained
in the private handoff. Final exact-head hosted image checks and review remain
separate from this local review and its corrections. No frontend change
or rendered acceptance is part of this block.

## Parent workflow launcher regressions

The first hosted populated-upgrade attempt stopped before the rehearsal because
the pinned uv CLI rejects `python find --python`. A regression executes the actual
workflow setup with a generated checkout and a synthetic harness probe. It first
reproduced that CLI error, then Git's checkout-ownership refusal at the privilege
boundary. The corrected launcher uses the positional Python request and scopes
Git trust to the exact checkout through the command environment. Another checkout
remains refused; no global Git setting is changed.

The probe avoids privilege escalation and Docker while testing interpreter
resolution and Git's owner-check behavior. The pinned uv 0.13.6 run passed all
166 focused parent cases after both corrections. The earlier source migration
and recovery proof remains bound to its original submitted revision; these
launcher changes require fresh hosted image gates and review. No application,
migration, fixture adapter or recovery-harness behavior changed.

## Remaining acceptance

The next hosted attempt passed launcher setup and reached database preflight, then
the image transport placed connection options before `pg_dump --version`. The real
PostgreSQL 18.6 client reproduced that refusal. A regression replaces only Docker
transport and executes the real client's received arguments; it failed before
the fix. Version-only probes now omit connection options, while database commands
retain their final-server TCP endpoint and environment-based authentication.
All 167 focused parent tests pass with the explicit matching client. This probe
never opens a database connection and does not certify the image rehearsal.

Actual affected baseline/candidate images remain mandatory hosted gates alongside
the existing source, container, native-delivery and writer-image checks. Local
Docker is unavailable, so local source proof is not image proof. Issue #25's
unobserved target image/kernel/storage/capacity/custody gates and issue #26's
approved activation/human observation remain open. Nothing is newly installed for
an owner to test as a result of this source block.

The corrected client preflight let the hosted image rehearsal finish successfully;
its job then failed while exporting proof because the unprivileged shell expanded
a wildcard inside the private output directory before elevation. An executable
workflow regression reproduced that exact copy error. Export now names the five
portable JSON files explicitly. The regression grants access only inside a
synthetic privileged invocation, verifies every copied byte, leaves unrelated JSON
and diagnostics behind, and preserves the private-directory boundary. Actual image
acceptance still requires successful proof retention and the aggregate gate.

## Promotion evidence follows the split acceptance jobs

Hosted review reproduced a successful beta run being refused because promotion
still looked for packaged checks inside the aggregate container job. The verifier
now requires distinct candidate, populated-upgrade and aggregate job records from
the same successful attempt, including the named package, export, rehearsal, proof
retention and aggregate steps. A complete split-job record passes read-only
verification. Missing or skipped jobs and missing, skipped or duplicate required
steps refuse without publication. Existing source, digest, owner-attestation and
human-observation checks remain required; no release was promoted by these tests.
