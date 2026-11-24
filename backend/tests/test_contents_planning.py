"""Contents plan v2 binds LF's decisions to complete, current, source-bound evidence."""

import hashlib
from copy import deepcopy

import pytest
from librarium.contents_planning import MAX_ENTRIES, contents_plan
from librarium.epub_inspection import inspect_bytes
from test_contents_rebuild import chapters, make, page, prose


def report(docs=None, old=None):
    docs = chapters(4) if docs is None else docs
    data = make(docs, [("Start", "c00.html")] if old is None else old)
    return inspect_bytes(data, hashlib.sha256(data).hexdigest())


def assert_held(result, reason=None):
    assert result["decision"] == "held"
    assert result["entries"] == []
    assert result["ready"] is False
    if reason is not None:
        assert result["reason_codes"] == [reason]


def test_a_proposal_carries_its_envelope_measures_and_exact_locators():
    value = report()
    result = contents_plan(value)
    assert result == value["contents_plan"]
    assert result["policy_version"] == "librarium.contents-plan.v2"
    assert result["inspection_policy"] == "librarium.epub-structure.v10"
    assert result["source_sha256"] == value["source_sha256"]
    assert result["decision"] == "propose"
    assert result["measures"]["headings"] == 4
    entry = result["entries"][1]
    doc = next(d for d in value["documents"] if d["path"] == "c01.html")
    assert entry["fragment"] == "c1" and entry["requires_anchor"] is False
    assert entry["position"] == {
        "document_index": 1,
        "source_index": doc["headings"][0]["source_index"],
        "word_offset": 0,
        "document_sha256": doc["byte_sha256"],
    }
    assert entry["label_source"]["path"] == "c01.html"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("incomplete", "inspection_incomplete"),
        ("truncated", "inspection_incomplete"),
        ("failure", "structural_failure"),
        ("old", "source_evidence_unavailable"),
        ("digest", "source_evidence_unavailable"),
        ("words", "source_evidence_unavailable"),
        ("observations", "contents_evidence_unavailable"),
        ("level", "source_evidence_unavailable"),
        ("order", "source_evidence_unavailable"),
        ("anchor", "duplicate_target"),
        ("spine", "target_order"),
    ],
)
def test_unusable_or_incomplete_evidence_is_held(change, reason):
    value = deepcopy(report())
    doc = value["documents"][0]
    if change == "incomplete":
        value["inspection_complete"] = False
    elif change == "truncated":
        value["findings_truncated"] = True
    elif change == "failure":
        value["findings"] = [{"code": "invalid_xml", "severity": "error"}]
    elif change == "old":
        value["policy"]["version"] = "librarium.epub-structure.v8"
    elif change == "digest":
        value["expected_sha256"] = "0" * 64
    elif change == "words":
        doc["body_word_count"] = None
    elif change == "observations":
        value["contents_observations"] = {"status": "unconfirmed", "reason": "record_limit"}
    elif change == "level":
        doc["headings"][0]["level"] = 7
    elif change == "order":
        doc["headings"].append(deepcopy(doc["headings"][0]))
    elif change == "anchor":
        doc["anchors"].append(deepcopy(doc["anchors"][0]))
    else:
        value["spine"].append(deepcopy(value["spine"][0]))
    assert_held(contents_plan(value), reason)


def test_missing_or_empty_navigation_still_allows_a_proposal():
    value = report()
    value["findings"] = [{"code": "empty_navigation", "severity": "error"}]
    value["structural_check"] = "failed"
    result = contents_plan(value)
    assert result["decision"] == "propose"
    assert [e["label"] for e in result["entries"]] == [f"Chapter {k + 1}" for k in range(4)]


def test_planning_is_deterministic_does_not_mutate_input_and_accounts_for_records():
    value = report()
    before = deepcopy(value)
    recorded = []

    def record(item):
        recorded.append(item)
        return item

    first = contents_plan(value, record=record)
    assert first == contents_plan(value)
    assert value == before
    assert len(recorded) == len(first["existing"]) + len(first["entries"])


def test_shared_record_budget_exceptions_propagate():
    class Exhausted(Exception):
        pass

    def record(item):
        raise Exhausted()

    with pytest.raises(Exhausted):
        contents_plan(report(), record=record)


def test_proposed_and_recorded_entries_share_one_limit():
    value = report()
    entries = value["navigation"]["entries"]
    value["navigation"]["entries"] = entries * (MAX_ENTRIES + 1)
    assert_held(contents_plan(value), "output_limit")


def test_a_kept_list_never_carries_replacement_entries():
    old = [(f"Chapter {k + 1}", f"c{k:02d}.html#c{k}") for k in range(4)]
    result = contents_plan(report(old=old))
    assert result["decision"] == "keep"
    assert result["entries"] == []
    assert [e["fragment"] for e in result["existing"]] == ["c0", "c1", "c2", "c3"]


def test_an_ocr_scan_refusal_names_the_scan():
    docs = {
        "a.html": page("<p>Produced in EPUB format by the Internet Archive.</p>" + prose(11000)),
        "b.html": page(prose(11000)),
    }
    result = contents_plan(report(docs, [("Start", "a.html")]))
    assert_held(result)
    assert result["reason_codes"] == ["no_chapter_headings", "ocr_scan"]
