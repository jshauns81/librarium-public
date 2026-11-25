# CI execution contract

All public repository workflows execute on GitHub-hosted Ubuntu 24.04 runners.
Every job that executes steps declares a literal `runs-on: ubuntu-24.04`.
Reusable-workflow callers inherit the runner declared in the called workflow.

## Workflows and acceptance cadence

| Workflow | Jobs | Acceptance cadence |
|---|---|---|
| Source quality | `source-quality` | Relevant checks on every PR; full main-push and beta calls; 30-minute timeout |
| Container acceptance | `changes`, `container` | Every PR, main push, manual dispatch and beta call |
| Container acceptance | `candidate-container` | Packaging/runtime or upgrade-contract PRs; full main-push, manual and beta acceptance |
| Container acceptance | `populated-upgrade` | Migration/compatibility/recovery PRs; full main-push, manual and beta acceptance; lightweight deferral after other selected builds |
| Synthetic writer acceptance | `pinned-writer-image`, `native-role-proof` | Writer-related `pull_request.paths`, nightly `schedule` on `main`, `workflow_dispatch` |
| Publish beta | `validate`, `rehearsal`, `publish`, and reusable `quality` and `acceptance` | Rehearse the main commit, then finalize the reviewed private images |
| Promote accepted beta | `verify`, `publish` | Existing manual promotion |

`ci-policy.yml` always runs its `ci-policy` job (check `Inspect CI policy`)
on literal `ubuntu-24.04`. Its `pull_request_target` event and trusted-base
checkout reads candidate workflow files as data.
`lint-actions.yml` also runs on literal `ubuntu-24.04`; it checks out the
repository with `persist-credentials: false` and reads workflow files as data
without executing candidate application code.

## Workflow linting

`.github/workflows/lint-actions.yml` runs `lint-actions` on `pull_request` and
`push` to `main` with `permissions: {}` at the workflow level and
`contents: read` on the job. It verifies workflow syntax, embedded shell and
Python scripts, and GitHub Actions security posture:

- `actionlint` 1.7.12, installed from its official release archive after SHA-256
  verification, with the runner's `shellcheck` and hash-pinned `pyflakes`
  active in an isolated virtual environment.
- `zizmor` 1.32.0 via `zizmorcore/zizmor-action` pinned by commit SHA, using the
  `regular` persona, `min-severity: low`, `advanced-security: false`, and online
  audits enabled with `GH_TOKEN`.

With `shellcheck` and `pyflakes` 3.4.0 installed, run both linters and the
local policy validator before pushing workflow changes:

```sh
actionlint \
  -shellcheck "$(command -v shellcheck)" \
  -pyflakes "$(command -v pyflakes)" \
  -ignore '^shellcheck reported issue in this script: SC2129:style:'
GH_TOKEN=$(gh auth token) zizmor --persona=regular --min-severity=low .github/workflows
python3 scripts/ci_policy.py --local .
```

## Change classification and required results

`.github/scripts/changed_areas.py` retains Python/frontend/docs selection and adds
`candidate_container` and `populated_upgrade`. Ordinary backend, frontend, docs
and unrelated workflow PRs defer both image acceptance tiers. Packaging/runtime
changes select the candidate: Dockerfiles, root Compose variants, Python pins,
requirements, build/runtime scripts copied or executed by the image workflow,
runtime settings, checker distribution and container/acceptance helpers.
Migrations, source compatibility declarations, recovery modules, rehearsal tools
and their tests select populated upgrade. The container workflow and tier helpers
select both. The rehearsal also selects its candidate-image producer so it can
consume the exact accepted image. The path sets live beside the existing classifier;
NUL-delimited diffs preserve path boundaries and disable rename collapsing so
removed contract paths still select their tier.

Both tiers run on every push to `main`, manual dispatch and reusable beta call;
there is no nightly schedule. These runs have no PR base and select all areas.
The candidate runner runs the selected populated upgrade on the local candidate
image. The downstream job verifies its portable proof against the source SHA
and image ID. Beta rehearsal additionally seals both accepted image exports to
the review certificate. The source and config receipt travels with the encrypted
images. The [release procedure](releases.md#build-once-test-it-promote-it)
covers private GHCR staging and verification.
Container concurrency includes the caller workflow, event, ref and requested source
so direct main-push/manual runs cannot cancel exact-source beta acceptance.

The required `container` result reports on every PR without workflow path filters.
The locked job conditions, dependencies and outputs remain intact: the existing
`code` output now routes candidate selection, and populated upgrade uses step
conditions. A packaging-only PR therefore starts a lightweight populated-upgrade
job that reports deferral without installing tools or downloading the image.
The aggregate recomputes classification from the same source/base and verifies
agreement with the initial classification. Its job summary distinguishes:

| State | Required result |
|---|---|
| Succeeded | A selected job returned success |
| Deferred | Classification explicitly excluded acceptance; the candidate job was skipped, or the rehearsal reported deferral after a selected build |
| Failed | Classification or any upstream job failed or was cancelled; aggregate fails |
| Missing | A selected job was skipped or has no result; aggregate fails |
| Unexpected | A job result disagrees with the classified execution path; aggregate fails |

Deferral is never inferred from failure or absent classification. Selected jobs
must succeed; deferred jobs must match the expected skipped/lightweight path.
Classification failures fail the gate even if both acceptance jobs were skipped.

`delivery-writer.yml` is not a required merge check. It triggers on
`pull_request` only when files uniquely protected by the writer proof change,
using a positive `paths` list covering the workflow and its acceptance scripts,
`Dockerfile.writer`, `.dockerignore`, Calibre/libarchive/EPUBCheck pins and
installers, the writer/recovery/direct-library backend modules and
writer tests, and Python dependency lockfiles. A nightly `schedule`
run on `main` (`17 3 * * *` UTC) is the regression net for unrelated changes,
and `workflow_dispatch` remains available for manual runs. Changes to shared
backend modules rely on the nightly writer run and the pre-release path, and a
writer-affecting change in a shared module can be proven before merge with
`workflow_dispatch`. A backend-only PR skips Node setup, frontend dependency
installation, frontend tests, build, formatting and audit in source quality.
Existing packaging still produces the complete application.

The source-quality timeout is 30 minutes. The Python suite runs with five pytest-xdist workers configured in `pyproject.toml`. The required source-quality job runs the whole suite in one invocation;
the worker setting lives in pytest configuration because required workflows are
policy-locked. Local runs can pass `-n 0` to run serially.
The native writer acceptance wrapper also passes `-n 0` because its proofs share
fixed ports and process state. Frontend Vitest test and hook timeouts in
`frontend/vite.config.ts` are set to 30 seconds.

## Trust and policy enforcement

Treat every PR checkout as untrusted. Jobs require disposable execution state,
bounded resources, strict network isolation, no production data or credentials,
no host Docker socket and no production deployment authority. Docker operations
use the disposable VM's daemon. Public CI uses synthetic test data.

The required policy status is the GitHub Actions job check `Inspect CI policy`.
The hosted policy workflow reads candidate workflow blobs as data and still
publishes `ci-policy` as a human-readable summary on the candidate commit;
that API-published check is no longer the required context. On PR #140, when
two policy runs inspected one head, the API check attached to the first run's
check suite and Actions-sourced ruleset matching treated it as missing despite
its success. Requiring the job's own check avoids that mismatch; the job fails
whenever the validator refuses, preserving the gate. Other workflows cannot
use either policy check name as a job ID or display name; matching trims
whitespace and ignores case.

The validator requires the literal `ubuntu-24.04` on every job with steps.
It refuses runner expressions, label arrays and group selectors. It also checks
privileged events, token permissions and checkout credential persistence.
Release publication retains its existing narrowly scoped write permissions.
Non-release workflows may use `schedule`; release workflows remain restricted to `workflow_dispatch`.

Required workflows (`quality.yml` and `container.yml`) retain the trusted base's
harness. The validator compares parsed mappings, normalizing scalar/list/mapping
event syntax. At workflow level, only `name`, `concurrency` and `jobs` are free;
all other fields must match (`required_workflow_changed`). The job-key set must
match. Required triggers may add only `push` with exactly `branches: [main]`,
`schedule` or `workflow_dispatch`; existing events and their configuration stay
fixed, including the unfiltered `pull_request` requirement. Within each job, only
`name`, `timeout-minutes`, `env` and `steps` are
free; all other fields, including job `concurrency` and unrecognized fields,
must match (`required_job_changed`). Existing runner, trigger, token and
required-status shadowing checks still apply to these free fields.

Every execution job requires a non-empty list of steps. Step fields and ordering
are free except action references and checkout credential persistence.
Every step action must use a clean local `./` path or an `owner/repository`
reference (optionally with a subdirectory) at a full 40-hex commit pin;
`step_uses_unpinned` refuses other references. A required workflow may introduce
a step action absent from that job's trusted base only with a full commit pin.
Local paths cannot contain parent traversal, `@` or whitespace. Existing local
actions may remain. Checkout matching ignores letter case and requires the
boolean `persist-credentials: false` in a mapping of inputs.

Run-step hollowing is accepted: a required job can replace its test commands
with one `run: true` step. Workflow-diff review owns that risk. Harness checks do
not certify coverage or prevent candidate test code or pytest configuration
from weakening it. Required source/container acceptance and human review still
own coverage. Secret references inside expression blocks or any `if` string
refuse; a plain run comment containing `secrets.X` outside an expression does not.
Malformed mappings and step lists refuse, and unexpected validation exceptions
produce a generic `inspection_failed` failure check without diagnostic details.

A PR changing the validator does not install or execute that candidate validator
in the privileged policy job. Required workflow edits can now pass when their
harness is unchanged, without a ruleset bypass. Root/job harness changes still
refuse. Local candidate-policy validation cannot substitute for the hosted
result or justify a fabricated passing check. See [L080](decisions.md#l080-required-ci-workflows-preserve-the-trusted-harness).

`.github/dependabot.yml` configures weekly Monday updates for the
`github-actions` ecosystem at `/` in a single `github-actions` group with a
seven-day `cooldown`, `open-pull-requests-limit: 2` and commit message prefix
`ci`. Dependabot runs on GitHub's side at no Actions cost; its PRs run the
GitHub-hosted checks.
Bumps that touch the two required workflows (`quality.yml` and `container.yml`)
are refused by the policy until PR #138 merges and pass afterwards because
SHA-pinned action bumps are allowed by the harness rules. Three pinned actions
currently target Node 20, and the first Dependabot PR is expected to move them
to Node 24 releases.

## Public upgrade baseline

The candidate-container job checks runtime startup and recovery using the image built from the PR or main commit. The candidate job also builds the [historical runtime fixture](../tests/fixtures/upgrade-baseline/README.md) from the tested commit and exercises both generations with synthetic data. Changes to the fixture, its manifest or its regression tests select both container tiers.

Exact released-image compatibility is a private release gate. That pipeline pulls the original registry digest, checks the expected image configuration digest and exercises the release with synthetic state.

## Kernel sandbox requirement

EPUB inspection, validation and the retained writer core run untrusted payloads
under Landlock ABI 3 or newer, with no unsandboxed mode. CI therefore requires
Landlock on the runner kernel. `source-quality` sets
`LIBRARIUM_REQUIRE_LANDLOCK=1`, so the root `conftest.py` skip list never applies
in CI; a missing ABI fails those tests. The candidate runner checks the ABI before both stages and fail when it is absent. The skip list remains only for
local development on kernels without Landlock.

## Scope and acceptance

Container tiering changes PR cadence and adds full main-push acceptance. It
reuses the existing classifier and acceptance jobs, with full acceptance on the default branch.
Release and deployment approvals are defined in [the release policy](releases.md). Writer tiering is owned separately;
beta/promotion pipeline trimming remains a separate follow-up.

Verify the job's runner group and image in GitHub Actions, then check the job
result. Queue time is separate from the job execution timeout.

Measure actual runner usage separately from billed overage when reporting costs.
