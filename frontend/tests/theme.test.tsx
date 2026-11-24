// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ThemePicker } from "../src/ThemePicker";
import { themes } from "../src/themes";
import {
  applyTheme,
  migrateStoredPreference,
  readPreference,
  themeStorageKey,
} from "../src/theme";

let change: (event: { matches: boolean }) => void;
let dark = false;
const remove = vi.fn();
beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.head.innerHTML = '<meta name="theme-color" content="#24273a">';
  dark = false;
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      get matches() {
        return dark;
      },
      addEventListener: (_: string, listener: typeof change) => {
        change = listener;
      },
      removeEventListener: remove,
    })),
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("changes the whole document immediately and remembers the selected room", () => {
  const { unmount } = render(<ThemePicker />);
  const select = screen.getByRole("combobox", { name: "Theme" });
  fireEvent.change(select, { target: { value: "light" } });
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(
    document.querySelector('meta[name="theme-color"]')?.getAttribute("content"),
  ).toBe("#f4ede0");
  expect(localStorage.getItem(themeStorageKey)).toBe("light");
  unmount();
  render(<ThemePicker />);
  expect(
    (screen.getByRole("combobox", { name: "Theme" }) as HTMLSelectElement)
      .value,
  ).toBe("light");
});

it("offers exactly the two rooms and the device's choice", () => {
  render(<ThemePicker />);
  expect(
    screen.getAllByRole("option").map((option) => option.textContent),
  ).toEqual(["System", "Dark", "Light"]);
});

it("opens in the dark room by default", () => {
  render(<ThemePicker />);
  expect(
    (screen.getByRole("combobox", { name: "Theme" }) as HTMLSelectElement)
      .value,
  ).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it.each([
  ["parchment", "light"],
  ["catppuccin-latte", "light"],
  ["dracula-alucard", "light"],
  ["solarized-light", "light"],
  ["librarium", "dark"],
  ["catppuccin-mocha", "dark"],
  ["nord", "dark"],
  ["dracula", "dark"],
])("an earlier %s room opens as %s and is rewritten once", (earlier, now) => {
  localStorage.setItem(themeStorageKey, earlier);
  expect(readPreference()).toBe(now);
  applyTheme(themes, earlier);
  expect(document.documentElement.dataset.theme).toBe(now);
  migrateStoredPreference();
  expect(localStorage.getItem(themeStorageKey)).toBe(now);
});

it("follows live device changes only while System is selected", () => {
  const { unmount } = render(<ThemePicker />);
  const select = screen.getByRole("combobox", { name: "Theme" });
  fireEvent.change(select, { target: { value: "system" } });
  expect(document.documentElement.dataset.theme).toBe("light");
  dark = true;
  change({ matches: true });
  expect(document.documentElement.dataset.theme).toBe("dark");
  fireEvent.change(select, { target: { value: "light" } });
  dark = false;
  change({ matches: false });
  expect(document.documentElement.dataset.theme).toBe("light");
  dark = true;
  change({ matches: true });
  expect(document.documentElement.dataset.theme).toBe("light");
  unmount();
  expect(remove).toHaveBeenCalled();
});

it("synchronizes other tabs, including a cleared preference", () => {
  render(<ThemePicker />);
  fireEvent(
    window,
    new StorageEvent("storage", { key: themeStorageKey, newValue: "light" }),
  );
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(
    (screen.getByRole("combobox", { name: "Theme" }) as HTMLSelectElement)
      .value,
  ).toBe("light");
  fireEvent(window, new StorageEvent("storage", { key: null }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it.each(["unknown", "__proto__", "constructor", "<script>alert(1)</script>"])(
  "ignores unsupported saved input %s",
  (value) => {
    localStorage.setItem(themeStorageKey, value);
    expect(readPreference()).toBe("dark");
    applyTheme(themes, value);
    expect(document.documentElement.dataset.theme).toBe("dark");
  },
);

it("still changes rooms when browser storage is blocked and explains persistence", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("blocked", "SecurityError");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });
  render(<ThemePicker />);
  fireEvent.change(screen.getByRole("combobox", { name: "Theme" }), {
    target: { value: "light" },
  });
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(screen.getByRole("status").textContent).toMatch(/not saved/i);
});

function luminance(hex: string) {
  const channels = hex
    .slice(1)
    .match(/../g)!
    .map((v) => parseInt(v, 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
function contrast(a: string, b: string) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}
it("keeps text, focus, control edges and progress readable in every palette and state", () => {
  for (const theme of themes) {
    const c = theme.colors;
    for (const background of [
      c.ground,
      c.surface,
      c["selection-fill"],
      c["pressed-fill"],
      c["evidence-well"],
    ]) {
      for (const foreground of [
        c.ink,
        c.muted,
        c.accent,
        c.copper,
        c.attention,
      ]) {
        expect(
          contrast(foreground, background),
          `${theme.id}: ${foreground} on ${background}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      expect(
        contrast(c.line, background),
        `${theme.id}: control edge`,
      ).toBeGreaterThanOrEqual(3);
      expect(
        contrast(c["attention-line"], background),
        `${theme.id}: error edge`,
      ).toBeGreaterThanOrEqual(3);
    }
    for (const fill of [c.accent, c["accent-hover"]]) {
      expect(
        contrast(c["on-accent"], fill),
        `${theme.id}: primary label`,
      ).toBeGreaterThanOrEqual(4.5);
    }
    expect(
      contrast(c.accent, c["progress-track"]),
      `${theme.id}: progress`,
    ).toBeGreaterThanOrEqual(3);
  }
});
