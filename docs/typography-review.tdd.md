# Typography review regression evidence

> **Retired.** The code, tests and scripts this document describes were removed
> by [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them).
> It stays only as the dated evidence record that decisions and status entries link to.

The synthetic journeys were derived from independent review: preparation must
preserve working metadata/navigation options when typography cannot be proved;
selectable CSS edits must generate consistently; child claims must be validated;
and copies must preserve every unselected byte. No real books were used.

| Finding | RED checkpoint | GREEN checkpoint | Executed regression |
| --- | --- | --- | --- |
| H1 / L5 parser failure isolation | a8d8cb7 | 4f7aa69 | CSS numeric/position exceptions, last-resort eligibility and URL refusal |
| M3 / L1 / L3 parser correctness and cost | 425c934 | 188b562 | Escape tails, negative leading, bad preludes and one selector parse per rule |
| H2 / H3 budgets and parent boundary | ce72ad1 | 4a42242 | Budget refusals, parent parser denial and malformed child plans |
| M1 / M2 colour and RTL | 8095b8d | a4a8f5b | Link/modern/escaped/variable/legacy/SVG colour controls, element backgrounds and nested RTL |
| M4 / L6 report and preservation | 86548f2 | 0b6fbfc | Forged summary fields and comparison before output parsing |
| L2 unavailable plan selection | 4464d42 | 7772802 | Missing-plan selection is 422 with reasons |
| M5 / L4 Unicode and truthful copy | a721444 | cd4bdad | Astral samples decode by code points; labels describe CSS changes |
| H2 document traversal | b8f39a6 | 0cd6c3c | Book/document byte, element and document-count edges |
| H2 report rows / L5 descriptions | a926f8c, 0a9781e | 777297a | Member-count refusal and known plain-language reasons |
| M3 sheet growth | dd9f620 | 777297a | An offered 64 KiB source sheet can grow by its exact planned replacements |
| L1 selector punctuation | 538d420 | 2550ae1 | Invalid selector punctuation, including inside functions, is not edited |
| L1 nested preludes | c7caaad | aa21b7e | Errors nested inside selector functions and media preludes cannot be offered |
| H3 sparse-rule validation | 26161db | 9fc62b7 | Empty rules cannot make a valid child plan fail parent validation |

`backend/tests/test_typography_review.py`, `test_typography_plan.py`,
`test_typography_generation.py` and `test_typography_requests.py` own the Python
regressions. `frontend/tests/corrected-output-api.test.ts` and
`corrected-output-typography.test.tsx` own Unicode decoding and copy. The HTTP
proof uses a separate worker, real EPUBCheck, held output validation, refusal,
replay and historical v1 readability/revalidation refusal. The authenticated
private receipt owns operational locators and exact gate logs.

The final combined measurement exercised all 512 edits and 2,000 declarations,
16 source sheets (one at 64 KiB), 128 KiB combined CSS including inline/style
blocks, 256 inline styles, 32 style elements, 64 documents, 4,096 elements,
512 KiB document bytes, 128 archive members and 4 MiB logical bytes. Isolated
eligibility/generation/preservation measured 0.62/1.16/1.40 seconds wall and
0.59/1.08/1.34 seconds CPU. A dense-token variant measured 0.88/1.46/1.63 wall
and 0.85/1.38/1.57 CPU; a sparse-declaration variant filled remaining CSS bytes
with empty rules and measured 1.03/2.08/1.97 wall and 1.00/1.99/1.91 CPU.
The final concurrent run measured 1.34/1.85/2.61 wall and 1.31/1.76/2.17 CPU.
Plan JSON was 94,538 bytes and the generation report
45,869 bytes. This exceeds 2x headroom below the fixed 10 CPU seconds, 15 wall
seconds and 1 MiB report ceilings. It is synthetic local evidence, not a
universal performance guarantee. Separate edge regressions bound oversized plan
JSON, long values, counts and bytes; output parsing allows only the bounded
seven-byte-per-edit growth after exact comparison.

Preservation is independent of generator claims and rederives source evidence;
it shares the CSS detector/parser. Exact expected splices, unchanged-member
comparison and document evidence establish the byte claims. These tests do not
establish a complete selector validator, reader rendering, physical-device
acceptance or real-library coverage. Colour handling intentionally refuses
uncertain cases and element backgrounds outside `html`, `body` and `:root`.


Verification: `pytest -W error --cov=backend/librarium --cov=scripts` ran the full
test paths (2,466 passed). A fresh coverage-append run of all typography modules
and `test_real_launchers_enforce_denials_and_late_import_guard` passed 153 tests;
test database selection was supplied privately. Combined line coverage is 87.68%.
Frontend coverage passes 780 tests at 91.78% lines and 86.38% branches. Mypy,
Ruff check/format, Django check/migration checks, both dependency audits,
Prettier, production build, workspace checks and protected tracked-text privacy
checks pass. The build retains its existing large-chunk advisory. No new browser
rendering or reader-app proof is claimed by this correction task.
