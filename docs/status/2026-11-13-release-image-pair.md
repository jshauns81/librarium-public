# Paired release images and install assets

The beta publisher now exports the tested source-browser image with the tested
application image. A config-digest receipt binds both exports to the same source
commit. Publication checks both loaded image IDs and both registry manifests,
then records each immutable image/config identity in `librarium.release.v2`.
A deterministic `stack-assets.zip` carries registry Compose files, overlays and
browser seccomp/provenance/license files, with archive and per-file checksums.
The beta draft becomes visible only after both images and uploaded assets verify.

Stable promotion requires both explicit registry digests and owner acceptance
schema v2 binding that pair. It revalidates source-derived compatibility and the
exact stack archive, copies both existing image manifests without rebuilding, and
checks both before creating Git/Release identities. A missing image or partial
registry write reserves the version and refuses automatic retry. Historical v1
single-image releases do not acquire an inferred browser image.

Reuse: extends the existing release, registry, promotion and container acceptance
owners. The browser build and BLC/LF reuse provenance remain those reviewed in the
source-browser change. Existing changeover/reuse records concern product features;
this work adds no provider or deployment system. ZIP generation uses Python's
standard library; no dependency is added.

Local verification: 547 warning-strict tests passed across release, registry,
promotion, workflow contracts, CI policy/classification, registry configuration,
privacy and build identity. Measured release-tool coverage is 86% (promotion 94%,
registry 91%; subprocess CLI checks do not contribute to parent-process coverage).
The configured type check passed 126 source files. Python lint, Python 3.12
compilation, actual host-runtime receipt/archive checks, actionlint with shellcheck
and pyflakes, online zizmor, trusted-main CI policy, workspace/status integrity
and protected-denylist privacy checks passed. Red-before-green evidence and
operational continuation remain private. GitHub owns exact-head image acceptance.

No image publication, Git tag, release, registry push, installation, activation,
library mutation or merge was performed. The installed application has nothing
new to test. Follow up with exact-head CI/review, the source-browser dependency's
merge and rebase onto main, then a separately authorized normal release run and
installation checks for both pinned images and the matching stack assets.
