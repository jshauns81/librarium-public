# Conditional delivery backend, 2026-10-30

[L055](../decisions.md#l055-conditionally-replace-one-epub-through-a-synthetic-sole-owner-writer)
adds a disabled, synthetic-only conditional EPUB writer with immutable approval,
persist-before-send journals, verified read-back receipts, observation-only recovery
and guarded Undo. Source-derived navigation requires no identity assessment;
catalogue-derived operations re-authenticate under current pins. Duplicate uncertainty
is retained and acknowledged for each exact in-place request.

The pinned real-runtime feasibility gate and native copy-loop/SIGKILL recovery
vectors pass. Synthetic HTTP proof uses distinct web, inspection worker, dispatcher
and writer processes plus PostgreSQL, kernel role restrictions and private loopback.
It covers holds, exact-key lost-response recovery, independent role loss,
cancellation, receipt history, later metadata/EPUB drift, guarded Undo and coordinated
restore. These are generated fixtures, with no real library or incumbent changes.

Security review remediation passes 2,373 warning-strict Python tests and 11
subtests at 90.18% statement coverage. Delivery module coverage is
jobs 83.30%, views 74.58%, writer 91.00%, native 86.15%,
client 97.22%, broker 97.50%, contract 96.67%, authorization 100.00%;
the dispatcher command has 84.00% coverage. Native subprocess/HTTP proofs are
additional evidence, rather than subprocess coverage. Types, lint/format, Django
and migration checks, dependency audit, workspace integrity, tracked privacy and
commit secrets checks pass.

The native CI command passes the real Calibre gate, twelve kill vectors and
separate-process HTTP role proof. CI now verifies the official archive checksum
before extraction and requires these three tests; missing prerequisites fail.
Definite never-sent outcomes release reservations; target-scoped reconciliation
cannot recapture released targets. Web recomputes approval holds. Checked library
marker exclusion and fsync-before-receipt remain controlled synthetic boundaries.
Physical power-loss proof and privileged database maintenance remain gaps.

The separate writer image and required native image workflow are authored. The
image has not been built or accepted as part of this source delivery; no hosted
CI result is claimed.
The delivery interface is described below. Independent security re-review and actual-image
acceptance remain required integration gates. Live writer coordination, production database/RPC topology,
real-library access and activation remain unapproved and undesigned. The installed
beta and existing services are unchanged. See [development](../development.md#conditional-epub-delivery)
and [packaging](../packaging.md#synthetic-writer-role) for the implemented boundary.
