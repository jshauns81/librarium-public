import garamond from "@fontsource-variable/eb-garamond/files/eb-garamond-latin-wght-normal.woff2?url";
import garamondItalic from "@fontsource-variable/eb-garamond/files/eb-garamond-latin-wght-italic.woff2?url";
import garamondExt from "@fontsource-variable/eb-garamond/files/eb-garamond-latin-ext-wght-normal.woff2?url";
import garamondExtItalic from "@fontsource-variable/eb-garamond/files/eb-garamond-latin-ext-wght-italic.woff2?url";
import literata from "@fontsource-variable/literata/files/literata-latin-wght-normal.woff2?url";
import literataItalic from "@fontsource-variable/literata/files/literata-latin-wght-italic.woff2?url";
import literataExt from "@fontsource-variable/literata/files/literata-latin-ext-wght-normal.woff2?url";
import literataExtItalic from "@fontsource-variable/literata/files/literata-latin-ext-wght-italic.woff2?url";
import {
  LINE_SPACING,
  TEXT_SIZES,
  type Face,
  type ReaderSettings,
} from "./prefs";

// Styles the engine places inside each book frame. The frames are blob:
// documents, so fonts are named by absolute same-origin URLs, and colours are
// concrete values read from the reader page rather than its custom properties.

const LATIN =
  "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD";
const LATIN_EXT =
  "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF";

const FACES: Record<
  Exclude<Face, "book">,
  { family: string; weight: string; files: [string, string, string, string] }
> = {
  garamond: {
    family: "Librarium Garamond",
    weight: "400 800",
    files: [garamond, garamondItalic, garamondExt, garamondExtItalic],
  },
  literata: {
    family: "Librarium Literata",
    weight: "200 900",
    files: [literata, literataItalic, literataExt, literataExtItalic],
  },
};

export type PageColours = {
  ink: string;
  link: string;
  selection: string;
  /** The reader page's scheme. A frame whose scheme differs is painted opaque. */
  scheme: "light" | "dark";
};

const absolute = (url: string) => new URL(url, location.href).href;
// Colours come from computed styles; keep only characters a colour can use.
const colour = (value: string, fallback: string) =>
  /^[#(),.%\s\w-]+$/.test(value.trim()) && value.trim()
    ? value.trim()
    : fallback;

function fontFaces(face: Exclude<Face, "book">) {
  const { family, weight, files } = FACES[face];
  const rule = (url: string, style: string, range: string) =>
    `@font-face{font-family:"${family}";font-style:${style};font-weight:${weight};font-display:swap;src:url("${absolute(url)}") format("woff2");unicode-range:${range}}`;
  return [
    rule(files[0], "normal", LATIN),
    rule(files[1], "italic", LATIN),
    rule(files[2], "normal", LATIN_EXT),
    rule(files[3], "italic", LATIN_EXT),
  ].join("\n");
}

/** [styles before the book's own, styles after them] for one set of settings. */
export function bookStyles(
  settings: ReaderSettings,
  colours: PageColours,
): [string, string] {
  const ink = colour(colours.ink, "#222");
  const link = colour(colours.link, ink);
  const selection = colour(colours.selection, "rgba(128,128,128,.35)");
  const size = TEXT_SIZES[settings.size] ?? TEXT_SIZES[2];
  const spacing = LINE_SPACING[settings.spacing] ?? LINE_SPACING[1];
  const before = `html{hyphens:auto;-webkit-hyphens:auto;}`;
  const face =
    settings.face === "book"
      ? ""
      : `${fontFaces(settings.face)}
html,body{font-family:"${FACES[settings.face].family}",Georgia,serif!important;}
body :not(pre,code,kbd,samp,pre *,code *,svg,svg *){font-family:inherit!important;}`;
  const after = `${face}
html{color-scheme:${colours.scheme === "light" ? "light" : "dark"}!important;color:${ink}!important;background:transparent!important;font-size:${size}px!important;-webkit-text-size-adjust:none;text-size-adjust:none;}
body,body *{background-color:transparent!important;}
body,body :not(a,a *){color:inherit!important;}
p,li,blockquote,dd,dt,div{line-height:${spacing}!important;}
:is(h1,h2,h3,h4,h5,h6){line-height:1.25!important;}
a,a *{color:${link}!important;}
::selection{background:${selection};}
img,svg{max-width:100%;}`;
  return [before, after];
}
