# CI Landlock requirement, 2026-11-06

[L078](../decisions.md#l078-ci-requires-the-kernel-sandbox-it-tests): CI fails
instead of skipping when the runner kernel lacks Landlock. Runner acceptance
requires the full suite green with no sandbox coverage skipped, plus clean
disposal across repeated runs.
