# Future accounts and personal collections

Status: future product direction, requested 2026-11-01. Implementation is deferred
until the current delivery and recovery work is complete. This document describes
requirements to design and prove; the current application does not provide these
account boundaries.

Issue 93 tracks the future scope.

## Experience

Keep the reading-room artwork, themes and overall layout. Each invited user gets
an individual account with a personal collection, saved preferences and activity
history. Collections can contain any supported books, including books outside
Warhammer. Identity, content access and permission to repair or deliver a file
are separate decisions.

Provide a Librarium-branded sign-in entry and an application session tied to a
verified identity. Prefer a maintained OpenID Connect integration with the
configured identity provider, using its supported login branding. A customized
screen does not require another password database. Keep passwords and recovery
with the identity provider; select the maintained Django integration and exact
login/logout protocol during implementation. Bind accounts to issuer and subject,
not a mutable display name or email address.

Private collections are the proposed default. Explicit sharing may grant another
account access to a selected collection; sharing the same book must not expose
someone else's private notes, preferences or history. Decide read versus editing
permissions before offering sharing. Invited reader access must not confer the
maintainer's library-writing permissions.

## Data and access boundaries

Represent users, collection ownership and membership explicitly. Separate the
physical Calibre library and stored book bytes from the collections a user can
access; multiple users need not duplicate the same EPUB on disk. Select shared
versus independent physical-library support during design, rather than assuming
one Calibre database per account.

Apply access checks on the server to books, searches, covers, evidence, artifacts,
jobs, outputs and history. Scope background jobs, recovery keys and caches to
the authorized collection and acting account. Filtering the visible shelves is
insufficient. Preserve creator/reviewer attribution through existing immutable
evidence without letting another user inherit approval or writer authority.

BL Catalog remains a specialized source for the books it covers. General reading
and browsing must work without a Warhammer reference match. Select additional
metadata sources later, with truthful unavailable/uncertain evidence; do not
treat a missing specialized record as proof that another genre is invalid.

## Implementation order and acceptance

1. Inventory current single-operator assumptions and choose the user, collection,
   membership and physical-library model. Define reader/editor/maintainer rights.
2. Reuse maintained identity-provider and Django session support for sign-in,
   logout, expiry and account disablement; preserve CSRF and trusted-origin checks.
3. Migrate existing content and evidence to an explicit initial owner, with a
   verified backup and no automatic sharing or evidence loss.
4. Enforce account/collection access throughout APIs, jobs, storage and caches.
5. Add account-aware collection selection, personal preferences and optional
   sharing within the current design. Broaden catalogue adapters separately.

Acceptance needs at least three independent fixture accounts with different and
partly shared collections, including a collection outside Warhammer. Prove direct
URL/API denial, search and cover isolation, job/output/history ownership, logout
and revocation, safe account switching and preservation of writer approvals.
Verify that existing records survive migration and that ordinary reading works
without a specialized catalogue. Render the new login/account journeys across
supported themes, keyboard navigation and narrow screens when they are built.

Public registration, subscription billing, reader-device synchronization and new
library-writing authority are outside this proposal. Identity-provider endpoints,
real account details and operational configuration belong outside the repository.
