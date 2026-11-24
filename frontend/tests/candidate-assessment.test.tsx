// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import {
  CandidateAssessment,
  ResumedAssessment,
} from "../src/CandidateAssessment";
import { PackageComparison } from "../src/PackageComparison";
import {
  BookWorkspaceContext,
  emptyWorkspaceSelection,
} from "../src/book-workspace";
import {
  readAssessmentIntent,
  saveAssessmentIntent,
} from "../src/candidate-assessment-api";
import type { Job } from "../src/types";
import {
  assessmentCatalogueFixture as pin,
  assessmentSourceFixture as source,
  assessmentReferenceFixture as reference,
  assessmentJobFixture,
  assessmentIntentFixture,
} from "./assessment-fixtures";

const reconciliation = "33333333-3333-4333-8333-333333333333";
let client: QueryClient;
let jobs: Job[];
let calls: { url: URL; init: RequestInit }[];
let intercept: (url: URL, init: RequestInit) => Promise<Response> | undefined;
const json = (value: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(value), { status }));
const summary = (job: Job) => {
  const { result, ...fields } = job;
  return {
    ...fields,
    result_summary: {
      policy_version: result.policy_version,
      error_code: null,
      assessed_at: result.assessed_at,
      reference_authentication: "not_requested",
      exact_bytes: "none_found",
    },
  };
};
const saved = {
  request_key: reconciliation,
  created_at: "2026-10-30T01:00:00Z",
  catalogue: pin,
  inventory: { token: "9".repeat(64), library_uuid: "fixture-library" },
  counts: { matched: 1, unmatched: 0, ambiguous: 0, disagreement: 0, held: 0 },
  total: 1,
  observation: "historical",
  ready: false,
  file_identity: "not_assessed",
  duplicates: "not_assessed",
};
const options = {
  source,
  catalogue: pin,
  workId: "w_fixture",
  reconciliationKey: reconciliation,
  reference: null,
};
beforeEach(() => {
  localStorage.clear();
  calls = [];
  jobs = [];
  intercept = () => undefined;
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(input, location.origin);
      calls.push({ url, init });
      const custom = intercept(url, init);
      if (custom) return custom;
      if (url.pathname === "/api/library/reconciliations")
        return json({
          reports: [saved],
          page: 1,
          page_size: 24,
          total: 1,
          pages: 1,
        });
      if (url.pathname === "/api/library/reconciliation-jobs")
        return json({ jobs: [], page: 1, page_size: 24, total: 0, pages: 1 });
      if (url.pathname === "/api/content-trust/references")
        return json({
          policy_version: "librarium.content-trust-discovery.v1",
          status: "available",
          catalogue: { ...pin, work_id: "w_fixture" },
          registry_sha256: reference.registry_sha256,
          references: [
            {
              ...reference,
              authority_id: "fixture.authority",
              artifact: {
                sha256: source.source_sha256,
                size: 2000,
                format: "epub",
              },
              publication: {
                work_id: "w_fixture",
                edition_id: "e_fixture",
                language: null,
                revision: null,
                scope: "standalone_work",
              },
              claims: ["work_identity", "edition_identity"],
            },
          ],
          reason_codes: [],
        });
      if (url.pathname.endsWith("/checks")) {
        if (init.method === "POST") {
          const body = JSON.parse(String(init.body));
          const job = assessmentJobFixture(
            { ...options, reference: body.reference ?? null },
            {
              id: `assessment-${jobs.length + 1}`,
              request_key: new Headers(init.headers).get("Idempotency-Key")!,
            },
          );
          jobs.unshift(job);
          return json(job, 202);
        }
        const key = url.searchParams.get("request_key");
        if (key) {
          const found = jobs.find((job) => job.request_key === key);
          return found ? json(found) : json({ error: "Not recorded" }, 404);
        }
        return json({
          jobs: jobs.map(summary),
          page: 1,
          page_size: 24,
          total: jobs.length,
          pages: 1,
        });
      }
      if (url.pathname.startsWith("/api/jobs/")) {
        const found = jobs.find(
          (job) => job.id === url.pathname.split("/").at(-1),
        );
        return found ? json(found) : json({ error: "Not found" }, 404);
      }
      throw new Error(`Unexpected fixture request: ${url.pathname}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function view(id = "", cancel = vi.fn(), comparisonJobs: Job[] = []) {
  return (
    <QueryClientProvider client={client}>
      <CandidateAssessment
        source={source}
        pin={pin}
        work={{ id: "w_fixture", title: "Synthetic work" }}
        session={{ csrf: "fixture", direct_library: true }}
        assessmentId={id}
        jobs={comparisonJobs}
        cancel={cancel}
      />
    </QueryClientProvider>
  );
}
async function chooseCoverage() {
  fireEvent.click(await screen.findByRole("radio"));
}
async function runCheck() {
  await chooseCoverage();
  fireEvent.click(
    screen.getByRole("button", { name: "Run candidate assessment" }),
  );
  await screen.findByText("Recorded candidate assessment");
}
it("keeps three recent reconciliation choices and the explicit older choice visible without changing selection or focus", async () => {
  const reports = Array.from({ length: 24 }, (_, index) => ({
    ...saved,
    request_key: `33333333-3333-4333-8333-${String(index + 1).padStart(12, "0")}`,
  }));
  const next = {
    ...saved,
    request_key: "33333333-3333-4333-8333-000000000025",
  };
  intercept = (url) =>
    url.pathname === "/api/library/reconciliations"
      ? json({
          reports: url.searchParams.get("page") === "2" ? [next] : reports,
          page: Number(url.searchParams.get("page")),
          page_size: 24,
          total: 25,
          pages: 2,
        })
      : undefined;
  render(view());
  await waitFor(() => expect(screen.getAllByRole("radio")).toHaveLength(3));
  expect(
    screen
      .getAllByRole("radio")
      .every((control) => !(control as HTMLInputElement).checked),
  ).toBe(true);
  const more = screen.getByRole("button", {
    name: /More saved reconciliations/,
  });
  expect(more.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(more);
  expect(screen.getAllByRole("radio")).toHaveLength(24);
  const older = screen.getByRole("radio", {
    name: new RegExp(reports[18].request_key),
  });
  act(() => older.focus());
  fireEvent.click(older);
  expect(document.activeElement).toBe(older);
  fireEvent.click(
    screen.getByRole("button", { name: /Fewer saved reconciliations/ }),
  );
  expect(screen.getAllByRole("radio")).toHaveLength(4);
  expect(
    screen.getByRole("radio", { name: new RegExp(reports[18].request_key) }),
  ).toBe(older);
  expect((older as HTMLInputElement).checked).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Next reconciliation page" }),
  );
  await screen.findByRole("radio", { name: new RegExp(next.request_key) });
  expect(
    screen.getByRole("radio", { name: new RegExp(reports[18].request_key) }),
  ).toBeTruthy();
  expect(screen.getByText("Selected from another page")).toBeTruthy();
  expect(
    screen.getAllByText(/1 library book · inventory/).length,
  ).toBeGreaterThan(0);
  expect(calls.some((call) => call.init.method === "POST")).toBe(false);
});

it("keeps older assessment choices focusable, selected and visible after collapsing or reopening an exact record", async () => {
  jobs = Array.from({ length: 25 }, (_, index) =>
    assessmentJobFixture(options, {
      id: `history-${index + 1}`,
      title: `Saved assessment ${index + 1}`,
    }),
  );
  intercept = (url, init) =>
    url.pathname.endsWith("/checks") &&
    init.method !== "POST" &&
    !url.searchParams.has("request_key")
      ? json({
          jobs: jobs
            .slice(
              (Number(url.searchParams.get("page")) - 1) * 24,
              Number(url.searchParams.get("page")) * 24,
            )
            .map(summary),
          page: Number(url.searchParams.get("page")),
          page_size: 24,
          total: 25,
          pages: 2,
        })
      : undefined;
  const rendered = render(view());
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: /Saved assessment/ }),
    ).toHaveLength(3),
  );
  fireEvent.click(
    screen.getByRole("button", { name: /More candidate assessments/ }),
  );
  expect(
    screen.getAllByRole("button", { name: /Saved assessment/ }),
  ).toHaveLength(24);
  const older = screen.getByRole("button", { name: /Saved assessment 19 / });
  act(() => older.focus());
  fireEvent.click(older);
  await screen.findByText("Recorded candidate assessment");
  expect(document.activeElement).toBe(older);
  expect(older.getAttribute("aria-current")).toBe("true");
  fireEvent.click(
    screen.getByRole("button", { name: /Fewer candidate assessments/ }),
  );
  expect(
    screen.getAllByRole("button", { name: /Saved assessment/ }),
  ).toHaveLength(4);
  expect(screen.getByRole("button", { name: /Saved assessment 19 / })).toBe(
    older,
  );
  fireEvent.click(screen.getByRole("button", { name: "Next assessment page" }));
  await screen.findByRole("button", { name: /Saved assessment 25 / });
  expect(
    screen
      .getByRole("button", { name: /Saved assessment 19 / })
      .getAttribute("aria-current"),
  ).toBe("true");
  expect(screen.getByText("Selected from another page")).toBeTruthy();
  rendered.unmount();
  render(view(jobs[18].id));
  await screen.findByText("Recorded candidate assessment");
  expect(
    screen
      .getByRole("button", { name: /Saved assessment 19 / })
      .getAttribute("aria-current"),
  ).toBe("true");
  expect(
    screen.getAllByRole("button", { name: /Saved assessment/ }),
  ).toHaveLength(4);
});

it("drops the retired correction-admission sentence from a recorded scope and keeps the rest", async () => {
  const job = assessmentJobFixture(options, { id: "scope-check" });
  job.result.scope =
    "Correction admission remains held. Historical source scope is retained. Correction admission remains held.";
  jobs = [job];
  render(view(job.id));
  await screen.findByText("Recorded candidate assessment");
  const panel = screen
    .getByText("Recorded candidate assessment")
    .closest(".assessment-outcome-panel")! as HTMLElement;
  expect(panel.textContent).not.toMatch(/correction admission/i);
  expect(
    within(panel).getByText("Historical source scope is retained."),
  ).toBeTruthy();
});
it("keeps selected older comparison inspections visible while bounding the list and retaining the eight-selection limit", async () => {
  const comparisons = Array.from({ length: 20 }, (_, index) => ({
    ...source,
    id: `11111111-1111-4111-8111-${String(index + 1).padStart(12, "0")}`,
    title: `Comparison fixture ${index + 1}`,
  }));
  render(view("", vi.fn(), comparisons));
  await waitFor(() =>
    expect(
      screen.getAllByRole("checkbox", { name: /Comparison fixture/ }),
    ).toHaveLength(3),
  );
  fireEvent.click(
    screen.getByRole("button", { name: /More comparison inspections/ }),
  );
  expect(
    screen.getAllByRole("checkbox", { name: /Comparison fixture/ }),
  ).toHaveLength(20);
  const older = screen.getByRole("checkbox", {
    name: /Comparison fixture 19 /,
  });
  act(() => older.focus());
  fireEvent.click(older);
  expect(document.activeElement).toBe(older);
  fireEvent.click(
    screen.getByRole("button", { name: /Fewer comparison inspections/ }),
  );
  expect(
    screen.getAllByRole("checkbox", { name: /Comparison fixture/ }),
  ).toHaveLength(4);
  expect(screen.getByRole("checkbox", { name: /Comparison fixture 19 / })).toBe(
    older,
  );
  act(() => older.focus());
  fireEvent.click(older);
  expect((older as HTMLInputElement).checked).toBe(false);
  expect(screen.getByRole("checkbox", { name: /Comparison fixture 19 / })).toBe(
    older,
  );
  expect(document.activeElement).toBe(older);
  expect(
    screen.getByRole("button", { name: /More comparison inspections/ })
      .textContent,
  ).toContain("16 additional loaded");
  fireEvent.click(older);
  expect((older as HTMLInputElement).checked).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: /More comparison inspections/ }),
  );
  for (let index = 1; index <= 7; index++)
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: new RegExp(`Comparison fixture ${index} `),
      }),
    );
  const list = screen.getByRole("list", {
    name: "Comparison EPUB inspections",
  });
  expect(list.querySelectorAll("input:checked")).toHaveLength(8);
  expect(list.querySelectorAll("input:disabled")).toHaveLength(12);
  fireEvent.click(
    screen.getByRole("button", { name: /Fewer comparison inspections/ }),
  );
  expect(
    screen.getAllByRole("checkbox", { name: /Comparison fixture/ }),
  ).toHaveLength(8);
  expect(
    screen.getByRole("button", { name: "Add comparison inspection" }),
  ).toBeTruthy();
});
it("posts explicit coverage and optional reference pins and displays bound authentication", async () => {
  render(view());
  await chooseCoverage();
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /fixture.reference/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Run candidate assessment" }),
  );
  await screen.findByText("Authenticated curated reference match");
  const call = calls.find((item) => item.init.method === "POST")!;
  expect(JSON.parse(String(call.init.body))).toEqual({
    version: pin.version,
    sha256: pin.sha256,
    catalogue_work_id: "w_fixture",
    source_sha256: source.source_sha256,
    report_sha256: source.result.report_sha256,
    reconciliation,
    reference,
  });
  expect(new Headers(call.init.headers).get("Idempotency-Key")).toMatch(
    /^[a-f0-9-]{36}$/,
  );
  expect(new Headers(call.init.headers).get("X-CSRFToken")).toBe("fixture");
  expect(screen.getByText(/Curated at snapshot 2026.10.28.1/)).toBeTruthy();
  expect(screen.queryByText(/semantic_duplicates_unconfirmed/)).toBeNull();
});
it("continues ordinary assessment with no trust configured and announces historical scope", async () => {
  intercept = (url) =>
    url.pathname.endsWith("/references")
      ? json({
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
        })
      : undefined;
  render(view());
  await runCheck();
  expect(screen.getByText("Not requested")).toBeTruthy();
  expect(
    JSON.parse(
      String(calls.find((item) => item.init.method === "POST")!.init.body),
    ).reference,
  ).toBeUndefined();
  expect(
    (
      await axe.run(
        screen.getByRole("region", {
          name: "Candidate assessment and library reconciliation",
        }),
        { rules: { "color-contrast": { enabled: false } } },
      )
    ).violations,
  ).toEqual([]);
});
it("recovers an accepted request after an uncertain POST without sending it twice", async () => {
  intercept = (url, init) => {
    if (url.pathname.endsWith("/checks") && init.method === "POST") {
      const key = new Headers(init.headers).get("Idempotency-Key")!;
      jobs.push(assessmentJobFixture(options, { request_key: key }));
      return Promise.reject(new TypeError("Connection closed"));
    }
  };
  render(view());
  await runCheck();
  expect(calls.filter((item) => item.init.method === "POST")).toHaveLength(1);
  expect(calls.some((item) => item.url.searchParams.has("request_key"))).toBe(
    true,
  );
});
it("recovers a persisted request on reload without assuming it ran", async () => {
  const intent = assessmentIntentFixture(options);
  const { saveAssessmentIntent } =
    await import("../src/candidate-assessment-api");
  saveAssessmentIntent(intent);
  jobs.push(assessmentJobFixture(options, { request_key: intent.key }));
  render(view());
  await screen.findByText("Recorded candidate assessment");
  expect(calls.some((item) => item.init.method === "POST")).toBe(false);
});
it("keeps an unrecorded uncertain request recoverable and retries its original key", async () => {
  let accepted = false;
  intercept = (url, init) => {
    if (
      url.pathname.endsWith("/checks") &&
      init.method === "POST" &&
      !accepted
    ) {
      accepted = true;
      return Promise.reject(new TypeError("Disconnected"));
    }
  };
  render(view());
  await chooseCoverage();
  fireEvent.click(
    screen.getByRole("button", { name: "Run candidate assessment" }),
  );
  await screen.findByText(
    "The candidate assessment request is not recorded yet.",
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Retry this candidate assessment request",
    }),
  );
  await screen.findByText("Recorded candidate assessment");
  const posts = calls.filter((item) => item.init.method === "POST");
  expect(posts).toHaveLength(2);
  expect(new Headers(posts[0].init.headers).get("Idempotency-Key")).toBe(
    new Headers(posts[1].init.headers).get("Idempotency-Key"),
  );
});
it("uses a new request key after changing the reference selection", async () => {
  render(view());
  await runCheck();
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /fixture.reference/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Run candidate assessment" }),
  );
  await screen.findByText("Authenticated curated reference match");
  const posts = calls.filter((item) => item.init.method === "POST");
  expect(new Headers(posts[0].init.headers).get("Idempotency-Key")).not.toBe(
    new Headers(posts[1].init.headers).get("Idempotency-Key"),
  );
});
it("opens a saved assessment directly using captured pins without catalogue search", async () => {
  const savedJob = assessmentJobFixture(options);
  jobs.push(savedJob);
  render(
    <QueryClientProvider client={client}>
      <PackageComparison job={source} assessmentId={savedJob.id} />
    </QueryClientProvider>,
  );
  await screen.findByText("Recorded candidate assessment");
  expect(
    calls.some(
      (item) =>
        item.url.pathname === "/api/catalogue" ||
        item.url.pathname.endsWith("/comparison"),
    ),
  ).toBe(false);
});
it("renders historical absence instead of inventing non-EPUB or reference observations", async () => {
  const old = assessmentJobFixture({ ...options, policy: 1 });
  const duplicates = old.result.duplicates as Record<string, unknown>;
  delete duplicates.content;
  delete duplicates.other_formats;
  delete old.result.source_provenance;
  jobs.push(old);
  render(view(old.id));
  await screen.findByText("Recorded candidate assessment");
  expect(
    screen.getAllByText(/Not recorded by this historical/).length,
  ).toBeGreaterThan(1);
});
it("keeps cancellation available for an active selected saved check", async () => {
  const queued = assessmentJobFixture(options, {
    state: "queued",
    result: {},
    revision: 1,
  });
  jobs.push(queued);
  const cancel = vi.fn();
  render(view(queued.id, cancel));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel check" }));
  expect(cancel).toHaveBeenCalledWith(queued);
});
it("runs and polls an explicit reconciliation, retaining cancellation and explicit coverage choice", async () => {
  let reconcile: Job | undefined;
  let finish: ((response: Response) => void) | undefined;
  const cancel = vi.fn();
  intercept = (url, init) => {
    if (url.pathname === "/api/direct-library")
      return json({ inventory: saved.inventory });
    if (
      url.pathname === "/api/library/reconciliation-jobs" &&
      init.method === "POST"
    ) {
      reconcile = {
        ...source,
        kind: "library_reconcile",
        id: "reconcile-1",
        request_key: new Headers(init.headers).get("Idempotency-Key")!,
        source_version: pin.version,
        source_sha256: pin.sha256,
        catalogue_version: pin.version,
        catalogue_sha256: pin.sha256,
        state: "queued",
        revision: 1,
        message: "Queued reconciliation",
        result: {},
      };
      return json(reconcile, 202);
    }
    if (url.pathname === "/api/jobs/reconcile-1")
      return new Promise((resolve) => {
        finish = resolve;
      });
  };
  render(view("", cancel));
  await chooseCoverage();
  fireEvent.click(
    screen.getByRole("button", { name: "Run library reconciliation" }),
  );
  await screen.findByText("Queued reconciliation");
  fireEvent.click(
    screen.getByRole("button", { name: "Cancel reconciliation" }),
  );
  expect(cancel).toHaveBeenCalledWith(reconcile);
  const sent = calls.find(
    (item) =>
      item.url.pathname === "/api/library/reconciliation-jobs" &&
      item.init.method === "POST",
  )!;
  expect(JSON.parse(String(sent.init.body))).toEqual({
    version: pin.version,
    sha256: pin.sha256,
    inventory: saved.inventory,
    previous: reconciliation,
  });
  await waitFor(() => expect(finish).toBeDefined());
  finish!(
    new Response(
      JSON.stringify({
        ...reconcile,
        state: "succeeded",
        revision: 4,
        message: "New coverage saved",
        result: {
          ready: false,
          request_key: "44444444-4444-4444-8444-444444444444",
        },
      }),
    ),
  );
  await screen.findByText("New coverage saved");
  expect((screen.getByRole("radio") as HTMLInputElement).checked).toBe(true);
});
it("ends at the saved assessment result with no correction or recheck step", async () => {
  const job = assessmentJobFixture(options);
  job.result.library_origin = {
    book_id: "1",
    library_uuid: "fixture-library",
    inventory: saved.inventory.token,
    format: "EPUB",
  };
  job.result.source_provenance = { kind: "native_library" };
  jobs.push(job);
  render(view(job.id));
  await screen.findByText("Recorded candidate assessment");
  expect(screen.getByText("Native library (1)")).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: /correction|review copy|recheck|prepar/i,
    }),
  ).toBeNull();
  expect(screen.queryByText(/correction admission/i)).toBeNull();
  expect(screen.queryByText(/admission blockers/i)).toBeNull();
  expect(
    calls.some((item) =>
      /\/(preparation|source-check|corrections)$/.test(item.url.pathname),
    ),
  ).toBe(false);
});
it("retries a persisted unsent request without silently choosing coverage again", async () => {
  const intent = assessmentIntentFixture(options);
  const { saveAssessmentIntent } =
    await import("../src/candidate-assessment-api");
  saveAssessmentIntent(intent);
  render(view());
  await screen.findByText(
    "The candidate assessment request is not recorded yet.",
  );
  expect((screen.getByRole("radio") as HTMLInputElement).checked).toBe(false);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Retry this candidate assessment request",
    }),
  );
  await screen.findByText("Recorded candidate assessment");
  const post = calls.find((call) => call.init.method === "POST")!;
  expect(new Headers(post.init.headers).get("Idempotency-Key")).toBe(
    intent.key,
  );
  expect(JSON.parse(String(post.init.body)).reconciliation).toBe(
    intent.reconciliation,
  );
});
it("keeps a newer saved-history choice when an older POST confirms late", async () => {
  const previous = assessmentJobFixture(options, { id: "previous-check" });
  jobs.push(previous);
  let complete: ((value: Response) => void) | undefined;
  intercept = (url, init) =>
    url.pathname.endsWith("/checks") && init.method === "POST"
      ? new Promise((resolve) => {
          complete = resolve;
        })
      : undefined;
  render(view());
  await chooseCoverage();
  fireEvent.click(
    screen.getByRole("button", { name: "Run candidate assessment" }),
  );
  await waitFor(() => expect(complete).toBeDefined());
  const choice = await screen.findByRole("button", { name: /previous-check/ });
  fireEvent.click(choice);
  await screen.findByText("Recorded candidate assessment");
  await act(async () => {
    complete!(
      new Response(
        JSON.stringify(assessmentJobFixture(options, { id: "late-check" })),
        { status: 202 },
      ),
    );
  });
  expect(choice.getAttribute("aria-current")).toBe("true");
  expect(screen.queryByRole("button", { name: /late-check/ })).toBeNull();
});
it.each([
  "registry",
  "manifest",
  "removed",
  "not_configured",
  "unavailable",
] as const)(
  "clears an exact reference selection when refreshed discovery changes: %s",
  async (change) => {
    render(view());
    await chooseCoverage();
    fireEvent.click(
      await screen.findByRole("checkbox", { name: /fixture.reference/ }),
    );
    const queryKey = [
      "content-trust-references",
      pin.version,
      pin.sha256,
      "w_fixture",
    ];
    const original =
      client.getQueryData<
        import("../src/candidate-assessment-api").ContentReferenceDiscovery
      >(queryKey)!;
    const refreshed = structuredClone(original);
    if (change === "registry") refreshed.registry_sha256 = "6".repeat(64);
    if (change === "manifest")
      refreshed.references[0].manifest_sha256 = "6".repeat(64);
    if (change === "removed") refreshed.references = [];
    if (change === "not_configured" || change === "unavailable") {
      refreshed.status = change;
      refreshed.registry_sha256 = null;
      refreshed.references = [];
      refreshed.reason_codes = [
        change === "not_configured"
          ? "trust_not_configured"
          : "registry_unavailable",
      ];
    }
    intercept = (url) =>
      url.pathname.endsWith("/references") ? json(refreshed) : undefined;
    await act(async () => {
      await client.invalidateQueries({ queryKey });
    });
    await waitFor(() =>
      expect(
        screen
          .queryAllByRole("checkbox")
          .some((input) => (input as HTMLInputElement).checked),
      ).toBe(false),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Run candidate assessment" }),
    );
    await screen.findByText("Recorded candidate assessment");
    const post = calls.find((item) => item.init.method === "POST")!;
    expect(JSON.parse(String(post.init.body)).reference).toBeUndefined();
    if (change === "registry" || change === "manifest") {
      fireEvent.click(
        screen.getByRole("checkbox", { name: /fixture.reference/ }),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Run candidate assessment" }),
      );
      await screen.findByText("Authenticated curated reference match");
      const posts = calls.filter((item) => item.init.method === "POST");
      expect(JSON.parse(String(posts.at(-1)!.init.body)).reference).toEqual({
        reference_id: reference.reference_id,
        registry_sha256: refreshed.registry_sha256,
        manifest_sha256: refreshed.references[0].manifest_sha256,
      });
    }
  },
);
it("labels advertised reference scope as not yet verified", async () => {
  render(view());
  const label = (
    await screen.findByRole("checkbox", { name: /fixture.reference/ })
  ).closest("label")!;
  expect(
    within(label).getByText(/Curated scope \(not yet verified\)/),
  ).toBeTruthy();
});
it("keeps saved assessment controls and resumed details in the book heading hierarchy", async () => {
  const job = assessmentJobFixture(options);
  jobs = [job];
  render(
    <QueryClientProvider client={client}>
      <main>
        <h1>Preserved book</h1>
        <h2>Reference</h2>
        <PackageComparison
          job={source}
          assessmentId={job.id}
          session={{ csrf: "fixture" }}
        />
        <ResumedAssessment source={source} job={job} />
      </main>
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", {
    name: "Candidate assessment and library reconciliation",
  });
  document.querySelectorAll("details").forEach((element) => {
    element.open = true;
  });
  expect(
    (
      await axe.run(screen.getByRole("main"), {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it("selects a queued later assessment and reopens its exact progress", async () => {
  const select = vi.fn();
  const queued = assessmentJobFixture(
    { ...options, reference: null },
    {
      id: "55555555-5555-4555-8555-555555555555",
      state: "queued",
      result: {},
      revision: 1,
    },
  );
  intercept = (url, init) => {
    if (url.pathname.endsWith("/checks") && init.method === "POST") {
      queued.request_key = new Headers(init.headers).get("Idempotency-Key")!;
      jobs = [queued];
      return json(queued, 202);
    }
    return undefined;
  };
  const context = {
    value: {
      schema_version: "librarium.book-workspace.v1" as const,
      source,
      origin: null,
      selection: { ...emptyWorkspaceSelection },
      jobs: [] as Job[],
    },
    select,
  };
  const renderView = (selected = "") => (
    <QueryClientProvider client={client}>
      <BookWorkspaceContext.Provider value={context}>
        <CandidateAssessment
          source={source}
          pin={pin}
          work={{ id: "w_fixture", title: "Synthetic work" }}
          session={{ csrf: "fixture", direct_library: true }}
          assessmentId={selected}
          selectAssessment={select}
          cancel={vi.fn()}
        />
        {selected && (
          <ResumedAssessment source={source} job={queued} cancel={vi.fn()} />
        )}
      </BookWorkspaceContext.Provider>
    </QueryClientProvider>
  );
  const mounted = render(renderView());
  await chooseCoverage();
  fireEvent.click(
    screen.getByRole("button", { name: "Run candidate assessment" }),
  );
  await waitFor(() => expect(select).toHaveBeenCalledWith(queued.id));
  expect(readAssessmentIntent(source)).toBeNull();
  mounted.unmount();
  context.value.selection.fa = queued.id;
  render(renderView(queued.id));
  await screen.findByRole("button", { name: "Cancel check" });
  expect(
    calls.filter(
      (c) => c.init.method === "POST" && c.url.pathname.endsWith("/checks"),
    ),
  ).toHaveLength(1);
});
