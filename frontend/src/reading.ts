// Reading place and reader preferences live in this browser only.

export type ReadingPlace = {
  uuid: string | null;
  section: number;
  fraction: number;
  percent: number;
  chapter: string;
  at: string;
  /** The exact spot as an EPUB CFI; places saved before it open by section. */
  cfi?: string;
};

export type ReaderPrefs = {
  size: number;
  tone: "room" | "night" | "parchment" | "paper";
  width: "narrow" | "wide";
};

export const TEXT_SIZES = [17, 19, 21, 23, 26];
const DEFAULT_PREFS: ReaderPrefs = { size: 2, tone: "room", width: "narrow" };
const placeKey = (bookId: string) => `librarium-reading:${bookId}`;
const PREFS_KEY = "librarium-reader-prefs";

export function loadPlace(
  bookId: string,
  uuid?: string | null,
): ReadingPlace | null {
  try {
    const value = JSON.parse(localStorage.getItem(placeKey(bookId)) ?? "null");
    if (
      !value ||
      typeof value.section !== "number" ||
      typeof value.fraction !== "number" ||
      typeof value.percent !== "number"
    )
      return null;
    // A different book now holds this Calibre id: forget the old place.
    if (uuid && value.uuid && value.uuid !== uuid) return null;
    if (value.cfi !== undefined && typeof value.cfi !== "string")
      delete value.cfi;
    return value as ReadingPlace;
  } catch {
    return null;
  }
}

export function savePlace(bookId: string, place: ReadingPlace) {
  try {
    localStorage.setItem(placeKey(bookId), JSON.stringify(place));
  } catch {
    // Reading continues; the place is simply not remembered.
  }
}

export function loadPrefs(): ReaderPrefs {
  try {
    const value = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "null");
    return {
      size:
        Number.isInteger(value?.size) &&
        value.size >= 0 &&
        value.size < TEXT_SIZES.length
          ? value.size
          : DEFAULT_PREFS.size,
      tone: ["room", "night", "parchment", "paper"].includes(value?.tone)
        ? value.tone
        : DEFAULT_PREFS.tone,
      width: value?.width === "wide" ? "wide" : "narrow",
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(prefs: ReaderPrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Preferences apply for this visit only.
  }
}

export type CoverLight = { deep: string; light: string };

const ROOM_MUTED = [0xe7, 0xdc, 0xcf];
// The dark room's rubric: initials, numerals and margin labels sit on the room too.
const ROOM_RUBRIC = [0xef, 0x92, 0x70];

function luminance([r, g, b]: number[]) {
  const [lr, lg, lb] = [r, g, b].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

export function contrast(a: number[], b: number[]) {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

function fromHsl(hue: number, s: number, l: number) {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((hue % 2) - 1));
  const [r1, g1, b1] =
    hue < 1
      ? [c, x, 0]
      : hue < 2
        ? [x, c, 0]
        : hue < 3
          ? [0, c, x]
          : hue < 4
            ? [0, x, c]
            : hue < 5
              ? [x, 0, c]
              : [c, 0, x];
  const m = l - c / 2;
  return [r1, g1, b1].map((value) => Math.round((value + m) * 255));
}

/** The cover's strongest colour as two room lights: deep for dark rooms, light for light ones. */
export function lightFromPixels(data: Uint8ClampedArray): CoverLight | null {
  const pixels: [number, number, number, number][] = [];
  for (let index = 0; index + 3 < data.length; index += 4) {
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    if (data[index + 3] < 128 || max < 40 || min > 225) continue;
    pixels.push([r, g, b, (max - min) / max]);
  }
  // A few vivid pixels (a red seal, a green cloak) say more than a grey sky.
  const vivid = pixels.filter((pixel) => pixel[3] > 0.3);
  const chosen =
    vivid.length >= Math.max(1, pixels.length * 0.03) ? vivid : pixels;
  let red = 0;
  let green = 0;
  let blue = 0;
  let weight = 0;
  for (const [r, g, b, saturation] of chosen) {
    const w = 0.15 + saturation * saturation;
    red += r * w;
    green += g * w;
    blue += b * w;
    weight += w;
  }
  if (!weight) return null;
  // Keep the cover's hue but set a fixed depth, so a dark cover still shows
  // its colour and a bright one never washes out the text.
  const [r, g, b] = [red, green, blue].map((value) => value / weight / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const chroma = max - min;
  let hue = 0;
  if (chroma) {
    if (max === r) hue = ((g - b) / chroma + 6) % 6;
    else if (max === g) hue = (b - r) / chroma + 2;
    else hue = (r - g) / chroma + 4;
  }
  const lightness = (max + min) / 2;
  const saturation = chroma ? chroma / (1 - Math.abs(2 * lightness - 1)) : 0;
  const s =
    saturation < 0.08
      ? saturation
      : Math.min(0.62, Math.max(0.32, saturation * 1.5));
  // Pale room text must read at 5:1 and the rubric at 4.6:1 whatever the art,
  // without the haze.
  let l = 0.3;
  let deep = fromHsl(hue, s, l);
  while (
    (contrast(ROOM_MUTED, deep) < 5 || contrast(ROOM_RUBRIC, deep) < 4.6) &&
    l > 0.05
  ) {
    l -= 0.01;
    deep = fromHsl(hue, s, l);
  }
  return { deep: deep.join(" "), light: fromHsl(hue, s, 0.86).join(" ") };
}

export function moodFromPixels(data: Uint8ClampedArray): string | null {
  return lightFromPixels(data)?.deep ?? null;
}

export type CoverRoom = CoverLight & { haze: string };

/** Room light and a 12x18 haze for one cover; upscaling the tiny image blurs it for free. */
export function coverRoom(url: string): Promise<CoverRoom | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = 24;
        canvas.height = 36;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) return resolve(null);
        context.drawImage(image, 0, 0, 24, 36);
        const light = lightFromPixels(context.getImageData(0, 0, 24, 36).data);
        if (!light) return resolve(null);
        const tiny = document.createElement("canvas");
        tiny.width = 12;
        tiny.height = 18;
        tiny.getContext("2d")?.drawImage(image, 0, 0, 12, 18);
        resolve({ ...light, haze: tiny.toDataURL("image/jpeg", 0.8) });
      } catch {
        resolve(null);
      }
    };
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

export function coverMood(url: string): Promise<string | null> {
  return coverRoom(url).then((room) => room?.deep ?? null);
}
