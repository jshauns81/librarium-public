# Workflow linting gate, 2026-11-06

`.github/workflows/lint-actions.yml` adds the hosted data-only `lint-actions`
check on literal `ubuntu-24.04` for pull requests and pushes to `main`. It runs
checksum-verified `actionlint` 1.7.12 with `shellcheck` and hash-pinned
`pyflakes`, plus `zizmor` 1.32.0 via SHA-pinned `zizmorcore/zizmor-action` with
the `regular` persona, `min-severity: low`, `advanced-security: false` and
online audits enabled. `ci-policy.yml` carries an inline suppression for its
trusted-base `pull_request_target` design, `beta.yml` suppresses
`self-repository` where `ci_policy.py` and `actionlint` 1.7.12 require `./`
reusable workflow paths, and `actionlint` filters `SC2129` style notices until
`quality.yml` is unlocked for edits. Local commands are documented in
[the CI contract](../ci.md#workflow-linting).
