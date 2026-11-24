// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Settings } from "../src/Settings";
import { applyRoomPrefs } from "../src/room-prefs";

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.roomLight;
  delete document.documentElement.dataset.motion;
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    })),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.startsWith("/api/direct-library?")
        ? json({
            inventory: {
              token: "a".repeat(64),
              observed_at: new Date().toISOString(),
            },
            total: 1882,
            books: [],
          })
        : url === "/api/catalogue"
          ? json({ status: "ready", version: "2026.10.24.2", total: 5824 })
          : json({ error: "Unexpected" }, 404),
    ),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Settings />
    </QueryClientProvider>,
  );
}

test("every room is offered and choosing one applies and keeps it", () => {
  mount();
  const rooms = screen
    .getAllByRole("radio")
    .filter((input) => (input as HTMLInputElement).name === "room");
  expect(rooms).toHaveLength(3);
  fireEvent.click(screen.getByRole("radio", { name: /^Light/ }));
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem("librarium.theme")).toBe("light");
});

test("room light off keeps the room's own colours, here and on the next visit", () => {
  mount();
  fireEvent.click(screen.getByRole("radio", { name: "Off" }));
  expect(document.documentElement.dataset.roomLight).toBe("off");
  delete document.documentElement.dataset.roomLight;
  applyRoomPrefs();
  expect(document.documentElement.dataset.roomLight).toBe("off");
});

test("text size steps save the reader's starting size", () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Larger text" }));
  expect(
    JSON.parse(localStorage.getItem("librarium-reader-prefs") ?? "{}").size,
  ).toBe(3);
  expect(screen.getByText(/^23 pixels\./)).toBeTruthy();
});

test("the library and catalogue lines state real counts", async () => {
  mount();
  expect(
    await screen.findByText(/1,882 books · read only · looked at just now/),
  ).toBeTruthy();
  expect(await screen.findByText(/edition · 5,824 works/)).toBeTruthy();
});

test("says plainly that Librarium reads books and never fixes or replaces them", () => {
  mount();
  expect(screen.queryByRole("link", { name: "Fixing books" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Fixing books" })).toBeNull();
  expect(
    screen.queryByText(/fixed cop|review cop|replacing books/i),
  ).toBeNull();
  expect(screen.getByText(/does not change them/)).toBeTruthy();
});
