# Upstream source references

Library Finish and BL Catalog remain separately owned source systems. Their live
checkouts and production data are not Librarium's application state.

[sources.json](sources.json) records refreshed **local observations**: repository,
selected ref/commit, checkout HEAD/branch, source-capture manifest and LF's delta
from the earlier anchor. These are local committed-source selections, not current
GitHub guarantees or production versions. No fetch/reset or upstream source
change occurred to create these records.

The implemented `scripts/capture_source.py` captures committed source at an explicit commit;
[reviewed manifests](manifests/) identify exact selected paths and exclusions.
Initial captures at LF `6e460de` and BLC `a8f2744` remain preserved. Later captures
add LF `4c9ed6d` and missing writer/queue/CWA/docs/test contract owners after the
[private engineering record](../docs/agent-environment.md#private-context-discovery).
These source archives are not catalogue data snapshots. JSON/binary/runtime paths
are excluded by the source policy, so these are not complete runnable mirrors.

The 2026-10-25 autonomous continuation also captured LF `a2a3692` as a candidate
baseline: 97 selected committed source files, with a verified archive and
[manifest](manifests/library-finish-a2a3692.json). Its contract review is pending;
the reviewed selected source remains unchanged. Untracked checkout artifacts
were excluded. Neither this capture nor BLC's unchanged local `a8f2744` proves a
development freeze or the deployed service versions. LF's large remote graph
upload still returns HTTP 413; use exact committed source/local navigation and
do not describe its remote graph as current. Librarium's own graph publishes.

Further snapshot work must capture committed source at an explicit resolved commit,
record original repository/ref, archive and per-file integrity, and keep refresh
diffs reviewable. Refuse unsafe archive paths and links; never run captured code
merely by importing it into the experiment. Exclude books, production databases,
credentials, local settings, runtime state, untracked files, and dependency caches.

Place any later authorized downloaded captures under ignored `upstream/snapshots/`.
Commit only reviewed provenance manifests, contract maps, assessment outcomes,
and relevant synthetic fixtures. A scheduled refresh, new GitHub repository,
production access, or writer change requires its own authorization.
