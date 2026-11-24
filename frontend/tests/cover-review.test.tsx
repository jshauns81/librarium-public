// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "../src/App";
import { CoverReview } from "../src/CoverReview";
import { coverEntry, coverQueue } from "./cover-review-fixtures";

let entries: ReturnType<typeof coverEntry>[],
  census: ReturnType<typeof coverQueue>["census"] | null;
let writes: RequestInit[], conflict: boolean, offline: boolean;
let catalogueVersion: string | null,
  changePin: boolean,
  suggestionArtwork: boolean,
  suggestionError: boolean;
const response = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));
beforeEach(() => {
  entries = [coverEntry(1), coverEntry(2, "generated"), coverEntry(3, "small")];
  census = coverQueue().census;
  writes = [];
  conflict = false;
  offline = false;
  catalogueVersion = null;
  changePin = false;
  suggestionArtwork = false;
  suggestionError = false;
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(input, location.origin);
      if (url.pathname === "/api/session")
        return response({
          csrf: "synthetic-csrf",
          library: true,
          direct_library: true,
        });
      if (url.pathname === "/api/jobs" || url.pathname === "/api/jobs/history")
        return response({ jobs: [], total: 0, page: 1, page_size: 24 });
      if (url.pathname === "/api/catalogue")
        return response(
          catalogueVersion
            ? {
                status: "ready",
                version: catalogueVersion,
                sha256: "a".repeat(64),
              }
            : { status: "not_configured" },
        );
      if (url.pathname === "/api/cover-reviews/suggestions") {
        if (suggestionError)
          return response(
            { error: "Stale snapshot", code: "snapshot_changed" },
            409,
          );
        if (changePin) {
          changePin = false;
          catalogueVersion = "test.2";
          return response(
            { code: "snapshot_changed", error: "Snapshot changed" },
            409,
          );
        }
        return response({
          inventory: "inventory",
          snapshot: { version: catalogueVersion, sha256: "a".repeat(64) },
          entries: url.searchParams.getAll("entry").map((key) => {
            const row = entries.find((e) => key === `${e.id}:${e.revision}`)!;
            return {
              id: row.id,
              revision: row.revision,
              book_id: row.book_id,
              book_uuid: row.book_uuid,
              library_uuid: row.library_uuid,
              work_id: suggestionArtwork ? "work-one" : null,
              cover: suggestionArtwork
                ? {
                    url: `/api/catalogue/covers/work-one/${"b".repeat(64)}?version=${catalogueVersion}&sha256=${"a".repeat(64)}`,
                    sha256: "b".repeat(64),
                    width: 1000,
                    height: 1500,
                  }
                : null,
            };
          }),
        });
      }
      if (url.pathname === "/api/cover-reviews/census")
        return response({
          ...coverQueue().census,
          state: "pending",
          complete: false,
        });
      if (url.pathname.endsWith("/skip")) {
        writes.push(init);
        if (offline) return Promise.reject(new Error("Connection lost"));
        if (conflict) {
          conflict = false;
          entries[0].revision++;
          return response(
            {
              error: "This review changed. Refresh it before continuing.",
              code: "conflict",
            },
            409,
          );
        }
        const row = entries.find((e) => url.pathname.includes(e.id))!;
        const body = JSON.parse(String(init.body));
        if (row.revision !== body.revision)
          return response({ error: "Conflict" }, 409);
        row.state = body.skipped ? "skipped" : "todo";
        row.revision++;
        return response(row);
      }
      if (url.pathname === "/api/cover-reviews") {
        const state = url.searchParams.get("state") ?? "todo",
          reason = url.searchParams.get("reason") ?? "";
        const matches = entries.filter(
          (e) =>
            e.state === state &&
            (!reason ||
              (reason === "small"
                ? e.facts.reasons.includes("width_below_1000")
                : e.facts.reasons.includes(reason))),
        );
        return response({
          ...coverQueue(
            matches.slice(
              (Number(url.searchParams.get("page") || 1) - 1) * 24,
              Number(url.searchParams.get("page") || 1) * 24,
            ),
          ),
          total: matches.length,
          pages: Math.max(1, Math.ceil(matches.length / 24)),
          page: Number(url.searchParams.get("page") || 1),
          census,
          state,
          reason,
          counts: Object.fromEntries(
            ["todo", "done", "skipped"].map((s) => [
              s,
              entries.filter((e) => e.state === s).length,
            ]),
          ),
        });
      }
      throw new Error(`Unexpected request ${url.pathname}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount(initialRoute = { crs: "todo", crr: "", crp: 1 }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wall() {
    const [route, setRoute] = React.useState(initialRoute);
    return (
      <CoverReview
        session={{ csrf: "synthetic-csrf" }}
        route={route}
        navigate={(patch) => setRoute((r) => ({ ...r, ...patch }))}
      />
    );
  }
  render(
    <QueryClientProvider client={client}>
      <Wall />
    </QueryClientProvider>,
  );
  return client;
}
it("shows honest empty frames, reasons, tabs, filtering and a read-only preview", async () => {
  entries.push(coverEntry(4, "small", "done"));
  mount();
  await screen.findByRole("heading", { name: "The Lantern Atlas" });
  expect(
    screen.getByLabelText("No current cover for The Lantern Atlas"),
  ).toBeTruthy();
  expect(screen.getByText("Title and author only")).toBeTruthy();
  expect(screen.getByText("600 × 900 px")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "small" },
  });
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "The Lantern Atlas" }),
    ).toBeNull(),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: /Preview current cover for The Glass Harbour/,
    }),
  );
  expect(await screen.findByRole("dialog")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /Apply|Use this cover/ }),
  ).toBeNull();
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Close preview",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: /Done 1/ }));
  expect(
    await screen.findByRole("heading", { name: "Letters from the Moon" }),
  ).toBeTruthy();
});
it("uses keyboard next/previous/skip and unskip with authenticated CAS", async () => {
  mount();
  await screen.findByRole("heading", { name: "The Lantern Atlas" });
  const first = screen.getByRole("article", { name: "The Lantern Atlas" });
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowRight" });
  const second = screen.getByRole("article", { name: "A Winter Orchard" });
  expect(document.activeElement).toBe(second);
  fireEvent.keyDown(second, { key: "ArrowLeft" });
  expect(document.activeElement).toBe(first);
  fireEvent.keyDown(first, { key: "s" });
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "The Lantern Atlas" }),
    ).toBeNull(),
  );
  expect((writes[0].headers as Record<string, string>)["X-CSRFToken"]).toBe(
    "synthetic-csrf",
  );
  expect(JSON.parse(String(writes[0].body))).toEqual({
    revision: 1,
    skipped: true,
  });
  fireEvent.click(screen.getByRole("button", { name: /Skipped 1/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Unskip The Lantern Atlas" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "The Lantern Atlas" }),
    ).toBeNull(),
  );
});
it("retains the book on conflict, refreshes its revision and accepts an explicit retry", async () => {
  conflict = true;
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Skip The Lantern Atlas" }),
  );
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "The Lantern Atlas" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Refresh review" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  fireEvent.click(
    screen.getByRole("button", { name: "Skip The Lantern Atlas" }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: "The Lantern Atlas" }),
    ).toBeNull(),
  );
  expect(JSON.parse(String(writes[1].body)).revision).toBe(2);
});
it("retries an uncertain skip with the original idempotency key", async () => {
  offline = true;
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Skip The Lantern Atlas" }),
  );
  await screen.findByRole("alert");
  offline = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry skip" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1].headers).toEqual(writes[0].headers);
});
it.each(["pending", "running", "partial", "failed", "cancelled"])(
  "never claims an empty %s census is complete",
  async (state) => {
    entries = [];
    census = {
      ...coverQueue().census,
      state,
      complete: false,
      remaining: 2,
      unresolved: 1,
    };
    mount();
    expect(
      await screen.findByText(/Check again|Checking covers/, {
        selector: "button",
      }),
    ).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.getByTestId("cover-census-status").textContent,
      ).not.toContain("Check complete"),
    );
    expect(screen.queryByText("No covers need attention.")).toBeNull();
  },
);
it("does not start a census automatically, and starts one only from Check again", async () => {
  census = null;
  entries = [];
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/census") && init?.method === "POST",
        ),
    ).toBe(true),
  );
});

it("joins the real app header and keeps review history reachable", async () => {
  history.replaceState(null, "", "/?view=covers");
  localStorage.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "The Lantern Atlas" });
  expect(screen.getByRole("button", { name: "Home" })).toBeTruthy();
  expect(screen.getByRole("navigation", { name: "Workspace" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "History" }));
  expect(new URL(location.href).searchParams.has("crs")).toBe(false);
  expect(
    await screen.findByRole("heading", { name: "Reviews and history" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Covers" }));
  expect(
    await screen.findByRole("heading", { name: "Covers to review" }),
  ).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "To do 3" }));
  fireEvent.click(screen.getByRole("button", { name: "History" }));
  expect(new URL(location.href).searchParams.has("crs")).toBe(false);
  client.clear();
});
it("uses truthful copy for a stale completed census", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) =>
      String(input).startsWith("/api/cover-reviews?")
        ? response({ ...coverQueue([]), stale: true })
        : original(input, init),
    ),
  );
  mount();
  expect(
    await screen.findByText(/Library changed since the last cover check/),
  ).toBeTruthy();
  expect(screen.queryByText("No covers need attention.")).toBeNull();
});

it("offers preview only on a readable current thumbnail and names the displayed image", async () => {
  mount();
  await screen.findByRole("heading", { name: "The Lantern Atlas" });
  expect(
    screen.queryByRole("button", {
      name: "Preview current cover for The Lantern Atlas",
    }),
  ).toBeNull();
  const preview = screen.getByRole("button", {
    name: "Preview current cover for A Winter Orchard",
  });
  expect(preview.classList.contains("cover-review-thumb")).toBe(true);
  expect(preview.querySelector("img")!.getAttribute("src")).toBe(
    entries[1].cover_url,
  );
  expect(
    screen.getByRole("img", { name: "Current cover of A Winter Orchard" }),
  ).toBeTruthy();
  expect(screen.queryByText("3 to review")).toBeNull();
  fireEvent.error(preview.querySelector("img")!);
  expect(
    screen.queryByRole("button", {
      name: "Preview current cover for A Winter Orchard",
    }),
  ).toBeNull();
});

it("keeps a focused Skip enabled and actionable throughout a background refetch", async () => {
  const client = mount();
  const button = await screen.findByRole("button", {
    name: "Skip The Lantern Atlas",
  });
  button.focus();
  const original = vi.mocked(fetch).getMockImplementation()!;
  let release!: () => void;
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).startsWith("/api/cover-reviews?")) await hold;
    return original(input, init);
  });
  const refetch = client.refetchQueries({ queryKey: ["cover-reviews"] });
  await waitFor(() =>
    expect(client.isFetching({ queryKey: ["cover-reviews"] })).toBe(1),
  );
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  expect(document.activeElement).toBe(button);
  fireEvent.keyDown(button, { key: "s" });
  await waitFor(() => expect(writes).toHaveLength(1));
  release();
  await refetch;
});

it("leaves toolbar keys alone and ignores shifted tile shortcuts", async () => {
  mount();
  const skip = await screen.findByRole("button", {
    name: "Skip The Lantern Atlas",
  });
  const check = screen.getByRole("button", { name: "Check again" });
  check.focus();
  fireEvent.keyDown(check, { key: "ArrowRight" });
  expect(document.activeElement).toBe(check);
  fireEvent.keyDown(check, { key: "s" });
  skip.focus();
  fireEvent.keyDown(skip, { key: "S", shiftKey: true });
  fireEvent.keyDown(skip, { key: "ArrowRight", shiftKey: true });
  expect(document.activeElement).toBe(skip);
  await new Promise((resolve) => setTimeout(resolve, 25));
  expect(writes).toHaveLength(0);
});

it("batches all visible tiles and refreshes the catalogue pin with a queue poll", async () => {
  catalogueVersion = "test.1";
  const client = mount();
  const suggestionCalls = () =>
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).includes("/suggestions?"));
  await waitFor(() => expect(suggestionCalls()).toHaveLength(1));
  expect(
    new URL(
      String(suggestionCalls()[0][0]),
      location.origin,
    ).searchParams.getAll("entry"),
  ).toHaveLength(3);
  expect(
    vi
      .mocked(fetch)
      .mock.calls.some(([url]) => String(url).includes("/match?")),
  ).toBe(false);
  catalogueVersion = "test.2";
  await client.refetchQueries({ queryKey: ["cover-reviews"] });
  await waitFor(() => expect(suggestionCalls()).toHaveLength(2));
  expect(String(suggestionCalls()[1][0])).toContain("version=test.2");
});

it("refreshes a changed snapshot pin and recovers suggestions without Check again", async () => {
  catalogueVersion = "test.1";
  changePin = true;
  mount();
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([url]) =>
            String(url).includes("/suggestions?") &&
            String(url).includes("version=test.2"),
        ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(screen.queryByText("Catalogue suggestion unavailable")).toBeNull(),
  );
});

it("clears and hides the reason filter on Done", async () => {
  const done = coverEntry(4, "small", "done");
  done.facts.reasons = [];
  entries.push(done);
  mount();
  await screen.findByRole("heading", { name: "The Lantern Atlas" });
  fireEvent.change(screen.getByLabelText("Show"), {
    target: { value: "missing" },
  });
  fireEvent.click(await screen.findByRole("button", { name: "Done 1" }));
  expect(
    await screen.findByRole("heading", { name: "Letters from the Moon" }),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Show")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "To do 3" }));
  await waitFor(() =>
    expect((screen.getByLabelText("Show") as HTMLSelectElement).value).toBe(""),
  );
});

it("moves across pages by keyboard and recovers when the last page disappears", async () => {
  entries = Array.from({ length: 25 }, (_, i) => coverEntry(i + 1));
  mount();
  await screen.findByRole("heading", { name: "The Lantern Atlas" });
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  const last = await screen.findByRole("article", {
    name: "Synthetic book 25",
  });
  last.focus();
  fireEvent.keyDown(last, { key: "ArrowLeft" });
  const previous = await screen.findByRole("article", {
    name: "Synthetic book 24",
  });
  await waitFor(() => expect(document.activeElement).toBe(previous));
  fireEvent.keyDown(previous, { key: "ArrowRight" });
  const again = await screen.findByRole("article", {
    name: "Synthetic book 25",
  });
  await waitFor(() => expect(document.activeElement).toBe(again));
  fireEvent.click(
    screen.getByRole("button", { name: "Skip Synthetic book 25" }),
  );
  expect(
    await screen.findByRole("heading", { name: "The Lantern Atlas" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
});

it("ignores a reason from a Done deep link", async () => {
  const done = coverEntry(4, "small", "done");
  done.facts.reasons = [];
  entries.push(done);
  mount({ crs: "done", crr: "missing", crp: 1 });
  expect(
    await screen.findByRole("heading", { name: "Letters from the Moon" }),
  ).toBeTruthy();
  expect(screen.queryByLabelText("Show")).toBeNull();
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).includes("/cover-reviews?"))
      .every(
        ([url]) =>
          new URL(String(url), location.origin).searchParams.get("reason") ===
          "",
      ),
  ).toBe(true);
});
it("shows the queue count once", async () => {
  mount();
  await screen.findByRole("button", { name: "To do 3" });
  expect(screen.queryByText("3 to review")).toBeNull();
});
it("ignores S in the toolbar and shifted S within a tile", async () => {
  mount();
  const skip = await screen.findByRole("button", {
    name: "Skip The Lantern Atlas",
  });
  fireEvent.keyDown(screen.getByRole("button", { name: "Check again" }), {
    key: "s",
  });
  skip.focus();
  fireEvent.keyDown(skip, { key: "S", shiftKey: true });
  await new Promise((resolve) => setTimeout(resolve, 25));
  expect(writes).toHaveLength(0);
});

it("names suggested art accurately, previews the current thumbnail and drops refused art", async () => {
  catalogueVersion = "test.1";
  suggestionArtwork = true;
  const client = mount();
  const suggested = await screen.findByRole("img", {
    name: "Suggested catalogue cover for A Winter Orchard",
  });
  expect(suggested.closest("button")?.getAttribute("aria-label")).toBe(
    "Choose a cover for A Winter Orchard",
  );
  const preview = screen.getByRole("button", {
    name: "Preview current cover for A Winter Orchard",
  });
  expect(preview.querySelector("img")!.getAttribute("src")).toBe(
    entries[1].cover_url,
  );
  fireEvent.click(preview);
  expect(
    within(await screen.findByRole("dialog"))
      .getByRole("img", { name: "Current cover of A Winter Orchard" })
      .getAttribute("src"),
  ).toBe(entries[1].cover_url);
  fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
  suggestionError = true;
  await client.invalidateQueries({ queryKey: ["cover-suggestions"] });
  await waitFor(() =>
    expect(
      screen.queryByRole("img", {
        name: "Suggested catalogue cover for A Winter Orchard",
      }),
    ).toBeNull(),
  );
});
