> Sanitized historical engineering record. Environment locators are examples;
> original operational evidence is private. Do not use these as live targets.

# Independent content authentication: next bounded slice

Date: 2026-10-29. Owner: Librarium / the maintainer. Investigation on `dev`, canonical
checkout `/home/developer/Developer/librarium`, main `ecfa0d5`. Continues
issue31; this recommendation
implements no authentication, provider, writer or admission decision.

## Recommendation

Capture source-located title/credit observations before introducing an identity
vote. Compare those observations with an explicitly selected pinned catalogue
work, separately from OPF declarations. Return corroboration, conflict or unknown;
keep `content_authentication` unconfirmed. A printed title and credited authors
can corroborate a work attribution, but cannot prove that its complete narrative
is present, that it is the advertised edition, or that an internal story names
the complete container. Source-text hashes and all-format byte-copy evidence
answer different questions and cannot fill that gap.

This is an actionable next implementation slice within the existing read-only
inspection and assessment boundary. It needs no new external provider or trust
endpoint. The existing policy already returns selected heading/navigation labels;
any new title/credit text must have its own small field/output limits and remain
in the immutable report, rather than being copied into job inputs or general logs.

## Verified upstream evidence

The candidate archive is ignored
`upstream/snapshots/library-finish-a2a3692-contracts/source.tar`, identified by
[the tracked manifest](../../upstream/manifests/library-finish-a2a3692.json):
commit `a2a3692c3d864e133f5d7b80ed71c9983e810432`, archive SHA-256
`98ce81f9f256348954e29ed34d660505e290738cf1c1c8844eddaee0d208866b`.
Archive bytes and the three identity module hashes were verified during this
investigation. Members were read in place; no upstream module was executed.
Locators below are archive member paths/lines at that commit.

- `bin/identity_vote.py:1–10,20–33,86–115` defines title-page, catalogue and
  isolated-read signals, plus owner confirmation and qualified catalogue support.
  Embedded metadata and filenames do not authenticate identity. Signal deduplication
  and tie handling exist, but vote agreement alone does not establish completeness.
- `bin/identity_resolver.py:45–71,113–135` samples bounded front/closing documents
  and checks nearby title/author text before chapter boundaries. It excludes
  navigation, advertisements, previews and series lists. Its document selection,
  text stripping and normalized-substring heuristics are adaptation candidates,
  not a parser/security contract to import into Librarium.
- `bin/identity_resolver.py:146–191,213–235,297–337` separates closing legal/bio
  corroboration and printed identifiers; internal-story credit and collection
  ambiguity retain review. Printed ISBN evidence is restricted by context and
  checksum. These exclusions are useful regression cases.
- `bin/identity_pilot.py:11–14,64–96` treats supplied text as untrusted evidence,
  marks sample truncation, checks exact quotes against source text and requires
  publication corroboration and collection evidence for its supported proposal.
  Provider agreement and a provider's assertion of whole-file scope do not
  independently prove complete preservation.
- `services/bookindex/app/intake.py:2162–2243` combines the signals and checks
  dissent. Its D058 compatibility permits a metadata-derived catalogue path;
  that historical behavior must not silently become Librarium's independent
  content-authentication policy. `:2244–2265` additionally holds periodicals and
  conflicting Calibre identity. No upstream owner override is imported here.

The archive is a captured candidate, not a reviewed replacement runtime or a
grant of library-write authority. See [L047/L048](../decisions.md#l047-durable-checks-and-independent-identity-evidence-precede-admission)
and [private engineering record](../agent-environment.md#private-context-discovery).

## Concrete implementation contract

1. Add a versioned observation module called inside the existing isolated EPUB
   inspection child, using its already bounded parsed trees. Preserve spine order,
   resource SHA-256, element/source position, literal short title/credit labels,
   and the rule that selected the candidate block. Distinguish a semantic
   title/credit marker from an unclassified front-matter lead. Do not infer that
   source text is visibly rendered, or treat a filename as a title-page marker.
2. Keep parsing and bibliographic interpretation separate. The capture consumes no
   selected work or OPF title as a search prompt. A later comparison binds the
   exact source/report digests, observation policy and catalogue version/digest/work
   ID. Reuse the existing conservative complete-author/alias rules rather than
   inventing surname matching. Catalogue title and ISBN stay one bibliographic
   lineage; two fields or repeated URLs are not two independent witnesses.
3. Expose `corroborated`, `conflicting`, `ambiguous`, or `unconfirmed` attribution,
   with cited observation IDs and explicit `whole_file_identity=unconfirmed`.
   Missing, truncated, malformed, unsupported or image-only title evidence is
   unknown. An observation from one contained story does not identify an omnibus.
   Saved old policies retain historical absence rather than acquiring new claims.
4. Advance the captured inspection policy for the new field and refuse pending
   old-policy work under the new engine. Update both saved-report readers and
   frontend report binding/display compatibility, even if broader UI controls
   remain deferred. Record the assessment engine upgrade separately. Retain
   content/semantic/writer admission blockers throughout this slice.

Meaningful RED cases should include matching OPF metadata with contradictory
title-page text; metadata-only agreement; title/author in navigation, preview,
advertisement, hidden/script content or a later contained story; collection-level
versus story-level authors; partial coauthors and alias collisions; an image-only
title page; duplicate candidate blocks; exhausted budgets; mixed source/report/
catalogue pins; and historical reports without capture. Positive cases should
independently construct the expected literal labels, resource hashes and source
positions, and verify that original EPUB bytes remain unchanged. A valid title
page must still leave complete narrative authentication unconfirmed.

## What remains a separate decision

Full content authentication needs an explicit independently trusted reference or
an attributable review of the complete selected artifact. None is established by
issue31, a source hash, the pinned bibliographic catalogue, or a provider name.
Define how publication evidence was acquired, its source lineage, scope and
freshness; how the reviewer/provider is authenticated; and what whole-file or
collection coverage actually supports before accepting an attestation. Do not
accept a caller-supplied `verified=true`, treat an arbitrary URL as trusted, or
forward books to a provider through routine assessment.

The next capture/corroboration slice can proceed without that decision. Enabling
external text delivery, importing owner confirmations, or clearing admission must
be reviewed against the concrete selected mechanism and existing approval
boundaries. No new mechanism or authority is selected by this report.

## Investigation checks and limits

Confirmed host/checkout/branch/commit and clean starting tree; queried local
Graphify before source navigation; read the product, architecture, decisions and
content-evidence handoff; verified archive/module digests and inspected the named
committed contracts. No external fetching, real book access, source execution,
service change, runtime test or library write was performed. This is research
evidence and a scoped implementation recommendation, not authentication acceptance.
