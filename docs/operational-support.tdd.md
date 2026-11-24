# Operator support and recovery verification

This source increment addresses the routine implementation portion of issue #28.
It does not certify a production target or close the issue's remaining gates.
[The contract](operational-support.md) owns reporting/approval semantics.

## Failing-first evidence

New report tests first failed because the projection did not exist. Identity tests
first failed for the absent implementation, then independently caught a missing
runtime-compatibility field and a generated record that was not safely readable.
Receipt tests first failed for the absent validator. These failures and subsequent
check receipts are retained in protected operator evidence, outside Git.

Regressions cover database connection errors, independent schema-read failure,
migration drift and the 256-row migration bound; unavailable/missing storage,
no-follow capacity reads and raw-error suppression; a 200-row job sample with
truncation, unknown state, queued age, retries and lease/liveness uncertainty;
missing/untrusted/malformed build records and declared versus observed image;
and malformed/unsupported/oversized/unsafe/future/stale/incompatible rehearsal
records. Private canaries in fields, paths and exceptions cannot reach output.
A real attempted write through the diagnostic connection is rejected by PostgreSQL.

## Local source checks

The integrated affected run passed 309 warning-strict tests: the new report,
build and receipt suites, release/promotion compatibility, deployment, durable
journey/job history, delivery recovery and EPUB acceptance regressions. Aggregate
coverage for the three new projection modules was 96% (report 100%, identity 95%,
receipt 94%). The subprocess restore has separate actual execution below and is
not counted as parent-process coverage.

Configured mypy passed 102 source files. Applicable Ruff, backend formatting,
Django checks, migration dry-run, frozen lock/export comparison and workspace
integrity passed. The export comparison ignores only uv's invocation header.
The public-content/workspace regression run passed 22 tests. Actionlint passed
the changed container workflow with shellcheck disabled. No frontend source changed;
existing assets were not replaced and no new rendered/UI acceptance is claimed.

## Actual isolated restore

The final integrated run used the explicit `LIBRARIUM_POSTGRES_BIN` test setting
with the existing synthetic PostgreSQL toolchain. It preserved a generated source,
ran real inspection/validation/correction, dumped PostgreSQL, created a uniquely
named disposable restore database and restored the dump/artifact archive. The
existing restore helper reopened source bytes, inspection/report bindings, checker
validation and corrected-copy/preservation evidence, then ran the actual support
command against restored state. Its separately measured recovery interval was
9.485231 seconds; capture age at recovery start was 0.106042 seconds. This is one
small prepared local fixture, not an RTO/RPO estimate for a target library.

This checkout was unbuilt: its receipt correctly retained null build bindings and
the report returned incomplete recovery evidence. It never claimed known packaged
identity or a verified running image. The helper's separate final local run also
passed, measuring 10.051756 seconds with a 0.104821-second capture age; the two
measurements describe separate actual runs, not a benchmark distribution.

The optional source-level PostgreSQL roundtrip requires an explicitly configured
client directory and skips when absent; it never discovers or contacts a target.
The hosted container restore remains mandatory and now requires packaged identity,
compares build/policy/source bindings and checks actual report states. The separate
coordinated delivery harness retains its original historical key, original-byte,
fresh writer epoch and no-duplicate/no-resend assertions, with a distinct recovery
timer/receipt. That full harness was extended but not rerun locally in this block.

All disposable restore databases were removed by their own test cleanup. No
long-lived fixture process, production service or installed application was started.
Docker was unavailable locally, so exact-image packaging/container and coordinated
delivery acceptance remain hosted parent gates. Review, final head and hosted
results belong to the PR and private handoff rather than this static test record.

## Independent review corrections

Independent source review found an active-job sampling gap and four smaller
correctness/documentation issues. Five failing regression cases reproduced hidden
active work, connection-time false future counts, two inconsistent duration values
and permissive schema acceptance. The corrected query excludes finished history,
uses the database snapshot clock, requires compatible restored schema, rejects
duration/timestamp disagreement beyond two seconds and documents container cwd
and receipt ownership/permissions. The final 309-test run includes these fixes;
parent exact-head hosted review and image gates remain separate.

## Remaining acceptance

Before production claims: independently observed exact running image, hosted image
checks, target-scale restore/capture currency, capacity/ownership approval,
physical durability and separately authorized activation remain required. No
recurring schedule, retention cleanup, real-library operation, writer admission,
account change or installed update is authorized by these synthetic results.
