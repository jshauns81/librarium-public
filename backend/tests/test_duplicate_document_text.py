"""Document source-text matches remain historical leads with bounded detail."""

from copy import deepcopy

import pytest
from librarium import content_evidence, duplicate_evidence
from test_duplicate_resources import report as resource_report


def report(digests, *, prefix="chapter"):
    value = resource_report(digests, prefix=prefix)
    value["policy"]["version"] = "librarium.epub-structure.v9"
    value["policy"]["limits"]["max_xml_text_chars"] = 16 * 1024 * 1024
    value["content_evidence"]["text_chars"] = len(digests) * 11 - 1
    value["document_text_evidence"] = {
        "policy": content_evidence.HISTORICAL_DOCUMENT_TEXT_POLICY,
        "status": "recorded",
        "source_sha256": value["source_sha256"],
        "reason": None,
        "scope": content_evidence.HISTORICAL_DOCUMENT_TEXT_SCOPE,
        "documents": [
            {
                "path": item["path"],
                "spine_index": index,
                "resource_sha256": item["byte_sha256"],
                "text_sha256": digest * 64,
                "text_chars": 10,
            }
            for index, (item, digest) in enumerate(zip(value["documents"], digests, strict=True))
        ],
    }
    return value


@pytest.mark.parametrize(
    "first,second,relation,count,order",
    [
        ("ab", "ab", "all_document_text_same", 2, True),
        ("ab", "ba", "all_document_text_same", 2, False),
        ("ab", "fabc", "selected_document_text_contained", 2, True),
        ("fabc", "ab", "comparison_document_text_contained", 2, True),
        ("aab", "abb", "shared_document_text", 2, True),
        ("ab", "bab", "selected_document_text_contained", 2, False),
        ("ab", "cd", "no_shared_document_text", 0, None),
    ],
)
def test_one_to_one_source_text_relations_preserve_occurrence_and_order_limits(
    first, second, relation, count, order
):
    result = duplicate_evidence.document_text_overlap(report(first), report(second, prefix="other"))
    assert result["status"] == "recorded"
    assert result["relation"] == relation
    assert result["matched_documents"] == count
    assert result["pairing_order_preserved"] is order
    assert len({row["comparison"]["spine_index"] for row in result["matches"]}) == count
    assert "clearance" not in result and "authentication" in result["limitations"]


def test_text_match_keeps_distinct_resource_digests_and_both_locations():
    first, second = report("a"), report("a", prefix="other")
    second["documents"][0]["byte_sha256"] = "b" * 64
    second["document_text_evidence"]["documents"][0]["resource_sha256"] = "b" * 64
    result = duplicate_evidence.document_text_overlap(first, second)
    assert result["matches"] == [
        {
            "text_sha256": "a" * 64,
            "text_chars": 10,
            "selected": {
                "path": "EPUB/chapter0.xhtml",
                "spine_index": 0,
                "resource_sha256": "a" * 64,
            },
            "comparison": {
                "path": "EPUB/other0.xhtml",
                "spine_index": 0,
                "resource_sha256": "b" * 64,
            },
        }
    ]


def test_digest_match_alone_cannot_ignore_disagreeing_character_count():
    first, second = report("a"), report("a")
    second["document_text_evidence"]["documents"][0]["text_chars"] = 11
    second["content_evidence"]["text_chars"] = 11
    assert duplicate_evidence.document_text_overlap(first, second)["matched_documents"] == 0


def test_non_spine_manifest_aliases_do_not_hide_valid_document_text():
    first, second = report("a"), report("a")
    for value in (first, second):
        value["manifest"].extend(
            [
                {"path": "EPUB/map.svg", "media_type": "image/svg+xml"},
                {"path": "EPUB/map.svg", "media_type": "image/svg+xml"},
            ]
        )
    assert duplicate_evidence.document_text_overlap(first, second)["matched_documents"] == 1


@pytest.mark.parametrize(
    "kind", ["historical", "unknown", "source", "resource", "extra", "failed", "limits", "missing"]
)
def test_unconfirmed_or_malformed_reports_never_supply_text_matches(kind):
    value = report("ab")
    if kind == "historical":
        value["policy"]["version"] = "librarium.epub-structure.v7"
        value.pop("document_text_evidence")
    elif kind == "unknown":
        value["document_text_evidence"].update(
            status="unconfirmed", reason="unavailable", documents=[]
        )
    elif kind == "source":
        value["document_text_evidence"]["source_sha256"] = "0" * 64
    elif kind == "resource":
        value["documents"][0]["byte_sha256"] = "f" * 64
    elif kind == "extra":
        value["document_text_evidence"]["documents"][0]["text"] = "forbidden prose"
    elif kind == "failed":
        value["structural_check"] = "failed"
    elif kind == "limits":
        value["policy"]["limits"]["max_records"] = 2
    else:
        value.pop("document_text_evidence")
    for left, right in [(value, report("ab")), (report("ab"), deepcopy(value))]:
        result = duplicate_evidence.document_text_overlap(left, right)
        assert result["status"] == result["relation"] == "unconfirmed"
        assert result["matches"] == [] and result["matched_documents"] is None


def test_detail_truncation_keeps_complete_counts_without_partial_clearance(monkeypatch):
    monkeypatch.setattr(duplicate_evidence, "MAX_DOCUMENT_TEXT_MATCHES", 2)
    result = duplicate_evidence.document_text_overlap(report("abcd"), report("abcd"))
    assert result["matched_documents"] == 4 and len(result["matches"]) == 2
    assert result["truncated"] is True
    assert result["relation"] == "all_document_text_same"


def current(digests, empty, *, prefix="chapter"):
    """An inspection v11 report whose ``empty`` spine indexes are text-empty pages."""
    value = report(digests, prefix=prefix)
    value["policy"]["version"] = "librarium.epub-structure.v11"
    rows = value["document_text_evidence"]["documents"]
    for index in empty:
        rows[index].update(text_chars=0, text_sha256=content_evidence.EMPTY_TEXT_SHA256)
    texts = [row["text_chars"] for row in rows if row["text_chars"]]
    value["document_text_evidence"].update(
        policy=content_evidence.DOCUMENT_TEXT_POLICY, scope=content_evidence.DOCUMENT_TEXT_SCOPE
    )
    value["content_evidence"] = content_evidence.unconfirmed(value["source_sha256"], "x") | {
        "status": "recorded",
        "reason": None,
        "text_sha256": "e" * 64,
        "spine_bytes_sha256": "d" * 64,
        "text_chars": sum(texts) + len(texts) - 1,
        "spine_documents": len(rows),
        "empty_spine_documents": len(empty),
    }
    return value


def test_text_empty_pages_are_never_shared_document_text():
    first, second = current("ab", [0]), current("ac", [0], prefix="other")
    content_evidence.validate_document_text_evidence(first)
    result = duplicate_evidence.document_text_overlap(first, second)
    assert result["status"] == "recorded"
    assert result["relation"] == "no_shared_document_text"
    assert result["matched_documents"] == 0
    assert result["selected_documents"] == result["comparison_documents"] == 1
    same = duplicate_evidence.document_text_overlap(first, current("cb", [0]))
    assert same["relation"] == "all_document_text_same"
    assert [row["selected"]["spine_index"] for row in same["matches"]] == [1]
