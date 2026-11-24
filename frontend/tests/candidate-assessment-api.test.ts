// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Job } from "../src/types";
import {
  assessmentJobBinds,
  assessmentIntentStorageKey,
  extractAssessmentReport,
  fetchCandidateAssessmentHistory,
  fetchContentReferences,
  readAssessmentIntent,
  requestCandidateAssessment,
  type AssessmentIntent,
} from "../src/candidate-assessment-api";

import {
  assessmentCatalogueFixture as pin,
  assessmentSourceFixture as source,
  assessmentReferenceFixture as reference,
  assessmentIntentFixture,
  assessmentResultFixture,
  assessmentJobFixture,
} from "./assessment-fixtures";
const intent = assessmentIntentFixture();
const result = (policy = 6) => assessmentResultFixture({ policy });
const job = (report = result()) => assessmentJobFixture({}, { result: report });
const reply = (value: unknown) =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(value))),
  );
beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

it("reads the real v6 claims array and original flat publication pin", () => {
  const read = extractAssessmentReport(source, job());
  expect(read?.reference_authentication?.claims).toEqual([
    "work_identity",
    "edition_identity",
  ]);
  expect(read?.reference_authentication?.reference_publication).toMatchObject({
    catalogue_version: "2026.10.28.1",
  });
});
it.each([1, 2, 3, 4, 5])(
  "keeps historical v%i absence without adding authentication",
  (policy) => {
    const report = result(policy);
    delete report.source_provenance;
    delete (report.duplicates as Record<string, unknown>).content;
    delete (report.duplicates as Record<string, unknown>).other_formats;
    expect(
      extractAssessmentReport(source, job(report))?.reference_authentication,
    ).toBeUndefined();
    expect(extractAssessmentReport(source, job(report))).not.toBeNull();
  },
);
it.each([
  { claims: { work_identity: "supported" } },
  { claims: ["work_identity", "invented_claim"] },
  { source_sha256: "0".repeat(64) },
  { catalogue: { ...pin, work_id: "w_other" } },
  { reference_sha256: "0".repeat(64) },
  { manifest_sha256: "0".repeat(64) },
  { reference_publication: { catalogue: pin, work_id: "w_fixture" } },
])("refuses malformed or rebound v6 authentication %j", (change) => {
  const report = result();
  report.reference_authentication = {
    ...(report.reference_authentication as object),
    ...change,
  };
  expect(extractAssessmentReport(source, job(report))).toBeNull();
});
it("requires positive source binding for sparse jobs", () => {
  const sparse = {
    ...job(),
    source_job_id: undefined,
    source_report_sha256: undefined,
    source_sha256: undefined,
    result: {},
    state: "queued",
  };
  expect(assessmentJobBinds(source, sparse)).toBe(false);
  expect(
    assessmentJobBinds(source, {
      ...sparse,
      state: "succeeded",
      result: result(4),
    }),
  ).toBe(true);
});
it("refuses a saved result whose current catalogue or reconciliation differs from captured job fields", () => {
  expect(
    extractAssessmentReport(source, {
      ...job(),
      catalogue_sha256: "0".repeat(64),
    }),
  ).toBeNull();
  expect(
    extractAssessmentReport(source, {
      ...job(),
      reconciliation_key: "44444444-4444-4444-8444-444444444444",
    }),
  ).toBeNull();
});
it.each([
  { comparison_inspections: [{}] },
  { reference: { ...reference, authority_id: "self-nominated" } },
  {
    comparison_inspections: [
      {
        job_id: "comparison",
        source_sha256: "bad",
        report_sha256: "b".repeat(64),
      },
    ],
  },
])("refuses malformed persisted intent %j", (change) => {
  localStorage.setItem(
    assessmentIntentStorageKey(source.id),
    JSON.stringify({ ...intent, ...change }),
  );
  expect(readAssessmentIntent(source)).toBeNull();
});
it("accepts summary-only source-bound history and sends explicit page", async () => {
  const { result: _result, ...summary } = job();
  reply({
    jobs: [
      {
        ...summary,
        result_summary: {
          policy_version: "librarium.book-assessment.v6",
          reference_authentication: "authenticated_reference_match",
          exact_bytes: "none_found",
          assessed_at: "2026-10-30T01:00:00Z",
          error_code: null,
        },
      },
    ],
    page: 2,
    page_size: 24,
    total: 25,
    pages: 2,
  });
  expect((await fetchCandidateAssessmentHistory(source, 2)).jobs).toHaveLength(
    1,
  );
  expect(vi.mocked(fetch).mock.calls[0][0]).toContain("?page=2");
});
it("refuses history with a full result or a different requested page", async () => {
  reply({ jobs: [job()], page: 1, page_size: 24, total: 1, pages: 1 });
  await expect(fetchCandidateAssessmentHistory(source)).rejects.toThrow();
  reply({ jobs: [], page: 1, page_size: 24, total: 25, pages: 2 });
  await expect(fetchCandidateAssessmentHistory(source, 2)).rejects.toThrow();
});
function discovery() {
  return {
    policy_version: "librarium.content-trust-discovery.v1",
    status: "available",
    catalogue: { ...pin, work_id: "w_fixture" },
    registry_sha256: reference.registry_sha256,
    references: [
      {
        reference_id: reference.reference_id,
        manifest_sha256: reference.manifest_sha256,
        authority_id: "fixture.authority",
        artifact: { sha256: source.source_sha256, size: 42, format: "epub" },
        publication: {
          work_id: "w_fixture",
          edition_id: null,
          language: null,
          revision: null,
          scope: "standalone_work",
        },
        claims: ["work_identity"],
      },
    ],
    reason_codes: [],
  };
}
it("reads real metadata discovery and refuses invalid advertised reference pins", async () => {
  const data = discovery();
  reply(data);
  expect(
    (await fetchContentReferences(pin, "w_fixture")).references[0].publication
      .scope,
  ).toBe("standalone_work");
  data.references[0].manifest_sha256 = "not-a-digest";
  reply(data);
  await expect(fetchContentReferences(pin, "w_fixture")).rejects.toThrow();
});
it("refuses a request whose local intent belongs to another source before POST", async () => {
  reply(job());
  await expect(
    requestCandidateAssessment({
      source,
      csrf: "fixture",
      intent: { ...intent, source_job_id: "another" },
    }),
  ).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
it("checks returned captured reference selection after POST", async () => {
  reply({
    ...job(),
    reference: { ...reference, manifest_sha256: "0".repeat(64) },
  });
  await expect(
    requestCandidateAssessment({ source, csrf: "fixture", intent }),
  ).rejects.toThrow();
});
it("reads a saved assessment with or without the retired correction-admission fields", () => {
  const withFields = result();
  expect(withFields).toHaveProperty("correction_admission");
  expect(extractAssessmentReport(source, job(withFields))).not.toBeNull();
  const without: Record<string, unknown> = { ...result() };
  delete without.correction_admission;
  delete without.blockers;
  delete without.ready;
  expect(extractAssessmentReport(source, job(without as never))).not.toBeNull();
});
