// @vitest-environment jsdom
import React from "react";
import { createHash } from "node:crypto";
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
import { App } from "../src/App";
import type { EpubReportEnvelope, Job } from "../src/types";

const MAX_BYTES = 32 * 1024 * 1024;
const fid = (n: number) =>
  `11111111-1111-4111-8111-${String(n).padStart(12, "0")}`;
const vid = (n: number) =>
  `22222222-2222-4222-8222-${String(n).padStart(12, "0")}`;
const POLICY = "librarium.epub-inspection.v1";
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const bytes = new TextEncoder().encode("PK\u0003\u0004 synthetic epub bytes");
const digest = createHash("sha256").update(bytes).digest("hex");
const sampleFile = () =>
  new File([bytes], "Sample Book.epub", { type: "application/epub+zip" });

function epub(n: number, overrides: Partial<Job> = {}): Job {
  return {
    id: fid(n),
    kind: "epub",
    request_key: `11111111-1111-4111-8111-${String(n).padStart(12, "0")}`,
    work_id: digest,
    title: `Uploaded ${n}.epub`,
    state: "succeeded",
    revision: 4,
    checkpoint: 4,
    attempts: 1,
    message: "Saved the EPUB structural report; readiness was not checked",
    updated_at: `2026-10-${String(1 + (n % 27)).padStart(2, "0")}T10:00:00Z`,
    source_version: POLICY,
    source_sha256: digest,
    input_fingerprint: "b".repeat(64),
    result: {
      read_only: true,
      synthetic: false,
      ready: false,
      epubcheck: "not_run",
      content_acceptance: "not_checked",
      structural_check: "passed",
      inspection_complete: true,
      report_sha256: "e".repeat(64),
      report_url: `/api/epub-inspections/${fid(n)}/report`,
      scope:
        "Structural checks only. EPUBCheck and content completeness were not checked.",
      findings: [
        {
          name: "Source integrity",
          ok: true,
          detail: "Length and SHA-256 match.",
        },
        {
          name: "EPUB structure",
          ok: true,
          detail: "The bounded checks passed.",
        },
        { name: "Navigation", ok: true, detail: "Navigation was found." },
        { name: "Scope of this check", ok: false, detail: "Structural only." },
      ],
    },
    ...overrides,
  };
}
function catalogueReview(n: number): Job {
  return {
    id: `review-${n}`,
    kind: "catalogue",
    request_key: `request-${n}`,
    work_id: `work-${n}`,
    title: `Captured title ${n}`,
    state: "succeeded",
    revision: 5,
    checkpoint: 4,
    attempts: 1,
    message: "Captured metadata reviewed",
    updated_at: "2026-10-26T12:00:00Z",
    source_version: "2026.10.24.2",
    source_sha256: "c".repeat(64),
    input_fingerprint: "a".repeat(64),
    result: { synthetic: false, scope: "Catalogue metadata only." },
  };
}
const fullReport = (jobId: string) => ({
  job_id: jobId,
  source_sha256: digest,
  report_sha256: "e".repeat(64),
  report: {
    schema_version: POLICY,
    source_sha256: digest,
    expected_sha256: digest,
    policy: { version: POLICY, limits: { max_archive_bytes: MAX_BYTES } },
    upstream: {
      repository: "https://github.com/jshauns81/library-finish.git",
      revision: "abc1234",
      source: "bin/epub_content.py",
      source_sha256: "f".repeat(64),
    },
    archive: { member_count: 7, expanded_bytes: 48213 },
    package: { path: "OEBPS/content.opf", version: "3.0" },
    metadata: [
      { name: "title", text: "The Glass Meridian" },
      { name: "creator", text: "Mara Ellison" },
      { name: "language", text: "en" },
    ],
    manifest: [
      {
        id: "ch1",
        path: "OEBPS/ch1.xhtml",
        media_type: "application/xhtml+xml",
        properties: [],
      },
      {
        id: "ch2",
        path: "OEBPS/ch2.xhtml",
        media_type: "application/xhtml+xml",
        properties: [],
      },
      {
        id: "nav",
        path: "OEBPS/nav.xhtml",
        media_type: "application/xhtml+xml",
        properties: ["nav"],
      },
    ],
    spine: [
      { index: 0, idref: "ch1", path: "OEBPS/ch1.xhtml", linear: "yes" },
      { index: 1, idref: "ch2", path: "OEBPS/ch2.xhtml", linear: "yes" },
    ],
    documents: [
      {
        path: "OEBPS/ch1.xhtml",
        byte_sha256: "1".repeat(64),
        headings: [{ level: 1, id: "c1", chapter_number: 1 }],
        links: [],
      },
      {
        path: "OEBPS/ch2.xhtml",
        byte_sha256: "2".repeat(64),
        headings: [{ level: 1, id: "c2", chapter_number: 2 }],
        links: [],
      },
    ],
    navigation: {
      nav_paths: ["OEBPS/nav.xhtml"],
      ncx_paths: [],
      entries: [
        {
          path: "OEBPS/nav.xhtml",
          target_path: "OEBPS/ch1.xhtml",
          fragment: null,
        },
        {
          path: "OEBPS/nav.xhtml",
          target_path: "OEBPS/ch2.xhtml",
          fragment: "c2",
        },
      ],
      external_link_count: 0,
    },
    findings: [
      {
        code: "repeated_spine_document",
        severity: "warning",
        path: "OEBPS/ch2.xhtml",
      },
    ],
    findings_truncated: false,
    inspection_complete: true,
    structural_check: "passed",
    epubcheck: "not_run",
    content_acceptance: "not_checked",
    ready: false,
  },
});

const contentsReport = (jobId: string) => {
  const saved = fullReport(jobId);
  return {
    ...saved,
    report: {
      ...saved.report,
      policy: {
        ...saved.report.policy,
        version: "librarium.epub-structure.v3",
      },
      spine: [
        { index: 0, idref: "ch2", path: "OEBPS/ch2.xhtml", linear: "yes" },
        { index: 1, idref: "ch1", path: "OEBPS/ch1.xhtml", linear: "yes" },
      ],
      documents: [
        {
          path: "OEBPS/ch1.xhtml",
          headings: [
            { level: 1, id: "c1", chapter_number: 1, label: "Chapter 1" },
          ],
          links: [],
        },
        {
          path: "OEBPS/ch2.xhtml",
          headings: [
            { level: 2, id: "c2", chapter_number: 1, label: "Chapter 1" },
          ],
          links: [],
        },
        {
          path: "OEBPS/printed.xhtml",
          headings: [
            { level: 1, id: "toc", chapter_number: null, label: "Contents" },
          ],
          links: [
            {
              tag: "a",
              attribute: "href",
              target_path: "OEBPS/ch1.xhtml",
              fragment: "c1",
              external: false,
              label: "The first <script>volume</script>",
            },
            {
              tag: "a",
              attribute: "href",
              target_path: "OEBPS/ch2.xhtml",
              fragment: "c2",
              external: false,
              label: "Αρχή دوم",
            },
            {
              tag: "a",
              attribute: "href",
              target_path: null,
              fragment: null,
              external: true,
              label: "https://external.invalid/private",
            },
          ],
        },
      ],
      navigation: {
        ...saved.report.navigation,
        ncx_paths: ["OEBPS/toc.ncx"],
        entries: [
          {
            path: "OEBPS/nav.xhtml",
            target_path: "OEBPS/ch1.xhtml",
            fragment: "c1",
            label: "Opening <img src=x>",
            kind: "nav",
            ancestors: ["First volume", "Part one"],
          },
          {
            path: "OEBPS/toc.ncx",
            target_path: "OEBPS/ch2.xhtml",
            fragment: "c2",
            label: "Afterword",
            kind: "ncx",
            ancestors: [],
          },
        ],
        external_link_count: 1,
      },
    },
  };
};

function validation(source: Job, n: number, overrides: Partial<Job> = {}): Job {
  const validator = {
    name: "EPUBCheck",
    version: "5.4.0",
    distribution_sha256: "1".repeat(64),
    jar_manifest_sha256: "2".repeat(64),
    java_major: 21,
  };
  const policy = {
    version: "librarium.epub-validation.v1",
    max_source_bytes: MAX_BYTES,
  };
  return {
    ...source,
    kind: "epub_validation",
    id: vid(n),
    request_key: `22222222-2222-4222-8222-${String(n).padStart(12, "0")}`,
    source_job_id: source.id,
    source_report_sha256: source.result.report_sha256,
    source_size: bytes.length,
    validator,
    policy,
    source_version: policy.version,
    updated_at: `2026-10-${String(n).padStart(2, "0")}T10:00:00Z`,
    result: {
      kind: "epub_validation",
      read_only: true,
      synthetic: false,
      source_job_id: source.id,
      source_report_sha256: source.result.report_sha256,
      source_sha256: source.source_sha256!,
      source_size: bytes.length,
      input_fingerprint: source.input_fingerprint,
      source_version: policy.version,
      validator,
      policy,
      outcome: "failed",
      counts: { fatal: 0, error: 1, warning: 0, info: null, usage: 0 },
      messages_truncated: false,
      message_repetition_limit: 25,
      process_exit_code: 1,
      ready: false,
      content_acceptance: "not_checked",
      report_sha256: "4".repeat(64),
      report_url: `/api/epub-validations/${vid(n)}/report`,
    },
    ...overrides,
  };
}

type Call = { url: URL; init: RequestInit };
let client: QueryClient;
let connected: boolean;
let fileInspections: boolean;
let validationEnabled: boolean | undefined;
let epubJobs: Job[];
let records: Job[];
let reports: Record<string, unknown>;
let uploads: Call[];
let calls: Call[];
let intercept: (url: URL, init: RequestInit) => Promise<Response> | undefined;
const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));
const headerOf = (init: RequestInit, name: string) =>
  new Headers(init.headers).get(name);

beforeEach(() => {
  history.replaceState(null, "", "/?view=files");
  localStorage.clear();
  connected = true;
  fileInspections = true;
  validationEnabled = undefined;
  epubJobs = [];
  records = [];
  reports = {};
  uploads = [];
  calls = [];
  intercept = () => undefined;
  client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true })),
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Element.prototype.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
  vi.spyOn(AbortSignal, "timeout").mockImplementation((ms) => {
    const controller = new AbortController();
    setTimeout(
      () =>
        controller.abort(new DOMException("Request timed out", "TimeoutError")),
      ms,
    );
    return controller.signal;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(String(input), location.origin);
      calls.push({ url, init });
      const custom = intercept(url, init);
      if (custom) return custom;
      if (url.pathname === "/api/session")
        return json({
          csrf: "test-token",
          library: connected,
          file_inspections: fileInspections,
          epub_validation: validationEnabled,
          epub_validator: validationEnabled
            ? {
                name: "EPUBCheck",
                version: "5.4.0",
                policy_version: "librarium.epub-validation.v1",
              }
            : undefined,
          file_inspection_max_bytes: MAX_BYTES,
        });
      if (url.pathname.endsWith("/workspace")) {
        const source = [...epubJobs, ...records].find(
          (job) => job.id === url.pathname.split("/").at(-2),
        );
        if (!source) return json({ error: "Inspection not found" }, 404);
        return json({
          schema_version: "librarium.book-workspace.v1",
          source,
          origin: null,
          selection: Object.fromEntries(
            ["fv", "fa"].map((key) => [key, url.searchParams.get(key)]),
          ),
          jobs: records.filter((job) => job.source_job_id === source.id),
        });
      }
      if (url.pathname === "/api/book-workspaces/resolve") {
        const job = [...epubJobs, ...records].find(
          (job) => job.id === url.searchParams.get("job"),
        );
        if (!job) return json({ error: "Inspection not found" }, 404);
        return json({
          schema_version: "librarium.book-workspace-resolution.v1",
          source_job_id: job.kind === "epub" ? job.id : job.source_job_id,
          selection: {
            fv: job.kind === "epub_validation" ? job.id : null,
            fa: null,
            fda: null,
            faj: null,
            fg: null,
            fo: null,
            fov: null,
            fdp: null,
            fd: null,
            fdj: null,
          },
        });
      }
      if (url.pathname.endsWith("/corrections"))
        return json({ results: [], count: 0, page: 1, pages: 1 });
      if (url.pathname === "/api/jobs") {
        const kind = url.searchParams.get("kind");
        const pool =
          kind === "epub"
            ? epubJobs
            : kind === "catalogue" || kind === "epub_validation"
              ? records.filter((j) => j.kind === kind)
              : [...records, ...epubJobs];
        return json({ jobs: pool.slice(0, 30) });
      }
      if (url.pathname === "/api/jobs/history") {
        const kind = url.searchParams.get("kind");
        const q = (url.searchParams.get("q") ?? "").toLowerCase();
        const state = url.searchParams.get("state") ?? "";
        const page = Number(url.searchParams.get("page") || 1);
        const matches = records.filter(
          (job) =>
            (!kind || job.kind === kind) &&
            job.title.toLowerCase().includes(q) &&
            (!state ||
              (state === "active"
                ? ["queued", "running"].includes(job.state)
                : job.state === state)),
        );
        return json({
          jobs: matches.slice((page - 1) * 24, page * 24),
          total: matches.length,
          page,
          page_size: 24,
        });
      }
      if (url.pathname.startsWith("/api/jobs/")) {
        const id = url.pathname.split("/").at(-1)!;
        const job = [...epubJobs, ...records].find((item) => item.id === id);
        if (!job) return json({ error: "Inspection not found" }, 404);
        if (init.method === "POST") {
          Object.assign(job, {
            state: "cancelled",
            revision: job.revision + 1,
            message: "Cancelled before completion",
          });
        }
        return json(job);
      }
      if (/^\/api\/epub-inspections\/[^/]+\/validations$/.test(url.pathname)) {
        const sourceId = url.pathname.split("/").at(-2)!;
        if (init.method === "POST") {
          const source = epubJobs.find((job) => job.id === sourceId)!;
          const job = validation(source, records.length + 1, {
            state: "queued",
            checkpoint: 0,
            result: {},
            request_key: headerOf(init, "Idempotency-Key")!,
          });
          records.unshift(job);
          return json(job, 202);
        }
        const page = Number(url.searchParams.get("page") || 1);
        const matching = records.filter(
          (job) =>
            job.kind === "epub_validation" && job.source_job_id === sourceId,
        );
        return json({
          jobs: matching.slice((page - 1) * 20, page * 20),
          total: matching.length,
          page,
          page_size: 20,
        });
      }
      if (url.pathname === "/api/epub-inspections") {
        if (init.method === "POST") {
          uploads.push({ url, init });
          const job = epub(uploads.length, {
            id: `queued-${uploads.length}`,
            request_key: headerOf(init, "Idempotency-Key")!,
            title: decodeURIComponent(headerOf(init, "X-Source-Name")!),
            state: "queued",
            revision: 1,
            checkpoint: 0,
            attempts: 0,
            message: "Queued",
            result: {},
          });
          epubJobs.unshift(job);
          return json(job, 202);
        }
        const key = url.searchParams.get("request_key");
        const found = epubJobs.find((job) => job.request_key === key);
        return found
          ? json(found)
          : json({ error: "This request is not recorded yet" }, 404);
      }
      if (/^\/api\/epub-inspections\/[^/]+\/report$/.test(url.pathname)) {
        const id = url.pathname.split("/").at(-2)!;
        return reports[id]
          ? json(reports[id])
          : json({ error: "This inspection has no published report" }, 409);
      }
      if (url.pathname === "/api/catalogue")
        return json({ status: "not_configured" });
      if (url.pathname === "/api/works")
        return json({
          works: [],
          total: 0,
          page: 1,
          page_size: 24,
          source_versions: [],
        });
      throw new Error(`Unexpected request ${url.pathname}`);
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
function mount() {
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}
function chooseFile(file: File) {
  const input = screen.getByLabelText("EPUB file") as HTMLInputElement;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}
const params = () => new URLSearchParams(location.search);
const inspectButton = () =>
  screen.getByRole("button", {
    name: "Inspect this EPUB",
  }) as HTMLButtonElement;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

it("surfaces a recorded structural warning beside Condition without inventing its location", async () => {
  const source = epub(1);
  epubJobs = [source];
  reports[source.id] = {
    ...fullReport(source.id),
    report: {
      ...fullReport(source.id).report,
      findings: [{ code: "missing_link_resource", severity: "warning" }],
    },
  };
  history.replaceState(null, "", `/?view=files&fj=${source.id}`);
  mount();
  const warnings = await screen.findByRole("region", {
    name: "Recorded structural warnings",
  });
  expect(
    within(warnings).getByText("1 recorded structural warning"),
  ).toBeTruthy();
  expect(within(warnings).getByText("Missing link resource")).toBeTruthy();
  expect(
    screen.getByRole("status", { name: "Source condition" }).textContent,
  ).toContain("1 recorded structural warning");
  expect(
    within(warnings).getByText(/exact affected resource was not recorded/i),
  ).toBeTruthy();
  expect(screen.getByText(/The bounded structural checks passed/)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: /Reading order/ })).toBeNull();
  fireEvent.click(
    within(warnings).getByRole("button", { name: "View structural findings" }),
  );
  const heading = await screen.findByRole("heading", {
    name: /Structural findings/,
  });
  await waitFor(() => expect(document.activeElement).toBe(heading));
  expect(
    calls.filter((call) => call.url.pathname.endsWith("/report")),
  ).toHaveLength(1);
});

it("keeps unread structural warnings unknown and retries the same bound report", async () => {
  const source = epub(1);
  epubJobs = [source];
  reports[source.id] = fullReport(source.id);
  const pending = deferred<Response>();
  let reads = 0;
  intercept = (url) =>
    url.pathname.endsWith("/report") && ++reads === 1
      ? pending.promise
      : undefined;
  history.replaceState(null, "", `/?view=files&fj=${source.id}`);
  mount();
  await screen.findByText("Reading recorded structural warnings…");
  expect(
    screen.queryByText("No structural warnings were recorded."),
  ).toBeNull();
  await act(async () =>
    pending.reject(new TypeError("Synthetic connection failed")),
  );
  const retry = await screen.findByRole("button", {
    name: "Retry structural warnings",
  });
  retry.focus();
  fireEvent.click(retry);
  await screen.findByText("1 recorded structural warning");
  expect(reads).toBe(2);
  await waitFor(() =>
    expect(document.activeElement?.id).toBe("book-condition"),
  );
});

it("does not steal newer typing when a structural-warning retry completes", async () => {
  const source = epub(1);
  epubJobs = [source];
  reports[source.id] = fullReport(source.id);
  const pending = deferred<Response>();
  let reads = 0;
  intercept = (url) =>
    url.pathname.endsWith("/report")
      ? ++reads === 1
        ? json({ error: "Synthetic report interruption" }, 503)
        : pending.promise
      : undefined;
  history.replaceState(null, "", `/?view=files&fj=${source.id}`);
  mount();
  const retry = await screen.findByRole("button", {
    name: "Retry structural warnings",
  });
  retry.focus();
  fireEvent.click(retry);
  await waitFor(() => expect(reads).toBe(2));
  const draft = document.createElement("input");
  document.body.append(draft);
  try {
    draft.focus();
    fireEvent.input(draft, { target: { value: "New reader input" } });
    await act(async () => pending.resolve(await json(fullReport(source.id))));
    await screen.findByText("1 recorded structural warning");
    expect(document.activeElement).toBe(draft);
    expect(draft.value).toBe("New reader input");
  } finally {
    draft.remove();
  }
});

it("keeps a late warning read out of a newer selected source", async () => {
  const first = epub(1);
  const second = epub(2);
  records = [first, second];
  epubJobs = [first, second];
  reports[second.id] = {
    ...fullReport(second.id),
    report: { ...fullReport(second.id).report, findings: [] },
  };
  const pending = deferred<Response>();
  let signal: AbortSignal | undefined;
  intercept = (url, init) => {
    if (url.pathname !== `/api/epub-inspections/${first.id}/report`)
      return undefined;
    signal = init.signal ?? undefined;
    return pending.promise;
  };
  history.replaceState(null, "", `/?view=files&fj=${first.id}`);
  mount();
  await screen.findByText("Reading recorded structural warnings…");
  fireEvent.click(screen.getByRole("button", { name: "Choose another EPUB" }));
  fireEvent.click(await screen.findByRole("button", { name: second.title }));
  await screen.findByText("No structural warnings were recorded.");
  await act(async () =>
    pending.resolve(
      await json({
        ...fullReport(first.id),
        report: {
          ...fullReport(first.id).report,
          findings: [{ code: "missing_link_resource", severity: "warning" }],
        },
      }),
    ),
  );
  expect(signal?.aborted).toBe(true);
  expect(
    screen.queryByRole("region", { name: "Recorded structural warnings" }),
  ).toBeNull();
  expect(screen.queryByText("Missing link resource")).toBeNull();
  expect(params().get("fj")).toBe(second.id);
});

it("distinguishes unavailable warning records from zero recorded warnings", async () => {
  const source = epub(1);
  epubJobs = [source];
  reports[source.id] = {
    ...fullReport(source.id),
    report: { ...fullReport(source.id).report, findings: undefined },
  };
  history.replaceState(null, "", `/?view=files&fj=${source.id}`);
  mount();
  await screen.findByText(
    "Structural warning records are unavailable in this report.",
  );
  expect(
    screen.queryByText("No structural warnings were recorded."),
  ).toBeNull();
});

it.each([
  {},
  [null],
  [{ severity: "warning" }],
  [{ code: "missing_link_resource", severity: "warning", path: {} }],
])(
  "refuses malformed structural findings without losing the source workspace: %j",
  async (findings) => {
    const source = epub(1);
    epubJobs = [source];
    reports[source.id] = {
      ...fullReport(source.id),
      report: { ...fullReport(source.id).report, findings },
    } as unknown as EpubReportEnvelope;
    history.replaceState(null, "", `/?view=files&fj=${source.id}`);
    mount();
    await screen.findByText(/unrecognized structural finding records/i);
    expect(
      screen.getByRole("status", { name: "Source condition" }),
    ).toBeTruthy();
    expect(
      screen.queryByText("No structural warnings were recorded."),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Retry structural warnings" }),
    ).toBeTruthy();
  },
);

it("offers no generated-copy or delivery section in a book workspace", async () => {
  const source = epub(1);
  epubJobs = [source];
  history.replaceState(null, "", `/?view=files&fj=${source.id}`);
  mount();
  await screen.findByRole("status", { name: "Source condition" });
  expect(
    screen.queryByRole("region", { name: /generated|delivery/i }),
  ).toBeNull();
  expect(screen.queryByText(/generated cop|delivery|review cop/i)).toBeNull();
  expect(calls.some((call) => /corrections/.test(call.url.pathname))).toBe(
    false,
  );
});

it("retains a prospective catalogue comparison when choosing an already inspected source", async () => {
  const source = epub(1);
  records = [source];
  epubJobs = [source];
  const target = {
    work: "w_fixture",
    version: "2026.10.24.2",
    sha256: "c".repeat(64),
  };
  history.replaceState(
    { catalogueComparisonOrigin: target },
    "",
    `/?view=files&fcw=${target.work}&fcv=${target.version}&fch=${target.sha256}`,
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: source.title }));
  await screen.findByRole("heading", { name: source.title });
  expect(params().get("fcw")).toBe(target.work);
  expect(params().get("fcv")).toBe(target.version);
  expect(params().get("fch")).toBe(target.sha256);
  expect(history.state.catalogueComparisonOrigin).toEqual(target);
});

it("leads with the source verdict and moves keyboard focus to a chosen workspace section", async () => {
  const source = epub(1);
  epubJobs = [source];
  history.replaceState(null, "", `/?view=files&fj=${source.id}`);
  mount();
  const summary = await screen.findByRole("status", {
    name: "Source condition",
  });
  expect(summary.textContent).toContain("Source structural checks passed");
  expect(summary.textContent).toContain("leaves library files unchanged");
  fireEvent.click(screen.getByRole("link", { name: "Reference" }));
  expect(document.activeElement?.id).toBe("book-reference");
  fireEvent.click(screen.getByRole("link", { name: "Condition" }));
  expect(document.activeElement?.id).toBe("book-condition");
});

it("offers Inspect an EPUB from the Reviews header only when file inspection is configured, and routes within the Reviews branch", async () => {
  history.replaceState(null, "", "/?view=inspections");
  mount();
  await screen.findByRole("heading", { name: "Reviews and history" });
  const entry = screen.getByRole("button", { name: "Inspect an EPUB" });
  expect(screen.getAllByRole("button", { name: /^Reviews/ })).toHaveLength(1);
  fireEvent.click(entry);
  await screen.findByRole("heading", { name: /Incoming books|Book workspace/ });
  expect(params().get("view")).toBe("files");
  expect(
    screen
      .getByRole("button", { name: /^Reviews/ })
      .getAttribute("aria-current"),
  ).toBe("page");
  expect(screen.queryByText("Demo data")).toBeNull();
  cleanup();
  client.clear();
  fileInspections = false;
  history.replaceState(null, "", "/?view=inspections");
  mount();
  await screen.findByRole("heading", { name: "Reviews and history" });
  expect(screen.queryByRole("button", { name: "Inspect an EPUB" })).toBeNull();
});

it("shows a truthful unconfigured state on a direct files route without a dead upload form", async () => {
  fileInspections = false;
  mount();
  await screen.findByText(
    /File inspection is not configured on this connection/,
  );
  expect(screen.queryByLabelText("EPUB file")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Inspect this EPUB" }),
  ).toBeNull();
  const sessionReads = () =>
    calls.filter((call) => call.url.pathname === "/api/session");
  const before = sessionReads().length;
  fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
  await waitFor(() => expect(sessionReads().length).toBeGreaterThan(before));
  expect(
    screen.getByText(/File inspection is not configured on this connection/),
  ).toBeTruthy();
  fileInspections = true;
  fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
  await screen.findByLabelText("EPUB file");
  expect(screen.queryByText(/not configured/)).toBeNull();
  cleanup();
  client.clear();
  fileInspections = false;
  history.replaceState(null, "", "/?view=files");
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Return to reviews" }),
  );
  await screen.findByRole("heading", { name: "Reviews and history" });
  expect(params().get("view")).toBe("inspections");
});

it("keeps a saved inspection readable from a direct link while uploads are unconfigured", async () => {
  fileInspections = false;
  const saved = epub(4);
  epubJobs = [saved];
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000004",
  );
  mount();
  await screen.findByRole("heading", { name: saved.title });
  expect(screen.getByText(/not configured on this connection/)).toBeTruthy();
  expect(screen.queryByLabelText("EPUB file")).toBeNull();
  expect(screen.getByText(/readiness were not checked/)).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Load the full report" }),
  ).toBeTruthy();
});

it("hashes a chosen EPUB in the browser and uploads the raw bytes with bound headers, then follows the queued inspection", async () => {
  mount();
  await screen.findByLabelText("EPUB file");
  expect(inspectButton().disabled).toBe(true);
  chooseFile(sampleFile());
  expect(screen.getByText("Sample Book.epub")).toBeTruthy();
  expect(screen.getByText(`${bytes.byteLength} bytes`)).toBeTruthy();
  expect(inspectButton().disabled).toBe(false);
  fireEvent.click(inspectButton());
  await waitFor(() => expect(uploads).toHaveLength(1));
  const { init } = uploads[0];
  expect(init.method).toBe("POST");
  expect(headerOf(init, "Content-Type")).toBe("application/epub+zip");
  expect(headerOf(init, "X-CSRFToken")).toBe("test-token");
  expect(headerOf(init, "Idempotency-Key")).toMatch(UUID);
  expect(headerOf(init, "X-Source-SHA256")).toBe(digest);
  expect(headerOf(init, "X-Source-Name")).toBe(
    encodeURIComponent("Sample Book.epub"),
  );
  expect(Array.from(new Uint8Array(init.body as ArrayBuffer))).toEqual(
    Array.from(bytes),
  );
  await screen.findByRole("heading", { name: "Sample Book.epub" });
  expect(params().get("fj")).toBe("queued-1");
  expect(screen.getByText("Queued", { selector: "strong" })).toBeTruthy();
  expect(localStorage.getItem("librarium-file-intent")).toBeNull();
  const record = screen.getByText("Inspection record").closest("details")!;
  expect(within(record).getByText("Inspection policy")).toBeTruthy();
  expect(within(record).getByText("Source digest")).toBeTruthy();
  expect(within(record).queryByText("Source snapshot")).toBeNull();
  expect(within(record).queryByText("Snapshot digest")).toBeNull();
});

it("does not restore a discarded catalogue target when a pending upload confirms", async () => {
  const pending = deferred<Response>();
  let uploaded: Job | undefined;
  const target = {
    work: "w_fixture",
    version: "2026.10.24.2",
    sha256: "c".repeat(64),
  };
  history.replaceState(
    { catalogueComparisonOrigin: target },
    "",
    `/?view=files&fcw=${target.work}&fcv=${target.version}&fch=${target.sha256}`,
  );
  intercept = (url, init) => {
    if (url.pathname !== "/api/epub-inspections" || init.method !== "POST")
      return;
    uploads.push({ url, init });
    uploaded = epub(7, {
      title: "Sample Book.epub",
      state: "queued",
      revision: 1,
      result: {},
      request_key: headerOf(init, "Idempotency-Key")!,
    });
    epubJobs.push(uploaded);
    return pending.promise;
  };
  mount();
  await screen.findByLabelText("EPUB file");
  chooseFile(sampleFile());
  fireEvent.click(inspectButton());
  await waitFor(() => expect(uploads).toHaveLength(1));
  fireEvent.click(
    screen.getByRole("button", { name: "Discard catalogue selection" }),
  );
  expect(params().get("fcw")).toBeNull();
  await act(async () => pending.resolve(await json(uploaded, 202)));
  await screen.findByRole("heading", { name: "Sample Book.epub" });
  expect(params().get("fcw")).toBeNull();
  expect(params().get("fcv")).toBeNull();
  expect(params().get("fch")).toBeNull();
});

it.each(["succeeded", "failed", "cancelled"] as const)(
  "reconciles the navigation count when an uploaded EPUB becomes %s",
  async (state) => {
    records = [catalogueReview(1)];
    records[0] = { ...records[0], state: "running", result: {} };
    mount();
    await screen.findByLabelText("EPUB file");
    await screen.findByRole("button", { name: "Reviews 1 active" });
    chooseFile(sampleFile());
    fireEvent.click(inspectButton());
    await screen.findByRole("heading", { name: "Sample Book.epub" });
    await screen.findByRole("button", { name: "Reviews 2 active" });

    epubJobs = [{ ...epubJobs[0], state, revision: 4 }];
    await act(async () => {
      await client.refetchQueries({ queryKey: ["jobs", "epub"] });
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Reviews 1 active" }),
      ).toBeTruthy(),
    );

    records = [{ ...records[0], state: "succeeded", revision: 6 }];
    await act(async () => {
      await client.refetchQueries({ queryKey: ["jobs"] });
    });
    await screen.findByRole("button", { name: "Reviews" });
  },
);

it("rejects an oversize file before reading its bytes", async () => {
  mount();
  await screen.findByLabelText("EPUB file");
  const big = new File([new Uint8Array(8)], "Huge.epub", {
    type: "application/epub+zip",
  });
  Object.defineProperty(big, "size", { value: MAX_BYTES + 1 });
  const read = vi.spyOn(big, "arrayBuffer");
  chooseFile(big);
  await screen.findByText(/larger than the 32 MiB limit/);
  expect(inspectButton().disabled).toBe(true);
  expect(read).not.toHaveBeenCalled();
  expect(uploads).toHaveLength(0);
});

it("ignores a double click so one intent creates one upload", async () => {
  mount();
  await screen.findByLabelText("EPUB file");
  chooseFile(sampleFile());
  const button = inspectButton();
  fireEvent.click(button);
  fireEvent.click(button);
  await screen.findByRole("heading", { name: "Sample Book.epub" });
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(uploads).toHaveLength(1);
});

it("keeps a slow upload alive past the 5 s read deadline and bounds it at 120 s", async () => {
  vi.useFakeTimers();
  let finish: (response: Response) => void = () => {};
  let aborted = false;
  intercept = (url, init) => {
    if (url.pathname !== "/api/epub-inspections" || init.method !== "POST")
      return undefined;
    return new Promise((resolve, reject) => {
      finish = resolve;
      init.signal?.addEventListener("abort", () => {
        aborted = true;
        reject(init.signal?.reason);
      });
    });
  };
  mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
  chooseFile(sampleFile());
  fireEvent.click(inspectButton());
  await act(async () => {
    await vi.waitFor(() =>
      expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(
        1,
      ),
    );
    await vi.advanceTimersByTimeAsync(6000);
  });
  expect(aborted).toBe(false);
  expect(screen.getByText(/Uploading Sample Book\.epub/)).toBeTruthy();
  await act(async () => {
    const accepted = epub(1, { id: "slow-1", state: "queued", result: {} });
    epubJobs.push(accepted);
    finish(await json(accepted, 202));
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(screen.getByRole("heading", { name: "Uploaded 1.epub" })).toBeTruthy();
  cleanup();
  client.clear();
  aborted = false;
  history.replaceState(null, "", "/?view=files");
  mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
  chooseFile(sampleFile());
  fireEvent.click(inspectButton());
  await act(async () => {
    await vi.waitFor(() =>
      expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(
        2,
      ),
    );
    await vi.advanceTimersByTimeAsync(121_000);
  });
  expect(aborted).toBe(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(100);
  });
  expect(screen.getByText(/not confirmed/)).toBeTruthy();
  expect(screen.queryByText(/upload failed/i)).toBeNull();
});

it("recovers a lost acknowledgement with the same key and treats 404 as not yet recorded", async () => {
  let dropped = true;
  intercept = (url, init) =>
    url.pathname === "/api/epub-inspections" &&
    init.method === "POST" &&
    dropped
      ? (uploads.push({ url, init }),
        Promise.reject(new TypeError("Failed to fetch")))
      : undefined;
  mount();
  await screen.findByLabelText("EPUB file");
  chooseFile(sampleFile());
  fireEvent.click(inspectButton());
  await screen.findByText(/not confirmed/);
  expect(screen.getByText(/not recorded yet/)).toBeTruthy();
  expect(screen.queryByText(/upload failed/i)).toBeNull();
  const lookups = calls.filter(
    (call) =>
      call.url.pathname === "/api/epub-inspections" &&
      call.init.method !== "POST",
  );
  expect(lookups).toHaveLength(1);
  const key = headerOf(uploads[0].init, "Idempotency-Key")!;
  expect(lookups[0].url.searchParams.get("request_key")).toBe(key);
  expect(
    JSON.parse(localStorage.getItem("librarium-file-intent")!),
  ).toMatchObject({
    key,
    digest,
    name: "Sample Book.epub",
    size: bytes.byteLength,
  });
  expect(screen.getByText("Sample Book.epub")).toBeTruthy();
  dropped = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry upload" }));
  await screen.findByRole("heading", { name: "Sample Book.epub" });
  expect(uploads).toHaveLength(2);
  expect(headerOf(uploads[1].init, "Idempotency-Key")).toBe(key);
  expect(headerOf(uploads[1].init, "X-Source-SHA256")).toBe(digest);
  expect(localStorage.getItem("librarium-file-intent")).toBeNull();
});

it("restores intent metadata on reload through the request-key lookup without re-reading bytes", async () => {
  const key = "22222222-2222-4222-8222-222222222222";
  localStorage.setItem(
    "librarium-file-intent",
    JSON.stringify({
      key,
      digest,
      name: "Sample Book.epub",
      size: bytes.byteLength,
    }),
  );
  mount();
  await screen.findByText(/not recorded yet/);
  expect(screen.getByText("Sample Book.epub")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Retry upload" })).toBeNull();
  expect(screen.getByText(/Choose the same file again/)).toBeTruthy();
  chooseFile(sampleFile());
  fireEvent.click(inspectButton());
  await waitFor(() => expect(uploads).toHaveLength(1));
  expect(headerOf(uploads[0].init, "Idempotency-Key")).toBe(key);
  cleanup();
  client.clear();
  const confirmed = epub(9, {
    id: "recorded-9",
    request_key: key,
    state: "running",
    revision: 2,
    checkpoint: 2,
    result: {},
  });
  epubJobs = [confirmed];
  localStorage.setItem(
    "librarium-file-intent",
    JSON.stringify({
      key,
      digest,
      name: "Sample Book.epub",
      size: bytes.byteLength,
    }),
  );
  history.replaceState(null, "", "/?view=files");
  mount();
  await screen.findByRole("heading", { name: confirmed.title });
  expect(params().get("fj")).toBe("recorded-9");
  expect(screen.getByText("Inspecting")).toBeTruthy();
  expect(screen.getByText("2 / 4 steps")).toBeTruthy();
  expect(localStorage.getItem("librarium-file-intent")).toBeNull();
});

it("explains server rejections beside the file and lets an explicit new inspection use a fresh key", async () => {
  let status = 503;
  intercept = (url, init) =>
    url.pathname === "/api/epub-inspections" && init.method === "POST" && status
      ? (uploads.push({ url, init }),
        json({ error: "File inspection is disabled" }, status))
      : undefined;
  mount();
  await screen.findByLabelText("EPUB file");
  chooseFile(sampleFile());
  fireEvent.click(inspectButton());
  await screen.findByText(/File inspection is disabled/);
  expect(screen.queryByText(/not confirmed/)).toBeNull();
  const first = headerOf(uploads[0].init, "Idempotency-Key");
  status = 0;
  fireEvent.click(
    screen.getByRole("button", { name: "Start a new inspection" }),
  );
  await screen.findByRole("heading", { name: "Sample Book.epub" });
  expect(uploads).toHaveLength(2);
  expect(headerOf(uploads[1].init, "Idempotency-Key")).not.toBe(first);
  expect(headerOf(uploads[1].init, "Idempotency-Key")).toMatch(UUID);
});

it("cancels a running inspection and keeps the newest revision over a stale poll", async () => {
  const running = epub(3, {
    state: "running",
    revision: 2,
    checkpoint: 1,
    result: {},
  });
  epubJobs = [running];
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000003",
  );
  mount();
  await screen.findByRole("heading", { name: running.title });
  expect(screen.getByText("Inspecting")).toBeTruthy();
  expect(
    screen.getByRole("progressbar", {
      name: `Inspection progress for ${running.title}`,
    }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Cancel inspection" }));
  await screen.findByText("Cancelled", { selector: "strong" });
  epubJobs = [{ ...running, state: "running", revision: 2 }];
  await act(async () => {
    await client.refetchQueries({ queryKey: ["jobs"] });
  });
  expect(screen.getByText("Cancelled", { selector: "strong" })).toBeTruthy();
  expect(screen.queryByText("Inspecting")).toBeNull();
});

it("does not describe an incomplete empty findings report as a completed check", async () => {
  const saved = epub(7);
  epubJobs = [saved];
  const report = fullReport(saved.id);
  report.report.findings = [];
  report.report.inspection_complete = false;
  report.report.findings_truncated = true;
  reports[saved.id] = report;
  history.replaceState(null, "", `/?view=files&fj=${saved.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await screen.findByRole("heading", { name: /Structural findings/ });
  const section = document
    .getElementById("report-findings")!
    .closest("section")!;
  expect(
    within(section).getByText("No structural findings were recorded."),
  ).toBeTruthy();
  expect(
    within(section).getByText(
      "Inspection was incomplete; further structural problems may remain.",
    ),
  ).toBeTruthy();
  expect(
    within(section).getByText(/later findings were not recorded/),
  ).toBeTruthy();
  expect(within(section).queryByText(/completed check/)).toBeNull();
});

it("loads the full report only when it binds to the same job and source digest", async () => {
  const done = epub(5);
  epubJobs = [done];
  reports[done.id] = fullReport(done.id);
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000005",
  );
  mount();
  await screen.findByRole("heading", { name: done.title });
  expect(screen.queryByText("Reading order")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Load the full report" }));
  await screen.findByRole("heading", { name: /Reading order/ });
  expect(screen.getByText("OEBPS/content.opf")).toBeTruthy();
  expect(screen.getByText("The Glass Meridian")).toBeTruthy();
  const order = screen.getByRole("list", { name: "Reading order" });
  expect(within(order).getAllByRole("listitem")).toHaveLength(2);
  expect(within(order).getByText(/Chapter 2/)).toBeTruthy();
  expect(
    within(screen.getByRole("region", { name: "Full report" })).getByText(
      /Repeated spine document/,
    ),
  ).toBeTruthy();
  const raw = screen.getByText("Raw report JSON").closest("details")!;
  expect(raw.querySelector("pre")).toBeNull();
  fireEvent.click(within(raw).getByText("Raw report JSON"));
  await waitFor(() =>
    expect(raw.querySelector("pre")?.textContent).toContain('"schema_version"'),
  );
  const jsonRegion = within(raw).getByRole("region", {
    name: "Raw structural report JSON",
  });
  expect(jsonRegion.tabIndex).toBe(0);
  jsonRegion.focus();
  expect(document.activeElement).toBe(jsonRegion);
  expect(screen.getByText("e".repeat(64))).toBeTruthy();
  cleanup();
  client.clear();
  reports[done.id] = { ...fullReport(done.id), source_sha256: "0".repeat(64) };
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000005",
  );
  mount();
  await screen.findByRole("heading", { name: done.title });
  fireEvent.click(screen.getByRole("button", { name: "Load the full report" }));
  // The structural-warnings read and the full report both refuse the mismatch.
  expect(
    (await screen.findAllByText(/does not match this inspection/)).length,
  ).toBeGreaterThan(0);
  expect(screen.queryByRole("heading", { name: /Reading order/ })).toBeNull();
});

it("shows no contents plan for a report from an earlier inspection, which stays preserved", async () => {
  const done = epub(62, { source_version: "librarium.epub-structure.v4" });
  epubJobs = [done];
  const saved = contentsReport(done.id);
  reports[done.id] = {
    ...saved,
    report: {
      ...saved.report,
      policy: {
        ...saved.report.policy,
        version: "librarium.epub-structure.v4",
      },
      contents_plan: {
        policy_version: "librarium.contents-plan.v1",
        source_sha256: digest,
        inspection_policy: "librarium.epub-structure.v4",
        decision: "propose",
        reason_codes: ["complete_numbered_headings"],
        existing: [],
        entries: [],
        excluded_targets: [],
        limitations: [],
        ready: false,
      },
    },
  };
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await screen.findByRole("region", { name: "Contents evidence" });
  expect(screen.getByText(/The bounded structural checks passed/)).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Contents plan" })).toBeNull();
  expect(screen.queryByRole("group", { name: "Contents planning" })).toBeNull();
  expect(screen.queryByText(/Planning held|Changes proposed/)).toBeNull();
  const raw = screen.getByText("Raw report JSON").closest("details")!;
  fireEvent.click(within(raw).getByText("Raw report JSON"));
  await waitFor(() => expect(raw.querySelector("pre")).toBeTruthy());
  expect(raw.querySelector("pre")!.textContent).toContain(
    "complete_numbered_headings",
  );
});

it("names an empty table of contents as a finding and offers no rebuild", async () => {
  const done = epub(64, {
    result: {
      ...epub(64).result,
      structural_check: "failed",
      findings: [
        {
          name: "EPUB structure",
          ok: false,
          detail: "Structural findings need review (1 recorded).",
        },
      ],
    },
  });
  epubJobs = [done];
  const saved = fullReport(done.id);
  reports[done.id] = {
    ...saved,
    report: {
      ...saved.report,
      structural_check: "failed",
      findings: [
        {
          code: "empty_navigation",
          severity: "error",
          path: "OEBPS/nav.xhtml",
        },
      ],
    },
  };
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await screen.findByText(/This book has no usable table of contents/);
  expect(screen.queryByText(/rebuild|propos|plan/i)).toBeNull();
});

it("shows labelled headings and printed contents links in recorded reading order without choosing novel boundaries", async () => {
  const done = epub(55, { source_version: "librarium.epub-structure.v3" });
  epubJobs = [done];
  reports[done.id] = contentsReport(done.id);
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  const contents = await screen.findByRole("region", {
    name: "Contents evidence",
  });
  expect(
    within(contents)
      .getAllByRole("heading", { level: 5 })
      .map((h) => h.textContent),
  ).toEqual(["OEBPS/ch2.xhtml", "OEBPS/ch1.xhtml", "OEBPS/printed.xhtml"]);
  expect(within(contents).getAllByText("Chapter 1")).toHaveLength(2);
  expect(
    within(contents).getByText("Heading 2 · Chapter 1 · #c2"),
  ).toBeTruthy();
  expect(within(contents).getByText("Outside reading order")).toBeTruthy();
  const links = within(contents).getByRole("list", {
    name: "Links in OEBPS/printed.xhtml",
  });
  expect(
    within(links)
      .getAllByRole("listitem")
      .map((li) => li.textContent),
  ).toEqual([
    "The first <script>volume</script>OEBPS/ch1.xhtml#c1",
    "Αρχή دومOEBPS/ch2.xhtml#c2",
  ]);
  expect(
    within(contents).getByText("1 external link is omitted from this view."),
  ).toBeTruthy();
  expect(
    within(contents).queryByText("https://external.invalid/private"),
  ).toBeNull();
  expect(contents.querySelector("script, img, a")).toBeNull();
  expect(within(contents).queryByText(/novel|proposed/i)).toBeNull();
});

it("retains NAV and NCX labels, flat ancestor context and exact source targets", async () => {
  const done = epub(56, { source_version: "librarium.epub-structure.v3" });
  epubJobs = [done];
  reports[done.id] = contentsReport(done.id);
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  const navigation = await screen.findByRole("region", { name: "Navigation" });
  fireEvent.click(within(navigation).getByText("2 navigation entries"));
  const items = within(navigation).getAllByRole("listitem");
  expect(items[0].textContent).toContain("Opening <img src=x>");
  expect(items[0].textContent).toContain("Within: First volume / Part one");
  expect(items[0].textContent).toContain("NAV · OEBPS/nav.xhtml");
  expect(items[0].textContent).toContain("OEBPS/ch1.xhtml#c1");
  expect(items[1].textContent).toContain("Afterword");
  expect(items[1].textContent).toContain("Top level");
  expect(items[1].textContent).toContain("NCX · OEBPS/toc.ncx");
  expect(navigation.querySelector("img, a, ol ol")).toBeNull();
});

it("keeps absent legacy labels and grouping distinct from captured empty labels", async () => {
  const done = epub(57, { source_version: "librarium.epub-structure.v3" });
  epubJobs = [done];
  const report = contentsReport(done.id);
  report.report.documents[0].headings[0].label = "";
  report.report.navigation.entries[0].label = "";
  report.report.navigation.entries[0].ancestors = [""];
  reports[done.id] = report;
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  const contents = await screen.findByRole("region", {
    name: "Contents evidence",
  });
  expect(within(contents).getByText("Unlabelled")).toBeTruthy();
  const navigation = screen.getByRole("region", { name: "Navigation" });
  fireEvent.click(within(navigation).getByText("2 navigation entries"));
  expect(within(navigation).getByText("Unlabelled")).toBeTruthy();
  expect(within(navigation).getByText("Within: Unlabelled group")).toBeTruthy();
  expect(
    within(navigation).queryByText(/Not recorded by this inspection/),
  ).toBeNull();
  cleanup();
  client.clear();
  epubJobs = [epub(57)];
  reports[done.id] = fullReport(done.id);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  const legacyContents = await screen.findByRole("region", {
    name: "Contents evidence",
  });
  expect(
    within(legacyContents).getAllByText("Not recorded by this inspection"),
  ).toHaveLength(2);
  expect(
    within(legacyContents).getByText(
      /Inspect this EPUB again to capture labels and grouping/,
    ),
  ).toBeTruthy();
  const legacyNavigation = screen.getByRole("region", { name: "Navigation" });
  fireEvent.click(within(legacyNavigation).getByText("2 navigation entries"));
  expect(
    within(legacyNavigation).getAllByText("Not recorded by this inspection"),
  ).toHaveLength(2);
  expect(
    within(legacyNavigation).getAllByText(
      "Grouping: Not recorded by this inspection",
    ),
  ).toHaveLength(2);
  expect(within(legacyNavigation).queryByText("Unlabelled")).toBeNull();
});

it("keeps labelled contents evidence accessible through the full report", async () => {
  const done = epub(58, { source_version: "librarium.epub-structure.v3" });
  epubJobs = [done];
  reports[done.id] = contentsReport(done.id);
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await screen.findByRole("region", { name: "Contents evidence" });
  fireEvent.click(screen.getByText("2 navigation entries"));
  document.querySelectorAll(".finding-details").forEach((detail) => {
    (detail as HTMLDetailsElement).open = true;
  });
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((value) => value.id)).toEqual([]);
});

it.each(["success", "error"])(
  "discards a late report %s after selecting another inspection",
  async (outcome) => {
    const first = epub(41, { title: "Earlier source A.epub" });
    const second = epub(42, {
      title: "Selected source B.epub",
      source_sha256: "d".repeat(64),
    });
    records = [first, second];
    epubJobs = [first, second];
    const pending = deferred<Response>();
    let signal: AbortSignal | undefined;
    intercept = (url, init) => {
      if (url.pathname !== `/api/epub-inspections/${first.id}/report`)
        return undefined;
      signal = init.signal ?? undefined;
      return pending.promise;
    };
    const report = fullReport(second.id);
    report.source_sha256 = second.source_sha256!;
    report.report.source_sha256 = second.source_sha256!;
    report.report.metadata = [{ name: "title", text: "Only B's report" }];
    reports[second.id] = report;
    history.replaceState(null, "", `/?view=files&fj=${first.id}`);
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load the full report" }),
    );
    await waitFor(() => expect(signal).toBeTruthy());
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another EPUB" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: second.title }));
    await screen.findByRole("heading", { name: second.title });
    const savedOldReport = contentsReport(first.id);
    const oldReport = {
      ...savedOldReport,
      report: {
        ...savedOldReport.report,
        metadata: [{ name: "title", text: "Only A's report" }],
        policy: {
          ...savedOldReport.report.policy,
          version: "librarium.epub-structure.v4",
        },
        contents_plan: {
          policy_version: "librarium.contents-plan.v1",
          source_sha256: digest,
          inspection_policy: "librarium.epub-structure.v4",
          decision: "held",
          reason_codes: ["abandoned_plan_reason"],
          existing: [],
          entries: [],
          excluded_targets: [],
          limitations: [],
          ready: false,
        },
      },
    };
    await act(async () => {
      if (outcome === "success") pending.resolve(await json(oldReport));
      else pending.reject(new TypeError("Earlier report connection failed"));
    });
    expect(screen.queryByText("Only A's report")).toBeNull();
    expect(screen.queryByText("Opening <img src=x>")).toBeNull();
    expect(screen.queryByText("The first <script>volume</script>")).toBeNull();
    expect(
      screen.queryByText("Recorded reason: abandoned_plan_reason"),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Retry the full report" }),
    ).toBeNull();
    expect(signal?.aborted).toBe(true);
    fireEvent.click(
      screen.getByRole("button", { name: "Load the full report" }),
    );
    await screen.findByText("Only B's report");
    expect(params().get("fj")).toBe(second.id);
  },
);

it("discards an in-flight report when the selected inspection's report digest changes", async () => {
  const done = epub(45);
  epubJobs = [done];
  const pending = deferred<Response>();
  let signal: AbortSignal | undefined;
  intercept = (url, init) => {
    if (url.pathname !== `/api/epub-inspections/${done.id}/report`)
      return undefined;
    signal = init.signal ?? undefined;
    return pending.promise;
  };
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await waitFor(() => expect(signal).toBeTruthy());
  const previousSignal = signal;
  epubJobs = [
    {
      ...done,
      revision: done.revision + 1,
      result: { ...done.result, report_sha256: "a".repeat(64) },
    },
  ];
  await act(async () => {
    await client.refetchQueries({ queryKey: ["jobs"] });
  });
  await screen.findByRole("button", { name: "Load the full report" });
  await act(async () => pending.resolve(await json(fullReport(done.id))));
  expect(screen.queryByText("The Glass Meridian")).toBeNull();
  expect(previousSignal?.aborted).toBe(true);
  intercept = () => undefined;
  reports[done.id] = { ...fullReport(done.id), report_sha256: "a".repeat(64) };
  fireEvent.click(screen.getByRole("button", { name: "Load the full report" }));
  await screen.findByText("The Glass Meridian");
  expect(screen.getByText("a".repeat(64))).toBeTruthy();
});

it("cancels a report read on unmount and keeps its late response out of a remounted inspection", async () => {
  const done = epub(46);
  epubJobs = [done];
  const pending = deferred<Response>();
  let signal: AbortSignal | undefined;
  intercept = (url, init) => {
    if (url.pathname !== `/api/epub-inspections/${done.id}/report`)
      return undefined;
    signal = init.signal ?? undefined;
    return pending.promise;
  };
  history.replaceState(null, "", `/?view=files&fj=${done.id}`);
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await waitFor(() => expect(signal).toBeTruthy());
  const previousSignal = signal;
  view.unmount();
  mount();
  await screen.findByRole("button", { name: "Load the full report" });
  await act(async () => pending.resolve(await json(fullReport(done.id))));
  expect(screen.queryByText("The Glass Meridian")).toBeNull();
  expect(previousSignal?.aborted).toBe(true);
});

it.each(["reset", "selection"])(
  "keeps a newer chosen file when an older recovery lookup finishes after %s",
  async (change) => {
    const oldJob = epub(43, { title: "Earlier source A.epub" });
    const pending = deferred<Response>();
    let signal: AbortSignal | undefined;
    intercept = (url, init) => {
      if (url.pathname !== "/api/epub-inspections" || init.method === "POST")
        return undefined;
      signal = init.signal ?? undefined;
      return pending.promise;
    };
    localStorage.setItem(
      "librarium-file-intent",
      JSON.stringify({
        key: oldJob.request_key,
        digest,
        name: oldJob.title,
        size: bytes.byteLength,
      }),
    );
    mount();
    await screen.findByText(/not confirmed/);
    if (change === "reset")
      fireEvent.click(
        screen.getByRole("button", { name: "Choose a different file" }),
      );
    chooseFile(
      new File([bytes], "New source B.epub", { type: "application/epub+zip" }),
    );
    await act(async () => pending.resolve(await json(oldJob)));
    expect(screen.getByText("New source B.epub")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: oldJob.title })).toBeNull();
    expect(params().get("fj")).toBeNull();
    expect(signal?.aborted).toBe(true);
    expect(inspectButton().disabled).toBe(false);
    fireEvent.click(inspectButton());
    await screen.findByRole("heading", { name: "New source B.epub" });
    expect(uploads).toHaveLength(1);
    expect(headerOf(uploads[0].init, "Idempotency-Key")).not.toBe(
      oldJob.request_key,
    );
  },
);

it.each(["success", "error"])(
  "keeps a newer unconfirmed intent after an abandoned lookup's late %s",
  async (outcome) => {
    const oldJob = epub(47);
    const pending = deferred<Response>();
    localStorage.setItem(
      "librarium-file-intent",
      JSON.stringify({
        key: oldJob.request_key,
        digest,
        name: oldJob.title,
        size: bytes.byteLength,
      }),
    );
    intercept = (url, init) => {
      if (url.pathname !== "/api/epub-inspections") return undefined;
      if (init.method === "POST") {
        uploads.push({ url, init });
        return Promise.reject(new TypeError("Upload acknowledgement lost"));
      }
      return url.searchParams.get("request_key") === oldJob.request_key
        ? pending.promise
        : undefined;
    };
    mount();
    await screen.findByText(/not confirmed/);
    fireEvent.click(
      screen.getByRole("button", { name: "Choose a different file" }),
    );
    chooseFile(
      new File([bytes], "New source B.epub", { type: "application/epub+zip" }),
    );
    fireEvent.click(inspectButton());
    await screen.findByText(/not recorded yet/);
    const saved = localStorage.getItem("librarium-file-intent");
    expect(JSON.parse(saved!).key).not.toBe(oldJob.request_key);
    await act(async () => {
      if (outcome === "success") pending.resolve(await json(oldJob));
      else pending.reject(new TypeError("Earlier lookup connection failed"));
    });
    expect(screen.getByText("New source B.epub")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry upload" })).toBeTruthy();
    expect(params().get("fj")).toBeNull();
    expect(localStorage.getItem("librarium-file-intent")).toBe(saved);
  },
);

it("leaves recovery metadata and navigation intact when a lookup finishes after unmount", async () => {
  const oldJob = epub(48);
  const saved = JSON.stringify({
    key: oldJob.request_key,
    digest,
    name: oldJob.title,
    size: bytes.byteLength,
  });
  localStorage.setItem("librarium-file-intent", saved);
  const pending = deferred<Response>();
  let signal: AbortSignal | undefined;
  intercept = (url, init) => {
    if (url.pathname !== "/api/epub-inspections" || init.method === "POST")
      return undefined;
    signal = init.signal ?? undefined;
    return pending.promise;
  };
  const view = mount();
  await screen.findByText(/not confirmed/);
  view.unmount();
  await act(async () => pending.resolve(await json(oldJob)));
  expect(params().get("fj")).toBeNull();
  expect(localStorage.getItem("librarium-file-intent")).toBe(saved);
  expect(signal?.aborted).toBe(true);
});

it.each(["initial link", "link selected before session arrives"])(
  "retains a selected inspection over stored recovery on %s",
  async (timing) => {
    const oldJob = epub(60, { title: "Earlier stored source A.epub" });
    const selectedJob = epub(61, {
      title: "Directly selected source B.epub",
      source_sha256: "d".repeat(64),
    });
    records = [selectedJob];
    epubJobs = [selectedJob];
    const saved = JSON.stringify({
      key: oldJob.request_key,
      digest,
      name: oldJob.title,
      size: bytes.byteLength,
    });
    localStorage.setItem("librarium-file-intent", saved);
    const lookup = deferred<Response>();
    const session = deferred<Response>();
    intercept = (url) => {
      if (url.pathname === "/api/epub-inspections") return lookup.promise;
      if (url.pathname === "/api/session" && timing !== "initial link")
        return session.promise;
      return undefined;
    };
    if (timing === "initial link")
      history.replaceState(null, "", `/?view=files&fj=${selectedJob.id}`);
    mount();
    if (timing !== "initial link") {
      await act(async () => {
        history.pushState(null, "", `/?view=files&fj=${selectedJob.id}`);
        window.dispatchEvent(new PopStateEvent("popstate"));
        session.resolve(
          await json({ csrf: "test-token", file_inspections: true }),
        );
      });
    }
    await screen.findByRole("heading", { name: selectedJob.title });
    await act(async () => lookup.resolve(await json(oldJob)));
    expect(params().get("fj")).toBe(selectedJob.id);
    expect(localStorage.getItem("librarium-file-intent")).toBe(saved);
    expect(
      screen.queryByText(/Checking whether the service recorded it/),
    ).toBeNull();

    intercept = () => undefined;
    epubJobs.push(oldJob);
    if (screen.queryByRole("button", { name: "Choose another EPUB" }))
      fireEvent.click(
        screen.getByRole("button", { name: "Choose another EPUB" }),
      );
    fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
    await screen.findByRole("heading", { name: oldJob.title });
    expect(localStorage.getItem("librarium-file-intent")).toBeNull();
  },
);

it.each([
  ["history selection", "success"],
  ["history selection", "error"],
  ["route change", "success"],
  ["route change", "error"],
])(
  "preserves a newer %s and stored recovery intent after a late lookup %s",
  async (navigation, outcome) => {
    const oldJob = epub(50, { title: "Recovered source A.epub" });
    const selectedJob = epub(51, {
      title: "User selected source B.epub",
      source_sha256: "d".repeat(64),
    });
    records = [selectedJob];
    epubJobs = [selectedJob];
    const saved = JSON.stringify({
      key: oldJob.request_key,
      digest,
      name: oldJob.title,
      size: bytes.byteLength,
    });
    localStorage.setItem("librarium-file-intent", saved);
    const pending = deferred<Response>();
    let signal: AbortSignal | undefined;
    intercept = (url, init) => {
      if (
        url.pathname !== "/api/epub-inspections" ||
        url.searchParams.get("request_key") !== oldJob.request_key
      )
        return undefined;
      signal = init.signal ?? undefined;
      return pending.promise;
    };
    mount();
    await screen.findByText(/not confirmed/);
    if (navigation === "history selection") {
      fireEvent.click(
        await screen.findByRole("button", { name: selectedJob.title }),
      );
    } else {
      act(() => {
        history.pushState(null, "", `/?view=files&fj=${selectedJob.id}`);
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
    }
    await screen.findByRole("heading", { name: selectedJob.title });
    expect(params().get("fj")).toBe(selectedJob.id);
    await act(async () => {
      if (outcome === "success") pending.resolve(await json(oldJob));
      else pending.reject(new TypeError("Earlier recovery connection failed"));
    });
    expect(params().get("fj")).toBe(selectedJob.id);
    expect(
      screen.getByRole("heading", { name: selectedJob.title }),
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { name: oldJob.title })).toBeNull();
    expect(localStorage.getItem("librarium-file-intent")).toBe(saved);
    expect(signal?.aborted).toBe(true);
    expect(
      screen.queryByText(/Checking whether the service recorded it/),
    ).toBeNull();

    intercept = () => undefined;
    epubJobs.push(oldJob);
    if (screen.queryByRole("button", { name: "Choose another EPUB" }))
      fireEvent.click(
        screen.getByRole("button", { name: "Choose another EPUB" }),
      );
    fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
    await screen.findByRole("heading", { name: oldJob.title });
    expect(params().get("fj")).toBe(oldJob.id);
    expect(localStorage.getItem("librarium-file-intent")).toBeNull();
  },
);

it.each(["success", "error"])(
  "preserves an unconfirmed upload across unmount and its late %s",
  async (outcome) => {
    const pending = deferred<Response>();
    let signal: AbortSignal | undefined;
    intercept = (url, init) => {
      if (url.pathname !== "/api/epub-inspections" || init.method !== "POST")
        return undefined;
      uploads.push({ url, init });
      signal = init.signal ?? undefined;
      return pending.promise;
    };
    const view = mount();
    await screen.findByLabelText("EPUB file");
    chooseFile(sampleFile());
    fireEvent.click(inspectButton());
    await waitFor(() => expect(uploads).toHaveLength(1));
    const saved = localStorage.getItem("librarium-file-intent");
    const key = headerOf(uploads[0].init, "Idempotency-Key")!;
    view.unmount();
    await act(async () => {
      if (outcome === "success")
        pending.resolve(await json(epub(49, { request_key: key }), 202));
      else pending.reject(new TypeError("Upload acknowledgement lost"));
    });
    expect(signal?.aborted).toBe(true);
    expect(params().get("fj")).toBeNull();
    expect(localStorage.getItem("librarium-file-intent")).toBe(saved);
    expect(
      calls.filter((call) => call.url.searchParams.has("request_key")),
    ).toHaveLength(0);
  },
);

it.each(["reading", "hashing"])(
  "does not persist or upload a file whose %s finishes after unmount",
  async (stage) => {
    const pending = deferred<ArrayBuffer>();
    const file = sampleFile();
    if (stage === "reading")
      vi.spyOn(file, "arrayBuffer").mockReturnValue(pending.promise);
    else vi.spyOn(crypto.subtle, "digest").mockReturnValue(pending.promise);
    const view = mount();
    await screen.findByLabelText("EPUB file");
    chooseFile(file);
    fireEvent.click(inspectButton());
    if (stage === "hashing")
      await waitFor(() => expect(crypto.subtle.digest).toHaveBeenCalled());
    view.unmount();
    await act(async () => pending.resolve(new ArrayBuffer(32)));
    expect(uploads).toHaveLength(0);
    expect(localStorage.getItem("librarium-file-intent")).toBeNull();
    expect(params().get("fj")).toBeNull();
  },
);

it("accepts an explicit recovery recheck while ignoring its superseded lookup", async () => {
  const oldJob = epub(50);
  localStorage.setItem(
    "librarium-file-intent",
    JSON.stringify({
      key: oldJob.request_key,
      digest,
      name: oldJob.title,
      size: bytes.byteLength,
    }),
  );
  const first = deferred<Response>();
  const second = deferred<Response>();
  const signals: AbortSignal[] = [];
  intercept = (url, init) => {
    if (url.pathname !== "/api/epub-inspections" || init.method === "POST")
      return undefined;
    signals.push(init.signal!);
    return signals.length === 1 ? first.promise : second.promise;
  };
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
  await waitFor(() => expect(signals).toHaveLength(2));
  expect(signals[0].aborted).toBe(true);
  epubJobs.push(oldJob);
  await act(async () => second.resolve(await json(oldJob)));
  await screen.findByRole("heading", { name: oldJob.title });
  await act(async () =>
    first.resolve(await json({ error: "Not recorded" }, 404)),
  );
  expect(screen.queryByText(/not confirmed/)).toBeNull();
  expect(params().get("fj")).toBe(oldJob.id);
  expect(localStorage.getItem("librarium-file-intent")).toBeNull();
});

it.each([409, 503, "network"])(
  "keeps a current report's %s error recoverable through an explicit retry",
  async (failure) => {
    const done = epub(51);
    epubJobs = [done];
    intercept = (url) => {
      if (url.pathname !== `/api/epub-inspections/${done.id}/report`)
        return undefined;
      return failure === "network"
        ? Promise.reject(new TypeError("Connection failed"))
        : json({ error: "Report service unavailable" }, failure as number);
    };
    history.replaceState(null, "", `/?view=files&fj=${done.id}`);
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load the full report" }),
    );
    const retry = await screen.findByRole("button", {
      name: "Retry the full report",
    });
    expect(
      screen.getByText(
        failure === 409
          ? "The report is not published yet. Refresh progress and try again."
          : failure === "network"
            ? "The report could not be read. Retry when the service is reachable."
            : "Report service unavailable",
      ),
    ).toBeTruthy();
    intercept = () => undefined;
    reports[done.id] = fullReport(done.id);
    fireEvent.click(retry);
    await screen.findByText("The Glass Meridian");
    expect(
      screen.queryByRole("button", { name: "Retry the full report" }),
    ).toBeNull();
  },
);

it("summarizes known source-check limits without repeating four separate scope clauses", async () => {
  const saved = epub(7);
  epubJobs = [saved];
  history.replaceState(null, "", `/?view=files&fj=${saved.id}`);
  mount();
  await screen.findByRole("heading", { name: saved.title });
  const structural = screen
    .getByRole("heading", { name: "Structural result" })
    .closest("section")!;
  expect(
    within(structural).getByText(
      "EPUBCheck was not run; content acceptance and readiness were not checked.",
    ),
  ).toBeTruthy();
  expect(
    within(structural).getByText(
      "This inspection cannot identify a work, confirm ownership or approve library changes.",
    ),
  ).toBeTruthy();
  expect(within(structural).queryByRole("list")).toBeNull();
});

it("presents completed structural findings with attention and never claims readiness", async () => {
  const malformed = epub(7, {
    result: {
      ...epub(7).result,
      structural_check: "failed",
      inspection_complete: false,
      findings: [
        {
          name: "Source integrity",
          ok: true,
          detail: "Length and SHA-256 match.",
        },
        {
          name: "EPUB structure",
          ok: false,
          detail: "Structural findings need review (3 recorded).",
        },
        {
          name: "Navigation",
          ok: false,
          detail: "Navigation could not be confirmed.",
        },
        { name: "Scope of this check", ok: false, detail: "Structural only." },
      ],
    },
  });
  epubJobs = [malformed];
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000007",
  );
  mount();
  await screen.findByRole("heading", { name: malformed.title });
  expect(screen.getByText("Complete", { selector: "strong" })).toBeTruthy();
  expect(screen.getByText(/Structural findings need attention/)).toBeTruthy();
  expect(screen.getByText("Attention · EPUB structure")).toBeTruthy();
  expect(screen.getByText("Passed · Source integrity")).toBeTruthy();
  expect(screen.getByText(/readiness were not checked/)).toBeTruthy();
  expect(screen.getByText(/EPUBCheck was not run/)).toBeTruthy();
  expect(screen.queryByText(/^Ready$/)).toBeNull();
  expect(screen.queryByText(/Agrees/)).toBeNull();
  expect(screen.queryByText(/identified|ownership confirmed/i)).toBeNull();
  const bare = epub(8, {
    result: { read_only: true, synthetic: false, ready: false },
  });
  epubJobs = [bare];
  cleanup();
  client.clear();
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000008",
  );
  mount();
  await screen.findByRole("heading", { name: bare.title });
  expect(screen.getByText(/Structural result not recorded/)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Load the full report" }),
  ).toBeNull();
});

it("opens an older inspection from the complete history and returns to the same page and focus", async () => {
  records = Array.from({ length: 30 }, (_, i) =>
    epub(30 - i, { title: `Archive ${30 - i}.epub` }),
  );
  history.replaceState(null, "", "/?view=files&fp=2");
  mount();
  await screen.findByText("25–30 of 30 inspections");
  const historyReads = () =>
    calls.filter((call) => call.url.pathname === "/api/jobs/history");
  expect(
    historyReads().every(
      (call) => call.url.searchParams.get("kind") === "epub",
    ),
  ).toBe(true);
  const row = screen.getByRole("button", { name: "Archive 6.epub" });
  expect(
    within(row.closest("article")!).getByText("EPUB file inspection"),
  ).toBeTruthy();
  row.focus();
  fireEvent.click(row);
  const heading = await screen.findByRole("heading", {
    name: "Archive 6.epub",
  });
  expect(params().get("fj")).toBe("11111111-1111-4111-8111-000000000006");
  expect(params().get("fp")).toBe("2");
  await waitFor(() => expect(document.activeElement).toBe(heading));
  fireEvent.click(
    screen.getByRole("button", { name: "Back to file inspections" }),
  );
  const restored = await screen.findByRole("button", {
    name: "Archive 6.epub",
  });
  expect(params().get("fj")).toBeNull();
  expect(screen.getByText("Page 2 of 2")).toBeTruthy();
  await waitFor(() => expect(document.activeElement).toBe(restored));
  const search = screen.getByRole("searchbox", {
    name: "Search file inspections",
  });
  fireEvent.change(search, { target: { value: "Archive 1" } });
  fireEvent.submit(search.closest("form")!);
  await screen.findByText("1–11 of 11 inspections");
  expect(params().get("fq")).toBe("Archive 1");
  expect(params().get("rq")).toBeNull();
});

it("labels EPUB jobs in mixed demo review history and opens them as file inspections", async () => {
  connected = false;
  records = [catalogueReview(2), epub(1, { title: "Demo upload.epub" })];
  history.replaceState(null, "", "/?view=inspections");
  mount();
  const row = await screen.findByRole("button", { name: "Demo upload.epub" });
  expect(
    within(row.closest("article")!).getByText("EPUB file inspection"),
  ).toBeTruthy();
  expect(screen.getByText("Catalogue metadata review")).toBeTruthy();
  expect(
    screen.getByText(/EPUB file inspections are labelled separately/),
  ).toBeTruthy();
  fireEvent.click(row);
  await screen.findByRole("heading", { name: "Demo upload.epub" });
  expect(params().get("view")).toBe("files");
  expect(params().get("fj")).toBe("11111111-1111-4111-8111-000000000001");
  expect(params().get("work")).toBeNull();
  expect(
    calls.some((call) => call.url.pathname.startsWith("/api/works/")),
  ).toBe(false);
  expect(screen.queryByText("Demo data")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Return to reviews" }));
  await screen.findByRole("heading", { name: "Inspection history" });
});

it("passes automated accessibility checks on the file inspection journey", async () => {
  const done = epub(5);
  epubJobs = [done];
  records = [done];
  reports[done.id] = fullReport(done.id);
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000005",
  );
  mount();
  await screen.findByRole("heading", { name: done.title });
  fireEvent.click(screen.getByRole("button", { name: "Load the full report" }));
  await screen.findByRole("heading", { name: /Reading order/ });
  fireEvent.click(screen.getByRole("button", { name: "Choose another EPUB" }));
  chooseFile(sampleFile());
  await screen.findByText("1–1 of 1 inspection");
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((value) => value.id)).toEqual([]);
});

it("queues a separate EPUBCheck explicitly and updates its URL, active count and cancellation without replacing the structural inspection", async () => {
  validationEnabled = true;
  const source = epub(1);
  epubJobs = [source];
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000001",
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Run EPUBCheck" }));
  await screen.findByText("Queued", { selector: ".epub-validation strong" });
  expect(params().get("fj")).toBe(source.id);
  expect(params().get("fv")).toBe("22222222-2222-4222-8222-000000000001");
  expect(screen.getByText("1 active")).toBeTruthy();
  expect(
    await screen.findByRole("heading", { name: source.title }),
  ).toBeTruthy();
  expect(screen.getByText(/The bounded structural checks passed/)).toBeTruthy();
  expect(source.result.epubcheck).toBe("not_run");
  expect(
    calls.filter(
      (call) =>
        call.init.method === "POST" &&
        call.url.pathname.endsWith("/validations"),
    ),
  ).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Cancel EPUBCheck" }));
  await waitFor(() =>
    expect(
      screen.getByText("Cancelled", { selector: ".epub-validation strong" }),
    ).toBeTruthy(),
  );
  expect(screen.queryByText("1 active")).toBeNull();
  expect(
    calls.some((call) => call.url.pathname.startsWith("/api/works/")),
  ).toBe(false);
});

it("reopens exact historical EPUBCheck from Reviews, keeps source history separate, and preserves the selected validation on reload", async () => {
  connected = false;
  validationEnabled = true;
  const source = epub(1);
  const saved = validation(source, 3);
  const recent = validation(source, 5, { state: "cancelled", result: {} });
  epubJobs = [source];
  records = [recent, saved];
  history.replaceState(null, "", "/?view=inspections");
  mount();
  const rows = await screen.findAllByRole("button", { name: source.title });
  expect(screen.getAllByText("EPUBCheck validation")).toHaveLength(2);
  expect(screen.queryByText("Demo data")).toBeNull();
  fireEvent.click(
    rows.find(
      (row) =>
        row.closest("article")?.id ===
        "inspection-22222222-2222-4222-8222-000000000003",
    )!,
  );
  await screen.findByText("EPUBCheck found conformance errors");
  expect(params().get("fj")).toBe(source.id);
  expect(params().get("fv")).toBe(saved.id);
  expect(
    screen.queryByText("Cancelled", { selector: ".epub-validation strong" }),
  ).toBeNull();
  cleanup();
  client.clear();
  mount();
  await screen.findByText("EPUBCheck found conformance errors");
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(0);
  expect(
    client
      .getQueryData<{ jobs: Job[] }>(["jobs", "epub"])
      ?.jobs.every((job) => job.kind === "epub"),
  ).toBe(true);
});

function declarationReport(id: string) {
  const value = fullReport(id);
  return {
    ...value,
    report: {
      ...value.report,
      policy: {
        ...value.report.policy,
        version: "librarium.epub-structure.v5",
      },
      package: { ...value.report.package, byte_sha256: "4".repeat(64) },
      metadata: [
        ...value.report.metadata,
        { name: "identifier", text: "9780306406157" },
      ],
      identifier_evidence: {
        schema_version: "librarium.epub-identifiers.v1",
        package_path: value.report.package.path,
        package_version: value.report.package.version,
        package_sha256: "4".repeat(64),
        unique_identifier: "book-id",
        prefix: null,
        entries: [
          {
            source_index: 2,
            value: "9780306406157",
            id: "book-id",
            xml_id: null,
            opf_scheme: "ISBN",
            id_count: 1,
            xml_id_count: 0,
            text_only: true,
          },
        ],
        refinements: [],
      },
    },
  };
}

it("loads raw identifier declarations through the pinned v5 full report without changing structural assurance", async () => {
  const source = epub(1, { source_version: "librarium.epub-structure.v5" });
  epubJobs = [source];
  reports[source.id] = declarationReport(source.id);
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000001",
  );
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  const raw = await screen.findByRole("region", {
    name: "Identifier declarations",
  });
  expect(within(raw).getByText("9780306406157")).toBeTruthy();
  expect(within(raw).getByText("ISBN")).toBeTruthy();
  expect(within(raw).getByText("Package source index 2")).toBeTruthy();
  expect(source.result.epubcheck).toBe("not_run");
  expect(screen.getByText("Raw report JSON")).toBeTruthy();
});

it("refuses malformed v5 identifier capture with the existing report retry path", async () => {
  const source = epub(1, { source_version: "librarium.epub-structure.v5" });
  epubJobs = [source];
  const wrong = declarationReport(source.id);
  wrong.report.identifier_evidence.package_sha256 = "0".repeat(64);
  reports[source.id] = wrong;
  history.replaceState(
    null,
    "",
    "/?view=files&fj=11111111-1111-4111-8111-000000000001",
  );
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Load the full report" }),
  );
  await screen.findByRole("button", { name: "Retry the full report" });
  expect(
    screen.queryByRole("region", { name: "Identifier declarations" }),
  ).toBeNull();
  reports[source.id] = declarationReport(source.id);
  fireEvent.click(
    screen.getByRole("button", { name: "Retry the full report" }),
  );
  await screen.findByRole("region", { name: "Identifier declarations" });
});
