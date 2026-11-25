"""Source order and positions from synthetic EPUBs, without returning prose.

Inspection v11 records only what checks and the report view read: each heading and link
with its source element index, group ancestry and the document's element count. Word and
media offsets, body counts, anchor lists and contents observations fed the retired
contents planner (L091) and are no longer produced.
"""

import hashlib
import json
from dataclasses import replace

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES, InspectionPolicy
from test_epub_contents_evidence import document, parts_with
from test_epub_inspection import archive, codes, inspect, page


def first_document(body):
    result = inspect(archive(parts_with(first=body)))
    return result, document(result, "EPUB/first.xhtml")


def test_headings_and_links_record_xml_source_order():
    body = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ignored title</title></head>'
        '<body><p>Hel<em>lo</em><br/>world\u00a0尾</p><span id="before"/>'
        '<h1 id="one">Chapter <em>1</em></h1>'
        '<p>After <a href="#one">end</a><img src="map.svg#map"/></p></body></html>'
    ).encode()
    result, doc = first_document(body)
    assert result["policy"]["version"] == "librarium.epub-structure.v11"
    assert doc["headings"] == [
        {
            "level": 1,
            "id": "one",
            "chapter_number": 1,
            "label": "Chapter 1",
            "source_index": 8,
        }
    ]
    assert [link["source_index"] for link in doc["links"]] == [11, 12]
    assert doc["links"][0]["ancestors"] == []
    assert "Ignored title" not in json.dumps(result)


def test_documents_carry_no_offsets_counts_anchors_or_contents_observations():
    result, doc = first_document(
        page('<a id="before"/><h1 id="one">Chapter 1</h1><p>Words <img src="map.svg#map"/></p>')
    )
    assert set(doc) == {"path", "byte_sha256", "headings", "links", "source_element_count"}
    assert set(doc["headings"][0]) == {"level", "id", "chapter_number", "label", "source_index"}
    assert all(
        not {"word_offset", "non_heading_word_offset", "media_offset", "heading_index"} & set(link)
        for link in doc["links"]
    )
    assert {"contents_plan", "contents_observations"}.isdisjoint(result)
    assert all("blocks" not in item and "anchors" not in item for item in result["documents"])


def test_nested_printed_group_labels_keep_their_ancestry_and_link_position():
    _, doc = first_document(
        page(
            '<h1 id="one">Contents</h1><ol><li><span>Collection</span><ol>'
            '<li><span>Alpha</span><ol><li><a href="second.xhtml#two">Chapter 1</a>'
            "</li></ol></li></ol></li></ol>"
        )
    )
    link = doc["links"][0]
    assert link["ancestors"] == ["Collection", "Alpha"]
    assert "ancestor_sources" not in link
    assert link["source_index"] == 11


@pytest.mark.parametrize(
    "body",
    [
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>No body</title></head></html>',
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body/><body/></html>',
        (
            b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            b'<h1 id="outside">Outside</h1></head><body/></html>'
        ),
    ],
)
def test_missing_ambiguous_or_empty_xhtml_body_is_inspected_without_counts(body):
    result, doc = first_document(body)
    assert result["inspection_complete"] is True
    assert "body_word_count" not in doc
    assert "media_count" not in doc
    assert "anchors" not in document(result, "EPUB/map.svg")


def test_head_script_and_style_do_not_leak_into_source_labels():
    result, doc = first_document(
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>HEAD_SENTINEL</title>'
        b"<style>HEAD_STYLE_SENTINEL</style></head><body><script>SCRIPT_SENTINEL</script>"
        b"<style>STYLE_SENTINEL</style><p>Visible <em>body</em></p>"
        b'<h1 id="one">Chapter <script>HEADING_SCRIPT_SENTINEL</script>1</h1></body></html>'
    )
    assert doc["headings"][0]["label"] == "Chapter 1"
    assert "SENTINEL" not in json.dumps(result)


def test_alias_duplicates_are_still_found_in_source_and_attribute_order():
    first = page(
        '<a name="legacy" xml:id="xml" id="html" href="#html"/>'
        '<span id="html"/><h1 id="one">Chapter 1</h1>'
    )
    result = inspect(archive(parts_with(first=first)))
    assert "duplicate_document_id" in codes(result)
    assert result["structural_check"] == "failed"
    assert result == inspect(archive(parts_with(first=first)))


@pytest.mark.parametrize(
    "start",
    [
        '<a id="one" name="one"/><h1>Chapter 1</h1>',
        '<a name="one" id="one" xml:id="one"/><h1>Chapter 1</h1>',
        '<h1 id="one" xml:id="one">Chapter 1</h1>',
        '<a name="legacy" id="one" xml:id="one"/><h1>Chapter 1</h1>',
    ],
)
def test_same_element_identifier_aliases_are_not_duplicates(start):
    from librarium.inspection_process import inspect_isolated
    from test_epub_inspection import fixture_parts

    parts = dict(fixture_parts())
    parts["EPUB/book.opf"] = parts["EPUB/book.opf"].replace(b'linear="no"', b'linear="yes"')
    parts["EPUB/first.xhtml"] = page(start + "<p>Independent synthetic narrative.</p>")
    data = archive(list(parts.items()))
    result = inspect(data)
    assert result["structural_check"] == "passed", result["findings"]
    assert "duplicate_document_id" not in codes(result)
    assert inspect_isolated(data, hashlib.sha256(data).hexdigest(), InspectionPolicy()) == result


def test_another_element_reusing_an_alias_identifier_is_rejected():
    result, _ = first_document(page('<a id="one" name="one"/><h1 xml:id="one">Chapter 1</h1>'))
    assert result["structural_check"] == "failed"
    assert "duplicate_document_id" in codes(result)


def test_printed_contents_link_ancestry_uses_literal_direct_group_labels_only():
    _, doc = first_document(
        page(
            '<h1 id="one">Contents</h1><ol><li><span>Volume <em>one</em></span>'
            '<p>PROSE_SENTINEL</p><ol><li><a href="second.xhtml#two">First tale</a><ol>'
            '<li><a href="second.xhtml#two">Chapter 1</a></li></ol></li></ol></li></ol>'
        )
    )
    assert [link["ancestors"] for link in doc["links"]] == [
        ["Volume one"],
        ["Volume one", "First tale"],
    ]
    # A paragraph inside a list item never becomes a group label.
    assert "PROSE_SENTINEL" not in json.dumps(doc["links"])


@pytest.mark.parametrize(
    "limit,code",
    [
        ({"max_records": 32}, "record_limit"),
        ({"max_output_bytes": ENVELOPE_BYTES}, "output_bytes_limit"),
        ({"max_xml_depth": 2}, "xml_depth_limit"),
    ],
)
def test_source_observations_share_record_output_and_xml_limits(limit, code):
    data = archive(
        parts_with(
            first=page(
                '<h1 id="one">Chapter 1</h1>'
                + "".join(f'<h2 id="section-{i}">Section {i}</h2>' for i in range(40))
            )
        )
    )
    result = inspect(data, policy=replace(InspectionPolicy(), **limit))
    assert code in codes(result)
    assert result["structural_check"] == "failed"
    if "max_output_bytes" in limit:
        assert len(json.dumps(result, ensure_ascii=True).encode()) <= limit["max_output_bytes"]


def test_a_new_report_is_bound_without_a_plan_and_matches_the_child():
    from librarium.inspection_process import inspect_isolated

    data = archive()
    digest = hashlib.sha256(data).hexdigest()
    result = inspect(data)
    assert result["source_sha256"] == digest
    assert {"contents_plan", "contents_observations"}.isdisjoint(result)
    assert inspect_isolated(data, digest, InspectionPolicy()) == result
