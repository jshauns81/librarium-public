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
import { seriesShelfSummary } from "../src/SeriesRoom";

const snapshot = {
  version: "2026.10.24.2",
  sha256: "c".repeat(64),
  fixture: false,
};
const series = {
  id: "516",
  name: "The Horus Heresy",
  version: snapshot.version,
};
const abnett = { id: 11, name: "Dan Abnett", version: snapshot.version };
const mcneill = { id: 12, name: "Graham McNeill", version: snapshot.version };
const longTitle =
  "Wywyższenie Horusa: Ziarna herezji zostały zasiane, an edition whose recorded title keeps every one of its many words";
const work = (
  id: string,
  title: string,
  position: number | null,
  extra: Record<string, unknown> = {},
) => ({
  id,
  title,
  authors: [abnett],
  series: [{ ...series, position }],
  edition_count: 2,
  type: "novel",
  first_published: "2006-04-01",
  ...extra,
});
const works = [
  work("w_rising", "Horus Rising", 1, {
    cover: {
      url: "/api/catalogue/covers/abc.jpg",
      sha256: "d".repeat(64),
      width: 400,
      height: 600,
      media_type: "image/jpeg",
    },
  }),
  work("w_gods", "False Gods", 2, { authors: [mcneill], type: "short_story" }),
  work("w_long", longTitle, 2.5),
  work("w_shadow", "Shadow Captain", -1),
  work("w_zero", "Visions of Heresy", 0),
  work("w_none", "Warhawk", null, {
    authors: [],
    type: null,
    first_published: null,
  }),
];
const listing = {
  snapshot,
  selected_series: {
    ...series,
    credit: { names: ["Dan Abnett"], others: 2 },
  },
  selected_author: null,
  position_counts: { numbered: 151, zero: 182, unpositioned: 475 },
  works,
  total: 808,
  page: 1,
  page_size: 24,
};
const overlay = {
  status: "ready",
  catalogue_version: snapshot.version,
  checked_at: "2026-10-26T05:29:28+00:00",
  snapshot: "b".repeat(24),
  coverage: "partial",
  truncated: false,
  works: [
    {
      id: "w_rising",
      title: "Horus Rising",
      state: "direct",
      current: false,
      copies: [{ calibre_id: 41, title: "Horus Rising", last_known: true }],
      contained_in: [],
      candidates: [],
    },
    {
      id: "w_gods",
      title: "False Gods",
      state: "contained",
      current: true,
      copies: [],
      contained_in: [
        { calibre_id: 42, title: "Heresy omnibus", last_known: false },
      ],
      candidates: [],
    },
  ],
};
let paths: string[] = [];
let navigations: Partial<CatalogueRoute>[] = [];
let intercept: (path: string) => Response | undefined;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
function mount(initial: Partial<CatalogueRoute> = {}, connected = true) {
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
        return json({ status: "ready", ...snapshot, total: 5824 });
      if (input.startsWith("/api/catalogue/works/"))
        return json({
          ...works[0],
          snapshot,
          synopsis: null,
          ownership: "unconfirmed",
          editions: [],
          support: [],
        });
      if (input.startsWith("/api/catalogue/works?")) return json(listing);
      if (input.startsWith("/api/library/series?")) return json(overlay);
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
      cv: snapshot.version,
      ch: snapshot.sha256,
      cs: series.id,
      cb: "works",
      ca: "",
      ...initial,
    });
    return (
      <Catalogue
        route={route}
        libraryConnected={connected}
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
const entries = () =>
  within(
    screen.getByRole("list", { name: "Works in recorded series order" }),
  ).getAllByRole("button");
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  intercept = () => undefined;
});

it("heads the series with its canonical credit, the recorded order and real shelf counts", async () => {
  const { container } = mount();
  await screen.findByRole("heading", { level: 1, name: "The Horus Heresy" });
  const context = container.querySelector(".series-context")!;
  expect(context.textContent).toContain("Dan Abnett and 2 others");
  expect(context.textContent).toContain("808 works in the catalogue");
  await waitFor(() =>
    expect(context.textContent).toContain(
      "2 of 808 shelved: 1 with a matched copy and 1 with a saved match",
    ),
  );
  expect(screen.getByText("808 works in recorded order")).toBeTruthy();
  expect(screen.getByText("Recorded at 0 · 182")).toBeTruthy();
  expect(screen.getByText("No position · 475")).toBeTruthy();
  expect(screen.queryByText(/matching works/)).toBeNull();
  expect(screen.queryByText(/editions?$/)).toBeNull();
});

it("omits the credit when an older listing has none and never infers it from authors", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({ ...listing, selected_series: series })
      : undefined;
  const { container } = mount({}, false);
  await screen.findByRole("heading", { level: 1, name: "The Horus Heresy" });
  const context = container.querySelector(".series-context")!;
  expect(context.querySelector(".series-credit")).toBeNull();
  expect(context.textContent).not.toContain("Dan Abnett");
  expect(context.textContent).toContain("808 works in the catalogue");
  expect(context.textContent).not.toContain("shelved");
});

it("does not invent a collective author credit when recorded author coverage is absent or insufficient", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?")
      ? json({
          ...listing,
          selected_series: { ...series, credit: { names: [], others: 0 } },
        })
      : undefined;
  const { container } = mount({}, false);
  await screen.findByRole("heading", { level: 1, name: "The Horus Heresy" });
  expect(container.querySelector(".series-credit")).toBeNull();
  expect(container.querySelector(".series-context")!.textContent).not.toContain(
    "Various authors",
  );
});

it("keeps the literal recorded order, every position and whole titles in folio or cover entries", async () => {
  mount({}, false);
  await screen.findByText("Horus Rising", {
    selector: ".shelf-caption strong",
  });
  const buttons = entries();
  expect(buttons.map((b) => b.id)).toEqual(
    works.map((w) => `catalogue-${w.id}`),
  );
  const positions = buttons.map(
    (b) => b.querySelector(".series-position")!.textContent,
  );
  expect(positions).toEqual([
    "Series position 1",
    "Series position 2",
    "Series position 2.5",
    "Series position -1",
    "Series position 0",
    "No position",
  ]);
  expect(buttons[0].querySelector("img.book-cover")!.getAttribute("src")).toBe(
    "/api/catalogue/covers/abc.jpg",
  );
  expect(buttons[0].querySelector(".position-badge")!.textContent).toBe("1");
  expect(buttons[1].querySelector("img.book-cover")).toBeNull();
  expect(buttons[1].querySelector(".shelf-art")).toBeNull();
  expect(buttons[1].querySelector(".book-folio")).toBeNull();
  expect(buttons[2].querySelector(".shelf-caption strong")!.textContent).toBe(
    longTitle,
  );
  expect(buttons[1].textContent).toContain("Graham McNeill");
  expect(buttons[1].textContent).toContain("Short story");
  expect(buttons[5].textContent).toContain("Author not recorded");
  expect(buttons[5].textContent).not.toContain("First published");
  expect(buttons[0]).toHaveProperty(
    "textContent",
    expect.stringContaining("2006"),
  );
  expect(buttons[0].getAttribute("aria-pressed")).toBe("false");
  const groups = [...document.querySelectorAll(".series-group")].map(
    (h) => h.textContent,
  );
  expect(groups).toEqual(["Recorded at 0 · 182", "No position · 475"]);
});

it("shows saved-library status only where the overlay has evidence", async () => {
  mount();
  const matched = await screen.findByRole("button", {
    name: /Horus Rising.*Direct match · saved match/,
  });
  expect(matched.querySelector(".library-state.direct")).toBeTruthy();
  const contained = screen.getByRole("button", { name: /False Gods/ });
  expect(contained.querySelector(".library-state.contained")!.textContent).toBe(
    "In a collection",
  );
  const unmatched = screen.getByRole("button", { name: /Shadow Captain/ });
  expect(unmatched.querySelector(".library-state")).toBeNull();
  expect(unmatched.textContent).not.toMatch(/No matched copy|Unconfirmed/);
  expect(screen.getByText(/Partial check/)).toBeTruthy();
  fireEvent.click(unmatched);
  expect(navigations.at(-1)).toEqual({ cw: "w_shadow" });
  expect(screen.getByRole("button", { name: "Back to series" })).toBeTruthy();
});

it("drops status lines and the shelved summary when the check belongs to another version", async () => {
  intercept = (path) =>
    path.startsWith("/api/library/series?")
      ? json({
          status: "version_mismatch",
          catalogue_version: "2026.10.01.1",
          works: overlay.works,
        })
      : undefined;
  const { container } = mount();
  await screen.findByText(/uses a different catalogue version/);
  expect(container.querySelector(".library-state")).toBeNull();
  expect(container.querySelector(".series-context")!.textContent).not.toContain(
    "shelved",
  );
});

it("remembers the List presentation and keeps the same order", async () => {
  mount({}, false);
  await screen.findByText("Horus Rising", {
    selector: ".shelf-caption strong",
  });
  const region = screen.getByRole("region", { name: "Catalogue" });
  expect(region.className).toContain("browse-shelves");
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect(region.className).toContain("browse-list");
  expect(localStorage.getItem("librarium.browse-view")).toBe("list");
  expect(entries().map((b) => b.id)).toEqual(
    works.map((w) => `catalogue-${w.id}`),
  );
});

it("pages at 24 works and summarises a search within the series", async () => {
  intercept = (path) =>
    path.startsWith("/api/catalogue/works?") && path.includes("q=Rising")
      ? json({ ...listing, works: [works[0]], total: 1 })
      : path.startsWith("/api/catalogue/works?")
        ? json({
            ...listing,
            page: Number(
              new URL(path, location.origin).searchParams.get("page"),
            ),
          })
        : undefined;
  mount({ cp: 2 });
  await screen.findByText("Page 2 of 34");
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  expect(navigations.at(-1)).toEqual({ cp: 1 });
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "Rising" },
  });
  fireEvent.submit(screen.getByRole("search"));
  await screen.findByText("1 matching work in recorded order");
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
});

it("passes axe in the series room with evidence", async () => {
  const { container } = mount();
  await screen.findByRole("button", { name: /Direct match · saved match/ });
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

it("words the shelved summary without claiming more than the check supports", () => {
  const n = (direct: number, saved: number, total: number, extra = {}) =>
    seriesShelfSummary({ current: direct, saved, total, ...extra });
  expect(n(0, 0, 808)).toBe("no saved matches in this check");
  expect(n(0, 204, 808)).toBe("204 of 808 shelved with a saved match");
  expect(n(3, 0, 808)).toBe("3 of 808 shelved with a matched copy");
  expect(n(3, 2, 808)).toBe(
    "5 of 808 shelved: 3 with a matched copy and 2 with a saved match",
  );
  expect(n(0, 15, 15)).toBe("15 shelved, every one with a saved match");
  expect(n(1, 0, 1)).toBe("1 shelved, with a matched copy");
  expect(n(3, 2, 808, { truncated: true })).toBe(
    "at least 5 of 808 shelved · partial list",
  );
});
