# Runtime startup and fresh-cluster recovery

The workspace now orders migration, create-only login setup, the existing grant
provisioner and an effective-runtime verification gate before web/worker admission.
Configuration mounts keep these checks separate from immutable app-image provenance.
The required image gate executes the actual entry, admission failures and a
post-migration restore into a fresh cluster, including an exact released-image
compatibility case. [Rollout](../runtime-rollout.md) preserves stopped-role capture,
pre-cutover acceptance and separate rollback state. Local PostgreSQL proof passes;
actual-image CI and actual target kernel/storage acceptance remain required.
