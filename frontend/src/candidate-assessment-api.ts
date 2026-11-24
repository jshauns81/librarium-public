import { api } from "./api";
import type { Job } from "./types";

export const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const ANY_UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const DIGEST_PATTERN = /^[a-f0-9]{64}$/;

export type CatalogueSnapshotPin = {
  version: string;
  sha256: string;
  fixture: boolean;
};

export type ReconciliationInventoryPin = {
  token: string;
  library_uuid?: string | null;
  observed_at?: string | null;
  scope?: string;
};

export type SavedReconciliationSummary = {
  request_key: string;
  created_at: string;
  catalogue: CatalogueSnapshotPin;
  inventory: {
    token: string;
    observed_at?: string | null;
    scope?: string;
    library_uuid?: string | null;
  };
  counts?: {
    matched?: number;
    unmatched?: number;
    ambiguous?: number;
    disagreement?: number;
    held?: number;
  };
  total: number;
  observation: "historical";
  file_identity: "not_assessed";
  duplicates: "not_assessed";
  ready: false;
};

export type SavedReconciliationsPage = {
  reports: SavedReconciliationSummary[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type ComparisonInspectionPin = {
  job_id: string;
  source_sha256: string;
  report_sha256: string;
};

export type ReferenceClaimName =
  | "work_identity"
  | "complete_collection"
  | "edition_identity"
  | "language"
  | "revision";

export type DiscoveredContentReference = {
  reference_id: string;
  manifest_sha256: string;
  authority_id: string;
  artifact: {
    sha256: string;
    size: number;
    format: "epub";
  };
  publication: {
    work_id: string;
    edition_id: string | null;
    language: string | null;
    revision: string | null;
    scope: "standalone_work" | "complete_collection";
  };
  claims: ReferenceClaimName[];
};

export type ContentReferenceDiscovery = {
  policy_version: "librarium.content-trust-discovery.v1";
  status: "available" | "not_configured" | "unavailable";
  catalogue: {
    version: string;
    sha256: string;
    work_id: string;
  };
  registry_sha256: string | null;
  references: DiscoveredContentReference[];
  reason_codes: string[];
};

export type ReferenceSelectionPin = {
  reference_id: string;
  registry_sha256: string;
  manifest_sha256: string;
};

export type ReferenceAuthenticationResult = {
  schema_version: "librarium.content-reference-authentication.v1";
  status:
    | "not_requested"
    | "authenticated_reference_match"
    | "different_bytes"
    | "unconfirmed";
  reason_codes: string[];
  source_sha256: string;
  report_sha256: string;
  catalogue: {
    version: string;
    sha256: string;
    work_id: string;
  };
  reference_id: string | null;
  reference_sha256: string | null;
  manifest_sha256: string | null;
  registry_sha256: string | null;
  authority_id: string | null;
  checked_at: string;
  claims: ReferenceClaimName[];
  reference_publication: {
    catalogue_version: string;
    catalogue_sha256: string;
    work_id: string;
    edition_id: string | null;
    language: string | null;
    revision: string | null;
    scope: "standalone_work" | "complete_collection";
  } | null;
  observation: "historical";
};

export type SpineOverlapMatch = {
  sha256?: string;
  text_sha256?: string;
  text_chars?: number;
  selected: {
    path: string;
    spine_index: number;
    resource_sha256?: string;
  };
  comparison: {
    path: string;
    spine_index: number;
    resource_sha256?: string;
  };
};

export type SpineOverlapEvidence = {
  scope: string;
  status: "recorded" | "unconfirmed";
  relation: string;
  selected_documents: number | null;
  comparison_documents: number | null;
  matched_documents: number | null;
  pairing_order_preserved: boolean | null;
  matches: SpineOverlapMatch[];
  truncated: boolean;
  limitations: string;
};

export type ContentDuplicateComparison = {
  inspection: ComparisonInspectionPin;
  inspection_policy: string | null;
  content_policy: string | null;
  text_relation: "same" | "different" | "unconfirmed";
  resource_overlap?: SpineOverlapEvidence;
  document_text_overlap?: SpineOverlapEvidence;
  exact_bytes: boolean;
  inventory_membership: "recorded" | "unconfirmed" | "not_applicable";
  book_id: string | null;
  relationship: "same_native_origin" | "candidate";
  library_origin: {
    library_uuid?: string | null;
    book_id?: string | null;
    inventory?: string | null;
    format?: string | null;
  } | null;
  declared_work: { status: string; work_id: string };
  declared_edition: {
    status: string;
    edition_id: string | null;
    candidates: {
      edition_id: string;
      work_id: string | null;
      format: string | null;
      disputed: boolean;
    }[];
  };
  observation: "historical";
};

export type BookAssessmentReport = {
  schema_version: string;
  policy_version: string;
  job_id: string;
  source_sha256: string;
  report_sha256: string;
  catalogue: CatalogueSnapshotPin;
  reconciliation_key: string;
  inventory: {
    token: string;
    observed_at?: string | null;
    scope?: string;
    library_uuid?: string | null;
  };
  library_origin: {
    library_uuid?: string | null;
    book_id?: string | null;
    inventory?: string | null;
    format?: string | null;
  } | null;
  source_provenance?: {
    kind: "native_library" | "incoming_upload";
  };
  content_identity?: {
    policy: string;
    status: "recorded" | "unconfirmed";
    source_sha256: string;
    text_sha256: string | null;
    spine_bytes_sha256: string | null;
    text_chars: number | null;
    spine_documents: number | null;
    reason: string | null;
    scope: string;
  } | null;
  source_attribution?: {
    schema_version: string;
    policy_version: string;
    observation_policy: string | null;
    capture: "recorded" | "unconfirmed" | "not_captured";
    ready: false;
    status: "corroborated" | "conflicting" | "ambiguous" | "unconfirmed";
    job_id: string;
    source_sha256: string;
    report_sha256: string;
    catalogue: CatalogueSnapshotPin & { work_id: string };
    observation_ids: string[];
    whole_file_identity: "unconfirmed";
    content_authentication: "unconfirmed";
  } | null;
  reference_authentication?: ReferenceAuthenticationResult | null;
  assessed_at: string;
  observation: "historical";
  file_work_identity: {
    status: "supported" | "ambiguous" | "conflicting" | "unconfirmed";
    work_id: string;
    basis: string;
    title: { status: string; [key: string]: unknown };
    creators: { status: string; [key: string]: unknown };
    isbn: { status: string; [key: string]: unknown };
    content_authentication: string;
  };
  edition_identity: {
    status: "supported" | "ambiguous" | "conflicting" | "unconfirmed";
    edition_id: string | null;
    candidates: {
      edition_id: string;
      work_id: string | null;
      format: string | null;
      disputed: boolean;
    }[];
    basis: string;
    language_and_content_equivalence: string;
  };
  current_library_bytes: {
    status:
      | "same_bytes"
      | "different_bytes"
      | "changed_during_scan"
      | "not_applicable"
      | "unconfirmed";
    observed_sha256: string | null;
  };
  duplicates: {
    complete: boolean;
    scope: string;
    recorded_files: number;
    resolved_files: number;
    epub_files: number;
    other_formats?: {
      status: string;
      byte_comparison: string;
      count: number;
      files: { book_id: string; format: string }[];
      truncated: boolean;
    };
    hashed: number;
    different_size: number;
    budget_exhausted: boolean;
    bytes_read: number;
    unreadable: { book_id: string; reason: string }[];
    unreadable_count: number;
    exact_bytes: {
      status: "found" | "none_found" | "unconfirmed";
      count: number;
      books: { book_id: string; format: string; sha256: string }[];
      truncated: boolean;
    };
    same_work: {
      status: "possible" | "unconfirmed";
      candidates: { book_id: string; basis: string[] }[];
      count: number;
      truncated: boolean;
    };
    content?: {
      scope: string;
      clearance: "unconfirmed";
      comparisons: ContentDuplicateComparison[];
      possible_count: number;
      limitations: string;
    };
  };
  scope: string;
};

export type CheckHistoryJob = Omit<Job, "result"> & {
  result_summary: {
    policy_version: string | null;
    error_code: string | null;
    assessed_at?: string | null;
    reference_authentication?: string | null;
    exact_bytes?: string | null;
    reconciliation?: string | null;
  };
};
export type CheckJobHistoryPage = {
  jobs: CheckHistoryJob[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type ReconciliationIntent = {
  key: string;
  version: string;
  sha256: string;
  inventory_token: string;
  library_uuid: string | null;
  previous: string | null;
};

export type AssessmentIntent = {
  key: string;
  source_job_id: string;
  source_sha256: string;
  report_sha256: string;
  version: string;
  sha256: string;
  catalogue_work_id: string;
  reconciliation: string;
  comparison_inspections: ComparisonInspectionPin[];
  reference: ReferenceSelectionPin | null;
};

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

const text = (value: unknown, max = 4096): value is string =>
  typeof value === "string" && value.length <= max;
const nonempty = (value: unknown, max = 128): value is string =>
  text(value, max) && value.length > 0;
const digest = (value: unknown): value is string =>
  typeof value === "string" && DIGEST_PATTERN.test(value);
const uuid = (value: unknown): value is string =>
  typeof value === "string" && ANY_UUID_PATTERN.test(value);
const count = (value: unknown): value is number =>
  Number.isSafeInteger(value) && (value as number) >= 0;
const strings = (value: unknown, max = 256): value is string[] =>
  Array.isArray(value) &&
  value.length <= max &&
  value.every((item) => text(item));
const oneOf = (value: unknown, values: readonly string[]) =>
  typeof value === "string" && values.includes(value);
const instant = (value: unknown): value is string =>
  text(value, 64) &&
  /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value));
const exact = (value: Record<string, unknown>, fields: string[]) =>
  Object.keys(value).length === fields.length &&
  fields.every((key) => Object.hasOwn(value, key));
const nullableText = (value: unknown) => value === null || nonempty(value);
const nullableDigest = (value: unknown) => value === null || digest(value);
const claimNames = [
  "work_identity",
  "complete_collection",
  "edition_identity",
  "language",
  "revision",
] as const;
const claims = (value: unknown): value is ReferenceClaimName[] =>
  strings(value, claimNames.length) &&
  new Set(value).size === value.length &&
  value.every((item) => oneOf(item, claimNames));

function snapshot(value: unknown): value is CatalogueSnapshotPin {
  return (
    record(value) &&
    nonempty(value.version, 64) &&
    digest(value.sha256) &&
    typeof value.fixture === "boolean"
  );
}

function referencePin(value: unknown): value is ReferenceSelectionPin {
  return (
    record(value) &&
    exact(value, ["reference_id", "registry_sha256", "manifest_sha256"]) &&
    nonempty(value.reference_id, 80) &&
    digest(value.registry_sha256) &&
    digest(value.manifest_sha256)
  );
}

function comparisonPins(value: unknown): value is ComparisonInspectionPin[] {
  return (
    Array.isArray(value) &&
    value.length <= 8 &&
    value.every(
      (pin) =>
        record(pin) &&
        exact(pin, ["job_id", "source_sha256", "report_sha256"]) &&
        nonempty(pin.job_id) &&
        digest(pin.source_sha256) &&
        digest(pin.report_sha256),
    ) &&
    new Set(value.map((pin) => pin.job_id)).size === value.length
  );
}

function assessmentIntent(value: unknown): value is AssessmentIntent {
  return (
    record(value) &&
    exact(value, [
      "key",
      "source_job_id",
      "source_sha256",
      "report_sha256",
      "version",
      "sha256",
      "catalogue_work_id",
      "reconciliation",
      "comparison_inspections",
      "reference",
    ]) &&
    uuid(value.key) &&
    nonempty(value.source_job_id) &&
    digest(value.source_sha256) &&
    digest(value.report_sha256) &&
    nonempty(value.version, 64) &&
    digest(value.sha256) &&
    nonempty(value.catalogue_work_id, 80) &&
    uuid(value.reconciliation) &&
    comparisonPins(value.comparison_inspections) &&
    (value.reference === null || referencePin(value.reference))
  );
}

function reconciliationIntent(value: unknown): value is ReconciliationIntent {
  return (
    record(value) &&
    exact(value, [
      "key",
      "version",
      "sha256",
      "inventory_token",
      "library_uuid",
      "previous",
    ]) &&
    uuid(value.key) &&
    nonempty(value.version, 64) &&
    digest(value.sha256) &&
    digest(value.inventory_token) &&
    (value.library_uuid === null || nonempty(value.library_uuid, 2000)) &&
    (value.previous === null || uuid(value.previous))
  );
}

function baseJob(
  value: unknown,
  kind: "book_assessment" | "library_reconcile",
) {
  return (
    record(value) &&
    value.kind === kind &&
    nonempty(value.id) &&
    uuid(value.request_key) &&
    oneOf(value.state, [
      "queued",
      "running",
      "succeeded",
      "failed",
      "cancelled",
    ]) &&
    count(value.revision) &&
    value.revision > 0 &&
    count(value.attempts) &&
    count(value.checkpoint) &&
    text(value.title) &&
    text(value.message) &&
    instant(value.updated_at)
  );
}

function historyPage(
  value: unknown,
  page: number,
  kind: "book_assessment" | "library_reconcile",
): value is CheckJobHistoryPage {
  if (
    !record(value) ||
    value.page !== page ||
    value.page_size !== 24 ||
    !count(value.total) ||
    !count(value.pages) ||
    !Array.isArray(value.jobs) ||
    value.jobs.length > 24
  )
    return false;
  return value.jobs.every(
    (job) =>
      baseJob(job, kind) &&
      !Object.hasOwn(job, "result") &&
      record(job.result_summary) &&
      nullableText(job.result_summary.policy_version) &&
      nullableText(job.result_summary.error_code) &&
      (kind === "library_reconcile"
        ? job.result_summary.reconciliation === null ||
          uuid(job.result_summary.reconciliation)
        : (job.result_summary.assessed_at === null ||
            instant(job.result_summary.assessed_at)) &&
          (job.result_summary.reference_authentication === null ||
            oneOf(job.result_summary.reference_authentication, [
              "not_requested",
              "authenticated_reference_match",
              "different_bytes",
              "unconfirmed",
            ])) &&
          (job.result_summary.exact_bytes === null ||
            oneOf(job.result_summary.exact_bytes, [
              "found",
              "none_found",
              "unconfirmed",
            ]))),
  );
}

function publication(value: unknown, original = false) {
  return (
    record(value) &&
    nonempty(value.work_id, 80) &&
    nullableText(value.edition_id) &&
    nullableText(value.language) &&
    nullableText(value.revision) &&
    oneOf(value.scope, ["standalone_work", "complete_collection"]) &&
    (!original ||
      (nonempty(value.catalogue_version, 64) && digest(value.catalogue_sha256)))
  );
}

function authentication(
  value: unknown,
  source: Job,
  pin: CatalogueSnapshotPin,
  workId: string,
  selected?: unknown,
): value is ReferenceAuthenticationResult {
  if (
    !record(value) ||
    value.schema_version !== "librarium.content-reference-authentication.v1" ||
    !oneOf(value.status, [
      "not_requested",
      "authenticated_reference_match",
      "different_bytes",
      "unconfirmed",
    ]) ||
    !strings(value.reason_codes) ||
    value.source_sha256 !== source.source_sha256 ||
    value.report_sha256 !== source.result.report_sha256 ||
    !record(value.catalogue) ||
    value.catalogue.version !== pin.version ||
    value.catalogue.sha256 !== pin.sha256 ||
    value.catalogue.work_id !== workId ||
    value.observation !== "historical" ||
    !instant(value.checked_at) ||
    !claims(value.claims) ||
    !nullableText(value.reference_id) ||
    !nullableDigest(value.reference_sha256) ||
    !nullableDigest(value.manifest_sha256) ||
    !nullableDigest(value.registry_sha256) ||
    !nullableText(value.authority_id) ||
    !(
      value.reference_publication === null ||
      publication(value.reference_publication, true)
    )
  )
    return false;
  if (value.status === "not_requested")
    return (
      (selected === undefined || selected === null) &&
      value.reference_id === null &&
      value.reference_sha256 === null &&
      value.manifest_sha256 === null &&
      value.registry_sha256 === null &&
      value.authority_id === null &&
      value.reference_publication === null &&
      value.claims.length === 0 &&
      value.reason_codes.length === 1 &&
      value.reason_codes[0] === "reference_not_pinned"
    );
  if (
    !nonempty(value.reference_id, 80) ||
    !digest(value.registry_sha256) ||
    !digest(value.manifest_sha256)
  )
    return false;
  if (
    selected !== undefined &&
    (!referencePin(selected) ||
      value.reference_id !== selected.reference_id ||
      value.registry_sha256 !== selected.registry_sha256 ||
      value.manifest_sha256 !== selected.manifest_sha256)
  )
    return false;
  if (value.status === "unconfirmed") return value.claims.length === 0;
  if (value.status === "different_bytes")
    return (
      value.claims.length === 0 &&
      digest(value.reference_sha256) &&
      value.reference_sha256 !== source.source_sha256 &&
      nonempty(value.authority_id) &&
      record(value.reference_publication) &&
      value.reference_publication.work_id === workId
    );
  const pub = value.reference_publication;
  return (
    value.reference_sha256 === source.source_sha256 &&
    nonempty(value.authority_id) &&
    record(pub) &&
    pub.work_id === workId &&
    value.claims.includes("work_identity") &&
    (pub.scope !== "complete_collection" ||
      value.claims.includes("complete_collection")) &&
    (!value.claims.includes("edition_identity") || pub.edition_id !== null) &&
    (!value.claims.includes("language") || pub.language !== null) &&
    (!value.claims.includes("revision") || pub.revision !== null)
  );
}

function overlap(value: unknown) {
  if (
    !record(value) ||
    !oneOf(value.status, ["recorded", "unconfirmed"]) ||
    !nonempty(value.relation) ||
    !text(value.scope) ||
    !text(value.limitations) ||
    !(value.matched_documents === null || count(value.matched_documents)) ||
    !(value.selected_documents === null || count(value.selected_documents)) ||
    !(
      value.comparison_documents === null || count(value.comparison_documents)
    ) ||
    !(
      value.pairing_order_preserved === null ||
      typeof value.pairing_order_preserved === "boolean"
    ) ||
    typeof value.truncated !== "boolean" ||
    !Array.isArray(value.matches) ||
    value.matches.length > 64
  )
    return false;
  return value.matches.every(
    (match) =>
      record(match) &&
      (digest(match.sha256) || digest(match.text_sha256)) &&
      [match.selected, match.comparison].every(
        (side) =>
          record(side) && nonempty(side.path, 4096) && count(side.spine_index),
      ),
  );
}

function editionCandidates(value: unknown) {
  return (
    Array.isArray(value) &&
    value.length <= 256 &&
    value.every(
      (item) =>
        record(item) &&
        nonempty(item.edition_id, 80) &&
        nullableText(item.work_id) &&
        nullableText(item.format) &&
        typeof item.disputed === "boolean",
    )
  );
}

function duplicateEvidence(value: unknown) {
  if (
    !record(value) ||
    typeof value.complete !== "boolean" ||
    !text(value.scope) ||
    ![
      "recorded_files",
      "resolved_files",
      "epub_files",
      "hashed",
      "different_size",
      "bytes_read",
      "unreadable_count",
    ].every((key) => value[key] === undefined || count(value[key])) ||
    typeof value.budget_exhausted !== "boolean" ||
    !Array.isArray(value.unreadable) ||
    !value.unreadable.every(
      (item) => record(item) && nonempty(item.book_id) && text(item.reason),
    )
  )
    return false;
  const exact = value.exact_bytes,
    same = value.same_work;
  if (
    !record(exact) ||
    !oneOf(exact.status, ["found", "none_found", "unconfirmed"]) ||
    !count(exact.count) ||
    typeof exact.truncated !== "boolean" ||
    !Array.isArray(exact.books) ||
    !exact.books.every(
      (item) =>
        record(item) &&
        nonempty(item.book_id) &&
        (item.format === undefined || nonempty(item.format)) &&
        digest(item.sha256),
    ) ||
    !record(same) ||
    !oneOf(same.status, ["possible", "unconfirmed"]) ||
    !count(same.count) ||
    typeof same.truncated !== "boolean" ||
    !Array.isArray(same.candidates) ||
    !same.candidates.every(
      (item) => record(item) && nonempty(item.book_id) && strings(item.basis),
    )
  )
    return false;
  const other = value.other_formats;
  if (
    other !== undefined &&
    (!record(other) ||
      !text(other.status) ||
      !text(other.byte_comparison) ||
      !count(other.count) ||
      typeof other.truncated !== "boolean" ||
      !Array.isArray(other.files) ||
      !other.files.every(
        (item) =>
          record(item) && nonempty(item.book_id) && nonempty(item.format),
      ))
  )
    return false;
  const content = value.content;
  if (
    content !== undefined &&
    (!record(content) ||
      content.clearance !== "unconfirmed" ||
      !text(content.scope) ||
      !text(content.limitations) ||
      !count(content.possible_count) ||
      !Array.isArray(content.comparisons) ||
      content.comparisons.length > 8 ||
      !content.comparisons.every(
        (item) =>
          record(item) &&
          comparisonPins([item.inspection]) &&
          oneOf(item.text_relation, ["same", "different", "unconfirmed"]) &&
          typeof item.exact_bytes === "boolean" &&
          oneOf(item.relationship, ["candidate", "same_native_origin"]) &&
          record(item.declared_work) &&
          text(item.declared_work.status) &&
          nonempty(item.declared_work.work_id, 80) &&
          record(item.declared_edition) &&
          text(item.declared_edition.status) &&
          nullableText(item.declared_edition.edition_id) &&
          editionCandidates(item.declared_edition.candidates) &&
          (item.resource_overlap === undefined ||
            overlap(item.resource_overlap)) &&
          (item.document_text_overlap === undefined ||
            overlap(item.document_text_overlap)),
      ))
  )
    return false;
  return true;
}

export const reconciliationIntentStorageKey = (
  version: string,
  sha256: string,
) => `librarium-reconcile-intent:${version}:${sha256}`;

export function readReconciliationIntent(
  version: string,
  sha256: string,
): ReconciliationIntent | null {
  try {
    const raw = localStorage.getItem(
      reconciliationIntentStorageKey(version, sha256),
    );
    const value: unknown = JSON.parse(raw ?? "null");
    if (
      reconciliationIntent(value) &&
      value.version === version &&
      value.sha256 === sha256
    ) {
      return value as ReconciliationIntent;
    }
  } catch {
    /* Storage may be unavailable */
  }
  return null;
}

export function saveReconciliationIntent(
  intent: ReconciliationIntent,
): boolean {
  try {
    localStorage.setItem(
      reconciliationIntentStorageKey(intent.version, intent.sha256),
      JSON.stringify(intent),
    );
    return true;
  } catch {
    return false;
  }
}

export function clearReconciliationIntent(
  version: string,
  sha256: string,
  key?: string,
) {
  try {
    const current = readReconciliationIntent(version, sha256);
    if (!key || current?.key === key) {
      localStorage.removeItem(reconciliationIntentStorageKey(version, sha256));
    }
  } catch {
    /* Retain in-memory state */
  }
}

export const assessmentIntentStorageKey = (sourceId: string) =>
  `librarium-book-assessment:${sourceId}`;

export function sameComparisonPins(
  left: ComparisonInspectionPin[],
  right: ComparisonInspectionPin[],
): boolean {
  return (
    left.length === right.length &&
    left.every(
      (item, index) =>
        item.job_id === right[index]?.job_id &&
        item.source_sha256 === right[index]?.source_sha256 &&
        item.report_sha256 === right[index]?.report_sha256,
    )
  );
}

export function sameReferencePin(
  left: ReferenceSelectionPin | null,
  right: ReferenceSelectionPin | null,
): boolean {
  if (!left || !right) return left === right;
  return (
    left.reference_id === right.reference_id &&
    left.registry_sha256 === right.registry_sha256 &&
    left.manifest_sha256 === right.manifest_sha256
  );
}

export function readAssessmentIntent(source: Job): AssessmentIntent | null {
  try {
    const raw = localStorage.getItem(assessmentIntentStorageKey(source.id));
    const value: unknown = JSON.parse(raw ?? "null");
    if (
      assessmentIntent(value) &&
      value.source_job_id === source.id &&
      value.source_sha256 === source.source_sha256 &&
      value.report_sha256 === source.result.report_sha256
    ) {
      return value as AssessmentIntent;
    }
  } catch {
    /* Storage may be unavailable */
  }
  return null;
}

export function saveAssessmentIntent(intent: AssessmentIntent): boolean {
  if (!assessmentIntent(intent)) return false;
  try {
    localStorage.setItem(
      assessmentIntentStorageKey(intent.source_job_id),
      JSON.stringify(intent),
    );
    return true;
  } catch {
    return false;
  }
}

export function clearAssessmentIntent(sourceId: string, key?: string) {
  try {
    const raw = localStorage.getItem(assessmentIntentStorageKey(sourceId));
    const parsed: unknown = JSON.parse(raw ?? "null");
    if (!key || (record(parsed) && parsed.key === key)) {
      localStorage.removeItem(assessmentIntentStorageKey(sourceId));
    }
  } catch {
    /* Retain in-memory state */
  }
}

export async function fetchSavedReconciliations(
  pin: CatalogueSnapshotPin,
  page = 1,
  signal?: AbortSignal,
): Promise<SavedReconciliationsPage> {
  const params = new URLSearchParams({
    version: pin.version,
    sha256: pin.sha256,
    page: String(page),
  });
  const result = await api<SavedReconciliationsPage>(
    `library/reconciliations?${params}`,
    { signal },
  );
  if (
    !record(result) ||
    result.page !== page ||
    result.page_size !== 24 ||
    !count(result.total) ||
    !count(result.pages) ||
    !Array.isArray(result.reports) ||
    result.reports.length > 24 ||
    !result.reports.every(
      (row) =>
        record(row) &&
        uuid(row.request_key) &&
        instant(row.created_at) &&
        snapshot(row.catalogue) &&
        row.catalogue.version === pin.version &&
        row.catalogue.sha256 === pin.sha256 &&
        record(row.inventory) &&
        digest(row.inventory.token) &&
        count(row.total) &&
        row.observation === "historical" &&
        row.ready === false &&
        row.duplicates === "not_assessed" &&
        row.file_identity === "not_assessed",
    )
  )
    throw new Error(
      "Saved reconciliation history did not match the selected catalogue.",
    );
  return result;
}

export async function fetchDirectLibraryInventory(
  signal?: AbortSignal,
): Promise<ReconciliationInventoryPin> {
  const response = await api<{ inventory: ReconciliationInventoryPin }>(
    "direct-library?page=1",
    { signal },
  );
  if (
    !response?.inventory ||
    typeof response.inventory.token !== "string" ||
    !DIGEST_PATTERN.test(response.inventory.token)
  ) {
    throw new Error(
      "The direct library inventory token could not be verified.",
    );
  }
  return response.inventory;
}

export async function requestReconciliationJob({
  csrf,
  intent,
  signal,
}: {
  csrf: string;
  intent: ReconciliationIntent;
  signal?: AbortSignal;
}): Promise<Job> {
  if (!reconciliationIntent(intent))
    throw new Error(
      "Choose exact saved reconciliation inputs before requesting a check.",
    );
  const body: Record<string, unknown> = {
    version: intent.version,
    sha256: intent.sha256,
    inventory: {
      token: intent.inventory_token,
      ...(intent.library_uuid ? { library_uuid: intent.library_uuid } : {}),
    },
  };
  if (intent.previous) body.previous = intent.previous;
  const job = await api<Job>("library/reconciliation-jobs", {
    method: "POST",
    headers: {
      "X-CSRFToken": csrf,
      "Idempotency-Key": intent.key,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (
    !baseJob(job, "library_reconcile") ||
    job.request_key !== intent.key ||
    job.catalogue_version !== intent.version ||
    job.catalogue_sha256 !== intent.sha256 ||
    !record(job.result)
  ) {
    throw new Error(
      "The returned reconciliation job did not match the requested key.",
    );
  }
  return job;
}

export async function recoverReconciliationJob(
  requestKey: string,
  signal?: AbortSignal,
): Promise<Job> {
  const job = await api<Job>(
    `library/reconciliation-jobs?request_key=${encodeURIComponent(requestKey)}`,
    { signal },
  );
  if (
    !baseJob(job, "library_reconcile") ||
    job.request_key !== requestKey ||
    !record(job.result)
  ) {
    throw new Error(
      "The recovered reconciliation job did not match the requested key.",
    );
  }
  return job;
}

export async function fetchReconciliationJobHistory(
  page = 1,
  signal?: AbortSignal,
): Promise<CheckJobHistoryPage> {
  const result: unknown = await api(
    `library/reconciliation-jobs?page=${page}`,
    { signal },
  );
  if (!historyPage(result, page, "library_reconcile"))
    throw new Error("Reconciliation history could not be verified.");
  return result;
}

export async function fetchContentReferences(
  pin: CatalogueSnapshotPin,
  workId: string,
  signal?: AbortSignal,
): Promise<ContentReferenceDiscovery> {
  const params = new URLSearchParams({
    version: pin.version,
    sha256: pin.sha256,
    work: workId,
  });
  const discovery = await api<ContentReferenceDiscovery>(
    `content-trust/references?${params}`,
    { signal },
  );
  if (
    !discovery ||
    discovery.policy_version !== "librarium.content-trust-discovery.v1" ||
    !["available", "not_configured", "unavailable"].includes(
      discovery.status,
    ) ||
    !discovery.catalogue ||
    discovery.catalogue.version !== pin.version ||
    discovery.catalogue.sha256 !== pin.sha256 ||
    discovery.catalogue.work_id !== workId ||
    !Array.isArray(discovery.references) ||
    discovery.references.length > 64 ||
    !strings(discovery.reason_codes) ||
    !(discovery.status === "available"
      ? digest(discovery.registry_sha256)
      : discovery.registry_sha256 === null &&
        discovery.references.length === 0) ||
    new Set(discovery.references.map((item) => item.reference_id)).size !==
      discovery.references.length ||
    !discovery.references.every(
      (item) =>
        record(item) &&
        nonempty(item.reference_id, 80) &&
        digest(item.manifest_sha256) &&
        nonempty(item.authority_id, 80) &&
        record(item.artifact) &&
        digest(item.artifact.sha256) &&
        count(item.artifact.size) &&
        item.artifact.size > 0 &&
        item.artifact.format === "epub" &&
        publication(item.publication) &&
        item.publication.work_id === workId &&
        claims(item.claims),
    )
  ) {
    throw new Error(
      "The curated reference discovery response did not match the selected catalogue work.",
    );
  }
  return discovery;
}

export function assessmentJobBinds(
  source: Job,
  job: Job | CheckHistoryJob,
): boolean {
  if (
    source.kind !== "epub" ||
    source.state !== "succeeded" ||
    !digest(source.source_sha256) ||
    !digest(source.result?.report_sha256) ||
    !baseJob(job, "book_assessment")
  )
    return false;
  const expected = {
    source_job_id: source.id,
    source_sha256: source.source_sha256,
    source_report_sha256: source.result.report_sha256,
  };
  if (
    Object.entries(expected).some(([key, value]) => {
      const actual = (job as unknown as Record<string, unknown>)[key];
      return actual != null && actual !== value;
    })
  )
    return false;
  if (
    job.source_job_id === source.id &&
    job.source_sha256 === source.source_sha256 &&
    job.source_report_sha256 === source.result.report_sha256
  )
    return true;
  return (
    job.state === "succeeded" &&
    "result" in job &&
    record(job.result) &&
    job.result.job_id === source.id &&
    job.result.source_sha256 === source.source_sha256 &&
    job.result.report_sha256 === source.result.report_sha256
  );
}

export function extractAssessmentReport(
  source: Job,
  job: Job,
): BookAssessmentReport | null {
  if (
    !assessmentJobBinds(source, job) ||
    job.state !== "succeeded" ||
    !record(job.result)
  )
    return null;
  const r = job.result;
  if (
    !oneOf(
      r.policy_version,
      [1, 2, 3, 4, 5, 6].map((n) => `librarium.book-assessment.v${n}`),
    ) ||
    r.schema_version !== r.policy_version ||
    r.job_id !== source.id ||
    r.source_sha256 !== source.source_sha256 ||
    r.report_sha256 !== source.result.report_sha256 ||
    !snapshot(r.catalogue) ||
    !uuid(r.reconciliation_key) ||
    !record(r.inventory) ||
    !digest(r.inventory.token) ||
    !instant(r.assessed_at) ||
    r.observation !== "historical" ||
    !text(r.scope) ||
    !duplicateEvidence(r.duplicates)
  )
    return null;
  const work = r.file_work_identity,
    edition = r.edition_identity,
    current = r.current_library_bytes;
  const statuses = ["supported", "ambiguous", "conflicting", "unconfirmed"];
  if (
    !record(work) ||
    !oneOf(work.status, statuses) ||
    !nonempty(work.work_id, 80) ||
    !text(work.basis) ||
    !record(work.title) ||
    !text(work.title.status) ||
    !record(work.creators) ||
    !text(work.creators.status) ||
    !record(work.isbn) ||
    !text(work.isbn.status) ||
    !text(work.content_authentication) ||
    !record(edition) ||
    !oneOf(edition.status, statuses) ||
    !nullableText(edition.edition_id) ||
    !editionCandidates(edition.candidates) ||
    !text(edition.basis) ||
    !text(edition.language_and_content_equivalence) ||
    !record(current) ||
    !oneOf(current.status, [
      "same_bytes",
      "different_bytes",
      "changed_during_scan",
      "not_applicable",
      "unconfirmed",
    ]) ||
    !nullableDigest(current.observed_sha256)
  )
    return null;
  if (
    (job.catalogue_version != null &&
      job.catalogue_version !== r.catalogue.version) ||
    (job.catalogue_sha256 != null &&
      job.catalogue_sha256 !== r.catalogue.sha256) ||
    (job.catalogue_work_id != null && job.catalogue_work_id !== work.work_id) ||
    (job.reconciliation_key != null &&
      job.reconciliation_key !== r.reconciliation_key)
  )
    return null;
  if (
    r.source_provenance !== undefined &&
    (!record(r.source_provenance) ||
      !oneOf(r.source_provenance.kind, ["native_library", "incoming_upload"]))
  )
    return null;
  if (r.source_attribution != null) {
    const attribution = r.source_attribution;
    if (
      !record(attribution) ||
      attribution.job_id !== source.id ||
      attribution.source_sha256 !== source.source_sha256 ||
      attribution.report_sha256 !== source.result.report_sha256 ||
      !record(attribution.catalogue) ||
      attribution.catalogue.version !== r.catalogue.version ||
      attribution.catalogue.sha256 !== r.catalogue.sha256 ||
      attribution.catalogue.work_id !== work.work_id ||
      !oneOf(attribution.status, [
        "corroborated",
        "conflicting",
        "ambiguous",
        "unconfirmed",
      ]) ||
      !strings(attribution.observation_ids)
    )
      return null;
  }
  if (r.policy_version === "librarium.book-assessment.v6") {
    const selected = (job as unknown as Record<string, unknown>).reference;
    if (
      selected === undefined ||
      !authentication(
        r.reference_authentication,
        source,
        r.catalogue,
        work.work_id,
        selected,
      )
    )
      return null;
  } else if (r.reference_authentication !== undefined) return null;
  return r as unknown as BookAssessmentReport;
}

export async function requestCandidateAssessment({
  source,
  csrf,
  intent,
  signal,
}: {
  source: Job;
  csrf: string;
  intent: AssessmentIntent;
  signal?: AbortSignal;
}): Promise<Job> {
  if (
    !assessmentIntent(intent) ||
    intent.source_job_id !== source.id ||
    intent.source_sha256 !== source.source_sha256 ||
    intent.report_sha256 !== source.result.report_sha256
  )
    throw new Error(
      "Choose an exact intent for this preserved source before requesting a check.",
    );
  const payload: Record<string, unknown> = {
    version: intent.version,
    sha256: intent.sha256,
    catalogue_work_id: intent.catalogue_work_id,
    source_sha256: intent.source_sha256,
    report_sha256: intent.report_sha256,
    reconciliation: intent.reconciliation,
  };
  if (intent.comparison_inspections.length > 0) {
    payload.comparison_inspections = intent.comparison_inspections;
  }
  if (intent.reference) {
    payload.reference = intent.reference;
  }
  const job = await api<Job>(
    `epub-inspections/${encodeURIComponent(source.id)}/checks`,
    {
      method: "POST",
      headers: {
        "X-CSRFToken": csrf,
        "Idempotency-Key": intent.key,
      },
      body: JSON.stringify(payload),
      signal,
    },
  );
  const selected = (job as unknown as Record<string, unknown>).reference;
  if (
    !assessmentJobBinds(source, job) ||
    job.request_key !== intent.key ||
    job.catalogue_version !== intent.version ||
    job.catalogue_sha256 !== intent.sha256 ||
    job.catalogue_work_id !== intent.catalogue_work_id ||
    job.reconciliation_key !== intent.reconciliation ||
    !(intent.reference === null
      ? selected === null
      : referencePin(selected) &&
        sameReferencePin(selected, intent.reference)) ||
    !record(job.result) ||
    (job.state === "succeeded" && !extractAssessmentReport(source, job))
  ) {
    throw new Error(
      "The returned candidate assessment did not match this preserved source and request.",
    );
  }
  return job;
}

export async function recoverCandidateAssessment(
  source: Job,
  requestKey: string,
  signal?: AbortSignal,
): Promise<Job> {
  const job = await api<Job>(
    `epub-inspections/${encodeURIComponent(source.id)}/checks?request_key=${encodeURIComponent(requestKey)}`,
    { signal },
  );
  if (
    !assessmentJobBinds(source, job) ||
    job.request_key !== requestKey ||
    !record(job.result) ||
    (job.state === "succeeded" && !extractAssessmentReport(source, job))
  ) {
    throw new Error(
      "The recovered candidate assessment did not match this preserved source and request.",
    );
  }
  return job;
}

export async function fetchCandidateAssessmentHistory(
  source: Job,
  page = 1,
  signal?: AbortSignal,
): Promise<CheckJobHistoryPage> {
  const result = await api<CheckJobHistoryPage>(
    `epub-inspections/${encodeURIComponent(source.id)}/checks?page=${page}`,
    {
      signal,
    },
  );
  if (
    !historyPage(result, page, "book_assessment") ||
    !result.jobs.every((job) => assessmentJobBinds(source, job))
  ) {
    throw new Error(
      "The candidate assessment history did not match this preserved source.",
    );
  }
  return result;
}
