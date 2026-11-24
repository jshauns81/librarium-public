"""Optional local original-cover reads bound to admitted catalogue metadata."""

import hashlib
import os
import sqlite3
import stat
import threading
import time
import zlib
from contextlib import ExitStack, contextmanager
from urllib.parse import urlencode

from django.conf import settings

from librarium import catalogue
from librarium.library import WORK

MAX_BODY = 8 * 1024 * 1024
MAX_HEADER = 256 * 1024
MAX_SIDE = 20_000
MAX_PIXELS = 40_000_000
TOTAL_SECONDS = 3.0
MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
SLOTS = threading.BoundedSemaphore(4)


def signature(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def blob(sha256: str, *, upscaled: bool = False):
    # Open each untrusted path component relative to its already-open directory.
    with ExitStack() as stack:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root = os.open(
            settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR
            if upscaled
            else settings.LIBRARIUM_CATALOGUE_COVER_DIR,
            directory_flags,
        )
        stack.callback(os.close, root)
        prefix = os.open(sha256[:2], directory_flags, dir_fd=root)
        stack.callback(os.close, prefix)
        fd = os.open(sha256, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=prefix)
        stream = stack.enter_context(os.fdopen(fd, "rb"))
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BODY:
            raise ValueError
        yield stream, signature(info)


def metadata(db, info: dict, work_id: str, *, upscaled: bool = False) -> dict | None:
    directory = (
        settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR
        if upscaled
        else settings.LIBRARIUM_CATALOGUE_COVER_DIR
    )
    if not directory or not WORK.fullmatch(work_id):
        return None
    # Covers are an optional snapshot extension, including on legacy publishers.
    try:
        columns = {row["name"] for row in db.execute('PRAGMA table_info("work_cover")')}
        if not {"work_id", "source_url", "sha256", "width", "height", "media_type"} <= columns:
            return None
        sql = (
            (
                "SELECT substr(d.sha256,1,65), d.width, d.height, substr(d.media_type,1,50) "
                "FROM work_cover c JOIN cover_derivative d ON d.original_sha256=c.sha256 "
                "WHERE c.work_id=? AND EXISTS (SELECT 1 FROM work WHERE id=?)"
            )
            if upscaled
            else (
                "SELECT substr(sha256,1,65) sha256, width, height, substr(media_type,1,50) media_type "
                "FROM work_cover WHERE work_id=? AND EXISTS (SELECT 1 FROM work WHERE id=?)"
            )
        )
        row = db.execute(sql, (work_id, work_id)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    sha256, width, height, media_type = tuple(row)
    if (
        not isinstance(sha256, str)
        or not catalogue.DIGEST.fullmatch(sha256)
        or type(width) is not int
        or type(height) is not int
        or not dimensions_allowed(width, height)
        or media_type not in MEDIA_TYPES
    ):
        return None
    try:
        with blob(sha256, upscaled=upscaled):
            pass
    except OSError, ValueError:
        return None
    return {
        **({"upscaled": True} if upscaled else {}),
        "sha256": sha256,
        "width": width,
        "height": height,
        "media_type": media_type,
        "url": f"/api/catalogue/covers/{work_id}/{sha256}?"
        + urlencode(
            {
                "version": info["version"],
                "sha256": info["sha256"],
                **({"variant": "upscaled"} if upscaled else {}),
            }
        ),
    }


def dimensions_allowed(width: int, height: int) -> bool:
    return 0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS


def png_dimensions(raw: bytes) -> tuple[int, int]:
    if (
        len(raw) < 33
        or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        or zlib.crc32(raw[12:29]) != int.from_bytes(raw[29:33], "big")
    ):
        raise ValueError
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
    if raw[24] not in depths.get(raw[25], set()) or raw[26:28] != b"\0\0" or raw[28] > 1:
        raise ValueError
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


def jpeg_dimensions(raw: bytes) -> tuple[int, int]:
    if len(raw) > MAX_BODY or not raw.startswith(b"\xff\xd8"):
        raise ValueError
    pos = 2
    budget = MAX_HEADER
    while pos < len(raw):
        budget -= 4
        if budget < 0:
            raise ValueError
        if raw[pos] != 0xFF:
            raise ValueError
        while pos < len(raw) and raw[pos] == 0xFF:
            budget -= 1
            if budget < 0:
                raise ValueError
            pos += 1
        if pos + 3 > len(raw):
            raise ValueError
        marker = raw[pos]
        pos += 1
        length = int.from_bytes(raw[pos : pos + 2], "big")
        end = pos + length
        if length < 2 or end > len(raw):
            raise ValueError
        if marker in {0xC0, 0xC1, 0xC2}:
            if length < 11 or raw[pos + 2] != 8:
                raise ValueError
            components = raw[pos + 7]
            if components not in {1, 3, 4} or length != 8 + 3 * components:
                raise ValueError
            return (
                int.from_bytes(raw[pos + 5 : pos + 7], "big"),
                int.from_bytes(raw[pos + 3 : pos + 5], "big"),
            )
        # Only table, application and comment segments may precede a supported frame.
        if marker not in {0xC4, 0xDB, 0xDD, 0xFE} and not 0xE0 <= marker <= 0xEF:
            raise ValueError
        pos = end
    raise ValueError


def gif_dimensions(raw: bytes) -> tuple[int, int]:
    if len(raw) < 13 or raw[:6] not in {b"GIF87a", b"GIF89a"}:
        raise ValueError
    width = int.from_bytes(raw[6:8], "little")
    height = int.from_bytes(raw[8:10], "little")
    pos = 13 + (3 * (2 << (raw[10] & 7)) if raw[10] & 0x80 else 0)
    budget = MAX_HEADER - pos
    frames = 0

    def subblocks(pos: int) -> int:
        nonlocal budget
        while pos < len(raw) and budget > 0:
            size = raw[pos]
            budget -= 1
            pos += 1
            if pos + size > len(raw):
                raise ValueError
            if not size:
                return pos
            pos += size
        raise ValueError

    while pos < len(raw):
        budget -= 2
        if budget <= 0:
            raise ValueError
        if raw[pos] == 0x21:
            if pos + 2 > len(raw) or raw[pos + 1] not in {0x01, 0xF9, 0xFE, 0xFF}:
                raise ValueError
            label = raw[pos + 1]
            pos += 2
            fixed_size = {0x01: 12, 0xF9: 4, 0xFF: 11}.get(label)
            if fixed_size is not None and (pos >= len(raw) or raw[pos] != fixed_size):
                raise ValueError
            if label == 0xF9:
                if pos + 6 > len(raw) or raw[pos + 5] != 0:
                    raise ValueError
                pos += 6
            else:
                pos = subblocks(pos)
        elif raw[pos] == 0x2C and pos + 11 <= len(raw):
            left = int.from_bytes(raw[pos + 1 : pos + 3], "little")
            top = int.from_bytes(raw[pos + 3 : pos + 5], "little")
            frame_width = int.from_bytes(raw[pos + 5 : pos + 7], "little")
            frame_height = int.from_bytes(raw[pos + 7 : pos + 9], "little")
            flags = raw[pos + 9]
            pos += 10 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
            if (
                not dimensions_allowed(frame_width, frame_height)
                or left + frame_width > width
                or top + frame_height > height
                or flags & 0x18
                or pos >= len(raw)
                or not 2 <= raw[pos] <= 8
            ):
                raise ValueError
            budget -= 10 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
            pos = subblocks(pos + 1)
            frames += 1
        elif raw[pos] == 0x3B and frames and pos + 1 == len(raw):
            return width, height
        else:
            raise ValueError
    raise ValueError


def webp_dimensions(raw: bytes, body_size: int) -> tuple[int, int]:
    if (
        len(raw) < 20
        or raw[:4] != b"RIFF"
        or raw[8:12] != b"WEBP"
        or int.from_bytes(raw[4:8], "little") + 8 != body_size
        or body_size % 2
    ):
        raise ValueError
    canvas = None
    pos = 12
    while pos + 8 <= len(raw):
        kind = raw[pos : pos + 4]
        size = int.from_bytes(raw[pos + 4 : pos + 8], "little")
        pos += 8
        end = pos + size
        if end + (size & 1) > body_size:
            raise ValueError
        if kind == b"VP8X":
            if (
                pos != 20
                or size != 10
                or end > len(raw)
                or raw[pos] & 0xC3
                or raw[pos + 1 : pos + 4] != b"\0\0\0"
            ):
                raise ValueError
            # Animated WebP requires frame admission; only still images are supported here.
            canvas = (
                1 + int.from_bytes(raw[pos + 4 : pos + 7], "little"),
                1 + int.from_bytes(raw[pos + 7 : pos + 10], "little"),
            )
        elif kind in {b"VP8 ", b"VP8L"}:
            if canvas is None and pos != 20:
                raise ValueError
            if kind == b"VP8 ":
                if size < 10 or pos + 10 > len(raw):
                    raise ValueError
                tag = int.from_bytes(raw[pos : pos + 3], "little")
                if (
                    tag & 1
                    or (tag >> 1) & 7 > 3
                    or not tag & 0x10
                    or tag >> 5 > size - 10
                    or raw[pos + 3 : pos + 6] != b"\x9d\x01\x2a"
                ):
                    raise ValueError
                dimensions = (
                    int.from_bytes(raw[pos + 6 : pos + 8], "little") & 0x3FFF,
                    int.from_bytes(raw[pos + 8 : pos + 10], "little") & 0x3FFF,
                )
            else:
                if size < 5 or pos + 5 > len(raw) or raw[pos] != 0x2F:
                    raise ValueError
                bits = int.from_bytes(raw[pos + 1 : pos + 5], "little")
                if bits >> 29:
                    raise ValueError
                dimensions = 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
            if canvas is not None and canvas != dimensions:
                raise ValueError
            return dimensions
        elif canvas is None or kind in {b"ANIM", b"ANMF"}:
            raise ValueError
        pos = end + (size & 1)
    raise ValueError


def raster_dimensions(raw: bytes, media_type: str) -> tuple[int, int]:
    # Bound header traversal independently of the compressed body; never decode pixels.
    header = raw[:MAX_HEADER]
    if media_type == "image/png":
        dimensions = png_dimensions(header)
    elif media_type == "image/jpeg":
        # Skip bounded APP payloads by length; ICC/EXIF can precede the frame.
        dimensions = jpeg_dimensions(raw)
    elif media_type == "image/gif":
        # GIF frame headers follow compressed sub-blocks; skip payloads without decoding.
        dimensions = gif_dimensions(raw)
    elif media_type == "image/webp":
        dimensions = webp_dimensions(header, len(raw))
    else:
        raise ValueError
    if not dimensions_allowed(*dimensions):
        raise ValueError
    return dimensions


def read(cover: dict) -> bytes:
    if not SLOTS.acquire(blocking=False):
        raise catalogue.CatalogueError("Catalogue cover service is busy", 503)
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        with blob(cover["sha256"], upscaled=cover.get("upscaled", False)) as (stream, before):
            parts = []
            size = 0
            while chunk := stream.read(min(64 * 1024, MAX_BODY + 1 - size)):
                size += len(chunk)
                if size > MAX_BODY or time.monotonic() >= deadline:
                    raise ValueError
                parts.append(chunk)
            raw = b"".join(parts)
            if (
                signature(os.fstat(stream.fileno())) != before
                or len(raw) != before[2]
                or hashlib.sha256(raw).hexdigest() != cover["sha256"]
                or raster_dimensions(raw, cover["media_type"]) != (cover["width"], cover["height"])
                or time.monotonic() >= deadline
            ):
                raise ValueError
            return raw
    except OSError, ValueError:
        raise catalogue.CatalogueError("Catalogue cover is unavailable", 404) from None
    finally:
        SLOTS.release()
