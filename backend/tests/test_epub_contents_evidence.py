"""Synthetic labels and hierarchy are evidence, never contents decisions."""

import hashlib
import json
from dataclasses import asdict, replace

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES, InspectionPolicy
from test_epub_inspection import archive, codes, fixture_parts, inspect, page


def parts_with(*, first=None, second=None, nav=None, ncx=None, printed=None):
    replacements = {
        "EPUB/first.xhtml": first,
        "EPUB/second.xhtml": second,
        "EPUB/nav.xhtml": nav,
    }
    parts = []
    for path, body in fixture_parts():
        if path == "EPUB/book.opf":
            items = b""
            if ncx is not None:
                items += b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            if printed is not None:
                items += (
                    b'<item id="printed" href="printed.xhtml" media-type="application/xhtml+xml"/>'
                )
            body = body.replace(b"</manifest>", items + b"</manifest>")
        parts.append((path, replacements.get(path) or body))
    if ncx is not None:
        parts.append(("EPUB/toc.ncx", ncx))
    if printed is not None:
        parts.append(("EPUB/printed.xhtml", printed))
    return parts


def ncx_page(body):
    return (
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>' + body + "</navMap></ncx>"
    ).encode()


def document(report, path):
    return next(item for item in report["documents"] if item["path"] == path)


def test_v3_preserves_document_labels_targets_and_byte_evidence():
    data = archive()
    result = inspect(data)
    assert result["policy"] == {
        "version": "librarium.epub-structure.v11",
        "limits": asdict(InspectionPolicy()),
    }
    assert set(result["policy"]["limits"]) == {
        "max_archive_bytes",
        "max_members",
        "max_member_bytes",
        "max_expanded_bytes",
        "max_expansion_ratio",
        "max_read_bytes",
        "max_name_chars",
        "max_field_chars",
        "max_metadata_chars",
        "max_xml_nodes",
        "max_xml_depth",
        "max_xml_text_chars",
        "max_xml_attributes",
        "max_attribute_chars",
        "max_records",
        "max_findings",
        "max_output_bytes",
    }
    first = document(result, "EPUB/first.xhtml")
    assert first["headings"] == [
        {
            "level": 1,
            "id": "one",
            "chapter_number": 1,
            "label": "Chapter 1",
            "source_index": 2,
        }
    ]
    assert (
        first["byte_sha256"]
        == hashlib.sha256(dict(fixture_parts())["EPUB/first.xhtml"]).hexdigest()
    )
    assert first["links"][0]["target_path"] == "EPUB/map.svg"
    assert "label" not in first["links"][0]
    assert first["links"][1] == {
        "tag": "a",
        "attribute": "href",
        "target_path": "EPUB/second.xhtml",
        "fragment": "two",
        "external": False,
        "label": "Next",
        "source_index": 5,
        "ancestors": [],
    }
    assert result["navigation"]["entries"] == [
        {
            "path": "EPUB/nav.xhtml",
            "target_path": "EPUB/first.xhtml",
            "fragment": "one",
            "label": "One",
            "kind": "nav",
            "ancestors": [],
        },
        {
            "path": "EPUB/nav.xhtml",
            "target_path": "EPUB/second.xhtml",
            "fragment": "two",
            "label": "Two",
            "kind": "nav",
            "ancestors": ["One"],
        },
    ]
    assert result["structural_check"] == "passed"


def test_linked_printed_contents_and_restarted_chapters_remain_source_observations():
    printed = page(
        '<h1>Contents</h1><h2><a href="first.xhtml#one">First <em>novel</em></a></h2>'
        '<h2><a href="second.xhtml#two">Second novel</a></h2>'
        "<p>Printed contents prose must not be captured.</p>"
    )
    data = archive(
        parts_with(
            second=page('<h1 id="two">Chapter 1</h1><p>Different invented story.</p>'),
            printed=printed,
        )
    )
    result = inspect(data)
    contents = document(result, "EPUB/printed.xhtml")
    assert [heading["label"] for heading in contents["headings"]] == [
        "Contents",
        "First novel",
        "Second novel",
    ]
    assert [
        (link["label"], link["target_path"], link["fragment"]) for link in contents["links"]
    ] == [
        ("First novel", "EPUB/first.xhtml", "one"),
        ("Second novel", "EPUB/second.xhtml", "two"),
    ]
    assert [
        document(result, path)["headings"][0]["label"]
        for path in ["EPUB/first.xhtml", "EPUB/second.xhtml"]
    ] == ["Chapter 1", "Chapter 1"]
    assert result == inspect(data)
    assert result["ready"] is False
    assert result["epubcheck"] == "not_run"
    assert result["content_acceptance"] == "not_checked"
    serialized = json.dumps(result)
    for absent in ["Printed contents prose", "Different invented story", "proposals", "repair"]:
        assert absent not in serialized


def test_nav_keeps_unlinked_parent_groups_and_linked_ancestors_in_source_order():
    nav = page(
        '<nav epub:type="landmarks"><a href="first.xhtml#one">Outside toc</a></nav>'
        '<nav epub:type="toc"><ol><li><span>Collected <em>tales</em></span><ol>'
        '<li><a href="second.xhtml#two">Second novel</a><ol>'
        '<li><a href="first.xhtml#one">Chapter 1</a></li>'
        "</ol></li><li><span>Interlude Ω</span><ol>"
        '<li><a href="second.xhtml#two">Chapter 1</a></li></ol></li>'
        '</ol></li><li><a href="first.xhtml#one">Closing</a></li></ol></nav>'
    )
    result = inspect(archive(parts_with(nav=nav)))
    assert [
        (entry["label"], entry["ancestors"], entry["fragment"])
        for entry in result["navigation"]["entries"]
    ] == [
        ("Second novel", ["Collected tales"], "two"),
        ("Chapter 1", ["Collected tales", "Second novel"], "one"),
        ("Chapter 1", ["Collected tales", "Interlude Ω"], "two"),
        ("Closing", [], "one"),
    ]
    assert result["structural_check"] == "passed"


def test_ncx_keeps_navlabel_hierarchy_and_global_navigation_source_order():
    ncx = ncx_page(
        "<navPoint><navLabel><text>Collected tales</text></navLabel>"
        '<navPoint><navLabel><text>Novel β</text></navLabel><content src="second.xhtml#two"/>'
        '<navPoint><navLabel><text>Chapter 1</text></navLabel><content src="first.xhtml#one"/>'
        "</navPoint></navPoint>"
        '<navPoint><navLabel><text>Novel α</text></navLabel><content src="first.xhtml#one"/>'
        "</navPoint></navPoint>"
    )
    result = inspect(archive(parts_with(ncx=ncx)))
    entries = result["navigation"]["entries"]
    assert [entry["kind"] for entry in entries] == ["nav", "nav", "ncx", "ncx", "ncx"]
    assert [
        (entry["label"], entry["ancestors"], entry["target_path"], entry["fragment"])
        for entry in entries[2:]
    ] == [
        ("Novel β", ["Collected tales"], "EPUB/second.xhtml", "two"),
        ("Chapter 1", ["Collected tales", "Novel β"], "EPUB/first.xhtml", "one"),
        ("Novel α", ["Collected tales"], "EPUB/first.xhtml", "one"),
    ]
    assert result["structural_check"] == "passed"


@pytest.mark.parametrize(
    "label,expected",
    [
        ("", ""),
        (" \n\t ", ""),
        ("  Café\u00a0 <em>Ω</em>\n尾  ", "Café Ω 尾"),
        ("A<em>B</em>C", "ABC"),
        ("x" * 512, "x" * 512),
    ],
    ids=[
        "empty",
        "whitespace",
        "unicode-inline",
        "adjacent-inline",
        "max-length",
    ],
)
def test_labels_preserve_empty_inline_unicode_and_boundary_values(label, expected):
    result = inspect(
        archive(
            parts_with(
                first=page(f'<h1 id="one">{label}</h1><a href="second.xhtml#two">{label}</a>'),
                nav=page(
                    f'<nav epub:type="toc"><ol><li><a href="first.xhtml#one">{label}</a>'
                    "</li></ol></nav>"
                ),
                ncx=ncx_page(
                    f"<navPoint><navLabel><text>{label}</text></navLabel>"
                    '<content src="first.xhtml#one"/></navPoint>'
                ),
            )
        )
    )
    first = document(result, "EPUB/first.xhtml")
    assert first["headings"][0]["label"] == expected
    assert first["links"][0]["label"] == expected
    assert [entry["label"] for entry in result["navigation"]["entries"]] == [expected, expected]
    assert result["structural_check"] == "passed"


@pytest.mark.parametrize("location", ["heading", "anchor", "nav_group", "ncx_label"])
def test_oversize_labels_refuse_instead_of_truncating(location):
    label = "x" * 513
    changes = {
        "heading": {"first": page(f'<h1 id="one">{label}</h1>')},
        "anchor": {"first": page(f'<h1 id="one"/><a href="second.xhtml#two">{label}</a>')},
        "nav_group": {
            "nav": page(
                f'<nav epub:type="toc"><ol><li><span>{label}</span><ol>'
                '<li><a href="first.xhtml#one">One</a></li></ol></li></ol></nav>'
            )
        },
        "ncx_label": {
            "ncx": ncx_page(
                f"<navPoint><navLabel><text>{label}</text></navLabel>"
                '<navPoint><content src="first.xhtml#one"/></navPoint></navPoint>'
            )
        },
    }
    result = inspect(archive(parts_with(**changes[location])))
    assert "field_limit" in codes(result)
    assert result["inspection_complete"] is False
    assert result["structural_check"] == "failed"
    assert label not in json.dumps(result)


def test_empty_group_labels_keep_the_source_depth_without_inventing_names():
    nav = page(
        '<nav epub:type="toc"><ol><li><span/><ol><li>'
        '<a href="first.xhtml#one"/></li></ol></li></ol></nav>'
    )
    ncx = ncx_page(
        "<navPoint><navLabel><text/></navLabel><navPoint>"
        '<content src="second.xhtml#two"/></navPoint></navPoint>'
    )
    result = inspect(archive(parts_with(nav=nav, ncx=ncx)))
    assert [(entry["label"], entry["ancestors"]) for entry in result["navigation"]["entries"]] == [
        ("", [""]),
        ("", [""]),
    ]


@pytest.mark.parametrize(
    "prose", ["Private group prose must stay out of labels", "x" * 513],
    ids=[
        "ordinary-prose",
        "oversized-prose",
    ],
)
def test_nav_group_labels_do_not_capture_nearby_paragraph_prose(prose):
    nav = page(
        '<nav epub:type="toc"><ol><li><span>Collected tales</span>'
        f'<p>{prose}</p><ol><li><a href="first.xhtml#one">One</a></li>'
        "</ol></li></ol></nav>"
    )
    result = inspect(archive(parts_with(nav=nav)))
    assert result["structural_check"] == "passed"
    assert result["navigation"]["entries"][0]["ancestors"] == ["Collected tales"]
    assert prose not in json.dumps(result)


def test_xhtml_line_breaks_keep_word_boundaries_in_recorded_labels():
    data = archive(
        parts_with(
            first=page(
                '<h1 id="one">Chapter<br/>1</h1><a href="second.xhtml#two">Second<br/>novel</a>'
            ),
            nav=page(
                '<nav epub:type="toc"><ol><li><span>Volume<br/>One</span><ol>'
                '<li><a href="first.xhtml#one">First<br/>novel</a></li>'
                "</ol></li></ol></nav>"
            ),
        )
    )
    result = inspect(data)
    first = document(result, "EPUB/first.xhtml")
    assert first["headings"][0]["label"] == "Chapter 1"
    assert first["headings"][0]["chapter_number"] == 1
    assert first["links"][0]["label"] == "Second novel"
    assert result["navigation"]["entries"][0]["label"] == "First novel"
    assert result["navigation"]["entries"][0]["ancestors"] == ["Volume One"]
    assert result["structural_check"] == "passed"


@pytest.mark.parametrize(
    "limit,code",
    [
        ({"max_records": 20}, "record_limit"),
        ({"max_output_bytes": ENVELOPE_BYTES}, "output_bytes_limit"),
        ({"max_xml_depth": 5}, "xml_depth_limit"),
        ({"max_xml_text_chars": 256}, "xml_text_limit"),
    ],
)
def test_contents_evidence_cannot_escape_existing_report_and_xml_budgets(limit, code):
    nav = page(
        '<nav epub:type="toc"><ol><li><span>Group</span><ol>'
        + '<li><a href="first.xhtml#one">'
        + "A" * 128
        + "</a></li>"
        + ('<li><a href="first.xhtml#one">' + "B" * 128 + "</a></li>") * 12
        + "</ol></li></ol></nav>"
    )
    result = inspect(archive(parts_with(nav=nav)), policy=replace(InspectionPolicy(), **limit))
    assert code in codes(result)
    assert result["inspection_complete"] is False
    assert result["structural_check"] == "failed"
    assert result["ready"] is False
    if "max_output_bytes" in limit:
        assert len(json.dumps(result, ensure_ascii=True).encode()) <= limit["max_output_bytes"]
        assert result["navigation"]["entries"] == []
