"""Untrusted image bytes are decoded and stripped in a bounded child."""

import io

import pytest
from librarium.cover_source_image import prepare
from PIL import Image
from tests.test_cover_facts import jpeg


def test_prepared_image_strips_metadata_and_has_real_dimensions():
    raw = jpeg((600, 900), art=True)
    result = prepare(raw)
    assert (result["width"], result["height"]) == (600, 900)
    with Image.open(io.BytesIO(result["data"])) as im:
        assert not im.getexif() and "comment" not in im.info
    assert len(result["fingerprint"]["g"]) == 864


@pytest.mark.parametrize(
    "raw",
    [b"<html>not an image</html>", b"x" * 5999, jpeg((200, 300)), jpeg((120, 900), art=True)],
    ids=["html", "below-byte-floor", "blank", "wrong-aspect"],
)
def test_html_short_blank_and_wrong_aspect_rejected(raw):
    with pytest.raises(ValueError):
        prepare(raw)


def test_embedded_profile_is_converted_to_srgb_without_metadata():
    from PIL import ImageCms

    raw = jpeg((600, 900), art=True)
    with Image.open(io.BytesIO(raw)) as original:
        image = original.convert("LAB")
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
        out = io.BytesIO()
        image.save(out, "TIFF", icc_profile=profile.tobytes())
    # TIFF is deliberately not admitted, even with a valid profile.
    with pytest.raises(ValueError):
        prepare(out.getvalue())
    with Image.open(io.BytesIO(raw)) as original:
        rgb = original.convert("RGB")
        out = io.BytesIO()
        rgb.save(
            out,
            "JPEG",
            quality=95,
            icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes(),
        )
    result = prepare(out.getvalue())
    with Image.open(io.BytesIO(result["data"])) as image:
        assert not image.info.get("icc_profile")
        assert image.mode == "RGB"


def test_near_pixel_limit_art_is_admitted():
    raw = jpeg((4000, 6000), art=True)
    result = prepare(raw)
    assert (result["width"], result["height"]) == (4000, 6000)


def test_wide_gamut_profile_changes_pixels_to_srgb():
    import struct

    from PIL import ImageCms, ImageStat

    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    # Synthetic RGB primaries in an otherwise valid ICC profile, entirely in memory.
    tags = {
        profile[132 + i * 12 : 136 + i * 12].decode(): struct.unpack(
            ">II", profile[136 + i * 12 : 144 + i * 12]
        )
        for i in range(struct.unpack(">I", profile[128:132])[0])
    }
    offset, _ = tags["rXYZ"]
    for position, value in enumerate((0.60, 0.30, 0.02)):
        struct.pack_into(">i", profile, offset + 8 + position * 4, int(value * 65536))
    raw = jpeg((600, 900), art=True)
    with Image.open(io.BytesIO(raw)) as original:
        rgb = original.convert("RGB")
        out = io.BytesIO()
        rgb.save(out, "PNG", icc_profile=bytes(profile))
        expected = ImageCms.profileToProfile(
            rgb,
            ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            ImageCms.createProfile("sRGB"),
            outputMode="RGB",
        )
        # JPEG output is lossy, so compare aggregate colour with a small tolerance.
        before = ImageStat.Stat(rgb).mean
        target = ImageStat.Stat(expected).mean
    assert max(abs(a - b) for a, b in zip(before, target)) > 2
    result = prepare(out.getvalue())
    with Image.open(io.BytesIO(result["data"])) as converted:
        actual = ImageStat.Stat(converted).mean
        assert max(abs(a - b) for a, b in zip(actual, target)) < 2
        assert "icc_profile" not in converted.info
