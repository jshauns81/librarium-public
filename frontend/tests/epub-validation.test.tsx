// @vitest-environment jsdom
import React, { useState } from "react";
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
import { EpubValidation } from "../src/EpubValidation";
import { JobProgress } from "../src/JobProgress";
import {
  readValidationHistory,
  recoverValidation,
  requestValidation,
  validationIntentKey,
  validationJobBinds,
  validationReportBinds,
} from "../src/epub-validation-api";
import type { EpubValidationEnvelope, Job, Session } from "../src/types";

const source: Job = {
  kind: "epub",
  id: "source-1",
  request_key: "11111111-1111-4111-8111-111111111111",
  work_id: "a".repeat(64),
  source_sha256: "a".repeat(64),
  title: "Preserved fixture.epub",
  state: "succeeded",
  revision: 4,
  checkpoint: 4,
  attempts: 1,
  updated_at: "2026-10-28T10:00:00Z",
  source_version: "librarium.epub-structure.v4",
  input_fingerprint: "b".repeat(64),
  message: "Saved structural evidence",
  result: {
    epubcheck: "not_run",
    structural_check: "passed",
    inspection_complete: true,
    report_sha256: "c".repeat(64),
    report_url: "/api/epub-inspections/source-1/report",
    ready: false,
  },
};
const validator = {
  name: "EPUBCheck",
  version: "5.4.0",
  distribution_sha256: "d".repeat(64),
  jar_manifest_sha256: "e".repeat(64),
  java_major: 21,
};
const policy = {
  version: "librarium.epub-validation.v2",
  max_source_bytes: 33554432,
  max_report_bytes: 1048576,
};
const session: Session = {
  csrf: "fictional-csrf",
  epub_validation: true,
  epub_validator: {
    name: validator.name,
    version: validator.version,
    policy_version: policy.version,
  },
};
const fixtureJob = (n: number, overrides: Partial<Job> = {}): Job => ({
  kind: "epub_validation",
  id: `validation-${n}`,
  request_key: `22222222-2222-4222-8222-${String(n).padStart(12, "0")}`,
  work_id: source.work_id,
  source_sha256: source.source_sha256,
  source_job_id: source.id,
  source_report_sha256: source.result.report_sha256,
  source_size: 42,
  title: source.title,
  state: "queued",
  revision: 1,
  checkpoint: 0,
  attempts: 0,
  updated_at: `2026-10-${String(10 + n).padStart(2, "0")}T10:00:00Z`,
  source_version: policy.version,
  validator,
  policy,
  input_fingerprint: "f".repeat(64),
  message: "Waiting for EPUBCheck",
  result: {},
  ...overrides,
});
function completed(
  n: number,
  outcome: "passed" | "failed" = "failed",
  version = policy.version,
): Job {
  const job = fixtureJob(n, {
    state: "succeeded",
    source_version: version,
    policy: { ...policy, version },
    revision: 4,
    checkpoint: 4,
    attempts: 1,
  });
  job.result = {
    kind: "epub_validation",
    synthetic: false,
    read_only: true,
    input_fingerprint: job.input_fingerprint,
    source_job_id: source.id,
    source_report_sha256: source.result.report_sha256,
    source_sha256: source.source_sha256!,
    source_size: 42,
    source_version: job.source_version,
    validator,
    policy: job.policy,
    outcome,
    counts: {
      fatal: 0,
      error: outcome === "failed" ? 1 : 0,
      warning: 2,
      info: null,
      usage: 0,
    },
    messages_truncated: true,
    message_repetition_limit: 25,
    process_exit_code: outcome === "failed" ? 1 : 0,
    ready: false,
    content_acceptance: "not_checked",
    report_sha256: "9".repeat(64),
    report_size: 512,
    report_url: `/api/epub-validations/${job.id}/report`,
    scope: "Conformance only.",
  };
  return job;
}
function envelope(job: Job): EpubValidationEnvelope {
  return {
    job_id: job.id,
    source_job_id: source.id,
    source_sha256: source.source_sha256!,
    source_report_sha256: source.result.report_sha256!,
    report_sha256: job.result.report_sha256!,
    report: {
      schema_version: "librarium.epub-validation.v1",
      source_sha256: source.source_sha256!,
      source_size: 42,
      validator,
      policy: job.policy!,
      outcome: job.result.outcome!,
      counts: job.result.counts!,
      messages: [
        {
          id: "RSC_005",
          severity: "ERROR",
          message: "A literal <img src=x> diagnostic.",
          locations: [
            { path: "EPUB/nav.xhtml", line: 3, column: null },
            { path: "", line: null, column: null },
          ],
        },
      ],
      messages_truncated: true,
      message_repetition_limit: 25,
      process_exit_code: job.result.process_exit_code!,
      ready: false,
      content_acceptance: "not_checked",
      limitations: ["Content acceptance was not checked."],
    },
  };
}
const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
let client: QueryClient;
let jobs: Job[];
let posts: { path: string; init: RequestInit }[];
let calls: string[];
let reports: Record<string, EpubValidationEnvelope>;
let intercept: (url: URL, init: RequestInit) => Promise<Response> | undefined;
const onJob = vi.fn();
const cancel = vi.fn();
const announce = vi.fn();

beforeEach(() => {
  localStorage.clear();
  jobs = [];
  posts = [];
  calls = [];
  reports = {};
  intercept = () => undefined;
  onJob.mockReset();
  cancel.mockReset();
  announce.mockReset();
  client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(String(input), location.origin);
      calls.push(url.pathname + url.search);
      const custom = intercept(url, init);
      if (custom) return custom;
      if (url.pathname === `/api/epub-inspections/${source.id}/validations`) {
        if (init.method === "POST") {
          posts.push({ path: url.pathname, init });
          const job = fixtureJob(jobs.length + 1, {
            request_key: new Headers(init.headers).get("Idempotency-Key")!,
          });
          jobs = [job, ...jobs];
          return json(job, 202);
        }
        const key = url.searchParams.get("request_key");
        if (key)
          return jobs.some((j) => j.request_key === key)
            ? json(jobs.find((j) => j.request_key === key))
            : json({ error: "Request not recorded" }, 404);
        const page = Number(url.searchParams.get("page") || 1);
        return json({
          jobs: jobs.slice((page - 1) * 20, page * 20),
          total: jobs.length,
          page,
          page_size: 20,
        });
      }
      if (url.pathname.startsWith("/api/jobs/")) {
        const id = url.pathname.split("/").at(-1);
        return jobs.some((j) => j.id === id)
          ? json(jobs.find((j) => j.id === id))
          : json({ error: "Not found" }, 404);
      }
      if (/^\/api\/epub-validations\/[^/]+\/report$/.test(url.pathname)) {
        const id = url.pathname.split("/").at(-2)!;
        return reports[id]
          ? json(reports[id])
          : json({ error: "Report unavailable" }, 409);
      }
      throw new Error(`Unexpected route ${url.pathname}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function Harness({
  item = source,
  currentSession = session,
  initial = "",
}: {
  item?: Job;
  currentSession?: Session;
  initial?: string;
}) {
  const [id, select] = useState(initial);
  return (
    <QueryClientProvider client={client}>
      <EpubValidation
        key={`${item.id}:${item.result.report_sha256}`}
        source={item}
        session={currentSession}
        validationId={id}
        selectValidation={select}
        onJob={onJob}
        cancel={cancel}
        announceTerminal={announce}
      />
    </QueryClientProvider>
  );
}

it("only queues EPUBCheck after explicit action and preserves the source structural outcome", async () => {
  const before = JSON.stringify(source);
  render(<Harness />);
  await screen.findByText("No EPUBCheck attempts recorded.");
  expect(posts).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Run EPUBCheck" }));
  await screen.findByText("Queued", { selector: "strong" });
  expect(posts).toHaveLength(1);
  expect(posts[0].init.body).toBe("{}");
  expect(new Headers(posts[0].init.headers).get("X-CSRFToken")).toBe(
    "fictional-csrf",
  );
  expect(new Headers(posts[0].init.headers).get("Idempotency-Key")).toMatch(
    /^[a-f0-9-]{36}$/,
  );
  expect(JSON.stringify(source)).toBe(before);
  expect(localStorage.getItem(validationIntentKey(source.id))).toBeNull();
});

it("retries an unconfirmed enqueue with the original key after a missing recovery read", async () => {
  let attempts = 0;
  intercept = (url, init) => {
    if (
      url.pathname.endsWith("/validations") &&
      init.method === "POST" &&
      attempts++ === 0
    ) {
      posts.push({ path: url.pathname, init });
      return Promise.reject(new TypeError("Response lost"));
    }
    return undefined;
  };
  render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: "Run EPUBCheck" }));
  await screen.findByText(/not confirmed/);
  const saved = JSON.parse(
    localStorage.getItem(validationIntentKey(source.id))!,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Retry this EPUBCheck request" }),
  );
  await screen.findByText("Queued", { selector: "strong" });
  expect(posts).toHaveLength(2);
  expect(new Headers(posts[0].init.headers).get("Idempotency-Key")).toBe(
    saved.key,
  );
  expect(new Headers(posts[1].init.headers).get("Idempotency-Key")).toBe(
    saved.key,
  );
});

it("recovers an uncertain request after reload without automatically posting again", async () => {
  const waiting = fixtureJob(4);
  jobs = [waiting];
  localStorage.setItem(
    validationIntentKey(source.id),
    JSON.stringify({
      key: waiting.request_key,
      source_job_id: source.id,
      source_sha256: source.source_sha256,
      source_report_sha256: source.result.report_sha256,
    }),
  );
  render(<Harness />);
  await screen.findByText("Queued", { selector: "strong" });
  expect(posts).toHaveLength(0);
  expect(
    calls.some((path) => path.includes(`request_key=${waiting.request_key}`)),
  ).toBe(true);
  expect(localStorage.getItem(validationIntentKey(source.id))).toBeNull();
});

it("keeps an explicitly opened historical validation ahead of automatic request recovery", async () => {
  const old = completed(1, "passed"),
    newer = fixtureJob(2);
  jobs = [newer, old];
  localStorage.setItem(
    validationIntentKey(source.id),
    JSON.stringify({
      key: newer.request_key,
      source_job_id: source.id,
      source_sha256: source.source_sha256,
      source_report_sha256: source.result.report_sha256,
    }),
  );
  render(<Harness initial={old.id} />);
  await screen.findByText("EPUBCheck passed");
  expect(calls.some((path) => path.includes("request_key="))).toBe(false);
  expect(localStorage.getItem(validationIntentKey(source.id))).toBeTruthy();
});

it("clears a rejected cross-source key and requires explicit fresh-key enqueue", async () => {
  let refused = true;
  intercept = (url, init) => {
    if (
      url.pathname.endsWith("/validations") &&
      init.method === "POST" &&
      refused
    ) {
      posts.push({ path: url.pathname, init });
      return json({ error: "This key belongs to another source" }, 409);
    }
    return undefined;
  };
  render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: "Run EPUBCheck" }));
  await screen.findByText("This key belongs to another source");
  expect(localStorage.getItem(validationIntentKey(source.id))).toBeNull();
  const firstKey = new Headers(posts[0].init.headers).get("Idempotency-Key");
  refused = false;
  fireEvent.click(
    screen.getByRole("button", { name: "Start a new EPUBCheck" }),
  );
  await screen.findByText("Queued", { selector: "strong" });
  expect(new Headers(posts[1].init.headers).get("Idempotency-Key")).not.toBe(
    firstKey,
  );
});

it("shows conformance errors from a completed job with truthful counts and bounded diagnostics", async () => {
  const done = completed(3);
  jobs = [done];
  reports[done.id] = envelope(done);
  render(<Harness initial={done.id} />);
  await screen.findByText("EPUBCheck found conformance errors");
  expect(screen.getByText("Complete", { selector: "strong" })).toBeTruthy();
  expect(screen.queryByText("Failed", { selector: "strong" })).toBeNull();
  expect(screen.getByText("Not reported")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Load EPUBCheck diagnostics" }),
  );
  await screen.findByText("A literal <img src=x> diagnostic.");
  expect(screen.getByText("EPUB/nav.xhtml · line 3")).toBeTruthy();
  expect(screen.getByText("Publication")).toBeTruthy();
  expect(
    screen.getByText(/25 for each diagnostic ID and message text/),
  ).toBeTruthy();
  expect(
    screen.getByText(/Some diagnostics or source locations were omitted/),
  ).toBeTruthy();
  expect(
    document.querySelector(".epub-validation img, .epub-validation a"),
  ).toBeNull();
});

it("keeps source date warnings readable while retaining their exact diagnostic and location", async () => {
  const done = completed(3);
  jobs = [done];
  const report = envelope(done);
  report.report.messages[0].id = "OPF_053";
  reports[done.id] = report;
  render(<Harness initial={done.id} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Load EPUBCheck diagnostics" }),
  );
  await screen.findByText(
    "A package date does not use the recommended date format.",
  );
  expect(screen.getByText("EPUB/nav.xhtml · line 3")).toBeTruthy();
  const exact = screen
    .getByText("Exact EPUBCheck diagnostic")
    .closest("details")!;
  expect(exact.open).toBe(false);
  fireEvent.click(exact.querySelector("summary")!);
  expect(
    within(exact).getByText("A literal <img src=x> diagnostic."),
  ).toBeTruthy();
  expect(document.querySelector(".epub-validation img")).toBeNull();
});

it("distinguishes worker failure and cancellation from conformance outcomes", async () => {
  jobs = [
    fixtureJob(5, {
      state: "failed",
      revision: 4,
      message: "The checker process did not finish safely",
    }),
  ];
  render(<Harness initial="validation-5" />);
  await screen.findByText("The checker process did not finish safely");
  expect(screen.getByText("Failed", { selector: "strong" })).toBeTruthy();
  expect(
    screen.queryByText(/EPUBCheck (passed|found conformance errors)/),
  ).toBeNull();
});

it("aborts source-A commands without stealing source B when a late enqueue finishes", async () => {
  const pending = deferred<Response>();
  let signal: AbortSignal | undefined;
  intercept = (url, init) => {
    if (url.pathname.endsWith("/validations") && init.method === "POST") {
      posts.push({ path: url.pathname, init });
      signal = init.signal ?? undefined;
      return pending.promise;
    }
    if (url.pathname.includes("source-2"))
      return json({ jobs: [], total: 0, page: 1, page_size: 20 });
    return undefined;
  };
  const view = render(<Harness />);
  fireEvent.click(await screen.findByRole("button", { name: "Run EPUBCheck" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  const second = { ...source, id: "source-2", title: "Source B.epub" };
  view.rerender(<Harness key="second" item={second} />);
  await act(async () => pending.resolve(await json(fixtureJob(9), 202)));
  expect(signal?.aborted).toBe(true);
  expect(onJob).not.toHaveBeenCalled();
  expect(screen.queryByText("Queued", { selector: "strong" })).toBeNull();
  expect(localStorage.getItem(validationIntentKey(source.id))).toBeTruthy();
});

it("rejects stale diagnostics after the user selects another validation", async () => {
  const first = completed(1),
    second = completed(2, "passed");
  jobs = [second, first];
  reports[second.id] = envelope(second);
  const pending = deferred<Response>();
  let signal: AbortSignal | undefined;
  intercept = (url, init) =>
    url.pathname === `/api/epub-validations/${first.id}/report`
      ? ((signal = init.signal ?? undefined), pending.promise)
      : undefined;
  render(<Harness initial={first.id} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Load EPUBCheck diagnostics" }),
  );
  await waitFor(() => expect(signal).toBeTruthy());
  fireEvent.click(
    screen.getByRole("button", {
      name: `Open EPUBCheck updated ${new Date(second.updated_at).toLocaleString()}`,
    }),
  );
  await screen.findByText("EPUBCheck passed");
  const old = envelope(first);
  old.report.messages[0].message = "Abandoned diagnostics";
  await act(async () => pending.resolve(await json(old)));
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("Abandoned diagnostics")).toBeNull();
});

it("offers report retry without rerunning the checker", async () => {
  const done = completed(6);
  jobs = [done];
  render(<Harness initial={done.id} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Load EPUBCheck diagnostics" }),
  );
  await screen.findByRole("button", { name: "Retry EPUBCheck diagnostics" });
  reports[done.id] = envelope(done);
  fireEvent.click(
    screen.getByRole("button", { name: "Retry EPUBCheck diagnostics" }),
  );
  await screen.findByText("A literal <img src=x> diagnostic.");
  expect(posts).toHaveLength(0);
});

it("keeps historical results readable when starting a new checker is unconfigured", async () => {
  const done = completed(7, "passed");
  jobs = [done];
  render(
    <Harness
      initial={done.id}
      currentSession={{ ...session, epub_validation: false }}
    />,
  );
  await screen.findByText("EPUBCheck passed");
  expect(screen.queryByRole("button", { name: "Run EPUBCheck" })).toBeNull();
  expect(posts).toHaveLength(0);
});

it("passes semantic accessibility checks for the outcome, history and diagnostics", async () => {
  const done = completed(8);
  jobs = [done];
  reports[done.id] = envelope(done);
  render(
    <main>
      <h1>File inspection</h1>
      <h2>Preserved source</h2>
      <Harness initial={done.id} />
    </main>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Load EPUBCheck diagnostics" }),
  );
  await screen.findByText("A literal <img src=x> diagnostic.");
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

it.each(["librarium.epub-validation.v1", "librarium.epub-validation.v2"])(
  "accepts enqueue and recovery responses with policy %s",
  async (version) => {
    const job = fixtureJob(1, {
      source_version: version,
      policy: { ...policy, version },
    });
    jobs = [job];
    intercept = (url, init) =>
      url.pathname.endsWith("/validations") && init.method === "POST"
        ? json(job, 202)
        : undefined;
    const signal = new AbortController().signal;
    await expect(
      requestValidation(source, job.request_key, session.csrf, signal),
    ).resolves.toEqual(job);
    await expect(
      recoverValidation(source, job.request_key, signal),
    ).resolves.toEqual(job);
  },
);

it("reads mixed v1/v2 history and opens either attempt's v1 diagnostics", async () => {
  const old = completed(1, "passed", "librarium.epub-validation.v1");
  const current = completed(2);
  jobs = [current, old];
  await expect(
    readValidationHistory(source, 1, new AbortController().signal),
  ).resolves.toEqual({ jobs, total: 2, page: 1, page_size: 20 });
  for (const job of jobs) {
    expect(validationReportBinds(source, job, envelope(job))).toBe(true);
  }
});

it.each(["librarium.epub-validation.v1", "librarium.epub-validation.v2"])(
  "requires report schema v1 independently of policy %s",
  (version) => {
    const job = completed(1, "passed", version);
    const value = envelope(job);
    expect(validationReportBinds(source, job, value)).toBe(true);
    value.report.schema_version = "librarium.epub-validation.v2";
    expect(validationReportBinds(source, job, value)).toBe(false);
  },
);

it.each([
  "librarium.epub-validation.v0",
  "librarium.epub-validation.v3",
  "future",
  "",
])(
  "rejects unsupported policy %s even when its source version matches",
  (version) => {
    const job = fixtureJob(1, {
      source_version: version,
      policy: { ...policy, version },
    });
    expect(validationJobBinds(source, job)).toBe(false);
  },
);

it("rejects a supported policy whose source version differs", () => {
  expect(
    validationJobBinds(
      source,
      fixtureJob(1, {
        source_version: "librarium.epub-validation.v1",
      }),
    ),
  ).toBe(false);
});

it("binds queued validation jobs to the original source inspection and captured profile", () => {
  expect(validationJobBinds(source, fixtureJob(1))).toBe(true);
  expect(
    validationJobBinds(
      source,
      fixtureJob(1, { source_job_id: "another-source" }),
    ),
  ).toBe(false);
  expect(
    validationJobBinds(
      source,
      fixtureJob(1, { source_report_sha256: "0".repeat(64) }),
    ),
  ).toBe(false);
});

it.each([
  "job",
  "source job",
  "source",
  "source report",
  "report",
  "size",
  "validator",
  "policy",
  "ready",
  "counts",
])("refuses diagnostic reports with a different %s binding", (field) => {
  const done = completed(2);
  const value = envelope(done);
  if (field === "job") value.job_id = "another-validation";
  if (field === "source job") value.source_job_id = "another-source";
  if (field === "source") value.report.source_sha256 = "0".repeat(64);
  if (field === "source report") value.source_report_sha256 = "0".repeat(64);
  if (field === "report") value.report_sha256 = "0".repeat(64);
  if (field === "size") value.report.source_size = 41;
  if (field === "validator")
    value.report.validator = {
      ...validator,
      distribution_sha256: "0".repeat(64),
    };
  if (field === "policy")
    value.report.policy = { ...policy, max_report_bytes: 2048 };
  if (field === "ready") value.report.ready = true as false;
  if (field === "counts")
    value.report.counts = { ...value.report.counts, error: 99 };
  expect(validationReportBinds(source, done, value)).toBe(false);
});

it("guards repeated Run actions while the first enqueue is still uncertain", async () => {
  const pending = deferred<Response>();
  intercept = (url, init) => {
    if (url.pathname.endsWith("/validations") && init.method === "POST") {
      posts.push({ path: url.pathname, init });
      return pending.promise;
    }
  };
  render(<Harness />);
  const run = await screen.findByRole("button", { name: "Run EPUBCheck" });
  fireEvent.click(run);
  fireEvent.click(run);
  expect(posts).toHaveLength(1);
  const job = fixtureJob(1, {
    request_key: new Headers(posts[0].init.headers).get("Idempotency-Key")!,
  });
  jobs = [job];
  await act(async () => pending.resolve(await json(job, 202)));
  await screen.findByText("Queued", { selector: "strong" });
  fireEvent.click(screen.getByRole("button", { name: "Run EPUBCheck" }));
  expect(posts).toHaveLength(1);
});

it("paginates scoped history while retaining the exact opened attempt", async () => {
  jobs = Array.from({ length: 21 }, (_, i) => completed(21 - i));
  render(<Harness initial="validation-21" />);
  await screen.findByText("21 EPUBCheck attempts");
  fireEvent.click(screen.getByRole("button", { name: "Next EPUBCheck page" }));
  await screen.findByText("Page 2 of 2");
  expect(
    screen.getAllByRole("button", { name: /^Open EPUBCheck updated/ }),
  ).toHaveLength(1);
  expect(screen.getByText("EPUBCheck found conformance errors")).toBeTruthy();
  const first = screen.getByRole("button", {
    name: `Open EPUBCheck updated ${new Date(jobs[20].updated_at).toLocaleString()}`,
  });
  fireEvent.click(first);
  await waitFor(() => expect(first.getAttribute("aria-current")).toBe("true"));
  expect(posts).toHaveLength(0);
});

it("retains the last status on a polling error, then refuses an older revision after recovery", async () => {
  const done = completed(2);
  jobs = [done];
  render(<Harness initial={done.id} />);
  await screen.findByText("EPUBCheck found conformance errors");
  intercept = (url) =>
    url.pathname === `/api/jobs/${done.id}`
      ? json({ error: "Status temporarily unavailable" }, 503)
      : undefined;
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh EPUBCheck status" }),
  );
  await screen.findByText("Status temporarily unavailable");
  expect(screen.getByText("EPUBCheck found conformance errors")).toBeTruthy();
  intercept = (url) =>
    url.pathname === `/api/jobs/${done.id}` ? json(fixtureJob(2)) : undefined;
  fireEvent.click(
    screen.getByRole("button", { name: "Retry EPUBCheck status" }),
  );
  await waitFor(() =>
    expect(screen.queryByText("Status temporarily unavailable")).toBeNull(),
  );
  expect(screen.getByText("EPUBCheck found conformance errors")).toBeTruthy();
  expect(screen.queryByText("Queued", { selector: "strong" })).toBeNull();
});

it("rejects a report from another captured checker profile in the mounted view", async () => {
  const done = completed(1);
  jobs = [done];
  const wrong = envelope(done);
  wrong.report.validator = {
    ...validator,
    jar_manifest_sha256: "0".repeat(64),
  };
  reports[done.id] = wrong;
  render(<Harness initial={done.id} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Load EPUBCheck diagnostics" }),
  );
  await screen.findByText(/diagnostics do not match this job/);
  expect(screen.queryByText("A literal <img src=x> diagnostic.")).toBeNull();
  expect(posts).toHaveLength(0);
});

it("retries history reads without enqueueing a validation", async () => {
  intercept = (url) =>
    url.pathname.endsWith("/validations")
      ? json({ error: "History temporarily unavailable" }, 503)
      : undefined;
  render(<Harness />);
  await screen.findByText("History temporarily unavailable");
  intercept = () => undefined;
  fireEvent.click(
    screen.getByRole("button", { name: "Retry EPUBCheck history" }),
  );
  await screen.findByText("No EPUBCheck attempts recorded.");
  expect(posts).toHaveLength(0);
});

it("moves keyboard focus from the completed load action to the diagnostics heading", async () => {
  const done = completed(1);
  jobs = [done];
  reports[done.id] = envelope(done);
  render(<Harness initial={done.id} />);
  const load = await screen.findByRole("button", {
    name: "Load EPUBCheck diagnostics",
  });
  load.focus();
  fireEvent.click(load);
  const heading = await screen.findByRole("heading", {
    name: "EPUBCheck diagnostics",
  });
  await waitFor(() => expect(document.activeElement).toBe(heading));
});

it("keeps native validation progress indeterminate while preserving recorded inspection steps", () => {
  const { unmount } = render(
    <JobProgress job={fixtureJob(1, { state: "running", checkpoint: 1 })} />,
  );
  expect(screen.getByRole("progressbar").getAttribute("value")).toBeNull();
  expect(screen.queryByText(/\/ 4 steps/)).toBeNull();
  unmount();
  render(<JobProgress job={{ ...source, state: "running", checkpoint: 2 }} />);
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("2");
  expect(screen.getByText("2 / 4 steps")).toBeTruthy();
});
