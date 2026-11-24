# Python child sandbox TDD evidence

The journeys derive from the sandbox implementation brief: inspect an owned
synthetic EPUB, generate selected corrections, reinspect/preserve saved output,
and refuse every missing isolation boundary without recording a verdict.
The [development contract](development.md#python-child-sandbox) owns the mechanism;
[L054 item 5](decisions.md#l054-generate-held-review-copies-and-validate-the-saved-output)
owns the decision. This is local source evidence, not deployment acceptance.

## RED and GREEN checkpoints

All focused commands used `uv run pytest -W error backend/tests/test_python_sandbox.py -q`.

| Cycle | RED checkpoint and observed result | GREEN checkpoint and observed result |
|---|---|---|
| Ruleset/filter, kernel denial, startup order and safe refusals | `cf0a12d`: 34 failed, 1 passed; missing sandbox implementation/refusal codes | `df15d69`: 35 passed |
| Platform preflight and durable job refusal coverage | `36241f7`: 1 failed, 37 passed; native preloads ran before unsupported-platform refusal | `b28a3be`: 39 passed; focused process/job target also passed 156 tests |
| Header prefetch and stable launcher platform errors | `9159d24`: 6 failed, 39 passed; missing unbuffered header reader and generic platform errors | `2b27470`: 45 passed |
| Current upstream ABI 12 | `42075d2`: 1 failed, 45 passed; audited ABI refused | `5dd3dbf`: 46 passed; ABI 12 retains the ABI 10/11 filesystem and network masks |

The focused process/job target was `uv run pytest -W error
backend/tests/test_python_sandbox.py backend/tests/test_inspection_process.py
backend/tests/test_corrected_output_jobs.py backend/tests/test_file_inspections.py -q`.
Lifecycle fixtures now pre-open their owned marker descriptors; they never receive
pathname write grants after restriction.

## Guaranteed behavior

| Guarantee | Executable evidence | Type |
|---|---|---|
| Every audited ABI handles all filesystem rights with no grants; TCP/UDP rights follow ABI support | `backend/tests/test_python_sandbox.py` ruleset construction and application errors | Unit |
| Missing platform, Landlock, libseccomp or filter installation refuses safely | Same file, platform/ABI/filter failure cases and exit-code transport | Unit/process |
| Files cannot be read, created or written; IPv4/IPv6/Unix sockets and io_uring setup return permission errors | Same file, real-kernel probe | Kernel |
| Landlock itself denies TCP bind/connect on supported ABIs | Same file, preopened TCP sockets with Landlock alone | Kernel |
| Inspection, eligibility, generation and preservation restrict before reading untrusted payloads | Same file, child startup-order cases | Unit |
| Trusted header transport cannot prefetch archive bytes | Same file, unbuffered header and bounded/complete header cases | Unit |
| Existing synthetic bytes still inspect, generate and preserve | Same file, real isolated round trip; existing correction/native suites | Process |
| All job paths fail without an output or validation verdict when a child refuses | `backend/tests/test_file_inspections.py`, `backend/tests/test_corrected_output_jobs.py` | Database/process |

The real-kernel filesystem/seccomp probe skips locally only for unavailable
Landlock with an explicit reason. CI treats that condition as failure. The
Landlock-only TCP probe explicitly skips kernels lacking ABI 4 network rights;
that does not skip the filesystem/seccomp probe or synthetic round trip.

## Limits

Only ABI 6 is exercised by real syscalls; other ABI layouts checked against
headers have construction tests. Linux codecs are preloaded and registry lookups
cannot trigger speculative imports. Any other late import terminates with
`sandbox_late_import`, even through exception-catching optional dependencies. The rules do not revoke pre-existing descriptors or cover every metadata
operation. Direct domain helper calls are unsandboxed; production job launchers
install the guards. The Java launcher's existing tests protect its unchanged
runtime/scratch Landlock grants, syscall set and captured validation contract;
shared libseccomp setup now refuses unresolved mandatory syscall names.

Actual-image and deployment-kernel acceptance, including replacement/restore,
remain required. Docker is unavailable in this implementation environment, so
no local container build ran. No frontend source changed or frontend checks ran.


## Initial implementation verification

`uv run pytest -W error --cov=librarium --cov=scripts.capture_source --cov-report=term-missing -q`
passes **2,238 tests plus 11 subtests**, with **zero skips**, in 320.08 seconds.
Combined line coverage is **90.95%** (8,480 of 9,324 statements). The focused sandbox
target passes 46 tests. Isolated child environments intentionally remain clean;
coverage instruments parent/unit code, while kernel/process assertions provide
child execution evidence.

Mypy passes across 71 source files. Ruff check and format (170 files), Django
system checks, warning-strict migration check, pip-audit (no known vulnerabilities),
workspace/archive integrity (18 preserved files), lock/export consistency,
documentation links and tracked-text privacy checks pass. The native
`corrected_checks()` acceptance helper also passes using a fresh temporary
synthetic artifact store: deterministic navigation/heading corrections, saved-byte
reinspection, pinned EPUBCheck and independent preservation. No HTTP service,
real library or deployed state is involved. This helper run does not substitute
for an image build or hosted replacement/restore acceptance.


## Independent security review remediation

These journeys add confinement of a compromised Python parser, legacy XML/name
parity, future-kernel compatibility, a dependency-completeness guard and accurate
job diagnostics. No library state, deployment, schema or Java syscall set changes.

| Finding | RED checkpoint and actual result | GREEN checkpoint and actual result |
|---|---|---|
| H1/L1 signals, group escape, new processes, namespaces and exec | `169448c`: 18 failed, 1 passed; scopes and controls absent | `233876d`: 100 Python/Java sandbox/process tests passed |
| M1 legacy codec parity | `58f9700`: 8 failed, 13 passed | `dad13fb`: 21 fixture cases passed, including exact generated bytes |
| Late-import guard and real-launcher file/socket denial | `654b887`: 8 failed, 4 passed | `2dc04c3`: 97 passed; unknown encoding retains its existing input finding |
| M2 future ABI masks | `fe504f7`: 3 failed | `134fec8`: 23 relevant ruleset cases passed |
| L2 generic correction failure codes | `3155a6c`: 3 failed with `inspection_process_failed` | `ef184e9`: 3 passed with `corrected_output_unavailable` |
| L3 parent preflight and forged platform exits | `bf0d7e7`: 9 failed | `28023fb`: 20 targeted cases passed; broader run had 196 passing cases and one superseded assertion, then the corrected assertion passed |
| H1 prctl integer-width bypass | `6229c9f`: 1 failed; high option bits bypassed the rule | `f2511f5`: 10 prctl/preflight cases passed |
| M1 codec alias normalization | `9717e32`: 1 failed; 127 dotted aliases differed | `8624c7d`: 1 passed across 623 known/unknown normalized names |
| Preflight input ordering and lifecycle fixtures | `40d5fd2`: 2 failed; native preflight ran for invalid inputs | `1ca7baf`: 23 input/preflight/lifecycle cases passed |

Commands were warning-strict pytest targets for `test_python_sandbox.py`,
`test_sandbox_codec_parity.py`, `test_sandbox_codec_aliases.py`,
`test_sandbox_preflight.py`, `test_sandbox_prctl.py`,
`test_corrected_output_jobs.py` and `test_file_inspections.py`. Checkpoint commits
preserve the reproducer and fix separately. The late-import guard uses an audit
hook plus a meta-path finder and exits immediately, so caught ImportError or
BaseException cannot silently produce a different verdict.

Lifecycle descendants are created in trusted fixture setup before restriction;
those tests prove cleanup of existing group members, not permission to fork
inside a parser. A focused preflight/input regression also preserves cheap
invalid-input refusal before native probing.

The final corpus target passes **42 cases** in **112.18 seconds**: 21 synthetic
encoding/ZIP-name fixtures with normal threads and with all thread creation
blocked. Each case compares inspection and eligibility, then five metadata/nav
selections, exact generated EPUB bytes, preservation reports and output
reinspection whenever generation succeeds. The copied review harness contained
20 keyed fixtures; an explicit UTF-8-flagged non-ASCII ZIP name completes the
21-case committed corpus. No fixture has a sandbox parity gap. A separate native thread census observed
one thread both before and after trusted preloading. This includes
existing `invalid_xml` results for unsupported encodings, rather than expanding
XML encoding support.

ElementTree/pyexpat's unknown-encoding handler calls Python codecs. All 120
Linux `encodings` modules, including CJK native extensions, preload before
restriction; Windows-only `mbcs` and `oem` are excluded. No gconv module access or
converter preload is needed for this path. Nine fresh-interpreter measurements
with warm filesystem caches gave a median **85 ms** for the prior domain/common
codec preload and **51 ms** incremental cost for all codecs plus the frozen
registry. These are local startup observations, not cold-storage or deployment
latency guarantees.

Parent preflight constructs the Python seccomp policy and performs a read-only
kernel action query; it never installs isolation in the parent. Runtime INFO
evidence includes the observed and effective Landlock ABI. Newer ABIs reuse the
ABI-12 filesystem/network masks and ABI-6 scopes. ABI-12 generic permissions are
not requested. Child setup/import status can still be forged by compromised
native code, but cannot record a verdict. ABI 3–5 has no signal scoping. Cleanup
covers the original process group and threads; no cgroup-wide claim is made.
Pathname metadata may remain visible, and pre-existing descriptors are not revoked.


### Remediation delivery gates

The full warning-strict suite with `--cov=librarium
--cov=scripts.capture_source --cov-report=term-missing` passes **2,329 tests and
11 subtests**, **zero skips**, in **467.73 seconds**. The local invocation used
an external test-only database-naming plugin; it changed no test behavior.
Combined line coverage is **91.07%**
(**8,561/9,400 statements**). The known HTTP-client deadline timing flake did not
occur. As before, clean isolated children are not coverage-instrumented; real
kernel and launcher assertions prove their execution.

Mypy passes across 71 source files. Ruff check and format (175 files), Django
system checks, `migrate --check`, `makemigrations --check --dry-run`, pip-audit
(no known vulnerabilities), workspace/archive integrity (18 preserved files),
lock consistency and protected-denylist tracked-text checks pass. Every
implementation checkpoint snapshot also passed the privacy gate. Graphify AST
update and the Developer-context refresh succeeded. Docker/image and hosted
replacement/restore acceptance were not run; no activation occurred.
