# Typography scale evidence, 2026-10-31

> **Retired.** The code, tests and scripts this document describes were removed
> by [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them).
> It stays only as the dated evidence record that decisions and status entries link to.

L057 expands stylesheet correction admission using invented EPUBs only. There is
no real-library survey, rendering pilot, deployment or installed-service change.
All existing child limits and unrelated correction policies remain fixed.

## Execution and resource ownership

| Phase | Entry point and work | Limits |
|---|---|---|
| Source/output inspection | `inspection_process.inspect_isolated`; native ZIP/XML/text inspection | 10 CPU s, 15 wall s, 512 MiB address space, 32 MiB archive, 1 MiB report |
| Preparation/eligibility | `correction_process.eligibility_isolated`; `corrected_epub.eligibility` calls `typography_plan` | Same CPU/wall/memory/archive/report limits |
| Generation | `correction_process.generate_isolated`; source-bound plan rederivation, span replacement and `verify_stylesheets` | Same; 1 MiB each for capture and source report, 32 MiB output |
| Independent preservation | `correction_process.preserve_isolated`; source plan rederivation, expected CSS splices, unchanged members, output reinspection and ordered text evidence | Same |

`correction_sandbox.restrict` installs CPU/address-space/core/file/descriptor and
lifecycle limits. `python_sandbox.restrict` preloads trusted dependencies, then
installs grant-free Landlock and seccomp before reading untrusted bytes. Parent
`_typography_shape` and `_typography_generation_shape` validate bounded evidence
without CSS parsing; generated stylesheet digests come from bounded ZIP reads.
Typography uses 1,024 edits, distinct from the unchanged 2,048 navigation entries.

## Reproduction and measurement

With the documented pinned native runtime configured, run:

```sh
uv run python scripts/measure_typography.py \
  --runs 5 --output .local/verification/typography-budgets/measurements.json
```

The generator varies document/member/image counts, logical/document/CSS bytes,
elements, per-document sheets, declarations, edits, inline styles and embedded
styles. It uses fixed timestamps and seeded opaque image payloads; these exercise
archive transport and preservation, not image decoding or reader rendering.
Generated books and raw evidence remain ignored. The runner accepts no book path.

Every run launches the production sandboxed source-inspection, eligibility,
generation, output-inspection and preservation paths. `wait4` records CPU and
peak RSS on reaping the actual parser child; preflight helper processes are
excluded. Peak RSS can include the fork's inherited pre-exec high-water mark,
so this is a conservative RSS figure, not measured virtual address space.
Wall time includes parent transport and validation. Report byte counts use ASCII-escaped wire JSON. Plan sizes use default-spaced
ASCII-escaped JSON, matching the planner and parent policy check.
A parent sampler also records `/proc` VmPeak every 5 ms after the parser exec;
this high-water field retains earlier allocation peaks until exit. Sampled virtual
address space is compared separately with the unchanged 512 MiB limit. Brief
allocations in the final sampling interval could be missed.

## Regression evidence

- RED `48e1c5e`: the 12-sheet cyclic graph resolves each import 13 times. GREEN
  `22b9290`: each import resolves once; all four documents still reach every sheet.
  The operation-count assertion avoids a timing-dependent regression.
- RED `9184d5b`: 400-document/400-sheet omnibus admission fails under old bounds.
  GREEN `4d70950`: omnibus admission and parent plan validation pass; bounds match
  the new policy. `f04bc84` simplifies synchronous measurement calls.
- RED `a40f402` / GREEN `717e5d2`: 2,001 empty-rule selector/declaration
  parses become one, while declaration rule indexes retain their source positions.
- RED `da873dd` / GREEN `741b376`: 100,023 per-character encodings become at most one
  on plain ASCII input; offsets use a constant-space range. RED `a1efd16` /
  GREEN `bc68bb4` keeps ASCII-with-BOM on the explicit mapping path. Unicode,
  CRLF and form-feed preprocessing retain the existing general mapping.
- RED `f912777` / GREEN `ce5aacf`: story-text normalization hashes a complete
  normalized fragment once instead of once per word/space (4,095 updates become
  one in the probe). Unicode whitespace, fragment boundaries, digests and
  character counts remain equivalent. The inspection policy is unchanged.
- At-ceiling and one-over cases cover every raised count/byte budget, with an
  exact 256 KiB JSON boundary. Exceeding a bound disables typography while
  container/metadata and navigation gates retain their prior results.
- Parent checks accept the larger plans and reject excess entries, serialized
  bytes and unchanged counters. Existing span, digest, sample, replay and mutation
  tests remain active. Source sheets at their new ceiling may grow only by exact
  planned replacements; independently checked output retains original documents.

Initial combined candidates exceeded the 5 s CPU target: 8 MiB documents /
65,536 elements reached 5.677 s; 4 MiB / 32,768 elements with 512 KiB CSS reached
5.026 s. A 256 KiB sparse-rule variant also exceeded the margin. Final ceilings
use 192 KiB CSS, 6,000 declarations and 1,024 inline styles, with distinct sheets
in the main measurements. Logical book bytes stop at 15 MiB so stored fixture ZIP
overhead remains below half the 32 MiB pipe. Larger 30 MiB books remain unproven.

## Admission ceilings

| Budget | Previous | Refined |
|---|---:|---:|
| Stylesheets | 16 | 512 |
| Bytes per sheet | 64 KiB | 128 KiB |
| Combined CSS | 128 KiB | 192 KiB |
| Declarations | 2,000 | 6,000 |
| Eligible edits | 512 | 1,024 |
| Inline styles | 256 | 1,024 |
| Style elements | 32 | 512 |
| Documents | 64 | 512 |
| Combined document bytes | 512 KiB | 4 MiB |
| Document elements | 4,096 | 32,768 |
| Logical book bytes | 4 MiB | 15 MiB |
| Book members | 128 | 1,280 |
| Plan JSON | 128 KiB | 256 KiB |

The maximum-width empty-rule case reached 5.426 CPU s before redundant parser
work was removed; an empty-rule-only optimization still reached 5.332 CPU s.
Plain ASCII mapping and exact-byte parse reuse address the remaining measured
hot loops. Every repeated sheet/inline style still consumes its full declaration
budget. Preservation checks each member delta before sharing a completeness scan.
RED `ec93374` / GREEN `cef8660` covers both source census and output checks.
RED `0bfd4db` / GREEN `c108c33` additionally rejects parsed source sheets and
combined census bytes beyond the parent byte bounds; legitimate over-budget
unavailable plans retain their existing transport behavior.
No CPU, wall, memory, report, archive or unrelated navigation limit was raised.

## Measured results

Development host: 16 logical CPUs, pinned Python 3.14.9. Nine tiers each run at least five
times through all five phases: 275 real child measurements, including five extra
boundary and wide-sheet rechecks. Main tier sheets have distinct selectors/bytes.
Duplicate-sheet reuse has separate regressions.

| Tier | Documents | Members | Sheets | Book MiB | Document MiB | CSS KiB | Declarations | Edits | Inline / embedded |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| novel | 49 | 92 | 8 | 1.00 | 0.25 | 8 | 144 | 32 | 16 / 4 |
| split | 193 | 516 | 192 | 8.00 | 2.00 | 128 | 1,856 | 768 | 256 / 128 |
| omnibus | 401 | 1004 | 400 | 15.00 | 4.00 | 160 | 5,024 | 1,024 | 1024 / 400 |
| boundary | 512 | 1280 | 512 | 15.00 | 4.00 | 184 | 6,000 | 1,024 | 1024 / 512 |
| imports | 401 | 1004 | 400 | 15.00 | 4.00 | 160 | 4,016 | 1,024 | 16 / 4 |
| dense | 193 | 332 | 8 | 15.00 | 4.00 | 184 | 5,624 | 1,024 | 16 / 4 |
| wide_sheet | 193 | 326 | 2 | 15.00 | 4.00 | 192 | 5,600 | 1,024 | 0 / 0 |
| rules | 193 | 332 | 8 | 15.00 | 4.00 | 184 | 5,616 | 1,024 | 16 / 4 |
| single_document | 2 | 70 | 1 | 15.00 | 4.00 | 128 | 6,000 | 1,024 | 1024 / 512 |

CSS KiB above counts external sheets; the shared ceiling additionally counts
wrapped inline styles and embedded styles. Document counts include navigation.
The wide-sheet tier uses one 128 KiB and one 64 KiB sheet. Document byte padding is actual invented prose inside paragraph text. Opaque image
members supply logical bytes without expansion-ratio shortcuts.

Median seconds are **CPU / wall**, from five launches per tier, or ten for boundary/wide-sheet rechecks.

| Tier | Source inspection | Eligibility | Generation | Output inspection | Preservation |
|---|---:|---:|---:|---:|---:|
| novel | 0.356 / 0.365 | 0.354 / 0.368 | 0.477 / 0.500 | 0.332 / 0.340 | 0.572 / 0.589 |
| split | 0.746 / 0.764 | 0.684 / 0.759 | 1.707 / 1.868 | 0.723 / 0.738 | 1.839 / 1.936 |
| omnibus | 1.459 / 1.491 | 1.245 / 1.342 | 3.042 / 3.346 | 1.520 / 1.545 | 3.822 / 4.019 |
| boundary | 1.531 / 1.560 | 1.384 / 1.489 | 2.832 / 3.258 | 1.451 / 1.480 | 3.705 / 3.882 |
| imports | 1.403 / 1.428 | 1.246 / 1.334 | 3.076 / 3.476 | 1.401 / 1.422 | 3.810 / 4.007 |
| dense | 1.270 / 1.297 | 1.434 / 1.527 | 3.311 / 3.537 | 1.343 / 1.367 | 4.188 / 4.359 |
| wide_sheet | 1.345 / 1.372 | 1.480 / 1.580 | 3.684 / 3.899 | 1.166 / 1.189 | 4.096 / 4.293 |
| rules | 1.372 / 1.398 | 1.584 / 1.682 | 3.526 / 3.808 | 1.293 / 1.315 | 4.393 / 4.559 |
| single_document | 1.240 / 1.271 | 0.979 / 1.089 | 3.036 / 3.271 | 1.360 / 1.381 | 3.147 / 3.358 |

Observed maxima across all tiers/runs, compared with unchanged child limits.
The acceptance threshold is 50% of each limit.

| Resource | Worst observed | Child limit | Used | Headroom |
|---|---:|---:|---:|---:|
| CPU seconds | 4.937 s | 10 s | 49.37% | 2.03× |
| Wall seconds | 5.117 s | 15 s | 34.11% | 2.93× |
| Peak RSS | 157.031 MiB | 512 MiB | 30.67% | 3.26× |
| Sampled VmPeak | 179.473 MiB | 512 MiB | 35.05% | 2.85× |
| Wire report JSON | 452.472 KiB | 1024 KiB | 44.19% | 2.26× |
| Archive transport | 15.128 MiB | 32 MiB | 47.27% | 2.12× |
| Policy plan JSON | 251.378 KiB | 1024 KiB | 24.55% | 4.07× |

CPU is the binding measured resource. Plan JSON also remains
inside its separate 256 KiB typography ceiling. Each admission ceiling shares
this resource envelope; at/over tests separately exercise exact scalar boundaries.
The split/omnibus timings show no measured superlinear step. Import resolution,
empty rules, ASCII mapping, duplicate parsing and story normalization have
operation-count regressions.

These are bounded synthetic measurements on one host, not a universal performance
guarantee for arbitrary CSS, path lengths, combined navigation captures or slower
deployment hardware. Runtime limits still refuse work outside their resource
envelope. Reader rendering, 30 MiB books and a real-library survey remain unproven.

## Verification and execution scope

The complete collection passes 2,781 warning-strict tests plus 11 subtests,
with zero skips. Coverage of the application and capture tool is 90.39%
(10,507/11,624 lines). Four disjoint groups use separate databases and
network namespaces; the packaged-producer test runs separately as a non-root
user. Coverage is combined only after collection/completeness and zero-skip
checks. The pinned Calibre runtime is enabled, including the native HTTP
coordinated restore, conditional writer and SIGKILL cases.

Mypy passes 83 source files; Ruff check/format, Django check, migration checks,
pip-audit, workspace/archive checks, docs links, the protected public-content
gate and outgoing-commit secrets scan pass. Frontend code is unchanged; its
production build supplies assets required by warning-strict WSGI tests. The
separate-worker typography HTTP proof passes preparation, selection, generation,
real EPUBCheck/structural/preservation checks, refusals, replay and historical
v1 handling. No user testing is needed for this local implementation handoff.

The delivery proof keeps its original reserved `librarium_delivery` database
namespace; a temporary typography namespace added during this work was removed
before publication because the delivery proof is not part of this change. A
previous startup race in the parser-cancellation test is recorded by a failing
full run and fixed in `813e2ca`: cancellation waits for the stub PID before
asserting prompt cleanup and process reaping. No production deadline is changed.
Raw exploratory failures and final execution receipts remain private; only the
portable engineering results are recorded here.
