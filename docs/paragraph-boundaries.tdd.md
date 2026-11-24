# Paragraph boundary refinement evidence

> **Retired.** The code, tests and scripts this document describes were removed
> by [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them).
> It stays only as the dated evidence record that decisions and status entries link to.

The L068 block extends L066's opt-in repair using its existing source-bound
planner, lexical writer, independent tree proof, archive and sandbox. LF K2
planned unwrapping without implementing it; BLC has no repair primitive. The
maintained parser/checker already in use supplies XML/CSS/conformance handling.
No reconversion, dictionary or generic text rewriter is introduced.

## Contracts and limits

Nested paragraph plans advance to v2. Each selected boundary records original
left/right paragraph byte offsets, a separator and a closed reason. Only ASCII
letter-hyphen/letter boundaries remove XML boundary whitespace. The literal
hyphen, other characters, nested inline elements/attributes and IDs remain.
Empty page anchors insert no spaces. Numeric character references at these
boundaries, unknown whitespace, discretionary/soft hyphens and dashes stay held.

Short interior numbered-clause fragments require a numbered start, at least two
long fragments, lowercase continuation evidence and a complete final sentence
or semicolon/and-or terminator. Distinct numbered starts remain separate.
Headings, quotations, lists and cross-document boundaries remain excluded.

Unsupported linked CSS and unresolved references hold their own documents;
identical flat duplicate declarations can agree. Conflicts, compound selectors,
inherited/semantic styles, embedded/inline styles and RTL remain held. Counts
identify changed and stylesheet-held documents, rather than promising every
previous refusal is repairable. All source documents remain within the existing
planner's 512-document/4-MiB ceiling and stylesheet budget.

Inspection evidence remains unchanged. For selected v2 edits, independent tree
reconstruction supplies the expected normalized document-text digest/count.
Actual output must equal that evidence; original folded characters, IDs and exact
allowed logical member deltas still pass independently. This is a selected
boundary-whitespace contract, not a general whitespace exemption.

Options, generated summaries, saved reports and UI expose literal-hyphen and
numbered-clause joins separately. Strict shapes reject partial new counts,
booleans, forged separators and inconsistent counters. Saved backend reports
bind counts to the selected capture. Historical v1 plans/two-count summaries
remain readable; a constructed historical capture/report regression verifies
durable reads and refusal of new validation under an old generator runtime. No
allowlist bypass or writer permission change is introduced.

## Failing-first and verification

The three focused new detector tests against the baseline planner fail: literal
hyphen plan/version, closed short numbered continuation and unrelated unsafe CSS.
The frontend initially fails 12 new tests. Tests cover inline emphasis/page IDs,
consecutive hyphen trims, quote/dash/whitespace/heading/list exclusions, conflicts,
forged plans/counters, source-plan drift, durable replay and historical reads.
Shared-writer fault injection must fail independent tree/text preservation.

Commands use the pinned native archive, Java/EPUBCheck configuration and a
separate synthetic database selected through environment variables. The
portable fixture/seed/child-measurement helper used for this block was removed
after [the 2026-11-07 suite review](research/orphaned-acceptance-suites-2026-11-07.md); per-PR backend and mounted tests own these
contracts, and `scripts/measure_typography.py` remains the manual budget tool.
No real book input or library writer is used.

Final checks before rendered acceptance:

- 253 broader backend repair/generation/job/native-checker tests passed.
- 97 frozen-source paragraph, durable API/capture and typography-request checks
  passed; paragraph planner/tree-proof coverage is 95% (94%/99% per module).
- Frontend: 957 tests passed, 89.17% statement / 85.12% branch coverage; the final
  focused API/mounted run passed 190 tests after pin-drift and expected-text wording was corrected.
- Build, Python lint/types (95 modules), formatting, 18 archived-file hashes,
  workspace tests and owned-document link audit passed. Existing build-size and
  progressive-document-adoption warnings remain informational.

The final synthetic 2,390-byte EPUB exercised eight removed paragraph boundaries,
one literal-hyphen join and five numbered-clause joins; one document changed and
one stylesheet-ambiguous document stayed unchanged. Under the unchanged 10-CPU /
15-wall-second / 512-MiB child ceilings, eligibility/generation/preservation used
0.328/0.455/0.372 CPU seconds, 0.360/0.461/0.376 wall seconds and less than 58 MB
sampled peak address space. Capture JSON was 14,322 bytes; eligibility/generation/
preservation reports were 2,504/4,020/443 bytes, within the unchanged 1-MiB ceiling.
These are measured fixture results, not maximum-corpus guarantees.

The browser harness used for the rendered acceptance below was removed after
[the 2026-11-07 suite review](research/orphaned-acceptance-suites-2026-11-07.md); it remains in Git history. Its results are a
historical receipt for this block, not a current check.

## Rendered acceptance and commands

The frozen built app and separate worker passed the real synthetic journey:
keyboard paragraph selection, server-side pin drift, explicit choice reload,
generation, actual EPUBCheck/preservation, saved results, history and reopening
that history after reloading the source. Counts were eight removed boundaries,
one literal-hyphen join, five numbered-clause joins, one changed and one held
document. No browser exceptions, console errors or server errors were recorded.

108 rendered samples covered choices/results/history at 1280, 390 and 320 pixels,
including 320-pixel doubled text and all shipped themes (system light/dark).
Every recorded sample passed horizontal-overflow, Axe, accessible-label and
coarse-pointer 44-pixel target checks. Compact paragraph-row captures were also
visually inspected. A final harness assertion initially looked for saved proof
status under report details; correcting it to the checks envelope and rerunning
the journey passed. The earlier successful render matrix was retained against
the same unchanged built bundle; raw failure evidence remains private.

Representative commands (configure the pinned native/checker environment and a
separate synthetic database first):

```sh
# RED against the baseline planner; GREEN against v2.
uv run pytest backend/tests/test_paragraph_repair.py -q \
  -k 'v2_literal or closed_numbered or css_holds'
uv run pytest -W error backend/tests/test_paragraph_repair.py \
  backend/tests/test_paragraph_requests.py backend/tests/test_corrected_output_api.py \
  backend/tests/test_corrected_capture_review.py backend/tests/test_typography_requests.py \
  --cov=librarium.paragraph_repair --cov=librarium.paragraph_preservation -q
npm --prefix frontend run coverage
npm --prefix frontend run test -- tests/corrected-output-api.test.ts \
  tests/corrected-output-typography.test.tsx
npm --prefix frontend run build
```

Privacy gates
cover staged portable content with the external denylist. The redacted complete
payload secret scan has three unchanged official EPUBCheck checksum-pin matches,
verified against the baseline; outgoing changes are scanned separately before push.

## Unproven limits

Synthetic Chromium emulation does not establish physical Kindle rendering,
screen-reader audio, real-library repair coverage or production readiness.
Screen breaks, document splitting, new CSS, accounts and identity providers are
outside this block. Originals, delivery/recovery contracts, resource ceilings and
the installed application remain unchanged.
