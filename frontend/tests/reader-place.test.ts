// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { loadPlace, savePlace } from "../src/reading";
import { placeAt, restoreFrom } from "../src/reader/place";
import { loadSettings, saveSettings } from "../src/reader/prefs";
import { bookStyles } from "../src/reader/book-styles";

beforeEach(() => localStorage.clear());

describe("reading places", () => {
  it("opens a place saved by the first reader at its section and depth", () => {
    // Exactly what the first reader wrote.
    localStorage.setItem(
      "librarium-reading:7",
      JSON.stringify({
        uuid: "book-uuid",
        section: 3,
        fraction: 0.4,
        percent: 31,
        chapter: "Chapter Two",
        at: "2026-11-01T10:00:00.000Z",
      }),
    );
    const place = loadPlace("7", "book-uuid");
    expect(place?.percent).toBe(31);
    expect(restoreFrom(place, 10)).toEqual({ index: 3, fraction: 0.4 });
    expect(restoreFrom(place, 3)).toBeNull();
    expect(restoreFrom(null, 10)).toBeNull();
  });

  it("prefers the exact CFI once this reader has saved one", () => {
    const place = placeAt({
      uuid: "book-uuid",
      index: 4,
      fraction: 0.25,
      bookFraction: 0.4567,
      chapter: "Chapter Three",
      cfi: "epubcfi(/6/10!/4/2/8,/1:0,/1:20)",
      now: new Date("2026-11-03T09:00:00.000Z"),
    });
    expect(place).toEqual({
      uuid: "book-uuid",
      section: 4,
      fraction: 0.25,
      percent: 46,
      chapter: "Chapter Three",
      cfi: "epubcfi(/6/10!/4/2/8,/1:0,/1:20)",
      at: "2026-11-03T09:00:00.000Z",
    });
    savePlace("7", place);
    const loaded = loadPlace("7", "book-uuid");
    expect(restoreFrom(loaded, 10)).toEqual({
      cfi: "epubcfi(/6/10!/4/2/8,/1:0,/1:20)",
      fallback: { index: 4, fraction: 0.25 },
    });
    // A book that has lost that section keeps the CFI but no fallback.
    expect(restoreFrom(loaded, 3)).toEqual({
      cfi: "epubcfi(/6/10!/4/2/8,/1:0,/1:20)",
      fallback: null,
    });
    // The book page still reads its percent and chapter.
    expect(loaded?.percent).toBe(46);
    expect(loaded?.chapter).toBe("Chapter Three");
  });

  it("ignores a damaged CFI and keeps the section", () => {
    localStorage.setItem(
      "librarium-reading:7",
      JSON.stringify({
        uuid: null,
        section: 1,
        fraction: 7,
        percent: 10,
        chapter: "",
        at: "",
        cfi: 42,
      }),
    );
    const place = loadPlace("7");
    expect(place?.cfi).toBeUndefined();
    expect(restoreFrom(place, 5)).toEqual({ index: 1, fraction: 1 });
    expect(restoreFrom({ ...place!, cfi: "javascript:alert(1)" }, 5)).toEqual({
      index: 1,
      fraction: 1,
    });
  });

  it("clamps fractions it is given", () => {
    expect(
      placeAt({
        uuid: null,
        index: 0,
        fraction: Number.NaN,
        bookFraction: 1.4,
        chapter: "",
        cfi: "",
      }),
    ).toMatchObject({ fraction: 0, percent: 100 });
  });
});

describe("reader settings", () => {
  it("keeps the first reader's preferences and adds its own", () => {
    localStorage.setItem(
      "librarium-reader-prefs",
      JSON.stringify({ size: 4, tone: "night", width: "wide" }),
    );
    expect(loadSettings()).toEqual({
      size: 4,
      tone: "night",
      width: "wide",
      flow: "paginated",
      spacing: 1,
      margins: 1,
      face: "garamond",
    });
    saveSettings({
      ...loadSettings(),
      flow: "scrolled",
      spacing: 2,
      margins: 0,
      face: "book",
    });
    expect(loadSettings()).toMatchObject({
      size: 4,
      flow: "scrolled",
      spacing: 2,
      margins: 0,
      face: "book",
    });
  });

  it("falls back on anything unexpected", () => {
    localStorage.setItem(
      "librarium-reader-prefs",
      JSON.stringify({ flow: "sideways", spacing: 9, margins: -1, face: "x" }),
    );
    expect(loadSettings()).toMatchObject({
      flow: "paginated",
      spacing: 1,
      margins: 1,
      face: "garamond",
    });
    localStorage.setItem("librarium-reader-prefs", "{not json");
    expect(loadSettings().flow).toBe("paginated");
  });
});

describe("book frame styles", () => {
  it("sets size, spacing, colour and an absolute font URL", () => {
    const [before, after] = bookStyles(
      { ...loadSettings(), size: 0, spacing: 2 },
      {
        ink: "rgb(20, 20, 20)",
        link: "#245",
        selection: "rgba(1,2,3,.3)",
        scheme: "dark",
      },
    );
    expect(before).toContain("hyphens:auto");
    expect(after).toContain("font-size:17px!important");
    expect(after).toContain("line-height:1.85!important");
    expect(after).toContain("color:rgb(20, 20, 20)!important");
    expect(after).toMatch(/src:url\("http:\/\/[^"]+\.woff2"\)/);
    expect(after).toContain('"Librarium Garamond"');
  });

  it("leaves the book's own typeface alone when asked", () => {
    const [, after] = bookStyles(
      { ...loadSettings(), face: "book" },
      { ink: "#000", link: "#000", selection: "#ccc", scheme: "light" },
    );
    expect(after).not.toContain("@font-face");
    expect(after).not.toContain("font-family");
  });

  it("never lets a computed colour break out of its declaration", () => {
    const [, after] = bookStyles(loadSettings(), {
      ink: "red;}body{display:none",
      link: "",
      selection: "x",
      scheme: "light",
    });
    expect(after).not.toContain("display:none");
    expect(after).toContain("color:#222!important");
  });
});
