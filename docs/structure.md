# Structure and ownership

This is the canonical map of the local project. Folder existence is not proof
that a capability is implemented. [Status](status.md) owns readiness and next work.

```text
librarium/
  docs/ci.md                GitHub-hosted runner policy and CI trust contract
  docs/research/ci-job-audit-2026-11-06.md measured CI costs and proposed test tiers
  scripts/ci_policy.py       trusted-base candidate workflow validation
  .github/scripts/changed_areas.py PR source checks and container-tier selection
  .github/scripts/cover_census_benchmark.py disposable offline census fixture, profiler and byte-preservation proof
  .github/scripts/container_tiers.py selected/deferred required container result
  AGENTS.md                 shared rules for every assistant
  CLAUDE.md                 imports AGENTS.md into Claude Code
  README.md                 entry point
  PRODUCT.md                product ambition, journeys, and required qualities
  DESIGN.md                 implemented design tokens and interaction rules
  .impeccable/design.json   verified Impeccable design-system sidecar
  Librarium.code-workspace  shared VS Code entry point
  .vscode/                  project settings, extension suggestions, process tasks
  scripts/release.py        paired beta identity, deterministic stack assets and source-derived manifest
  scripts/populated_upgrade.py isolated historical-source upgrade/capture/recovery orchestration
  scripts/upgrade_fixture.py synthetic old/current application work and retained-evidence checks
  backend/librarium/build_identity.py packaged source/assets identity and shared compatibility
  backend/librarium/operational_status.py bounded private operator report projection
  backend/librarium/recovery_evidence.py strict retained isolated recovery observations
  backend/librarium/management/commands/support_report.py read-only JSON diagnostics
  docs/operational-support.md signals, ownership, capacity, incidents and proposed cadence
  scripts/registry.py       authenticated paired GHCR manifest/config verification
  scripts/promotion.py      owner-accepted paired beta verification and exact-byte stable promotion
  scripts/registry_config.py resolved deployment isolation checks
  compose.registry.yaml    registry-only isolated deployment path
  compose.registry-library.yaml single-entry registry deployment with native read-only library
  compose.registry-workspace.yaml single-entry preserved-book workflow with read-only assessment inputs
  compose.runtime.yaml     separated non-owner web/worker database credentials
  scripts/runtime_login.sql create-only login bootstrap with protected environment input
  scripts/runtime_identity.py read-only effective-login and existing grant-matrix admission check
  .github/scripts/runtime_container_acceptance.py composed admission failures and fresh-cluster recovery
  compose.assessments.yaml  explicit worker read-only library/catalogue inputs for durable checks
  compose.catalogue-sync.yaml opt-in worker replica writes via a fixed-upstream TCP relay
  compose.source-browser.yaml opt-in headed Chrome role, private control and owned profile
  services/source-browser/ pinned browser image, namespace seccomp policy and reuse provenance
  compose.cover-sources.yaml opt-in source-only public egress, authenticated worker lane and internal edge ingress
  .github/scripts/cover_sources_container_acceptance.py executed disposable network/capability proof
  backend/librarium/catalogue_sync.py bounded idle-worker snapshot and verified cover replication
  compose.content-trust.yaml independently pinned read-only curated reference store
  backend/librarium/xml_policy.py closed XML DOCTYPE and HTML character-reference policy
  scripts/check_public_content.py redacted tracked-content privacy gate
  docs/privacy.md           personal/operational context and publication boundary
  tests/test_public_content.py privacy regression behavior
  scripts/dev.py            read-only environment/workspace integrity checks
  scripts/capture_source.py selected committed-source capture and integrity checks
  scripts/build_libarchive.py hash-verified native archive build and capability check
  Dockerfile.writer         separate disabled synthetic Calibre runtime, absent from ordinary roles
  scripts/run_delivery_writer.py verified runtime, synthetic marker, content-server connection
  scripts/calibre_delivery_runtime.json official archive digests and provenance
  scripts/calibre_delivery_gate.py / calibre_delivery_owner.py native lock/API proof
  scripts/install_epubcheck.py hash-verified complete official checker distribution install
  scripts/cloud_session_start.sh cloud-session-only PostgreSQL start and pinned dependency sync
  scripts/design_system.py  builds the Design System artifact's files from code and design-system/
  design-system/            authored artifact content (tokens.base.json, project/); build/ is generated
  tests/workspace_test.py   development CLI behavior and archive protection
  tests/test_capture_source.py source-capture behavior and boundary tests
  tests/test_release_workflows.py paired artifact and publication-order contracts
  tests/test_promotion.py    acceptance, transport, exact-copy and partial-publication refusals
  tests/test_design_system.py theme parsing, contrast and artifact build output
  pyproject.toml / uv.lock  application/test dependencies; Python in .python-version
  requirements.txt          generated hash-locked runtime export for image builds
  backend/
    bl_catalog/             retained offline BLC evidence/resolver/publisher, provenance manifest
      native.py             bounded packet facade and immutable staging, no provider fetching
    librarium/              Django reads, fixture projection, durable job protocol
      catalogue.py          validated read-only, version/digest-pinned BLC snapshots
      catalogue_views.py    catalogue status, work/series/author search and evidence API
      catalogue_covers.py   pinned, digest-verified local original/derivative artwork
      cover_candidates.py   local art admission, bounded catalogue suggestions and prepared selections
      source_browser.py     authenticated bounded browser owner and public-address pinned proxy
      cover_browser_sources.py worker Goodreads cache and bounded live wiki search/export adapter
      cover_browser_parsing.py fresh HTML/XML parser with CPU, memory and elapsed-time limits
      cover_candidate_views.py authenticated pinned choice and selection API
      cover_sources.py concurrent leased web searches, source and per-image timings, independent admission
      cover_admission.py shared image-admission slots granted round-robin across sources
      cover_providers.py / cover_source_rules.py LF provider/ranking ports, archive-only wiki search
      cover_source_fetch.py checked-public-address HTTPS transport and redirect policy
      cover_source_server.py isolated nonwriting internet role with typed bounded interface
      cover_source_image.py / cover_source_image_child.py sandboxed metadata-free derivatives
      cover_source_protocol.py / cover_source_views.py closed role vocabulary and authenticated job API
      cover_sources_provenance.json LF commit/function/test provenance
      catalogue_status.py   worker-only bounded BLC poll and latest-good Postgres copy
      catalogue_health.py   saved telemetry and snapshot/job health projection
      catalogue_reviews.py  pinned compact capture and pure catalogue metadata review
      epub_inspection.py    pure policy-versioned EPUB domain checks and bounded report (v11: no contents planner)
      identifier_evidence.py bounded raw identifier capture, target census and saved-report validation
      xml_names.py          shared XML 1.0 NCName and XML whitespace rules
      epub_archive.py       maintained seekable ZIP reader and actual output budgets
      inspection_process.py fresh Linux inspection child, limits and bounded transport
      artifacts.py          immutable private source/report artifacts, no-follow access
      file_inspections.py   captured source/policy jobs and fenced report publication
      epub_validations.py  source-bound EPUBCheck jobs, heartbeat/lease fencing and report binding
      epubcheck_process.py pinned offline checker child, limits and normalized immutable evidence
      epubcheck_sandbox.py fail-closed Linux Landlock filesystem rules for the Java child
      python_sandbox.py grant-free Landlock, codec preloads and late-import guard
      seccomp_sandbox.py shared network/io_uring denial; Python-only process controls
      epubcheck_distribution.json official checker archive and complete JAR manifest pins
      package_comparison.py explicit report/catalogue-pin comparison and global alias checks
      package_identifiers.py explicit ISBN URNs, canonical representation and complete pinned edition evidence
      isbn_declarations.py  conservative interpretation of captured EPUB 2 schemes and EPUB 3 ONIX types
      library.py            bounded selected-field LF browse reader
      library_evidence.py   bounded LF positive evidence for one pinned series/work
      library_shelves.py    bounded background match index, matching-only pages and position leads
      direct_library.py / direct_library_views.py native read-only Calibre metadata/WAL, files and covers
      library_matching.py   conservative native metadata matching against exact catalogue bytes
      library_reconciliation.py complete pinned metadata inventories, saved coverage and explicit deltas
      cover_facts.py / cover_process.py ported cover detectors in a bounded raster child
      cover_reviews.py / cover_review_views.py explicit census, skip queue and bounded pinned page suggestions
      library_read_model.py worker-refreshed Postgres copy of the Calibre listing data, serving and parity
      reconciliation_views.py bounded historical coverage and selected-source confirmation
      management/commands/provision_runtime_role.py owner-only runtime grant matrix
      testing/postgresql/   atomic flush backend selected only by test_settings
      delivery_contract.py   policy name bound into writer grants and receipts
      operator_identity.py default-off exact-proxy identity handoff at the outer WSGI boundary
      delivery_client.py     fixed loopback RPC to the retained writer and bounded deadline
      delivery_authorization.py independent approval seals, distinct from transport
      delivery_broker.py     durable journal, consumed operations, reservations and epoch fencing
      delivery_recovery.py   verified offline baseline and durable operation recovery references
      delivery_content_server.py / delivery_session.py remote byte transport and supervised approval
      delivery_native.py / delivery_writer.py historical native test oracle and narrow synthetic RPC (writer core, retained by L091)
      retired_jobs.py        retired job kinds: stored history only, never claimed, cancellable
      library_check_jobs.py / library_check_views.py durable pinned reconciliation/assessment requests and recovery
      book_assessment.py       independent declared identity, all-recorded-format byte census and admission blockers
      content_trust.py / content_trust_views.py strict curated-reference store and safe metadata discovery
      source_attribution.py   bounded source title/credit capture and strict locator validation
      attribution_comparison.py separate pinned catalogue corroboration, never whole-file authentication
      content_evidence.py      bounded whole-spine and document source-text/resource fingerprints, no prose
      duplicate_evidence.py    pinned document-text/shared-resource leads, no semantic clearance
      catalogue_control.py saved-source health and incomplete/conflict/same-title queues
      catalogue_health.py  read-only tool-health report for the Catalogue dashboard
      reference_production.py private native generations, receipts, recovery and active publication
      library_inspections.py source-bound capture from a selected native library EPUB
      book_workspace.py     bounded recorded lineage, exact route resolution and Library resume
      validation.py         shared bounded text validation
      management/commands/ fixture seeding and independent worker dispatch by job kind
        reference_import.py explicit offline packet import; no web writer or scheduled updater
        library_reconcile.py / library_reconciliation.py save/read complete historical coverage
        library_read_model.py refresh the library read model or check its parity
      migrations/           application-owned schema; no external library state
        0003_catalogue_review_jobs.py job kind/target, backfill, guarded reverse
        0004_epub_inspection_jobs.py preserved file-job kind and guarded reverse
        0005_epub_validation_jobs.py source-bound checker-job kind and guarded reverse
        0006_library_reconciliation.py saved inventory/coverage reports and guarded reverse
        0007_library_check_jobs.py pinned check job kinds/active intents and guarded reverse
        0008_corrected_epub_jobs.py protected output bindings, kinds, active intents and legacy lease/reverse guards (tables and guards kept; the kinds are retired by L091)
        0011_library_read_model.py replaceable Calibre read model; plain reverse
        0013_cover_census.py durable cover census, UUID-paired queue and idempotent skip receipts
    tests/                  PostgreSQL journey/concurrency/security tests
      test_catalogue_review*.py / test_library_*evidence.py / test_static_shell.py
      test_catalogue_mapping.py immutable scans, bounded file-read syscalls and source preservation
      test_job_history.py   complete paged history, literal filters and read-only boundary
      test_epub_*.py / test_inspection_process.py parser, archive and resource regressions
      test_epub_contents_evidence.py labelled headings, printed links and source NAV/NCX hierarchy
      test_epub_source_positions.py heading/link source order, ancestry, alias ids and v11 report shape
      test_epub_identifiers.py raw declarations, exact targets, package hashes and historical capture absence
      test_delivery_http_deadline.py trickled authentication/headers/body, shared retries, TLS and cleanup
      test_isbn_declarations.py declared types, namespace resolution, ambiguity and lexical regressions
      test_empty_navigation.py empty navigation as a structural error, never repaired, and v10 history
      test_artifacts.py / test_file_inspection*.py storage, upload and job provenance
      test_epub_validation*.py durable checker protocol, API, cancellation and recovery
      test_epubcheck*.py process/report/identity boundaries, native checker and filesystem isolation
  frontend/                 React/TypeScript app, locked Node build/test tooling
    reader.html / reader-page.ts reader page entry; excludes unshipped foliate-js modules
    vendor/foliate-js/      pinned, unmodified MIT reader engine subset with hashes
    src/                    collection, Library, Catalogue, progress, identity and evidence values
      LibraryEvidence.tsx   saved-library positive evidence overlay and match proof
      CatalogueReview.tsx   review action, progress, cancel and same-key retry
      JobProgress.tsx       shared job progress for inspections and reviews
      FindingEvidence.tsx / finding-evidence.css source-agreement comparisons with exact raw evidence
      CoverReview.tsx / cover-review-api.ts / cover-review.css read-only cover wall, strict reads and local suggestions
      ReviewHistory.tsx / review-history.css complete filtered history and return context
      FileInspections.tsx   preserved-book context, inspection, source history and incoming entry
      book-workspace.ts     strict selected-lineage decoder and shared workspace context
      EpubValidation.tsx / epub-validation-api.ts / epub-validation.css explicit checker attempts, recovery and diagnostics
      EpubCheckMessage.tsx   bounded date explanations with exact checker diagnostic disclosure
      PackageComparison.tsx / package-comparison.css explicit title search, alias evidence and comparison recovery
      CandidateAssessment.tsx / candidate-assessment-api.ts explicit coverage/reference/comparison pins, durable checks and saved results
      candidate-assessment.css responsive assessment choices and evidence readouts
      OutputStructureEvidence.tsx inspection coverage/findings before exact checker policy
      SourceAttribution.tsx  source-bound title/credit disclosure and historical absence
      IdentifierDeclarations.tsx / identifier-declarations.css raw package attributes and refinement targets
      themes.ts             palette registry; theme.ts applies validated preferences
      BookCover.tsx / BrowseView.tsx safe artwork fallback and remembered Shelves/List
      Synopsis.tsx / LibraryBookDetails.tsx measured preview and lazy pinned book context
      Library.tsx           series shelves, search/filter state, selection and Library return path
      DirectLibrary.tsx / direct-library.css native books, files, covers, matching and inspection entry
      reader/               reader page (/read/<id>): foliate-js shell, loader, cleaning, places, settings
      CatalogueControl.tsx / catalogue-control.css pinned reference attention queues
      CatalogueHealth.tsx / catalogue-health.css Catalogue landing: tool-health dashboard
      CatalogueGlance.tsx / catalogue-sources.ts cycle band, source display names and cover progress
      CatalogueSupport.tsx / catalogue-support.css grouped field claims, source associations and raw support
      LibraryBookArt.tsx / LibraryBookPane.tsx admitted artwork and selected book/evidence disclosures
      SeriesName.tsx        shared slash break opportunities without splitting series words
      SeriesRoom.tsx / catalogue-room.css Catalogue/author folios and recorded-order series room
      reading-room.css      approved Library composition, responsive shelves and detail
      ThemePicker.tsx       saved preference, device mode and cross-tab changes
      assets/librarium-symbols.svg supplied emblem/small/outlined-lettering symbols
    theme-assets.ts         generated same-origin theme CSS and pre-paint script
    tests/                  mounted journeys, API deadlines, state and semantic axe
      cover-review*.test.ts* cover queue, strict suggestions, skips, recovery, navigation and history
      epub-validation.test.tsx source/profile binding, request recovery, stale-response and keyboard behavior
      identifier-declarations.test.tsx raw-value disclosure, binding and historical absence
      candidate-assessment*.test.ts* strict API bindings, explicit choices, recovery, cancellation and saved assessment reopening
  Dockerfile               pinned frontend build and non-root Python runtime
  compose.yaml             separate fictional local experiment stack
  compose.dockhand.yaml    persistent Compose candidate, no automatic demo seed
  compose.files.yaml       opt-in private artifact mount; file inspection disabled by default
  compose.library.yaml     opt-in read-only Calibre mount for web only, no LF origin
  .github/workflows/       source/container checks and manual package publication/promotion; no deployment
  .github/gitleaks.toml     scoped public-checksum secret-scan rule
  .github/scripts/         actual image/worker/persistence and synthetic acceptance helpers (assessment, native writer proofs)
  .github/ISSUE_TEMPLATE/  product, bug and release/activation forms linked to Project 5
  .github/pull_request_template.md issue completion, validation and operational scope
  .github/release.yml      generated release-note categories, not a publication workflow
  .env.example              names only; real local values remain ignored
  .codex/README.md           Codex-specific onboarding
  .claude/README.md          Claude-specific onboarding
  .claude/settings.json      SessionStart hook for cloud sessions (no-op locally)
  .agents/rules/librarium.md Antigravity pointer to the same AGENTS.md and knowledge workflow
  .governance/docs-map.json  documentation-role mapping for the existing audit
  docs/
    agent-environment.md    portable private-context discovery and sharing contract
    architecture.md         assessment questions and local experiment boundary
    context-hygiene.md      knowledge ownership, maintenance, conflict and bloat policy
    decisions.md            durable approved decisions
    development.md          local checks and setup boundaries
    frontend-control-inventory.md permanent control IDs, route/state ownership and bounded coverage
    frontend-findings.md     single severity register and frontend completion acceptance
    delivery-recovery.md    offline baseline verification, admission and restore limits
    unified-book-workspace.tdd.md continuous source context and acceptance scope
    python-child-sandbox.tdd.md filesystem/network sandbox RED/GREEN guarantees and limits
    vscode.md               Remote SSH, live diff/history review, optional coding
    packaging.md            accepted reproducible container release contract
    populated-upgrade.md    historical-source rehearsal sequence and held target packet
    populated-upgrade.tdd.md actual transition proof, regression scope and image limits
    roadmap.md              product goals and release acceptance
    releases.md             versioning, beta/stable promotion and activation policy
    dockhand.md             portable deployment setup and target gates
    skills.md               capability-based skill routing
    ux-standards.md         canonical UI hierarchy, status, density and acceptance rules
    status.md               status index, product baseline and open gates
    status/                 dated per-PR status entries (YYYY-MM-DD-<slug>.md)
    handoffs/START-HERE.md  complete prompt to start with either assistant
    design/lexicanum-intake.md proposed native reference intake, source-browser contract and Update workflow
    design/collection.md   surface direction contract and pre-build acceptance
    design/accounts-and-collections.md future invited accounts, content ownership and optional sharing
    design/reading-room-foundation-2026-10-26.md approved Library shelves foundation and implementation contract
    design/design-system-artifact.md Design System artifact: sources, build and sync
    research/               dated investigations and source evidence
    research/epubcheck-runtime-2026-10-27.md official checker/JRE pins, support and upgrade evidence
    research/ecc-setup-2026-10-24.md local/hosted ECC audit and setup gaps
    reviews/                independent review findings and resolution
      contents-plan-2026-10-27.md source/worker/UI findings, corrections and bounded verdict
      epub-validation-2026-10-27.md independent backend/process findings and parent rendered/native proof
  upstream/
    README.md               source/snapshot policy
    sources.json            refreshed local refs and source-capture provenance
    manifests/              reviewed source-selection integrity inventories
  experiments/
    README.md               experiment admission and lifecycle
    migration-baseline/    original paused Django experiment and preservation manifest
  images/inspiration/       three generated concepts and explanatory README
  images/brand/             preserved artwork; librarium-a/ owns the supplied vector family
```

`.impeccable/surfaces/frontend-src-catalogue-tsx.md` records the bounded series
extension's direction; `docs/reviews/series-explorer-*` own its independent finish
and design-system evidence. They supplement the canonical product/design owners.

## Canonical owners

| Fact | Owner |
|---|---|
| Contributor/agent rules | `AGENTS.md` |
| File navigation and boundaries | This map |
| Product outcomes | `PRODUCT.md` |
| Visual and interaction intent | `DESIGN.md` |
| UX priorities and UI acceptance | `docs/ux-standards.md` |
| Active phase, readiness, next deliverable | `docs/status.md` and `docs/status/` |
| Durable decisions and replacements | `docs/decisions.md` |
| Architecture options and evaluation method | `docs/architecture.md` |
| Reproducible local checks | `docs/development.md` |
| Assistant-specific discovery and workflow | Respective `.codex/` and `.claude/` README |
| Shared knowledge policy | `docs/context-hygiene.md` |
| Verified tool access, storage and fallbacks | `docs/agent-environment.md` |
| Work continuation prompt | `docs/handoffs/START-HERE.md` |

Research and review documents are supporting evidence, not competing status
trackers. Once GitHub work is authorized, Issues own task assignment and acceptance;
`docs/status.md` keeps the stable baseline while each PR adds its own dated entry
under `docs/status/`.

The local application is a synthetic experiment, not a production configuration.
PostgreSQL state and the isolated development toolchain live under ignored `.local`.
This implementation worktree links that directory to the parent checkout's shared
snapshot, cover cache, toolchain and verification artifacts.
Generated builds, screenshots/recordings, coverage, graphs and source archives remain
ignored. Source manifests contain no books or database bytes. `.impeccable/` owns
the documented design-system sidecar;
its disposable reviews/mocks are ignored. The public GitHub remote and active PR
are recorded in status. Container acceptance runs through GitHub Actions;
manual beta publication is configured, with no automatic release or deployment.

Private agent context and original operational documentation live outside the
checkout as described in [the environment contract](agent-environment.md).
They are not a tracked documentation subtree or a GitHub sharing mechanism.

Writer-core acceptance lives in `tests/test_delivery_*`, backend delivery tests and
`.github/scripts/delivery_native_kills.py`; its synthetic EPUB comes from
`.github/scripts/synthetic_epub_fixtures.py`. The writer-image workflow owns
actual-image native acceptance. Operational contracts and receipts remain outside
the checkout; see [the environment contract](agent-environment.md). The review-copy
generation, stylesheet and paragraph repair modules, their tests, scripts and
interface were removed by [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them);
`backend/tests/retired_history.py` builds stored rows of the retired kinds for the
tests that keep proving they stay readable history.

`backend/librarium/author_groups.py` owns bounded recorded-name presentation;
`catalogue.py` reuses it for alias-aware search and exact snapshot groups.
`frontend/src/author-groups-api.ts`, `AuthorGroups.tsx` and `author-groups.css`
own strict decoding and disclosure. Catalogue/FileInspections/PackageComparison
carry the explicit source-comparison continuation. `docs/author-aliases.tdd.md`
records L069 contracts and synthetic proof helpers.

`frontend/src/return-intent.ts` owns the shared cancellation guard for deferred
work and results-list restoration after newer reader input.

`frontend/src/FileInspections.tsx` shares a bound saved-report query between the
condition warning summary and the full report. `FindingEvidence.tsx` groups exact
typed captured values by field while retaining each record's source relationship,
qualifiers and raw-record focus target. Print tokens in `style.css` keep evidence
readable independently of the selected screen palette.

The Review wall opens `frontend/src/CoverPicker.tsx` through the pinned
`cover-picker-api.ts` contract; `cover-picker.css` owns its comparison and preview
layout, including side-by-side phone comparison. `cover_candidates.py` owns the
bounded pixel-facts cache and page-batched full-binding selection validation.
The wall owns opener focus restoration.
[Cover picker status](status/2026-11-11-cover-picker.md) records its limits.
