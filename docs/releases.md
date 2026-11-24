# Beta and production releases

Owner: Librarium / the maintainer. Established 2026-10-27 under L035.

The [roadmap](roadmap.md) describes the release goals.
[Packaging](packaging.md) owns image and schema compatibility, and
[Dockhand](dockhand.md) owns target installation and recovery procedures.

## Channels and versions

Use Semantic Versioning: `vMAJOR.MINOR.PATCH`, with `-beta.N` for candidates.
The first release line is `v0.1.0-beta.1` through an accepted beta, followed by
`v0.1.0`. Existing package metadata is already `0.1.0`; it does not constitute a
published release. During `0.x`, a minor release may change application contracts;
document every incompatible API, schema, policy or configuration change. Patches
repair the stated release scope. `1.0.0` requires the migration and recovery goal,
not simply a polished read-only interface.

| Channel | Audience and scope | Publication | Runtime |
|---|---|---|---|
| Development | Reviewed feature work and synthetic proofs | Branch PRs and CI results | Local/disposable state |
| Beta | Restricted testing of the next bounded release | GitHub Pre-release and private GHCR image | Separate beta stack, credentials, database and artifacts |
| Production | Accepted release for daily use | GitHub Release promoting the accepted beta digest | Explicitly approved activation on a target that meets the [runtime requirements](decisions.md#l079-deployment-kernel-requirements) |

`main` stays releasable. Use short topic branches and PRs; do not maintain a
permanent beta branch. Beta and stable tags point to the same accepted source
commit. A new fix means a new commit, image and beta number. Published version
tags and release assets must never be overwritten to conceal a correction.

Beta candidates are cut when a complete slice passes its gates, with a weekly
review of readiness during active development. Stable releases follow milestone
acceptance rather than a calendar deadline. This policy creates no scheduled job.
Support the latest stable release and the current beta; repair an older stable
line only for a concrete recovery need. Every hotfix still gets a tested beta
artifact before promotion. the maintainer may record a shorter beta observation period
for an urgent fix, with the reason and remaining risk in its release issue.

## Build once, test it, promote it

The release contract is:

1. A reviewed PR passes source checks and the existing actual-image `container`
   check. UI changes also need the rendered journeys required by UX standards.
2. A manual beta-publication workflow accepts a strict beta version and a full
   commit SHA reachable from `main`. It verifies source checks at that exact
   revision, builds application and source-browser Linux `amd64` images, and runs the complete packaged
   application, file-role, worker-replacement and database/artifact restore tests
   against the application image. The browser must pass its isolation, native
   sandbox and driver acceptance. The same job exports both accepted images and
   a receipt binding their config digests to that source commit. Test failure
   publishes nothing.
3. The workflow loads the accepted exports without rebuilding, verifies both
   config digests, and pushes them to private `ghcr.io/jshauns81/librarium` and
   `ghcr.io/jshauns81/librarium-source-browser`. It checks each registry manifest's
   bytes and config digest. A GitHub draft receives `release-manifest.json` and
   `stack-assets.zip`; their uploaded sizes and SHA-256 digests must match before
   the prerelease becomes visible. The annotated version tag identifies the tested source. A
   `sha-<full-commit>` tag and `0.1.0-beta.N` tag aid discovery; runtime references
   always use each repository's `@sha256:<digest>` reference.
4. After approved beta activation and acceptance, a separate manual promotion
   workflow verifies the beta release manifest, both registry/config digests,
   source-bound stack archive and release-issue evidence. It requires the beta
   tag, both expected registry digests, stable
   version and an explicit `PROMOTE` input. It rejects an existing stable version
   and any mismatch. It applies the stable tag to both existing manifests,
   without building, then verifies both stable digests and every manifest byte.
   Both images must verify before a Git tag or Release is created. The stable
   Release retains the identical stack archive. The stable
   Git tag points to the same source commit as the beta.
5. Publish the GitHub Release with the immutable image reference, acceptance
   evidence, changes, known limits, migration instructions and recovery plan.
   Mark the stable release as latest; pre-releases never become latest stable.
6. Activate the approved target in a separate, recorded operation. Publication
   does not deploy the application or approve a library writer.

Mutable `beta` and `stable` image aliases may help discovery once automation
exists. They are never deployment inputs. Keep every active deployment's digest,
the previous two stable images and matching recovery assets; no automated
package or backup deletion is introduced by this policy.

Each release attaches a machine-readable `release-manifest.json` containing:

- Version, channel, complete Git commit and source repository.
- `images.application` and `images.source-browser`: immutable image reference,
  accepted config digest, source commit and platform for each role. The top-level
  `image` field remains the application reference for existing readers.
- Acceptance workflow run and check result, including browser acceptance.
- `stack_assets`: deterministic ZIP name, archive SHA-256 and per-file SHA-256
  values for the registry Compose stack, overlays and browser seccomp/provenance/license.
- Required configuration and supported migration/policy versions derived from
  that revision, rather than hardcoded assumptions about future schemas.
- Previous supported release, upgrade/recovery instructions and known limits.
- Beta acceptance and promotion issue/evidence links for a stable release.

New paired releases use `librarium.release.v2`. A missing role, accepted-image
receipt or stack archive fails closed. Historical single-image v1 releases stay
readable as history; this verifier refuses to promote them or infer a missing
browser image. A new tested beta is required.

A registry cannot transact across two repositories. A failed second push/copy
can leave one reserved version tag. Such a version is incomplete, must not be
installed, and is never overwritten or automatically rolled back. The shared
release concurrency group serializes the normal publisher/promotion path;
operators must inspect partial registry, Git and draft identities before choosing
a new candidate version. Consumers select a complete published release manifest,
not the existence of a registry tag.

Generate change lists through [.github/release.yml](../.github/release.yml), then
edit them into user-facing notes. Include configuration, compatibility, backup,
security and known limitations even when generated PR lists omit them. Never put
credentials, book contents or personal database backups in Actions artifacts or
release assets. Retain CI evidence with the release manifest so an expired CI
artifact is not the only copy of release identity.

## Environment isolation and activation

The reusable container workflow also requires the `populated-upgrade` job. It
consumes the exact candidate image accepted by `candidate-container`, rebuilds the
pinned sanitized historical-source fixture, and verifies populated forward migration
and separate pre/current-generation recovery. Beta publication depends on the
whole reusable workflow; the existing `container` check also aggregates both jobs
and fails if either fails or is skipped. Exporting an image alone is insufficient. See the
[procedure](populated-upgrade.md) for its synthetic scope and remaining target gates.

Beta is a separate deployment, initially a restricted read-only product. Give it
its own Compose project name, appdata root, database, secret key, database
password, artifact directory, edge network and reverse-proxy upstream. A separate
origin is required. Record each candidate’s activation scope and verify its exact image, isolation, recovery and health before installation.

Do not reuse production writable mounts or live database credentials in beta.
Use synthetic inputs or a specifically approved, isolated restore. A validated
catalogue snapshot may be copied read-only. Beta must never select the production
library writer. Use an independent edge network: both stacks currently advertise
the `librarium-web` alias, so sharing their edge network could route users to the
wrong environment. Parameterize the public origin before beta activation;
`compose.dockhand.yaml` currently fixes it to production.

Create a target-activation issue naming the environment, immutable digest,
enabled roles, source/snapshot pins, state changes, backup/restore evidence and
recovery action. Obtain the maintainer's concrete approval of that issue before target
mutation. Record the approval source and time. Beta approval does not approve
production, and production approval does not approve a library-content write.

Before each activation:

1. Inspect actual target images, schema, jobs, mounts, disk capacity, source pins
   and authentication. The last documented runtime `b1822a4` is dated 2026-10-25;
   it is not proof of today's state.
2. Prepare a registry-pull Compose path with no build directives or
   `pull_policy: build`. Disable Dockhand build-on-deploy for that path and pin
   initialize, web and worker to the same image digest. The existing build-based
   Compose path remains the current implementation until this work is tested.
3. Stop admission of new jobs, drain compatible work and stop old web/worker
   processes. Record any incompatible pending jobs; never delete evidence to
   make an upgrade pass. Take a coordinated PostgreSQL and artifact backup after
   writes stop, recording old image, schema and catalogue pins with it.
4. Verify a restore into separate state before the first populated upgrade or
   any new migration/backup procedure. Preserve artifact ownership, modes and
   digest bindings. A database-only restore is insufficient for file jobs.
5. Run migrations with the candidate initializer, then start the compatible
   web/worker pair. Do not run old and new workers together across incompatible
   schemas or policy transitions. These releases use a maintenance window;
   rolling or canary traffic is inappropriate until compatibility is proven.
6. Check health, authenticated access, catalogue/library read journeys, job
   completion, reconnect/cancel/retry and recovery. Enabling the optional file
   role also requires a candidate-container check of Landlock/seccomp support on
   the actual target kernel; GitHub runner success does not establish this.
7. Record the running digest, migration result, checks and observation period.
   Mark a GitHub Deployment successful only after those target checks succeed.
   Package publication alone must never create a successful runtime deployment.

For the first stable release, require at least 48 hours of beta observation,
one representative user session and a restart/reconnect check, with no unresolved
data-integrity, security, lost-action or release-blocking accessibility defects.
Low beta usage is not evidence of reliability; run the release journeys explicitly.

If code and state remain compatible, restore the retained previous image digest
and verify both processes. Across schema changes, choose fix-forward or restore
the coordinated pre-upgrade database and artifacts before starting compatible old
code. Reverting an image does not reverse migrations. Schema `0003`–`0005`
guard populated evidence against reversal, and newer workers reject unsupported
pending inspection policies. State restoration may discard later application
work; name that loss in the activation issue before approval.

## Explicit beta acceptance record

Elapsed time, a closed issue, successful CI and a reachable login page cannot
establish beta acceptance. Promotion requires a separate human attestation in an
unedited GitHub issue comment in this repository, authored by the repository owner as a `User` with association `OWNER`. No workflow or helper creates
or posts this record. A release operator selects its numeric issue/comment IDs;
the verifier fetches the comment and evidence through fixed repository APIs.

The entire comment body must be JSON using schema
`librarium.beta-acceptance.v2`, with these exact fields:

| Field | Required meaning |
|---|---|
| `schema` | Exact acceptance schema above |
| `repository` | `https://github.com/jshauns81/librarium` |
| `beta` | Exact published prerelease tag |
| `source_sha` | Complete lowercase source commit SHA |
| `image_digest` | Exact application `sha256:` registry manifest digest |
| `source_browser_digest` | Exact source-browser `sha256:` registry manifest digest |
| `observation` | `started_at` and `ended_at`, strict UTC `YYYY-MM-DDTHH:MM:SSZ` |
| `representative_session` | `complete: true`, plus nonempty `evidence` comment URLs |
| `restart_reconnect` | `complete: true`, plus nonempty `evidence` comment URLs |
| `blocking_defects` | Empty array after explicit review of the blocker classes |

`representative_session.complete` attests a real authenticated session exercising
the release's supported catalogue/library, evidence, history and job-recovery
journeys, rather than a sign-in redirect or an anonymous health probe.
`restart_reconnect.complete` attests that supported jobs and return context
survive the applicable restart/reconnect checks. The blocker review covers data
integrity, security, lost actions and release-blocking accessibility defects.
Disabled roles cannot acquire acceptance from checks of enabled roles; file-role
activation retains its separate actual-kernel gate.

Observation must start no earlier than beta publication, last at least 48 hours,
and end no later than acceptance-comment creation. Future timestamps, edited
comments, duplicate/unknown JSON fields and incomplete evidence refuse promotion.
The interval describes observed operation of the selected installed digest;
waiting since package publication does not constitute runtime observation.
Evidence links must identify existing issue comments in this repository, created
after beta publication and before acceptance. The verifier retains their body
hashes along with the acceptance comment ID, issue, timestamps and body hash.
This is an accountable operator attestation, not automated proof of human use
or cryptographic protection of a mutable GitHub comment.

Promotion re-fetches the beta release/asset, annotated tag, publication run and
attempt-specific required jobs, acceptance and evidence immediately before
mutation. Any changed proof refuses publication. Release asset downloads may
follow one HTTPS redirect from the fixed GitHub API asset endpoint to
`release-assets.githubusercontent.com`, without credentials or cookies; further
redirects refuse. Asset size and GitHub-recorded SHA-256 must match the downloaded
bytes. Other transport/auth failures never mean an unused version.

The initial verifier also requires the publication run's `head_sha` to equal the
selected source SHA. General beta publication can build an older main-reachable
source while running a newer workflow; that combination is held for promotion
until separate exact-input provenance is supported. Do not infer the selected
source from a workflow revision.

Before dispatch, review the beta's user-facing release notes and limits along
with its acceptance evidence. Stable notes preserve that candidate text under a
labelled historical section and add exact promotion, image, source and recovery
links. The candidate-notes hash is part of preflight proof. A needed correction
must be reviewed before starting; an in-flight edit refuses publication. The `PROMOTE` input is an
explicit publication intent, not an environment reviewer gate.

The manual workflow inputs are `beta`, `source-sha`, `digest`, `browser-digest`, `stable`,
`acceptance-issue`, `acceptance-comment` and `confirm` (`PROMOTE`). Use the existing
owner evidence; neither issue closure nor a workflow can create acceptance.
Read-only `promotion.py verify` writes proof and prints its canonical hash;
`publish` repeats verification with `--expected-proof` before any mutation.
Both CLI modes also enforce the manual main/repository context. The workflow
uploads preflight proof and successful stable-manifest evidence for 30 days;
the Release retains the stable manifest and stack archive beyond that artifact window.

Promotion shares the beta publisher's serialized `librarium-release` concurrency
group and rechecks that the stable registry tag, Git tag and Release are absent.
A partial publication reserves that stable version even if later steps fail.
Retain its run and artifacts; prepare a new matching beta/stable version line
after repair. Do not delete a tag, overwrite a release asset or reuse the partial
version to make a retry succeed. No shorter-observation exception is automated.

## GitHub controls and current implementation

Protect the default branch with review and required checks. Protect release tags against modification. Keep target activation credentials outside CI. Parse version tags before publishing.

Use `contents: read` by default. Grant `packages: write` only to publication and
promotion jobs and `contents: write` only where tags/releases are created. Build
and test jobs do not need registry or deployment credentials. Pin third-party
actions to reviewed complete commit SHAs; untrusted PR input must not enter a
privileged shell context. External private GHCR pulls require a protected
`read:packages` credential on the target; provision it only when that deployment
is authorized, never in source or release assets.

The beta implementation is in `.github/workflows/beta.yml`, with reusable
`quality.yml` and `container.yml` gates. `scripts/release.py` validates beta
identity and derives compatibility from source; `scripts/registry.py` verifies
registry manifest bytes and the accepted image config digest. The publication
job consumes the image exported by the acceptance job and does not rebuild it.
The separate `compose.registry.yaml` path has no build directive; validate its
resolved JSON with `scripts/registry_config.py`, optionally comparing protected
production JSON with `--compare`. Never put resolved secrets into CI artifacts.

Both source checks and actual-image tests must pass for the selected source.
Pipeline and target execution evidence belongs in
[private engineering record](agent-environment.md#private-context-discovery), including limitations.
Stable promotion tooling is implemented in `promote.yml` and
`scripts/promotion.py`, with acceptance defined above and
[private engineering record](agent-environment.md#private-context-discovery); it has not
published a stable release. No runtime success is recorded by a publication workflow. Partial
publication reserves its version: retain the failed run and artifacts, repair the
cause, then use a new beta number rather than overwrite an existing version.

Review supported dependency releases and advisories weekly during active work,
and before each beta. This creates no scheduler. Coordinate Python/Node locks,
runtime export, native/JRE/checker pins and compatibility tests in reviewed PRs.
Do not silently auto-merge dependency updates.

## Sources and feature limits

Verified against official documentation on 2026-10-27:

- [GitHub deployment environments and protection availability](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
- [Rulesets and plan availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).
- [Artifact attestations and private repositories](https://docs.github.com/en/actions/concepts/security/artifact-attestations).
- [GitHub Container registry authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
- [Generated release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes).
