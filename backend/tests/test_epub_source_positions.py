"""Source counters and positions from synthetic EPUBs, without returning prose."""

import hashlib
import json
import sys
from dataclasses import replace
from types import ModuleType

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES, InspectionPolicy
from test_epub_contents_evidence import document, parts_with
from test_epub_inspection import archive, codes, inspect, page


def first_document(body):
    result = inspect(archive(parts_with(first=body)))
    return result, document(result, "EPUB/first.xhtml")


def test_inline_br_unicode_and_block_counters_share_full_document_source_order():
    body = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ignored title</title></head>'
        '<body><p>Hel<em>lo</em><br/>world\u00a0尾</p><span id="before"/>'
        '<h1 id="one">Chapter <em>1</em></h1>'
        '<p>After <a href="#one">end</a><img src="map.svg#map"/></p></body></html>'
    ).encode()
    result, doc = first_document(body)
    assert result["policy"]["version"] == "librarium.epub-structure.v10"
    assert (doc["body_word_count"], doc["non_heading_word_count"], doc["media_count"]) == (7, 5, 1)
    assert doc["headings"] == [
        {
            "level": 1,
            "id": "one",
            "chapter_number": 1,
            "label": "Chapter 1",
            "source_index": 8,
            "word_offset": 3,
            "non_heading_word_offset": 3,
            "media_offset": 0,
            "word_count": 2,
        }
    ]
    assert doc["anchors"] == [
        {
            "id": "before",
            "source_index": 7,
            "word_offset": 3,
            "non_heading_word_offset": 3,
            "media_offset": 0,
        },
        {
            "id": "one",
            "source_index": 8,
            "word_offset": 3,
            "non_heading_word_offset": 3,
            "media_offset": 0,
        },
    ]
    assert [(link["source_index"], link["word_offset"]) for link in doc["links"]] == [
        (11, 6),
        (12, 7),
    ]
    assert doc["links"][0]["ancestors"] == []
    assert "Ignored title" not in json.dumps(result)


def test_nested_printed_group_labels_retain_each_actual_label_node_position():
    _, doc = first_document(
        page(
            '<h1 id="one">Contents</h1><ol><li><span>Collection</span><ol>'
            '<li><span>Alpha</span><ol><li><a href="second.xhtml#two">Chapter 1</a>'
            "</li></ol></li></ol></li></ol>"
        )
    )
    link = doc["links"][0]
    assert link["ancestors"] == ["Collection", "Alpha"]
    assert link["ancestor_sources"] == [
        {"label": "Collection", "source_index": 5},
        {"label": "Alpha", "source_index": 8},
    ]
    assert link["source_index"] == 11


@pytest.mark.parametrize(
    "between,words,media",
    [
        ("", 0, 0),
        (" \n ", 0, 0),
        ("<p>Intervening text</p>", 2, 0),
        ('<img src="map.svg#map"/>', 0, 1),
    ],
)
def test_anchor_before_heading_keeps_intervening_text_and_media_evidence(between, words, media):
    result, doc = first_document(page(f'<a id="before"/>{between}<h1 id="one">Chapter 1</h1>'))
    anchor, heading_anchor = doc["anchors"]
    heading = doc["headings"][0]
    assert anchor["source_index"] < heading["source_index"]
    assert anchor["word_offset"] == anchor["non_heading_word_offset"] == anchor["media_offset"] == 0
    assert heading["word_offset"] == heading["non_heading_word_offset"] == words
    assert heading["media_offset"] == media
    assert heading_anchor["source_index"] == heading["source_index"]
    assert result["ready"] is False


@pytest.mark.parametrize(
    "body",
    [
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>No body</title></head></html>',
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body/><body/></html>',
    ],
)
def test_missing_or_ambiguous_xhtml_body_is_unknown_instead_of_empty(body):
    result, doc = first_document(body)
    assert doc["body_word_count"] is None
    assert doc["non_heading_word_count"] is None
    assert doc["media_count"] is None
    svg = document(result, "EPUB/map.svg")
    assert svg["body_word_count"] is None
    assert svg["anchors"][0]["word_offset"] is None


def test_empty_body_is_known_zero_and_outside_body_offsets_are_unknown():
    _, doc = first_document(
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<h1 id="outside">Outside</h1></head><body/></html>'
    )
    assert (doc["body_word_count"], doc["non_heading_word_count"], doc["media_count"]) == (0, 0, 0)
    assert doc["headings"][0]["word_offset"] is None
    assert doc["headings"][0]["non_heading_word_offset"] is None
    assert doc["headings"][0]["media_offset"] is None
    assert doc["anchors"][0]["word_offset"] is None


def test_head_script_and_style_do_not_count_or_leak_into_source_labels():
    result, doc = first_document(
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>HEAD_SENTINEL</title>'
        b"<style>HEAD_STYLE_SENTINEL</style></head><body><script>SCRIPT_SENTINEL</script>"
        b"<style>STYLE_SENTINEL</style><p>Visible <em>body</em></p>"
        b'<h1 id="one">Chapter <script>HEADING_SCRIPT_SENTINEL</script>1</h1></body></html>'
    )
    assert (doc["body_word_count"], doc["non_heading_word_count"], doc["media_count"]) == (4, 2, 0)
    assert doc["headings"][0]["label"] == "Chapter 1"
    assert "SENTINEL" not in json.dumps(result)


def test_inline_text_joins_across_skipped_scripts_but_blocks_separate_words():
    _, doc = first_document(
        page(
            "<p>hel<span>l</span><script>ignored</script>o</p><div>world</div>"
            '<div>one<br/>two</div><h1 id="one">Chapter<br/>1</h1>'
        )
    )
    assert doc["body_word_count"] == 6
    assert doc["non_heading_word_count"] == 4
    assert doc["headings"][0]["word_offset"] == 4
    assert doc["headings"][0]["word_count"] == 2


@pytest.mark.parametrize("tag", ["head", "script", "style"])
def test_foreign_elements_with_script_like_names_do_not_hide_source_words(tag):
    _, doc = first_document(
        page(
            f'<p xmlns:custom="urn:synthetic:ordinary">Literal <custom:{tag}>foreign</custom:{tag}> tail</p>'
        )
    )
    assert doc["body_word_count"] == doc["non_heading_word_count"] == 3


def test_image_and_embedded_media_are_observed_even_without_words():
    _, doc = first_document(
        page(
            '<img src="map.svg#map"/><audio/><video/><object/><embed/><iframe/><canvas/>'
            '<svg xmlns="http://www.w3.org/2000/svg"/>'
        )
    )
    assert doc["body_word_count"] == doc["non_heading_word_count"] == 0
    assert doc["media_count"] == 8


def test_anchor_aliases_and_duplicates_keep_source_and_attribute_order():
    result, doc = first_document(
        page(
            '<a name="legacy" xml:id="xml" id="html" href="#html"/>'
            '<span id="html"/><h1 id="one">Chapter 1</h1>'
        )
    )
    assert [anchor["id"] for anchor in doc["anchors"]] == ["legacy", "xml", "html", "html", "one"]
    assert [anchor["source_index"] for anchor in doc["anchors"]] == [2, 2, 2, 3, 4]
    assert "duplicate_document_id" in codes(result)
    assert result["structural_check"] == "failed"
    assert result == inspect(
        archive(
            parts_with(
                first=page(
                    '<a name="legacy" xml:id="xml" id="html" href="#html"/>'
                    '<span id="html"/><h1 id="one">Chapter 1</h1>'
                )
            )
        )
    )


@pytest.mark.parametrize(
    "start,expected",
    [
        ('<a id="one" name="one"/><h1>Chapter 1</h1>', ["one"]),
        ('<a name="one" id="one" xml:id="one"/><h1>Chapter 1</h1>', ["one"]),
        ('<h1 id="one" xml:id="one">Chapter 1</h1>', ["one"]),
        ('<a name="legacy" id="one" xml:id="one"/><h1>Chapter 1</h1>', ["legacy", "one"]),
    ],
)
def test_same_element_identifier_aliases_record_each_distinct_anchor_once(start, expected):
    from librarium.epub_inspection import InspectionPolicy
    from librarium.inspection_process import inspect_isolated
    from test_epub_inspection import fixture_parts

    parts = dict(fixture_parts())
    parts["EPUB/book.opf"] = parts["EPUB/book.opf"].replace(b'linear="no"', b'linear="yes"')
    parts["EPUB/first.xhtml"] = page(start + "<p>Independent synthetic narrative.</p>")
    data = archive(list(parts.items()))
    result = inspect(data)
    assert result["structural_check"] == "passed", result["findings"]
    assert "duplicate_document_id" not in codes(result)
    anchors = document(result, "EPUB/first.xhtml")["anchors"]
    assert [anchor["id"] for anchor in anchors] == expected
    assert all(anchor["source_index"] == 2 for anchor in anchors)
    # LF never keeps a list of fewer than three entries; the anchor directly before the
    # heading is its link target, so no new anchor is needed.
    plan = result["contents_plan"]
    assert plan["decision"] == "propose"
    first = plan["entries"][0]
    assert (first["label"], first["fragment"], first["requires_anchor"]) == (
        "Chapter 1",
        expected[-1],
        False,
    )
    assert inspect_isolated(data, hashlib.sha256(data).hexdigest(), InspectionPolicy()) == result


def test_alias_deduplication_still_rejects_another_element_reusing_the_same_identifier():
    result, doc = first_document(page('<a id="one" name="one"/><h1 xml:id="one">Chapter 1</h1>'))
    assert result["structural_check"] == "failed"
    assert "duplicate_document_id" in codes(result)
    assert [(anchor["id"], anchor["source_index"]) for anchor in doc["anchors"]] == [
        ("one", 2),
        ("one", 3),
    ]


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
                + "".join(f'<span id="anchor-{i}"/>' for i in range(40))
            )
        )
    )
    result = inspect(data, policy=replace(InspectionPolicy(), **limit))
    assert code in codes(result)
    assert result["structural_check"] == "failed"
    assert result["contents_plan"]["decision"] == "held"
    assert result["contents_plan"]["entries"] == []
    if "max_output_bytes" in limit:
        assert len(json.dumps(result, ensure_ascii=True).encode()) <= limit["max_output_bytes"]
        assert result["contents_plan"]["reason_codes"] == ["output_bytes_limit"]


def planner_module(monkeypatch, plan):
    module = ModuleType("librarium.contents_planning")
    module.contents_plan = plan
    module.held_plan = lambda report, reason: {
        "policy_version": "librarium.contents-plan.v1",
        "source_sha256": report["source_sha256"],
        "inspection_policy": report["policy"]["version"],
        "decision": "held",
        "reason_codes": [reason],
        "existing": [],
        "entries": [],
        "excluded_targets": [],
        "limitations": [],
        "ready": False,
    }
    monkeypatch.setitem(sys.modules, "librarium.contents_planning", module)


def test_planner_runs_after_structural_check_with_the_shared_record_budget(monkeypatch):
    observed = []

    def plan(report, *, record):
        observed.append(report["structural_check"])
        assert report["policy"]["version"] == "librarium.epub-structure.v10"
        assert document(report, "EPUB/first.xhtml")["body_word_count"] > 0
        return {
            "marker": record({"captured": True}),
            "decision": "held",
            "entries": [],
            "ready": False,
        }

    planner_module(monkeypatch, plan)
    result = inspect(archive())
    assert observed == ["passed"]
    assert result["contents_plan"] == {
        "marker": {"captured": True},
        "decision": "held",
        "entries": [],
        "ready": False,
    }


def test_planner_record_exhaustion_returns_empty_held_plan(monkeypatch):
    def plan(report, *, record):
        for i in range(100):
            record({"index": i})
        raise AssertionError("record budget was not applied")

    planner_module(monkeypatch, plan)
    result = inspect(archive(), policy=replace(InspectionPolicy(), max_records=64))
    assert "record_limit" in codes(result)
    assert result["structural_check"] == "failed"
    assert result["contents_plan"]["decision"] == "held"
    assert result["contents_plan"]["entries"] == []
    assert result["contents_plan"]["reason_codes"] == ["record_limit"]


def test_new_plan_is_bound_without_recursive_report_digest_and_matches_the_child():
    pytest.importorskip("librarium.contents_planning")
    from librarium.inspection_process import inspect_isolated

    data = archive()
    digest = hashlib.sha256(data).hexdigest()
    result = inspect(data)
    assert result["contents_plan"]["policy_version"] == "librarium.contents-plan.v2"
    assert result["contents_plan"]["source_sha256"] == digest
    assert result["contents_plan"]["inspection_policy"] == "librarium.epub-structure.v10"
    assert "report_sha256" not in result["contents_plan"]
    assert inspect_isolated(data, digest, InspectionPolicy()) == result
