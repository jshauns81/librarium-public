export type ThemeColors = Record<
  | "ground"
  | "surface"
  | "ink"
  | "muted"
  | "accent"
  | "accent-hover"
  | "on-accent"
  | "copper"
  | "line"
  | "soft-line"
  | "selection-fill"
  | "pressed-fill"
  | "evidence-well"
  | "attention"
  | "attention-line"
  | "progress-track",
  string
>;
export type Theme = {
  id: string;
  name: string;
  family: string;
  scheme: "light" | "dark";
  colors: ThemeColors;
  brand?: { ink: string; accent: string; wordmark: string };
};

// Two rooms: vellum and lapis by day, a candlelit scriptorium by night.
// The open book's cover lights either one; see room-tokens.ts.
export const themes: readonly Theme[] = [
  {
    id: "dark",
    name: "Dark",
    family: "Librarium",
    scheme: "dark",
    brand: { ink: "#efe5d3", accent: "#c9a25f", wordmark: "#efe5d3" },
    colors: {
      ground: "#1b1714",
      surface: "#15120f",
      ink: "#efe5d3",
      muted: "#bfb2a2",
      accent: "#9db6ef",
      "accent-hover": "#bccdf5",
      "on-accent": "#111a30",
      copper: "#ef9270",
      line: "#9a8b7b",
      "soft-line": "#3f3731",
      "selection-fill": "#2e2823",
      "pressed-fill": "#27221e",
      "evidence-well": "#221d19",
      attention: "#f3a5ad",
      "attention-line": "#d88d96",
      "progress-track": "#433a33",
    },
  },
  {
    id: "light",
    name: "Light",
    family: "Librarium",
    scheme: "light",
    brand: { ink: "#231b16", accent: "#8a6424", wordmark: "#231b16" },
    colors: {
      ground: "#f4ede0",
      surface: "#ebe1cf",
      ink: "#231b16",
      muted: "#5b4c40",
      accent: "#24479a",
      "accent-hover": "#1c3a80",
      "on-accent": "#f7f1e6",
      copper: "#a0331a",
      line: "#7b6a5b",
      "soft-line": "#cfc0a8",
      "selection-fill": "#e4d8c2",
      "pressed-fill": "#ddcfb6",
      "evidence-well": "#efe6d5",
      attention: "#97203a",
      "attention-line": "#97203a",
      "progress-track": "#d6c8b0",
    },
  },
];
