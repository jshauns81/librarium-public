# CI policy harness comparison, 2026-11-06

[L080](../decisions.md#l080-required-ci-workflows-preserve-the-trusted-harness)
replaces required-workflow equality with a trusted-base harness comparison.
Step implementation and job env edits can pass while root triggers/permissions,
job membership and execution/privilege configuration stay fixed. Action pins,
checkout credentials, runner routes and required-status names remain checked.
`lint-actions.yml` joins the configurable-runner allow-list for its separate PR.
The candidate validator is verified locally against PR #136; hosted acceptance
and review remain required before merging. No workflow file, ruleset or runner
configuration changes are included.
