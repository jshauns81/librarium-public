// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import axe from "axe-core";
import { moodFromPixels } from "../src/reading";
import {
  legacyReaderHref,
  readerAddress,
  readerHref,
} from "../src/reader/address";

// The engine needs a real browser (frames, layout, CSS columns); the headless
// Chrome check covers it. Here a stand-in engine records what the room asks.
const engine = vi.hoisted(() => ({
  views: [] as unknown[],
  book: null as unknown,
}));

vi.mock("../src/reader/book", async (original) => ({
  ...(await original<typeof import("../src/reader/book")>()),
  openBook: vi.fn(async () => engine.book),
}));

vi.mock("@vendor/foliate/view.js", () => {
  class FakeRenderer extends HTMLElement {
    goTo = vi.fn(async (target: { index: number; anchor?: number }) =>
      (this.parentView as FakeView).move(target.index, target.anchor ?? 0),
    );
    setStyles = vi.fn();
    parentView: unknown = null;
    atStart = false;
    atEnd = false;
  }
  class FakeView extends HTMLElement {
    renderer = document.createElement("fake-renderer") as FakeRenderer;
    lastLocation: unknown = null;
    index = 0;
    open = vi.fn(async () => {
      this.renderer.parentView = this;
      this.append(this.renderer);
      (engine.views as unknown[]).push(this);
    });
    init = vi.fn(async ({ lastLocation }: { lastLocation?: string }) =>
      this.move(lastLocation ? 3 : 1, 0.25),
    );
    goTo = vi.fn(async () => this.move(4, 0));
    // Fake CFIs name their section as /6/<2 × (index + 1)>.
    resolveCFI = vi.fn((cfi: string) => ({
      index: Number(/^epubcfi\(\/6\/(\d+)/.exec(cfi)?.[1] ?? NaN) / 2 - 1,
      anchor: null,
    }));
    next = vi.fn(async () => this.move(this.index, 0.5, "page"));
    prev = vi.fn(async () => this.move(this.index, 0.1, "page"));
    goRight = vi.fn(async () => this.next());
    goLeft = vi.fn(async () => this.prev());
    close = vi.fn();
    move(index: number, fraction: number, reason = "navigation") {
      this.index = index;
      const labels = ["Cover", "One", "Two", "Three", "Four"];
      this.lastLocation = {
        fraction: (index + fraction) / 5,
        section: { current: index, total: 5 },
        tocItem: { label: labels[index], href: `${index}.xhtml` },
        cfi: `epubcfi(/6/${(index + 1) * 2}!/4/2/1:${Math.round(fraction * 100)})`,
      };
      this.renderer.dispatchEvent(
        new CustomEvent("relocate", { detail: { index, fraction, reason } }),
      );
    }
  }
  customElements.define("fake-renderer", FakeRenderer);
  customElements.define("foliate-view", FakeView);
  return { View: FakeView };
});

import { ReaderApp } from "../src/reader/ReaderApp";

type FakeView = HTMLElement & {
  renderer: HTMLElement & {
    goTo: ReturnType<typeof vi.fn>;
    setStyles: ReturnType<typeof vi.fn>;
  };
  init: ReturnType<typeof vi.fn>;
  next: ReturnType<typeof vi.fn>;
  prev: ReturnType<typeof vi.fn>;
  goTo: ReturnType<typeof vi.fn>;
};

const detail = {
  book: {
    id: "7",
    uuid: "book-uuid",
    title: "False Gods",
    authors: ["Graham McNeill"],
    series: "The Horus Heresy",
    series_index: 2,
    publisher: null,
    published_at: null,
    languages: ["eng"],
    identifiers: [],
    formats: [],
    cover: null,
  },
};

let wide = true;
function serve(file: Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("/file?")
        ? file
        : new Response(JSON.stringify(detail), { status: 200 }),
    ),
  );
}

beforeEach(() => {
  localStorage.clear();
  engine.views.length = 0;
  engine.book = {
    metadata: { title: "False Gods" },
    sections: [{}, {}, {}, {}, {}],
    toc: [
      { label: "One", href: "1.xhtml" },
      {
        label: "Two",
        href: "2.xhtml",
        subitems: [{ label: "Three", href: "3.xhtml" }],
      },
      { label: "Four", href: "4.xhtml" },
    ],
    destroy: vi.fn(),
  };
  wide = true;
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("min-width") ? wide : false,
    addEventListener() {},
    removeEventListener() {},
  }));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", (run: () => void) => {
    run();
    return 0;
  });
  serve(new Response(new Uint8Array([1, 2, 3]), { status: 200 }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openReader() {
  render(<ReaderApp bookId="7" inventory={"a".repeat(64)} />);
  await waitFor(() => expect(engine.views.length).toBeGreaterThan(0));
  const view = engine.views.at(-1) as FakeView;
  await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  return view;
}

it("opens a place saved by the first reader and saves an exact one", async () => {
  localStorage.setItem(
    "librarium-reading:7",
    JSON.stringify({
      uuid: "book-uuid",
      section: 2,
      fraction: 0.5,
      percent: 30,
      chapter: "Two",
      at: "2026-11-01T00:00:00.000Z",
    }),
  );
  const view = await openReader();
  expect(view.renderer.goTo).toHaveBeenCalledWith({ index: 2, anchor: 0.5 });
  expect(view.init).not.toHaveBeenCalled();
  const saved = JSON.parse(localStorage.getItem("librarium-reading:7")!);
  expect(saved).toMatchObject({
    uuid: "book-uuid",
    section: 2,
    fraction: 0.5,
    percent: 50,
    chapter: "Two",
    cfi: "epubcfi(/6/6!/4/2/1:50)",
  });
  expect(screen.getByText("50%")).toBeTruthy();
  expect(
    screen.getByRole("link", { name: /False Gods/ }).getAttribute("href"),
  ).toBe("/?lw=7");
});

it("returns to an exact place by its CFI", async () => {
  localStorage.setItem(
    "librarium-reading:7",
    JSON.stringify({
      uuid: "book-uuid",
      section: 3,
      fraction: 0.2,
      percent: 60,
      chapter: "Three",
      at: "",
      cfi: "epubcfi(/6/8!/4/2/1:20)",
    }),
  );
  const view = await openReader();
  expect(view.init).toHaveBeenCalledWith({
    lastLocation: "epubcfi(/6/8!/4/2/1:20)",
  });
});

it("falls back to the saved section when the exact place no longer exists", async () => {
  localStorage.setItem(
    "librarium-reading:7",
    JSON.stringify({
      uuid: "book-uuid",
      section: 2,
      fraction: 0.4,
      percent: 50,
      chapter: "Two",
      at: "",
      cfi: "epubcfi(/6/40!/4/2/1:20)",
    }),
  );
  const view = await openReader();
  expect(view.init).not.toHaveBeenCalledWith({
    lastLocation: "epubcfi(/6/40!/4/2/1:20)",
  });
  expect(view.renderer.goTo).toHaveBeenCalledWith({ index: 2, anchor: 0.4 });
});

it("starts a new book at its text and announces page turns", async () => {
  const view = await openReader();
  expect(view.init).toHaveBeenCalledWith({ showTextStart: true });
  fireEvent.keyDown(window, { key: "ArrowRight" });
  await waitFor(() => expect(view.next).toHaveBeenCalledTimes(1));
  fireEvent.keyDown(window, { key: "PageDown" });
  fireEvent.keyDown(window, { key: " " });
  await waitFor(() => expect(view.next).toHaveBeenCalledTimes(3));
  fireEvent.keyDown(window, { key: "PageUp" });
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  await waitFor(() => expect(view.prev).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(document.querySelector(".reader-sr")?.textContent).toBe(
      "One. 22 percent through the book.",
    ),
  );
  // Space on a control activates the control, not the page.
  fireEvent.keyDown(screen.getByRole("button", { name: "Contents" }), {
    key: " ",
  });
  expect(view.next).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getAllByRole("button", { name: "Next page" })[0]);
  await waitFor(() => expect(view.next).toHaveBeenCalledTimes(4));
});

it("keeps Contents open beside the book on wide screens", async () => {
  const view = await openReader();
  fireEvent.click(screen.getByRole("button", { name: "Contents" }));
  const contents = screen.getByRole("navigation", { name: "Contents" });
  expect(contents.querySelectorAll("li")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Four" }));
  await waitFor(() => expect(view.goTo).toHaveBeenCalledWith("4.xhtml"));
  expect(screen.getByRole("navigation", { name: "Contents" })).toBeTruthy();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Four" }).getAttribute("aria-current"),
    ).toBe("true"),
  );
  expect(
    (await axe.run(document.body, { rules: { region: { enabled: false } } }))
      .violations,
  ).toEqual([]);
});

it("closes Contents after a choice on phones", async () => {
  wide = false;
  const view = await openReader();
  fireEvent.click(screen.getByRole("button", { name: "Contents" }));
  fireEvent.click(screen.getByRole("button", { name: "Four" }));
  await waitFor(() => expect(view.goTo).toHaveBeenCalledWith("4.xhtml"));
  await waitFor(() =>
    expect(screen.queryByRole("navigation", { name: "Contents" })).toBeNull(),
  );
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Contents" }),
  );
});

it("opens links out of the book only in a separate, unlinked tab", async () => {
  const view = await openReader();
  const open = vi.fn();
  vi.stubGlobal("open", open);
  const follow = (href: string) => {
    const event = new CustomEvent("external-link", {
      detail: { href },
      cancelable: true,
    });
    view.dispatchEvent(event);
    return event.defaultPrevented;
  };
  expect(follow("https://example.com/a")).toBe(true);
  expect(open).toHaveBeenCalledWith(
    "https://example.com/a",
    "_blank",
    "noopener,noreferrer",
  );
  expect(follow("javascript:alert(1)")).toBe(true);
  expect(open).toHaveBeenCalledTimes(1);
  await waitFor(() =>
    expect(document.querySelector(".reader-sr")?.textContent).toBe(
      "That link cannot be opened from the reader.",
    ),
  );
});

it("keeps text settings between visits and restyles the pages", async () => {
  const view = await openReader();
  fireEvent.click(
    screen.getByRole("button", { name: "Text and page settings" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Larger text" }));
  fireEvent.click(screen.getByLabelText("Scroll"));
  fireEvent.click(screen.getByLabelText("Night"));
  const prefs = JSON.parse(localStorage.getItem("librarium-reader-prefs")!);
  expect(prefs).toMatchObject({ size: 3, flow: "scrolled", tone: "night" });
  await waitFor(() =>
    expect(view.renderer.getAttribute("flow")).toBe("scrolled"),
  );
  const [, styles] = view.renderer.setStyles.mock.calls.at(-1)![0];
  expect(styles).toContain("font-size:23px!important");
  expect(document.querySelector(".reader")?.getAttribute("data-tone")).toBe(
    "night",
  );
  fireEvent.keyDown(window, { key: "Escape" });
  expect(document.querySelector("#reader-settings")).toBeNull();
});

it("explains a changed library instead of showing an empty page", async () => {
  serve(new Response(JSON.stringify({}), { status: 409 }));
  render(<ReaderApp bookId="7" inventory={"a".repeat(64)} />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "The library changed since this page opened.",
  );
  expect(
    screen.getByRole("link", { name: "Back to the book" }).getAttribute("href"),
  ).toBe("/?lw=7");
});

it("draws a cover mood from its strongest colour and ignores near-black", () => {
  const pixels = new Uint8ClampedArray([200, 40, 30, 255, 5, 5, 5, 255]);
  // Deep enough for pale room text at 5:1 and the dark rubric at 4.6:1.
  expect(moodFromPixels(pixels)).toBe("112 31 26");
  expect(moodFromPixels(new Uint8ClampedArray([60, 70, 90, 255]))).toBe(
    "45 59 88",
  );
  expect(moodFromPixels(new Uint8ClampedArray([0, 0, 0, 255]))).toBeNull();
});

describe("reader addresses", () => {
  it("reads the book and inventory from the reader route", () => {
    expect(readerAddress("/read/7", "?inventory=abc")).toEqual({
      bookId: "7",
      inventory: "abc",
    });
    expect(readerAddress("/read/a%20b/", "?inventory=abc")?.bookId).toBe("a b");
    expect(readerAddress("/read/7", "")).toBeNull();
    expect(readerAddress("/read/7/extra", "?inventory=abc")).toBeNull();
    expect(readerAddress("/read/%E0%A4%A", "?inventory=abc")).toBeNull();
    expect(readerHref("7", "abc")).toBe("/read/7?inventory=abc");
  });

  it("sends links from the first reader to the reader page", () => {
    expect(legacyReaderHref("?read=7&inventory=abc")).toBe(
      "/read/7?inventory=abc",
    );
    expect(legacyReaderHref("?lw=7")).toBeNull();
  });
});
