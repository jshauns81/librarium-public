# Python child sandbox, 2026-10-30

Inspection, eligibility, generation, output reinspection and preservation now
apply grant-free Landlock and shared seccomp denial before reading untrusted
payloads. See the [sandbox contract](../development.md#python-child-sandbox) and
[TDD evidence](../python-child-sandbox.tdd.md). Existing resource/lifecycle limits
and Java filesystem policy remain unchanged. No schema, dependency or image pin
changes are needed.

Local verification: 2,238 warning-strict Python tests plus 11 subtests pass at
90.95% combined coverage, with zero skips. All 46 focused sandbox tests pass,
including real-kernel filesystem/socket/io_uring and TCP denial checks. Mypy
checks 71 source files; lint/format, Django/migration, dependency audit,
workspace/archive integrity, lock/export consistency, docs links and private
tracked-text privacy checks pass. The native corrected-output acceptance helper
also passes against a fresh synthetic artifact store, including deterministic
navigation/heading changes, saved-byte reinspection, pinned EPUBCheck and
independent preservation. This is not actual-image acceptance. Docker is absent;
no local container build ran. Frontend source is unchanged. Hosted image checks,
independent security review and deployment-kernel acceptance remain parent-owned
gates before any separately authorized activation.
