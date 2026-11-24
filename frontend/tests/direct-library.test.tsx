// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { DirectLibrary, type DirectLibraryRoute } from "../src/DirectLibrary";
import { App } from "../src/App";
import { emptyWorkspaceSelection } from "../src/book-workspace";

const inventory = {
  token: "a".repeat(64),
  observed_at: "2026-10-28T12:00:00Z",
  scope: "metadata",
};
const book = {
  id: "41",
  title: "Fixture: The Glass Meridian",
  authors: ["Fixture Author"],
  series: "Fixture Archive",
  series_index: 2,
  publisher: "Fixture Press",
  published_at: "2024-01-01",
  languages: ["eng"],
  identifiers: [{ type: "isbn", value: "9780306406157" }],
  formats: [
    {
      format: "EPUB",
      name: "Fixture - Fixture Author",
      size_bytes: 12345,
      available: true,
    },
  ],
  cover: {
    url: `/api/direct-library/books/41/cover?inventory=${inventory.token}`,
    media_type: "image/jpeg",
    width: 300,
    height: 450,
  },
  description: "A fixture synopsis.",
};
const listing = {
  configured: true,
  source: "calibre",
  read_only: true,
  inventory,
  total: 25,
  page: 1,
  pages: 2,
  page_size: 24,
  books: [book],
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
let intercept: (url: string) => Response | Promise<Response> | undefined;
let calls: string[];
beforeEach(() => {
  calls = [];
  intercept = () => undefined;
  history.replaceState(null, "", "/");
  localStorage.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true })),
  );
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return (
        intercept(url) ??
        (url.startsWith("/api/direct-library/books/")
          ? json({ inventory, book })
          : url.startsWith("/api/direct-library?")
            ? json(listing)
            : url === "/api/session"
              ? json({ csrf: "fixture", library: true, direct_library: true })
              : url.startsWith("/api/jobs")
                ? json({ jobs: [] })
                : json({ error: "Unexpected request" }, 404))
      );
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function mount(
  initial: Partial<DirectLibraryRoute> = {},
  inspectBook?: React.ComponentProps<typeof DirectLibrary>["inspectBook"],
  extra: Partial<React.ComponentProps<typeof DirectLibrary>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Harness() {
    const [route, setRoute] = useState<DirectLibraryRoute>({
      lq: "",
      lp: 1,
      lt: "",
      lw: "",
      ld: "",
      ...initial,
    });
    return (
      <DirectLibrary
        route={route}
        navigate={(next) => setRoute((old) => ({ ...old, ...next }))}
        inspectBook={inspectBook}
        {...extra}
      />
    );
  }
  const view = render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

it("keeps the catalogue selection and search when returning through workspace navigation", async () => {
  history.replaceState(
    null,
    "",
    "/?cq=meridian&cw=work-41&cv=fixture-v1&ch=" + "c".repeat(64),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Library" });
  fireEvent.click(screen.getByRole("button", { name: "Catalogue" }));
  const params = new URLSearchParams(location.search);
  expect(params.get("cq")).toBe("meridian");
  expect(params.get("cw")).toBe("work-41");
  expect(params.get("cv")).toBe("fixture-v1");
  view.unmount();
  client.clear();
});

it("opens native books, their real formats and plain description with no Index reads", async () => {
  const inspect = vi.fn();
  mount({}, inspect);
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  expect(await screen.findByRole("heading", { name: book.title })).toBeTruthy();
  expect(
    screen.getByText(
      (_, node) =>
        node?.classList.contains("blurb") === true &&
        node.textContent === "AA fixture synopsis.",
    ),
  ).toBeTruthy();
  expect(screen.getByText("Fixture - Fixture Author")).toBeTruthy();
  expect(screen.getByText("Available")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Start a new EPUB inspection" }),
  );
  expect(inspect).toHaveBeenCalledWith(book, inventory);
  // The book page reads the library and the catalogue snapshot, never the Index.
  expect(
    calls.every(
      (url) =>
        url.startsWith("/api/direct-library") || url === "/api/catalogue",
    ),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Back to library" }));
  await waitFor(() =>
    expect(document.activeElement?.id).toBe("direct-book-41"),
  );
});

it("returns focus to the library row when a selected book was restored without a local selection click", async () => {
  mount({ lw: book.id, lt: inventory.token });
  await screen.findByRole("heading", { name: book.title });
  fireEvent.click(screen.getByRole("button", { name: "Back to library" }));
  await waitFor(() =>
    expect(document.activeElement?.id).toBe(`direct-book-${book.id}`),
  );
});

it("does not steal focus from a newer search edit after Clear search finishes loading", async () => {
  intercept = (url) =>
    url.startsWith("/api/direct-library?")
      ? json({ ...listing, total: 0, pages: 1, books: [] })
      : undefined;
  mount({ lq: "no result", lt: inventory.token });
  const clear = await screen.findByRole("button", { name: "Clear search" });
  await waitFor(() =>
    expect((clear as HTMLButtonElement).disabled).toBe(false),
  );
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>((done) => {
    resolve = done;
  });
  intercept = (url) =>
    url.startsWith("/api/direct-library?") ? pending : undefined;
  fireEvent.click(clear);
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.startsWith("/api/direct-library?") &&
          new URL(url, location.origin).searchParams.get("q") === "",
      ),
    ).toBe(true),
  );
  const input = screen.getByRole("searchbox", { name: "Search library" });
  act(() => {
    input.focus();
    fireEvent.change(input, { target: { value: "new draft" } });
  });
  await act(async () => resolve(json(listing)));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  expect(document.activeElement).toBe(input);
  expect((input as HTMLInputElement).value).toBe("new draft");
});

it("searches literally, resets paging and retains the inventory pin", async () => {
  mount({ lp: 2, lt: inventory.token });
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  fireEvent.change(screen.getByLabelText("Search library"), {
    target: { value: "100% _" },
  });
  fireEvent.submit(screen.getByRole("search"));
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("q=100%25+_") &&
          url.includes("page=1") &&
          url.includes(`inventory=${inventory.token}`),
      ),
    ).toBe(true),
  );
});

it.each([null, "2016-11-15 00:00:00.000000"])(
  "shows the recorded publication value or its absence (%s)",
  async (published) => {
    intercept = (url) =>
      url.startsWith("/api/direct-library/books/")
        ? json({ inventory, book: { ...book, published_at: published } })
        : undefined;
    mount({ lw: book.id, lt: inventory.token, ld: "1" });
    await screen.findByRole("heading", { name: book.title });
    expect(screen.getByText("Published").nextElementSibling?.textContent).toBe(
      published ?? "Not recorded",
    );
  },
);

it("requires an explicit refresh after inventory change and clears stale detail", async () => {
  intercept = (url) =>
    url.includes("inventory=")
      ? json(
          { error: "Library metadata changed", code: "direct_library_changed" },
          409,
        )
      : undefined;
  mount({ lt: "old", lw: "41", ld: "1" });
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: book.title })).toBeNull();
  intercept = () => undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh library" }));
  expect(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
  expect(screen.queryByRole("heading", { name: book.title })).toBeNull();
});

it("offers retry and honest empty states; failed covers fall back to their title", async () => {
  intercept = () => json({ error: "Library unavailable" }, 503);
  mount();
  expect(await screen.findByRole("alert")).toBeTruthy();
  intercept = () => json({ ...listing, total: 0, pages: 1, books: [] });
  fireEvent.click(screen.getByRole("button", { name: "Retry library" }));
  expect(
    await screen.findByRole("heading", { name: "No books in this library" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
  intercept = () => undefined;
  fireEvent.click(screen.getByRole("button", { name: "Refresh library" }));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  fireEvent.error(document.querySelector(".direct-cover")!);
  expect(document.querySelector(".direct-cover")).toBeNull();
  expect(
    screen.getByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
});

it("clears a native no-match search without changing the inventory", async () => {
  intercept = (url) => {
    if (!url.startsWith("/api/direct-library?")) return undefined;
    const params = new URL(url, "https://example.test").searchParams;
    return params.get("q")
      ? json({ ...listing, total: 0, pages: 1, books: [] })
      : undefined;
  };
  mount({ lq: "missing fixture", lt: inventory.token });
  expect(
    await screen.findByRole("heading", { name: "No books match this search" }),
  ).toBeTruthy();
  expect(screen.queryByText("No books in this library")).toBeNull();
  const clear = screen.getByRole("button", { name: "Clear search" });
  clear.focus();
  fireEvent.click(clear);
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  expect(
    (screen.getByLabelText("Search library") as HTMLInputElement).value,
  ).toBe("");
  const lastRead = calls
    .filter((url) => url.startsWith("/api/direct-library?"))
    .at(-1)!;
  const params = new URL(lastRead, "https://example.test").searchParams;
  expect(params.get("q")).toBe("");
  expect(params.get("page")).toBe("1");
  expect(params.get("inventory")).toBe(inventory.token);
  await waitFor(() =>
    expect(document.activeElement?.className).toBe("direct-summary"),
  );
});

it("returns an empty later native page to the first page under the same search and inventory", async () => {
  intercept = (url) => {
    if (!url.startsWith("/api/direct-library?")) return undefined;
    const params = new URL(url, "https://example.test").searchParams;
    return params.get("page") === "3"
      ? json({ ...listing, page: 3, books: [] })
      : undefined;
  };
  mount({ lq: "meridian", lp: 3, lt: inventory.token });
  expect(
    await screen.findByRole("heading", { name: "No books on this page" }),
  ).toBeTruthy();
  expect(screen.queryByText("No books match this search")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "First page" }));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  const lastRead = calls
    .filter((url) => url.startsWith("/api/direct-library?"))
    .at(-1)!;
  const params = new URL(lastRead, "https://example.test").searchParams;
  expect(params.get("q")).toBe("meridian");
  expect(params.get("page")).toBe("1");
  expect(params.get("inventory")).toBe(inventory.token);
  await waitFor(() =>
    expect(document.activeElement?.className).toBe("direct-summary"),
  );
});

it("refreshes native Library from page one while preserving the search and clearing old detail", async () => {
  const fresh = { ...inventory, token: "b".repeat(64) };
  let refreshed = false;
  intercept = (url) =>
    refreshed && url.startsWith("/api/direct-library?")
      ? json({ ...listing, inventory: fresh, total: 1, page: 1, pages: 1 })
      : undefined;
  mount({ lq: "meridian", lp: 2, lt: inventory.token, lw: book.id, ld: "1" });
  await screen.findByRole("heading", { name: book.title });
  calls.length = 0;
  refreshed = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh library" }));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  await waitFor(() =>
    expect(calls.some((url) => url.includes(`inventory=${fresh.token}`))).toBe(
      true,
    ),
  );
  const reads = calls.filter((url) => url.startsWith("/api/direct-library?"));
  expect(reads.length).toBeGreaterThan(0);
  expect(
    reads.every(
      (url) =>
        new URL(url, "https://example.test").searchParams.get("page") === "1",
    ),
  ).toBe(true);
  expect(
    (screen.getByLabelText("Search library") as HTMLInputElement).value,
  ).toBe("meridian");
  expect(screen.queryByRole("heading", { name: book.title })).toBeNull();
});

it("keeps native details accessible and lists missing files truthfully", async () => {
  intercept = (url) =>
    url.startsWith("/api/direct-library/books/")
      ? json({
          inventory,
          book: {
            ...book,
            formats: [{ ...book.formats[0], available: false }],
          },
        })
      : undefined;
  const { container } = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  expect(await screen.findByText("Unavailable")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Start a new EPUB inspection" }),
  ).toBeNull();
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

it("App prefers direct library over the saved Index adapter", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
  expect(calls.some((url) => url.startsWith("/api/library"))).toBe(false);
});

it("keeps an uncertain native inspection retry bound to its original request key", async () => {
  intercept = (url) =>
    url === "/api/session"
      ? json({
          csrf: "fixture-csrf",
          library: true,
          direct_library: true,
          file_inspections: true,
        })
      : url.endsWith("/inspect")
        ? json({ error: "Temporary failure" }, 503)
        : undefined;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Start a new EPUB inspection" }),
  );
  expect(await screen.findByText(/Inspection was not confirmed/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry inspection" }));
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.filter(([url]) => String(url).endsWith("/inspect")).length,
    ).toBe(2),
  );
  const posts = vi
    .mocked(fetch)
    .mock.calls.filter(([url]) => String(url).endsWith("/inspect"));
  expect(
    (posts[0][1]?.headers as Record<string, string>)["Idempotency-Key"],
  ).toBe((posts[1][1]?.headers as Record<string, string>)["Idempotency-Key"]);
  expect((posts[0][1]?.headers as Record<string, string>)["X-CSRFToken"]).toBe(
    "fixture-csrf",
  );
  expect(posts[0][1]?.body).toBe(
    JSON.stringify({ inventory: inventory.token }),
  );
});

it("compares the selected native book explicitly under both pins without claiming file identity", async () => {
  const catalogue = {
    version: "2026.10.24.2",
    sha256: "b".repeat(64),
    fixture: true,
  };
  intercept = (url) =>
    url === "/api/catalogue"
      ? json({ status: "ready", ...catalogue })
      : url.includes("/match?")
        ? json({
            inventory,
            book: { id: book.id, title: book.title, authors: book.authors },
            catalogue,
            status: "matched",
            basis: "identifier_and_metadata",
            candidates: [
              {
                work_id: "fixture-work",
                title: book.title,
                authors: [{ id: "author-1", name: "Fixture Author" }],
                title_status: "same",
                authors_status: "same",
                identifier_match: true,
              },
            ],
            identifiers: [
              {
                type: "isbn",
                value: "9780306406157",
                status: "same",
                editions: [
                  {
                    edition_id: "edition-1",
                    work_id: "fixture-work",
                    format: "paperback",
                    disputed: false,
                  },
                ],
              },
            ],
            scope: "Recorded metadata only.",
          })
        : undefined;
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  await screen.findByRole("button", { name: "Compare with reference" });
  expect(calls.some((url) => url.includes("/match?"))).toBe(false);
  fireEvent.click(
    screen.getByRole("button", { name: "Compare with reference" }),
  );
  expect(await screen.findByText("Reference match")).toBeTruthy();
  expect(
    screen.getByText(
      /does not establish that the library file is the same edition/,
    ),
  ).toBeTruthy();
  expect(
    calls.some(
      (url) =>
        url.includes("/match?") &&
        url.includes(`inventory=${inventory.token}`) &&
        url.includes(`sha256=${catalogue.sha256}`),
    ),
  ).toBe(true);
});

it("pages native books under one inventory and uses the supporting list presentation", async () => {
  mount();
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(document.querySelector(".direct-books.is-list")).toBeTruthy();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Next" }).hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("page=2") &&
          url.includes(`inventory=${inventory.token}`),
      ),
    ).toBe(true),
  );
});

it("opens reference browsing before secondary Catalogue operations and never calls the old library adapter", async () => {
  const pin = {
    version: "2026.10.24.2",
    sha256: "b".repeat(64),
    fixture: true,
  };
  intercept = (url) =>
    url === "/api/catalogue"
      ? json({ status: "ready", ...pin, total: 0 })
      : url.startsWith("/api/catalogue/control?")
        ? json({
            snapshot: pin,
            producer: {
              status: "not_configured",
              message: "Reference ingestion is not configured.",
            },
            source_observations: [],
            counts: {
              incomplete: 0,
              conflicts: 0,
              possible_duplicates: 0,
              unmatched: null,
            },
            library_matching: {
              status: "not_assessed",
              message: "Not checked.",
            },
            queue: "incomplete",
            page: 1,
            pages: 1,
            page_size: 24,
            total: 0,
            works: [],
            scope: "Snapshot only.",
          })
        : url.startsWith("/api/catalogue/works?")
          ? json({
              snapshot: pin,
              works: [],
              total: 0,
              page: 1,
              page_size: 24,
              selected_series: null,
              selected_author: null,
            })
          : undefined;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  fireEvent.click(screen.getByRole("button", { name: "Catalogue" }));
  expect(
    await screen.findByRole("heading", { name: "Catalogue" }),
  ).toBeTruthy();
  // The Catalogue leads with tool health; books stay one tab away.
  const sections = screen.getByRole("navigation", {
    name: "Catalogue sections",
  });
  expect(
    within(sections)
      .getByRole("button", { name: "Tool health" })
      .getAttribute("aria-current"),
  ).toBe("page");
  await waitFor(() => expect(calls).toContain("/api/catalogue/health"));
  expect(new URLSearchParams(location.search).get("cm")).toBe("health");
  fireEvent.click(within(sections).getByRole("button", { name: "Books" }));
  await waitFor(() =>
    expect(new URLSearchParams(location.search).get("cm")).toBe("browse"),
  );
  expect(calls.some((url) => url.startsWith("/api/library"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Catalogue operations" }));
  expect(
    await screen.findByRole("heading", {
      name: "Catalogue control",
    }),
  ).toBeTruthy();
});

it("opens a native reference work after Catalogue was left in Series mode", async () => {
  const pin = {
    version: "2026.10.24.2",
    sha256: "b".repeat(64),
    fixture: true,
  };
  const reference = {
    id: "fixture-work",
    title: "Reference: The Glass Meridian",
    authors: [{ id: "1", name: "Fixture Author", version: pin.version }],
    series: [],
    edition_count: 0,
  };
  history.replaceState(null, "", "/?cb=series");
  intercept = (url) => {
    if (url === "/api/catalogue")
      return json({ status: "ready", ...pin, total: 1 });
    if (url.includes("/match?"))
      return json({
        inventory,
        book,
        catalogue: pin,
        status: "matched",
        basis: "title_and_authors",
        candidates: [
          {
            ...reference,
            work_id: reference.id,
            title_status: "same",
            authors_status: "same",
            identifier_match: false,
          },
        ],
        identifiers: [],
        scope: "Recorded metadata only.",
      });
    if (url.startsWith("/api/catalogue/works/fixture-work?"))
      return json({
        ...reference,
        snapshot: pin,
        synopsis: "The selected reference work.",
        ownership: "unconfirmed",
        editions: [],
        support: [],
      });
    if (url.startsWith("/api/catalogue/works?"))
      return json({
        snapshot: pin,
        works: [reference],
        total: 1,
        page: 1,
        page_size: 24,
        selected_series: null,
        selected_author: null,
      });
    if (url.startsWith("/api/catalogue/series?"))
      return json({
        snapshot: pin,
        series: [],
        total: 0,
        page: 1,
        page_size: 24,
      });
    return undefined;
  };
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <App />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Compare with reference" }),
  );
  const referenceTrigger = await screen.findByRole("button", {
    name: "Open reference record",
  });
  referenceTrigger.focus();
  fireEvent.click(referenceTrigger);
  expect(
    await screen.findByRole("heading", { name: reference.title }),
  ).toBeTruthy();
  expect(new URLSearchParams(location.search).get("cb")).toBe("works");
  expect(new URLSearchParams(location.search).get("cw")).toBe(reference.id);
  expect(calls.some((url) => url.startsWith("/api/catalogue/series?"))).toBe(
    false,
  );
  expect(calls.some((url) => url.startsWith("/api/library"))).toBe(false);
  await act(async () => {
    history.back();
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  const restoredReference = await screen.findByRole("button", {
    name: "Open reference record",
  });
  await waitFor(() => expect(document.activeElement).toBe(restoredReference));
});

it("keeps the featured inspection and its focused control stable when it finishes", async () => {
  const captured = { ...inventory, library_uuid: "fixture-library" };
  let running = true;
  const ids = [
    "22222222-2222-4222-8222-000000000001",
    "22222222-2222-4222-8222-000000000002",
  ];
  intercept = (url) =>
    url.includes("/workspaces?")
      ? json({
          sources: ids.map((id, index) => ({
            job: {
              id,
              kind: "epub",
              state: index === 1 && running ? "running" : "succeeded",
              updated_at: "2026-11-02T12:00:00Z",
            },
            origin: {
              library_uuid: captured.library_uuid,
              book_id: book.id,
              inventory: inventory.token,
              format: "EPUB",
            },
            inventory_matches: true,
          })),
          total: 2,
          page: 1,
          page_size: 20,
        })
      : url.startsWith("/api/direct-library/books/")
        ? json({ inventory: captured, book })
        : url.startsWith("/api/direct-library?")
          ? json({ ...listing, inventory: captured })
          : undefined;
  const mounted = mount(
    { lw: book.id, lt: inventory.token, ld: "1" },
    undefined,
    { resumeBook: vi.fn() },
  );
  const featured = await screen.findByRole("button", {
    name: "Resume preserved work · 00000002",
  });
  featured.focus();
  running = false;
  await act(async () =>
    mounted.client.invalidateQueries({ queryKey: ["library-book-workspaces"] }),
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Resume preserved work · 00000002" })
        .closest("li")?.textContent,
    ).toContain("Inspection complete"),
  );
  expect(
    screen.getByRole("button", { name: "Resume preserved work · 00000002" }),
  ).toBe(featured);
  expect(document.activeElement).toBe(featured);
});

it.each([false, true])(
  "keeps high-history books readable and restores an older exact inspection: restored=%s",
  async (restored) => {
    const captured = { ...inventory, library_uuid: "fixture-library" };
    const sources = ["succeeded", "cancelled", "cancelled"].map(
      (state, index) => ({
        job: {
          id: `22222222-2222-4222-8222-${String(index + 1).padStart(12, "0")}`,
          kind: "epub",
          state,
          updated_at: "2026-11-02T12:00:00Z",
        },
        origin: {
          library_uuid: captured.library_uuid,
          book_id: book.id,
          inventory: inventory.token,
          format: "EPUB",
        },
        inventory_matches: index !== 2,
      }),
    );
    intercept = (url) =>
      url.includes("/workspaces?")
        ? json({ sources, total: 3, page: 1, page_size: 20 })
        : url.startsWith("/api/direct-library/books/")
          ? json({ inventory: captured, book })
          : url.startsWith("/api/direct-library?")
            ? json({ ...listing, inventory: captured })
            : undefined;
    const route = {
      lq: "",
      lp: 1,
      lt: inventory.token,
      lw: book.id,
      ld: "1",
      lwp: 1,
    };
    const resumeBook = vi.fn();
    mount(route, undefined, {
      resumeBook,
      ...(restored
        ? {
            restore: {
              route,
              scroll: 150,
              focusId: `resume-book-${sources[2].job.id}`,
            },
          }
        : {}),
    });
    const region = await screen.findByRole("region", {
      name: "Resume preserved work",
    });
    await within(region).findByRole("button", {
      name: /Resume preserved work/,
    });
    expect(
      within(region).getAllByRole("button", { name: /Resume preserved work/ }),
    ).toHaveLength(1);
    const summary = within(region).getByText(
      "Other preserved inspections · 2 on this page",
    );
    expect(summary.closest("details")?.open).toBe(restored);
    if (!restored) fireEvent.click(summary);
    const older = within(region).getAllByRole("button", {
      name: /Open inspection/,
    });
    expect(older.map((control) => control.textContent)).toEqual([
      "Open inspection · 00000002",
      "Open inspection · 00000003",
    ]);
    expect(
      within(region).getByText(
        /Historical source; the library inventory has changed/,
      ),
    ).toBeTruthy();
    if (restored)
      await waitFor(() => expect(document.activeElement).toBe(older[1]));
    fireEvent.click(older[1]);
    expect(resumeBook).toHaveBeenCalledWith(sources[2].job.id);
  },
);

it.each([false, true])(
  "restores the exact paged resume control only after delayed source history, with newer-input cancellation=%s",
  async (cancel) => {
    const library_uuid = "11111111-1111-4111-8111-111111111111";
    const sourceId = "22222222-2222-4222-8222-222222222222";
    const captured = { ...inventory, library_uuid };
    let finish!: (value: Response) => void;
    intercept = (url) =>
      url.includes("/workspaces?") && url.includes("page=1")
        ? // The seal's own read of the latest inspection answers at once.
          json({ sources: [], total: 0, page: 1, page_size: 20 })
        : url.includes("/workspaces?")
          ? new Promise<Response>((resolve) => {
              finish = resolve;
            })
          : url.startsWith("/api/direct-library/books/")
            ? json({ inventory: captured, book })
            : url.startsWith("/api/direct-library?")
              ? json({ ...listing, inventory: captured })
              : undefined;
    const route = {
      lq: "Fixture",
      lp: 1,
      lt: inventory.token,
      lw: book.id,
      ld: "1",
      lwp: 2,
    };
    mount(route, undefined, {
      resumeBook: vi.fn(),
      restore: { route, scroll: 450, focusId: `resume-book-${sourceId}` },
    });
    await screen.findByRole("heading", { name: book.title });
    expect(document.activeElement).toBe(document.body);
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    expect(
      calls.some(
        (url) => url.includes("/workspaces?") && url.includes("page=2"),
      ),
    ).toBe(true);
    if (cancel) fireEvent.wheel(document);
    await act(async () =>
      finish(
        json({
          sources: [
            {
              job: {
                id: sourceId,
                kind: "epub",
                state: "succeeded",
                updated_at: "2026-11-01T12:00:00Z",
              },
              origin: {
                library_uuid,
                book_id: book.id,
                inventory: inventory.token,
                format: "EPUB",
              },
              inventory_matches: true,
            },
          ],
          total: 25,
          page: 2,
          page_size: 20,
        }),
      ),
    );
    const resume = await screen.findByRole("button", {
      name: /Resume preserved work ·/,
    });
    await waitFor(() =>
      expect(document.activeElement === resume).toBe(!cancel),
    );
    if (cancel) expect(document.activeElement).toBe(document.body);
  },
);

it.each(["library", "references"])(
  "restores the departing %s control on browser Back and retains the source on Forward",
  async (origin) => {
    const sourceId = "22222222-2222-4222-8222-222222222222";
    const captured = { ...inventory, library_uuid: "fixture-library" };
    const source = {
      id: sourceId,
      kind: "epub",
      title: book.title,
      state: "queued",
      revision: 1,
      result: {},
      updated_at: "2026-11-01T12:00:00Z",
    };
    const recorded = {
      library_uuid: captured.library_uuid,
      book_id: book.id,
      inventory: inventory.token,
      format: "EPUB",
    };
    intercept = (url) => {
      if (url === "/api/session")
        return json({
          csrf: "fixture",
          library: true,
          direct_library: true,
          file_inspections: true,
        });
      if (url.includes("/workspaces?"))
        return json({
          sources: [{ job: source, origin: recorded, inventory_matches: true }],
          total: 1,
          page: 1,
          page_size: 20,
        });
      if (url.endsWith("/workspace"))
        return json({
          schema_version: "librarium.book-workspace.v1",
          source,
          origin: recorded,
          selection: emptyWorkspaceSelection,
          jobs: [],
        });
      if (url === `/api/jobs/${sourceId}`) return json(source);
      if (url.startsWith("/api/direct-library/books/"))
        return json({ inventory: captured, book });
      if (url.startsWith("/api/direct-library?"))
        return json({ ...listing, inventory: captured });
      return undefined;
    };
    history.replaceState(
      null,
      "",
      `/?lw=${book.id}&lt=${inventory.token}&ld=1`,
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );
    const resume = await screen.findByRole("button", {
      name: /Resume preserved work/,
    });
    resume.focus();
    fireEvent.click(resume);
    const browse = await screen.findByRole("button", {
      name: "Browse reference catalogue",
    });
    if (origin === "references") {
      browse.focus();
      fireEvent.click(browse);
      await screen.findByRole("button", { name: "Return to book workspace" });
    }
    await act(async () => {
      history.back();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    const restored = await screen.findByRole("button", {
      name:
        origin === "library"
          ? /Resume preserved work/
          : "Browse reference catalogue",
    });
    await waitFor(() => expect(document.activeElement).toBe(restored));
    await act(async () => {
      history.forward();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(new URLSearchParams(location.search).get("fj")).toBe(sourceId);
    if (origin === "library")
      await screen.findByRole("button", { name: "Browse reference catalogue" });
    else
      await screen.findByRole("button", { name: "Return to book workspace" });
    client.clear();
  },
);

it.each([false, true])(
  "discloses unavailable preserved rows without claiming no historical work: all unavailable=%s",
  async (allUnavailable) => {
    const captured = { ...inventory, library_uuid: "fixture-library" };
    const sourceId = "22222222-2222-4222-8222-222222222223";
    intercept = (url) =>
      url.includes("/workspaces?")
        ? json({
            sources: allUnavailable
              ? []
              : [
                  {
                    job: {
                      id: sourceId,
                      kind: "epub",
                      state: "succeeded",
                      updated_at: "2026-11-01T12:00:00Z",
                    },
                    origin: {
                      library_uuid: captured.library_uuid,
                      book_id: book.id,
                      inventory: inventory.token,
                      format: "EPUB",
                    },
                    inventory_matches: true,
                  },
                ],
            total: allUnavailable ? 1 : 2,
            page: 1,
            page_size: 20,
            unavailable_count: 1,
          })
        : url.startsWith("/api/direct-library/books/")
          ? json({ inventory: captured, book })
          : url.startsWith("/api/direct-library?")
            ? json({ ...listing, inventory: captured })
            : undefined;
    mount({ lw: book.id, lt: inventory.token, ld: "1" }, undefined, {
      resumeBook: vi.fn(),
    });
    await screen.findByText(
      /1 recorded inspection on this page could not be verified/,
    );
    expect(
      screen.queryByText(/No preserved inspection is recorded for this book/),
    ).toBeNull();
    if (allUnavailable) {
      expect(
        screen.getByText(
          /No verified preserved inspection is available on this page/,
        ),
      ).toBeTruthy();
      expect(
        screen.queryByRole("button", { name: /Resume preserved work ·/ }),
      ).toBeNull();
    } else
      expect(
        screen.getByRole("button", { name: /Resume preserved work ·/ }),
      ).toBeTruthy();
  },
);

it.each([-1, 1.5, "1", 21, null])(
  "refuses an invalid unavailable-row count: %s",
  async (unavailable_count) => {
    const captured = { ...inventory, library_uuid: "fixture-library" };
    intercept = (url) =>
      url.includes("/workspaces?")
        ? json({
            sources: [],
            total: 25,
            page: 1,
            page_size: 20,
            unavailable_count,
          })
        : url.startsWith("/api/direct-library/books/")
          ? json({ inventory: captured, book })
          : url.startsWith("/api/direct-library?")
            ? json({ ...listing, inventory: captured })
            : undefined;
    mount({ lw: book.id, lt: inventory.token, ld: "1" }, undefined, {
      resumeBook: vi.fn(),
    });
    await screen.findByRole("button", { name: "Retry preserved work" });
    expect(
      screen.queryByText(/No preserved inspection is recorded for this book/),
    ).toBeNull();
  },
);

it("seals the book only when the latest check of this exact file passed with nothing flagged", async () => {
  const captured = { ...inventory, library_uuid: "fixture-library" };
  const source = (
    state: string,
    result: Record<string, unknown>,
    { matches = true, at = "2026-11-02T12:00:00Z", size = 12345 } = {},
  ) => ({
    job: {
      id: `job-${at}`,
      kind: "epub",
      state,
      updated_at: at,
      source_size: size,
      result,
    },
    origin: {
      library_uuid: captured.library_uuid,
      book_id: book.id,
      inventory: inventory.token,
      format: "EPUB",
    },
    inventory_matches: matches,
  });
  const clean = {
    structural_check: "passed",
    inspection_complete: true,
    findings: [{ name: "spine", ok: true, detail: "", status: "pass" }],
  };
  let sources = [source("succeeded", clean)];
  intercept = (url) =>
    url.includes("/workspaces?")
      ? json({ sources, total: sources.length, page: 1, page_size: 20 })
      : url.startsWith("/api/direct-library/books/")
        ? json({ inventory: captured, book })
        : url.startsWith("/api/direct-library?")
          ? json({ ...listing, inventory: captured })
          : undefined;
  const mounted = mount({ lw: book.id, lt: inventory.token, ld: "1" });
  const refresh = () =>
    act(async () =>
      mounted.client.invalidateQueries({ queryKey: ["library-book-seal"] }),
    );
  expect(
    await screen.findByRole("img", {
      name: /Sealed by Librarium: checked .*, sound/,
    }),
  ).toBeTruthy();

  // A passed check that still flags something earns no seal.
  sources = [
    source("succeeded", {
      ...clean,
      findings: [{ name: "links", ok: true, detail: "", status: "attention" }],
    }),
  ];
  await refresh();
  await waitFor(() =>
    expect(
      screen.queryByRole("img", { name: /Sealed by Librarium/ }),
    ).toBeNull(),
  );
  expect(screen.getByText(/it found something to look at/)).toBeTruthy();

  // So does one that proposes a contents fix.
  sources = [
    source("succeeded", { ...clean, contents_plan: { decision: "propose" } }),
  ];
  await refresh();
  await waitFor(() =>
    expect(screen.getByText(/it found something to look at/)).toBeTruthy(),
  );

  // A sound check of a file that has since changed size never seals it.
  sources = [source("succeeded", clean, { size: 999 })];
  await refresh();
  await waitFor(() =>
    expect(
      screen.getByText(/The file has changed since its last check/),
    ).toBeTruthy(),
  );

  // A check of an older library snapshot never seals the current one.
  sources = [source("succeeded", clean, { matches: false })];
  await refresh();
  await waitFor(() => expect(screen.getByText(/Not checked yet/)).toBeTruthy());

  // A running check says so.
  sources = [source("running", {})];
  await refresh();
  await waitFor(() =>
    expect(screen.getByText("Being checked now.")).toBeTruthy(),
  );
  expect(screen.queryByRole("img", { name: /Sealed by Librarium/ })).toBeNull();
});
