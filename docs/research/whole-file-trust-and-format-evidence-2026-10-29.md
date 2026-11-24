# Whole-file trust and broader format evidence

Date: 2026-10-29. Status: curated-reference contract implemented in the development
backend and browser, with synthetic HTTP/worker/browser acceptance. The maintainer selected
locally curated reference copies with documented provenance. That selects the
implementation route; no particular authority, reference copy, external delivery
or writer is activated by this document.

## Existing evidence and the remaining gap

The [earlier authentication assessment](content-authentication-2026-10-29.md)
separated printed attribution from complete-artifact authentication. Inspection
v7 and assessment v4 implement attribution without claiming that the complete
advertised narrative is present. Their contracts are owned by
[development](../development.md#source-title-and-credit-attribution) and L050 in
[decisions](../decisions.md#l050--source-attribution-remains-separate-from-whole-file-authentication).

The source boundaries explain why a new trusted witness is necessary:

- `backend/librarium/file_inspections.py:report` rereads preserved source bytes
  and validates the immutable source/report/policy binding. It establishes which
  artifact was inspected, rather than who published its contents.
- `backend/librarium/content_evidence.py:capture` fingerprints ordered XHTML
  spine body source text. The module's scope excludes linked-asset equality,
  complete narrative identity, language/edition equivalence and semantic meaning.
- `backend/librarium/duplicate_evidence.py:resource_overlap` compares source-bound
  XML resources. Shared boilerplate and resource containment remain leads;
  neither establishes a complete story or book.
- `backend/librarium/catalogue.py:snapshot` validates explicit bibliographic
  snapshot bytes and schema. Title, author and ISBN agreement remain evidence
  from that bibliographic lineage, rather than an independently authenticated
  narrative reference.
- `backend/librarium/book_assessment.py:assess` retains independent content,
  semantic and writer blockers. `LIBRARIUM_REFERENCE_STATE_DIR` configures BLC
  reference production; it is not a book-content trust store.

No real issuer or reviewer is configured by this implementation. A field named
`verified`, an arbitrary URL, an owned local file or agreement between several
metadata fields cannot supply independently approved trust configuration.

## Selected route: a curated complete reference

Implement an offline reference mechanism whose trust configuration is separate
from uploads, catalogue metadata, ordinary check requests and library files.
The application may accept a reference only after the operator has selected its
authority and acquisition policy. An empty or unconfigured trust store must leave
authentication unconfirmed. Attributable review remains a secondary future route;
it is not an alternative acceptance path in the first implementation.

Each admitted reference would need an immutable record binding:

1. An opaque reference ID, exact source SHA-256 and byte size, format and the
   version of the reference-record contract. Artifact names are display data,
   never authority or filesystem selectors.
2. An acquisition receipt identifying the publication source, acquisition method
   and time, preserved supporting-evidence digests, and how that source was
   authenticated. Record actual private locators in protected configuration or
   private evidence, following [privacy](../privacy.md).
3. An independently authenticated issuer, its allowed claims and a verifiable
   binding between that issuer and this exact record. A signature is meaningful
   only when its verification key and scope were configured independently of
   the submitted record. A record must not nominate its own trusted key.
4. The original catalogue version/digest/work and any edition, language, revision
   and publication-scope claims. Explicitly distinguish a standalone work from
   a preview, abridgement, translation, anthology, omnibus or contained story.
5. Coverage of the complete reference. For collections, enumerate the expected
   constituent works, their order where meaningful, and the evidence supporting
   completeness. Unknown extras, missing constituents or unsupported media
   prevent a complete-container claim.
6. Issue time, an explicit validity policy, authority/key version and revocation
   identity. Historical observations preserve the policy and time under which
   they were made; a later result must check current revocation and freshness.

Initially, exact equality with an admitted complete reference is the narrowest
useful comparison. The resulting claim would be equality with that specific
authenticated reference under its recorded scope. It would inherit only the
publication and completeness claims that the authority was permitted to make.
It would not prove ownership, writer permission or absence of other duplicates.

A repackaged EPUB with matching normalized text needs a separate comparison
policy: changed assets, omitted media, reordered stories, edition differences
and hidden source text can survive text-only agreement. Such agreement must
remain a comparison observation until that policy and its supported claims have
been reviewed. Different bytes or different text likewise cannot establish that
two artifacts are semantically unrelated.

### First implementation contract

Keep the trust root in operator-controlled configuration outside the checkout,
outside the writable artifact store and outside the native library. The paired
settings `LIBRARIUM_CONTENT_TRUST_REGISTRY` and
`LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256` select one exact registry file and its
expected digest together. Neither is a request field. The registry, manifests,
receipts and reference artifacts are mounted read-only to the application and
worker. Their original acquisition and curation happen through a separately
authorized operator workflow; ordinary uploads cannot promote themselves into
this store.

The initial authentication mechanism is explicit operator curation of exact
registry bytes through that separate trusted configuration. Filesystem ownership
or a digest supplied alongside an upload is insufficient. A later remote or
signature-backed registry would need its own reviewed authenticator and protocol.

The reference's catalogue version/digest records its original curation provenance.
A new assessment independently pins the current catalogue and resolves the same
explicit `work_id`. A routine catalogue refresh does not require reacquiring or
re-curating an unchanged reference. A missing, changed or merged work ID refuses
the association; title, alias or fuzzy matching cannot rebind it. Edition-specific
claims additionally require the explicit edition to belong to that current work.
Keep the original reference publication pin and current assessment pin separately
visible. Regression cases must cover refreshed-same-work acceptance, changed-work
refusal and unavailable edition claims.

Use strict bounded JSON, rejecting duplicate keys, unknown fields and unsupported
versions. Hash the exact persisted bytes, avoiding an implicit JSON
canonicalization scheme. The following exact field sets are the implemented v1
contract; optional values use explicit `null` rather than omitted keys:

| Record | Exact fields and responsibility |
|---|---|
| Registry | `schema`, `registry_id`, `revision`, `issued_at`, `valid_until`, `authorities`, `references`, `revocations`. `schema` is `librarium.content-trust-registry.v1`; revision is a positive integer. Its configured digest authenticates the complete record. |
| Authority entry | `authority_id`, `method`, `scope`, `valid_from`, `valid_until`, `revoked_at`. Initially `method` is `operator_curated_local_reference`; scope is a nonempty unique list drawn from `work_identity`, `complete_collection`, `edition_identity`, `language`, `revision`. Authority IDs are opaque, and registry admission is the operator's responsibility. |
| Reference entry | `reference_id`, `authority_id`, `manifest_sha256`. It selects exact manifest bytes from the dedicated store by digest, never by a caller-supplied filesystem path. |
| Revocation entry | `reference_id`, `revoked_at`, `reason_code`. Authority-wide revocation also invalidates references issued under that authority. |
| Reference manifest | `schema`, `reference_id`, `authority_id`, `issued_at`, `valid_until`, `artifact`, `publication`, `acquisition`, `coverage`. `schema` is `librarium.complete-content-reference.v1`; IDs must match the registry entry. |
| Artifact | `sha256`, `size`, `format`. They bind the preserved full reference bytes. Format is exactly lowercase `epub`. A digest-derived store key selects bytes. |
| Publication | `catalogue_version`, `catalogue_sha256`, `work_id`, `edition_id`, `language`, `revision`, `scope`. Scope is `standalone_work` or `complete_collection`; unknown edition/language/revision stays `null` and cannot support that specific claim. |
| Acquisition | `method`, `acquired_at`, `source_lineage_id`, `receipt_sha256`, `publication_evidence_sha256`. Method and opaque lineage identify how the curated copy was obtained; separately preserved receipts explain the authenticated publication source. |
| Coverage | `protocol`, `record_sha256`, `expected_constituents`, `unsupported_components`. Protocol is `librarium.complete-reference-curation.v1`; the record documents whole-artifact examination. Empty unsupported components and complete expected-constituent evidence are necessary before a complete claim. |
| Constituent entry | `work_id`, `position`, `evidence_sha256`. Standalone scope requires the selected work; collection scope requires the container's complete expected set and its supporting independent publication evidence. Duplicate or missing positions/IDs refuse complete coverage. |

The acquisition receipt, publication evidence and coverage record remain immutable
private evidence selected by digest. Their content must establish the claims;
the mere presence of these fields is not proof. The curation workflow must inspect
and approve the exact manifest and evidence digests before adding its registry
entry. The application validates that approval boundary and byte bindings; it does
not invent provenance from a title or decide that a receipt URL is trustworthy.

For the first implementation, a request selects `reference_id`,
`registry_sha256` and `manifest_sha256` alongside the existing exact inspection and
catalogue pins. Validate that all selections agree with independently configured
registry bytes. A registry digest in a request is a concurrency pin, not a trust
root. Changing configured registry bytes requires a new operator configuration
decision and makes pending old-registry work refuse silent reinterpretation.

Record a source-bound result containing `schema_version`, `status`, `reason_codes`,
`source_sha256`, `report_sha256`, `catalogue`, `reference_id`, `reference_sha256`,
`manifest_sha256`, `registry_sha256`, `authority_id`, `reference_publication`, `checked_at`, `claims` and
`observation`. Status distinguishes `authenticated_reference_match`,
`different_bytes`, `unconfirmed` and `not_requested` when no reference was pinned.
Claims enumerate only supported work,
collection, edition, language and revision claims; observation identifies a
historical result. Exact byte equality is required for a positive v1 match.
Different bytes remain unconfirmed for narrative identity, even when source-text
fingerprints match. Authentication adds no semantic duplicate clearance or writer
permission.

Validate registry/authority/manifest time intervals and revocations at execution,
using a single captured check time. Reject future issuance, invalid interval
ordering, expired authority/registry/reference, duplicate IDs, unknown authorities,
missing evidence and any digest mismatch. Do not downgrade these failures to
successful authentication or substitute the latest reference. Preserve exact
records for historical recovery and label them historical. Loading an old result
does not consult current revocations or refresh its claim; its saved time and
registry pin remain explicit. A new current assessment checks the configured registry.

The dedicated store root is the selected registry file's parent. Fixed
`manifests/<digest>.json`, `evidence/<digest>` and `artifacts/<digest>` leaves use
validated digests, with no caller-supplied paths or alternate store selector.
All remain outside writable application artifacts and the native library.

## Secondary future route: attributable complete-artifact review

A reviewer route requires a separately authenticated reviewer and an approved
review protocol. A review record must bind the exact selected source digest/size,
inspection/report pins, protocol version, claimed work/edition/language and the
reviewer's permitted scope. Identity supplied inside the review payload does not
authenticate its author.

The review must explain how the entire artifact was examined, the independently
obtained publication evidence used to identify it, and any inaccessible, sampled,
truncated, encrypted, image-only or otherwise unsupported portions. For an omnibus
or anthology, review must cover the container and its expected constituents;
recognizing one story does not authenticate the collection. Partial review can
support a limited observation while leaving whole-file authentication unconfirmed.

Keep the review and its supporting evidence immutable and attributable. Bind
approval to exact reviewed bytes; later artifact changes require another review.
Define reviewer authorization, revocation and validity rules before accepting the
first attestation. A provider's name, model response or statement that it read
everything cannot replace evidence of authenticated origin and actual coverage.
No existing owner-acceptance mechanism for software release promotion grants
book-review authority.

## Spoofing, recovery and admission requirements

Both routes should refuse unknown issuers, self-supplied keys, unexpected record
fields, ambiguous identities, digest/size/policy mismatches, missing evidence,
unsupported coverage and stale or revoked authority. Pin reference and review
records explicitly; do not select an implicit latest witness or reinterpret old
records under a new protocol. Duplicate witnesses from one acquisition lineage
do not become independent evidence through repetition.

Saved historical results may remain readable after authority changes, provided
they disclose their historical nature. They must not silently become current
authorization. Offline recovery may recover the exact saved result; unavailable
current revocation information must not manufacture a fresh authentication claim.

Regression cases must include a forged issuer/key, a revoked or expired witness,
a changed selected artifact, a valid reference for another edition/language, a
sample or contained-story reference offered as a complete collection, missing
media and mixed source/report/catalogue pins. A positive exact-reference case
must still retain semantic duplicate and writer-admission boundaries.

## Non-EPUB evidence: establish the boundary first

The current upload/inspection path preserves EPUB artifacts, and explicit content
comparisons select completed EPUB inspections. All-format library byte observations
do not add a non-EPUB parser or preserved format-inspection contract. Introducing
such a contract is work separate from broadening comparisons of existing captures.

Strict UTF-8 TXT is a narrow possible first format. A proposed contract should
require explicit format selection, immutable original bytes and bounded decoding,
reject invalid encoding rather than replacing characters, and define treatment
of a BOM, line endings, whitespace and control characters. Bind every fingerprint
to that versioned normalization policy. Empty, truncated, undecodable or over-limit
input must supply no complete-text fingerprint. TXT has no reliable book/container
structure by itself, so complete text extraction still cannot authenticate a work,
edition or collection. No charset guessing or format conversion is implied.

PDF requires a separate isolated parser boundary and explicit extraction limits.
Distinguish encoded text extraction from rendered page appearance and OCR. Missing
or partial extraction, images, layout/reading order, embedded resources and
encryption need explicit coverage states. OCR would need its own versioned policy
and uncertainty reporting; successful text extraction cannot claim complete visual
or narrative equivalence. This recommendation selects no PDF dependency and makes
no claim about installed parser capabilities.

Cross-format comparisons may eventually share a deliberately reviewed normalized
text policy. Their source-format extraction and coverage must remain visible.
Matching text supplies a possible duplicate lead; differing extraction is not
semantic clearance. Native library membership remains bound to the exact recorded
library/inventory/file origin, independently of format comparison.

## Next bounded work and authorization

Broader source-bound document comparisons can proceed using eligible preserved
EPUB captures while trusted authentication remains unconfirmed. A future format
slice should first implement the immutable artifact/inspection boundary and its
failure states, then comparison. Neither step needs an external book recipient.

Implement and verify the selected local-reference contract against synthetic
records before asking the operator to approve a concrete authority, curator
protocol and first real reference. Acquiring new reference books,
importing owner confirmations or reviews, transmitting text externally, activating
a trust source, and clearing writer admission retain their applicable approval
boundaries. This document authorizes none of those actions.

This assessment reads local source and existing project contracts only. It adds
no external research, reference corpus, trust configuration, parser dependency,
runtime acceptance result or production change.
