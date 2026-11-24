"""Fresh raster child: canonical output removes EXIF, comments and other metadata."""

import base64
import io
import json
import os
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
from librarium.cover_facts import MAX_BYTES
from librarium.cover_process import measure, sandbox
from librarium.cover_source_rules import fingerprint, problem
from librarium.inspection_process import _read_header, parent_guard


def child():
    from PIL import Image, ImageCms

    header = _read_header(1024)
    parent_guard(header["parent_pid"])
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sandbox()
    if type(header["size"]) is not int or not 6000 <= header["size"] <= MAX_BYTES:
        raise ValueError
    raw = sys.stdin.buffer.read(header["size"] + 1)
    if len(raw) != header["size"]:
        raise ValueError
    facts = measure(raw)
    if facts["status"] != "known" or facts["placeholder"] or facts["blank"]:
        raise ValueError
    with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG", "GIF", "WEBP"]) as original:
        if problem(original):
            raise ValueError
        # A new image owns pixels only; source metadata cannot enter the derivative.
        image = Image.new("RGB", original.size)
        profile = original.info.get("icc_profile")
        if profile:
            converted = ImageCms.profileToProfile(
                original,
                ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
        else:
            converted = original.convert("RGB")
        if converted is None:
            raise ValueError
        image.paste(converted)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=92)
        data = out.getvalue()
        if len(data) > MAX_BYTES:
            raise ValueError
        print(
            json.dumps(
                {
                    "data": base64.b64encode(data).decode(),
                    "width": image.width,
                    "height": image.height,
                    "fingerprint": fingerprint(image),
                },
                allow_nan=False,
            )
        )


if __name__ == "__main__":
    try:
        child()
    except Exception:  # noqa: BLE001 -- Raster child exposes only a safe failure exit.
        os._exit(3)
