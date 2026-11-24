// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { App } from "../src/App";
import { Library, shelfCredits, type LibraryRoute } from "../src/Library";
import { LibraryBookArt } from "../src/LibraryBookArt";

const version = "2026.10.24.2",
  sha256 = "b".repeat(64),
  token = "a".repeat(24);
const work = {
  id: "w_first",
  title: "First and Only",
  kind: "novel",
  authors: ["Dan Abnett"],
  series: [{ id: "7", name: "Gaunt's Ghosts", position: 1 }],
  state: "direct",
  current: false,
  copies: [{ calibre_id: 152, title: "First and Only", last_known: true }],
  contained_in: [],
  candidates: [],
};
const shelf = {
  id: "7",
  name: "Gaunt's Ghosts",
  total: 15,
  catalogue_total: 15,
  credit: { names: ["Dan Abnett"], others: 0 },
  works: [
    work,
    {
      ...work,
      id: "w_folio",
      title: "The Guns of Tanith",
      series: [{ ...work.series[0], position: 5 }],
    },
  ],
  counts: {
    saved: 15,
    direct: 0,
    contained: 0,
    pending: 0,
    missing: 0,
    unknown: 0,
  },
  position_counts: { numbered: 15, zero: 0, unpositioned: 0 },
};
const listing = {
  status: "ready",
  source: "library_finish",
  catalogue_version: version,
  catalogue_snapshot: { version, sha256, fixture: false },
  checked_at: "2026-10-26T05:29:28+00:00",
  coverage: "partial",
  loading: false,
  snapshot: token,
  page: 1,
  page_size: 4,
  total: 1698,
  series_total: 1,
  truncated: false,
  unlinked_total: 0,
  shelves: [shelf],
  works: shelf.works,
};
let overrides: (url: string) => unknown;
let calls: string[] = [];
function setup(
  app = false,
  initial: Partial<LibraryRoute> = {},
  openCatalogue?: React.ComponentProps<typeof Library>["openCatalogue"],
) {
  calls = [];
  if (typeof matchMedia !== "function")
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    }));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      const value = await (overrides?.(url) ??
        (url === "/api/session"
          ? { csrf: "test", library: true }
          : url.startsWith("/api/jobs")
            ? { jobs: [] }
            : url === "/api/catalogue"
              ? { status: "ready", version, sha256, fixture: false }
              : url.startsWith("/api/catalogue/covers?")
                ? { snapshot: { version, sha256 }, covers: {} }
                : url.startsWith("/api/catalogue/works/")
                  ? {
                      id: url.includes("w_folio") ? "w_folio" : "w_first",
                      title: work.title,
                      authors: [],
                      series: [],
                      identifiers: [],
                      snapshot: { version, sha256, fixture: false },
                      synopsis: "The Sabbat Worlds are at war. ".repeat(40),
                      first_published: "1999",
                      edition_count: 15,
                      editions: [
                        { id: "e_1", format: "ebook", isbn13: "9780306406157" },
                      ],
                      support: [],
                    }
                  : listing));
      return value instanceof Response
        ? value
        : new Response(JSON.stringify(value), { status: 200 });
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Harness() {
    const [route, setRoute] = useState<LibraryRoute>({
      lq: "",
      lp: 1,
      lo: "owned",
      lx: "series",
      lt: "",
      ...initial,
    });
    return (
      <Library
        openCatalogue={openCatalogue}
        route={route}
        navigate={(next) => setRoute((old) => ({ ...old, ...next }))}
      />
    );
  }
  const view = render(
    <QueryClientProvider client={client}>
      {app ? <App /> : <Harness />}
    </QueryClientProvider>,
  );
  return { ...view, client };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  history.replaceState(null, "", "/");
  overrides = () => undefined;
});

it("holds a second token change after adopting a preparing snapshot without opening another automatic refresh", async () => {
  let conflict = false;
  overrides = (url) => {
    if (!url.startsWith("/api/library/shelves?")) return undefined;
    if (!conflict) return { ...listing, series_total: 8 };
    const params = new URL(url, "http://local").searchParams;
    if (params.get("snapshot"))
      return new Response(
        JSON.stringify({
          error: "Check changed",
          code: "library_check_changed",
        }),
        { status: 409 },
      );
    return {
      ...listing,
      status: "preparing",
      snapshot: "c".repeat(24),
      page: 2,
      shelves: [],
      works: [],
    };
  };
  setup();
  await screen.findByRole("heading", { name: work.title, level: 2 });
  conflict = true;
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("Preparing shelves…");
  const alert = await screen.findByRole("alert", {}, { timeout: 4500 });
  expect(
    within(alert).getByRole("button", { name: "Reload library" }),
  ).toBeTruthy();
  expect(
    calls.filter(
      (url) =>
        url.startsWith("/api/library/shelves?") &&
        new URL(url, "http://local").searchParams.get("snapshot") === "",
    ).length,
  ).toBe(2);
  expect(
    screen.getByRole("heading", { name: work.title, level: 2 }),
  ).toBeTruthy();
});

it("restores a same-pin Series return after the new token was adopted while shelves were still preparing", async () => {
  const latest = "c".repeat(24);
  const route = {
    lq: "",
    lp: 1,
    lo: "owned",
    lx: "series",
    lt: token,
    lw: "w_folio",
  };
  history.replaceState(
    {
      libraryReturn: {
        route,
        work: "w_folio",
        shelf: "7",
        scroll: 300,
        open: [],
        focusId: "library-7-w_folio",
        catalogue: { version, sha256 },
      },
    },
    "",
  );
  const scroll = vi.spyOn(window, "scrollTo");
  scroll.mockClear();
  overrides = (url) => {
    if (!url.startsWith("/api/library/shelves?")) return undefined;
    const snapshot = new URL(url, "http://local").searchParams.get("snapshot");
    if (snapshot === token)
      return new Response(
        JSON.stringify({
          error: "Check changed",
          code: "library_check_changed",
        }),
        { status: 409 },
      );
    if (!snapshot)
      return {
        ...listing,
        status: "preparing",
        snapshot: latest,
        works: [],
        shelves: [],
      };
    return { ...listing, snapshot: latest };
  };
  setup(false, route);
  await screen.findByText("Preparing shelves…");
  await waitFor(
    () => expect(history.state.libraryReturn.route.lt).toBe(latest),
    { timeout: 4500 },
  );
  await waitFor(() => expect(scroll).toHaveBeenCalledWith(0, 300));
  expect(document.activeElement?.id).toBe("library-7-w_folio");
});

it.each(["Shelves", "List"])(
  "keeps retained %s positives historical and turns old absence into unknown",
  async (presentation) => {
    let conflict = false;
    let finish!: (value: unknown) => void;
    const missing = {
      ...work,
      id: "w_missing",
      title: "Fixture: Unconfirmed copy",
      state: "missing",
      current: true,
      copies: [],
    };
    const works = [
      {
        ...work,
        current: true,
        copies: [{ ...work.copies[0], last_known: false }],
      },
      missing,
    ];
    const original = {
      ...listing,
      total: 2,
      coverage: "complete",
      works,
      shelves: [
        {
          ...shelf,
          total: 2,
          catalogue_total: 2,
          works,
          counts: { direct: 1, contained: 0, saved: 0, missing: 1, unknown: 0 },
        },
      ],
    };
    overrides = (url) => {
      if (!url.startsWith("/api/library/shelves?")) return undefined;
      if (!conflict) return original;
      if (new URL(url, "http://local").searchParams.get("snapshot"))
        return new Response(
          JSON.stringify({
            error: "Check changed",
            code: "library_check_changed",
          }),
          { status: 409 },
        );
      return new Promise((resolve) => {
        finish = resolve;
      });
    };
    const view = setup(false, { lw: "w_missing" });
    await screen.findByRole("heading", { name: missing.title, level: 2 });
    fireEvent.click(screen.getByRole("button", { name: presentation }));
    conflict = true;
    act(() => {
      void view.client.refetchQueries({ queryKey: ["library"] });
    });
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    expect(screen.getByText("1 of 2 shelved with a saved match")).toBeTruthy();
    expect(screen.queryByText("No matched copy")).toBeNull();
    expect(
      screen.queryByText("The complete check found no Calibre copy."),
    ).toBeNull();
    expect(
      screen.getByText("Saved match", { selector: ".library-state" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Unconfirmed", {
        selector: ".library-status-well strong",
      }),
    ).toBeTruthy();
    expect(
      (
        await axe.run(view.container, {
          rules: { "color-contrast": { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
    await act(async () => finish({ ...original, snapshot: "c".repeat(24) }));
  },
);

it.each([null, 0, -1, 1])(
  "leaves no artwork slot or duplicated identity without a cover (%s)",
  (position) => {
    const view = render(
      <LibraryBookArt
        work={{
          ...work,
          state: "direct",
          series: [{ ...work.series[0], position }],
        }}
      />,
    );
    expect(view.container.querySelector(".shelf-art")).toBeNull();
    expect(view.container.querySelector(".book-folio")).toBeNull();
    expect(view.container.querySelector(".archivist-mark")).toBeNull();
    expect(view.container.textContent).toBe("");
  },
);

it("keeps No position in the entry name while leaving its folio unnumbered", async () => {
  const unpositioned = {
    ...work,
    series: [{ ...work.series[0], position: null }],
  };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [unpositioned],
          shelves: [{ ...shelf, works: [unpositioned] }],
        }
      : undefined;
  setup();
  const entry = await screen.findByRole("button", {
    name: /No position.*First and Only.*Dan Abnett.*Saved match/,
  });
  expect(entry.querySelector(".folio-position")).toBeNull();
});

it("allows series names to break after every slash in the book bibliography", async () => {
  const slashed = {
    ...work,
    series: [{ ...work.series[0], name: "Eisenhorn/Ravenor/Bequin" }],
  };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [slashed],
          shelves: [
            { ...shelf, name: slashed.series[0].name, works: [slashed] },
          ],
        }
      : undefined;
  const view = setup();
  await screen.findByRole("heading", { name: work.title, level: 2 });
  expect(
    view.container.querySelector(".book-bibliography")!.querySelectorAll("wbr"),
  ).toHaveLength(2);
});

it.each(["series", "title"])(
  "uses the canonical catalogue lead in %s detail",
  async (order) => {
    const alternate = {
      ...work,
      series: [{ ...work.series[0], lead_work_id: work.id, position_total: 1 }],
    };
    overrides = (url) =>
      url.startsWith("/api/library")
        ? {
            ...listing,
            works: [alternate],
            shelves:
              order === "series"
                ? [{ ...shelf, works: [alternate] }]
                : undefined,
          }
        : url.startsWith("/api/catalogue/works/")
          ? {
              id: work.id,
              snapshot: { version, sha256, fixture: false },
              series: [
                {
                  ...work.series[0],
                  lead_work_id: "w_unmatched",
                  position_total: 6,
                },
              ],
            }
          : undefined;
    const view = setup(false, { lx: order, lw: work.id });
    await waitFor(() =>
      expect(
        view.container.querySelector(".book-bibliography")?.textContent,
      ).toContain("Position 1"),
    );
  },
);

it("keeps masthead keyboard order aligned with each layout and retains theme choice across resizing", async () => {
  const listeners: (() => void)[] = [];
  const desktop = {
    matches: true,
    addEventListener(_name: string, callback: () => void) {
      listeners.push(callback);
    },
    removeEventListener() {},
  };
  vi.stubGlobal("matchMedia", (query: string) =>
    query.includes("min-width: 960px")
      ? desktop
      : { matches: false, addEventListener() {}, removeEventListener() {} },
  );
  setup(true);
  await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
  const theme = screen.getByRole("combobox", { name: "Theme" });
  const nav = screen.getByRole("navigation", { name: "Workspace" });
  expect(
    nav.compareDocumentPosition(theme) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  fireEvent.change(theme, { target: { value: "light" } });
  act(() => {
    desktop.matches = false;
    listeners.forEach((callback) => callback());
  });
  expect(
    theme.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.getByRole("combobox", { name: "Theme" })).toBe(theme);
  expect((theme as HTMLSelectElement).value).toBe("light");
});

it("defaults to persisted Series order and mounts the same library search in the masthead", async () => {
  setup(true);
  await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
  expect(
    (screen.getByRole("combobox", { name: "Order" }) as HTMLSelectElement)
      .value,
  ).toBe("series");
  expect(screen.getByRole("search").closest(".masthead")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Order" }), {
    target: { value: "author" },
  });
  await waitFor(() =>
    expect(localStorage.getItem("librarium.library-order")).toBe("author"),
  );
  expect(
    calls.some(
      (url) => url.startsWith("/api/library?") && url.includes("sort=author"),
    ),
  ).toBe(true);
});

it("uses server shelves and preserves ordered, title-led entries without artwork", async () => {
  const view = setup();
  await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
  expect(
    calls.some(
      (url) =>
        url.startsWith("/api/library/shelves?") &&
        url.includes(`sha256=${sha256}`),
    ),
  ).toBe(true);
  const entries = () =>
    [...view.container.querySelectorAll<HTMLButtonElement>(".shelf-entry")].map(
      (el) => el.dataset.work,
    );
  expect(entries()).toEqual(["w_first", "w_folio"]);
  const entry = view.container.querySelectorAll(".shelf-entry")[1];
  expect(
    within(entry as HTMLElement).getAllByText("The Guns of Tanith"),
  ).toHaveLength(1);
  expect(
    screen.getByRole("button", { name: /Book 5.*The Guns of Tanith/ }),
  ).toBe(entry);
  expect(entry.querySelector(".shelf-position")?.textContent).toBe("Book 5");
  expect(entry.querySelector(".shelf-art")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(entries()).toEqual(["w_first", "w_folio"]);
  expect(localStorage.getItem("librarium.browse-view")).toBe("list");
  expect(
    screen.getByRole("link", { name: "All 15 →" }).getAttribute("href"),
  ).toContain("cs=7");
});

it("keeps the check context and three detail disclosures closed, with synopsis and actions above them", async () => {
  const view = setup();
  await screen.findByRole("heading", { name: "First and Only", level: 2 });
  await screen.findByText(/The Sabbat Worlds are at war/);
  expect(screen.getByRole("button", { name: "Review metadata" })).toBeTruthy();
  for (const label of ["Editions", "Library evidence", "Record details"]) {
    const disclosure = [...view.container.querySelectorAll("details")].find(
      (d) => d.querySelector("summary")?.textContent?.startsWith(label),
    );
    expect(disclosure?.open).toBe(false);
  }
  expect(
    view.container.querySelector<HTMLDetailsElement>(".library-context")?.open,
  ).toBe(false);
  fireEvent.click(screen.getByText("Details", { exact: true }));
  expect(screen.getByRole("button", { name: "Reload library" })).toBeTruthy();
  expect(
    view.container.querySelector(".library-context .source-id")?.textContent,
  ).toBe(token);
  expect(
    (
      await axe.run(view.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it("uses grouped catalogue support in saved-library details while preserving every captured claim", async () => {
  overrides = (url) =>
    url.startsWith("/api/catalogue/works/")
      ? {
          id: "w_first",
          snapshot: { version, sha256, fixture: false },
          editions: [],
          support: [
            {
              field: "title",
              value: work.title,
              agree: ["source-one"],
              disagree: [
                { origin: "source-three", value: "An alternate title" },
              ],
            },
            {
              field: "title",
              value: work.title,
              agree: ["source-two"],
              disagree: [
                { origin: "source-three", value: "An alternate title" },
              ],
            },
            {
              field: "tag",
              value: ["Recorded tag", 0, false, null],
              agree: [],
              disagree: [],
            },
          ],
        }
      : undefined;
  setup();
  await screen.findByRole("heading", { name: work.title, level: 2 });
  fireEvent.click(screen.getByText("Record details", { exact: true }));
  fireEvent.click(
    await screen.findByText("Source support · 2 fields · 2 disputed records"),
  );
  const title = screen.getByRole("region", { name: "Title" });
  expect(within(title).getByText("source-one, source-two")).toBeTruthy();
  expect(within(title).getAllByText("An alternate title")).toHaveLength(1);
  expect(within(title).getByRole("link", { name: "value 1" })).toBeTruthy();
  const tags = screen.getByRole("region", { name: "Tags" });
  expect(within(tags).getByText("Recorded tag")).toBeTruthy();
  expect(within(tags).getByText("0")).toBeTruthy();
  expect(within(tags).getByText("false")).toBeTruthy();
  expect(within(tags).getByText("Not recorded")).toBeTruthy();
  fireEvent.click(screen.getByText("Captured source records · 3"));
  const raw = screen
    .getByText("Captured source records · 3")
    .closest("details")!;
  expect(within(raw).getAllByText("An alternate title")).toHaveLength(2);
});

it.each([
  ["direct", true, "Direct match"],
  ["contained", true, "In a collection"],
  ["direct", false, "Saved match"],
  ["contained", false, "Saved match"],
  ["pending", false, "Pending ID"],
  ["unknown", false, "Unconfirmed"],
  ["missing", true, "No matched copy"],
])(
  "keeps %s/current=%s shelf wording truthful",
  async (state, current, label) => {
    overrides = (url) =>
      url.startsWith("/api/library/shelves?")
        ? {
            ...listing,
            works: [{ ...work, state, current }],
            shelves: [{ ...shelf, works: [{ ...work, state, current }] }],
          }
        : undefined;
    setup();
    const entry = await screen.findByRole("button", {
      name: /First and Only/,
    });
    expect(within(entry).getByText(label as string)).toBeTruthy();
  },
);

it("selects a folio with a focused-detail return path and keeps saved evidence explicit", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  setup();
  fireEvent.click(
    await screen.findByRole("button", { name: /The Guns of Tanith/ }),
  );
  await screen.findByRole("heading", { name: "The Guns of Tanith", level: 2 });
  expect(screen.getByText("Direct match · saved match")).toBeTruthy();
  expect(
    screen.getByText(/Not yet re-confirmed by a complete check/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Back to library" }));
  await waitFor(() =>
    expect(document.activeElement?.getAttribute("data-work")).toBe("w_folio"),
  );
  expect(
    screen
      .getByRole("button", { name: /The Guns of Tanith/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("captures the visible phone row position before hiding it for detail and Catalogue navigation", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  const openCatalogue = vi.fn();
  setup(false, {}, openCatalogue);
  vi.stubGlobal("scrollY", 20);
  const entry = await screen.findByRole("button", {
    name: /The Guns of Tanith/,
  });
  const row = document.querySelector(".shelf-row")!;
  Object.defineProperty(row, "scrollLeft", {
    get: () => (document.querySelector(".library-focused") ? 0 : 150),
  });
  fireEvent.click(entry);
  vi.stubGlobal("scrollY", 900);
  fireEvent.click(await screen.findByText("Record details", { exact: true }));
  fireEvent.click(screen.getByRole("link", { name: "Catalogue evidence" }));
  expect(openCatalogue.mock.calls[0][1].shelfScroll).toEqual({ "7": 150 });
  expect(openCatalogue.mock.calls[0][1].scroll).toBe(20);
});

it("does not turn a withheld shelf preview into a no-matches claim", async () => {
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [],
          shelves: [
            {
              ...shelf,
              works: [],
              truncated: true,
              prefix_complete: false,
              inspected: 2,
            },
          ],
        }
      : undefined;
  setup();
  await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
  expect(screen.queryByText("No matches for these filters.")).toBeNull();
  expect(screen.getByText(/could not establish the first works/)).toBeTruthy();
});

it("polls while Library Finish has not loaded its first catalogue version", async () => {
  let reads = 0;
  overrides = (url) =>
    url.startsWith("/api/library/shelves?") && reads++ === 0
      ? {
          ...listing,
          status: "loading",
          loading: true,
          catalogue_version: null,
          total: 0,
          works: [],
          shelves: [],
        }
      : undefined;
  setup();
  await screen.findByText("Library Finish is loading · reload shortly");
  await screen.findByRole(
    "heading",
    { name: "Gaunt's Ghosts" },
    { timeout: 4000 },
  );
  expect(reads).toBeGreaterThan(1);
});

it("names a shelf entry with position, title, author and truthful copy status", async () => {
  setup();
  const entry = await screen.findByRole("button", {
    name: /Book 1.*First and Only.*Dan Abnett.*Saved match/,
  });
  expect(entry.getAttribute("aria-label")).toBeNull();
  expect(entry.getAttribute("aria-pressed")).toBe("true");
});

it.each([
  [
    { total: 45, catalogue_total: 87, counts: { saved: 45 } },
    "Dan Abnett · 45 of 87 shelved with a saved match",
  ],
  [
    { total: 15, catalogue_total: 15, counts: { direct: 10, contained: 5 } },
    "Dan Abnett · 15 shelved, every one with a matched copy",
  ],
  [
    { total: 15, catalogue_total: 87, counts: { direct: 10, contained: 5 } },
    "Dan Abnett · 15 of 87 shelved with a matched copy",
  ],
  [
    { total: 15, catalogue_total: 87, counts: { direct: 3, saved: 12 } },
    "Dan Abnett · 15 of 87 shelved: 3 with a matched copy and 12 with a saved match",
  ],
  [
    {
      total: 15,
      catalogue_total: 87,
      counts: { direct: 2, saved: 0 },
      inspected: 2,
      counts_complete: false,
      truncated: true,
    },
    "Dan Abnett · 87 catalogue titles; 2 of 15 entries read",
  ],
])(
  "uses the catalogue denominator and inspected evidence in the shelf summary %#",
  async (patch, expected) => {
    overrides = (url) =>
      url.startsWith("/api/library/shelves?")
        ? { ...listing, shelves: [{ ...shelf, ...patch }] }
        : undefined;
    const view = setup();
    await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
    expect(
      view.container
        .querySelector(".shelf-context")
        ?.textContent?.replaceAll("\u00a0", " "),
    ).toBe(expected);
    if (patch.catalogue_total === 87)
      expect(screen.getByRole("link", { name: "All 87 →" })).toBeTruthy();
    expect(screen.queryByText(/Counts below describe this read/)).toBeNull();
    expect(view.container.querySelector(".shelf-order-context")).toBeNull();
  },
);

it("keeps the match clause when a complete check confirms every shelved copy", async () => {
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          coverage: "complete",
          shelves: [{ ...shelf, counts: { direct: 15 } }],
        }
      : undefined;
  setup();
  expect(await screen.findByText(/every one with a matched copy/)).toBeTruthy();
});

it("uses catalogue author credits and adds shared-position alternates quietly", async () => {
  const lead = {
    ...work,
    authors: ["A", "B", "C", "D", "E", "F", "G", "H"],
    shelf_alternates: 1,
  };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [lead],
          shelves: [{ ...shelf, works: [lead] }],
        }
      : undefined;
  setup();
  const entry = await screen.findByRole("button", { name: /First and Only/ });
  expect(
    within(entry).getByText("A, B and 6 others", { selector: ".book-author" }),
  ).toBeTruthy();
  expect(within(entry).getByText("+1 at this position")).toBeTruthy();
});

it("calls a non-lead shared-position work Position 1 in detail", async () => {
  const alternate = {
    ...work,
    series: [{ ...work.series[0], lead_work_id: "w_other", position_total: 2 }],
  };
  overrides = (url) =>
    url.startsWith("/api/library?")
      ? {
          ...listing,
          works: [alternate],
          shelves: undefined,
        }
      : undefined;
  const view = setup(false, { lx: "title", lw: work.id });
  await screen.findByRole("heading", { name: work.title, level: 2 });
  expect(
    view.container.querySelector(".book-bibliography")?.textContent,
  ).toContain("Position 1");
});

it("presses a multi-series work on exactly one shelf and uses that shelf in detail", async () => {
  const multi = {
    ...work,
    series: [{ id: "8", name: "Other series", position: 3 }, ...work.series],
  };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [multi],
          shelves: [
            { ...shelf, works: [multi] },
            { ...shelf, id: "8", name: "Other series", works: [multi] },
          ],
        }
      : undefined;
  const view = setup(false, { lw: work.id });
  await screen.findByRole("heading", { name: "Other series" });
  expect(
    view.container.querySelectorAll('.shelf-entry[aria-pressed="true"]'),
  ).toHaveLength(1);
  expect(
    view.container.querySelector(".book-bibliography")?.textContent,
  ).toContain("Gaunt's Ghosts");
});

it("derives the active shelf from a selected work on a later shelf", async () => {
  const later = {
    ...work,
    id: "w_later",
    title: "Later work",
    series: [{ id: "8", name: "Other series", position: 2 }],
  };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [work, later],
          shelves: [
            { ...shelf, works: [work] },
            { ...shelf, id: "8", name: "Other series", works: [later] },
          ],
        }
      : undefined;
  const view = setup(false, { lw: "w_later" });
  await screen.findByRole("heading", { name: "Later work", level: 2 });
  expect(
    view.container.querySelector(".book-bibliography")?.textContent,
  ).toContain("Other series");
});

it("encodes the no-series shelf identity and does not select a phone book on first load", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  const alone = { ...work, series: [] };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: [alone],
          shelves: [
            { ...shelf, id: null, name: "Not in a series", works: [alone] },
          ],
        }
      : undefined;
  const view = setup(true);
  const entry = await screen.findByRole("button", { name: /First and Only/ });
  expect(
    view.container.querySelectorAll('.shelf-entry[aria-pressed="true"]'),
  ).toHaveLength(0);
  fireEvent.click(entry);
  await waitFor(() =>
    expect(new URLSearchParams(location.search).get("ls")).toBe("none"),
  );
});

it("returns from Catalogue with ld cleared and Forward into detail restores focus mode", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  const view = setup(true);
  fireEvent.click(
    await screen.findByRole("button", { name: /First and Only/ }),
  );
  fireEvent.click(await screen.findByText("Record details", { exact: true }));
  fireEvent.click(screen.getByRole("link", { name: "Catalogue evidence" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Return to library results" }),
  );
  await screen.findByRole("heading", { name: "Your library" });
  await waitFor(() =>
    expect(new URLSearchParams(location.search).has("ld")).toBe(false),
  );
  history.replaceState(
    null,
    "",
    `/?lx=series&lt=${token}&lw=w_first&ls=7&ld=1`,
  );
  fireEvent.popState(window);
  await waitFor(() =>
    expect(view.container.querySelector(".library-focused")).toBeTruthy(),
  );
});

it("polls Preparing shelves until the background match index is ready", async () => {
  let reads = 0;
  overrides = (url) =>
    url.startsWith("/api/library/shelves?") && reads++ === 0
      ? {
          ...listing,
          status: "preparing",
          works: [],
          shelves: [],
        }
      : undefined;
  setup();
  await screen.findByText("Preparing shelves…");
  expect(screen.queryByText("No results on this page.")).toBeNull();
  await screen.findByRole(
    "heading",
    { name: "Gaunt's Ghosts" },
    { timeout: 4000 },
  );
  expect(reads).toBeGreaterThan(1);
});

it("keeps exactly one responsive preview row and retains its selected work", async () => {
  let resize: ResizeObserverCallback;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private callback: ResizeObserverCallback) {}
      observe(node: Element) {
        if (node.classList.contains("reading-room")) resize = this.callback;
      }
      disconnect() {}
    },
  );
  const many = Array.from({ length: 5 }, (_, i) => ({
    ...work,
    id: `w_${i}`,
    title: `Title ${i}`,
    series: [{ ...work.series[0], position: i + 1 }],
  }));
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          works: many,
          shelves: [{ ...shelf, works: many }],
        }
      : undefined;
  const view = setup(false, { lw: "w_4", ls: "7" });
  await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
  for (const [width, count] of [
    [1300, 5],
    [1150, 4],
    [1000, 3],
  ]) {
    act(() =>
      resize!(
        [{ contentRect: { width } } as ResizeObserverEntry],
        {} as ResizeObserver,
      ),
    );
    expect(view.container.querySelectorAll(".shelf-entry")).toHaveLength(count);
    expect(
      view.container.querySelector('.shelf-entry[aria-pressed="true"]')
        ?.textContent,
    ).toContain("Title 4");
  }
});

it.each([390, 320])(
  "retains all five phone preview books at %spx",
  async (width) => {
    vi.stubGlobal("innerWidth", width);
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    }));
    const many = Array.from({ length: 5 }, (_, i) => ({
      ...work,
      id: `w_${i}`,
      title: `Book title ${i + 1}`,
    }));
    overrides = (url) =>
      url.startsWith("/api/library/shelves?")
        ? { ...listing, works: many, shelves: [{ ...shelf, works: many }] }
        : undefined;
    const view = setup();
    await screen.findByRole("heading", { name: shelf.name });
    expect(view.container.querySelectorAll(".shelf-entry")).toHaveLength(5);
    const fifth = screen.getByRole("button", { name: /Book title 5/ });
    expect(fifth.tabIndex).toBe(0);
    fifth.focus();
    expect(document.activeElement).toBe(fifth);
    fireEvent.click(fifth);
    await screen.findByRole("heading", { name: "Book title 5", level: 2 });
  },
);

it.each(["page", "reload"])(
  "keeps the previous page and pane visible while %s prepares",
  async (change) => {
    let preparing = false;
    overrides = (url) =>
      url.startsWith("/api/library/shelves?")
        ? preparing
          ? { ...listing, status: "preparing", page: 2, shelves: [], works: [] }
          : { ...listing, series_total: 8 }
        : undefined;
    const view = setup();
    await screen.findByRole("heading", { name: work.title, level: 2 });
    preparing = true;
    if (change === "page")
      fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    else {
      fireEvent.click(screen.getByText("Details", { exact: true }));
      fireEvent.click(screen.getByRole("button", { name: "Reload library" }));
    }
    await screen.findByText("Preparing shelves…");
    expect(
      screen.getByRole("heading", { name: shelf.name, hidden: true }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: work.title, level: 2 }),
    ).toBeTruthy();
    expect(
      view.container.querySelector('.shelves-display[aria-busy="true"]'),
    ).toBeTruthy();
    expect(screen.getByText(/Showing the previous page/)).toBeTruthy();
  },
);

it("deduplicates entry credits and singularises the one remaining author", () => {
  expect(shelfCredits(["Zed", "Amy", "Zed", "Bea"])).toBe(
    "Zed, Amy and 1 other",
  );
});

it("renders the server's shelf credit without substituting raw work authors", async () => {
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          shelves: [{ ...shelf, credit: { names: ["Zed", "Amy"], others: 4 } }],
        }
      : undefined;
  const view = setup();
  await screen.findByRole("heading", { name: shelf.name });
  expect(view.container.querySelector(".shelf-context")?.textContent).toMatch(
    /^Zed and Amy/,
  );
});

it("uses Various authors when no ranked canonical credit meets the threshold", async () => {
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          shelves: [{ ...shelf, credit: { names: [], others: 8 } }],
        }
      : undefined;
  const view = setup();
  await screen.findByRole("heading", { name: shelf.name });
  expect(view.container.querySelector(".shelf-context")?.textContent).toMatch(
    /^Various authors/,
  );
});

it("shows a single-title match without every one", async () => {
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? {
          ...listing,
          shelves: [
            { ...shelf, total: 1, catalogue_total: 1, counts: { saved: 1 } },
          ],
        }
      : undefined;
  setup();
  expect(await screen.findByText(/1 shelved, with a saved match/)).toBeTruthy();
});

it("names zero positions accessibly without putting a chip over the cover", async () => {
  const zero = { ...work, series: [{ ...work.series[0], position: 0 }] };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? { ...listing, works: [zero], shelves: [{ ...shelf, works: [zero] }] }
      : url.startsWith("/api/catalogue/covers?")
        ? {
            snapshot: { version, sha256 },
            covers: {
              [work.id]: {
                url: "/api/catalogue/covers/w_first/test",
                width: 200,
                height: 300,
                sha256,
                media_type: "image/jpeg",
              },
            },
          }
        : undefined;
  setup();
  const entry = await screen.findByRole("button", {
    name: /Position 0.*First and Only/,
  });
  await waitFor(() => expect(entry.querySelector("img")).toBeTruthy());
  expect(entry.querySelector(".position-badge")).toBeNull();
  expect(entry.querySelector(".shelf-position")?.textContent).toBe(
    "Position 0",
  );
  expect(entry.querySelector(".shelf-caption > .sr-only")?.textContent).toBe(
    ", ",
  );
});

it("opens all standalone titles in Title order, preserving query and Copies, with Back to the shelf", async () => {
  history.replaceState(null, "", "/?lx=series&lq=Alone&lo=direct");
  const alone = { ...work, series: [] };
  overrides = (url) =>
    url.startsWith("/api/library/shelves?")
      ? url.includes("group=standalone")
        ? {
            ...listing,
            total: 573,
            page_size: 24,
            works: [alone],
            shelves: undefined,
          }
        : {
            ...listing,
            works: [alone],
            shelves: [
              {
                ...shelf,
                id: null,
                name: "Standalone and collected",
                total: 573,
                catalogue_total: 2908,
                works: [alone],
              },
            ],
          }
      : undefined;
  setup(true);
  fireEvent.click(await screen.findByRole("link", { name: "All 573 →" }));
  await screen.findByText("Showing all 573 standalone and collected titles");
  const params = new URLSearchParams(location.search);
  expect(params.get("lx")).toBe("title");
  expect(params.get("lq")).toBe("Alone");
  expect(params.get("lo")).toBe("direct");
  expect(
    calls.some(
      (url) =>
        url.includes("group=standalone") &&
        url.includes("q=Alone") &&
        url.includes("ownership=direct"),
    ),
  ).toBe(true);
  act(() => history.back());
  await screen.findByRole("heading", { name: "Standalone and collected" });
});

it("prefers the largest catalogue membership in Title detail and the clicked shelf in Series detail", async () => {
  const memberships = [
    {
      id: "9",
      name: "Warhammer 40,000",
      position: null,
      work_count: 1847,
      shelf_eligible: false,
    },
    { id: "8", name: "A translation series", position: 1, work_count: 12 },
    { id: "7", name: "The Horus Heresy", position: 1, work_count: 808 },
  ];
  overrides = (url) =>
    url.startsWith("/api/library?")
      ? {
          ...listing,
          works: [{ ...work, series: memberships }],
          shelves: undefined,
        }
      : url.startsWith("/api/catalogue/works/")
        ? {
            id: work.id,
            snapshot: { version, sha256, fixture: false },
            series: memberships,
          }
        : undefined;
  const view = setup(false, { lx: "title" });
  await waitFor(() =>
    expect(
      view.container.querySelector(".book-bibliography")?.textContent,
    ).toContain("The Horus Heresy"),
  );
});

it("binds separators to preceding text and leaves a normal following space", async () => {
  const view = setup();
  await screen.findByRole("heading", { name: "Gaunt's Ghosts" });
  expect(view.container.querySelector(".shelf-context")?.textContent).toBe(
    "Dan Abnett\u00a0· 15 shelved, every one with a saved match",
  );
  await waitFor(() =>
    expect(
      view.container.querySelector(".book-bibliography")?.textContent,
    ).toContain("Gaunt's Ghosts\u00a0· Book 1"),
  );
  expect(
    view.container.querySelector(".library-status-well")?.textContent,
  ).toContain("Direct match\u00a0· saved match");
});
