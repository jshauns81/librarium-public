import { loadPrefs, savePrefs, TEXT_SIZES, type ReaderPrefs } from "../reading";

// The first reader stored size, tone and width. This one keeps those under the
// same key and adds how pages turn, line spacing, margins and the typeface.

export type Flow = "paginated" | "scrolled";
export type Face = "garamond" | "literata" | "book";
export type ReaderSettings = ReaderPrefs & {
  flow: Flow;
  spacing: number;
  margins: number;
  face: Face;
};

export { TEXT_SIZES };
export const LINE_SPACING = [1.45, 1.65, 1.85];
// The engine shows about half of each side margin beside a single page.
export const MARGINS = [24, 48, 88];
// Same key as reading.ts, so older preferences carry over.
const PREFS_KEY = "librarium-reader-prefs";
const DEFAULTS = {
  flow: "paginated",
  spacing: 1,
  margins: 1,
  face: "garamond",
};

const index = (value: unknown, length: number, fallback: number) =>
  Number.isInteger(value) &&
  (value as number) >= 0 &&
  (value as number) < length
    ? (value as number)
    : fallback;

export function loadSettings(): ReaderSettings {
  let stored: Record<string, unknown> = {};
  try {
    const value = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "null");
    if (value && typeof value === "object") stored = value;
  } catch {
    // Defaults apply.
  }
  return {
    ...loadPrefs(),
    flow: stored.flow === "scrolled" ? "scrolled" : "paginated",
    spacing: index(stored.spacing, LINE_SPACING.length, DEFAULTS.spacing),
    margins: index(stored.margins, MARGINS.length, DEFAULTS.margins),
    face: (["garamond", "literata", "book"] as const).includes(
      stored.face as Face,
    )
      ? (stored.face as Face)
      : "garamond",
  };
}

export function saveSettings(settings: ReaderSettings) {
  savePrefs(settings);
}
