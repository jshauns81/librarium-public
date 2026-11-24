import json
import re
from pathlib import Path

import pytest

from scripts.design_system import LAUNCH_THEMES, build, contrast, parse_themes

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
HEX = re.compile(r"^#[0-9a-f]{6}$")


@pytest.fixture(scope="module")
def themes():
    return parse_themes((ROOT / "frontend/src/themes.ts").read_text())


def test_every_registered_theme_is_parsed_with_all_roles(themes):
    assert themes[0]["id"] == "dark"
    assert len(themes) == 2
    for theme in themes:
        assert theme["scheme"] in {"light", "dark"}
        assert len(theme["colors"]) == 16
        assert all(HEX.match(value) for value in theme["colors"].values())


def test_brand_roles_fall_back_like_the_theme_asset_plugin(themes):
    by_id = {theme["id"]: theme for theme in themes}
    assert by_id["dark"]["brand"] == {
        "ink": "#efe5d3",
        "accent": "#c9a25f",
        "wordmark": "#efe5d3",
    }
    assert by_id["light"]["brand"] == {
        "ink": "#231b16",
        "accent": "#8a6424",
        "wordmark": "#231b16",
    }


def test_contrast_matches_wcag_reference_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_build_writes_a_readable_token_file_and_reference_section(tmp_path):
    report = build(ROOT, tmp_path, fonts_dir=None)
    project = tmp_path / "project"
    tokens = json.loads((project / "tokens.json").read_text())

    assert [theme["id"] for theme in tokens["color"]["themes"]] == LAUNCH_THEMES
    names = [
        token["name"]
        for family, value in tokens.items()
        if isinstance(value, dict) and "tokens" in value
        for token in value["tokens"]
    ]
    assert len(names) == len(set(names))
    assert all(NAME.match(name) for name in names)
    assert all(token["usage"] for token in tokens["color"]["tokens"])
    assert tokens["meta"]["paths"]["tokens"] == ["frontend/src/themes.ts"]

    themes_page = (project / "1-themes.md").read_text()
    assert "Dark" in themes_page
    assert "Light" in themes_page and "Solarized" not in themes_page
    css = (project / "components/bundle.css").read_text()
    assert ".shelf-entry" in css and "</style" not in css.lower()
    ux = (ROOT / "docs/ux-standards.md").read_text()
    copied = (project / "2-ux-standards.md").read_text()
    assert copied.startswith("# UX standards\n")
    assert ux.split("\n## ", 1)[1].split("](")[0] in copied
    assert "](skills.md)" not in copied and "/blob/main/docs/skills.md)" in copied

    labels = (project / "3-status-labels.md").read_text()
    for label in ["Direct match", "No matched copy", "Partial check", "Cancelled", "Not checked"]:
        assert f"| {label} |" in labels
    assert not (project / "2-status-and-truth.md").exists()
    assert report["design_md_drift"] == []
    assert report["unknown_css_variables"] == []
