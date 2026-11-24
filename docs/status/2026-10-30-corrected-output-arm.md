# Corrected-output arm, 2026-10-30

[L054](../decisions.md#l054-generate-held-review-copies-and-validate-the-saved-output)
adds explicitly selected held review copies. A reviewer chooses the catalogue
title, the complete author set and/or contents replacement from a saved
preparation. A durable job writes one immutable corrected EPUB into application
storage. A mandatory validation job then rechecks the saved bytes: structural
reinspection, EPUBCheck and an independent preservation comparison. Untouched
members keep identical logical bytes, edited documents keep identical normalized
text, and heading anchors are id-only insertions. Every output stays held for
delivery; generation exposes no download or library write. The separate synthetic
delivery boundary is described below. The initial v1 arm reported typography,
junk pages, OCR text, cover, identifiers and series as not attempted; the stylesheet
extension below advances the selected typography scope.

Generation and preservation children use the inspection process posture plus
parent-death and process-group cleanup. Inspection, eligibility, generation and
preservation now preload their trusted runtime and apply grant-free Landlock plus
shared seccomp denial before reading untrusted payloads. Linux x86-64, libseccomp
and Landlock ABI 3+ are mandatory, with no unsandboxed mode. Newer ABIs use
the ABI-12 masks. Review fixes add signal
scoping at ABI 6+, Python process controls, codec parity and a late-import guard.
See the
[Python sandbox contract](../development.md#python-child-sandbox). Independent review
found no blocking defect; its high finding (author order behind preserved
translators) and medium findings (navigation-only cuts applied to metadata
requests, oversized captures, ratio-exceeding re-encoding) have regressions.

Verification on the integrated branch: 2,183 warning-strict Python tests plus 11
subtests pass at 90.5% combined coverage; 710 frontend tests pass at 91.34% lines
and 85.97% branches. Types, lint/format, Django/schema, production build, workspace
integrity and dependency audits pass. Synthetic HTTP proof with a separate worker
passes on the final source: EPUB3 and EPUB2 navigation, metadata-only, refusal,
EPUBCheck failure, revalidation, replay and recovery without library or catalogue
inputs, and queued cancellation. Seven Chromium journeys and 116 rendered samples
across every theme, desktop, 390/320px and doubled text report no scoped axe,
overflow, unlabelled-control or runtime failures; they found two UI integration
defects that now have regressions. Browser emulation is not physical-device or
screen-reader acceptance. Running-generation cancellation and mid-publication
worker loss have backend tests, not browser proof. Hosted source and container
checks remain required before merge.
