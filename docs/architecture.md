# Architecture assessment brief

Application stack: selected for the bounded synthetic experiment in the
[dated assessment](research/first-slice-2026-10-24.md): Django, React/TypeScript,
PostgreSQL and independent Python workers. This is an implemented experiment,
not production architecture approval or migration-parity evidence. L007 authorizes
local work; the following questions remain the evaluation brief.
Approved choices live in [decisions](decisions.md). See [upstream sources](../upstream/README.md)
for dated source anchors and [product outcomes](../PRODUCT.md) for the target.

## Leading proposal to evaluate

Django for application APIs/domain orchestration, React with TypeScript for a
bespoke interactive UI, PostgreSQL for owned application state, and independent
durable Python workers. Preserve existing BLC engines, published snapshot/API
contracts, and consumers where their evidence supports retaining them.

This was the previous assistant recommendation, not the maintainer's approved stack.
Reassess it against the real code and hard product journeys. Do not copy the
archived experiment's Django 5.2/Python 3.12 pins into an active application.
Verify current stable releases, compatibility, support dates, security-update
coverage, and the next upgrade path from official sources at assessment time.

TypeScript is a language; Angular/React are frontend approaches; Node is a runtime.
A frontend build pipeline may use Node without a running Node application backend.
Do not assume Node is required or forbidden. Choose one coherent UI approach;
adding overlapping frameworks does not establish stability.

## Evidence to gather

| Area | Question | Required evidence |
|---|---|---|
| Product/domain | What belongs together for the user, and who owns each datum? | User journeys and current source/contract map |
| Existing systems | What should be retained, adapted, or replaced? | Committed source anchors, consumers, compatibility risks |
| Frontend | Which approach delivers the chosen experience and predictable state? | Accessible mobile/desktop interaction experiment, failure/reconnect cases |
| Backend | What does Django improve over current service boundaries? | Domain/auth/transaction/job needs and integration cost |
| Jobs | How do checks survive disconnects without blocking interaction? | Durable state, idempotency, progress, cancellation semantics, recovery design |
| Storage | Which data needs a relational database, snapshots, or external writers? | Ownership, migration/reconciliation strategy, rollback |
| Runtime | Are capability, maturity, and support runway healthy? | Dated primary-source support/compatibility matrix and upgrade plan |
| Operations | How are regressions diagnosed and deployment reversed? | Observability, backup/restore, failure isolation, staged rollout plan |

Compare the leading proposal with credible alternatives, including retaining more
of the present backend and a different frontend approach where justified. Explain
why each alternative wins or loses on the actual journeys; do not choose by
popularity, the assistant's comfort, or generic framework checklists.

## Migration experiment foundation

Periodic source snapshots should capture committed source at an explicit commit,
record repository/ref/commit/archive hashes, and produce repeatable assessments
without importing production data or executing upstream code. Refreshes must be
explicit, reviewable, and must not reset either source checkout. The old helper
code is unapproved research input; its fixture tests alone are insufficient.

The first proposed experiment must cover a representative end-to-end journey with
background work, useful progress, responsive controls, failure/retry handling,
and a visible data contract. Define measurable acceptance criteria before building.
Do not declare migration viable after a tiny helper endpoint or static mockup.

## Deliverable

Produce one dated recommendation under `docs/research/`, an independent review
under `docs/reviews/`, and a dated status entry under `docs/status/`. Include an honest
retained/replaced map, support matrix, measured/unknown distinctions, and the
smallest representative experiment that can disprove the recommendation.
L007 lifts the implementation pause. Evaluate contracts and technical choices as
part of the first application slice, record the rationale, and continue bounded
local implementation without another general approval gate. Follow the accepted
[container release contract](packaging.md). Publication and production retain
their explicit authorization requirements.

## Retained synthetic writer core

[L055](decisions.md#l055-conditionally-replace-one-epub-through-a-synthetic-sole-owner-writer)
added a separate disabled writer for generated fixtures only.
[L060](decisions.md#l060-delivery-through-the-owning-calibre-content-server)
connected it to the owning Calibre content server. [L091](decisions.md#l091-librarium-reads-and-checks-books-and-no-longer-repairs-them)
retired the corrected copies that fed it and removed the web approval, dispatcher,
routes and worker around it: Librarium reads and checks books and reports problems,
and nothing in the web or worker reaches the writer now. The writer core, its broker
journal, content-server transport and recovery evidence remain as Librarium's
library-write path until the owner decides it. The server alone owns the writing
cache, the writer has a read-only library mount, and production activation remains
unapproved.

Broker fences and reconciliation compare the selected book's identity, EPUB and
authored metadata. The server has no atomic expected-digest write, so supervision must
exclude other writers. Derived page counts, size and modification times remain server
housekeeping. Uncertain or mismatched outcomes latch a durable global hold until
reviewed; reconciliation never resends or clears the hold. Authoritative never-sent
operations seal as not applied and release their target. Historical receipts never
recapture a released reservation. Marker flock exclusion covers cooperating Librarium
writers only; server read-back does not certify remote fsync or physical recovery.

## Continuous preserved-book workspace

The book task joins the native Library and preserved incoming EPUB to the existing
inspection, pinned reference comparison, EPUBCheck validation and explicit
assessment contracts. It introduces no second application mode, bibliographic
resolver, repair engine or writer. Source history remains keyed by the recorded
inspection and immutable source/report bindings rather than by title.

A bounded read projection resolves selected job and artifact identifiers against
that lineage before the interface mounts result controls. Recorded Library origin
is historical context, never current ownership or write permission. Recovery reads
do not require the original Library mount. A saved route that still names a retired
selection (a review copy, an output check or a delivery) opens at its nearest kept
ancestor, the inspection or the selected assessment. See the
[workspace contract](development.md#preserved-book-workspace) and
[verification scope](unified-book-workspace.tdd.md).

Retained confirmed views survive pending selections and transient reads; pending
selections cannot start new work, while cancellation and request recovery remain
available.
