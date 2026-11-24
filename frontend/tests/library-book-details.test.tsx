// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LibraryBookDetails } from "../src/LibraryBookDetails";

const pin = { version: "2026.10.25.1", sha256: "a".repeat(64) };
const props = { workId: "w_book", ...pin, enabled: true };
const synopsis =
  "A traveller searches the archives for a forgotten expedition.";
const detail = {
  id: props.workId,
  title: "The Forgotten Expedition",
  synopsis,
  snapshot: { ...pin, fixture: false },
  ownership: "unconfirmed",
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const clients: QueryClient[] = [];

function mount(initial = props) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  clients.push(client);
  const view = (next: typeof props) => (
    <QueryClientProvider client={client}>
      <LibraryBookDetails {...next} />
    </QueryClientProvider>
  );
  return {
    ...render(view(initial)),
    update: (next: typeof props) => view(next),
  };
}

function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("does not read before opening or render anything after closing", async () => {
  const fetch = vi.fn(async () => json(detail));
  vi.stubGlobal("fetch", fetch);
  const view = mount({ ...props, enabled: false });
  expect(view.container.innerHTML).toBe("");
  expect(fetch).not.toHaveBeenCalled();
  view.rerender(view.update(props));
  await screen.findByText(synopsis);
  expect(fetch).toHaveBeenCalledTimes(1);
  view.rerender(view.update({ ...props, enabled: false }));
  expect(view.container.innerHTML).toBe("");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("requests only the exact pinned work, uses Synopsis, and makes no ownership claims", async () => {
  const workId = "w_book/edition?name=one";
  const text = synopsis.repeat(12);
  const fetch = vi.fn(async () =>
    json({ ...detail, id: workId, synopsis: text, ownership: "Owned now" }),
  );
  vi.stubGlobal("fetch", fetch);
  const view = mount({ ...props, workId });
  expect(screen.getByRole("status").textContent).toBe("Loading synopsis…");
  await screen.findByRole("region", { name: "About this book" });
  const [path, request] = fetch.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe(
    `/api/catalogue/works/${encodeURIComponent(workId)}?version=${pin.version}&sha256=${pin.sha256}`,
  );
  expect(request.method ?? "GET").toBe("GET");
  expect(request.signal).toBeInstanceOf(AbortSignal);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(view.container.firstElementChild?.className).toBe(
    "library-book-details",
  );
  expect(
    screen.getByRole("heading", { level: 2, name: "About this book" }),
  ).toBeTruthy();
  expect(screen.queryByRole("img")).toBeNull();
  expect(screen.queryByText(detail.title)).toBeNull();
  expect(screen.queryByText(/Owned now|Ownership unconfirmed/)).toBeNull();
  const expand = screen.getByRole("button", { name: "Read full synopsis" });
  fireEvent.click(expand);
  expect(
    screen
      .getByRole("button", { name: "Show less" })
      .getAttribute("aria-expanded"),
  ).toBe("true");
});

it.each([null, "", "   \n  ", undefined])(
  "quietly identifies an absent synopsis (%s)",
  async (text) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ ...detail, synopsis: text })),
    );
    mount();
    await screen.findByText("No synopsis recorded");
    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.queryByRole("region", { name: "About this book" }),
    ).toBeNull();
  },
);

it("keeps failure local and retries only this synopsis read", async () => {
  const retry = deferred();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json({ error: "Private upstream diagnostics" }, 503))
    .mockReturnValueOnce(retry.promise);
  vi.stubGlobal("fetch", fetch);
  mount();
  await screen.findByText("Synopsis unavailable");
  expect(screen.queryByText(/Private upstream diagnostics/)).toBeNull();
  expect(screen.queryByText("No synopsis recorded")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry synopsis" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][0]).toBe(fetch.mock.calls[0][0]);
  await screen.findByText("Loading synopsis…");
  expect(screen.queryByRole("button", { name: "Retry synopsis" })).toBeNull();
  await act(async () => retry.resolve(json(detail)));
  await screen.findByText(synopsis);
  expect(screen.queryByText("Synopsis unavailable")).toBeNull();
});

it.each([
  ["work ID", { ...detail, id: "w_other" }],
  [
    "version",
    { ...detail, snapshot: { ...detail.snapshot, version: "older" } },
  ],
  [
    "digest",
    { ...detail, snapshot: { ...detail.snapshot, sha256: "b".repeat(64) } },
  ],
  ["fixture", { ...detail, snapshot: { ...detail.snapshot, fixture: true } }],
  ["missing fixture marker", { ...detail, snapshot: pin }],
  ["missing snapshot", { ...detail, snapshot: null }],
  ["malformed synopsis", { ...detail, synopsis: { text: synopsis } }],
  ["null response", null],
])(
  "rejects a response with an invalid %s before displaying text",
  async (_, response) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(response)),
    );
    mount();
    await screen.findByText("Synopsis unavailable");
    expect(screen.queryByText(synopsis)).toBeNull();
    expect(screen.queryByText("No synopsis recorded")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry synopsis" })).toBeTruthy();
  },
);

it.each([
  ["work", { workId: "w_other" }],
  ["version", { version: "2026.10.26.1" }],
  ["digest", { sha256: "b".repeat(64) }],
])("isolates cached synopsis when the %s changes", async (_, change) => {
  const pending = deferred();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(detail))
    .mockReturnValueOnce(pending.promise);
  vi.stubGlobal("fetch", fetch);
  const view = mount();
  await screen.findByText(synopsis);
  const next = { ...props, ...change };
  view.rerender(view.update(next));
  expect(screen.queryByText(synopsis)).toBeNull();
  expect(screen.getByRole("status").textContent).toBe("Loading synopsis…");
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () =>
    pending.resolve(
      json({
        ...detail,
        id: next.workId,
        synopsis: "A different pinned synopsis.",
        snapshot: {
          version: next.version,
          sha256: next.sha256,
          fixture: false,
        },
      }),
    ),
  );
  await screen.findByText("A different pinned synopsis.");
  expect(screen.queryByText(synopsis)).toBeNull();
});

it("ignores a late old response while rejecting a mismatch for the new pin", async () => {
  const old = deferred();
  const current = deferred();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(current.promise),
  );
  const view = mount();
  view.rerender(view.update({ ...props, sha256: "b".repeat(64) }));
  await act(async () => old.resolve(json(detail)));
  expect(screen.queryByText(synopsis)).toBeNull();
  expect(screen.getByRole("status").textContent).toBe("Loading synopsis…");
  await act(async () => current.resolve(json(detail)));
  await screen.findByText("Synopsis unavailable");
  expect(screen.queryByText(synopsis)).toBeNull();
  expect(screen.queryByText(/owned|missing|unconfirmed/i)).toBeNull();
});

it.each(["workId", "version", "sha256"] as const)(
  "does not make an unpinned read when %s is absent",
  async (field) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    mount({ ...props, [field]: "" });
    await screen.findByText("Synopsis unavailable");
    expect(fetch).not.toHaveBeenCalled();
  },
);
