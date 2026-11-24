// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { Catalogue, type CatalogueRoute } from "../src/Catalogue";

const snapshot = {
  version: "2026.10.25.1",
  sha256: "a".repeat(64),
  fixture: true,
};
const row = {
  id: "w_fixture",
  title: "Fixture: The Glass Meridian",
  authors: [{ id: 1, name: "Fixture Author", version: snapshot.version }],
  series: [],
  edition_count: 1,
};
let paths: string[] = [];
let navigations: Partial<CatalogueRoute>[] = [];
let intercept: (path: string) => Response | Promise<Response> | undefined;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
function mount(
  initial: Partial<CatalogueRoute> = {},
  libraryConnected = false,
) {
  paths = [];
  navigations = [];
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Element.prototype.scrollTo = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      paths.push(input);
      const custom = intercept?.(input);
      if (custom) return custom;
      if (input === "/api/catalogue")
        return json({ status: "ready", ...snapshot, total: 1 });
      if (input.startsWith("/api/catalogue/works/w_fixture"))
        return json({
          ...row,
          synopsis: "Fictional contract record.",
          snapshot,
          ownership: "unconfirmed",
          editions: [
            {
              id: "e_fixture",
              format: "ebook",
              isbn13: "9780306406157",
              isbn10: null,
              publisher: null,
              release_date: null,
            },
          ],
          support: [
            {
              field: "title",
              value: row.title,
              agree: ["publisher"],
              disagree: [],
            },
          ],
        });
      if (input.startsWith("/api/catalogue/works?"))
        return json({
          snapshot,
          works: input.includes("absent") ? [] : [row],
          total: input.includes("absent") ? 0 : 1,
          page: 1,
          page_size: 24,
        });
      throw new Error(input);
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Harness() {
    const [route, setRoute] = useState<CatalogueRoute>({
      cq: "",
      cp: 1,
      cw: "",
      cv: "",
      ch: "",
      cs: "",
      cb: "works",
      ca: "",
      ...initial,
    });
    return (
      <Catalogue
        route={route}
        libraryConnected={libraryConnected}
        navigate={(next) => {
          navigations.push(next);
          setRoute((old) => ({ ...old, ...next }));
        }}
      />
    );
  }
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}
async function openSnapshot() {
  const summary = await screen.findByText(/Fixture data|Catalogue info/, {
    selector: ".snapshot-details summary",
  });
  fireEvent.click(summary);
  expect((summary.parentElement as HTMLDetailsElement).open).toBe(true);
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  intercept = () => undefined;
  document.getElementById("workspace-search-slot")?.remove();
});

it("preserves the committed query and unsent draft through Works and Series", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/series?")
      ? json({ snapshot, series: [], total: 0, page: 1, page_size: 24 })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cq: "Archive", cp: 2 });
  const input = await screen.findByRole("searchbox");
  fireEvent.change(input, { target: { value: "Archive draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Series" }));
  await waitFor(() =>
    expect(
      paths.some(
        (path) =>
          path.includes("catalogue/series?") &&
          path.includes("q=Archive") &&
          path.includes("page=1"),
      ),
    ).toBe(true),
  );
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(
    "Archive draft",
  );
  fireEvent.click(screen.getByRole("button", { name: "Works" }));
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(
    "Archive draft",
  );
  fireEvent.submit(screen.getByRole("search"));
  await waitFor(() =>
    expect(
      paths.some(
        (path) =>
          path.includes("catalogue/works?") && path.includes("q=Archive+draft"),
      ),
    ).toBe(true),
  );
});

it.each(["works", "series", "selected series"])(
  "uses the shared masthead search slot for %s",
  async (mode) => {
    const slot = document.createElement("div");
    slot.id = "workspace-search-slot";
    document.body.append(slot);
    intercept = (path) =>
      path.startsWith("/api/catalogue/series?")
        ? json({ snapshot, series: [], total: 0, page: 1, page_size: 24 })
        : mode === "selected series" && path.startsWith("/api/catalogue/works?")
          ? json({
              snapshot,
              works: [row],
              selected_series: series,
              selected_author: null,
              total: 1,
              page: 1,
              page_size: 24,
            })
          : undefined;
    mount({
      cv: snapshot.version,
      ch: snapshot.sha256,
      cb: mode === "series" ? "series" : "works",
      cs: mode === "selected series" ? "7" : "",
    });
    await waitFor(() =>
      expect(slot.contains(screen.getByRole("searchbox"))).toBe(true),
    );
    await screen.findByRole("searchbox", {
      name:
        mode === "series"
          ? "Search series"
          : mode === "selected series"
            ? "Search this series"
            : "Search catalogue",
    });
  },
);

it("keeps standalone Catalogue search usable without an App masthead", async () => {
  const view = mount({ cv: snapshot.version, ch: snapshot.sha256 });
  const input = await screen.findByRole("searchbox", {
    name: "Search catalogue",
  });
  expect(
    view.container.querySelector(".catalogue > form")?.contains(input),
  ).toBe(true);
  fireEvent.change(input, { target: { value: "Archive" } });
  fireEvent.submit(screen.getByRole("search"));
  await waitFor(() =>
    expect(
      paths.some(
        (path) =>
          path.startsWith("/api/catalogue/works?") &&
          path.includes("q=Archive"),
      ),
    ).toBe(true),
  );
});

it("composes general catalogue works around one title without fake artwork or an ownership claim", async () => {
  const view = mount({ cv: snapshot.version, ch: snapshot.sha256 });
  const entry = await screen.findByRole("button", {
    name: /Fixture: The Glass Meridian/,
  });
  expect(within(entry).getAllByText(row.title)).toHaveLength(1);
  expect(entry.querySelector(".shelf-art")).toBeNull();
  expect(entry.querySelector(".book-folio")).toBeNull();
  expect(
    view.container.querySelector(".series-shelves .library-state"),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(
    view.container.querySelector(".catalogue.browse-list .shelf-entry"),
  ).toBeTruthy();
});

it("presents an author room with All works preserving the selected series and query", async () => {
  const author = {
    id: "9007199254740993",
    name: "Fixture Author",
    version: snapshot.version,
  };
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          selected_series: series,
          selected_author: path.includes("author=9007199254740993")
            ? author
            : null,
          works: [row],
          total: 1,
          page: 1,
          page_size: 24,
        })
      : undefined;
  mount({
    cv: snapshot.version,
    ch: snapshot.sha256,
    cs: "7",
    ca: author.id,
    cq: "Archive",
  });
  await screen.findByRole("heading", { name: author.name, level: 1 });
  expect(screen.queryByText("Author: Fixture Author")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "All works" }));
  await waitFor(() =>
    expect(
      paths.some(
        (path) =>
          path.includes("catalogue/works?") &&
          path.includes("series=7") &&
          path.includes("q=Archive") &&
          new URL(path, "http://local").searchParams.get("author") === "",
      ),
    ).toBe(true),
  );
  expect(
    paths
      .filter((path) => path.startsWith("/api/catalogue/works?"))
      .every((path) => path.includes(snapshot.sha256)),
  ).toBe(true);
});

it("presents structured source disagreements without losing nested values", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture")
      ? json({
          ...row,
          snapshot,
          synopsis: null,
          editions: [],
          support: [
            {
              field: "series",
              value: "Northern Archive",
              agree: ["publisher"],
              disagree: [
                {
                  origin: "openlibrary",
                  value: {
                    series: ["Archive", "Winter"],
                    position: 0,
                    verified: false,
                    note: null,
                  },
                },
              ],
            },
          ],
        })
      : undefined;
  const view = mount({ cv: snapshot.version, ch: snapshot.sha256, cw: row.id });
  fireEvent.click(await screen.findByText(/Source support · 1 field/));
  const comparison = within(screen.getByRole("region", { name: "Series" }));
  expect(comparison.getByRole("heading", { name: "openlibrary" })).toBeTruthy();
  expect(comparison.getByText("Archive")).toBeTruthy();
  expect(comparison.getByText("Winter")).toBeTruthy();
  expect(comparison.getByText("0")).toBeTruthy();
  expect(comparison.getByText("false")).toBeTruthy();
  expect(comparison.getByText("Not recorded")).toBeTruthy();
  expect(screen.queryByText(/\{"series"/)).toBeNull();
  expect(
    (
      await axe.run(view.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it("keeps the author room's keyboard return and folio selection accessible", async () => {
  const author = { id: "1", name: "Fixture Author", version: snapshot.version };
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          selected_author: new URL(path, "http://local").searchParams.get(
            "author",
          )
            ? author
            : null,
          selected_series: null,
          works: [row],
          total: 1,
          page: 1,
          page_size: 24,
        })
      : undefined;
  const view = mount({ cv: snapshot.version, ch: snapshot.sha256, ca: "1" });
  await screen.findByRole("heading", { name: author.name, level: 1 });
  const all = screen.getByRole("button", { name: "All works" });
  all.focus();
  fireEvent.click(all);
  const heading = await screen.findByRole("heading", {
    name: "Catalogue",
    level: 1,
  });
  await waitFor(() => expect(document.activeElement).toBe(heading));
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  await screen.findByRole("heading", { name: row.title, level: 2 });
  expect(
    (
      await axe.run(view.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it("returns from an author's selected work to that pinned author room with keyboard context", async () => {
  history.replaceState(null, "", "/");
  const author = { id: "1", name: "Fixture Author", version: snapshot.version };
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          selected_author: author,
          selected_series: null,
          works: [row],
          total: 1,
          page: 1,
          page_size: 24,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, ca: "1", cq: "Archive" });
  const work = await screen.findByRole("button", {
    name: /Fixture: The Glass Meridian/,
  });
  fireEvent.click(work);
  await screen.findByRole("heading", { name: row.title, level: 2 });
  fireEvent.click(screen.getByRole("button", { name: "Back to author" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /Fixture: The Glass Meridian/ }),
    ),
  );
  expect(
    screen.getByRole("heading", { name: author.name, level: 1 }),
  ).toBeTruthy();
  expect(screen.getByRole("searchbox").getAttribute("value")).toBe("Archive");
});

it("pins list and detail to the same version and exposes honest evidence", async () => {
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  expect(await screen.findByRole("heading", { name: row.title })).toBeTruthy();
  expect(screen.getByText("Ownership unconfirmed")).toBeTruthy();
  expect(screen.getByText("9780306406157")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Inspect metadata/ })).toBeNull();
  expect(
    paths
      .filter((p) => p.startsWith("/api/catalogue/works"))
      .every(
        (p) =>
          p.includes(`version=${snapshot.version}`) &&
          p.includes(`sha256=${snapshot.sha256}`),
      ),
  ).toBe(true);
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

it("shows an actionable unconfigured state", async () => {
  intercept = (p) =>
    p === "/api/catalogue" ? json({ status: "not_configured" }) : undefined;
  mount();
  expect(
    await screen.findByRole("heading", { name: "No catalogue connected" }),
  ).toBeTruthy();
  expect(
    screen.getByText(/Waiting for the first published snapshot/),
  ).toBeTruthy();
  expect(paths).toEqual(["/api/catalogue"]);
});

it("offers recovery for an incomplete snapshot link", async () => {
  mount({ cv: snapshot.version });
  expect(await screen.findByRole("alert")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Use current snapshot" }));
  expect(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
});

it("searches and clears an empty result without losing its snapshot", async () => {
  mount();
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "absent" },
  });
  fireEvent.submit(screen.getByRole("search"));
  expect(await screen.findByText("No matching catalogue works")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
});

it("requires an explicit switch when a pinned snapshot disappears", async () => {
  let unavailable = true;
  intercept = (p) =>
    p.startsWith("/api/catalogue/works?") && unavailable
      ? json({ error: "Selected catalogue snapshot is unavailable" }, 409)
      : undefined;
  mount();
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeNull();
  unavailable = false;
  fireEvent.click(screen.getByRole("button", { name: "Use current snapshot" }));
  expect(
    await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
});

it("recovers a status failure through its retry control", async () => {
  let unavailable = true;
  intercept = (p) =>
    p === "/api/catalogue" && unavailable
      ? json({ error: "Catalogue snapshot is unavailable or invalid" }, 503)
      : undefined;
  mount();
  expect(await screen.findByRole("alert")).toBeTruthy();
  unavailable = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry catalogue" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /Fixture: The Glass Meridian/ }),
    ).toBeTruthy(),
  );
});

it("pages within the pinned snapshot and returns from a phone detail", async () => {
  intercept = (p) =>
    p.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          works: [row],
          total: 48,
          page: p.includes("page=2") ? 2 : 1,
          page_size: 24,
        })
      : undefined;
  mount();
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(await screen.findByText("Page 2 of 2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  await screen.findByText("Page 1 of 2");
  fireEvent.click(
    screen.getByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  const heading = await screen.findByRole("heading", { name: row.title });
  await waitFor(() => expect(document.activeElement).toBe(heading));
  fireEvent.click(screen.getByRole("button", { name: "Back to catalogue" }));
  expect(screen.queryByRole("heading", { name: row.title })).toBeNull();
});

it("does not change the route after leaving during a slow snapshot switch", async () => {
  const { unmount } = mount();
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  let finish: (response: Response) => void = () => {};
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await openSnapshot();
  fireEvent.click(screen.getByRole("button", { name: "Use current snapshot" }));
  unmount();
  const count = navigations.length;
  finish(json({ status: "ready", ...snapshot, version: "2026.10.25.2" }));
  await new Promise((resolve) => setTimeout(resolve, 25));
  expect(navigations).toHaveLength(count);
});

const series = { id: 7, name: "Fixture Archive", version: snapshot.version };

it("labels zero and unpositioned groups without changing recorded values", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          selected_series: series,
          position_counts: { numbered: 12, zero: 8, unpositioned: 30 },
          works: [-1, 0.5, 0, 0, null].map((position, i) => ({
            ...row,
            id: `w_group${i}`,
            title: `Group work ${i}`,
            series: [{ ...series, position }],
          })),
          total: 50,
          page: 1,
          page_size: 24,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "7" });
  expect(await screen.findByText("Recorded at 0 · 8")).toBeTruthy();
  expect(screen.getByText("No position · 30")).toBeTruthy();
  expect(
    screen.getAllByText("0", { selector: ".series-position" }),
  ).toHaveLength(2);
  expect(screen.getByText("-1", { selector: ".series-position" })).toBeTruthy();
  expect(
    screen.getByText("0.5", { selector: ".series-position" }),
  ).toBeTruthy();
});

it("opens a searchable series index and keeps the pin when choosing its reading order", async () => {
  intercept = (path) => {
    if (path.startsWith("/api/catalogue/series?"))
      return json({
        snapshot,
        series: [{ ...series, work_count: 3 }],
        total: 1,
        page: 1,
        page_size: 24,
      });
    if (path.startsWith("/api/catalogue/works?"))
      return json({
        snapshot,
        selected_series: path.includes("series=7") ? series : null,
        works: [{ ...row, series: [{ ...series, position: 0.5 }] }],
        total: 1,
        page: 1,
        page_size: 24,
      });
  };
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Series" }));
  fireEvent.change(
    await screen.findByRole("searchbox", { name: "Search series" }),
    { target: { value: "Archive" } },
  );
  fireEvent.submit(screen.getByRole("search"));
  await waitFor(() =>
    expect(
      paths.some(
        (p) => p.includes("catalogue/series?") && p.includes("q=Archive"),
      ),
    ).toBe(true),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture Archive.*3 works/ }),
  );
  expect(
    await screen.findByRole("heading", { name: "Fixture Archive", level: 1 }),
  ).toBeTruthy();
  expect(
    await screen.findByText("0.5", { selector: ".series-position" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("list", { name: "Works in recorded series order" }),
  ).toBeTruthy();
  expect(navigations.at(-1)).toMatchObject({
    cs: "7",
    cb: "works",
    cq: "",
    cp: 1,
    cw: "",
  });
  expect(
    paths
      .filter((p) => p.startsWith("/api/catalogue/series?"))
      .every((p) => p.includes(snapshot.sha256)),
  ).toBe(true);
});

it("opens a work's exact series and clears version-scoped IDs on a snapshot switch", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture")
      ? json({
          ...row,
          snapshot,
          synopsis: null,
          editions: [],
          support: [],
          series: [{ ...series, position: 2 }],
        })
      : undefined;
  mount({
    cv: snapshot.version,
    ch: snapshot.sha256,
    cw: row.id,
    cq: "Meridian",
    cp: 3,
  });
  fireEvent.click(
    await screen.findByRole("button", { name: /Browse Fixture Archive/ }),
  );
  expect(navigations.at(-1)).toMatchObject({ cs: "7", cq: "", cw: "", cp: 1 });
  await waitFor(() =>
    expect(
      paths.some(
        (p) => p.startsWith("/api/catalogue/works?") && p.includes("series=7"),
      ),
    ).toBe(true),
  );
  await openSnapshot();
  fireEvent.click(screen.getByRole("button", { name: "Use current snapshot" }));
  await waitFor(() =>
    expect(navigations.at(-1)).toMatchObject({ cs: "", cw: "", cp: 1 }),
  );
});

it("keeps a selected series through search, pagination and evidence return", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          selected_series: series,
          works: [{ ...row, series: [{ ...series, position: null }] }],
          total: 48,
          page: path.includes("page=2") ? 2 : 1,
          page_size: 24,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "7" });
  await screen.findByText("No position");
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "Meridian" },
  });
  fireEvent.submit(screen.getByRole("search"));
  await waitFor(() =>
    expect(
      paths.some((p) => p.includes("q=Meridian") && p.includes("series=7")),
    ).toBe(true),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Next" }));
  await screen.findByText("Page 2 of 2");
  fireEvent.click(
    screen.getByRole("button", { name: /Fixture: The Glass Meridian/ }),
  );
  await screen.findByRole("heading", { name: row.title });
  fireEvent.click(screen.getByRole("button", { name: "Back to series" }));
  expect(navigations.at(-1)).toEqual({ cw: "" });
  expect(screen.getByRole("searchbox").getAttribute("value")).toBe("Meridian");
  expect(screen.getByText("Page 2 of 2")).toBeTruthy();
});

it("shows an unknown series without suggesting that the whole catalogue is empty", async () => {
  intercept = (p) =>
    p.startsWith("/api/catalogue/works?")
      ? json({
          snapshot,
          selected_series: null,
          works: [],
          total: 0,
          page: 1,
          page_size: 24,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "999" });
  expect(
    await screen.findByRole("heading", {
      name: "Series not found in this snapshot",
    }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Browse all series" }));
  expect(navigations.at(-1)).toMatchObject({
    cs: "",
    cb: "series",
    cq: "",
    cp: 1,
  });
});

it("keeps a new search draft and its focus when a slow series index arrives", async () => {
  mount();
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  let finish: (value: Response) => void = () => {};
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Series" }));
  const search = await screen.findByRole("searchbox", {
    name: "Search series",
  });
  search.focus();
  fireEvent.change(search, { target: { value: "My unfinished search" } });
  finish(
    json({
      snapshot,
      series: [{ ...series, work_count: 3 }],
      total: 1,
      page: 1,
      page_size: 24,
    }),
  );
  await screen.findByRole("button", { name: /Fixture Archive.*3 works/ });
  expect(document.activeElement).toBe(search);
  expect((search as HTMLInputElement).value).toBe("My unfinished search");
});

it("does not let an abandoned series request replace the current catalogue", async () => {
  mount();
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  let finish: (value: Response) => void = () => {};
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Series" }));
  await screen.findByText("Loading catalogue series…");
  fireEvent.click(screen.getByRole("button", { name: "Works" }));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  finish(
    json({
      snapshot,
      series: [{ ...series, work_count: 3 }],
      total: 1,
      page: 1,
      page_size: 24,
    }),
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(
    screen.queryByRole("button", { name: /Fixture Archive.*3 works/ }),
  ).toBeNull();
  expect(
    screen.getByRole("heading", { name: "Catalogue", level: 1 }),
  ).toBeTruthy();
});

it("retries a series index failure without discarding its search or snapshot", async () => {
  let fail = true;
  intercept = (path) =>
    path.startsWith("/api/catalogue/series?")
      ? fail
        ? json({ error: "Catalogue unavailable" }, 503)
        : json({
            snapshot,
            series: [{ ...series, work_count: 3 }],
            total: 1,
            page: 1,
            page_size: 24,
          })
      : undefined;
  mount({
    cv: snapshot.version,
    ch: snapshot.sha256,
    cb: "series",
    cq: "Archive",
  });
  await screen.findByRole("alert");
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry catalogue" }));
  await screen.findByRole("button", { name: /Fixture Archive.*3 works/ });
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(
    "Archive",
  );
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

it("keeps exact string IDs in series navigation", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/series?")
      ? json({
          snapshot,
          series: [{ ...series, id: "9007199254740993", work_count: 3 }],
          total: 1,
          page: 1,
          page_size: 24,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cb: "series" });
  fireEvent.click(
    await screen.findByRole("button", { name: /Fixture Archive.*3 works/ }),
  );
  expect(navigations.at(-1)?.cs).toBe("9007199254740993");
});

it.each(["series", "works"])(
  "recovers a shared %s link beyond its final page",
  async (cb) => {
    intercept = (path) => {
      if (path.startsWith("/api/catalogue/series?"))
        return json({
          snapshot,
          series: [],
          total: 48,
          page: 3,
          page_size: 24,
        });
      if (path.startsWith("/api/catalogue/works?"))
        return json({
          snapshot,
          selected_series: series,
          works: [],
          total: 48,
          page: 3,
          page_size: 24,
        });
    };
    mount({
      cv: snapshot.version,
      ch: snapshot.sha256,
      cb,
      cp: 3,
      cs: cb === "works" ? "7" : "",
    });
    expect(
      await screen.findByRole("heading", { name: "This page has no results" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "First page" }));
    expect(navigations.at(-1)).toEqual({ cp: 1 });
  },
);

it("does not attach an unpinned series ID to the current catalogue", async () => {
  mount({ cs: "7" });
  await screen.findByRole("alert");
  expect(paths.some((p) => p.startsWith("/api/catalogue/works?"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Use current snapshot" }));
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  expect(navigations.at(-1)).toMatchObject({
    cs: "",
    cv: snapshot.version,
    ch: snapshot.sha256,
  });
});

it("shows work failure recovery inside the focused evidence panel", async () => {
  let fail = true;
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture") && fail
      ? json({ error: "Catalogue work not found" }, 404)
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cw: row.id, cs: "7" });
  const panel = screen.getByRole("complementary", {
    name: "Catalogue evidence",
  });
  await waitFor(() =>
    expect(panel.textContent).toContain("Unable to load this work"),
  );
  expect(panel.querySelector("button")?.textContent).toBe(
    "Retry work evidence",
  );
  fail = false;
  fireEvent.click(panel.querySelector("button")!);
  await screen.findByRole("heading", { name: row.title });
});

it("filters the selected series by exact author identity and exposes bibliography values", async () => {
  const author = {
    id: "9007199254740993",
    name: "Fixture Author",
    version: snapshot.version,
  };
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture")
      ? json({
          ...row,
          authors: [author],
          snapshot,
          type: "short_story",
          first_published: "2021-05",
          synopsis: null,
          editions: [],
          support: [],
        })
      : path.startsWith("/api/catalogue/works?")
        ? json({
            snapshot,
            selected_series: series,
            selected_author: path.includes("author=9007199254740993")
              ? author
              : null,
            works: [
              { ...row, type: "short_story", first_published: "2021-05" },
            ],
            total: 1,
            page: 1,
            page_size: 24,
          })
        : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "7", cw: row.id });
  await screen.findByRole("heading", { name: row.title });
  expect(screen.getAllByText(/Short story/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/2021-05/).length).toBeGreaterThan(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Browse author Fixture Author" }),
  );
  expect(navigations.at(-1)).toMatchObject({
    ca: author.id,
    cq: "",
    cp: 1,
    cw: "",
  });
  await waitFor(() =>
    expect(
      paths.some(
        (p) => p.includes("author=9007199254740993") && p.includes("series=7"),
      ),
    ).toBe(true),
  );
  fireEvent.click(await screen.findByRole("button", { name: "All works" }));
  expect(navigations.at(-1)).toMatchObject({ ca: "", cp: 1 });
});

it("joins saved series matches by exact work ID and keeps partial coverage explicit", async () => {
  intercept = (path) => {
    if (path.startsWith("/api/catalogue/works?"))
      return json({
        snapshot: { ...snapshot, fixture: false },
        selected_series: series,
        works: [row, { ...row, id: "w_other", title: "Other work" }],
        total: 2,
        page: 1,
        page_size: 24,
      });
    if (path.startsWith("/api/library/series?"))
      return json({
        status: "ready",
        catalogue_version: snapshot.version,
        checked_at: "2026-10-25T12:00:00Z",
        snapshot: "b".repeat(24),
        coverage: "partial",
        truncated: false,
        works: [
          {
            id: row.id,
            title: row.title,
            state: "direct",
            current: false,
            copies: [
              { calibre_id: 41, title: "Saved Calibre copy", last_known: true },
            ],
            contained_in: [],
            candidates: [],
          },
        ],
      });
  };
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "7" }, true);
  const matched = await screen.findByRole("button", {
    name: /Fixture: The Glass Meridian.*Direct match/,
  });
  expect(
    screen.getByRole("button", { name: /Other work/ }).textContent,
  ).not.toContain("Direct match");
  expect(screen.getByText(/Partial check/)).toBeTruthy();
  fireEvent.click(matched);
  expect(await screen.findByText("Saved Calibre copy")).toBeTruthy();
  expect(screen.getByText(/Calibre #41/)).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "View in library" }).getAttribute("href"),
  ).toContain(`lt=${"b".repeat(24)}`);
});

it("keeps catalogue browsing usable when library evidence fails or belongs to another version", async () => {
  let failed = true;
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          snapshot: { ...snapshot, fixture: false },
          selected_series: series,
          works: [row],
          total: 1,
          page: 1,
          page_size: 24,
        })
      : path.startsWith("/api/library/series?")
        ? failed
          ? json({ error: "Library service unavailable" }, 502)
          : json({
              status: "version_mismatch",
              catalogue_version: "2026.10.01.1",
              works: [],
            })
        : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "7" }, true);
  await screen.findByText(/Library evidence unavailable/);
  expect(
    screen.getByRole("button", { name: /Fixture: The Glass Meridian/ }),
  ).toBeTruthy();
  failed = false;
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh saved matches" }),
  );
  await screen.findByText(/uses a different catalogue version/);
  expect(screen.queryByText("Direct match")).toBeNull();
});

it.each(["contained", "pending"])(
  "shows %s evidence without calling it a direct copy",
  async (state) => {
    intercept = (path) => {
      if (path.startsWith("/api/catalogue/works?"))
        return json({
          snapshot: { ...snapshot, fixture: false },
          selected_series: series,
          works: [row],
          total: 1,
          page: 1,
          page_size: 24,
        });
      if (path.startsWith("/api/library/series?"))
        return json({
          status: "ready",
          catalogue_version: snapshot.version,
          checked_at: null,
          snapshot: "b".repeat(24),
          coverage: "partial",
          truncated: true,
          works: [
            {
              id: row.id,
              title: row.title,
              state,
              current: false,
              copies: [],
              contained_in:
                state === "contained"
                  ? [
                      {
                        calibre_id: 42,
                        title: "Containing anthology",
                        last_known: true,
                      },
                    ]
                  : [],
              candidates:
                state === "pending"
                  ? [
                      {
                        title: "Possible incoming copy",
                        stage: "inbox",
                        confidence: "possible",
                      },
                    ]
                  : [],
            },
          ],
        });
    };
    mount(
      { cv: snapshot.version, ch: snapshot.sha256, cs: "7", cw: row.id },
      true,
    );
    if (state === "contained") {
      await screen.findByText("Containing anthology");
      expect(screen.getByText(/Calibre #42/)).toBeTruthy();
    } else {
      await screen.findByText("Possible incoming copy");
      expect(screen.getByText(/Inbox.*possible match/)).toBeTruthy();
    }
    expect(screen.queryByText("Calibre copies")).toBeNull();
    const context = screen.getByRole("region", {
      name: "Saved library evidence",
    });
    expect(within(context).getByText(/partial list/)).toBeTruthy();
    expect(within(context).getByText(/No check date/)).toBeTruthy();
  },
);

it("does not request real library evidence for a catalogue fixture", async () => {
  mount({ cv: snapshot.version, ch: snapshot.sha256, cs: "7" }, true);
  await screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
  expect(paths.some((path) => path.startsWith("/api/library/series?"))).toBe(
    false,
  );
});

it("checks a standalone catalogue work through title candidates verified by exact identity", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture")
      ? json({
          ...row,
          snapshot: { ...snapshot, fixture: false },
          synopsis: null,
          editions: [],
          support: [],
        })
      : path.startsWith("/api/library/works/w_fixture?")
        ? json({
            status: "ready",
            catalogue_version: snapshot.version,
            lookup: "title_candidates_verified_by_id",
            snapshot: "b".repeat(24),
            coverage: "partial",
            works: [
              {
                id: row.id,
                title: row.title,
                state: "direct",
                current: false,
                copies: [
                  {
                    calibre_id: 43,
                    title: "Standalone saved copy",
                    last_known: true,
                  },
                ],
                contained_in: [],
                candidates: [],
              },
            ],
          })
        : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cw: row.id }, true);
  await screen.findByText("Standalone saved copy");
  expect(screen.getByText(/Calibre #43/)).toBeTruthy();
  expect(
    paths.some(
      (path) =>
        path.startsWith("/api/library/works/w_fixture?") &&
        path.includes(`sha256=${snapshot.sha256}`),
    ),
  ).toBe(true);
  expect(paths.some((path) => path.startsWith("/api/library/series?"))).toBe(
    false,
  );
});

it("does not turn an empty work-evidence search into an ownership claim", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture")
      ? json({
          ...row,
          snapshot: { ...snapshot, fixture: false },
          synopsis: null,
          editions: [],
          support: [],
        })
      : path.startsWith("/api/library/works/w_fixture?")
        ? json({
            status: "ready",
            catalogue_version: snapshot.version,
            snapshot: "b".repeat(24),
            coverage: "complete",
            truncated: true,
            works: [],
          })
        : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cw: row.id }, true);
  await screen.findByText(/No saved match · may still be in your library/);
  expect(screen.getByText(/incomplete search, unconfirmed/)).toBeTruthy();
  expect(screen.queryByText("No matched copy")).toBeNull();
});

it("ignores a late saved-evidence response after selecting another series", async () => {
  let finish: (response: Response) => void = () => {};
  const nextSeries = { ...series, id: "8", name: "Other archive" };
  const nextWork = { ...row, id: "w_next", title: "Next work" };
  intercept = (path) => {
    if (path.startsWith("/api/catalogue/works?"))
      return json({
        snapshot: { ...snapshot, fixture: false },
        selected_series: path.includes("series=8") ? nextSeries : series,
        works: [path.includes("series=8") ? nextWork : row],
        total: 1,
        page: 1,
        page_size: 24,
      });
    if (path.startsWith("/api/catalogue/works/w_fixture"))
      return json({
        ...row,
        snapshot,
        synopsis: null,
        series: [{ ...nextSeries, position: 1 }],
        editions: [],
        support: [],
      });
    if (path.startsWith("/api/library/series?series=7"))
      return new Promise((resolve) => {
        finish = resolve;
      });
    if (path.startsWith("/api/library/series?series=8"))
      return json({
        status: "ready",
        catalogue_version: snapshot.version,
        snapshot: "b".repeat(24),
        coverage: "partial",
        works: [
          {
            id: "w_next",
            title: nextWork.title,
            state: "direct",
            current: false,
            copies: [],
            contained_in: [],
            candidates: [],
          },
        ],
      });
  };
  mount(
    { cv: snapshot.version, ch: snapshot.sha256, cs: "7", cw: row.id },
    true,
  );
  await screen.findByText("Reading saved library matches…");
  fireEvent.click(
    await screen.findByRole("button", { name: "Browse Other archive" }),
  );
  await screen.findByRole("button", { name: /Next work.*Direct match/ });
  finish(
    json({
      status: "ready",
      catalogue_version: snapshot.version,
      snapshot: "a".repeat(24),
      coverage: "partial",
      works: [
        {
          id: row.id,
          title: row.title,
          state: "contained",
          copies: [],
          contained_in: [],
          candidates: [],
        },
      ],
    }),
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(screen.queryByText("In a collection")).toBeNull();
  expect(
    screen.getByRole("heading", { name: nextSeries.name, level: 1 }),
  ).toBeTruthy();
});

it("keeps a dated series match but marks it stale inside the work panel when refresh fails", async () => {
  let unavailable = false;
  intercept = (path) => {
    if (path.startsWith("/api/catalogue/works?"))
      return json({
        snapshot: { ...snapshot, fixture: false },
        selected_series: series,
        works: [row],
        total: 1,
        page: 1,
        page_size: 24,
      });
    if (path.startsWith("/api/library/series?"))
      return unavailable
        ? json({ error: "Saved check unavailable" }, 503)
        : json({
            status: "ready",
            catalogue_version: snapshot.version,
            snapshot: "b".repeat(24),
            coverage: "partial",
            checked_at: "2026-10-25T17:14:10Z",
            works: [
              {
                id: row.id,
                title: row.title,
                kind: "novel",
                state: "direct",
                current: false,
                copies: [
                  {
                    calibre_id: 42,
                    title: "Saved library title",
                    last_known: true,
                  },
                ],
                contained_in: [],
                candidates: [],
              },
            ],
          });
  };
  mount(
    { cv: snapshot.version, ch: snapshot.sha256, cs: "7", cw: row.id },
    true,
  );
  const proof = await screen.findByRole("region", {
    name: "Saved match for this work",
  });
  expect(within(proof).getByText("Saved library title")).toBeTruthy();
  unavailable = true;
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh saved matches" }),
  );
  await waitFor(() =>
    expect(within(proof).getByText(/refresh failed/)).toBeTruthy(),
  );
  expect(within(proof).getByText("Saved library title")).toBeTruthy();
  expect(within(proof).getByText(/current copy unconfirmed/)).toBeTruthy();
});

it("keeps the pin compact and flags a newer snapshot", async () => {
  intercept = (path) =>
    path === "/api/catalogue"
      ? json({
          status: "ready",
          ...snapshot,
          version: "2026.10.25.2",
          total: 1,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256 });
  const summary = await screen.findByText(/update available/, {
    selector: ".snapshot-details summary",
  });
  expect(summary.textContent).toContain("Fixture data");
  expect(summary.textContent).not.toContain(snapshot.version);
  fireEvent.click(summary);
  expect(screen.getByText(snapshot.version)).toBeTruthy();
  fireEvent.click(summary);
  expect((summary.parentElement as HTMLDetailsElement).open).toBe(false);
  expect(screen.getByText(snapshot.sha256)).toBeTruthy();
});

it("collapses long edition and support lists behind counted summaries", async () => {
  const editions = Array.from({ length: 90 }, (_, i) => ({
    id: `e_${i}`,
    format: "ebook",
    isbn13: null,
    isbn10: null,
    publisher: null,
    release_date: null,
  }));
  const support = Array.from({ length: 100 }, (_, i) => ({
    field: `field_${i}`,
    value: "v",
    agree: ["publisher"],
    disagree: i < 2 ? [{ origin: "openlibrary", value: "x" }] : [],
  }));
  intercept = (path) =>
    path.startsWith("/api/catalogue/works/w_fixture")
      ? json({
          ...row,
          type: "novel",
          first_published: "1999",
          edition_count: 90,
          snapshot,
          synopsis: null,
          editions,
          support,
        })
      : undefined;
  mount({ cv: snapshot.version, ch: snapshot.sha256, cw: row.id });
  await screen.findByRole("heading", { name: row.title });
  expect(screen.getByText(/Novel · First published 1999/)).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Browse author Fixture Author" }),
  ).toBeTruthy();
  const editionSummary = screen.getByText("Editions · 90");
  const supportSummary = screen.getByText(
    "Source support · 100 fields · 2 disputed records",
  );
  expect((editionSummary.parentElement as HTMLDetailsElement).open).toBe(false);
  expect((supportSummary.parentElement as HTMLDetailsElement).open).toBe(false);
});
