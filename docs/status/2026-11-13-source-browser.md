# Shared source browser for cover choices

PR3b-1 implements a default-off source-browser role for Goodreads and live
Lexicanum cover choices. It uses headed Chrome under Xvfb with native namespace
and Seccomp-BPF sandboxes, a narrowly extended pinned seccomp policy, an owned
profile volume, authenticated internal control and public-address pinned HTTPS.
The browser receives no library, database, writer or application credentials.

The worker reuses the retained Goodreads parsers and lookup/cache behavior,
replacing SQLite with a bounded six-hour PostgreSQL page cache. Current Lexicanum
reads use GET current-revision export XML and original same-wiki covers; archived
copies remain a labelled fallback. Source & method records the reach method.
The existing image child, identity binding, cancellation fence and append-only
PreparedCover path admit every candidate.

Reuse is recorded in `services/source-browser/provenance.json`. The purpose list
preserves search, original artwork, current wiki retrieval and archive fallback.
No public upstream facade, intake, Update action, extension, upscaler or prebake
worker is introduced.

Verification covers protocol authentication and URL policy, private DNS refusal,
cache expiry/retention/refresh, parser layouts, placeholder refusal, current XML,
archive fallback, image-child admission and mounted picker status/retry behavior.
The disposable container proof validates the original resolved model before
fixture rewrites, then checks network separation, credential/mount absence,
control listener isolation and Chrome's reported native sandboxes. Tests use
synthetic fixtures; they do not establish current provider availability or
production reliability. Server-side CI and independent review remain merge gates.

Local results: the complete warning-strict Python suite passed 4,084 tests and
187 subtests with 14 skips. An additional populated cache
migration reverse/reapply check preserves existing search and prepared selection
records; the final focused run passed 320 tests with one optional skip. All
1,270 frontend tests, application types, production build, lint, schema drift,
workflow policy/action lint and the protected privacy gate passed. Four native
Chromium fixture renders cover both themes, 320px and desktop widths and doubled
text, with zero axe violations and no horizontal overflow. The enlarged-text
render exposed comparison-label overlap; stacking the phone comparison fixes it.
Five browser-driver tests cover current XML, canonical fallback, challenge refusal
and URL rules. Five focused control tests cover authentication, DNS, the bounded
queue and exclusive profile ownership. A hostile-markup regression proves that
HTML/XML parsing cannot hold the worker beyond its fresh child's resource limits.

Nothing was activated or deployed. The installed application has nothing new to
test. Intake/Update and any production activation remain separate work.

Review round 1 fixes response classification (ordinary errors are not challenges),
CONNECT cleanup on every tunnel exit, known Goodreads book navigation parameters
and honest null results for unrecognised thumbnail paths. The image build and
installed-stack acceptance compile all copied modules on the pinned Python 3.12.
Acceptance stages the exact host-side seccomp file outside the checkout, proves
missing-profile refusal and checks both native Chrome sandboxes without changing
the profile path. A real-browser offline fixture skips the Lexicanum portal's
Book2.jpg placeholder before selecting the publication cover.

A bounded nine-GET live smoke retrieved Goodreads ISBN/title HTML and decoded
Goodreads and Lexicanum originals. The live responses exposed the current
Goodreads CDN and Lexicanum placeholder selection; both now have regressions.
The article/export loaded successfully, but the role rejected the placeholder
before that fix. The corrected selector passes an offline replay of the captured
page and XML; the two-request live chain was not repeated within the GET cap.
Evidence and timings remain private. No challenge was observed with scripts off.

Image publication is explicitly deferred to **Release source-browser image and
stack assets with multi-image promotion**, before installation. It must preserve
the accepted browser bytes, verify both registry digests, include them in the
manifest, preserve both through stable promotion and provide checksummed stack
assets. Current release/promotion tooling validates one application image.

Round 1 verification: the complete warning-strict Python suite passed 4,088 tests
and 187 subtests with 14 retained skips (89% coverage); all 25 browser-driver
cases passed inside the built image. Types, lint, schema drift, host Python 3.12
compilation, workspace integrity and the protected privacy gate passed.
No UI files changed in this round.
