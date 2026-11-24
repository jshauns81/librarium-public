import base64
import hashlib
import os
import sqlite3
import struct
import zlib
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

VERSION = "2026.10.25.1"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1cAAAAASUVORK5CYII="
)
DIGEST = hashlib.sha256(PNG).hexdigest()
SCHEMA = Path(__file__).parent / "fixtures/blc-schema.sql"
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAADAAIBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAACP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AP7//2Q=="
)
JPEG_PROGRESSIVE = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwg"
    "JC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wgARCAADAAIDASIAAhEBAxEB/8QA"
    "FQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAGfg//E"
    "ABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAQUCf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMB"
    "AT8Bf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Bf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/"
    "2gAIAQEABj8Cf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8hf//aAAwDAQACAAMAAAAQA//E"
    "ABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQMBAT8Qf//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIB"
    "AT8Qf//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8Qf//Z"
)
GIF = base64.b64decode("R0lGODdhAgADAIAAAAAAAAAAACwAAAAAAgADAAAIBgABCBwYEAA7")
WEBP = base64.b64decode("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoCAAMAAUAmJaQAA3AA/v02aAA=")
WEBP_LOSSLESS = base64.b64decode("UklGRhoAAABXRUJQVlA4TA4AAAAvAYAAAAcQEf0PRET/Aw==")
WEBP_EXTENDED = base64.b64decode(
    "UklGRkYAAABXRUJQVlA4WAoAAAAQAAAAAQAAAgAAQUxQSAcAAAAAAAAAAAAAAFZQOCAYAAAA"
    "MAEAnQEqAgADAAFAJiWkAANwAP79NmgA"
)


def png(width, height):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    compressor = zlib.compressobj()
    row = bytes(1 + (width + 7) // 8)
    body = b"".join(compressor.compress(row) for _ in range(height)) + compressor.flush()
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
        + chunk(b"IDAT", body)
        + chunk(b"IEND", b"")
    )


def test_jpeg_frame_after_large_metadata_uses_bounded_marker_traversal():
    from librarium import catalogue_covers

    segment = b"\xff\xe1\xff\xff" + bytes(65533)
    raw = JPEG[:2] + segment * 5 + JPEG[2:]
    assert catalogue_covers.raster_dimensions(raw, "image/jpeg") == (2, 3)
    with pytest.raises(ValueError):
        catalogue_covers.raster_dimensions(raw[:300000], "image/jpeg")
    with pytest.raises(ValueError):
        catalogue_covers.raster_dimensions(
            JPEG[:2] + b"\xff\xe1\x00\x02" * 70000 + JPEG[2:], "image/jpeg"
        )


def replace_cover(covers, raw, media_type, width=1, height=1):
    path, blob = covers
    digest = hashlib.sha256(raw).hexdigest()
    target = blob.parent.parent / digest[:2] / digest
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(raw)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "UPDATE work_cover SET sha256=?,media_type=?,width=?,height=?",
            (digest, media_type, width, height),
        )


@pytest.fixture
def covers(tmp_path, settings):
    root = tmp_path / "catalogue"
    root.mkdir()
    path = root / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (VERSION,))
        db.execute("INSERT INTO work(id, title) VALUES ('w_fixture', 'Fixture Cover')")
        db.execute("INSERT INTO work(id, title) VALUES ('w_uncovered', 'Fixture Without Cover')")
        db.execute(
            "INSERT INTO work_cover VALUES ('w_fixture', ?, ?, 1, 1, 'image/png')",
            ("https://untrusted.invalid/not-a-fetch-target.png", DIGEST),
        )
    (root / "current").write_text(VERSION)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = str(tmp_path / "covers")
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    blob = tmp_path / "covers" / DIGEST[:2] / DIGEST
    blob.parent.mkdir(parents=True)
    blob.write_bytes(PNG)
    return path, blob


def pin(client):
    value = client.get("/api/catalogue").json()
    return {"version": value["version"], "sha256": value["sha256"]}


def image_url(client):
    value = client.get("/api/catalogue/works/w_fixture", pin(client)).json()
    return value["cover"]["url"]


def test_cover_metadata_is_pinned_and_same_origin(client, covers):
    path, blob = covers
    token = pin(client)
    before = path.read_bytes(), blob.read_bytes()
    detail = client.get("/api/catalogue/works/w_fixture", token).json()
    cover = detail["cover"]
    url = cover.pop("url")
    assert cover == {"sha256": DIGEST, "width": 1, "height": 1, "media_type": "image/png"}
    assert url.startswith(f"/api/catalogue/covers/w_fixture/{DIGEST}?")
    assert parse_qs(urlsplit(url).query) == {k: [v] for k, v in token.items()}
    listing = client.get("/api/catalogue/works", token).json()
    assert listing["works"][0]["cover"] == {**cover, "url": url}
    assert listing["works"][1]["cover"] is None
    assert detail["snapshot"]["sha256"] == token["sha256"]
    assert (path.read_bytes(), blob.read_bytes()) == before
    assert "untrusted.invalid" not in str(detail)


def test_batch_is_separate_from_lf_and_omits_unavailable_entries(client, covers):
    token = pin(client)
    reply = client.get(
        "/api/catalogue/covers", {**token, "work": ["w_fixture", "w_uncovered", "w_unknown"]}
    )
    assert reply.status_code == 200
    data = reply.json()
    assert data["snapshot"]["sha256"] == token["sha256"]
    assert set(data["covers"]) == {"w_fixture"}
    assert data["covers"]["w_fixture"]["url"] == image_url(client)


def test_unconfigured_local_cover_directory_keeps_catalogue_working(client, covers, settings):
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = ""
    token = pin(client)
    assert client.get("/api/catalogue/works/w_fixture", token).json()["cover"] is None
    assert client.get("/api/catalogue/covers", {**token, "work": "w_fixture"}).json() == {
        "snapshot": {**token, "fixture": True},
        "covers": {},
    }


@pytest.mark.parametrize(
    "schema", ["DROP TABLE work_cover", "ALTER TABLE work_cover RENAME COLUMN sha256 TO broken"]
)
def test_absent_or_unsupported_optional_table_keeps_catalogue_working(client, covers, schema):
    path, _ = covers
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(schema)
    token = pin(client)
    assert client.get("/api/catalogue/works/w_fixture", token).json()["cover"] is None
    assert client.get("/api/catalogue/works", token).status_code == 200
    assert (
        client.get("/api/catalogue/covers", {**token, "work": "w_fixture"}).json()["covers"] == {}
    )


@pytest.mark.parametrize(
    "column,value",
    [
        ("sha256", "not-a-digest"),
        ("sha256", "../" + "a" * 61),
        ("width", 40_000_001),
        ("width", 20_001),
        ("height", "bad"),
        ("media_type", "image/svg+xml"),
        ("media_type", "image/png\r\nInjected: true"),
    ],
)
def test_invalid_optional_metadata_is_not_admitted(client, covers, column, value):
    path, _ = covers
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f"UPDATE work_cover SET {column}=?", (value,))
    assert client.get("/api/catalogue/works/w_fixture", pin(client)).json()["cover"] is None


def test_only_verified_original_local_bytes_are_served(client, covers):
    reply = client.get(
        image_url(client), HTTP_AUTHORIZATION="Bearer private", HTTP_COOKIE="private=value"
    )
    assert reply.status_code == 200
    assert reply.content == PNG
    assert reply["Content-Type"] == "image/png"
    assert reply["ETag"] == f'"{DIGEST}"'
    assert reply["Content-Length"] == str(len(PNG))
    assert "private" in reply["Cache-Control"] and "immutable" in reply["Cache-Control"]
    assert reply["X-Content-Type-Options"] == "nosniff"
    assert reply["Cross-Origin-Resource-Policy"] == "same-origin"
    assert reply["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "changed",
        "empty",
        "directory",
        "fifo",
        "file_symlink",
        "prefix_symlink",
        "root_symlink",
    ],
)
def test_unavailable_or_unsafe_local_files_fail_independently(
    client, covers, settings, tmp_path, problem
):
    path, blob = covers
    url = image_url(client)
    original = tmp_path / "original"
    original.write_bytes(PNG)
    if problem == "missing":
        blob.unlink()
    elif problem == "changed":
        blob.write_bytes(PNG + b"changed")
    elif problem == "empty":
        blob.write_bytes(b"")
    elif problem == "directory":
        blob.unlink()
        blob.mkdir()
    elif problem == "fifo":
        blob.unlink()
        os.mkfifo(blob)
    elif problem == "file_symlink":
        blob.unlink()
        blob.symlink_to(original)
    elif problem == "prefix_symlink":
        blob.unlink()
        blob.parent.rmdir()
        blob.parent.symlink_to(tmp_path, target_is_directory=True)
    elif problem == "root_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(blob.parent.parent, target_is_directory=True)
        settings.LIBRARIUM_CATALOGUE_COVER_DIR = str(alias)
    reply = client.get(url)
    assert reply.status_code == 404
    assert reply.json() == {"error": "Catalogue cover is unavailable"}
    assert reply["Cache-Control"] == "no-store"
    assert client.get("/api/catalogue/works", pin(client)).status_code == 200
    assert path.is_file()


def test_raster_signature_must_match_even_a_pinned_digest(client, covers):
    path, blob = covers
    payload = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    digest = hashlib.sha256(payload).hexdigest()
    target = blob.parent.parent / digest[:2] / digest
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(payload)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work_cover SET sha256=?", (digest,))
    assert client.get(image_url(client)).status_code == 404


def test_file_bytes_have_a_hard_cap(client, covers, monkeypatch):
    from librarium import catalogue_covers

    url = image_url(client)
    monkeypatch.setattr(catalogue_covers, "MAX_BODY", len(PNG) - 1)
    assert client.get(url).status_code == 404
    assert client.get("/api/catalogue/works/w_fixture", pin(client)).json()["cover"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"work": []},
        {"work": ["w_fixture"] * 25},
        {"work": ["../bad"]},
        {"work": ["w_fixture"], "url": "http://bad"},
    ],
)
def test_batch_rejects_unbounded_or_unsupported_queries(client, covers, extra):
    assert client.get("/api/catalogue/covers", {**pin(client), **extra}).status_code == 400


def test_image_requires_matching_pin_digest_work_and_known_metadata(client, covers):
    url = image_url(client)
    assert client.get(url.replace(DIGEST, "a" * 64, 1)).status_code == 404
    assert client.get(url.replace("w_fixture", "w_unknown")).status_code == 404
    assert client.get(url.split("?")[0]).status_code == 400
    assert client.get(url + "&url=http://bad").status_code == 400
    assert client.get(url + "&version=" + VERSION).status_code == 400
    token = pin(client)
    assert client.get(url.replace(token["sha256"], "b" * 64)).status_code == 409
    assert client.post(url).status_code == 405


def test_disabled_directory_refuses_old_image_requests(client, covers, settings):
    url = image_url(client)
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = ""
    assert client.get(url).status_code == 503


def test_full_worker_admission_or_network_is_not_needed_for_cover_reads(
    client, covers, monkeypatch
):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Cover reads must never connect to the network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert client.get(image_url(client)).content == PNG
    assert (
        client.get("/api/catalogue/covers", {**pin(client), "work": "w_fixture"}).status_code == 200
    )


def test_busy_readers_fail_promptly_and_release_capacity(client, covers):
    from librarium import catalogue_covers

    url = image_url(client)
    for _ in range(4):
        assert catalogue_covers.SLOTS.acquire(blocking=False)
    try:
        reply = client.get(url)
        assert reply.status_code == 503
        assert reply.json() == {"error": "Catalogue cover service is busy"}
    finally:
        for _ in range(4):
            catalogue_covers.SLOTS.release()
    assert client.get(url).status_code == 200


def test_read_budget_expires_without_serving_partial_bytes(client, covers, monkeypatch):
    from librarium import catalogue_covers

    url = image_url(client)
    monkeypatch.setattr(catalogue_covers, "TOTAL_SECONDS", -1)
    result = client.get(url)
    assert result.status_code == 404
    assert result.json() == {"error": "Catalogue cover is unavailable"}


@pytest.mark.parametrize(
    "media,raw,width,height",
    [
        ("image/png", PNG, 1, 1),
        ("image/jpeg", JPEG, 2, 3),
        ("image/jpeg", JPEG_PROGRESSIVE, 2, 3),
        ("image/gif", GIF, 2, 3),
        ("image/gif", GIF[:19] + b"\x21\xfe\x04note\x00" + GIF[19:], 2, 3),
        ("image/gif", GIF[:-1] + GIF[19:], 2, 3),
        ("image/gif", b"GIF89a" + GIF[6:], 2, 3),
        ("image/webp", WEBP, 2, 3),
        ("image/webp", WEBP_LOSSLESS, 2, 3),
        ("image/webp", WEBP_EXTENDED, 2, 3),
    ],
    ids=[
        "png",
        "jpeg-baseline",
        "jpeg-progressive",
        "gif",
        "gif-comment",
        "gif-multiple-frames",
        "gif89a",
        "webp-lossy",
        "webp-lossless",
        "webp-extended",
    ],
)
def test_valid_raster_headers_match_the_pin_and_serve_original_bytes(
    client, covers, media, raw, width, height
):
    replace_cover(covers, raw, media, width, height)
    result = client.get(image_url(client))
    assert result.status_code == 200
    assert result.content == raw
    assert result["Content-Type"] == media


@pytest.mark.parametrize(
    "media,raw",
    [
        ("image/png", png(2, 3)),
        ("image/png", png(10_000, 10_000)),
        ("image/png", png(20_001, 1)),
        ("image/jpeg", JPEG),
        ("image/gif", GIF),
        ("image/webp", WEBP),
        ("image/webp", WEBP_LOSSLESS),
        ("image/webp", WEBP_EXTENDED),
    ],
    ids=[
        "tiny-png-mismatch",
        "100-megapixel-png",
        "too-wide-png",
        "jpeg",
        "gif",
        "vp8",
        "vp8l",
        "vp8x",
    ],
)
def test_actual_dimensions_cannot_bypass_pinned_metadata(client, covers, media, raw):
    replace_cover(covers, raw, media)
    result = client.get(image_url(client))
    assert result.status_code == 404
    assert result.json() == {"error": "Catalogue cover is unavailable"}
    assert result["Cache-Control"] == "no-store"
    assert client.get("/api/catalogue/works/w_fixture", pin(client)).status_code == 200


@pytest.mark.parametrize(
    "media,raw",
    [
        ("image/png", PNG[:8]),
        ("image/png", PNG[:32]),
        ("image/png", PNG[:11] + b"\x0c" + PNG[12:]),
        ("image/png", PNG[:12] + b"IDAT" + PNG[16:]),
        ("image/png", PNG[:29] + b"\0\0\0\0" + PNG[33:]),
        ("image/jpeg", b"\xff\xd8\xff"),
        ("image/jpeg", b"\xff\xd8\xff\xe0\x00\x01" + JPEG[2:]),
        ("image/jpeg", b"\xff\xd8\xff\xe0\xff\xff" + JPEG[2:]),
        ("image/jpeg", b"\xff\xd8\xff\xda\x00\x02" + JPEG[2:]),
        ("image/jpeg", JPEG.replace(b"\xff\xc0", b"\xff\xc3")),
        ("image/jpeg", JPEG[: JPEG.index(b"\xff\xc0") + 10]),
        ("image/gif", b"GIF89a"),
        ("image/gif", GIF[:12]),
        ("image/gif", GIF[:28]),
        ("image/gif", GIF[:10] + b"\x87" + GIF[11:]),
        ("image/gif", GIF[:-2]),
        ("image/gif", GIF[:24] + b"\x10\x27\x10\x27" + GIF[28:]),
        ("image/gif", GIF[:-1] + GIF[19:24] + b"\x10\x27\x10\x27" + GIF[28:]),
        ("image/gif", GIF[:19] + b"\x21\xf9\x03abc\x00" + GIF[19:]),
        ("image/webp", b"RIFFxxxxWEBP"),
        ("image/webp", WEBP[:29]),
        ("image/webp", WEBP[:20] + b"\x31" + WEBP[21:]),
        ("image/webp", WEBP[:23] + b"bad" + WEBP[26:]),
        ("image/webp", WEBP_LOSSLESS[:20] + b"\x00" + WEBP_LOSSLESS[21:]),
        ("image/webp", WEBP_EXTENDED[:20] + b"\x02" + WEBP_EXTENDED[21:]),
        ("image/webp", WEBP_EXTENDED[:24] + b"\0\0\0" + WEBP_EXTENDED[27:]),
    ],
    ids=[
        "png-signature-only",
        "png-truncated-header",
        "png-wrong-chunk-length",
        "png-wrong-chunk-kind",
        "png-bad-crc",
        "jpeg-truncated-marker",
        "jpeg-invalid-segment-length",
        "jpeg-oversized-segment",
        "jpeg-invalid-scan",
        "jpeg-unsupported-frame",
        "jpeg-truncated-frame",
        "gif-truncated-signature",
        "gif-truncated-screen",
        "gif-truncated-image",
        "gif-truncated-color-table",
        "gif-missing-trailer",
        "gif-oversized-frame",
        "gif-oversized-second-frame",
        "gif-bad-control-block",
        "webp-truncated-riff",
        "webp-truncated-frame",
        "webp-bad-frame-tag",
        "webp-bad-frame-signature",
        "webp-bad-lossless-signature",
        "webp-extended-flags",
        "webp-zero-dimensions",
    ],
)
def test_invalid_or_truncated_dimension_headers_fail_only_the_cover(client, covers, media, raw):
    replace_cover(
        covers, raw, media, 1 if media == "image/png" else 2, 1 if media == "image/png" else 3
    )
    assert client.get(image_url(client)).status_code == 404
    assert client.get("/api/catalogue/works", pin(client)).status_code == 200


@pytest.mark.parametrize("width,height", [(0, 1), (1, 0), (20_001, 1), (10_000, 10_000)])
def test_actual_raster_dimensions_have_independent_size_and_pixel_caps(width, height):
    from librarium import catalogue_covers

    with pytest.raises(ValueError):
        catalogue_covers.raster_dimensions(png(width, height), "image/png")


def test_raster_dimensions_accept_the_exact_side_and_pixel_limits():
    from librarium import catalogue_covers

    assert catalogue_covers.raster_dimensions(png(20_000, 2_000), "image/png") == (20_000, 2_000)


def test_dimension_header_traversal_is_bounded(client, covers, monkeypatch):
    from librarium import catalogue_covers

    raw = JPEG[:2] + b"\xff\xe1\x00\x02" * 32 + JPEG[2:]
    replace_cover(covers, raw, "image/jpeg", 2, 3)
    url = image_url(client)
    monkeypatch.setattr(catalogue_covers, "MAX_HEADER", 64)
    assert client.get(url).status_code == 404
    assert client.get("/api/catalogue/works/w_fixture", pin(client)).status_code == 200


def test_large_pixel_count_is_omitted_without_hiding_the_work(client, covers):
    path, _ = covers
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work_cover SET width=10000,height=10000")
    result = client.get("/api/catalogue/works/w_fixture", pin(client))
    assert result.status_code == 200
    assert result.json()["cover"] is None


def test_batch_requires_exact_pin_and_accepts_twenty_four_ids(client, covers):
    token = pin(client)
    query = {**token, "work": [f"w_fixture_{i}" for i in range(24)]}
    assert client.get("/api/catalogue/covers", query).status_code == 200
    assert client.get("/api/catalogue/covers", {"work": "w_fixture"}).status_code == 400
    assert client.get("/api/catalogue/covers", {**query, "sha256": "f" * 64}).status_code == 409
    assert (
        client.get("/api/catalogue/covers", {**query, "version": [VERSION, VERSION]}).status_code
        == 400
    )
    assert client.post("/api/catalogue/covers", query).status_code == 405


@pytest.mark.parametrize("work,digest", [("bad", DIGEST), ("w_fixture", "BAD")])
def test_invalid_path_identities_fail_before_local_io(client, covers, work, digest):
    result = client.get(f"/api/catalogue/covers/{work}/{digest}", pin(client))
    assert result.status_code == 400
