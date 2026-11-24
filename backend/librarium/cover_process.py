"""Fresh image decoder with no ambient files, network, subprocesses or credentials."""

import io
import json
import os
import resource
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
from librarium.cover_facts import MAX_BYTES, MAX_PIXELS, POLICY, unknown
from librarium.inspection_process import _read_header, parent_guard
from librarium.python_sandbox import _import_audit, _NoLateImports, restrict_filesystem
from librarium.seccomp_sandbox import deny_network


def measure(raw):
    import hashlib

    from PIL import Image, ImageStat

    digest = hashlib.sha256(raw).hexdigest()
    if raw.lstrip().startswith(b"<"):
        return unknown("unsupported", digest)
    try:
        with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG", "GIF", "WEBP"]) as image:
            width, height = image.size
            if width * height > MAX_PIXELS or max(width, height) > 12000:
                return unknown("oversize", digest)
            if getattr(image, "n_frames", 1) != 1:
                return unknown("animated", digest)
            image.load()
            comment = image.info.get("comment") or b""
            if isinstance(comment, str):
                comment = comment.encode("utf-8", "replace")
            placeholder = b"Generated cover: calibre" in comment
            if not placeholder and (width, height) == (1200, 1600):
                small = (
                    image.convert("RGB")
                    .resize((120, 160))
                    .quantize(colors=24, method=Image.Quantize.MEDIANCUT)
                )
                counts = [int(pair[0]) for pair in (small.getcolors() or [])]
                placeholder = sum(sorted(counts, reverse=True)[:3]) / (120 * 160) >= 0.6
            blank = ImageStat.Stat(image.convert("L").resize((48, 72))).stddev[0] < 10
            reasons = []
            for reason, applies in (
                ("generated", placeholder),
                ("blank", blank),
                ("width_below_1000", width < 1000),
                ("height_below_1200", height < 1200),
            ):
                if applies:
                    reasons.append(reason)
            return {
                "status": "known",
                "error": "",
                "width": width,
                "height": height,
                "placeholder": placeholder,
                "blank": blank,
                "reasons": reasons,
                "sha256": digest,
                "detector": POLICY,
                "media_type": Image.MIME[image.format or ""],
            }
    except Image.DecompressionBombError, Image.DecompressionBombWarning:
        return unknown("oversize", digest)
    except OSError, ValueError, SyntaxError:
        return unknown("unreadable", digest)


def sandbox():
    import hashlib
    import math

    from PIL import (
        GifImagePlugin,
        Image,
        ImageStat,
        JpegImagePlugin,
        PngImagePlugin,
        WebPImagePlugin,
    )

    # Only these raster plugins are admitted; all native libraries load before isolation.
    _ = hashlib, math, ImageStat, JpegImagePlugin, PngImagePlugin, GifImagePlugin, WebPImagePlugin
    Image.init()
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    deny_network(python_child=True)
    restrict_filesystem()
    sys.meta_path.insert(0, _NoLateImports())
    sys.addaudithook(_import_audit)


def child():
    header = _read_header(1024)
    parent_guard(header["parent_pid"])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    sandbox()
    if type(header["size"]) is not int or not 0 <= header["size"] <= MAX_BYTES:
        raise ValueError
    raw = sys.stdin.buffer.read(header["size"] + 1)
    if len(raw) != header["size"]:
        raise ValueError
    sys.stdout.write(json.dumps(measure(raw), allow_nan=False))


if __name__ == "__main__":
    try:
        child()
    except Exception:  # noqa: BLE001 -- The isolated decoder exposes only a safe exit code.
        os._exit(3)
