import type { Job } from "../src/types";
import type {
  AssessmentIntent,
  CatalogueSnapshotPin,
  ReferenceSelectionPin,
} from "../src/candidate-assessment-api";

export const assessmentCatalogueFixture = {
  version: "2026.10.29.1",
  sha256: "c".repeat(64),
  fixture: true,
};
export const assessmentSourceFixture: Job = {
  id: "source-1",
  kind: "epub",
  state: "succeeded",
  request_key: "11111111-1111-4111-8111-111111111111",
  work_id: "a".repeat(64),
  source_sha256: "a".repeat(64),
  source_version: "librarium.epub-structure.v8",
  title: "Preserved fixture",
  message: "Saved",
  revision: 4,
  checkpoint: 4,
  attempts: 1,
  updated_at: "2026-10-30T01:00:00Z",
  input_fingerprint: "d".repeat(64),
  result: { report_sha256: "b".repeat(64) },
};
export const assessmentReferenceFixture = {
  reference_id: "fixture.reference",
  registry_sha256: "e".repeat(64),
  manifest_sha256: "f".repeat(64),
};

export type AssessmentFixtureOptions = {
  source?: Job;
  catalogue?: CatalogueSnapshotPin;
  workId?: string;
  reconciliationKey?: string;
  reference?: ReferenceSelectionPin | null;
  policy?: number;
};
export function assessmentIntentFixture(
  options: AssessmentFixtureOptions = {},
): AssessmentIntent {
  const source = options.source ?? assessmentSourceFixture;
  const pin = options.catalogue ?? assessmentCatalogueFixture;
  return {
    key: "22222222-2222-4222-8222-222222222222",
    source_job_id: source.id,
    source_sha256: source.source_sha256!,
    report_sha256: source.result.report_sha256!,
    version: pin.version,
    sha256: pin.sha256,
    catalogue_work_id: options.workId ?? "w_fixture",
    reconciliation:
      options.reconciliationKey ?? "33333333-3333-4333-8333-333333333333",
    comparison_inspections: [],
    reference:
      options.reference === undefined
        ? assessmentReferenceFixture
        : options.reference,
  };
}
export function assessmentResultFixture(
  options: AssessmentFixtureOptions = {},
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const source = options.source ?? assessmentSourceFixture;
  const pin = options.catalogue ?? assessmentCatalogueFixture;
  const workId = options.workId ?? "w_fixture";
  const intent = assessmentIntentFixture(options);
  const policy = options.policy ?? 6;
  const reference =
    options.reference === undefined
      ? assessmentReferenceFixture
      : options.reference;
  return {
    schema_version: `librarium.book-assessment.v${policy}`,
    policy_version: `librarium.book-assessment.v${policy}`,
    job_id: source.id,
    source_sha256: source.source_sha256,
    report_sha256: source.result.report_sha256,
    catalogue: pin,
    reconciliation_key: intent.reconciliation,
    inventory: { token: "9".repeat(64), library_uuid: "fixture-library" },
    library_origin: null,
    source_provenance: { kind: "incoming_upload" },
    assessed_at: "2026-10-30T01:00:00Z",
    observation: "historical",
    file_work_identity: {
      status: "unconfirmed",
      work_id: workId,
      basis: "preserved_package_declarations",
      title: {
        status: "same",
        epub: ["Fixture title"],
        catalogue: "Fixture title",
      },
      creators: {
        status: "same",
        epub: ["Fixture Author"],
        catalogue: [{ id: "a_fixture", name: "Fixture Author" }],
        matches: [],
        missing_authors: [],
      },
      isbn: {
        status: "unknown",
        capture: "recorded",
        entries: [],
        scope: "Declared ISBN evidence",
      },
      content_authentication: "not_assessed",
    },
    edition_identity: {
      status: "unconfirmed",
      edition_id: null,
      candidates: [],
      basis: "unambiguous_explicit_epub_edition",
      language_and_content_equivalence: "not_assessed",
    },
    current_library_bytes: { status: "not_applicable", observed_sha256: null },
    duplicates: {
      complete: true,
      scope: "all_recorded_formats",
      recorded_files: 0,
      resolved_files: 0,
      epub_files: 0,
      other_formats: {
        status: "unconfirmed",
        byte_comparison: "complete",
        count: 0,
        files: [],
        truncated: false,
      },
      hashed: 0,
      different_size: 0,
      budget_exhausted: false,
      bytes_read: 0,
      unreadable: [],
      unreadable_count: 0,
      exact_bytes: {
        status: "none_found",
        count: 0,
        books: [],
        truncated: false,
      },
      same_work: {
        status: "unconfirmed",
        count: 0,
        candidates: [],
        truncated: false,
      },
      content: {
        scope: "explicit_preserved_inspections",
        clearance: "unconfirmed",
        comparisons: [],
        possible_count: 0,
        limitations: "Source fingerprints only",
      },
    },
    blockers: [
      ...(policy < 6 || !reference ? ["content_identity_unconfirmed"] : []),
      "semantic_duplicates_unconfirmed",
      "writer_not_authorized",
    ],
    correction_admission: "held",
    ready: false,
    scope: "Historical observation",
    ...(policy === 6
      ? {
          reference_authentication: {
            schema_version: "librarium.content-reference-authentication.v1",
            status: reference
              ? "authenticated_reference_match"
              : "not_requested",
            reason_codes: reference ? [] : ["reference_not_pinned"],
            source_sha256: source.source_sha256,
            report_sha256: source.result.report_sha256,
            catalogue: {
              version: pin.version,
              sha256: pin.sha256,
              work_id: workId,
            },
            reference_id: reference?.reference_id ?? null,
            registry_sha256: reference?.registry_sha256 ?? null,
            manifest_sha256: reference?.manifest_sha256 ?? null,
            reference_sha256: reference ? source.source_sha256 : null,
            authority_id: reference ? "fixture.authority" : null,
            checked_at: "2026-10-30T01:00:00Z",
            claims: reference ? ["work_identity", "edition_identity"] : [],
            observation: "historical",
            reference_publication: reference
              ? {
                  catalogue_version: "2026.10.28.1",
                  catalogue_sha256: "8".repeat(64),
                  work_id: workId,
                  edition_id: "e_fixture",
                  language: null,
                  revision: null,
                  scope: "standalone_work",
                }
              : null,
          },
        }
      : {}),
    ...overrides,
  };
}

export function assessmentJobFixture(
  options: AssessmentFixtureOptions = {},
  overrides: Partial<Job> = {},
): Job {
  const source = options.source ?? assessmentSourceFixture;
  const pin = options.catalogue ?? assessmentCatalogueFixture;
  const intent = assessmentIntentFixture(options);
  return {
    ...source,
    kind: "book_assessment",
    source_version: pin.version,
    id: "assessment-1",
    request_key: intent.key,
    source_job_id: source.id,
    source_report_sha256: source.result.report_sha256,
    catalogue_version: pin.version,
    catalogue_sha256: pin.sha256,
    catalogue_work_id: intent.catalogue_work_id,
    reconciliation_key: intent.reconciliation,
    reference: intent.reference,
    result: assessmentResultFixture(options),
    ...overrides,
  } as Job;
}
