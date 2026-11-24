"""Ported cover-facts cases plus hostile raster and strict threshold regressions."""

import io
import random

import pytest
from librarium import cover_facts
from PIL import Image, ImageDraw


def jpeg(size=(1000, 1200), *, comment=None, art=False, blank=False, kind="JPEG"):
    image = Image.new("RGB", size, (40, 60, 90))
    if art:
        rng = random.Random(7)
        small = Image.frombytes("RGB", (120, 160), rng.randbytes(120 * 160 * 3))
        image = small.resize(size)
    elif not blank:
        ImageDraw.Draw(image).rectangle((0, size[1] // 3, size[0], size[1] // 2), fill="white")
    out = io.BytesIO()
    image.save(out, kind, **({"comment": comment} if comment else {}))
    return out.getvalue()


@pytest.mark.parametrize("size", [(590, 750), (1500, 1500)])
def test_calibre_comment_at_arbitrary_dimensions(size):
    facts = cover_facts.inspect_cover(jpeg(size, comment=b"Generated cover: calibre 7.10"))
    assert facts["placeholder"] and facts["detector"] == cover_facts.POLICY
    assert "generated" in facts["reasons"]
    assert (facts["width"], facts["height"]) == size
    assert len(facts["sha256"]) == 64


@pytest.mark.parametrize(
    "size,art,expected",
    [((1200, 1600), False, True), ((1000, 1500), False, False), ((1200, 1600), True, False)],
)
def test_ported_dimension_specific_flatness(size, art, expected):
    assert cover_facts.inspect_cover(jpeg(size, art=art))["placeholder"] is expected


@pytest.mark.parametrize(
    "size,reasons",
    [
        ((999, 1200), ["width_below_1000"]),
        ((1000, 1199), ["height_below_1200"]),
        ((1000, 1200), []),
        ((1000, 1000), ["height_below_1200"]),
    ],
)
def test_separate_strict_floors_and_square_art(size, reasons):
    assert cover_facts.inspect_cover(jpeg(size, art=True))["reasons"] == reasons


def test_blank_is_a_separate_verdict():
    facts = cover_facts.inspect_cover(jpeg(blank=True))
    assert facts["blank"] and not facts["placeholder"] and facts["reasons"] == ["blank"]


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"bad image", "unreadable"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "unsupported"),
        (b"x" * (16 * 1024 * 1024 + 1), "oversize"),
    ],
    ids=["corrupt", "svg", "oversize"],
)
def test_unknowns_are_never_missing(raw, code):
    facts = cover_facts.inspect_cover(raw)
    assert facts["status"] == "unresolved" and facts["error"] == code
    assert facts["reasons"] == []


def test_animation_and_pixel_budget():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(
        out, "GIF", save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")], duration=100
    )
    assert cover_facts.inspect_cover(out.getvalue())["error"] == "animated"
    assert cover_facts.inspect_cover(jpeg((5001, 5000), blank=True))["error"] == "oversize"


def test_corrupt_pixels_with_valid_header_are_not_good_art():
    raw = jpeg(art=True)
    assert cover_facts.inspect_cover(raw[: len(raw) // 2])["status"] == "unresolved"
