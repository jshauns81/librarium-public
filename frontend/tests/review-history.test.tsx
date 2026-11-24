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
import { App } from "../src/App";
import { RETIRED_KINDS } from "../src/retired-kinds";
import type { Job } from "../src/types";
import {
  emptyWorkspaceSelection,
  type WorkspaceRoute,
} from "../src/book-workspace";

const pin = { version: "2026.10.24.2", sha256: "c".repeat(64), fixture: false };
function review(n: number, overrides: Partial<Job> = {}): Job {
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
    source_version: pin.version,
    source_sha256: pin.sha256,
    input_fingerprint: "a".repeat(64),
    result: {
      synthetic: false,
      scope: "Catalogue metadata only. Book files were not checked.",
    },
    ...overrides,
  };
}
let records: Job[], client: QueryClient, connected: boolean;
let reads: URL[];
let historyRead: ((url: URL) => Promise<Response> | undefined) | undefined;
let jobRead:
  ((url: URL, init: RequestInit) => Promise<Response> | undefined) | undefined;
let extraRead:
  ((url: URL, init: RequestInit) => Promise<Response> | undefined) | undefined;
const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));
beforeEach(() => {
  history.replaceState(null, "", "/?view=inspections");
  localStorage.clear();
  connected = true;
  records = Array.from({ length: 60 }, (_, i) => review(60 - i));
  historyRead = undefined;
  jobRead = undefined;
  extraRead = undefined;
  reads = [];
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
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(String(input), location.origin);
      reads.push(url);
      const extra = extraRead?.(url, init);
      if (extra) return extra;
      if (url.pathname === "/api/session")
        return json({
          csrf: "test-token",
          library: connected,
          file_inspections: true,
        });
      if (url.pathname === "/api/jobs/history") {
        const response = historyRead?.(url);
        if (response) return response;
        const q = url.searchParams.get("q") ?? "",
          state = url.searchParams.get("state") ?? "";
        const kind = url.searchParams.get("kind"),
          page = Number(url.searchParams.get("page") || 1);
        const matches = records.filter(
          (job) =>
            (!kind || job.kind === kind) &&
            job.title.toLowerCase().includes(q.toLowerCase()) &&
            (!state ||
              state === "all" ||
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
      if (url.pathname === "/api/jobs")
        return json({ jobs: records.slice(0, 30) });
      if (url.pathname.startsWith("/api/jobs/")) {
        const custom = jobRead?.(url, init);
        if (custom) return custom;
        const id = url.pathname.split("/").at(-1)!;
        const job = records.find((item) => item.id === id);
        if (!job) return json({ error: "Not found" }, 404);
        if (init.method === "POST") {
          Object.assign(job, {
            state: "cancelled",
            revision: job.revision + 1,
          });
        }
        return json(job);
      }
      if (url.pathname === "/api/catalogue")
        return json({ status: "ready", ...pin });
      if (url.pathname === "/api/catalogue/works")
        return json({
          snapshot: pin,
          works: [],
          total: 0,
          page: 1,
          page_size: 24,
        });
      if (url.pathname.startsWith("/api/catalogue/works/")) {
        const id = url.pathname.split("/").at(-1)!;
        return json({
          id,
          title: records.find((job) => job.work_id === id)?.title,
          authors: [],
          series: [],
          edition_count: 0,
          editions: [],
          support: [],
          synopsis: null,
          snapshot: {
            ...pin,
            version: url.searchParams.get("version"),
            sha256: url.searchParams.get("sha256"),
          },
        });
      }
      if (url.pathname.startsWith("/api/library/works/"))
        return json({
          status: "ready",
          works: [],
          coverage: "partial",
          catalogue_version: pin.version,
        });
      if (url.pathname === "/api/works")
        return json({ works: [], total: 0, page: 1, page_size: 24 });
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

const workspaceSourceId = "10000000-0000-4000-8000-000000000010";
function resumeReads(job: Job, source: string, pins: WorkspaceRoute = {}) {
  const previous = extraRead;
  extraRead = (url, init) => {
    if (
      url.pathname === "/api/book-workspaces/resolve" &&
      url.searchParams.get("job") === job.id
    )
      return json({
        schema_version: "librarium.book-workspace-resolution.v1",
        source_job_id: source,
        selection: { ...emptyWorkspaceSelection, ...pins },
      });
    if (url.pathname === `/api/epub-inspections/${source}/workspace`)
      return json(
        {
          error:
            "Saved workspace temporarily unavailable; retry this exact source.",
        },
        503,
      );
    return previous?.(url, init);
  };
}

function historyReads() {
  return reads.filter((url) => url.pathname === "/api/jobs/history");
}
async function goBack() {
  await act(async () => {
    const popped = new Promise<void>((resolve) =>
      window.addEventListener("popstate", () => resolve(), { once: true }),
    );
    history.back();
    await popped;
  });
}
function search(value: string) {
  const input = screen.getByRole("searchbox", { name: "Search reviews" });
  fireEvent.change(input, { target: { value } });
  fireEvent.submit(input.closest("form")!);
}

it.each([
  ["all", "No saved work yet", "Open book workspaces", "files"],
  ["catalogue", "No catalogue reviews yet", "Browse catalogue", "catalogue"],
  ["epub", "No file inspections yet", "Choose an EPUB", "files"],
  [
    "epub_validation",
    "No EPUBCheck validations yet",
    "Open book workspaces",
    "files",
  ],
  [
    "library_reconcile",
    "No library reconciliations yet",
    "Open book workspaces",
    "files",
  ],
  [
    "book_assessment",
    "No candidate assessments yet",
    "Open book workspaces",
    "files",
  ],
  ["retired", "No retired records", "", ""],
  ["synthetic", "No synthetic inspections yet", "", ""],
])(
  "names the empty %s history and offers its actual destination",
  async (kind, heading, action, destination) => {
    records = [];
    history.replaceState(null, "", `/?view=inspections&rk=${kind}`);
    mount();
    const empty = (
      await screen.findByRole("heading", { name: heading })
    ).closest(".empty")!;
    expect(
      within(empty as HTMLElement).queryByText(
        /Open a work to review its metadata/,
      ),
    ).toBeNull();
    if (action) {
      fireEvent.click(
        within(empty as HTMLElement).getByRole("button", { name: action }),
      );
      await waitFor(() =>
        expect(new URLSearchParams(location.search).get("view")).toBe(
          destination,
        ),
      );
      if (destination === "files")
        expect(await screen.findByLabelText("EPUB file")).toBeTruthy();
    } else {
      expect(within(empty as HTMLElement).queryByRole("button")).toBeNull();
    }
  },
);

it("keeps the local empty inspection action attached to its available chooser", async () => {
  records = [];
  history.replaceState(null, "", "/?view=files");
  mount();
  const empty = (
    await screen.findByRole("heading", { name: "No file inspections yet" })
  ).closest(".empty")!;
  fireEvent.click(
    within(empty as HTMLElement).getByRole("button", {
      name: "Choose an EPUB",
    }),
  );
  expect(document.activeElement?.id).toBe("file-input");
  expect(new URLSearchParams(location.search).get("view")).toBe("files");
});

it("does not promise a source action when file inspection is unavailable", async () => {
  records = [];
  history.replaceState(null, "", "/?view=inspections&rk=book_assessment");
  extraRead = (url) =>
    url.pathname === "/api/session"
      ? json({ csrf: "fixture", library: true, file_inspections: false })
      : undefined;
  mount();
  const empty = (
    await screen.findByRole("heading", { name: "No candidate assessments yet" })
  ).closest(".empty")!;
  expect(within(empty as HTMLElement).queryByRole("button")).toBeNull();
  expect(
    within(empty as HTMLElement).queryByText(/Choose an EPUB above/),
  ).toBeNull();
});

it("keeps filtered empty recovery scoped to its selected record kind", async () => {
  records = [];
  history.replaceState(
    null,
    "",
    "/?view=inspections&rk=book_assessment&rq=missing&rs=failed",
  );
  mount();
  await screen.findByRole("heading", {
    name: "No reviews match these filters",
  });
  fireEvent.click(screen.getByRole("button", { name: "Clear review filters" }));
  await screen.findByRole("heading", { name: "No candidate assessments yet" });
  const params = new URLSearchParams(location.search);
  expect(params.get("rk")).toBe("book_assessment");
  expect(params.get("rq")).toBeNull();
  expect(params.get("rs")).toBeNull();
});

it("offers the demo collection only for an empty synthetic history in a demo session", async () => {
  connected = false;
  records = [];
  history.replaceState(null, "", "/?view=inspections&rk=synthetic");
  mount();
  const empty = (
    await screen.findByRole("heading", { name: "No synthetic inspections yet" })
  ).closest(".empty")!;
  fireEvent.click(
    within(empty as HTMLElement).getByRole("button", {
      name: "Browse collection",
    }),
  );
  await waitFor(() =>
    expect(new URLSearchParams(location.search).get("view")).toBeNull(),
  );
});

it("pages all 60 reviews independently of the 30-job poll, searches literally, and resets state filters to page one", async () => {
  records[0] = review(60, {
    state: "failed",
    title: "A literal 100%_ title",
    message: "Pinned snapshot changed",
  });
  mount();
  await screen.findByText("1\u201324 of 60 reviews");
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("25\u201348 of 60 reviews");
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Captured title 1" });
  expect(new URLSearchParams(location.search).get("rp")).toBe("3");
  search("100%_");
  await screen.findByText("1\u20131 of 1 review");
  expect(historyReads().at(-1)!.searchParams.get("q")).toBe("100%_");
  expect(
    historyReads().every((url) => url.searchParams.get("kind") === "catalogue"),
  ).toBe(true);
  fireEvent.change(screen.getByRole("combobox", { name: "Review state" }), {
    target: { value: "failed" },
  });
  await waitFor(() =>
    expect(historyReads().at(-1)!.searchParams.get("state")).toBe("failed"),
  );
  expect(new URLSearchParams(location.search).get("rp")).toBeNull();
  search("not recorded");
  await screen.findByRole("heading", {
    name: "No reviews match these filters",
  });
  fireEvent.click(screen.getByRole("button", { name: "Clear review filters" }));
  await screen.findByText("1\u201324 of 60 reviews");
});

it("gives each expanded review a book heading and properly nested finding headings", async () => {
  records = [
    review(1, {
      result: {
        findings: [
          {
            name: "Source agreement",
            ok: false,
            detail: "Captured sources differ.",
          },
        ],
      },
    }),
  ];
  mount();
  const title = await screen.findByRole("heading", {
    name: "Captured title 1",
    level: 2,
  });
  expect(
    within(title).getByRole("button", { name: "Captured title 1" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByText("Finding details"));
  expect(
    screen.getByRole("heading", { name: "Source agreement", level: 3 }),
  ).toBeTruthy();
});

it("keeps the previous page inert through a delayed replacement and failure, then retries the requested page", async () => {
  mount();
  const old = await screen.findByRole("button", { name: "Captured title 60" });
  let finish: (response: Response) => void = () => {};
  historyRead = (url) =>
    url.searchParams.get("page") === "2"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText(/Loading page 2.*Previous results remain visible/);
  expect(old.closest("[inert]")).toBeTruthy();
  expect(old.closest("[aria-busy='true']")).toBeTruthy();
  await act(async () =>
    finish(await json({ error: "History read failed" }, 503)),
  );
  await screen.findByRole("alert");
  expect(screen.getByText(/Previous results are out of date/)).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Captured title 60" })
      .closest("[inert]"),
  ).toBeTruthy();
  historyRead = undefined;
  jobRead = undefined;
  fireEvent.click(screen.getByRole("button", { name: "Retry review history" }));
  await screen.findByText("25\u201348 of 60 reviews");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Captured title 60" }),
  ).toBeNull();
});

it("recovers an initial history failure without claiming there are no reviews", async () => {
  historyRead = () => json({ error: "History unavailable" }, 503);
  mount();
  await screen.findByRole("button", { name: "Retry review history" });
  expect(
    screen.queryByRole("heading", { name: "No catalogue reviews yet" }),
  ).toBeNull();
  historyRead = undefined;
  jobRead = undefined;
  fireEvent.click(screen.getByRole("button", { name: "Retry review history" }));
  await screen.findByText("1\u201324 of 60 reviews");
});

it.each([["catalogue", 503, "Retry review history"]] as const)(
  "keeps newer typing focused when a delayed %s retry succeeds",
  async (kind, status, label) => {
    history.replaceState(null, "", `/?view=inspections&rk=${kind}`);
    historyRead = () => json({ error: "History unavailable" }, Number(status));
    mount();
    const retry = await screen.findByRole("button", { name: label });
    let finish: (response: Response) => void = () => {};
    historyRead = () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    fireEvent.click(retry);
    await screen.findByText("Loading page 1…");
    const input = screen.getByRole("searchbox", { name: "Search reviews" });
    input.focus();
    fireEvent.change(input, { target: { value: "newer search draft" } });
    await act(async () =>
      finish(await json({ jobs: [], total: 0, page: 1, page_size: 24 })),
    );
    await screen.findByText("0 reviews");
    expect(document.activeElement).toBe(input);
    expect((input as HTMLInputElement).value).toBe("newer search draft");
  },
);

it("keeps a newer search when an obsolete history response arrives late", async () => {
  mount();
  await screen.findByText("1\u201324 of 60 reviews");
  let finish: (response: Response) => void = () => {};
  historyRead = (url) =>
    url.searchParams.get("q") === "slow"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined;
  search("slow");
  await waitFor(() =>
    expect(historyReads().at(-1)!.searchParams.get("q")).toBe("slow"),
  );
  search("title 1");
  await screen.findByText("1\u201311 of 11 reviews");
  await act(async () =>
    finish(
      await json({
        jobs: [review(999, { title: "Obsolete reply" })],
        total: 1,
        page: 1,
        page_size: 24,
      }),
    ),
  );
  expect(screen.queryByRole("button", { name: "Obsolete reply" })).toBeNull();
  expect(screen.getByText("1\u201311 of 11 reviews")).toBeTruthy();
});

it("restores filter/page on reload and Back, preserves exact reviewed snapshot links, and restores focus", async () => {
  const saved = review(25, {
    source_version: "2026.10.20.1",
    source_sha256: "d".repeat(64),
  });
  records[35] = saved;
  history.replaceState(
    null,
    "",
    "/?view=inspections&rq=Captured&rs=succeeded&rp=2",
  );
  mount();
  const button = await screen.findByRole("button", { name: saved.title });
  expect(
    (
      screen.getByRole("searchbox", {
        name: "Search reviews",
      }) as HTMLInputElement
    ).value,
  ).toBe("Captured");
  expect(screen.getByText("Page 2 of 3")).toBeTruthy();
  button.focus();
  fireEvent.click(button);
  await screen.findByRole("heading", { name: saved.title });
  const params = new URLSearchParams(location.search);
  expect(params.get("cw")).toBe(saved.work_id);
  expect(params.get("cv")).toBe(saved.source_version);
  expect(params.get("ch")).toBe(saved.source_sha256);
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: saved.title }),
    ),
  );
  await goBack();
  const back = await screen.findByRole("button", { name: saved.title });
  await waitFor(() => expect(document.activeElement).toBe(back));
  fireEvent.click(back);
  await screen.findByRole("heading", { name: saved.title });
  fireEvent.click(screen.getByRole("button", { name: "Return to reviews" }));
  const restored = await screen.findByRole("button", { name: saved.title });
  await waitFor(() => expect(document.activeElement).toBe(restored));
  expect(screen.getByText("Page 2 of 3")).toBeTruthy();
  search("title 1");
  await screen.findByText("1\u201311 of 11 reviews");
  await goBack();
  await screen.findByText("Page 2 of 3");
  expect(
    (
      screen.getByRole("searchbox", {
        name: "Search reviews",
      }) as HTMLInputElement
    ).value,
  ).toBe("Captured");
});

it("merges newer live revisions without injecting recent jobs into old pages and keeps cancellation working", async () => {
  history.replaceState(null, "", "/?view=inspections&rp=2");
  const active = review(25, {
    state: "running",
    revision: 2,
    checkpoint: 1,
    result: {},
  });
  records[35] = active;
  mount();
  const row = (
    await screen.findByRole("button", { name: active.title })
  ).closest("article")!;
  expect(within(row).getByText("1 / 4 steps")).toBeTruthy();
  await act(async () => {
    client.setQueriesData(
      { queryKey: ["jobs"] },
      {
        jobs: [
          review(25, {
            state: "running",
            revision: 3,
            checkpoint: 3,
            result: {},
          }),
          review(60),
        ],
      },
    );
  });
  await within(row).findByText("3 / 4 steps");
  expect(
    screen.queryByRole("button", { name: "Captured title 60" }),
  ).toBeNull();
  records[35] = { ...active, revision: 3, checkpoint: 3 };
  fireEvent.click(within(row).getByRole("button", { name: "Cancel review" }));
  await within(row).findByText("Cancelled");
});

it("refreshes history and moves a disappearing final active page back within its result range", async () => {
  records = records
    .slice(0, 25)
    .map((job) => ({ ...job, state: "running", revision: 2, result: {} }));
  history.replaceState(null, "", "/?view=inspections&rs=active&rp=2");
  mount();
  await screen.findByText("25\u201325 of 25 reviews");
  records = records.map((job, i) =>
    i === 24 ? { ...job, state: "succeeded", revision: 3 } : job,
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
  await screen.findByText("1\u201324 of 24 reviews");
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
});

it("explicitly labels synthetic inspections alongside catalogue reviews in demo history", async () => {
  connected = false;
  records = [
    review(2),
    review(1, { kind: "synthetic", result: { synthetic: true } }),
  ];
  mount();
  const synthetic = (
    await screen.findByRole("button", { name: "Captured title 1" })
  ).closest("article")!;
  expect(
    within(synthetic).getByText("Synthetic metadata inspection"),
  ).toBeTruthy();
  expect(screen.getByText("Catalogue metadata review")).toBeTruthy();
  expect(historyReads().at(-1)!.searchParams.has("kind")).toBe(false);
});

it.each([
  ["library_reconcile", "Library reconciliation"],
  ["book_assessment", "Book identity and duplicate assessment"],
] as const)(
  "opens %s as a selected saved record without navigating to a synthetic work",
  async (kind, label) => {
    connected = false;
    records = [
      review(1, {
        kind,
        work_id: "f".repeat(64),
        title: "Saved library check",
        result: { read_only: true, ready: false },
        message: "Saved the selected check; correction admission remains held",
      }),
    ];
    mount();
    const title = await screen.findByRole("button", {
      name: "Saved library check",
    });
    const row = title.closest("article")!;
    expect(within(row).getByText(label)).toBeTruthy();
    expect(screen.queryByText("Synthetic metadata inspection")).toBeNull();
    expect(screen.queryByText("Demo data")).toBeNull();
    fireEvent.click(title);
    const selected = await screen.findByRole("region", {
      name: "Selected library check record",
    });
    const record = within(selected).getByText("Library check record");
    expect((record.closest("details") as HTMLDetailsElement).open).toBe(true);
    expect(new URLSearchParams(location.search).get("rj")).toBe(records[0].id);
    expect(reads.some((url) => url.pathname.startsWith("/api/works/"))).toBe(
      false,
    );
    expect(
      within(row).getByText(
        "Saved the selected check; correction admission remains held",
      ),
    ).toBeTruthy();
    expect(
      within(row).getByText(
        kind === "book_assessment" ? "Catalogue digest" : "Snapshot digest",
      ),
    ).toBeTruthy();
    expect(
      reads.some((url) => url.pathname === `/api/jobs/${records[0].id}`),
    ).toBe(true);
  },
);

it("opens a book_assessment with source_job_id into the preserved file inspection and renders off-page or sparse check records without picking the latest source", async () => {
  connected = false;
  const sourceJob = review(10, {
    id: "10000000-0000-4000-8000-000000000010",
    kind: "epub",
    title: "Preserved Source 10.epub",
    work_id: "1".repeat(64),
    source_version: "librarium.epub-structure.v8",
    source_sha256: "1".repeat(64),
    result: {
      read_only: true,
      ready: false,
      structural_check: "passed",
      inspection_complete: true,
      report_sha256: "2".repeat(64),
      report_url: "/api/epub-inspections/source-epub-10/report",
    },
  });
  const boundAssessment = review(11, {
    id: "a0000000-0000-4000-8000-000000000011",
    kind: "book_assessment",
    title: "Assessment for Preserved Source 10.epub",
    work_id: "1".repeat(64),
    source_version: pin.version,
    source_sha256: "1".repeat(64),
    catalogue_version: pin.version,
    catalogue_sha256: pin.sha256,
    source_job_id: sourceJob.id,
    source_report_sha256: "2".repeat(64),
    catalogue_work_id: "w_one",
    reconciliation_key: "44444444-4444-4444-8444-444444444444",
    result: { read_only: true, ready: false },
  } as Partial<Job>);
  const sparseOffPageCheck = review(12, {
    id: "sparse-check-12",
    kind: "book_assessment",
    title: "Historical Sparse Assessment",
    work_id: "3".repeat(64),
    source_version: "",
    source_sha256: null,
    result: { read_only: true, ready: false },
  });
  resumeReads(boundAssessment, sourceJob.id, { fa: boundAssessment.id });
  records.push(boundAssessment, sourceJob, sparseOffPageCheck);
  history.replaceState(null, "", "/?view=inspections&rq=Assessment");
  mount();

  const boundRow = (
    await screen.findByRole("button", { name: boundAssessment.title })
  ).closest("article")!;
  expect(within(boundRow).getByText("Source inspection")).toBeTruthy();
  expect(within(boundRow).getByText(sourceJob.id)).toBeTruthy();
  expect(within(boundRow).getByText("Reconciliation")).toBeTruthy();
  expect(
    within(boundRow).getByText("44444444-4444-4444-8444-444444444444"),
  ).toBeTruthy();

  const sparseRow = screen
    .getByRole("button", { name: sparseOffPageCheck.title })
    .closest("article")!;
  expect(
    within(sparseRow).getAllByText("Not recorded by this historical check")
      .length,
  ).toBeGreaterThan(0);

  fireEvent.click(screen.getByRole("button", { name: boundAssessment.title }));
  await screen.findByRole("button", {
    name: "Retry saved workspace",
  });
  const params = new URLSearchParams(location.search);
  expect(params.get("view")).toBe("files");
  expect(params.get("fj")).toBe(sourceJob.id);
  expect(params.get("fa")).toBe(boundAssessment.id);
  expect(
    reads.some((url) => url.pathname === `/api/jobs/${sourceJob.id}`),
  ).toBe(true);

  fireEvent.click(screen.getByRole("button", { name: "Return to reviews" }));
  await screen.findByRole("button", { name: sparseOffPageCheck.title });

  fireEvent.click(
    screen.getByRole("button", { name: sparseOffPageCheck.title }),
  );
  const historical = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  expect(within(historical).getByText(sparseOffPageCheck.title)).toBeTruthy();
  expect(new URLSearchParams(location.search).get("view")).toBe("inspections");
  expect(new URLSearchParams(location.search).get("rj")).toBe(
    sparseOffPageCheck.id,
  );
  expect(
    reads.some(
      (url) =>
        url.pathname === "/api/book-workspaces/resolve" &&
        url.searchParams.get("job") === sparseOffPageCheck.id,
    ),
  ).toBe(false);
});

it.each(["library_reconcile", "book_assessment"] as const)(
  "shows indeterminate %s progress and preserves cancellation",
  async (kind) => {
    connected = false;
    records = [
      review(1, {
        kind,
        title: "Running library check",
        state: "running",
        checkpoint: 1,
        result: {},
      }),
    ];
    mount();
    const row = (
      await screen.findByRole("button", { name: "Running library check" })
    ).closest("article")!;
    expect(within(row).getByText("Checking")).toBeTruthy();
    expect(within(row).queryByText("1 / 4 steps")).toBeNull();
    const progress = within(row).getByRole("progressbar", {
      name: "Check progress for Running library check",
    });
    expect(progress.hasAttribute("value")).toBe(false);
    fireEvent.click(within(row).getByRole("button", { name: "Cancel check" }));
    await within(row).findByText("Cancelled");
  },
);

it("keeps paging keyboard focus while loading and moves to the new results summary", async () => {
  mount();
  await screen.findByText("1\u201324 of 60 reviews");
  const next = screen.getByRole("button", { name: "Next page" });
  next.focus();
  fireEvent.click(next);
  await screen.findByText("25\u201348 of 60 reviews");
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByText("25\u201348 of 60 reviews"),
    ),
  );
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
});

it("keeps newer typing focused when a delayed history page arrives", async () => {
  mount();
  await screen.findByText("1\u201324 of 60 reviews");
  let finish: (response: Response) => void = () => {};
  historyRead = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText(/Loading page 2/);
  const input = screen.getByRole("searchbox", { name: "Search reviews" });
  input.focus();
  fireEvent.change(input, { target: { value: "newer page draft" } });
  await act(async () =>
    finish(
      await json({
        jobs: records.slice(24, 48),
        total: 60,
        page: 2,
        page_size: 24,
      }),
    ),
  );
  await screen.findByText("25\u201348 of 60 reviews");
  expect(document.activeElement).toBe(input);
  expect((input as HTMLInputElement).value).toBe("newer page draft");
});

it("keeps a focused pager enabled during an active-job background refresh", async () => {
  records[35] = review(25, {
    state: "running",
    revision: 2,
    checkpoint: 1,
    result: {},
  });
  history.replaceState(null, "", "/?view=inspections&rp=2");
  mount();
  await screen.findByText("25\u201348 of 60 reviews");
  const previous = screen.getByRole("button", {
    name: "Previous page",
  }) as HTMLButtonElement;
  previous.focus();
  let finish: (response: Response) => void = () => {};
  historyRead = () =>
    new Promise((resolve) => {
      finish = resolve;
    });
  let pending: Promise<unknown> = Promise.resolve();
  await act(async () => {
    pending = client.refetchQueries({
      queryKey: ["review-history"],
      type: "active",
    });
    await Promise.resolve();
  });
  expect(previous.disabled).toBe(false);
  expect(document.activeElement).toBe(previous);
  await act(async () => {
    finish(
      await json({
        jobs: records.slice(24, 48),
        total: 60,
        page: 2,
        page_size: 24,
      }),
    );
    await pending;
  });
  expect(document.activeElement).toBe(previous);
});

it("filters saved assessment and reconciliation kinds explicitly and restores the selected off-page check after reload", async () => {
  const check = review(61, {
    kind: "library_reconcile",
    title: "Older reconciliation result",
    catalogue_version: pin.version,
    catalogue_sha256: pin.sha256,
    result: { read_only: true, ready: false, reconciliation: "saved-coverage" },
  });
  records.push(check);
  mount();
  await screen.findByText("1–24 of 60 reviews");
  fireEvent.change(screen.getByRole("combobox", { name: "Record kind" }), {
    target: { value: "library_reconcile" },
  });
  const title = await screen.findByRole("button", { name: check.title });
  expect(historyReads().at(-1)?.searchParams.get("kind")).toBe(
    "library_reconcile",
  );
  fireEvent.click(title);
  const selected = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  expect(within(selected).getByText(check.title)).toBeTruthy();
  expect(new URLSearchParams(location.search).get("rk")).toBe(
    "library_reconcile",
  );
  expect(new URLSearchParams(location.search).get("rj")).toBe(check.id);
  cleanup();
  client.clear();
  mount();
  const restored = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  expect(within(restored).getByText(check.title)).toBeTruthy();
  fireEvent.click(
    within(restored).getByRole("button", { name: "Close check record" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("region", { name: "Selected library check record" }),
    ).toBeNull(),
  );
  expect(new URLSearchParams(location.search).get("rj")).toBeNull();
});

it("loads and cancels a selected active check whose row is outside the current history page", async () => {
  const check = review(61, {
    kind: "library_reconcile",
    title: "Off-page active reconciliation",
    state: "running",
    revision: 2,
    checkpoint: 1,
    result: {},
  });
  records.push(check);
  history.replaceState(null, "", `/?view=inspections&rj=${check.id}`);
  mount();
  const selected = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  expect(within(selected).getByText(check.title)).toBeTruthy();
  expect(screen.queryByRole("button", { name: check.title })).toBeNull();
  fireEvent.click(
    within(selected).getByRole("button", { name: "Cancel check" }),
  );
  await within(selected).findByText("Cancelled");
  expect(records.at(-1)?.state).toBe("cancelled");
});

it("keeps a confirmed selected-check cancellation when an older progress response arrives late", async () => {
  const check = review(61, {
    kind: "library_reconcile",
    title: "Selected race reconciliation",
    state: "running",
    revision: 2,
    result: {},
  });
  records.push(check);
  history.replaceState(null, "", `/?view=inspections&rj=${check.id}`);
  mount();
  const selected = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  const old = { ...check, result: {} };
  let finish: (response: Response) => void = () => {};
  jobRead = (_url, init) =>
    !init.method
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined;
  let pending: Promise<unknown> = Promise.resolve();
  await act(async () => {
    pending = client.refetchQueries({ queryKey: ["review-check", check.id] });
    await Promise.resolve();
  });
  fireEvent.click(
    within(selected).getByRole("button", { name: "Cancel check" }),
  );
  await within(selected).findByText("Cancelled");
  await act(async () => {
    finish(await json(old));
    await pending;
  });
  expect(within(selected).getByText("Cancelled")).toBeTruthy();
  expect(
    within(selected).queryByRole("button", { name: "Cancel check" }),
  ).toBeNull();
});

it("counts an active library check while the default history stays filtered to catalogue reviews", async () => {
  records[0] = review(60, {
    kind: "library_reconcile",
    title: "Active reconciliation outside catalogue history",
    state: "running",
    result: {},
  });
  mount();
  await screen.findByRole("button", { name: "Reviews 1 active" });
  await screen.findByText("1–24 of 59 reviews");
  expect(screen.queryByRole("button", { name: records[0].title })).toBeNull();
  expect(historyReads().at(-1)?.searchParams.get("kind")).toBe("catalogue");
  expect(
    reads
      .filter((url) => url.pathname === "/api/jobs")
      .every((url) => !url.searchParams.has("kind")),
  ).toBe(true);
});

it("refuses a selected-check route that resolves to another job kind and leaves history usable", async () => {
  history.replaceState(null, "", `/?view=inspections&rj=${records[0].id}`);
  mount();
  const error = await screen.findByRole("alert");
  expect(
    within(error).getByText(/This record is not a saved library check/),
  ).toBeTruthy();
  expect(
    within(error).queryByRole("button", { name: "Retry selected check" }),
  ).toBeNull();
  expect(
    screen.queryByRole("region", { name: "Selected library check record" }),
  ).toBeNull();
  expect(screen.getByText("1–24 of 60 reviews")).toBeTruthy();
  fireEvent.click(
    within(error).getByRole("button", { name: "Close check record" }),
  );
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(new URLSearchParams(location.search).get("rj")).toBeNull();
});

it("opens a source-less historical assessment in Reviews without attempting workspace resolution", async () => {
  const assessment = review(1, {
    id: "a0000000-0000-4000-8000-000000000099",
    kind: "book_assessment",
    title: "Historical assessment without source",
  });
  records = [assessment];
  connected = false;
  extraRead = (url) =>
    url.pathname === "/api/book-workspaces/resolve"
      ? json(
          {
            error:
              "This historical check has no recorded preserved source to resume.",
          },
          404,
        )
      : undefined;
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: assessment.title }),
  );
  const selected = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  expect(within(selected).getByText(assessment.title)).toBeTruthy();
  expect(new URLSearchParams(location.search).get("view")).toBe("inspections");
  expect(new URLSearchParams(location.search).get("rj")).toBe(assessment.id);
  expect(screen.getByRole("button", { name: assessment.title })).toBeTruthy();
  expect(
    reads.some((url) => url.pathname.startsWith("/api/epub-inspections/")),
  ).toBe(false);
  expect(
    reads.some((url) => url.pathname === "/api/book-workspaces/resolve"),
  ).toBe(false);
});

it("keeps the specific source-less EPUBCheck notice without attempting workspace resolution", async () => {
  const validation = review(1, {
    id: "e0000000-0000-4000-8000-000000000099",
    kind: "epub_validation",
    title: "Historical EPUBCheck without source",
  });
  records = [validation];
  history.replaceState(null, "", "/?view=inspections&rk=all");
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: validation.title }),
  );
  await screen.findByText(
    "This EPUBCheck does not record a source inspection to reopen.",
  );
  expect(
    reads.some((url) => url.pathname === "/api/book-workspaces/resolve"),
  ).toBe(false);
  expect(new URLSearchParams(location.search).get("view")).toBe("inspections");
});

it("aborts a superseded resolve and preserves the newer historical-check notice", async () => {
  const correction = review(1, {
    id: "c0000000-0000-4000-8000-000000000098",
    kind: "epub",
    title: "Delayed preserved inspection",
  });
  const validation = review(2, {
    id: "e0000000-0000-4000-8000-000000000098",
    kind: "epub_validation",
    title: "Source-less EPUBCheck",
  });
  records = [correction, validation];
  history.replaceState(null, "", "/?view=inspections&rk=all");
  let finish!: (response: Response) => void;
  let signal: AbortSignal | null | undefined;
  extraRead = (url, init) =>
    url.pathname === "/api/book-workspaces/resolve"
      ? url.searchParams.get("job") === correction.id
        ? new Promise((resolve) => {
            finish = resolve;
            signal = init.signal;
          })
        : json({ error: "No source recorded" }, 404)
      : undefined;
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: correction.title }),
  );
  await screen.findByText("Opening preserved book workspace…");
  fireEvent.click(screen.getByRole("button", { name: validation.title }));
  await screen.findByText(
    "This EPUBCheck does not record a source inspection to reopen.",
  );
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    finish(
      await json({
        schema_version: "librarium.book-workspace-resolution.v1",
        source_job_id: workspaceSourceId,
        selection: { ...emptyWorkspaceSelection },
      }),
    ),
  );
  expect(
    screen.getByText(
      "This EPUBCheck does not record a source inspection to reopen.",
    ),
  ).toBeTruthy();
  expect(new URLSearchParams(location.search).get("view")).toBe("inspections");
  expect(new URLSearchParams(location.search).get("fj")).toBeNull();
});

it("does not let a delayed Reviews resolver navigate after the user leaves for the catalogue", async () => {
  const job = review(1, {
    id: "c0000000-0000-4000-8000-000000000099",
    kind: "epub",
    title: "Delayed saved inspection",
  });
  records = [job];
  history.replaceState(null, "", "/?view=inspections&rk=all");
  let finish!: (response: Response) => void;
  let signal: AbortSignal | null | undefined;
  extraRead = (url, init) =>
    url.pathname === "/api/book-workspaces/resolve"
      ? new Promise((resolve) => {
          finish = resolve;
          signal = init.signal;
        })
      : undefined;
  mount();
  fireEvent.click(await screen.findByRole("button", { name: job.title }));
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "Catalogue" }));
  await waitFor(() =>
    expect(new URLSearchParams(location.search).get("view")).toBe("catalogue"),
  );
  await waitFor(() => expect(signal?.aborted).toBe(true));
  expect(screen.queryByText("Opening preserved book workspace…")).toBeNull();
  await act(async () =>
    finish(
      await json({
        schema_version: "librarium.book-workspace-resolution.v1",
        source_job_id: workspaceSourceId,
        selection: { ...emptyWorkspaceSelection },
      }),
    ),
  );
  expect(new URLSearchParams(location.search).get("view")).toBe("catalogue");
  expect(new URLSearchParams(location.search).get("fj")).toBeNull();
});

it("describes mixed book history by each record's own scope", async () => {
  history.replaceState(null, "", "/?view=inspections&rk=all");
  mount();
  await screen.findByText(/Saved book work and reference reviews/);
  expect(screen.queryByText(/Reviews do not validate ebook files/)).toBeNull();
});

it("opens a saved link to a retired record as a plain record with no result or controls", async () => {
  const old = review(62, {
    kind: "epub_delivery",
    title: "Old delivery",
    state: "cancelled",
    result: {},
  });
  records.push(old);
  history.replaceState(null, "", `/?view=inspections&rj=${old.id}`);
  mount();
  const selected = await screen.findByRole("region", {
    name: "Selected library check record",
  });
  await within(selected).findByText(/A record from a retired feature/);
  expect(within(selected).queryByText("Saved check result")).toBeNull();
  expect(
    within(selected).queryByRole("button", { name: "Cancel check" }),
  ).toBeNull();
  expect(screen.queryByText(/not a saved library check/)).toBeNull();
});
