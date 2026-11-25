"""Synthetic EPUBs only; fixtures contain no library or upstream book bytes."""

import builtins
import hashlib
import io
import json
import os
import socket
import struct
import subprocess
import warnings
import zipfile
from dataclasses import replace

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES

OPF = "http://www.idpf.org/2007/opf"
XHTML = "http://www.w3.org/1999/xhtml"
OPS = "http://www.idpf.org/2007/ops"


def page(body):
    return f'<html xmlns="{XHTML}" xmlns:epub="{OPS}"><body>{body}</body></html>'.encode()


def fixture_parts():
    return [
        ("mimetype", b"application/epub+zip"),
        (
            "META-INF/container.xml",
            (
                b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                b'<rootfiles><rootfile full-path="EPUB/book.opf" '
                b'media-type="application/oebps-package+xml"/></rootfiles></container>'
            ),
        ),
        (
            "EPUB/book.opf",
            f'<package xmlns="{OPF}" version="3.0" unique-identifier="uid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="uid">urn:synthetic:epub</dc:identifier>'
            "<dc:title>A synthetic volume</dc:title><dc:language>en</dc:language></metadata>"
            '<manifest><item id="second" href="second.xhtml" '
            'media-type="application/xhtml+xml"/>'
            '<item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
            'properties="nav"/><item id="map" href="map.svg" media-type="image/svg+xml"/>'
            '</manifest><spine><itemref idref="first"/><itemref idref="second" '
            'linear="no"/></spine></package>'.encode(),
        ),
        (
            "EPUB/first.xhtml",
            page(
                '<h1 id="one">Chapter 1</h1><p>Unique synthetic story sentence.</p>'
                '<img src="map.svg#map" alt=""/><a href="second.xhtml#two">Next</a>'
            ),
        ),
        ("EPUB/second.xhtml", page('<h1 id="two">Chapter 2</h1><p>Invented ending.</p>')),
        (
            "EPUB/nav.xhtml",
            page(
                '<nav epub:type="toc"><ol><li><a href="first.xhtml#one">One</a>'
                '<ol><li><a href="second.xhtml#two">Two</a></li></ol></li></ol></nav>'
            ),
        ),
        ("EPUB/map.svg", b'<svg xmlns="http://www.w3.org/2000/svg" id="map"/>'),
    ]


def archive(parts=None, *, compression=zipfile.ZIP_STORED, mime_compression=None):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w") as zipped:
            for name, body in fixture_parts() if parts is None else parts:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = (
                    mime_compression
                    if name == "mimetype" and mime_compression is not None
                    else zipfile.ZIP_STORED
                    if name == "mimetype"
                    else compression
                )
                zipped.writestr(info, body)
    return stream.getvalue()


def changed(name, old, new):
    return [
        (path, body.replace(old, new) if path == name else body) for path, body in fixture_parts()
    ]


def inspect(data, **kwargs):
    from librarium.epub_inspection import inspect_bytes

    return inspect_bytes(data, hashlib.sha256(data).hexdigest(), **kwargs)


def codes(result):
    return {finding["code"] for finding in result["findings"]}


def test_clean_structure_preserves_manifest_spine_navigation_order_and_honest_limits():
    data = archive()
    result = inspect(data)
    assert result["structural_check"] == "passed"
    assert result["inspection_complete"] is True
    assert result["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert result["expected_sha256"] == result["source_sha256"]
    assert result["policy"]["version"] == "librarium.epub-structure.v11"
    assert result["upstream"]["revision"] == "a2a3692c3d864e133f5d7b80ed71c9983e810432"
    assert [item["id"] for item in result["manifest"]] == ["second", "first", "nav", "map"]
    assert [item["idref"] for item in result["spine"]] == ["first", "second"]
    assert [item["linear"] for item in result["spine"]] == ["yes", "no"]
    assert [item["fragment"] for item in result["navigation"]["entries"]] == ["one", "two"]
    assert result["epubcheck"] == "not_run"
    assert result["content_acceptance"] == "not_checked"
    assert result["ready"] is False
    serialized = json.dumps(result)
    for forbidden in [
        "Unique synthetic story",
        "Invented ending",
        "source_path",
        "repair",
        "ownership",
    ]:
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "member,old,new,code",
    [
        ("EPUB/first.xhtml", b"map.svg#map", b"lost.svg", "missing_link_resource"),
        ("EPUB/first.xhtml", b"second.xhtml#two", b"second.xhtml#absent", "missing_link_fragment"),
        ("EPUB/nav.xhtml", b"first.xhtml#one", b"first.xhtml#absent", "missing_link_fragment"),
        ("EPUB/book.opf", b'href="map.svg"', b'href="lost.svg"', "missing_manifest_resource"),
        ("EPUB/book.opf", b'idref="first"', b'idref="absent"', "missing_spine_manifest_id"),
        ("EPUB/book.opf", b'properties="nav"', b'properties=""', "missing_navigation"),
        ("EPUB/nav.xhtml", b'<nav epub:type="toc">', b"<section>", "invalid_xml"),
        ("EPUB/book.opf", b'id="second"', b'id="first"', "duplicate_manifest_id"),
        (
            "EPUB/second.xhtml",
            b'id="two"',
            b'id="two"><span id="two"/></h1><h1',
            "duplicate_document_id",
        ),
    ],
)
def test_broken_structure_is_reported(member, old, new, code):
    result = inspect(archive(changed(member, old, new)))
    assert result["structural_check"] == "failed"
    assert code in codes(result)
    assert result["ready"] is False


@pytest.mark.parametrize(
    "href",
    [
        "https://example.invalid/book.xhtml",
        "//example.invalid/book.xhtml",
        "../../../escape.xhtml",
        "/home/private.xhtml",
        "file:///private.xhtml",
        "%2e%2e/%2e%2e/escape.xhtml",
        "C:%5cprivate.xhtml",
        "first.xhtml?query=1",
        "first.xhtml#one",
        "first.xhtml#",
        "first.xhtml?",
        "first%ZZ.xhtml",
        "first%252fother.xhtml",
    ],
)
def test_package_references_are_local_and_unambiguous(href):
    result = inspect(
        archive(changed("EPUB/book.opf", b'href="first.xhtml"', f'href="{href}"'.encode()))
    )
    assert "unsafe_package_reference" in codes(result)
    assert "/home/private" not in json.dumps(result)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/home/private",
        "a/../../outside",
        "C:/outside",
        "a/./b",
        "a//b",
        "a//",
        "a/%2e%2e/b",
    ],
)
def test_unsafe_zip_names_fail_without_echoing_them(name):
    data = bytearray(archive(fixture_parts() + [(name.replace("\x00", "X"), b"opaque")]))
    if "\x00" in name:
        data = data.replace(b"aXb", b"a\x00b")
    result = inspect(bytes(data))
    assert "unsafe_zip_member" in codes(result)
    assert "/home/private" not in json.dumps(result)


def test_duplicate_members_are_refused():
    result = inspect(archive(fixture_parts() + [("EPUB/book.opf", b"duplicate")]))
    assert "duplicate_zip_member" in codes(result)


@pytest.mark.parametrize(
    "parts,compression",
    [
        (fixture_parts()[1:] + fixture_parts()[:1], None),
        (fixture_parts(), zipfile.ZIP_DEFLATED),
        ([(n, b"wrong" if n == "mimetype" else b) for n, b in fixture_parts()], None),
    ],
)
def test_mimetype_must_be_correct_first_and_uncompressed(parts, compression):
    result = inspect(archive(parts, mime_compression=compression))
    assert "invalid_mimetype" in codes(result)


def test_every_member_crc_is_checked_including_unreferenced_binary():
    data = archive(fixture_parts() + [("unused.bin", b"Unreferenced checksum sentinel")])
    data = data.replace(b"Unreferenced checksum sentinel", b"Xnreferenced checksum sentinel")
    assert "zip_crc_failure" in codes(inspect(data))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_entity_declarations_never_expand_or_fetch(encoding):
    xml = '<?xml version="1.0"?><!DOCTYPE html [<!ENTITY x SYSTEM "file:///private">]>'
    xml += f'<html xmlns="{XHTML}"><body>&x;</body></html>'
    parts = [
        (n, xml.encode(encoding) if n == "EPUB/first.xhtml" else b) for n, b in fixture_parts()
    ]
    result = inspect(archive(parts))
    assert result["structural_check"] == "failed"
    assert codes(result) & {"xml_dtd_forbidden", "invalid_xml"}
    assert "/private" not in json.dumps(result)


@pytest.mark.parametrize(
    "limit,value,code",
    [
        ("max_archive_bytes", 64, "archive_bytes_limit"),
        ("max_members", 3, "archive_members_limit"),
        ("max_member_bytes", 64, "member_bytes_limit"),
        ("max_expanded_bytes", 256, "expansion_limit"),
        ("max_read_bytes", 64, "read_bytes_limit"),
        ("max_xml_nodes", 5, "xml_nodes_limit"),
        ("max_xml_depth", 2, "xml_depth_limit"),
        ("max_xml_text_chars", 4, "xml_text_limit"),
        ("max_metadata_chars", 4, "metadata_limit"),
        ("max_records", 2, "record_limit"),
    ],
)
def test_resource_limits_are_explicit_and_never_pass_as_complete(limit, value, code):
    from librarium.epub_inspection import InspectionPolicy

    result = inspect(archive(), policy=replace(InspectionPolicy(), **{limit: value}))
    assert code in codes(result)
    assert result["inspection_complete"] is False
    assert result["structural_check"] == "failed"


def test_expansion_ratio_and_forged_directory_count_are_bounded_before_member_reads():
    data = archive(
        fixture_parts() + [("padding.bin", b"a" * 100_000)], compression=zipfile.ZIP_DEFLATED
    )
    assert "expansion_ratio_limit" in codes(inspect(data))
    from librarium.epub_inspection import InspectionPolicy

    data = bytearray(archive())
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, end + 8, 1, 1)
    result = inspect(bytes(data), policy=replace(InspectionPolicy(), max_members=3))
    assert "archive_members_limit" in codes(result)


def test_findings_are_bounded_with_explicit_truncation():
    from librarium.epub_inspection import InspectionPolicy

    parts = changed(
        "EPUB/first.xhtml",
        b"</body>",
        b"".join(f'<img src="missing-{i}.png"/>'.encode() for i in range(15)) + b"</body>",
    )
    result = inspect(archive(parts), policy=replace(InspectionPolicy(), max_findings=3))
    assert len(result["findings"]) <= 3
    assert result["findings_truncated"] is True
    assert "finding_limit" in codes(result)
    assert result["structural_check"] == "failed"


def test_hash_mismatch_stops_before_zip_parsing(monkeypatch):
    from librarium.epub_inspection import inspect_bytes

    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: pytest.fail("ZIP opened"))
    result = inspect_bytes(b"not an archive", "0" * 64)
    assert codes(result) == {"source_hash_mismatch"}
    assert result["inspection_complete"] is False


def test_inspection_is_deterministic_and_has_no_filesystem_network_or_process_io(monkeypatch):
    data = archive()
    expected = inspect(data)

    def forbidden(*args, **kwargs):
        pytest.fail("Inspector attempted external I/O")

    with monkeypatch.context() as context:
        context.setattr(builtins, "open", forbidden)
        context.setattr(io, "open", forbidden)
        context.setattr(socket, "socket", forbidden)
        context.setattr(socket, "getaddrinfo", forbidden)
        context.setattr(subprocess, "Popen", forbidden)
        context.setattr(os, "open", forbidden)
        context.setattr(os, "write", forbidden)
        context.setattr(zipfile.ZipFile, "extract", forbidden)
        context.setattr(zipfile.ZipFile, "extractall", forbidden)
        assert inspect(data) == expected
        assert inspect(data) == expected
    assert hashlib.sha256(data).hexdigest() == expected["source_sha256"]


def test_linked_printed_contents_omnibus_reports_topology_without_repair_decisions():
    contents = '<h1>Contents</h1><h2><a href="first.xhtml#one">First novel</a></h2>'
    contents += '<h2><a href="second.xhtml#two">Second novel</a></h2>'
    parts = []
    for name, body in changed("EPUB/second.xhtml", b"Chapter 2", b"Chapter 1"):
        if name == "EPUB/book.opf":
            body = (
                body.replace(
                    b"</manifest>",
                    b'<item id="printed" href="printed.xhtml" '
                    b'media-type="application/xhtml+xml"/>'
                    b'<item id="stub-one" href="stub-one.xhtml" media-type="application/xhtml+xml"/>'
                    b'<item id="stub-two" href="stub-two.xhtml" media-type="application/xhtml+xml"/>'
                    b"</manifest>",
                )
                .replace(b"<spine>", b'<spine><itemref idref="printed"/>')
                .replace(
                    b'<itemref idref="first"', b'<itemref idref="stub-one"/><itemref idref="first"'
                )
                .replace(
                    b'<itemref idref="second"',
                    b'<itemref idref="stub-two"/><itemref idref="second"',
                )
            )
        elif name == "EPUB/nav.xhtml":
            body = body.replace(b"first.xhtml#one", b"stub-one.xhtml").replace(
                b"second.xhtml#two", b"stub-two.xhtml"
            )
        elif name in {"EPUB/first.xhtml", "EPUB/second.xhtml"}:
            body = body.replace(b"</body>", b'<h2 id="later">Chapter 2</h2></body>')
        parts.append((name, body))
    parts.append(("EPUB/printed.xhtml", page(contents)))
    parts.extend(
        [
            ("EPUB/stub-one.xhtml", page("<h1>First novel</h1>")),
            ("EPUB/stub-two.xhtml", page("<h1>Second novel</h1>")),
        ]
    )
    result = inspect(archive(parts))
    assert result["structural_check"] == "passed"
    printed = next(d for d in result["documents"] if d["path"] == "EPUB/printed.xhtml")
    assert [link["target_path"] for link in printed["links"]] == [
        "EPUB/first.xhtml",
        "EPUB/second.xhtml",
    ]
    assert [link["fragment"] for link in printed["links"]] == ["one", "two"]
    chapters = [
        h["chapter_number"]
        for d in result["documents"]
        for h in d["headings"]
        if h["chapter_number"] is not None
    ]
    assert chapters == [1, 2, 1, 2]
    assert [s["idref"] for s in result["spine"]] == [
        "printed",
        "stub-one",
        "first",
        "stub-two",
        "second",
    ]
    assert [entry["target_path"] for entry in result["navigation"]["entries"]] == [
        "EPUB/stub-one.xhtml",
        "EPUB/stub-two.xhtml",
    ]
    for forbidden in ["remove_documents", "rebuild", "novel_groups", "junk_candidates"]:
        assert forbidden not in json.dumps(result)


def test_crc_failure_after_findings_fill_the_budget_still_returns_a_bounded_report():
    from librarium.epub_inspection import InspectionPolicy

    parts = changed("EPUB/book.opf", b'href="map.svg"', b'href="lost.svg"')
    data = archive(parts + [("opaque.bin", b"Checksum sentinel")])
    data = data.replace(b"Checksum sentinel", b"Xhecksum sentinel")
    result = inspect(data, policy=replace(InspectionPolicy(), max_findings=2))
    assert result["structural_check"] == "failed"
    assert len(result["findings"]) <= 2
    assert "zip_crc_failure" in codes(result)


def test_directory_payloads_cannot_bypass_crc_inspection():
    result = inspect(archive(fixture_parts() + [("opaque/", b"hidden bytes")]))
    assert result["structural_check"] == "failed"
    assert "unsupported_zip_member" in codes(result)


def test_multiple_renditions_are_an_explicit_unsupported_case():
    parts = changed(
        "META-INF/container.xml", b"</rootfiles>", b'<rootfile full-path="other.opf"/></rootfiles>'
    )
    result = inspect(archive(parts))
    assert result["structural_check"] == "failed"
    assert "multiple_renditions_not_supported" in codes(result)


@pytest.mark.parametrize(
    "member,replacement",
    [
        (
            "META-INF/container.xml",
            (
                b'<wrong xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                b'<rootfiles><rootfile full-path="EPUB/book.opf"/></rootfiles></wrong>'
            ),
        ),
        ("EPUB/first.xhtml", b'<wrong><h1 id="one"/></wrong>'),
    ],
    ids=[
        "container-root",
        "content-root",
    ],
)
def test_wrong_xml_roots_do_not_pass_structure_checks(member, replacement):
    parts = [(n, replacement if n == member else b) for n, b in fixture_parts()]
    result = inspect(archive(parts))
    assert result["structural_check"] == "failed"
    assert codes(result) & {"invalid_container", "unexpected_document_root"}


def test_ncx_targets_include_fragment_validation_and_keep_order():
    ncx = b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
    ncx += b'<navPoint><content src="second.xhtml#two"/></navPoint>'
    ncx += b'<navPoint><content src="first.xhtml#missing"/></navPoint></navMap></ncx>'
    parts = changed("EPUB/book.opf", b'properties="nav"', b'properties=""')
    parts = [
        (
            n,
            b.replace(
                b"</manifest>",
                b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
            ),
        )
        for n, b in parts
    ]
    result = inspect(archive(parts + [("EPUB/toc.ncx", ncx)]))
    assert result["navigation"]["ncx_paths"] == ["EPUB/toc.ncx"]
    assert [e["fragment"] for e in result["navigation"]["entries"]] == ["two", "missing"]
    assert "missing_link_fragment" in codes(result)


def test_serialized_output_is_bounded_without_silently_truncating_success():
    from librarium.epub_inspection import InspectionPolicy

    parts = changed("EPUB/first.xhtml", b"</body>", b'<a href="#one">Local</a>' * 50 + b"</body>")
    result = inspect(
        archive(parts), policy=replace(InspectionPolicy(), max_output_bytes=ENVELOPE_BYTES)
    )
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= ENVELOPE_BYTES
    assert result["structural_check"] == "failed"
    assert result["inspection_complete"] is False
    assert codes(result) == {"output_bytes_limit"}


@pytest.mark.parametrize(
    "policy_change,member,old,new,code",
    [
        (
            {"max_attribute_chars": 128},
            "EPUB/first.xhtml",
            b'id="one"',
            ('id="' + "x" * 129 + '"').encode(),
            "xml_attributes_limit",
        ),
        (
            {"max_xml_attributes": 1},
            "EPUB/first.xhtml",
            b'id="one"',
            b'id="one" class="a" title="b"',
            "xml_attributes_limit",
        ),
        (
            {},
            "EPUB/first.xhtml",
            b"<body>",
            b'<body xml:base="elsewhere/">',
            "unsupported_base_reference",
        ),
        (
            {},
            "EPUB/first.xhtml",
            b"<body>",
            b'<body><base href="elsewhere/"/>',
            "unsupported_base_reference",
        ),
        (
            {},
            "EPUB/first.xhtml",
            b"second.xhtml#two",
            b"javascript:alert(1)",
            "unsafe_resource_link",
        ),
        (
            {},
            "EPUB/first.xhtml",
            b"map.svg#map",
            b"https://example.invalid/map.svg",
            "remote_resource_reference",
        ),
    ],
    ids=[
        "attribute-too-long",
        "too-many-attributes",
        "xml-base",
        "html-base",
        "javascript-link",
        "remote-resource",
    ],
)
def test_xml_and_reference_policy_rejections(policy_change, member, old, new, code):
    from librarium.epub_inspection import InspectionPolicy

    result = inspect(
        archive(changed(member, old, new)), policy=replace(InspectionPolicy(), **policy_change)
    )
    assert result["structural_check"] == "failed"
    assert code in codes(result)


def test_remote_hyperlinks_are_counted_without_echoing_or_fetching_the_url():
    parts = changed("EPUB/first.xhtml", b"second.xhtml#two", b"https://example.invalid/private")
    result = inspect(archive(parts, compression=zipfile.ZIP_DEFLATED))
    assert result["structural_check"] == "passed"
    assert result["navigation"]["external_link_count"] == 1
    assert "example.invalid" not in json.dumps(result)


@pytest.mark.parametrize(
    "data", [b"", b"not a zip", b"PK\x05\x06", b"PK\x03\x04" * 100],
    ids=[
        "empty",
        "not-zip",
        "truncated-end-record",
        "repeated-local-header",
    ],
)
def test_invalid_archives_return_findings(data):
    result = inspect(data)
    assert result["structural_check"] == "failed"
    assert codes(result) == {"invalid_zip"}


@pytest.mark.parametrize(
    "policy_kwargs",
    [
        {"max_members": 0},
        {"max_members": 2049},
        {"max_members": True},
        {"max_output_bytes": 1024},
    ],
)
def test_policy_only_accepts_explicit_integer_limits_within_hard_ceilings(policy_kwargs):
    from librarium.epub_inspection import InspectionPolicy

    with pytest.raises(ValueError):
        InspectionPolicy(**policy_kwargs)


def test_caller_type_and_pin_errors_are_distinct_from_epub_failures():
    from librarium.epub_inspection import inspect_bytes

    with pytest.raises(TypeError):
        inspect_bytes(bytearray(), "0" * 64)
    with pytest.raises(ValueError):
        inspect_bytes(b"", "BAD")
    with pytest.raises(TypeError):
        inspect_bytes(b"", "0" * 64, {})


def test_member_count_limit_is_checked_before_zipfile_allocates_entries(monkeypatch):
    from librarium.epub_inspection import InspectionPolicy

    data = archive()
    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: pytest.fail("ZIP allocated entries"))
    result = inspect(data, policy=replace(InspectionPolicy(), max_members=2))
    assert codes(result) == {"archive_members_limit"}


@pytest.mark.parametrize(
    "method,flags,mode",
    [
        (zipfile.ZIP_BZIP2, 0, 0),
        (zipfile.ZIP_STORED, 1, 0),
        (zipfile.ZIP_STORED, 0, 0o120777 << 16),
    ],
)
def test_unsupported_zip_compression_encryption_and_symlinks_fail_before_reads(method, flags, mode):
    data = bytearray(archive())
    central = data.find(b"PK\x01\x02")
    struct.pack_into("<HH", data, central + 8, flags, method)
    struct.pack_into("<L", data, central + 38, mode)
    struct.pack_into("<HH", data, 6, flags, method)
    assert inspect(bytes(data))["structural_check"] == "failed"


@pytest.mark.parametrize("name", ["a\\outside", "a\x00b"])
def test_reader_normalization_is_disclosed_without_raw_name_claims(name):
    data = bytearray(archive(fixture_parts() + [(name.replace("\x00", "X"), b"opaque")]))
    if "\x00" in name:
        data = data.replace(b"aXb", b"a\x00b")
    result = inspect(bytes(data))
    assert result["structural_check"] == "passed"
    assert result["archive_reader"]["names"] == "library_exposed"
    assert result["archive_reader"]["raw_header_conformance"] == "not_checked"
    assert result["epubcheck"] == "not_run" and result["ready"] is False


@pytest.mark.parametrize("method,flags", [(zipfile.ZIP_BZIP2, 0), (zipfile.ZIP_STORED, 1)])
def test_central_only_method_or_flags_do_not_establish_raw_header_conformance(method, flags):
    data = bytearray(archive())
    central = data.find(b"PK\x01\x02")
    struct.pack_into("<HH", data, central + 8, flags, method)
    result = inspect(bytes(data))
    assert result["structural_check"] == "passed"
    assert result["archive_reader"]["metadata"] == "library_exposed"
    assert result["archive_reader"]["raw_header_conformance"] == "not_checked"
    assert result["ready"] is False


def test_internal_entity_expansion_and_external_subset_are_refused_without_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("XML attempted external I/O")

    documents = [
        (
            '<!DOCTYPE html [<!ENTITY a "boom"><!ENTITY b "&a;&a;&a;">]>'
            f'<html xmlns="{XHTML}"><body>&b;</body></html>'
        ),
        (
            '<!DOCTYPE html SYSTEM "https://example.invalid/unsafe.dtd">'
            f'<html xmlns="{XHTML}"><body/></html>'
        ),
    ]
    archives = [
        archive([(n, xml.encode() if n == "EPUB/first.xhtml" else b) for n, b in fixture_parts()])
        for xml in documents
    ]
    with monkeypatch.context() as context:
        context.setattr(builtins, "open", forbidden)
        context.setattr(io, "open", forbidden)
        context.setattr(os, "open", forbidden)
        context.setattr(socket, "socket", forbidden)
        context.setattr(socket, "getaddrinfo", forbidden)
        for data in archives:
            assert "xml_dtd_forbidden" in codes(inspect(data))


def test_manifest_resource_alias_cannot_turn_the_package_into_a_story_document():
    parts = changed("EPUB/book.opf", b'href="first.xhtml"', b'href="book.opf"')
    result = inspect(archive(parts))
    assert "unexpected_document_root" in codes(result)
    assert result["structural_check"] == "failed"


@pytest.mark.parametrize("encoding", ["unknown-encoding", "shift_jis"])
def test_unsupported_xml_encodings_are_input_findings(encoding):
    document = f'<?xml version="1.0" encoding="{encoding}"?>'
    document += f'<html xmlns="{XHTML}"><body/></html>'
    parts = [(n, document.encode() if n == "EPUB/first.xhtml" else b) for n, b in fixture_parts()]
    result = inspect(archive(parts))
    assert result["structural_check"] == "failed"
    assert "invalid_xml" in codes(result)


def test_empty_unmanifested_xml_is_not_silently_skipped():
    result = inspect(archive(fixture_parts() + [("unused.xml", b"")]))
    assert result["structural_check"] == "failed"
    assert "invalid_xml" in codes(result)
