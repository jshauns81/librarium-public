// The lit room: each room takes the open book's cover colour, by scheme.
// Dark rooms use the capped deep mood under pale text, and the haze may only
// deepen them. Light rooms mix the light mood into vellum, and the haze only
// tints, so brightness and contrast stay put.
export function roomTokens(scheme: "light" | "dark") {
  const shared =
    "--rubric:var(--copper);--wash:color-mix(in oklab,var(--room) 7%,var(--ground));--wash-strong:color-mix(in oklab,var(--room) 14%,var(--surface));";
  return scheme === "dark"
    ? `--room:rgb(var(--mood-deep));--room-ink:#f8f1e6;--room-muted:#e7dccf;--plate:color-mix(in oklab,var(--surface) 82%,#000);--plate-edge:color-mix(in oklab,var(--surface) 70%,var(--ink));--haze-opacity:.5;--haze-blend:multiply;--on-rubric:#2b1a12;${shared}`
    : `--room:color-mix(in oklab,rgb(var(--mood-light)) 70%,var(--ground));--room-ink:var(--ink);--room-muted:var(--muted);--plate:color-mix(in oklab,var(--ground) 50%,#fff);--plate-edge:color-mix(in oklab,var(--ground) 80%,var(--ink));--haze-opacity:.6;--haze-blend:color;--on-rubric:#fbf3e6;${shared}`;
}
