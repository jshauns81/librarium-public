// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CandidateAssessment } from "../src/CandidateAssessment";
import { api } from "../src/api";
import * as checks from "../src/candidate-assessment-api";
import type { Job } from "../src/types";

vi.mock("../src/api", async (original) => ({
  ...(await original<typeof import("../src/api")>()),
  api: vi.fn(),
}));
vi.mock("../src/candidate-assessment-api", async (original) => ({
  ...(await original<typeof import("../src/candidate-assessment-api")>()),
  fetchSavedReconciliations: vi.fn(),
  fetchReconciliationJobHistory: vi.fn(),
  fetchCandidateAssessmentHistory: vi.fn(),
  fetchContentReferences: vi.fn(),
  extractAssessmentReport: vi.fn(() => null),
}));

const pin = { version: "2026.10.29.1", sha256: "c".repeat(64), fixture: true };
const source: Job = {
  id: "source",
  kind: "epub",
  request_key: "11111111-1111-4111-8111-111111111111",
  work_id: "source",
  title: "Synthetic source",
  state: "succeeded",
  revision: 4,
  checkpoint: 4,
  attempts: 1,
  updated_at: "2026-10-29T12:00:00Z",
  message: "Saved source",
  source_sha256: "a".repeat(64),
  source_version: "librarium.epub-structure.v8",
  input_fingerprint: "f".repeat(64),
  result: { ready: false, report_sha256: "b".repeat(64) },
};
const key = "22222222-2222-4222-8222-222222222222";
const record = {
  request_key: key,
  created_at: "2026-10-29T12:00:00Z",
  catalogue: pin,
  inventory: { token: "d".repeat(64) },
  total: 2,
  observation: "historical" as const,
  file_identity: "not_assessed" as const,
  duplicates: "not_assessed" as const,
  ready: false as const,
};
const job: Job = {
  ...source,
  id: "check",
  kind: "book_assessment",
  source_job_id: source.id,
  source_report_sha256: source.result.report_sha256,
  catalogue_work_id: "w_fixture",
  catalogue_version: pin.version,
  catalogue_sha256: pin.sha256,
  reconciliation_key: key,
  title: "Saved assessment",
  message: "Full saved check",
  result: { ready: false },
};
let client: QueryClient;
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  vi.mocked(checks.fetchSavedReconciliations).mockResolvedValue({
    reports: [record],
    page: 1,
    page_size: 24,
    total: 1,
    pages: 1,
  });
  vi.mocked(checks.fetchReconciliationJobHistory).mockResolvedValue({
    jobs: [],
    page: 1,
    page_size: 24,
    total: 0,
    pages: 1,
  });
  vi.mocked(checks.fetchCandidateAssessmentHistory).mockResolvedValue({
    jobs: [],
    page: 1,
    page_size: 24,
    total: 0,
    pages: 1,
  });
  vi.mocked(checks.fetchContentReferences).mockResolvedValue({
    policy_version: "librarium.content-trust-discovery.v1",
    status: "not_configured",
    catalogue: {
      version: pin.version,
      sha256: pin.sha256,
      work_id: "w_fixture",
    },
    registry_sha256: null,
    references: [],
    reason_codes: ["trust_not_configured"],
  });
  vi.mocked(api).mockResolvedValue(job);
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
});
function view(assessmentId = "", onJob = vi.fn()) {
  return (
    <QueryClientProvider client={client}>
      <CandidateAssessment
        source={source}
        pin={pin}
        work={{ id: "w_fixture", title: "Synthetic work" }}
        session={{ csrf: "fixture", direct_library: true }}
        assessmentId={assessmentId}
        onJob={onJob}
      />
    </QueryClientProvider>
  );
}
it("requires an explicit saved reconciliation choice before enabling assessment", async () => {
  render(view());
  const choice = await screen.findByRole("radio");
  expect((choice as HTMLInputElement).checked).toBe(false);
  const run = screen.getByRole("button", { name: "Run candidate assessment" });
  expect((run as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(choice);
  expect((run as HTMLButtonElement).disabled).toBe(false);
});
it("does not silently open the first historical assessment", async () => {
  vi.mocked(checks.fetchCandidateAssessmentHistory).mockResolvedValue({
    jobs: [
      {
        ...job,
        result_summary: {
          policy_version: "librarium.book-assessment.v6",
          error_code: null,
        },
      },
    ],
    page: 1,
    page_size: 24,
    total: 1,
    pages: 1,
  });
  render(view());
  await screen.findByRole("button", { name: /Saved assessment/ });
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(api).not.toHaveBeenCalled();
});
it("loads full detail instead of treating a history summary as a saved result", async () => {
  const { result: _result, ...summary } = job;
  vi.mocked(checks.fetchCandidateAssessmentHistory).mockResolvedValue({
    jobs: [
      {
        ...summary,
        result_summary: {
          policy_version: "librarium.book-assessment.v6",
          error_code: null,
        },
      },
    ],
    page: 1,
    page_size: 24,
    total: 1,
    pages: 1,
  });
  const onJob = vi.fn();
  render(view(job.id, onJob));
  await waitFor(() => expect(onJob).toHaveBeenCalledWith(job));
  expect(checks.extractAssessmentReport).toHaveBeenCalledWith(source, job);
});
it("makes older saved reconciliation pages reachable", async () => {
  vi.mocked(checks.fetchSavedReconciliations).mockResolvedValue({
    reports: [record],
    page: 1,
    page_size: 24,
    total: 25,
    pages: 2,
  });
  render(view());
  fireEvent.click(
    await screen.findByRole("button", { name: "Next reconciliation page" }),
  );
  await waitFor(() =>
    expect(checks.fetchSavedReconciliations).toHaveBeenCalledWith(
      pin,
      2,
      expect.any(AbortSignal),
    ),
  );
});
it("does not replace the newer reconciliation-history choice with a late read", async () => {
  const first: Job = {
    ...job,
    id: "rec-a",
    kind: "library_reconcile",
    source_version: pin.version,
    source_sha256: pin.sha256,
    title: "Coverage A",
    message: "Older coverage opened",
  };
  const second: Job = {
    ...first,
    id: "rec-b",
    title: "Coverage B",
    message: "Newer coverage opened",
  };
  const row = (value: Job) => ({
    ...value,
    result_summary: {
      policy_version: "librarium.library-reconciliation.v1",
      error_code: null,
    },
  });
  vi.mocked(checks.fetchReconciliationJobHistory).mockResolvedValue({
    jobs: [row(first), row(second)],
    page: 1,
    page_size: 24,
    total: 2,
    pages: 1,
  });
  let completeA: ((job: Job) => void) | undefined;
  let completeB: ((job: Job) => void) | undefined;
  vi.mocked(api).mockImplementation(
    (route) =>
      new Promise((resolve) => {
        if (route.endsWith(first.id)) completeA = resolve;
        else completeB = resolve;
      }),
  );
  render(view());
  fireEvent.click(await screen.findByText("Reconciliation request history"));
  fireEvent.click(screen.getByRole("button", { name: /Coverage A/ }));
  fireEvent.click(screen.getByRole("button", { name: /Coverage B/ }));
  await waitFor(() => expect(completeB).toBeDefined());
  completeB!(second);
  await screen.findByText("Newer coverage opened");
  completeA!(first);
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(screen.queryByText("Older coverage opened")).toBeNull();
});
