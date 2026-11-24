"""Small synthetic archives for the independently reproduced EPUB defects."""

import io
import struct
import zipfile
import zlib
from dataclasses import replace

import pytest
from librarium.epub_inspection import InspectionPolicy
from test_epub_inspection import archive, changed, codes, fixture_parts, inspect, page


@pytest.mark.parametrize(
    ("missing", "code"),
    [
        ("META-INF/container.xml", "missing_container"),
        ("EPUB/book.opf", "missing_package_document"),
    ],
)
def test_missing_required_members_keep_a_bound_report_in_the_inspection_child(missing, code):
    import hashlib

    from librarium.inspection_process import inspect_isolated

    data = archive([(path, body) for path, body in fixture_parts() if path != missing])
    digest = hashlib.sha256(data).hexdigest()
    report = inspect(data)
    assert report["structural_check"] == "failed"
    assert report["inspection_complete"] is False
    assert report["source_sha256"] == report["expected_sha256"] == digest
    assert code in codes(report)
    assert report["ready"] is False
    assert inspect_isolated(data, digest, InspectionPolicy()) == report


def central_record(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        entries = zipped.infolist()
        offset = zipped.start_dir
    for entry in entries:
        if entry.filename == name:
            return offset
        sizes = struct.unpack_from("<3H", data, offset + 28)
        offset += 46 + sum(sizes)
    raise AssertionError(name)


def conflicting_zip64_directory():
    data = bytearray(archive())
    end = data.rfind(b"PK\x05\x06")
    directory_size, directory_offset = struct.unpack_from("<LL", data, end + 12)
    result = data[:end]
    zip64_offset = len(result)
    result.extend(
        struct.pack(
            "<4sQHHLLQQQQ",
            b"PK\x06\x06",
            91,
            45,
            45,
            0,
            0,
            7,
            7,
            directory_size,
            directory_offset,
        )
    )
    decoy_offset = len(result)
    decoy = bytearray(46)
    decoy[:4] = b"PK\x01\x02"
    struct.pack_into("<3H", decoy, 28, 1, 0, 20)
    result.extend(decoy + b"a" + struct.pack("<4sLQL", b"PK\x06\x07", 0, zip64_offset, 1))
    result.extend(
        struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            1,
            1,
            len(result) - decoy_offset,
            decoy_offset,
            0,
        )
    )
    return bytes(result)


def test_alternate_directory_cannot_bypass_member_limit():
    result = inspect(
        conflicting_zip64_directory(), policy=replace(InspectionPolicy(), max_members=1)
    )
    assert result["structural_check"] == "failed"
    assert result["inspection_complete"] is False


def test_forged_directory_prefix_cannot_hide_expanded_stream():
    prefix = page('<h1 id="two">Chapter 2</h1><p>Invented ending.</p>')
    parts = [
        (name, prefix + b"A" * 8192 if name == "EPUB/second.xhtml" else body)
        for name, body in fixture_parts()
    ]
    data = bytearray(archive(parts, compression=zipfile.ZIP_DEFLATED))
    offset = central_record(data, "EPUB/second.xhtml")
    struct.pack_into("<L", data, offset + 16, zlib.crc32(prefix))
    struct.pack_into("<L", data, offset + 24, len(prefix))
    result = inspect(
        bytes(data),
        policy=replace(
            InspectionPolicy(),
            max_member_bytes=1024,
            max_expanded_bytes=4096,
            max_read_bytes=4096,
        ),
    )
    assert result["structural_check"] == "failed"


@pytest.mark.parametrize("mutation", ["overdeclared_size", "local_header"])
def test_conflicting_zip_metadata_is_refused(mutation):
    data = bytearray(archive(compression=zipfile.ZIP_DEFLATED))
    if mutation == "overdeclared_size":
        offset = central_record(data, "EPUB/second.xhtml")
        size = struct.unpack_from("<L", data, offset + 24)[0]
        struct.pack_into("<L", data, offset + 24, size + 100)
    else:
        struct.pack_into("<H", data, 8, zipfile.ZIP_DEFLATED)
        struct.pack_into("<LLL", data, 14, 0x12345678, 0, 0)
    assert inspect(bytes(data))["structural_check"] == "failed"


@pytest.mark.parametrize("media_type", ["application/xml", "text/xml", ""])
def test_generic_manifest_alias_cannot_skip_xhtml_root_validation(media_type):
    parts = changed(
        "EPUB/book.opf",
        b"<manifest>",
        f'<manifest><item id="alias" href="first.xhtml" media-type="{media_type}"/>'.encode(),
    )
    parts = [
        (name, b'<wrong id="one"/>' if name == "EPUB/first.xhtml" else body) for name, body in parts
    ]
    result = inspect(archive(parts))
    assert result["structural_check"] == "failed"


def test_navigation_role_requires_xhtml_document():
    parts = changed(
        "EPUB/book.opf",
        b'href="nav.xhtml" media-type="application/xhtml+xml"',
        b'href="nav.xhtml" media-type="application/xml"',
    )
    parts = [
        (
            name,
            body.replace(b"<html ", b"<wrong ").replace(b"</html>", b"</wrong>")
            if name == "EPUB/nav.xhtml"
            else body,
        )
        for name, body in parts
    ]
    result = inspect(archive(parts))
    assert result["structural_check"] == "failed"


def test_reference_budget_exhaustion_stops_the_inspection():
    parts = changed(
        "EPUB/first.xhtml",
        b"second.xhtml#two",
        b"second.xhtml#very_long_fragment_exceeding_limit",
    )
    result = inspect(archive(parts), policy=replace(InspectionPolicy(), max_field_chars=24))
    assert "field_limit" in codes(result)
    assert result["inspection_complete"] is False
