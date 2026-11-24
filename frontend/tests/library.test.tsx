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
import {
  QueryClient,
  QueryClientProvider,
  onlineManager,
} from "@tanstack/react-query";
import axe from "axe-core";
import { Library, type LibraryRoute } from "../src/Library";

const version = "2026.10.24.2",
  token = "a".repeat(24),
  sha256 = "b".repeat(64);
const sample = {
  status: "ready",
  source: "library_finish",
  catalogue_version: version,
  checked_at: "2026-10-25T02:21:21+00:00",
  coverage: "partial",
  loading: false,
  snapshot: token,
  page: 1,
  page_size: 24,
  total: 30,
  finish_origin: "http://lf.invalid",
  works: [
    {
      id: "w_fixture",
      title: "Fixture: The Glass Meridian",
      kind: "novel",
      authors: ["Fixture Author"],
      series: [{ id: "7", name: "Fixture Archive", position: 2 }],
      state: "direct",
      current: false,
      copies: [
        { calibre_id: 41, title: "Fixture Calibre title", last_known: true },
      ],
      contained_in: [],
      candidates: [],
    },
  ],
};
let intercept: (url: string) => Response | Promise<Response> | undefined;
let calls: string[];
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const entry = () =>
  screen.findByRole("button", { name: /Fixture: The Glass Meridian/ });
function disclose(label: string) {
  fireEvent.click(
    screen.getByText(label, {
      selector: ".reading-disclosures summary span",
      exact: true,
    }),
  );
}
function mount(
  initial: Partial<LibraryRoute> = {},
  openCatalogue?: React.ComponentProps<typeof Library>["openCatalogue"],
  sharedClient?: QueryClient,
) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      return (
        intercept?.(url) ??
        (url === "/api/catalogue"
          ? json({ status: "ready", version, sha256, fixture: false })
          : url.startsWith("/api/catalogue/works/")
            ? json({
                id: url.split("/").pop()!.split("?")[0],
                snapshot: { version, sha256, fixture: false },
                synopsis: "A fictional synopsis.",
                editions: [],
                support: [],
              })
            : json(sample))
      );
    }),
  );
  const client =
    sharedClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
  function Harness() {
    const [route, setRoute] = useState<LibraryRoute>({
      lq: "",
      lp: 1,
      lo: "owned",
      lx: "title",
      lt: token,
      ...initial,
    });
    return (
      <Library
        route={route}
        navigate={(next) => setRoute((old) => ({ ...old, ...next }))}
        openCatalogue={openCatalogue}
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
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  intercept = () => undefined;
  localStorage.clear();
  onlineManager.setOnline(true);
  history.replaceState(null, "", "/");
});

it("uses in-app evidence navigation and preserves modified native links with filters and pin", async () => {
  const openCatalogue = vi.fn();
  intercept = (url) =>
    url.startsWith("/api/library?") ? json({ ...sample, page: 2 }) : undefined;
  mount(
    { lq: "Archive", lp: 2, lo: "contained", lx: "author", lt: token },
    openCatalogue,
  );
  fireEvent.click(await entry());
  disclose("Record details");
  const link = screen.getByRole("link", { name: "Catalogue evidence" });
  fireEvent.click(link);
  expect(openCatalogue).toHaveBeenCalledWith(
    expect.objectContaining({ cw: "w_fixture", cv: version }),
    expect.objectContaining({
      route: expect.objectContaining({ lq: "Archive", lp: 2, lt: token }),
      work: "w_fixture",
      open: ["w_fixture"],
    }),
  );
  openCatalogue.mockClear();
  let nativeLink = false;
  document.addEventListener(
    "click",
    (event) => {
      nativeLink = !event.defaultPrevented;
      event.preventDefault();
    },
    { once: true },
  );
  fireEvent.click(link, { ctrlKey: true });
  expect(openCatalogue).not.toHaveBeenCalled();
  expect(nativeLink).toBe(true);
  const series = screen.getByRole("link", {
    name: "Browse Fixture Archive in catalogue",
  });
  const params = Object.fromEntries(
    new URLSearchParams(series.getAttribute("href")!.split("?")[1]),
  );
  expect(params).toMatchObject({
    lq: "Archive",
    lp: "2",
    lo: "contained",
    lx: "author",
    lt: token,
    cs: "7",
    cv: version,
    ch: sha256,
  });
});

it("bounds changed-check recovery and retries without resetting the current search or page", async () => {
  let changed = true;
  intercept = (url) =>
    url.startsWith("/api/library?") && changed
      ? json(
          { error: "The library check changed", code: "library_check_changed" },
          409,
        )
      : undefined;
  mount({ lq: "Archive", lp: 2, lt: token });
  const alert = await screen.findByRole("alert");
  expect(
    within(alert).getByRole("button", { name: "Reload library" }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Select Fixture/ })).toBeNull();
  changed = false;
  fireEvent.click(
    within(alert).getByRole("button", { name: "Reload library" }),
  );
  await entry();
  expect(
    calls.some(
      (url) =>
        url.includes("q=Archive") &&
        url.includes("page=2") &&
        new URL(url, "http://local").searchParams.get("snapshot") === "",
    ),
  ).toBe(true);
});

it.each(["title", "author"])(
  "keeps the last view, focus and historical evidence while %s order recovers a new check",
  async (lx) => {
    let conflict = false;
    let finish!: (response: Response) => void;
    const latest = "c".repeat(24);
    const current = {
      ...sample,
      page: 2,
      total: 70,
      coverage: "complete",
      works: [
        {
          ...sample.works[0],
          current: true,
          copies: [{ ...sample.works[0].copies[0], last_known: false }],
        },
      ],
    };
    intercept = (url) => {
      if (!url.startsWith("/api/library?")) return undefined;
      const params = new URL(url, "http://local").searchParams;
      if (!conflict) return json(current);
      if (params.get("snapshot") === token)
        return json(
          { error: "Check changed", code: "library_check_changed" },
          409,
        );
      if (!params.get("snapshot"))
        return new Promise((resolve) => {
          finish = resolve;
        });
      return json({ ...current, snapshot: latest });
    };
    const view = mount({ lq: "Archive", lp: 2, lx, lw: "w_fixture" });
    const button = await entry();
    button.focus();
    conflict = true;
    if (lx === "title") {
      act(() => onlineManager.setOnline(false));
      act(() => onlineManager.setOnline(true));
    } else
      act(() => {
        void view.client.refetchQueries({ queryKey: ["library"] });
      });
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    expect(
      screen.getByRole("heading", {
        name: "Fixture: The Glass Meridian",
        level: 2,
      }),
    ).toBeTruthy();
    expect(screen.getByText("Direct match · saved match")).toBeTruthy();
    expect(document.activeElement).toBe(button);
    expect(
      calls.some(
        (url) =>
          url.includes("page=2") &&
          url.includes("q=Archive") &&
          url.includes("snapshot="),
      ),
    ).toBe(true);
    await act(async () => finish(json({ ...current, snapshot: latest })));
    await waitFor(() =>
      expect(screen.queryByText("Direct match · saved match")).toBeNull(),
    );
    expect(screen.getByRole("searchbox").getAttribute("value")).toBe("Archive");
    expect(document.activeElement).toBe(button);
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() =>
      expect(
        calls.some(
          (url) => url.includes("page=1") && url.includes(`snapshot=${latest}`),
        ),
      ).toBe(true),
    );
  },
);

it("lets a new search win while an older recovery response is delayed", async () => {
  let conflict = false;
  let finish!: (response: Response) => void;
  const latest = "d".repeat(24);
  intercept = (url) => {
    if (!url.startsWith("/api/library?")) return undefined;
    const params = new URL(url, "http://local").searchParams;
    if (!conflict) return json(sample);
    if (params.get("snapshot"))
      return json(
        { error: "Check changed", code: "library_check_changed" },
        409,
      );
    if (params.get("q") === "new search")
      return json({
        ...sample,
        snapshot: latest,
        works: [{ ...sample.works[0], title: "Fixture: New intent" }],
      });
    return new Promise((resolve) => {
      finish = resolve;
    });
  };
  const view = mount();
  await entry();
  conflict = true;
  act(() => {
    void view.client.refetchQueries({ queryKey: ["library"] });
  });
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "new search" },
  });
  fireEvent.submit(screen.getByRole("search", { name: "Library search" }));
  await screen.findByRole("button", { name: /Fixture: New intent/ });
  await act(async () =>
    finish(
      json({
        ...sample,
        snapshot: "c".repeat(24),
        works: [{ ...sample.works[0], title: "Fixture: Obsolete response" }],
      }),
    ),
  );
  expect(screen.queryByText("Fixture: Obsolete response")).toBeNull();
  expect(screen.getByRole("searchbox").getAttribute("value")).toBe(
    "new search",
  );
});

it("revalidates an otherwise fresh cached route on a new mount", async () => {
  const shared = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = mount({}, undefined, shared);
  await entry();
  view.unmount();
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? new URL(url, "http://local").searchParams.get("snapshot")
        ? json({ error: "Check changed", code: "library_check_changed" }, 409)
        : json({ ...sample, snapshot: "c".repeat(24) })
      : undefined;
  mount({}, undefined, shared);
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("snapshot=") &&
          new URL(url, "http://local").searchParams.get("snapshot") === "",
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(screen.queryByText(/Reading the current check/)).toBeNull(),
  );
});

it("reconciles a same-pin Catalogue return after a cold check recovery", async () => {
  const latest = "c".repeat(24);
  const originRoute = {
    lq: "Archive",
    lp: 2,
    lo: "owned",
    lx: "title",
    lt: token,
    lw: "w_fixture",
  };
  history.replaceState(
    {
      libraryReturn: {
        route: originRoute,
        work: "w_fixture",
        scroll: 300,
        open: [],
        focusId: "library-none-w_fixture",
        catalogue: { version, sha256 },
      },
    },
    "",
  );
  const scroll = vi.spyOn(window, "scrollTo");
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? new URL(url, "http://local").searchParams.get("snapshot")
        ? json({ error: "Check changed", code: "library_check_changed" }, 409)
        : json({ ...sample, snapshot: latest, page: 2 })
      : undefined;
  mount(originRoute);
  await entry();
  await waitFor(() =>
    expect(history.state.libraryReturn.route.lt).toBe(latest),
  );
  await waitFor(() => expect(scroll).toHaveBeenCalledWith(0, 300));
  expect(history.state.libraryReturn.work).toBe("w_fixture");
});

it("refuses an old Catalogue return selection and scroll when the digest changed but the LF token did not", async () => {
  const other = {
    ...sample.works[0],
    id: "w_other",
    title: "Fixture: Other snapshot identity",
  };
  history.replaceState(
    {
      libraryReturn: {
        route: {
          lq: "",
          lp: 1,
          lo: "owned",
          lx: "title",
          lt: token,
          lw: "w_other",
        },
        work: "w_other",
        scroll: 300,
        open: [],
        catalogue: { version, sha256: "c".repeat(64) },
      },
    },
    "",
  );
  const scroll = vi.spyOn(window, "scrollTo");
  scroll.mockClear();
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ ...sample, works: [...sample.works, other] })
      : undefined;
  mount({ lw: "w_other" });
  await entry();
  await act(async () => {
    await new Promise(requestAnimationFrame);
  });
  expect(
    screen.queryByRole("heading", { name: other.title, level: 2 }),
  ).toBeNull();
  expect(scroll).not.toHaveBeenCalledWith(0, 300);
  fireEvent.click(
    screen.getByRole("button", { name: /Fixture: Other snapshot identity/ }),
  );
  await screen.findByRole("heading", { name: other.title, level: 2 });
});

it("keeps the latest page intent when a superseded recovery finishes late", async () => {
  let conflict = false;
  let finish!: (response: Response) => void;
  const latest = "d".repeat(24);
  intercept = (url) => {
    if (!url.startsWith("/api/library?")) return undefined;
    const params = new URL(url, "http://local").searchParams;
    const page = Number(params.get("page"));
    if (!conflict || params.get("snapshot") === latest)
      return json({
        ...sample,
        page,
        total: 70,
        snapshot: conflict ? latest : token,
      });
    if (params.get("snapshot"))
      return json(
        { error: "Check changed", code: "library_check_changed" },
        409,
      );
    if (page === 3)
      return json({ ...sample, page: 3, total: 70, snapshot: latest });
    return new Promise((resolve) => {
      finish = resolve;
    });
  };
  const view = mount({ lp: 2 });
  await entry();
  conflict = true;
  act(() => {
    void view.client.refetchQueries({ queryKey: ["library"] });
  });
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("Page 3 of 3");
  await act(async () =>
    finish(json({ ...sample, page: 2, total: 70, snapshot: "c".repeat(24) })),
  );
  expect(screen.getByText("Page 3 of 3")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
  await waitFor(() =>
    expect(
      calls.some(
        (url) => url.includes("page=2") && url.includes(`snapshot=${latest}`),
      ),
    ).toBe(true),
  );
});

it("never restores current ownership from an invalid cached check after recovery is cancelled by unmount", async () => {
  let conflict = false;
  let freshStarted = false;
  const shared = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  intercept = (url) => {
    if (!url.startsWith("/api/library?")) return undefined;
    if (!conflict)
      return json({
        ...sample,
        works: [{ ...sample.works[0], current: true }],
      });
    if (new URL(url, "http://local").searchParams.get("snapshot"))
      return json(
        { error: "Check changed", code: "library_check_changed" },
        409,
      );
    freshStarted = true;
    return new Promise(() => {});
  };
  const view = mount({}, undefined, shared);
  await entry();
  conflict = true;
  act(() => {
    void shared.refetchQueries({ queryKey: ["library"] });
  });
  await waitFor(() => expect(freshStarted).toBe(true));
  view.unmount();
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ error: "Still changing", code: "library_check_changed" }, 409)
      : undefined;
  mount({}, undefined, shared);
  await screen.findByRole("alert");
  await entry();
  expect(screen.getByText("Direct match · saved match")).toBeTruthy();
  expect(
    screen.getByText(/Current copies and absence are unconfirmed/),
  ).toBeTruthy();
});

it("binds a retained-book click and Catalogue return to its displayed page rather than the pending page", async () => {
  let conflict = false;
  let finish!: (response: Response) => void;
  const latest = "c".repeat(24);
  intercept = (url) => {
    if (!url.startsWith("/api/library?")) return undefined;
    const params = new URL(url, "http://local").searchParams;
    const page = Number(params.get("page"));
    if (!conflict) return json({ ...sample, page: 1, total: 70 });
    if (params.get("snapshot") === token)
      return json(
        { error: "Check changed", code: "library_check_changed" },
        409,
      );
    if (page === 1)
      return json({ ...sample, page: 1, total: 70, snapshot: latest });
    return new Promise((resolve) => {
      finish = resolve;
    });
  };
  const open = vi.fn();
  mount({}, open);
  await entry();
  conflict = true;
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  fireEvent.click(await entry());
  await screen.findByText("Page 1 of 3");
  disclose("Record details");
  fireEvent.click(screen.getByRole("link", { name: "Catalogue evidence" }));
  expect(open).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({
      route: expect.objectContaining({ lp: 1 }),
      work: "w_fixture",
    }),
  );
  await act(async () =>
    finish(
      json({
        ...sample,
        page: 2,
        total: 70,
        snapshot: "d".repeat(24),
        works: [
          { ...sample.works[0], id: "w_late", title: "Fixture: Obsolete page" },
        ],
      }),
    ),
  );
  expect(screen.queryByText("Fixture: Obsolete page")).toBeNull();
});

it("keeps persistent recovery beside a focused phone book and exposes a keyboard retry", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  let conflict = false;
  intercept = (url) =>
    url.startsWith("/api/library?") && conflict
      ? json({ error: "Check changed", code: "library_check_changed" }, 409)
      : undefined;
  const view = mount({ lw: "w_fixture", ld: "1" });
  await entry();
  conflict = true;
  act(() => {
    void view.client.refetchQueries({ queryKey: ["library"] });
  });
  const alert = await screen.findByRole("alert");
  expect(alert.closest('[aria-label="Selected book"]')).toBeTruthy();
  const retry = within(alert).getByRole("button", { name: "Reload library" });
  retry.focus();
  expect(document.activeElement).toBe(retry);
  conflict = false;
  fireEvent.click(retry);
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("heading", {
        name: "Fixture: The Glass Meridian",
        level: 2,
      }),
    ),
  );
  expect(
    screen.getByRole("heading", {
      name: "Fixture: The Glass Meridian",
      level: 2,
    }),
  ).toBeTruthy();
  expect(
    (
      await axe.run(view.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it("returns retry focus to results when the refreshed phone check removes the selected book", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  let phase: "ready" | "conflict" | "empty" = "ready";
  intercept = (url) => {
    if (!url.startsWith("/api/library?")) return;
    if (phase === "conflict")
      return json(
        { error: "Check changed", code: "library_check_changed" },
        409,
      );
    if (phase === "empty")
      return json({ ...sample, snapshot: "c".repeat(24), total: 0, works: [] });
  };
  const view = mount({ lw: "w_fixture", ld: "1" });
  await entry();
  phase = "conflict";
  act(() => {
    void view.client.refetchQueries({ queryKey: ["library"] });
  });
  const retry = within(await screen.findByRole("alert")).getByRole("button", {
    name: "Reload library",
  });
  retry.focus();
  phase = "empty";
  fireEvent.click(retry);
  await screen.findByText("0 matching titles");
  await waitFor(() =>
    expect(document.activeElement).toBe(
      view.container.querySelector(".list-summary"),
    ),
  );
  expect(
    screen.queryByRole("heading", {
      name: "Fixture: The Glass Meridian",
      level: 2,
    }),
  ).toBeNull();
});

it.each(["version_mismatch", "not_configured", "truncated"])(
  "stops a fresh recovery truthfully when it returns %s",
  async (terminal) => {
    let conflict = false;
    intercept = (url) => {
      if (!url.startsWith("/api/library?")) return undefined;
      if (!conflict) return json(sample);
      if (new URL(url, "http://local").searchParams.get("snapshot"))
        return json(
          { error: "Check changed", code: "library_check_changed" },
          409,
        );
      return json(
        terminal === "not_configured"
          ? { status: terminal }
          : {
              ...sample,
              snapshot: "c".repeat(24),
              status: terminal === "truncated" ? "ready" : terminal,
              truncated: terminal === "truncated",
            },
      );
    };
    const view = mount();
    await entry();
    conflict = true;
    act(() => {
      void view.client.refetchQueries({ queryKey: ["library"] });
    });
    const alert = await screen.findByRole("alert");
    expect(screen.queryByText(/Reading the current check/)).toBeNull();
    expect(screen.getByText("Direct match · saved match")).toBeTruthy();
    expect(
      within(alert).getByRole("button", {
        name:
          terminal === "truncated" ? "Browse in Title order" : "Reload library",
      }),
    ).toBeTruthy();
  },
);

it("recovers a cold expired route automatically and never retries an unrelated catalogue conflict", async () => {
  const latest = "c".repeat(24);
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? new URL(url, "http://local").searchParams.get("snapshot")
        ? json(
            { error: "Expired LF check", code: "library_check_changed" },
            409,
          )
        : json({ ...sample, snapshot: latest })
      : undefined;
  const view = mount({ lq: "Archive", lp: 2 });
  await entry();
  expect(calls.filter((url) => url.startsWith("/api/library?")).length).toBe(2);
  view.unmount();
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ error: "Pinned catalogue changed" }, 409)
      : undefined;
  mount();
  await screen.findByText("Pinned catalogue changed");
  expect(calls.filter((url) => url.startsWith("/api/library?")).length).toBe(1);
});

it("shows dated saved evidence, a working copy URL and mounted semantic accessibility", async () => {
  const view = mount();
  await entry();
  expect(
    view.container.querySelector(".library-context summary")?.textContent,
  ).toContain("Partial check");
  expect(screen.getByText("Direct match · saved match")).toBeTruthy();
  expect(
    screen.getByText("Not yet re-confirmed by a complete check."),
  ).toBeTruthy();
  disclose("Library evidence");
  expect(screen.getByText(/Calibre #41/)).toBeTruthy();
  expect(screen.getByText("Fixture Calibre title")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Open in Library Finish ↗" })
      .getAttribute("href"),
  ).toBe("http://lf.invalid/book?calibre=41");
  expect(
    (
      await axe.run(view.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it("joins artwork only under the matching pin and preserves book identity and evidence after cover failure", async () => {
  const cover = {
    url: "/api/catalogue/covers/w_fixture/" + "a".repeat(64),
    width: 400,
    height: 600,
    sha256: "a".repeat(64),
    media_type: "image/jpeg",
  };
  intercept = (url) =>
    url.startsWith("/api/catalogue/covers?")
      ? json({ snapshot: { version, sha256 }, covers: { w_fixture: cover } })
      : undefined;
  const view = mount();
  await waitFor(() =>
    expect(
      view.container
        .querySelector(".shelf-entry .book-cover")
        ?.getAttribute("src"),
    ).toBe(cover.url),
  );
  expect(
    calls.some(
      (url) =>
        url.includes("work=w_fixture") && url.includes(`sha256=${sha256}`),
    ),
  ).toBe(true);
  fireEvent.error(view.container.querySelector(".shelf-entry .book-cover")!);
  const failedEntry = await entry();
  expect(failedEntry.querySelector(".book-cover")).toBeNull();
  expect(failedEntry.querySelector(".book-folio")).toBeNull();
  expect(within(failedEntry).getAllByText(sample.works[0].title)).toHaveLength(
    1,
  );
  expect(screen.getByText("Direct match · saved match")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "List" }));
  expect((await entry()).getAttribute("aria-pressed")).toBe("true");
});

it("drops artwork with a mismatched response pin without disrupting records", async () => {
  intercept = (url) =>
    url.startsWith("/api/catalogue/covers?")
      ? json({
          snapshot: { version: "2026.10.25.1", sha256 },
          covers: { w_fixture: { url: "/api/catalogue/covers/w_fixture/bad" } },
        })
      : undefined;
  const view = mount();
  await entry();
  await waitFor(() =>
    expect(calls.some((url) => url.startsWith("/api/catalogue/covers?"))).toBe(
      true,
    ),
  );
  expect(view.container.querySelector(".book-cover")).toBeNull();
  expect(screen.getByText("Direct match · saved match")).toBeTruthy();
});

it("distinguishes unknown coverage and no check date from partial coverage", async () => {
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ ...sample, coverage: "unknown", checked_at: null })
      : undefined;
  const view = mount();
  await entry();
  expect(
    view.container.querySelector(".library-context summary")?.textContent,
  ).toContain("Coverage unknown");
  expect(screen.queryByText(/Partial check/)).toBeNull();
});

it("keeps phone Copies in a disclosure while Order and presentation remain reachable", async () => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
  mount({ lt: token });
  await entry();
  const options = screen.getByText("Filters and view").closest("details")!;
  expect(options.open).toBe(false);
  expect(screen.getByRole("combobox", { name: "Order" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "List" })).toBeTruthy();
  fireEvent.click(screen.getByText("Filters and view"));
  fireEvent.change(screen.getByLabelText("Copies"), {
    target: { value: "contained" },
  });
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("ownership=contained") &&
          url.includes(`snapshot=${token}`),
      ),
    ).toBe(true),
  );
});

it("keeps contained, pending and candidate confidence separate", async () => {
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({
          ...sample,
          total: 2,
          works: [
            {
              ...sample.works[0],
              id: "w_inside",
              title: "Inside fixture",
              state: "contained",
              copies: [],
              contained_in: sample.works[0].copies,
            },
            {
              ...sample.works[0],
              id: "w_pending",
              title: "Pending fixture",
              state: "pending",
              copies: [],
              candidates: [
                {
                  title: "Possible fixture",
                  stage: "inbox",
                  confidence: "possible",
                },
              ],
            },
          ],
        })
      : undefined;
  mount();
  await screen.findByRole("button", { name: /Inside\ fixture/ });
  expect(screen.getByText("In a collection · saved match")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Pending\ fixture/ }));
  await screen.findByRole("heading", { name: "Pending fixture", level: 2 });
  disclose("Library evidence");
  expect(screen.getByText(/Possible fixture.*possible match/i)).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /inspect|import|download/i }),
  ).toBeNull();
});

it("pins pagination and resets the page for search and Copies", async () => {
  mount();
  await entry();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() =>
    expect(
      calls.some(
        (url) => url.includes("page=2") && url.includes(`snapshot=${token}`),
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("Copies"), {
    target: { value: "pending" },
  });
  await waitFor(() =>
    expect(
      calls.some(
        (url) => url.includes("ownership=pending") && url.includes("page=1"),
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("Search your library"), {
    target: { value: "Glass" },
  });
  fireEvent.submit(screen.getByRole("search"));
  await waitFor(() =>
    expect(calls.some((url) => url.includes("q=Glass"))).toBe(true),
  );
});

it("does not link a match into a different catalogue", async () => {
  intercept = (url) =>
    url === "/api/catalogue"
      ? json({
          status: "ready",
          version: "2026.10.25.1",
          sha256: "c".repeat(64),
          fixture: false,
        })
      : undefined;
  mount();
  await entry();
  disclose("Record details");
  expect(screen.queryByRole("link", { name: "Catalogue evidence" })).toBeNull();
  expect(screen.getByText(/different catalogue version/)).toBeTruthy();
});

it("distinguishes loading, disconnected and empty-filter states with recovery", async () => {
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ ...sample, works: [], total: 0, loading: true })
      : undefined;
  const first = mount();
  await screen.findByText(/Library Finish is loading/);
  expect(screen.queryByText("No matches for these filters.")).toBeNull();
  first.unmount();
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ status: "not_configured" })
      : undefined;
  const second = mount();
  await screen.findByText("Library not connected");
  second.unmount();
  intercept = (url) =>
    url.startsWith("/api/library?")
      ? json({ ...sample, works: [], total: 0 })
      : undefined;
  mount({ lq: "absent" });
  await screen.findByText("No matches for these filters.");
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(calls.at(-1)).not.toContain("absent"));
});
