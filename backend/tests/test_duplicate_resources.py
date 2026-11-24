"""Exact shared resource bytes are review leads, never whole-book equivalence."""

from copy import deepcopy

import pytest
from librarium import content_evidence, duplicate_evidence


def report(digests, *, prefix="chapter"):
    value = {
        "policy": {
            "version": "librarium.epub-structure.v6",
            "limits": {"max_members": 2048, "max_records": 8192, "max_name_chars": 512},
        },
        "source_sha256": "f" * 64,
        "inspection_complete": True,
        "structural_check": "passed",
        "spine": [],
        "documents": [],
        "manifest": [],
    }
    for index, digest in enumerate(digests):
        path = f"EPUB/{prefix}{index}.xhtml"
        value["spine"].append({"index": index, "path": path})
        value["documents"].append({"path": path, "byte_sha256": digest * 64})
        value["manifest"].append({"path": path, "media_type": "application/xhtml+xml"})
    value["content_evidence"] = content_evidence.unconfirmed(
        value["source_sha256"], "unused", content_evidence.HISTORICAL_POLICY
    ) | {
        "status": "recorded",
        "reason": None,
        "text_sha256": "e" * 64,
        "spine_bytes_sha256": "d" * 64,
        "text_chars": 100,
        "spine_documents": len(digests),
    }
    return value


def overlap(first, second):
    return duplicate_evidence.resource_overlap(first, second)


def test_renamed_paths_retain_exact_resource_matches_and_both_source_locations():
    value = overlap(report("ab"), report("ab", prefix="renamed"))
    assert value["status"] == "recorded"
    assert value["relation"] == "all_spine_resources_same"
    assert value["matched_documents"] == 2
    assert value["pairing_order_preserved"] is True
    assert value["matches"][0] == {
        "sha256": "a" * 64,
        "selected": {"path": "EPUB/chapter0.xhtml", "spine_index": 0},
        "comparison": {"path": "EPUB/renamed0.xhtml", "spine_index": 0},
    }


def test_changed_chapter_does_not_hide_other_exact_shared_resource():
    value = overlap(report("ab"), report("ac"))
    assert value["relation"] == "shared_spine_resources"
    assert value["matched_documents"] == 1
    assert value["selected_documents"] == value["comparison_documents"] == 2
    assert value["matches"][0]["sha256"] == "a" * 64


@pytest.mark.parametrize(
    "first,second,relation",
    [
        ("ab", "fabc", "selected_spine_resources_contained"),
        ("fabc", "ab", "comparison_spine_resources_contained"),
        ("ab", "cd", "no_shared_spine_resources"),
    ],
)
def test_byte_resource_containment_is_directional_and_does_not_clear_semantics(
    first, second, relation
):
    value = overlap(report(first), report(second))
    assert value["relation"] == relation
    assert "semantic" in value["limitations"]
    assert "clearance" not in value


def test_repeated_digest_uses_occurrences_once_without_cartesian_inflation():
    value = overlap(report("aab"), report("abb"))
    assert value["matched_documents"] == 2
    assert len(value["matches"]) == 2
    assert len({entry["comparison"]["spine_index"] for entry in value["matches"]}) == 2
    assert value["relation"] == "shared_spine_resources"


def test_reordered_resources_disclose_order_change():
    value = overlap(report("aba"), report("baa"))
    assert value["matched_documents"] == 3
    assert value["relation"] == "all_spine_resources_same"
    assert value["pairing_order_preserved"] is False


def test_partial_repeated_digest_pairing_does_not_assert_optimal_subsequence_alignment():
    value = overlap(report("ab"), report("bab"))
    assert value["relation"] == "selected_spine_resources_contained"
    assert value["matched_documents"] == 2
    assert [match["comparison"]["spine_index"] for match in value["matches"]] == [1, 0]
    assert value["pairing_order_preserved"] is False
    assert "first unused comparison occurrence" in value["limitations"]
    assert "not all possible subsequence alignments" in value["limitations"]


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(inspection_complete=False),
        lambda value: value.update(structural_check="failed"),
        lambda value: value["policy"].update(version="librarium.epub-structure.v5"),
        lambda value: value["content_evidence"].update(status="unconfirmed"),
        lambda value: value["content_evidence"].update(source_sha256="0" * 64),
        lambda value: value["content_evidence"].update(spine_documents=3),
        lambda value: value["documents"][0].pop("byte_sha256"),
        lambda value: value["documents"][0].update(byte_sha256="invalid"),
        lambda value: value["documents"].append(deepcopy(value["documents"][0])),
        lambda value: value["spine"][1].update(path=value["spine"][0]["path"]),
        lambda value: value["spine"][0].update(index=True),
        lambda value: value["spine"][0].update(path="../unsafe.xhtml"),
        lambda value: value["manifest"][0].update(media_type="image/svg+xml"),
        lambda value: value["policy"]["limits"].update(max_members=1),
        lambda value: value["policy"]["limits"].update(max_members=2049),
        lambda value: value.update(documents=None),
        lambda value: value.update(manifest=None),
    ],
)
def test_ineligible_or_malformed_evidence_never_produces_matches(change):
    malformed = report("ab")
    change(malformed)
    for first, second in [(malformed, report("ab")), (report("ab"), malformed)]:
        value = overlap(first, second)
        assert value["status"] == "unconfirmed"
        assert value["relation"] == "unconfirmed"
        assert value["matched_documents"] is None
        assert value["matches"] == []


def test_detail_limit_retains_total_counts_and_explicit_truncation(monkeypatch):
    monkeypatch.setattr(duplicate_evidence, "MAX_RESOURCE_MATCHES", 2)
    value = overlap(report("abcd"), report("abcd"))
    assert value["matched_documents"] == 4
    assert len(value["matches"]) == 2
    assert value["truncated"] is True
    assert value["relation"] == "all_spine_resources_same"
