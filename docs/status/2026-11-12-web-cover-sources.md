# Web cover sources in the cover picker

The existing comparison modal adds explicit web search, query-only title/author/ISBN
refinement, source selection and pasted HTTPS image addresses. Stored catalogue
art remains first; existing Enhanced derivatives remain available without a web
request. Results append without changing the current choice. Source progress is
announced politely and distinguishes empty, unavailable, rate limited, timed out,
failed and cancelled work. A strong regular match makes the archived wiki search
unnecessary rather than claiming an empty wiki search. No PR3b controls appear.

Apple Books, Google Books, Open Library, optional-token Hardcover and archived
Lexicanum parsing through Wayback, identity/ranking, omnibus and look-alike rules
are ported from Library Finish at the commit recorded in
`backend/librarium/cover_sources_provenance.json`. Its safe-fetch policy is the
starting point for the new checked-address TLS connection. The retained catalogue
reader, LF preparation/restart tests and source-changeover plans were checked;
Librarium reuses its existing native matching, artifact custody, raster sandbox
and append-only PreparedCover selection. No source facade or new dependency is
introduced.

New code supplies the network role, closed internal request vocabulary, durable
PostgreSQL provider checkpoints, lease/cancellation fencing, independent result
admission, metadata-stripped derivatives and picker integration. Search evidence
binds the book identity, current cover and query. Omnibus mismatches are displayed
and refused by the server. Untrusted images remain outside the web process and
are decoded with byte, pixel, CPU, memory and wall-time limits. DNS checks include
every answer; TLS uses the checked address and original hostname, redirects are
checked again and credentials never follow a redirect.

Migration 0015 adds search storage without rewriting existing rows. Runtime
provisioning must run again after migration to admit the new mutable job table;
PreparedCover and its append-only guards remain unchanged. The optional compose
overlay preserves web ingress on an internal edge network and gives only the
source role a public route. Worker/source requests require a protected shared
secret, and the listener binds only to the internal control address. The source role has no library/artifact/catalogue
mount, database login, approval key or writer interface. Packaging documents
explicit activation and internal ingress requirements. Default installations
remain off; this PR does not activate the installed beta.

Verification uses synthetic provider fixtures and PostgreSQL request, worker,
restart, cancellation, image, kind-mismatch and selection journeys. An executed
compose proof validates the unmodified resolved configuration, then uses local
listeners to check source-only egress, preserved internal edge ingress, absent
source mounts/application-network access, authenticated control-only listening
and missing-token unavailable behavior. Rendered desktop/phone samples
in both rooms include 320px reflow, 200% text, keyboard/preview return, retained
selection and axe. Review round one adds provider-specific image-host restrictions at worker and role,
including redirects, explicit special-purpose network exclusions, clean refusal
of non-ASCII URLs, socket/total deadlines, source-only token inheritance and
restricted second decode. ICC profiles convert to sRGB before metadata removal;
a 24-megapixel fixture verifies the revised raster budget. Search RPC timeout was
already 95 seconds, so the reported 20-second search limit was not reproduced.
The cache lock now protects cache access only; different provider children run
concurrently while preserving independent pacing state.

Search starts immediately with recorded title/author/ISBN and all five sources.
Collapsed refinement contains the fields, sources and Search again. Every requested
source reports its state, failed sources offer individual retries with recovery
copy, and the running heading remains until all sources settle. Late results and
retries retain the selected artwork.

Per-actor active/daily quotas and seven-day retention bound disposable search
artifacts in a separate web namespace. Raw downloads are hashed without storing
another original. Retention preserves every PreparedCover reference and all other
artifact namespaces; selection verifies bytes under the retention lock. Pasted
URLs require an empty provider list and provider ISBN values are typed.

Failing-first regressions cover the confirmed behavior changes, including a
selection/retention race. An existing order-dependent shelves fixture also needed
eager consumer loading before mocking its transport; the exact failing two-test
sequence passes after that test-only repair. Focused source regressions, frontend
coverage, types, lint, build, Django/migration checks, executed image/network proof,
private-denylist gate and fourteen private rendered samples pass. The complete
warning-strict rerun passed 3,993 tests and 187 subtests with 14 skips. The populated-upgrade rehearsal now expects migration 0015, checks the new
CoverSearch column set, and verifies its runtime DML/denied administrative grants
after migration and restore. Release manifests already expected 0015.
Required PR checks and independent review still own remote acceptance. Host firewall changes
remain deferred; the proof does not claim installed host/LAN filtering.

Nothing needs testing in the installed application. The lead can review the PR
and private synthetic evidence, then complete exact-head checks and independent
review. Deployment remains separate. Goodreads/browser/extension intake,
current-cover upscaling and prebake belong to PR3b; cover delivery/Undo remains
separately gated.

## Review round 2

The 24-result web budget now gives newest searches capacity first, retaining the
saved selection when older results are displaced. Regression journeys fill an
older search, then refine or paste an image and select the new result.

The registry validator admits only the optional cover-sources role with its
fixed execution, resource, secret and network contract. Base and overlay models,
including actual Compose resolution, pass; unsafe attachments and source-role
overrides remain refused. The owner clarified that live Lexicanum needs a browser
session; the source now queries Wayback directly and is labelled "Lexicanum
(archived copy)". Live hosts are refused before DNS, including pasted URLs and
redirects. The strict weak-match gate, Book2.jpg exclusion, pacing and deadlines
remain. Wayback 429 reports Rate limited; persistent 503 reports Unavailable.
Live art belongs to the browser extension in PR3b. Stored Original/Enhanced
catalogue art remains available.
This reuses the retained archive parser and existing selection/registry gates;
no dependency or new provider implementation is introduced.

Failing-first regressions demonstrated each reported defect. The focused
warning-strict run passed 236 tests; frontend coverage passed 1,268 tests. Fourteen
synthetic rendered samples cover both rooms, phone/reflow and enlarged text with
no overflow or axe findings. The complete warning-strict backend run passed
4,035 tests and 187 subtests with 14 skips. Python types, lint, build, Django/migration checks
and the private-denylist gate pass. Remote acceptance remains with exact-head PR
checks and review. Nothing needs testing in the installed application; no merge,
deployment or library write is part of this fix.
