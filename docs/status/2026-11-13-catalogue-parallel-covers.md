# Catalogue-first cover choices and parallel web searches

The picker now checks the pinned local catalogue and displays its choices before
web search. A bounded title/author similarity search also considers recorded title
aliases and containment relationships. Suggestions show their title and similarity,
require an explicit choice, and never become an automatic catalogue link or default
selection. Recorded anthology covers stay visibly distinct and blocked for a
standalone book. Conflicting identifiers, ambiguous identity, placeholders and
changed provenance retain their existing refusal rules. A saved exact choice
cannot silently become a suggestion after a catalogue change. Catalogue absence
remains visible when web covers exist; failed checks do not establish absence.

Every requested source starts in one leased attempt. Each result is admitted and
checkpointed independently, while other sources continue. CoverSearch records
source start/finish timestamps and elapsed milliseconds in a reversible JSON-field
migration; old searches retain unknown timings. Resume retries unfinished sources
only, and cancellation or a replaced lease fences late results. The source role
admits the bounded concurrent requests while preserving its source locks, host
pacing, resource limits and network boundaries. Explicit wiki lanes no longer wait
for another provider's score.

Live Lexicanum tries the exact article first. A missing article triggers a bounded,
main-namespace Special:Search GET for title and author on the same wiki. Up to two
matching article links continue through current-page export and original artwork
admission. Search/query/redirect rules refuse other hosts, action parameters and
non-article namespaces. Unknown layouts and source failures remain distinguishable
from a valid empty search. No challenge solving or new egress host is introduced.

Reuse review covered BLC's published snapshot, alias/containment schema and verified
artwork; LF's retained similarity, image admission and changeover boundaries; and
the existing worker lease, append-only selection and source-browser export paths.
These existing capabilities supply the feature without a new service or dependency.
The worker coordinates them with bounded standard-library threads; the fresh parser
uses the standard-library HTML parser.

Verification is recorded with the pull request: behavior regressions were observed
before implementation, then catalogue/picker/worker/browser suites, types, lint,
production build, synthetic theme/viewport renders, disposable source-role and
packaged-worker acceptance, schema checks and the protected privacy gate run.
The deployed beta, operator configuration and library remain unchanged. No merge,
release, import, catalogue publication or library-write approval is included.

Local results: 119 related catalogue/picker/worker/browser tests and 318
provider/security/configuration tests pass. All 1,273 frontend tests pass; the final
picker pass contains 21 cases. Type checking covers 126 Python modules; lint,
schema-drift, production build, workspace, documentation links and protected
tracked/staged privacy checks pass. The existing bundle-size warning remains.
Six synthetic Firefox renders cover 1440, 390 and 320 pixels in both themes with
no overflow or runtime errors and catalogue suggestions before web search.

Fresh application and browser images pass disposable network/credential/control
acceptance, including both native Chrome sandboxes. A network-disabled packaged
worker proof passes migrations, seven concurrent starts, durable early results,
timings and recovery without repeating completed sources. These are synthetic
checks; no live multi-provider performance or installed-beta behavior is claimed.

Review round 1 corrects six edge cases. A labelled, manually selected suggestion
replaces blocked exact-title artwork when an author spelling is sufficiently close.
Any shared author can support a multi-author suggestion. Broad title searches rank
and cap comparisons at sixteen works rather than rejecting the choices API, so
web results remain available. Wiki fallback filters publication markers in titles,
article paths and search snippets before spending either of its two export slots.
Browser commands share a worker queue with a ninety-second admission bound; the
image transport and its twenty-second watchdog start only after admission. API
source tasks retain their parallel execution. The populated upgrade rehearsal now
requires leaf 0017 and verifies both the timings column and browser-cache table,
alongside the existing least-privilege runtime grant check.

New regressions reproduce the failures before the fixes, including author-typo
selection persistence, twenty-one related catalogue works, a slow wiki holding up
an image, queue timeout/release, publication filtering before export, and missing
schema columns/tables. The focused run passes 65 tests with one prerequisite skip;
types, lint, migration drift, workspace integrity and the protected content gate
also pass. Full-suite and packaged acceptance results are reported on the PR.
The full-suite run also exposed the release manifest test's stale 0016 leaf
expectation; it now verifies the derived 0017 leaf. The populated image-mode
upgrade and both-generation recovery pass with complete owned-resource cleanup.
