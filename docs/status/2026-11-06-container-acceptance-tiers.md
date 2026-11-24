# Container acceptance tiers, 2026-11-06

[L081](../decisions.md#l081-container-acceptance-follows-contract-changes) selects
image acceptance on packaging/runtime-contract PRs and populated upgrade on
migration/compatibility/recovery PRs, including the candidate image it consumes.
Ordinary source PRs retain the required aggregate with explicit deferred states.
Main pushes, manual dispatch and beta calls run both tiers; beta image export
is preserved. Source quality has a 30-minute timeout for shared-compute contention.
The additive-trigger policy landed in PR #146.
Hosted exact-head checks and review remain required. The landed writer tiering,
audit and frontend timeout changes are preserved.
Selected container and upgrade tiers retain L078's mandatory kernel checks.
