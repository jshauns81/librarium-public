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
import {
  QueryClient,
  QueryClientProvider,
  focusManager,
} from "@tanstack/react-query";
import axe from "axe-core";
import { App } from "../src/App";
import type { Job, Work } from "../src/types";

const work: Work = {
  id: "demo-00001",
  title: "The Glass Meridian",
  author: "Mara Ellison",
  series: "The Meridian Papers",
  edition_count: 1,
  synthetic: true,
  description: "Fictional metadata for interaction checks.",
  library_uuid: "synthetic-library-1",
  file_sha256: "a".repeat(64),
  library_title: "The Glass Meridian",
  library_isbn: "9780306406157",
  source_version: "synthetic-test-v9",
  fault: null,
  editions: [
    { id: "edition-1", format: "EPUB", isbn: "9780306406157", year: 2024 },
  ],
  evidence: [
    {
      source: "synthetic-catalogue",
      field: "title",
      value: "The Glass Meridian",
      native_id: "fixture-1",
      observed_at: "2026-10-24",
    },
  ],
};
const second = { ...work, id: "demo-00002", title: "A Map of Quiet Stars" };
let jobs: Job[];
let client: QueryClient;
let intercept: (
  path: string,
  init: RequestInit,
) => Promise<Response> | undefined;
const json = (value: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(value), { status }));
const job = (state = "running", revision = 2) =>
  ({
    id: "job-1",
    work_id: work.id,
    title: work.title,
    state,
    revision,
    checkpoint: 1,
    attempts: 1,
    message: "Saved source versions",
    updated_at: "2026-10-24T12:00:00Z",
    source_version: work.source_version,
    input_fingerprint: "a".repeat(64),
    result: {},
  }) as Job;

beforeEach(() => {
  history.replaceState(null, "", "/?work=demo-00001");
  localStorage.clear();
  jobs = [];
  intercept = () => undefined;
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true })),
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Element.prototype.scrollTo = vi.fn();
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
      const path = String(input);
      const response = intercept(path, init);
      if (response) return response;
      if (path === "/api/session") return json({ csrf: "test-token" });
      if (path.startsWith("/api/works/"))
        return json(path.endsWith(second.id) ? second : work);
      if (path.startsWith("/api/works?"))
        return json({
          works: [work, second],
          total: 2,
          page: 1,
          page_size: 24,
          source_versions: [work.source_version],
        });
      if (path.startsWith("/api/jobs?")) return json({ jobs });
      if (path.startsWith("/api/jobs/history?"))
        return json({ jobs, total: jobs.length, page: 1, page_size: 24 });
      throw new Error(`Unexpected request ${path}`);
    }),
  );
  client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  focusManager.setFocused(undefined);
});
async function open() {
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("button", { name: "Inspect metadata" });
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Inspect metadata",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
}

it("keeps each workspace navigation in browser history", async () => {
  await open();
  const push = vi.spyOn(history, "pushState");
  fireEvent.click(screen.getByRole("button", { name: "Inspections" }));
  expect(new URLSearchParams(location.search).get("view")).toBe("inspections");
  expect(push).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Collection" }));
  expect(new URLSearchParams(location.search).has("view")).toBe(false);
  expect(push).toHaveBeenCalledTimes(2);
});

it("changes theme without replacing the selected work or losing the route", async () => {
  await open();
  const action = screen.getByRole("button", { name: "Inspect metadata" });
  const route = location.href;
  fireEvent.change(screen.getByRole("combobox", { name: "Theme" }), {
    target: { value: "light" },
  });
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(screen.getByRole("button", { name: "Inspect metadata" })).toBe(action);
  expect(location.href).toBe(route);
});

it("bounds stalled query reads, re-enables Refresh and recovers polling", async () => {
  await open();
  vi.useFakeTimers();
  let stalled = true;
  intercept = (path, init) =>
    path.startsWith("/api/jobs?") && stalled
      ? new Promise((_resolve, reject) =>
          init.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true },
          ),
        )
      : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5500);
  });
  const refresh = screen.getByRole("button", {
    name: "Refresh progress",
  }) as HTMLButtonElement;
  expect(refresh.disabled).toBe(false);
  expect(screen.getByText(/Unable to reach the local service/)).toBeTruthy();
  stalled = false;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1600);
  });
  expect(screen.queryByText(/Unable to reach the local service/)).toBeNull();
});

it("recovers a failed session read along with the successful progress polls", async () => {
  await open();
  vi.useFakeTimers();
  let stalled = true;
  intercept = (path, init) =>
    stalled && (path.startsWith("/api/jobs?") || path === "/api/session")
      ? new Promise((_resolve, reject) =>
          init.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true },
          ),
        )
      : undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5500);
  });
  expect(screen.getByText("Offline")).toBeTruthy();
  stalled = false;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(screen.queryByText(/Unable to reach the local service/)).toBeNull();
  expect(screen.queryByText("Offline")).toBeNull();
});

it("marks paused progress as stale without inventing a connection failure", async () => {
  vi.useFakeTimers();
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(
    (
      screen.getByRole("button", {
        name: "Inspect metadata",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  focusManager.setFocused(false);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9000);
  });
  expect(screen.queryByText("Offline")).toBeNull();
  expect(screen.getByText(/Saved progress may be out of date/)).toBeTruthy();
  focusManager.setFocused(true);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(100);
  });
  expect(screen.queryByText("Offline")).toBeNull();
});

it("reconciles a lost POST response so one Inspect again creates a fresh intent", async () => {
  const keys: string[] = [];
  intercept = (path, init) => {
    if (path !== "/api/jobs" || init.method !== "POST") return;
    const key = (init.headers as Record<string, string>)["Idempotency-Key"];
    keys.push(key);
    if (keys.length === 1) {
      jobs = [{ ...job("succeeded", 6), request_key: key } as Job];
      return Promise.reject(new TypeError("Response lost"));
    }
    return json({ ...job("queued", 1), id: "job-2", request_key: key }, 202);
  };
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Inspect metadata" }));
  await screen.findByText(/Response lost/);
  fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
  fireEvent.click(await screen.findByRole("button", { name: "Inspect again" }));
  await waitFor(() => expect(keys.length).toBe(2));
  expect(keys[1]).not.toBe(keys[0]);
});

it("reports the real completion when cancellation loses the race", async () => {
  jobs = [job()];
  intercept = (path, init) =>
    path === "/api/jobs/job-1" && init.method === "POST"
      ? json(job("succeeded", 6))
      : undefined;
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Cancel inspection" }),
  );
  await screen.findByText(
    "Inspection already completed. Its saved result is available.",
  );
  expect(screen.queryByText("Inspection cancelled.")).toBeNull();
  expect(screen.getByRole("button", { name: "Inspect again" })).toBeTruthy();
});

it("keeps a polled confirmation when the original POST later loses its response", async () => {
  let rejectRequest: (reason: Error) => void = () => {};
  intercept = (path, init) => {
    if (path !== "/api/jobs" || init.method !== "POST") return;
    const key = (init.headers as Record<string, string>)["Idempotency-Key"];
    jobs = [{ ...job("succeeded", 6), request_key: key }];
    return new Promise((_resolve, reject) => {
      rejectRequest = reject;
    });
  };
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Inspect metadata" }));
  await waitFor(() => expect(jobs.length).toBe(1));
  fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
  await screen.findByText("Complete");
  await act(async () => {
    rejectRequest(new TypeError("POST response lost after confirmation"));
  });
  await screen.findByRole("button", { name: "Inspect again" });
  expect(
    screen.queryByText("POST response lost after confirmation"),
  ).toBeNull();
  expect(screen.queryByText(/Inspection was not confirmed/)).toBeNull();
  expect(
    screen.getByText(
      "Inspection already completed. Its saved result is available.",
    ),
  ).toBeTruthy();
});

it("returns focus after a failed command and clears its error on another work", async () => {
  let rejectRequest: (reason: Error) => void = () => {};
  intercept = (path, init) =>
    path === "/api/jobs" && init.method === "POST"
      ? new Promise((_resolve, reject) => {
          rejectRequest = reject;
        })
      : undefined;
  await open();
  const button = screen.getByRole("button", { name: "Inspect metadata" });
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(true),
  );
  button.blur();
  await act(async () => {
    rejectRequest(new TypeError("Fixture command failure"));
  });
  await screen.findByText("Fixture command failure");
  await waitFor(() => expect(document.activeElement).toBe(button));
  fireEvent.click(screen.getByRole("button", { name: /A Map of Quiet Stars/ }));
  await screen.findByRole("heading", { name: second.title });
  expect(screen.queryByText("Fixture command failure")).toBeNull();
});

it("leaves a newer search focus alone when a delayed command finishes", async () => {
  let resolveRequest: (value: Response) => void = () => {};
  intercept = (path, init) =>
    path === "/api/jobs" && init.method === "POST"
      ? new Promise((resolve) => {
          resolveRequest = resolve;
        })
      : undefined;
  await open();
  const button = screen.getByRole("button", { name: "Inspect metadata" });
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(true),
  );
  const search = screen.getByRole("searchbox");
  search.focus();
  fireEvent.change(search, { target: { value: "glass" } });
  await act(async () => {
    resolveRequest(await json(job("queued", 1), 202));
  });
  await screen.findByRole("button", { name: "Cancel inspection" });
  expect(document.activeElement).toBe(search);
});

it("keeps a delayed failure scoped to the work that requested it", async () => {
  let rejectRequest: (reason: Error) => void = () => {};
  intercept = (path, init) =>
    path === "/api/jobs" && init.method === "POST"
      ? new Promise((_resolve, reject) => {
          rejectRequest = reject;
        })
      : undefined;
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Inspect metadata" }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Requesting inspection…",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true),
  );
  fireEvent.click(screen.getByRole("button", { name: /A Map of Quiet Stars/ }));
  await screen.findByRole("heading", { name: second.title });
  await act(async () => {
    rejectRequest(new TypeError("Other work failure"));
  });
  expect(screen.queryByText("Other work failure")).toBeNull();
  expect(screen.queryByText(/Inspection was not confirmed/)).toBeNull();
});

it("restores the cancellation control after a failed cancellation", async () => {
  jobs = [job()];
  let rejectRequest: (reason: Error) => void = () => {};
  intercept = (path, init) =>
    path === "/api/jobs/job-1" && init.method === "POST"
      ? new Promise((_resolve, reject) => {
          rejectRequest = reject;
        })
      : undefined;
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  const button = await screen.findByRole("button", {
    name: "Cancel inspection",
  });
  button.focus();
  fireEvent.click(button);
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(true),
  );
  button.blur();
  await act(async () => {
    rejectRequest(new TypeError("Cancellation response lost"));
  });
  await screen.findByText("Cancellation response lost");
  await waitFor(() => expect(document.activeElement).toBe(button));
});

it("opens a saved result from Inspections and exposes its evidence and finding count", async () => {
  jobs = [
    {
      ...job("succeeded", 6),
      checkpoint: 4,
      result: {
        findings: [
          {
            name: "Title comparison",
            ok: false,
            detail: "Library and catalogue titles differ",
          },
          {
            name: "ISBN checksum",
            ok: true,
            detail: "Library ISBN has a valid checksum",
          },
        ],
        scope: "Metadata only. Book content was not checked.",
      },
    },
  ];
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: /Inspections/ }));
  await screen.findByRole("heading", { name: "Inspection history" });
  expect(await screen.findByText("Review · Title comparison")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: work.title }));
  await screen.findByRole("heading", { name: work.title });
  expect(screen.getByText("Source and binding")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Inspect again" })).toBeTruthy();
  expect(screen.getAllByText(work.source_version).length).toBeGreaterThan(0);
});

it("explains a fresh installation and opens catalogue setup without a false filter recovery", async () => {
  history.replaceState(null, "", "/");
  intercept = (path) =>
    path.startsWith("/api/works?")
      ? json({
          works: [],
          total: 0,
          page: 1,
          page_size: 24,
          source_versions: [],
        })
      : path === "/api/catalogue"
        ? json({ status: "not_configured" })
        : undefined;
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Your library starts here" });
  expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open catalogue" }));
  await screen.findByRole("heading", { name: "No catalogue connected" });
  expect(location.search).toContain("view=catalogue");
});

it("clears an empty search and preserves the controlled filter value", async () => {
  intercept = (path) =>
    path.startsWith("/api/works?") &&
    new URL(path, location.origin).searchParams.get("q")
      ? json({
          works: [],
          total: 0,
          page: 1,
          page_size: 24,
          source_versions: [],
        })
      : undefined;
  await open();
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "no-match" },
  });
  await screen.findByRole("heading", { name: "No works match this search" });
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(
    "no-match",
  );
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await screen.findByRole("button", { name: /The Glass Meridian/ });
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("");
});

it("uses list history for Back and restores row focus on popstate", async () => {
  history.replaceState(null, "", "/?q=before");
  history.pushState(null, "", "/");
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  const row = await screen.findByRole("button", { name: /The Glass Meridian/ });
  row.focus();
  fireEvent.click(row);
  await screen.findByRole("heading", { name: work.title });
  fireEvent.click(screen.getByRole("button", { name: "Back to collection" }));
  await waitFor(() => expect(location.search).toBe(""));
  await waitFor(() => expect(document.activeElement).toBe(row));
  await act(async () => {
    history.back();
  });
  await waitFor(() => expect(location.search).toBe("?q=before"));
  expect(screen.queryByRole("heading", { name: work.title })).toBeNull();
});

it("reports bad request details without calling them a connection failure", async () => {
  intercept = (path) =>
    path.startsWith("/api/jobs?")
      ? json({ error: "Invalid work identifier" }, 400)
      : undefined;
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByText(/Invalid work identifier/);
  expect(screen.queryByText(/Unable to reach the local service/)).toBeNull();
  expect(screen.queryByText("Offline")).toBeNull();
});

it("runs automated semantic accessibility checks on the selected-work journey", async () => {
  await open();
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((value) => value.id)).toEqual([]);
});

it("opens the connected real library without fictional-data claims or inspection controls", async () => {
  history.replaceState(null, "", "/");
  intercept = (path) =>
    path === "/api/session"
      ? json({ csrf: "test-token", library: true })
      : path === "/api/catalogue"
        ? json({ status: "not_configured" })
        : path.startsWith("/api/library?")
          ? json({
              status: "ready",
              source: "library_finish",
              catalogue_version: "2026.10.24.2",
              checked_at: null,
              coverage: "unknown",
              loading: false,
              snapshot: "a".repeat(24),
              total: 0,
              page: 1,
              page_size: 24,
              works: [],
            })
          : undefined;
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Your library" });
  await screen.findByText(/Series shelves need the published catalogue/);
  fireEvent.change(screen.getByRole("combobox", { name: "Order" }), {
    target: { value: "title" },
  });
  await screen.findByText("No matches for these filters.");
  expect(screen.getByRole("button", { name: /^Library$/ })).toBeTruthy();
  expect(screen.queryByText(/All titles.*synthetic/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Inspect metadata" })).toBeNull();
});

it("returns from catalogue evidence to the same library page, disclosure and focused row", async () => {
  const version = "2026.10.24.2",
    digest = "c".repeat(64),
    token = "b".repeat(24);
  history.replaceState(null, "", `/?lq=Meridian&lp=2&lx=title&lt=${token}`);
  const book = {
    id: "w_fixture",
    title: "Fixture Meridian",
    kind: "novel",
    authors: ["Fixture Author"],
    series: [],
    state: "direct",
    current: false,
    copies: [{ calibre_id: 41, title: "Saved title", last_known: true }],
    contained_in: [],
    candidates: [],
  };
  const catalogueWork = {
    id: book.id,
    title: book.title,
    authors: [{ id: "1", name: "Fixture Author", version }],
    series: [],
    edition_count: 0,
    type: "novel",
    first_published: null,
  };
  intercept = (path) =>
    path === "/api/session"
      ? json({ csrf: "test-token", library: true })
      : path === "/api/catalogue"
        ? json({ status: "ready", version, sha256: digest, fixture: false })
        : path.startsWith("/api/library?")
          ? json({
              status: "ready",
              catalogue_version: version,
              checked_at: null,
              coverage: "partial",
              loading: false,
              snapshot: token,
              page: 2,
              page_size: 24,
              total: 48,
              works: [book],
            })
          : path.startsWith("/api/catalogue/works/w_fixture")
            ? json({
                ...catalogueWork,
                snapshot: { version, sha256: digest, fixture: false },
                synopsis: null,
                editions: [],
                support: [],
              })
            : path.startsWith("/api/catalogue/works?")
              ? json({
                  snapshot: { version, sha256: digest, fixture: false },
                  selected_series: null,
                  selected_author: null,
                  works: [catalogueWork],
                  total: 1,
                  page: 1,
                  page_size: 24,
                })
              : undefined;
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: (name) => name.includes(book.title),
    }),
  );
  fireEvent.click(screen.getByText("Record details", { exact: true }));
  fireEvent.click(screen.getByRole("link", { name: "Catalogue evidence" }));
  await screen.findByRole("heading", { name: book.title });
  expect(history.state.libraryOrigin.route).toMatchObject({
    lq: "Meridian",
    lp: 2,
    lt: token,
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Browse author Fixture Author" }),
  );
  await screen.findByRole("button", { name: "All works" });
  fireEvent.click(
    screen.getByRole("button", { name: "Return to library results" }),
  );
  await screen.findByRole("button", {
    name: (name) => name.includes(book.title),
  });
  expect(new URLSearchParams(location.search).get("lp")).toBe("2");
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(
    "Meridian",
  );
  expect(
    screen
      .getByRole("button", { name: (name) => name.includes(book.title) })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: (name) => name.includes(book.title) }),
    ),
  );
});

const cataloguePin = {
  version: "2026.10.25.2",
  sha256: "c".repeat(64),
  fixture: false,
};
const catalogueRow = {
  id: "w_catalogue_17",
  title: "Saved catalogue title",
  authors: [
    {
      id: "17",
      name: "Catalogue Author",
      version: cataloguePin.version,
    },
  ],
  series: [],
  edition_count: 1,
  type: "novel",
  first_published: null,
};
const reviewScope =
  "Catalogue metadata only. Library ownership, book files and Calibre records were not checked.";
function catalogueJob(overrides: Partial<Job> = {}): Job {
  return {
    ...job("succeeded", 5),
    kind: "catalogue",
    id: "catalogue-review-17",
    request_key: "saved-catalogue-request",
    work_id: catalogueRow.id,
    title: catalogueRow.title,
    source_version: cataloguePin.version,
    source_sha256: cataloguePin.sha256,
    checkpoint: 4,
    message: "Captured catalogue metadata reviewed",
    result: {
      synthetic: false,
      scope: reviewScope,
      findings: [
        {
          name: "Edition ISBN checks",
          ok: false,
          status: "partial",
          detail:
            "200 of 300 editions checked. Remaining editions were not checked.",
        },
      ],
    },
    ...overrides,
  };
}
function connectedCatalogue(
  options: {
    fixture?: boolean;
    command?: (init: RequestInit) => Promise<Response>;
  } = {},
) {
  const requests: { path: string; init: RequestInit }[] = [];
  intercept = (path, init) => {
    requests.push({ path, init });
    const url = new URL(path, location.origin);
    const snapshot = {
      version: url.searchParams.get("version") || cataloguePin.version,
      sha256: url.searchParams.get("sha256") || cataloguePin.sha256,
      fixture: options.fixture ?? false,
    };
    if (path === "/api/session")
      return json({ csrf: "connected-library-csrf", library: true });
    if (path === "/api/catalogue")
      return json({
        status: "ready",
        ...cataloguePin,
        fixture: options.fixture ?? false,
      });
    if (path.startsWith("/api/catalogue/works?"))
      return json({
        snapshot,
        selected_series: null,
        selected_author: null,
        works: [
          {
            ...catalogueRow,
            authors: catalogueRow.authors.map((author) => ({
              ...author,
              version: snapshot.version,
            })),
          },
        ],
        total: 1,
        page: 1,
        page_size: 24,
      });
    if (url.pathname === `/api/catalogue/works/${catalogueRow.id}`)
      return json({
        ...catalogueRow,
        authors: catalogueRow.authors.map((author) => ({
          ...author,
          version: snapshot.version,
        })),
        snapshot,
        synopsis: null,
        editions: [],
        support: [],
      });
    if (path.startsWith("/api/library/works/"))
      return json({
        status: "ready",
        catalogue_version: snapshot.version,
        coverage: "partial",
        works: [],
      });
    if (
      path.startsWith("/api/library?") ||
      path.startsWith("/api/library/shelves?")
    )
      return json({
        status: "ready",
        catalogue_version: cataloguePin.version,
        checked_at: null,
        coverage: "partial",
        loading: false,
        snapshot: "b".repeat(24),
        works: [],
        total: 0,
        page: 1,
        page_size: 24,
      });
    if (path === "/api/jobs" && init.method === "POST")
      return options.command?.(init);
    if (path.startsWith("/api/jobs?")) {
      const workId = url.searchParams.get("work_id");
      return json({
        jobs: jobs.filter((value) => !workId || value.work_id === workId),
      });
    }
  };
  return requests;
}
function mountApp() {
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

it("places Catalogue search in the same masthead slot used by Library", async () => {
  history.replaceState(null, "", "/?view=catalogue");
  connectedCatalogue();
  const view = mountApp();
  await screen.findByRole("button", { name: new RegExp(catalogueRow.title) });
  expect(
    view.container.querySelector(
      ".masthead #workspace-search-slot input[type=search]",
    ),
  ).toBeTruthy();
  expect(
    view.container.querySelector("main .catalogue input[type=search]"),
  ).toBeNull();
});

it("loads recent jobs of every kind while retaining the default catalogue history in a connected Library session", async () => {
  history.replaceState(null, "", "/");
  jobs = [catalogueJob()];
  const requests = connectedCatalogue();
  mountApp();
  await screen.findByRole("heading", { name: "Your library" });
  fireEvent.click(screen.getByRole("button", { name: /^Reviews/ }));
  await screen.findByRole("heading", { name: "Reviews and history" });
  await screen.findByRole("button", { name: catalogueRow.title });
  const reads = requests.filter(({ path }) => path.startsWith("/api/jobs?"));
  expect(reads.length).toBeGreaterThan(0);
  expect(
    reads.every(
      ({ path }) =>
        new URL(path, location.origin).searchParams.get("kind") === null,
    ),
  ).toBe(true);
  expect(screen.queryByText(/All titles.*synthetic/)).toBeNull();
  expect(
    screen.queryByRole("heading", { name: "Inspection history" }),
  ).toBeNull();
});

it("opens the catalogue route from the empty Reviews action", async () => {
  history.replaceState(null, "", "/");
  connectedCatalogue();
  mountApp();
  await screen.findByRole("heading", { name: "Your library" });
  fireEvent.click(screen.getByRole("button", { name: /^Reviews/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Browse catalogue" }),
  );
  await screen.findByRole("button", { name: new RegExp(catalogueRow.title) });
  expect(new URLSearchParams(location.search).get("view")).toBe("catalogue");
  expect(
    screen
      .getByRole("button", { name: /^Catalogue$/ })
      .getAttribute("aria-current"),
  ).toBe("page");
  expect(screen.queryByRole("heading", { name: "Your library" })).toBeNull();
});

it("opens a saved review's exact catalogue work and original snapshot instead of the current pin", async () => {
  history.replaceState(null, "", "/");
  const saved = catalogueJob({
    source_version: "2026.10.24.1",
    source_sha256: "d".repeat(64),
  });
  jobs = [saved];
  const requests = connectedCatalogue();
  mountApp();
  await screen.findByRole("heading", { name: "Your library" });
  fireEvent.click(screen.getByRole("button", { name: /^Reviews/ }));
  fireEvent.click(await screen.findByRole("button", { name: saved.title }));
  await screen.findByRole("heading", { name: catalogueRow.title });
  const route = new URLSearchParams(location.search);
  expect(
    Object.fromEntries(
      ["view", "cw", "cv", "ch"].map((name) => [name, route.get(name)]),
    ),
  ).toEqual({
    view: "catalogue",
    cw: saved.work_id,
    cv: saved.source_version,
    ch: saved.source_sha256,
  });
  const detailRead = requests.find(
    ({ path }) =>
      new URL(path, location.origin).pathname ===
      `/api/catalogue/works/${saved.work_id}`,
  );
  expect(detailRead).toBeTruthy();
  const pin = new URL(detailRead!.path, location.origin).searchParams;
  expect(pin.get("version")).toBe(saved.source_version);
  expect(pin.get("sha256")).toBe(saved.source_sha256);
  expect(requests.some(({ path }) => path.startsWith("/api/works/"))).toBe(
    false,
  );
  expect(screen.queryByRole("heading", { name: "Your library" })).toBeNull();
});

it("returns from source selection to the same catalogue control, query, pins and scroll after discarding its target", async () => {
  history.replaceState(
    null,
    "",
    `/?view=catalogue&cm=browse&cw=${catalogueRow.id}&cv=${cataloguePin.version}&ch=${cataloguePin.sha256}&cq=Pen`,
  );
  connectedCatalogue();
  const connected = intercept;
  intercept = (path, init) =>
    path === "/api/session"
      ? json({ csrf: "fixture", library: true, file_inspections: true })
      : connected(path, init);
  mountApp();
  const compare = await screen.findByRole("button", {
    name: "Compare with an inspected EPUB",
  });
  compare.focus();
  vi.stubGlobal("scrollY", 456);
  const pane = document.querySelector<HTMLElement>(".catalogue .detail")!;
  pane.scrollTop = 210;
  document.querySelector<HTMLDetailsElement>(
    ".catalogue .snapshot-details",
  )!.open = true;
  fireEvent.click(compare);
  fireEvent.click(
    await screen.findByRole("button", { name: "Discard catalogue selection" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Return to catalogue work" }),
  );
  const restored = await screen.findByRole("button", {
    name: "Compare with an inspected EPUB",
  });
  await waitFor(() => expect(document.activeElement).toBe(restored));
  expect(window.scrollTo).toHaveBeenLastCalledWith(0, 456);
  expect(Element.prototype.scrollTo).toHaveBeenLastCalledWith(0, 210);
  expect(
    document.querySelector<HTMLDetailsElement>(".catalogue .snapshot-details")!
      .open,
  ).toBe(true);
  const route = new URLSearchParams(location.search);
  expect(route.get("cw")).toBe(catalogueRow.id);
  expect(route.get("cv")).toBe(cataloguePin.version);
  expect(route.get("ch")).toBe(cataloguePin.sha256);
  expect(route.get("cq")).toBe("Pen");
});

it.each(["focus", "scroll", "none"])(
  "respects %s intent while the selected-work return is waiting for detail",
  async (intent) => {
    history.replaceState(
      null,
      "",
      `/?view=catalogue&cm=browse&cw=${catalogueRow.id}&cv=${cataloguePin.version}&ch=${cataloguePin.sha256}`,
    );
    connectedCatalogue();
    const connected = intercept;
    let delayed = false;
    let finish: (() => void) | undefined;
    intercept = (path, init) =>
      path === "/api/session"
        ? json({ csrf: "fixture", library: true, file_inspections: true })
        : delayed && path.startsWith(`/api/catalogue/works/${catalogueRow.id}?`)
          ? new Promise<Response>((resolve) => {
              finish = () => connected(path, init)!.then(resolve);
            })
          : connected(path, init);
    const mounted = mountApp();
    const compare = await screen.findByRole("button", {
      name: "Compare with an inspected EPUB",
    });
    vi.stubGlobal("scrollY", 456);
    fireEvent.click(compare);
    await screen.findByRole("button", { name: "Return to catalogue work" });
    mounted.unmount();
    client.clear();
    delayed = true;
    mountApp();
    fireEvent.click(
      await screen.findByRole("button", { name: "Return to catalogue work" }),
    );
    await waitFor(() => expect(finish).toBeDefined());
    const search = screen.getByRole("searchbox", { name: "Search catalogue" });
    vi.mocked(window.scrollTo).mockClear();
    if (intent === "focus") search.focus();
    if (intent === "scroll") fireEvent.wheel(document);
    await act(async () => {
      finish!();
    });
    const restored = await screen.findByRole("button", {
      name: "Compare with an inspected EPUB",
    });
    await act(async () => {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
    });
    if (intent === "none") {
      await waitFor(() => expect(document.activeElement).toBe(restored));
      expect(window.scrollTo).toHaveBeenLastCalledWith(0, 456);
    } else {
      expect(document.activeElement).toBe(
        intent === "focus" ? search : document.body,
      );
      expect(window.scrollTo).not.toHaveBeenCalled();
    }
  },
);

it.each([
  ["catalogue", "none"],
  ["author", "none"],
  ["series", "none"],
  ["catalogue", "focus"],
  ["catalogue", "wheel"],
  ["catalogue", "touch"],
  ["catalogue", "keyboard"],
  ["catalogue", "pointer"],
] as const)(
  "restores the %s list after comparison and reload, respecting newer %s input",
  async (room, intent) => {
    const filter =
      room === "author" ? "&ca=1" : room === "series" ? "&cs=2" : "";
    history.replaceState(
      null,
      "",
      `/?view=catalogue&cm=browse&cv=${cataloguePin.version}&ch=${cataloguePin.sha256}&cq=Pen${filter}`,
    );
    connectedCatalogue();
    const connected = intercept;
    let delayListing = false;
    let releaseListing: (() => void) | undefined;
    intercept = (path, init) =>
      path === "/api/session"
        ? json({ csrf: "fixture", library: true, file_inspections: true })
        : delayListing && path.startsWith("/api/catalogue/works?")
          ? new Promise<Response>((resolve) => {
              releaseListing = () => connected(path, init)!.then(resolve);
            })
          : connected(path, init);
    let mounted = mountApp();
    await waitFor(() =>
      expect(
        document.getElementById(`catalogue-${catalogueRow.id}`),
      ).toBeTruthy(),
    );
    const row = document.getElementById(`catalogue-${catalogueRow.id}`)!;
    vi.stubGlobal("scrollY", 654);
    fireEvent.click(row);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Compare with an inspected EPUB",
      }),
    );
    await screen.findByRole("button", { name: "Return to catalogue work" });
    mounted.unmount();
    client.clear();
    delayListing = true;
    mounted = mountApp();
    fireEvent.click(
      await screen.findByRole("button", { name: "Return to catalogue work" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: `Back to ${room}` }),
    );
    await waitFor(() => expect(releaseListing).toBeDefined());
    await act(async () => {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
    });
    const search = screen.getByRole("searchbox", { name: "Search catalogue" });
    vi.mocked(window.scrollTo).mockClear();
    if (intent === "focus") search.focus();
    if (intent === "wheel") fireEvent.wheel(document);
    if (intent === "touch") fireEvent.touchMove(document);
    if (intent === "keyboard") fireEvent.keyDown(document, { key: "PageDown" });
    if (intent === "pointer") fireEvent.pointerDown(document);
    await act(async () => {
      releaseListing!();
    });
    if (intent !== "none") {
      await waitFor(() =>
        expect(
          document.getElementById(`catalogue-${catalogueRow.id}`),
        ).toBeTruthy(),
      );
      await act(async () => {
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => resolve()),
        );
      });
      expect(document.activeElement).toBe(
        intent === "focus" ? search : document.body,
      );
      expect(window.scrollTo).not.toHaveBeenCalled();
      return;
    }
    await waitFor(() =>
      expect(document.activeElement).toBe(
        document.getElementById(`catalogue-${catalogueRow.id}`),
      ),
    );
    expect(window.scrollTo).toHaveBeenLastCalledWith(0, 654);
    expect(new URLSearchParams(location.search).get("view")).toBe("catalogue");
    expect(new URLSearchParams(location.search).has("cw")).toBe(false);
    mounted.unmount();
  },
);

it.each(["libraryOrigin", "reviewOrigin"])(
  "retains the %s return path through source selection, reload and discard",
  async (key) => {
    const origin =
      key === "libraryOrigin"
        ? {
            route: { lq: "Meridian", lp: 2, lt: "b".repeat(24) },
            work: catalogueRow.id,
            scroll: 321,
            open: [catalogueRow.id],
          }
        : {
            route: { rq: "Meridian", rs: "succeeded", rp: 2 },
            jobId: "catalogue-review-17",
            scroll: 321,
          };
    history.replaceState(
      { [key]: origin },
      "",
      `/?view=catalogue&cm=browse&cw=${catalogueRow.id}&cv=${cataloguePin.version}&ch=${cataloguePin.sha256}`,
    );
    connectedCatalogue();
    const connected = intercept;
    intercept = (path, init) =>
      path === "/api/session"
        ? json({ csrf: "fixture", library: true, file_inspections: true })
        : connected(path, init);
    const mounted = mountApp();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Compare with an inspected EPUB",
      }),
    );
    await screen.findByRole("button", { name: "Return to catalogue work" });
    mounted.unmount();
    client.clear();
    mountApp();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Discard catalogue selection",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Return to catalogue work" }),
    );
    const returnControl = await screen.findByRole("button", {
      name:
        key === "libraryOrigin"
          ? "Return to library results"
          : "Return to reviews",
    });
    expect(history.state[key]).toEqual(origin);
    fireEvent.click(returnControl);
    expect(
      history.state[key === "libraryOrigin" ? "libraryReturn" : "reviewReturn"],
    ).toEqual(origin);
    const route = new URLSearchParams(location.search);
    expect(route.get(key === "libraryOrigin" ? "lq" : "rq")).toBe("Meridian");
    expect(route.get(key === "libraryOrigin" ? "lp" : "rp")).toBe("2");
  },
);

it.each([false, true])(
  "keeps saved review scope, partial coverage and fixture label accurate in history (fixture=%s)",
  async (fixture) => {
    history.replaceState(null, "", "/");
    jobs = [
      catalogueJob({
        result: { ...catalogueJob().result, synthetic: fixture },
      }),
    ];
    connectedCatalogue();
    mountApp();
    await screen.findByRole("heading", { name: "Your library" });
    fireEvent.click(screen.getByRole("button", { name: /^Reviews/ }));
    const row = (
      await screen.findByRole("button", { name: catalogueRow.title })
    ).closest("article")!;
    expect(within(row).getByText(reviewScope)).toBeTruthy();
    expect(within(row).getByText("Partial · Edition ISBN checks")).toBeTruthy();
    expect(
      within(row).getByText(
        "200 of 300 editions checked. Remaining editions were not checked.",
      ),
    ).toBeTruthy();
    expect(!!within(row).queryByText("Synthetic fixture review")).toBe(fixture);
    fireEvent.click(within(row).getByText("Review record"));
    expect(within(row).getByText(cataloguePin.sha256)).toBeTruthy();
    fireEvent.click(
      within(row).getByRole("button", { name: catalogueRow.title }),
    );
    const review = await screen.findByRole("region", {
      name: `Catalogue metadata review for ${catalogueRow.title}`,
    });
    await waitFor(() =>
      expect(within(review).getByText(reviewScope)).toBeTruthy(),
    );
    expect(!!within(review).queryByText("Synthetic fixture review")).toBe(
      fixture,
    );
  },
);

it.each([false, true])(
  "keeps a started review in the active count, history and refresh (leave before reply=%s)",
  async (leaveBeforeReply) => {
    history.replaceState(null, "", "/?view=catalogue");
    let finish: (response: Response) => void = () => {};
    let submitted: RequestInit | undefined;
    const requests = connectedCatalogue({
      command: (init) => {
        submitted = init;
        return new Promise((resolve) => {
          finish = resolve;
        });
      },
    });
    mountApp();
    await screen.findByRole("button", { name: /^Library$/ });
    fireEvent.click(
      await screen.findByRole("button", {
        name: new RegExp(catalogueRow.title),
      }),
    );
    const start = await screen.findByRole("button", {
      name: "Review catalogue metadata",
    });
    await waitFor(() =>
      expect((start as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(start);
    await waitFor(() => expect(submitted).toBeTruthy());
    expect(submitted!.headers).toMatchObject({
      "X-CSRFToken": "connected-library-csrf",
    });
    expect(JSON.parse(submitted!.body as string)).toEqual({
      catalogue_work_id: catalogueRow.id,
      version: cataloguePin.version,
      sha256: cataloguePin.sha256,
    });
    if (leaveBeforeReply) {
      fireEvent.click(screen.getByRole("button", { name: /^Library$/ }));
      await screen.findByRole("heading", { name: "Your library" });
    }
    const saved = catalogueJob({
      state: "queued",
      revision: 1,
      checkpoint: 0,
      request_key: (submitted!.headers as Record<string, string>)[
        "Idempotency-Key"
      ],
      result: {},
    });
    jobs = [saved];
    await act(async () => {
      finish(await json(saved, 202));
    });
    await screen.findByRole("button", { name: "Reviews 1 active" });
    if (!leaveBeforeReply) {
      fireEvent.click(screen.getByRole("button", { name: /^Library$/ }));
      await screen.findByRole("heading", { name: "Your library" });
      expect(
        screen.getByRole("button", { name: "Reviews 1 active" }),
      ).toBeTruthy();
    }
    fireEvent.click(screen.getByRole("button", { name: /^Reviews/ }));
    await screen.findByRole("button", { name: catalogueRow.title });
    expect(screen.getByText("Queued", { selector: "strong" })).toBeTruthy();
    jobs = [catalogueJob({ revision: 6, request_key: saved.request_key })];
    const before = requests.filter(({ path }) =>
      path.startsWith("/api/jobs?"),
    ).length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
    await screen.findByText("Progress refreshed.");
    expect(
      requests.filter(({ path }) => path.startsWith("/api/jobs?")).length,
    ).toBeGreaterThan(before);
    await screen.findByRole("button", { name: "Reviews" });
    expect(screen.getByText("Complete", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText(reviewScope)).toBeTruthy();
  },
);

it.each(["collection", "inspections"])(
  "keeps one demo-data label in the workspace on the synthetic %s view",
  async (view) => {
    history.replaceState(null, "", `/?view=${view}`);
    jobs = [job("succeeded", 5)];
    mountApp();
    const label = await within(screen.getByRole("main")).findByText(
      "Demo data",
    );
    expect(label.closest(".experiment, .connection")).toBeNull();
    expect(screen.getAllByText("Demo data")).toHaveLength(1);
  },
);

it("keeps technical binding fields in one closed disclosure and comparison values visible", async () => {
  await open();
  expect(within(screen.getByRole("main")).getByText("Demo data")).toBeTruthy();
  const disclosure = screen.getByText("Source and binding").closest("details")!;
  expect(disclosure.open).toBe(false);
  for (const value of [
    work.source_version,
    work.library_uuid,
    work.editions[0].id,
  ]) {
    const matches = screen.getAllByText(value, { exact: false });
    expect(matches.length).toBeGreaterThan(0);
    for (const match of matches) expect(disclosure.contains(match)).toBe(true);
  }
  const comparison = screen.getByRole("heading", {
    name: "Compare the evidence",
  }).parentElement!;
  expect(within(comparison).getAllByText(work.title)).toHaveLength(2);
  expect(within(comparison).getAllByText(work.library_isbn)).toHaveLength(2);
  fireEvent.click(screen.getByText("Source and binding"));
  expect(disclosure.open).toBe(true);
  expect(within(disclosure).getByText(work.library_uuid)).toBeTruthy();
});

it.each(["collection", "catalogue"])(
  "shows a single inline session failure and retry recovery on connected %s",
  async (view) => {
    history.replaceState(null, "", `/?view=${view}`);
    connectedCatalogue();
    mountApp();
    await screen.findByRole("button", { name: /^Library$/ });
    if (view === "catalogue")
      await screen.findByRole("button", {
        name: new RegExp(catalogueRow.title),
      });
    else await screen.findByRole("heading", { name: "Your library" });
    const connected = intercept;
    let failed = true;
    intercept = (path, init) =>
      path === "/api/session" && failed
        ? json({ error: "Session access expired" }, 403)
        : connected(path, init);
    await act(async () => {
      await client.refetchQueries({ queryKey: ["session"] });
    });
    const alert = await within(screen.getByRole("main")).findByRole("alert");
    expect(alert.textContent).toContain("Session access expired");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    const retry = within(alert).getByRole("button", { name: "Retry request" });
    expect(retry.closest(".connection")).toBeNull();
    failed = false;
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.getByRole("button", { name: /^Library$/ })).toBeTruthy();
    expect(
      new URLSearchParams(location.search).get("view") ?? "collection",
    ).toBe(view);
  },
);
