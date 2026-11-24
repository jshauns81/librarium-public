"""Synthetic adversarial archives exercise the native reader boundary."""

import io
import struct
import zipfile
from dataclasses import replace

import pytest
from librarium.epub_inspection import InspectionPolicy
from test_epub_inspection import archive, fixture_parts
from test_epub_inspection_regressions import central_record, conflicting_zip64_directory


def read(data, **limits):
    from librarium.epub_archive import read_archive

    return read_archive(data, replace(InspectionPolicy(), **limits))


def refused(data, code=None, **limits):
    from librarium.epub_archive import ArchiveRefused

    with pytest.raises(ArchiveRefused) as error:
        read(data, **limits)
    if code:
        assert error.value.code == code
    assert str(error.value) == error.value.code


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_members_are_ordered_and_fully_validated_before_read(compression):
    parts = fixture_parts() + [("empty", b""), ("directory/", b"")]
    result = read(archive(parts, compression=compression))
    assert list(result.members) == [name for name, _ in parts]
    for name, body in parts:
        member = result.members[name]
        assert member.name == name
        assert member.size == len(body)
        assert member.is_dir() is name.endswith("/")
        assert result.read(name) == body


def test_zip64_alternate_directory_cannot_evade_count_limit():
    refused(conflicting_zip64_directory(), "archive_members_limit", max_members=1)


@pytest.mark.parametrize(
    "limit,code",
    [
        ("max_member_bytes", "member_bytes_limit"),
        ("max_expanded_bytes", "expansion_limit"),
        ("max_read_bytes", "read_bytes_limit"),
    ],
)
def test_actual_output_limits_cover_unreferenced_assets(limit, code):
    data = archive(fixture_parts() + [("asset", b"x" * 8192)])
    refused(data, code, **{limit: 4096})


def test_ratio_uses_this_members_consumed_compressed_bytes():
    parts = [
        ("mimetype", b"application/epub+zip"),
        ("padding", bytes(range(256)) * 20),
        ("bomb", b"x" * 65536),
    ]
    refused(
        archive(parts, compression=zipfile.ZIP_DEFLATED),
        "expansion_ratio_limit",
        max_expansion_ratio=100,
    )


@pytest.mark.parametrize("mutation", ["size", "crc", "directory_header", "empty_header"])
def test_native_metadata_warnings_and_unread_members_are_refused(mutation):
    parts = fixture_parts() + [("empty", b""), ("directory/", b"")]
    data = bytearray(archive(parts, compression=zipfile.ZIP_DEFLATED))
    target = (
        "directory/"
        if mutation == "directory_header"
        else "empty"
        if mutation == "empty_header"
        else "EPUB/second.xhtml"
    )
    offset = central_record(data, target)
    local = struct.unpack_from("<L", data, offset + 42)[0]
    if mutation == "size":
        size = struct.unpack_from("<L", data, offset + 24)[0]
        struct.pack_into("<L", data, offset + 24, size + 100)
    elif mutation == "crc":
        name_length, extra_length = struct.unpack_from("<HH", data, local + 26)
        data[local + 30 + name_length + extra_length] ^= 1
    else:
        data[local : local + 4] = b"NONE"
    refused(bytes(data))


@pytest.mark.parametrize(
    "parts,mime_compression",
    [
        (fixture_parts()[1:] + fixture_parts()[:1], None),
        (fixture_parts(), zipfile.ZIP_DEFLATED),
        ([("mimetype", b"wrong")] + fixture_parts()[1:], None),
    ],
)
def test_mimetype_requires_first_stored_member_with_exact_value(parts, mime_compression):
    refused(archive(parts, mime_compression=mime_compression), "invalid_mimetype")


@pytest.mark.parametrize("name", ["../unsafe", "/absolute", "a//b", "a/./b", "a%2fb"])
def test_library_exposed_unsafe_names_are_refused_without_echo(name):
    refused(archive(fixture_parts() + [(name, b"")]), "unsafe_zip_member")


def test_duplicate_library_names_are_refused():
    refused(archive(fixture_parts() + [("EPUB/map.svg", b"")]), "duplicate_zip_member")


def test_symlinks_and_other_compression_are_refused():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        zipped.writestr("mimetype", b"application/epub+zip")
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        zipped.writestr(info, b"target")
    refused(stream.getvalue(), "unsupported_zip_member")
    refused(archive(compression=zipfile.ZIP_BZIP2), "unsupported_zip_member")


def test_small_zip64_is_supported_without_a_second_reader():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, body in fixture_parts():
            with zipped.open(name, "w", force_zip64=True) as stream:
                stream.write(body)
    assert read(output.getvalue()).read("mimetype") == b"application/epub+zip"
