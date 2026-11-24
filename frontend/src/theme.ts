import { themes, type Theme } from "./themes.ts";

export const themeStorageKey = "librarium.theme";

// Also serialized into the blocking, same-origin boot asset. Keep it self-contained.
export function applyTheme(
  palettes: readonly Theme[],
  preference: string | null,
) {
  // Rooms from before there were two keep their light or dark.
  const earlierLight = [
    "parchment",
    "catppuccin-latte",
    "dracula-alucard",
    "solarized-light",
  ];
  const selected =
    preference === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : preference && earlierLight.includes(preference)
        ? "light"
        : preference;
  const theme = palettes.find((entry) => entry.id === selected) ?? palettes[0];
  document.documentElement.dataset.theme = theme.id;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme.colors.ground);
  return theme.id;
}

const EARLIER_LIGHT = new Set([
  "parchment",
  "catppuccin-latte",
  "dracula-alucard",
  "solarized-light",
]);

/** The room a stored choice now means; any earlier dark room is Dark. */
export function validPreference(value: string | null) {
  if (value === "system" || themes.some((theme) => theme.id === value))
    return value!;
  if (value && EARLIER_LIGHT.has(value)) return "light";
  return "dark";
}

export function readPreference() {
  try {
    return validPreference(localStorage.getItem(themeStorageKey));
  } catch {
    return "dark";
  }
}

/** Rewrites an earlier room's id to the room it now means, once. */
export function migrateStoredPreference() {
  try {
    const stored = localStorage.getItem(themeStorageKey);
    if (stored === null) return;
    const next = validPreference(stored);
    if (next !== stored) localStorage.setItem(themeStorageKey, next);
  } catch {
    // The mapped room still applies for this visit.
  }
}
