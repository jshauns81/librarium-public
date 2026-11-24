import type { ReadingPlace } from "../reading";

// A place saved by this reader carries an exact CFI. Places saved by the first
// reader only have a spine section and how far down it the reader had scrolled;
// those still open, at the same proportion of the same section.

type Section = { index: number; fraction: number };
// A saved CFI carries the section it was taken in, for when the book has
// changed and the exact position no longer resolves.
export type Restore =
  { cfi: string; fallback: Section | null } | Section | null;

const clamp = (value: number) =>
  Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;

export function restoreFrom(
  place: ReadingPlace | null,
  sections: number,
): Restore {
  if (!place) return null;
  const section =
    Number.isInteger(place.section) &&
    place.section >= 0 &&
    place.section < sections
      ? { index: place.section, fraction: clamp(place.fraction) }
      : null;
  if (place.cfi && /^epubcfi\(.+\)$/.test(place.cfi))
    return { cfi: place.cfi, fallback: section };
  return section;
}

export function placeAt(at: {
  uuid: string | null;
  index: number;
  fraction: number;
  bookFraction: number;
  chapter: string;
  cfi: string;
  now?: Date;
}): ReadingPlace {
  return {
    uuid: at.uuid,
    section: at.index,
    fraction: clamp(at.fraction),
    percent: Math.round(clamp(at.bookFraction) * 100),
    chapter: at.chapter,
    cfi: at.cfi,
    at: (at.now ?? new Date()).toISOString(),
  };
}
