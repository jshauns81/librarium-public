# Populated historical-source upgrade and recovery

This procedure owns the isolated routine rehearsal for issue #25. It is a source
and synthetic-state acceptance gate. Target activation, recovery custody and the
human observation gates in issues #25 and #26 remain separate. Librarium remains
one book application; upstream project names describe engineering provenance.

## Historical baseline and tested identity

The baseline is the **sanitized historical source/schema fixture** at commit
`bf7af4d0042d452bfc7d288b92046861f63c2743`, tree
`6cfc1a5c9554629f84a504bfed6ca3ef13165e8b`. It is a current-main ancestor with
migration leaf `0005_epub_validation_jobs`. The candidate advances through actual
migrations to `0012_cataloguestatus`. Baseline selection must verify the full
commit, tree, ancestry, migration leaf and captured policies before executing it.
An earlier preservation snapshot is not an acceptable portable baseline.

A rebuilt historical-source image is not proof of an original released image's
digest. Neither the old fixture nor a candidate test observes an installed target.
The rehearsal records exact source exports, tree/schema/policy identities,
fixture inputs, artifact/result hashes and image identities when images run.
Source-runtime proof and actual-image proof must stay separately labelled.
Do not use a retired release number or publish an archive, image, tag or release
as a side effect of running this rehearsal.

The reusable harness is [populated_upgrade.py](../scripts/populated_upgrade.py),
with [upgrade_fixture.py](../scripts/upgrade_fixture.py) supplying synthetic work
through existing application owners. Consult its `--help` for the implemented
invocation. Source exports use disposable build contexts, without a Git worktree
or a shared-checkout reset. Fixture databases, artifact roots and exact owned
processes must be distinct from any retained state. An omitted prerequisite is a
held result, never permission to discover or contact a target.

## State sequence and evidence

1. Initialize the historical schema using its source/runtime. Generate synthetic
   inputs and complete supported metadata, preserved-EPUB inspection and checker
   work through that engine. Record durable IDs, request keys, captured policies,
   results and immutable artifact bindings. A seeded obsolete pending job must
   be identified separately from work actually completed by the old engine.
2. Stop admission, drain work and stop only the owned old web/worker processes.
   Confirm termination before capture or candidate migration. An incompatible
   old/new worker overlap must refuse. A script's intention to stop a role is not
   termination evidence.
3. Capture PostgreSQL and the complete immutable artifact root as one stopped-role
   generation. Bind the dump and artifact inventory by exact hash, including
   file modes and ownership. Incomplete or changed captures must refuse before
   migration or recovery acceptance.
4. Run the actual candidate migrations as the schema owner. A migration failure
   holds all new runtime starts. Provision the dedicated least-privilege runtime
   role through the existing owner command when that role is part of the tested
   configuration. Start only compatible candidate roles after successful schema
   and captured-policy checks.
5. Reopen historical evidence through current readers and verify retained source,
   report, checker, IDs, request keys and result bindings. Completed historical
   work keeps its captured assurance. Obsolete pending policies must fail through
   the current execution contract; never edit captured inputs to make them run.
6. Complete representative current work and verify it through role replacement.
   Capture a separate coordinated current generation, restore into a new isolated
   database/artifact root and reopen the same evidence and keys. Add one stored row of
   a retired job kind (L091) and verify the current worker leaves it untouched and
   it reads as plain history (cancelled, with no result); the writer core's
   acceptance keeps its own approval/no-resend boundaries. The historical sources
   predate corrected output, so the rehearsal creates that retired row itself.
7. Refuse image-only rollback to the old source against migrated state. This is
   a rehearsal-orchestration guard. The historical application has not acquired
   a production schema guard merely because the rehearsal prevents that launch.
8. Restore the retained pre-upgrade generation into a separate old-compatible
   database and artifact root. Reopen usable old evidence under the old runtime.
   Preserve the migrated/current generation and explicitly list the current jobs,
   results and artifacts that returning to the earlier generation would lose.
   Reverse migration or evidence deletion is not a rollback shortcut.

Use the existing [recovery receipt owner](operational-support.md#bind-build-and-recovery-evidence)
for capture timestamps and the separately measured recovery interval. Report the
capture's age at recovery start, receipt binding and exact restored scope. Recovery
time excludes prior source preparation/builds and is not a target-scale RTO.
Capture age is not a claim about capture frequency or a target RPO.
A checkout without packaged build identity must retain unknown bindings; it must
not fabricate a package identity to produce a current report.

## Reviewable activation packet

Keep the candidate packet in protected configuration outside the checkout. Its
portable engineering portion can identify the tested source and synthetic gates;
actual endpoints, paths, host inventory, credentials, custody and operational
handoffs stay private. Before any target action, the packet needs these facts:

| Field | Required evidence or current boundary |
|---|---|
| Candidate | Exact reviewed source/tree, build/image digest, schema leaves, captured policies, harness/fixture hashes and exact-head CI outcomes |
| Historical generation | Full sanitized source/tree pin and explicit source/runtime or rebuilt-image scope; no original-image equivalence claim |
| Roles | Proposed admission stop, exact-owned drain/termination, owner-only migration and compatible web/worker start order; writer stays disabled unless separately authorized |
| Configuration | Protected runtime credentials; read-only catalogue/library/reference mounts only for roles that need them; separate private immutable artifact root |
| Capture/recovery | Coordinated database and artifact generation, exact digests/modes/ownership, separate restore roots, measured capture age and recovery interval |
| Loss boundary | Exact post-upgrade work absent from the retained pre-upgrade generation; retained current generation remains available for review |
| Retired work | Count of stored jobs of the six retired kinds still queued or running, and of stored delivery receipts, taken before installation, with how each is handled; an earlier release can still lease such a row, so every earlier web, worker and delivery process is stopped first; after installation the rows stay stored, are not claimed by the current worker and remain inert until cancelled through `POST /api/jobs/<id>/cancel` |
| Installed state | Independently observed running image, schema and policy compatibility; unobserved until a target survey is authorized |
| Host and storage | Kernel isolation, filesystem behavior, capacity/headroom, durability and backup custody; synthetic results do not certify these |
| Access and supervision | Accepted proxy/authentication/session boundary, operator authority and writer supervision; no account or authentication redesign is implied |
| Human acceptance | Separately approved activation and 48-hour observation, with concrete retained outcomes and recovery ownership |

Until the missing target evidence and authority are supplied, the activation
packet stays held. Source publication and automatic synthetic CI authorize no
installed update, target survey/resource change, library read/write/import/restore,
service restart/retirement, credential change, recurring work or release dispatch.

## Reuse and scope

The reuse review considered retained BL Catalog and Library Finish source contracts,
current carry-over decisions and the Library Finish changeover evidence. Their
engines supply catalogue/EPUB evidence and writer/recovery constraints. Librarium's
existing Job protocol, initializer/migrations, file artifacts, historical readers,
EPUBCheck, runtime-role provisioning, release/build compatibility and recovery
receipts supply execution and evidence ownership. PostgreSQL dump/restore and
standard-library orchestration supply the missing transition proof. This adds no
second backup engine, job engine, bibliographic resolver or dependency.

[Verification evidence](populated-upgrade.tdd.md) records actual failing-first and
isolated checks. [Packaging](packaging.md) owns supported schema/role compatibility;
[release policy](releases.md) owns publication and activation decisions.
