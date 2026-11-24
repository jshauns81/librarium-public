// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Home,
  chapterNumber,
  editionName,
  greeting,
  lastOpenPlace,
} from "../src/Home";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const inventory = {
  token: "a".repeat(64),
  observed_at: "2026-11-03T12:00:00Z",
};
const book = {
  id: "7",
  uuid: "u-7",
  title: "Necropolis",
  authors: ["Dan Abnett"],
  series: "Gaunt's Ghosts",
  series_index: 3,
  added_at: "2026-11-02 10:00:00+00:00",
  cover: null,
  formats: [{ format: "EPUB", available: true, name: "Necropolis" }],
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.startsWith("/api/direct-library?")
        ? json({ inventory, total: 1882, books: [book] })
        : url.startsWith("/api/direct-library/books/7")
          ? json({ inventory, book })
          : url.startsWith("/api/direct-library/series")
            ? json({ books: [book] })
            : url === "/api/catalogue"
              ? json({ status: "ready", version: "2026.10.24.2", total: 5824 })
              : url.startsWith("/api/jobs/history")
                ? json({ jobs: [] })
                : url === "/api/jobs"
                  ? json({ jobs: [] })
                  : json({ error: "Unexpected" }, 404),
    ),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(now = new Date(2026, 10, 3, 20, 0)) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Home openBook={vi.fn()} openLibrary={vi.fn()} now={now} />
    </QueryClientProvider>,
  );
}

test("the greeting comes from the clock alone", () => {
  expect(greeting(new Date(2026, 10, 3, 20, 0)).opening).toMatch(/ evening\.$/);
  expect(greeting(new Date(2026, 10, 3, 23, 0)).opening).toMatch(/^Late on /);
  expect(greeting(new Date(2026, 10, 3, 9, 0)).margin).toBe("This morning");
});

test("the ribbon numeral comes only from a chapter's own number", () => {
  expect(chapterNumber("One")).toBe(1);
  expect(chapterNumber("Chapter 7")).toBe(7);
  expect(chapterNumber("seventeen")).toBe(17);
  expect(chapterNumber("Leaving Deliverance")).toBeNull();
  expect(chapterNumber(undefined)).toBeNull();
});

test("the open book is the latest unfinished place", () => {
  localStorage.setItem(
    "librarium-reading:3",
    JSON.stringify({ percent: 40, at: "2026-11-01T10:00:00Z" }),
  );
  localStorage.setItem(
    "librarium-reading:7",
    JSON.stringify({ percent: 12, at: "2026-11-02T10:00:00Z" }),
  );
  localStorage.setItem(
    "librarium-reading:9",
    JSON.stringify({ percent: 100, at: "2026-11-03T10:00:00Z" }),
  );
  expect(lastOpenPlace()?.id).toBe("7");
});

test("the room shows the open book, its place and a resume link", async () => {
  localStorage.setItem(
    "librarium-reading:7",
    JSON.stringify({
      uuid: "u-7",
      percent: 38,
      chapter: "Seven",
      at: "2026-11-02T10:00:00Z",
    }),
  );
  mount();
  expect(
    await screen.findByRole("heading", { name: "Necropolis" }),
  ).toBeTruthy();
  expect(
    screen.getByText(/is open where you left it, at chapter seven\./),
  ).toBeTruthy();
  const resume = screen.getByRole("link", { name: "Resume reading" });
  expect(resume.getAttribute("href")).toContain("/read/7?");
  expect(screen.getByText("Nothing is waiting on you. Read.")).toBeTruthy();
  expect(
    await screen.findByText(/1,882 books, with a catalogue of 5,824/),
  ).toBeTruthy();
});

test("with nothing open, the room says so and offers the library", async () => {
  mount();
  expect(
    await screen.findByText(/Nothing is open on this device\./),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Open the library" })).toBeTruthy();
  expect(
    await screen.findByText(/Necropolis arrived from Calibre\./),
  ).toBeTruthy();
});

test("catalogue editions are named by their date", () => {
  expect(editionName("2026.10.24.2")).toMatch(/24/);
  expect(editionName("2026.10.24.2")).not.toContain("2026");
  expect(editionName("fixture-v1")).toBe("fixture-v1");
});
