"""Build the Librarium Design System artifact's files from the checked-in sources.

Colours come from frontend/src/themes.ts, the component stylesheet from the two
application stylesheets, and everything authored (brand book, sections,
component previews) from design-system/project/. The output tree mirrors the
artifact's project/ folder so it can be published as-is. Nothing here writes to
the artifact; publishing stays a reviewed step (docs/design/design-system-artifact.md).
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

# Product brief: two rooms, Dark (the first-visit default) and Light.
LAUNCH_THEMES = ["dark", "light"]
ROLES = [
    "ground",
    "surface",
    "ink",
    "muted",
    "accent",
    "accent-hover",
    "on-accent",
    "copper",
    "line",
    "soft-line",
    "selection-fill",
    "pressed-fill",
    "evidence-well",
    "progress-track",
    "attention",
    "attention-line",
]
BRAND_ROLES = ["brand-ink", "brand-accent", "brand-wordmark"]
# Custom properties the stylesheets declare themselves rather than read from a theme.
LOCAL_VARIABLES = {
    "ease-folio",
    "librarium-ink",
    "librarium-accent",
    "librarium-wordmark",
    "shelf-columns",
}
# (foreground, background, minimum): text pairs at 4.5:1, edges and focus at 3:1.
CONTRAST_PAIRS = [
    ("ink", "ground", 4.5),
    ("ink", "surface", 4.5),
    ("muted", "ground", 4.5),
    ("muted", "surface", 4.5),
    ("muted", "evidence-well", 4.5),
    ("accent", "ground", 4.5),
    ("accent", "surface", 4.5),
    ("on-accent", "accent", 4.5),
    ("copper", "ground", 4.5),
    ("attention", "ground", 4.5),
    ("line", "ground", 3.0),
    ("accent", "selection-fill", 3.0),
]
STYLESHEETS = ["frontend/src/style.css", "frontend/src/reading-room.css"]
FONT = "literata-latin-wght-normal.woff2"
ASSETS = [
    ("Logos", "images/brand/librarium-a/librarium-emblem.svg"),
    ("Logos", "images/brand/librarium-a/librarium-horizontal.svg"),
    ("Logos", "images/brand/librarium-a/librarium-stacked.svg"),
    ("Logos", "images/brand/librarium-a/librarium-wordmark.svg"),
    ("Logos", "images/brand/librarium-a/librarium-icon-small.svg"),
    ("Logos", "images/brand/librarium-a/librarium-icon-micro.svg"),
    ("Favicons", "images/brand/librarium-a/librarium-favicon-dark.svg"),
    ("Favicons", "images/brand/librarium-a/librarium-favicon-light.svg"),
    ("Inspiration", "images/inspiration/librarium-01-collection-atlas.png"),
    ("Inspiration", "images/inspiration/librarium-02-book-atelier.png"),
    ("Inspiration", "images/inspiration/librarium-03-reading-room.png"),
    ("Historical", "images/brand/librarium-icon-original.png"),
]


def parse_themes(source: str) -> list[dict]:
    """Read the theme registry literal; themes.ts stays the single source of colour."""
    themes = []
    for block in re.split(r"\n  \{\n", source)[1:]:

        def field(key: str, block: str = block) -> str:
            return re.search(rf'^    {key}: "([^"]*)"', block, re.MULTILINE).group(1)

        colors_body = re.search(r"colors: \{(.*?)\n    \}", block, re.DOTALL).group(1)
        colors = {
            key: value.lower()
            for key, value in re.findall(r'"?([\w-]+)"?: "(#[0-9a-fA-F]{6})"', colors_body)
        }
        brand_match = re.search(
            r'brand: \{ ink: "(#\w+)", accent: "(#\w+)", wordmark: "(#\w+)" \}', block
        )
        brand = (
            dict(zip(["ink", "accent", "wordmark"], (v.lower() for v in brand_match.groups())))
            if brand_match
            else {"ink": colors["ink"], "accent": colors["copper"], "wordmark": colors["ink"]}
        )
        themes.append(
            {
                "id": field("id"),
                "name": field("name"),
                "family": field("family"),
                "scheme": field("scheme"),
                "colors": colors,
                "brand": brand,
            }
        )
    return themes


def _luminance(value: str) -> float:
    channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    a, b = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _role_value(theme: dict, role: str) -> str:
    return (
        theme["brand"][role.removeprefix("brand-")]
        if role in BRAND_ROLES
        else theme["colors"][role]
    )


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return "unknown"


def _design_md_colors(root: Path) -> dict[str, str]:
    front = (root / "DESIGN.md").read_text().split("---")[1]
    block = front.split("colors:")[1].split("typography:")[0]
    return {key: value.lower() for key, value in re.findall(r'\n  ([\w-]+): "(#\w+)"', block)}


def _themes_section(themes: list[dict]) -> str:
    lines = [
        "# Themes",
        "",
        (
            "Generated from `frontend/src/themes.ts`; edit the registry, not this page. "
            "Every theme shares composition and meaning: only values change. "
            "The token view carries the eight launch themes; all eleven registered themes are "
            "listed here. `System` is not a palette: it follows the device live through "
            "Catppuccin Latte and Mocha."
        ),
        "",
        "| Theme | Family | Scheme | In token view |",
        "| --- | --- | --- | --- |",
    ]
    for theme in themes:
        lines.append(
            f"| {theme['name']} | {theme['family']} | {theme['scheme']} | "
            f"{'yes' if theme['id'] in LAUNCH_THEMES else 'reference only'} |"
        )
    lines += [
        "",
        "## Contrast",
        "",
        (
            "Text pairs need 4.5:1; control edges and focus need 3:1. Ratios are computed on "
            "every build; a miss is marked **below** and belongs in the theme's fix list."
        ),
        "",
    ]
    header = "| Pair | " + " | ".join(t["name"] for t in themes) + " |"
    lines += [header, "| --- |" + " --- |" * len(themes)]
    for fg, bg, minimum in CONTRAST_PAIRS:
        cells = []
        for theme in themes:
            ratio = contrast(theme["colors"][fg], theme["colors"][bg])
            cells.append(f"{ratio:.1f}" + ("" if ratio >= minimum else " **below**"))
        lines.append(f"| `{fg}` on `{bg}` ({minimum:g}:1) | " + " | ".join(cells) + " |")
    lines += ["", "## Values", ""]
    roles = ROLES + BRAND_ROLES
    for start in range(0, len(themes), 6):
        chunk = themes[start : start + 6]
        lines += [
            "| Role | " + " | ".join(t["name"] for t in chunk) + " |",
            "| --- |" + " --- |" * len(chunk),
        ]
        for role in roles:
            lines.append(
                f"| `{role}` | " + " | ".join(f"`{_role_value(t, role)}`" for t in chunk) + " |"
            )
        lines.append("")
    return "\n".join(lines)


GITHUB_BLOB = "https://github.com/jshauns81/librarium-public/blob/main/"


def _ux_standards_section(root: Path) -> str:
    """Copy the canonical UX standards verbatim; only relative links are made absolute."""
    title, body = (root / "docs/ux-standards.md").read_text().split("\n", 1)
    body = re.sub(
        r"\]\((?!https?:|#)([^)]+)\)",
        lambda m: f"]({GITHUB_BLOB}{(Path('docs') / m.group(1)).as_posix()})",
        body,
    )
    note = (
        "Copied word for word from `docs/ux-standards.md`, the single owner of these rules, "
        "on every build. Change them there, never here."
    )
    return f"{title}\n\n{note}\n{body}"


def _object_labels(source: str, opening: str) -> dict[str, str]:
    """Read a flat `key: "Label"` object literal that follows `opening` in TypeScript source."""
    start = source.index(opening) + len(opening)
    body = source[start : source.index("}", start)]
    return dict(re.findall(r'(\w+): "([^"]+)"', body))


def _status_labels(root: Path) -> dict[str, dict[str, str]]:
    library = (root / "frontend/src/Library.tsx").read_text()
    progress = (root / "frontend/src/JobProgress.tsx").read_text()
    check = re.search(
        r'coverage === "complete"\s*\?\s*"([^"]+)"\s*:\s*coverage === "partial"'
        r'\s*\?\s*"([^"]+)"\s*:\s*"([^"]+)"',
        library,
    ).groups()
    return {
        "Library state (`matchLabels`, `Library.tsx`)": _object_labels(
            library, "export const matchLabels = {"
        ),
        "Check coverage (`checkLabel`, `Library.tsx`)": dict(
            zip(["complete", "partial", "unknown"], check)
        ),
        "Job state (`stateLabel`, `JobProgress.tsx`)": _object_labels(
            progress, "export const stateLabel: Record<string, string> = {"
        ),
        "Finding (`JobProgress.tsx`)": _object_labels(progress, "? {"),
    }


def _status_labels_section(labels: dict[str, dict[str, str]]) -> str:
    lines = [
        "# Status labels",
        "",
        (
            "Generated from the label maps in the frontend, so a design uses exactly the words "
            "the app shows. What each label may claim, and when it may appear, is owned by "
            "**UX standards**."
        ),
    ]
    for heading, mapping in labels.items():
        lines += ["", f"## {heading}", "", "| Key | Label |", "| --- | --- |"]
        lines += [f"| `{key}` | {label} |" for key, label in mapping.items()]
    return "\n".join(lines)


def _tokens(root: Path, themes: list[dict]) -> dict:
    base = json.loads((root / "design-system/tokens.base.json").read_text())
    usage = base["color"].pop("usage")
    by_id = {theme["id"]: theme for theme in themes}
    launch = [by_id[theme_id] for theme_id in LAUNCH_THEMES]
    base["color"] = {
        "themes": [{"id": t["id"], "name": t["name"]} for t in launch],
        "tokens": [
            {
                "name": role,
                "value": {t["id"]: _role_value(t, role) for t in launch},
                "usage": usage[role],
            }
            for role in ROLES + BRAND_ROLES
        ],
    }
    base["meta"] = {
        "source": "code",
        "repo": "jshauns81/librarium",
        "ref": f"{_git(root, 'rev-parse', '--abbrev-ref', 'HEAD')}@{_git(root, 'rev-parse', '--short', 'HEAD')}",
        "paths": {
            "tokens": ["frontend/src/themes.ts"],
            "type": ["design-system/tokens.base.json", "DESIGN.md"],
            "stylesheets": STYLESHEETS,
            "fonts": ["@fontsource-variable/literata 5.3.0"],
            "assets": sorted({path.rsplit("/", 1)[0] for _, path in ASSETS}),
            "docs": ["DESIGN.md", "PRODUCT.md", "docs/ux-standards.md"],
            "labels": ["frontend/src/Library.tsx", "frontend/src/JobProgress.tsx"],
        },
        "synced": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    return base


def build(root: Path, out: Path, fonts_dir: Path | None) -> dict:
    root, out = Path(root), Path(out)
    project = out / "project"
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(root / "design-system/project", project)

    themes = parse_themes((root / "frontend/src/themes.ts").read_text())
    (project / "tokens.json").write_text(json.dumps(_tokens(root, themes), indent=2) + "\n")
    (project / "1-themes.md").write_text(_themes_section(themes) + "\n")
    (project / "2-ux-standards.md").write_text(_ux_standards_section(root))
    (project / "3-status-labels.md").write_text(_status_labels_section(_status_labels(root)) + "\n")

    css = "".join(f"/* {path} */\n{(root / path).read_text()}\n" for path in STYLESHEETS)
    if "</style" in css.lower():
        raise ValueError("stylesheet contains a literal </style")
    (project / "components/bundle.css").write_text(
        "/* Librarium application stylesheets, copied verbatim by scripts/design_system.py */\n"
        + css
    )

    (project / "brand").mkdir(exist_ok=True)
    shutil.copy2(
        root / "frontend/src/assets/librarium-symbols.svg", project / "brand/librarium-symbols.svg"
    )

    missing_font = None
    if fonts_dir and (fonts_dir / FONT).is_file():
        (project / "fonts").mkdir(exist_ok=True)
        shutil.copy2(fonts_dir / FONT, project / "fonts" / FONT)
    else:
        missing_font = FONT

    uploads = []
    for group, path in ASSETS:
        data = (root / path).read_bytes()
        uploads.append(
            {
                "group": group,
                "name": path.rsplit("/", 1)[1],
                "source": path,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "type": "image/svg+xml" if path.endswith(".svg") else "image/png",
            }
        )
    (out / "uploads.json").write_text(json.dumps(uploads, indent=2) + "\n")

    librarium = next(t for t in themes if t["id"] == LAUNCH_THEMES[0])
    design_md = _design_md_colors(root)
    drift = [
        f"{role}: DESIGN.md {value} != themes.ts {librarium['colors'].get(role)}"
        for role, value in design_md.items()
        if librarium["colors"].get(role) != value
    ]
    used = set(re.findall(r"var\(--([\w-]+)", css))
    unknown = sorted(used - set(ROLES) - set(BRAND_ROLES) - LOCAL_VARIABLES)
    failing = [
        f"{theme['name']}: {fg} on {bg} {contrast(theme['colors'][fg], theme['colors'][bg]):.2f}"
        for theme in themes
        for fg, bg, minimum in CONTRAST_PAIRS
        if contrast(theme["colors"][fg], theme["colors"][bg]) < minimum
    ]
    report = {
        "out": str(project),
        "themes": len(themes),
        "missing_font": missing_font,
        "design_md_drift": drift,
        "unknown_css_variables": unknown,
        "contrast_below_floor": failing,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--out", type=Path, default=root / "design-system/build")
    parser.add_argument(
        "--fonts-dir",
        type=Path,
        default=root / "frontend/node_modules/@fontsource-variable/literata/files",
        help="installed @fontsource-variable/literata files directory",
    )
    args = parser.parse_args()
    print(json.dumps(build(root, args.out, args.fonts_dir), indent=2))


if __name__ == "__main__":
    main()
