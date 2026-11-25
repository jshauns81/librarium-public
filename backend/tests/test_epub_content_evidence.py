"""Synthetic source fingerprints identify comparison leads without admitting content."""

import hashlib
import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES, InspectionPolicy
from test_epub_inspection import archive, fixture_parts, inspect, page


def replaced(path, old, new):
    return [
        (name, body.replace(old, new) if name == path else body) for name, body in fixture_parts()
    ]


def evidence(parts=None, **kwargs):
    result = inspect(archive(parts), **kwargs)
    return result, result["content_evidence"]


def test_complete_evidence_is_bound_and_omits_prose():
    result, value = evidence()
    assert value["policy"] == "librarium.epub-content-evidence.v2"
    assert value["status"] == "recorded"
    assert value["source_sha256"] == result["source_sha256"]
    assert value["spine_documents"] == 2
    text = "Chapter 1 Unique synthetic story sentence. Next Chapter 2 Invented ending."
    assert value["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert value["text_chars"] == len(text)
    assert len(value["spine_bytes_sha256"]) == 64
    assert value["reason"] is None
    assert "Unique synthetic story sentence" not in json.dumps(value)
    assert result["content_acceptance"] == "not_checked" and result["ready"] is False


def test_zip_repackaging_changes_source_but_preserves_content_fingerprints():
    first = inspect(archive())
    second = inspect(archive(compression=zipfile.ZIP_DEFLATED))
    assert first["source_sha256"] != second["source_sha256"]
    for key in ("text_sha256", "spine_bytes_sha256"):
        assert first["content_evidence"][key] == second["content_evidence"][key]


def test_inline_markup_and_whitespace_normalize_without_inventing_word_boundaries():
    first, original = evidence()
    _, formatted = evidence(
        replaced(
            "EPUB/first.xhtml",
            b"Unique synthetic story sentence.",
            b"Uni<em>que</em>  synthetic\n story sentence.",
        )
    )
    assert original["text_sha256"] == formatted["text_sha256"]
    assert original["spine_bytes_sha256"] != formatted["spine_bytes_sha256"]
    assert first["source_sha256"] != formatted["source_sha256"]


@pytest.mark.parametrize(
    "old,new",
    [
        (b"Unique", b"unique"),
        (b"sentence.", b"sentence!"),
        (b"synthetic story", b"different story"),
        (b"Unique synthetic", b"<p>Unique</p><p>synthetic</p>"),
    ],
)
def test_changed_words_case_punctuation_and_block_boundaries_are_observed(old, new):
    _, original = evidence()
    _, changed = evidence(replaced("EPUB/first.xhtml", old, new))
    if b"<p>" in new:
        # Block boundaries must separate neighboring text rather than fusing words.
        assert changed["text_sha256"] == original["text_sha256"]
    else:
        assert changed["text_sha256"] != original["text_sha256"]


def test_spine_order_and_non_linear_content_are_included():
    _, original = evidence()
    _, reordered = evidence(
        replaced(
            "EPUB/book.opf",
            b'<itemref idref="first"/><itemref idref="second" linear="no"/>',
            b'<itemref idref="second" linear="no"/><itemref idref="first"/>',
        )
    )
    _, changed = evidence(replaced("EPUB/second.xhtml", b"Invented ending.", b"New ending."))
    assert reordered["status"] == changed["status"] == "recorded"
    assert original["text_sha256"] != reordered["text_sha256"]
    assert original["text_sha256"] != changed["text_sha256"]


def test_body_text_is_not_filtered_by_visibility_style_or_tag():
    _, original = evidence()
    _, changed = evidence(
        replaced(
            "EPUB/second.xhtml",
            b"</body>",
            b'<span hidden="hidden">Hidden source text</span><script>script text</script></body>',
        )
    )
    assert changed["status"] == "recorded"
    assert changed["text_sha256"] != original["text_sha256"]


def emptied(*paths, body=""):
    # Keep the anchors other documents link to; they add no text.
    anchors = {"EPUB/first.xhtml": '<div id="one"/>', "EPUB/second.xhtml": '<div id="two"/>'}
    return [
        (name, page(anchors[name] + body) if name in paths else value)
        for name, value in fixture_parts()
    ]


@pytest.mark.parametrize("body", ["", '<img src="map.svg"/>', "<p> </p><div><br/></div>"])
def test_text_empty_spine_documents_are_recorded_counted_and_disclosed(body):
    result, value = evidence(emptied("EPUB/second.xhtml", body=body))
    text = "Chapter 1 Unique synthetic story sentence. Next"
    assert result["structural_check"] == "passed"
    assert value["policy"] == "librarium.epub-content-evidence.v2"
    assert value["status"] == "recorded" and value["reason"] is None
    assert value["spine_documents"] == 2
    assert value["empty_spine_documents"] == 1
    assert value["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert value["text_chars"] == len(text)
    rows = result["document_text_evidence"]["documents"]
    assert result["document_text_evidence"]["policy"] == "librarium.epub-document-text.v2"
    assert [row["text_chars"] for row in rows] == [len(text), 0]
    assert rows[1]["text_sha256"] == hashlib.sha256(b"").hexdigest()
    assert rows[1]["resource_sha256"] == hashlib.sha256(page('<div id="two"/>' + body)).hexdigest()


def test_empty_documents_still_bind_their_bytes_and_order():
    _, first = evidence(emptied("EPUB/second.xhtml"))
    _, media = evidence(emptied("EPUB/second.xhtml", body='<img src="map.svg"/>'))
    assert first["text_sha256"] == media["text_sha256"]
    assert first["spine_bytes_sha256"] != media["spine_bytes_sha256"]


def test_a_spine_without_any_text_remains_unconfirmed():
    result, value = evidence(emptied("EPUB/first.xhtml", "EPUB/second.xhtml"))
    assert result["structural_check"] == "passed"
    assert value["status"] == "unconfirmed" and value["reason"] == "empty_spine_body"
    assert value["empty_spine_documents"] is None
    assert result["document_text_evidence"]["status"] == "unconfirmed"


@pytest.mark.parametrize("kind", ["svg", "duplicate", "alias", "missing"])
def test_unsupported_or_ambiguous_spine_holds_all_fingerprints(kind):
    parts = fixture_parts()
    if kind == "svg":
        parts = replaced("EPUB/book.opf", b'<itemref idref="second"', b'<itemref idref="map"')
    elif kind == "duplicate":
        parts = replaced("EPUB/book.opf", b'<itemref idref="second"', b'<itemref idref="first"')
    elif kind == "alias":
        parts = replaced(
            "EPUB/book.opf",
            b"</manifest>",
            b'<item id="alias" href="first.xhtml" media-type="application/xhtml+xml"/></manifest>',
        )
    else:
        parts = [(name, body) for name, body in parts if name != "EPUB/second.xhtml"]
    _, value = evidence(parts)
    assert value["status"] == "unconfirmed"
    assert value["text_sha256"] is value["spine_bytes_sha256"] is None
    assert value["reason"]


@pytest.mark.parametrize(
    "policy",
    [
        InspectionPolicy(max_records=1),
        InspectionPolicy(max_xml_nodes=1),
        InspectionPolicy(max_output_bytes=ENVELOPE_BYTES),
        InspectionPolicy(max_archive_bytes=1),
    ],
)
def test_exhausted_inspection_limits_never_leave_recorded_fingerprints(policy):
    result, value = evidence(policy=policy)
    assert result["structural_check"] == "failed"
    assert value["status"] == "unconfirmed"
    assert value["text_sha256"] is value["spine_bytes_sha256"] is None


def test_unrelated_structure_failure_clears_otherwise_complete_spine_evidence():
    result, value = evidence(replaced("EPUB/first.xhtml", b"map.svg#map", b"map.svg#missing"))
    assert result["inspection_complete"] is True and result["structural_check"] == "failed"
    assert value["status"] == "unconfirmed" and value["text_sha256"] is None


def test_text_outside_the_body_cannot_enter_the_body_fingerprint():
    _, original = evidence()
    _, changed = evidence(replaced("EPUB/second.xhtml", b"</body>", b"</body>Outside body text"))
    assert changed["status"] == "recorded"
    assert changed["text_sha256"] == original["text_sha256"]
    assert changed["spine_bytes_sha256"] != original["spine_bytes_sha256"]


@pytest.mark.parametrize("body", ["<p>a</p><p>b</p>", "<p>a</p>b"])
def test_normalized_text_uses_the_explicit_xml_text_budget(body):
    from xml.etree import ElementTree as ET

    from librarium.content_evidence import capture

    # Boundaries can add normalized spaces absent from XML text nodes.
    report = {
        "source_sha256": "a" * 64,
        "spine": [{"path": "doc.xhtml"}],
        "manifest": [{"path": "doc.xhtml", "media_type": "application/xhtml+xml"}],
        "policy": {"limits": {"max_xml_text_chars": 2}},
    }
    value = capture(
        report,
        {"doc.xhtml": ET.fromstring(page(body))},
        SimpleNamespace(read=lambda _: page(body)),
        {"{http://www.w3.org/1999/xhtml}p"},
        "{http://www.w3.org/1999/xhtml}",
    )
    assert value["status"] == "unconfirmed" and value["reason"] == "content_text_limit"


@pytest.mark.parametrize(
    "kind",
    [
        "binding",
        "status",
        "extra",
        "eligible",
        "digest",
        "char_count",
        "doc_count",
        "reason",
        "unconfirmed_digest",
        "unconfirmed_reason",
    ],
)
def test_saved_evidence_validator_rejects_changed_or_impossible_observations(kind):
    from librarium.content_evidence import unconfirmed, validate_content_evidence

    _, value = evidence()
    value = deepcopy(value)
    eligible = True
    if kind == "binding":
        value["source_sha256"] = "b" * 64
    elif kind == "status":
        value["status"] = "cleared"
    elif kind == "extra":
        value["extra"] = True
    elif kind == "eligible":
        eligible = False
    elif kind == "digest":
        value["text_sha256"] = "unknown"
    elif kind == "char_count":
        value["text_chars"] = True
    elif kind == "doc_count":
        value["spine_documents"] = 0
    elif kind == "reason":
        value["reason"] = "unavailable"
    else:
        value = unconfirmed(value["source_sha256"], "unavailable")
        if kind == "unconfirmed_digest":
            value["text_sha256"] = "a" * 64
        else:
            value["reason"] = "Unsafe prose."
    with pytest.raises(ValueError):
        validate_content_evidence(value, evidence()[0]["source_sha256"], eligible=eligible)


def test_saved_evidence_validator_accepts_recorded_and_unconfirmed():
    from librarium.content_evidence import unconfirmed, validate_content_evidence

    result, value = evidence()
    validate_content_evidence(value, result["source_sha256"])
    validate_content_evidence(
        unconfirmed(result["source_sha256"], "unavailable"), result["source_sha256"], eligible=False
    )


def test_document_text_capture_binds_each_normalized_body_to_its_spine_resource():
    result, _ = evidence()
    value = result["document_text_evidence"]
    assert value["policy"] == "librarium.epub-document-text.v2"
    assert value["status"] == "recorded" and value["reason"] is None
    assert value["source_sha256"] == result["source_sha256"]
    expected = [
        ("EPUB/first.xhtml", "Chapter 1 Unique synthetic story sentence. Next"),
        ("EPUB/second.xhtml", "Chapter 2 Invented ending."),
    ]
    raw = dict(fixture_parts())
    assert value["documents"] == [
        {
            "path": path,
            "spine_index": index,
            "resource_sha256": hashlib.sha256(raw[path]).hexdigest(),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text_chars": len(text),
        }
        for index, (path, text) in enumerate(expected)
    ]
    assert "Unique synthetic story" not in json.dumps(value)
    assert result["ready"] is False and result["content_acceptance"] == "not_checked"


def test_document_text_capture_survives_markup_without_claiming_whole_file_equality():
    result, _ = evidence()
    changed, _ = evidence(
        replaced("EPUB/first.xhtml", b"Unique synthetic", b"Uni<em>que</em>  synthetic")
    )
    first = result["document_text_evidence"]["documents"][0]
    second = changed["document_text_evidence"]["documents"][0]
    assert first["text_sha256"] == second["text_sha256"]
    assert first["text_chars"] == second["text_chars"]
    assert first["resource_sha256"] != second["resource_sha256"]
    assert result["source_sha256"] != changed["source_sha256"]


@pytest.mark.parametrize("kind", ["empty", "unsupported", "failure", "records", "output"])
def test_incomplete_document_text_capture_has_no_partial_rows(kind):
    parts = fixture_parts()
    policy = InspectionPolicy()
    if kind == "empty":
        parts = emptied("EPUB/first.xhtml", "EPUB/second.xhtml")
    elif kind == "unsupported":
        parts = replaced("EPUB/book.opf", b'<itemref idref="second"', b'<itemref idref="map"')
    elif kind == "failure":
        parts = replaced("EPUB/first.xhtml", b"map.svg#map", b"map.svg#missing")
    elif kind == "records":
        policy = InspectionPolicy(max_records=1)
    else:
        policy = InspectionPolicy(max_output_bytes=ENVELOPE_BYTES)
    result, _ = evidence(parts, policy=policy)
    value = result["document_text_evidence"]
    assert value["status"] == "unconfirmed" and value["documents"] == []
    assert value["source_sha256"] == result["source_sha256"]
    assert value["reason"]


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "policy",
        "scope",
        "missing",
        "order",
        "path",
        "digest",
        "resource",
        "chars",
        "total",
        "extra",
        "ineligible",
        "duplicate",
    ],
)
def test_document_text_validator_rejects_unbound_or_impossible_rows(mutation):
    from librarium.content_evidence import validate_document_text_evidence

    result, _ = evidence()
    result = deepcopy(result)
    value = result["document_text_evidence"]
    if mutation == "source":
        value["source_sha256"] = "a" * 64
    elif mutation == "policy":
        value["policy"] = "unknown"
    elif mutation == "scope":
        value["scope"] = "whole narrative"
    elif mutation == "missing":
        value["documents"].pop()
    elif mutation == "order":
        value["documents"].reverse()
    elif mutation == "path":
        value["documents"][0]["path"] = "another.xhtml"
    elif mutation == "digest":
        value["documents"][0]["text_sha256"] = "unknown"
    elif mutation == "resource":
        value["documents"][0]["resource_sha256"] = "b" * 64
    elif mutation == "chars":
        value["documents"][0]["text_chars"] = True
    elif mutation == "total":
        value["documents"][0]["text_chars"] += 1
    elif mutation == "extra":
        value["documents"][0]["verified"] = True
    elif mutation == "ineligible":
        result["structural_check"] = "failed"
    else:
        result["spine"][1]["path"] = result["spine"][0]["path"]
    with pytest.raises(ValueError):
        validate_document_text_evidence(result)


def test_document_text_validator_accepts_recorded_and_bound_unconfirmed_capture():
    from librarium.content_evidence import validate_document_text_evidence

    result, _ = evidence()
    validate_document_text_evidence(result)
    failed, _ = evidence(policy=InspectionPolicy(max_records=1))
    validate_document_text_evidence(failed)


@pytest.mark.parametrize(
    "mutation",
    [
        "value_type",
        "rows_type",
        "row_type",
        "status",
        "reason",
        "content_status",
        "content_docs",
        "content_chars",
        "limits_type",
        "member_limit",
        "record_limit",
        "name_limit",
        "text_limit",
        "rows_over_limit",
        "records_over_limit",
        "path_control",
        "spine_index_bool",
        "row_index_bool",
        "media",
        "duplicate_resource",
        "duplicate_manifest",
        "resource_digest",
        "unconfirmed_rows",
        "unconfirmed_reason",
        "unconfirmed_reason_type",
    ],
)
def test_document_text_validator_checks_cross_field_counts_paths_and_limits(mutation):
    from librarium.content_evidence import unconfirmed, validate_document_text_evidence

    result, _ = evidence()
    result = deepcopy(result)
    value = result["document_text_evidence"]
    limits = result["policy"]["limits"]
    if mutation == "value_type":
        result["document_text_evidence"] = []
    elif mutation == "rows_type":
        value["documents"] = {}
    elif mutation == "row_type":
        value["documents"][0] = None
    elif mutation == "status":
        value["status"] = "authenticated"
    elif mutation == "reason":
        value["reason"] = "unexpected"
    elif mutation == "content_status":
        result["content_evidence"] = unconfirmed(result["source_sha256"], "unavailable")
    elif mutation == "content_docs":
        result["content_evidence"]["spine_documents"] = 1
    elif mutation == "content_chars":
        result["content_evidence"]["text_chars"] += 1
    elif mutation == "limits_type":
        result["policy"]["limits"] = []
    elif mutation in {"member_limit", "record_limit", "name_limit", "text_limit"}:
        name = {
            "member_limit": "max_members",
            "record_limit": "max_records",
            "name_limit": "max_name_chars",
            "text_limit": "max_xml_text_chars",
        }[mutation]
        limits[name] = True
    elif mutation == "rows_over_limit":
        limits["max_members"] = 1
    elif mutation == "records_over_limit":
        limits["max_records"] = sum(len(result[key]) for key in ("spine", "manifest", "documents"))
    elif mutation == "path_control":
        value["documents"][0]["path"] = "EPUB/../first.xhtml"
    elif mutation == "spine_index_bool":
        result["spine"][0]["index"] = False
    elif mutation == "row_index_bool":
        value["documents"][0]["spine_index"] = False
    elif mutation == "media":
        next(item for item in result["manifest"] if item["path"] == value["documents"][0]["path"])[
            "media_type"
        ] = "image/svg+xml"
    elif mutation == "duplicate_resource":
        result["documents"].append(deepcopy(result["documents"][0]))
    elif mutation == "duplicate_manifest":
        result["manifest"].append(deepcopy(result["manifest"][0]))
    elif mutation == "resource_digest":
        result["documents"][0]["byte_sha256"] = "unknown"
    else:
        value["status"] = "unconfirmed"
        value["reason"] = "unavailable"
        if mutation != "unconfirmed_rows":
            value["documents"] = []
            value["reason"] = "private prose" if mutation == "unconfirmed_reason" else None
    with pytest.raises(ValueError):
        validate_document_text_evidence(result)


@pytest.mark.parametrize(
    "mutation", ["count", "content_count", "digest", "chars", "aggregate", "historical", "all"]
)
def test_empty_document_rows_must_agree_with_their_disclosed_counts(mutation):
    from librarium.content_evidence import (
        validate_content_evidence,
        validate_document_text_evidence,
    )

    result, _ = evidence(emptied("EPUB/second.xhtml"))
    validate_document_text_evidence(result)
    validate_content_evidence(result["content_evidence"], result["source_sha256"])
    result = deepcopy(result)
    value, content = result["document_text_evidence"], result["content_evidence"]
    if mutation == "count":
        value["documents"][1]["text_chars"] = 1
    elif mutation == "content_count":
        content["empty_spine_documents"] = 0
    elif mutation == "digest":
        value["documents"][1]["text_sha256"] = value["documents"][0]["text_sha256"]
    elif mutation == "chars":
        value["documents"][1]["text_chars"] = -1
    elif mutation == "aggregate":
        content["text_chars"] += 1
    elif mutation == "historical":
        result["policy"]["version"] = "librarium.epub-structure.v8"
    else:
        value["documents"][0]["text_chars"] = 0
        value["documents"][0]["text_sha256"] = value["documents"][1]["text_sha256"]
        content["empty_spine_documents"] = 2
    with pytest.raises(ValueError):
        validate_document_text_evidence(result)
        validate_content_evidence(content, result["source_sha256"])


def test_historical_content_evidence_keeps_its_original_shape():
    from librarium import content_evidence
    from librarium.content_evidence import validate_content_evidence

    _, value = evidence()
    historical = {k: v for k, v in value.items() if k != "empty_spine_documents"}
    historical["policy"] = "librarium.epub-content-evidence.v1"
    historical["scope"] = content_evidence.SCOPE
    with pytest.raises(ValueError):
        validate_content_evidence(historical, value["source_sha256"])
    validate_content_evidence(
        historical, value["source_sha256"], policy="librarium.epub-content-evidence.v1"
    )


def test_document_text_does_not_reinterpret_historical_capture():
    from librarium.content_evidence import validate_document_text_evidence

    result, _ = evidence()
    result["policy"]["version"] = "librarium.epub-structure.v7"
    with pytest.raises(ValueError):
        validate_document_text_evidence(result)
    result.pop("document_text_evidence")
    validate_document_text_evidence(result)


def title_parts():
    return replaced(
        "EPUB/first.xhtml",
        b"<body>",
        b'<body><section xmlns:epub="http://www.idpf.org/2007/ops" epub:type="titlepage">'
        b'<p epub:type="title">A synthetic volume</p>'
        b'<p epub:type="author">Fixture Author</p></section>',
    )


def test_optional_document_records_cannot_fail_structure_or_erase_existing_evidence(monkeypatch):
    from librarium.epub_inspection import _Budget

    original = _Budget.record
    before_rows = []

    def recording(budget, value):
        if set(value) == {"path", "spine_index", "resource_sha256", "text_sha256", "text_chars"}:
            before_rows.append(budget.records)
        return original(budget, value)

    monkeypatch.setattr(_Budget, "record", recording)
    evidence(title_parts())
    # Everything except the optional rows fits; the rows themselves do not.
    result, _ = evidence(title_parts(), policy=InspectionPolicy(max_records=before_rows[0] + 1))
    assert result["inspection_complete"] is True
    assert result["structural_check"] == "passed"
    assert result["content_evidence"]["status"] == "recorded"
    assert result["source_attribution"]["status"] == "recorded"
    assert result["document_text_evidence"]["status"] == "unconfirmed"
    assert result["document_text_evidence"]["reason"] == "record_limit"
    assert result["document_text_evidence"]["documents"] == []
    assert not any(item["severity"] == "error" for item in result["findings"])


def test_optional_document_output_cannot_erase_a_complete_structural_report():
    from librarium.content_evidence import unconfirmed_document_text

    baseline, _ = evidence(title_parts())
    baseline["document_text_evidence"] = unconfirmed_document_text(
        baseline["source_sha256"], "output_bytes_limit"
    )
    limit = len(json.dumps(baseline, ensure_ascii=True).encode()) + 32
    result, _ = evidence(title_parts(), policy=InspectionPolicy(max_output_bytes=limit))
    assert result["inspection_complete"] is True and result["structural_check"] == "passed"
    assert result["content_evidence"]["status"] == "recorded"
    assert result["source_attribution"]["status"] == "recorded"
    assert result["document_text_evidence"]["status"] == "unconfirmed"
    assert result["document_text_evidence"]["reason"] == "output_bytes_limit"
    assert result["document_text_evidence"]["documents"] == []
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= limit


def test_document_text_rows_share_the_inspection_record_budget(monkeypatch):
    from librarium.epub_inspection import _Budget

    original = _Budget.record
    row_counts = []

    def recording(budget, value):
        result = original(budget, value)
        if set(value) == {"path", "spine_index", "resource_sha256", "text_sha256", "text_chars"}:
            row_counts.append(budget.records)
        return result

    monkeypatch.setattr(_Budget, "record", recording)
    evidence()
    assert len(row_counts) == 2
    result, _ = evidence(policy=InspectionPolicy(max_records=row_counts[0]))
    assert result["document_text_evidence"]["status"] == "unconfirmed"
    assert result["document_text_evidence"]["documents"] == []
    assert result["content_evidence"]["status"] == "recorded"
    assert result["structural_check"] == "passed"
    assert not any(finding["code"] == "record_limit" for finding in result["findings"])


def test_document_text_preserves_non_linear_spine_order_and_body_boundaries():
    first, _ = evidence()
    reordered, _ = evidence(
        replaced(
            "EPUB/book.opf",
            b'<itemref idref="first"/><itemref idref="second" linear="no"/>',
            b'<itemref idref="second" linear="no"/><itemref idref="first"/>',
        )
    )
    assert [row["text_sha256"] for row in first["document_text_evidence"]["documents"]] == [
        row["text_sha256"] for row in reversed(reordered["document_text_evidence"]["documents"])
    ]
    assert [row["spine_index"] for row in reordered["document_text_evidence"]["documents"]] == [
        0,
        1,
    ]
    changed, _ = evidence(replaced("EPUB/second.xhtml", b"</body>", b"</body>Outside body text"))
    assert (
        changed["document_text_evidence"]["documents"][1]["text_sha256"]
        == first["document_text_evidence"]["documents"][1]["text_sha256"]
    )


@pytest.mark.parametrize(
    "change", [b"unique", b"Unique!", b'<span hidden="hidden">Hidden</span>Unique']
)
def test_document_text_keeps_case_punctuation_and_hidden_source_text(change):
    first, _ = evidence()
    second, _ = evidence(replaced("EPUB/first.xhtml", b"Unique", change))
    assert (
        first["document_text_evidence"]["documents"][0]["text_sha256"]
        != second["document_text_evidence"]["documents"][0]["text_sha256"]
    )


@pytest.mark.parametrize(
    "target,media", [("map.svg", "image/svg+xml"), ("nav.xhtml", "application/xhtml+xml")]
)
def test_nonspine_manifest_alias_keeps_document_text_report_readable(target, media):
    from librarium.content_evidence import validate_document_text_evidence

    addition = f'<item id="alias" href="{target}" media-type="{media}"/>'.encode()
    result, _ = evidence(replaced("EPUB/book.opf", b"</manifest>", addition + b"</manifest>"))
    assert result["structural_check"] == "passed"
    assert result["document_text_evidence"]["status"] == "recorded"
    validate_document_text_evidence(result)


def test_nonspine_manifest_alias_count_uses_record_budget_instead_of_archive_members():
    from librarium.content_evidence import validate_document_text_evidence

    addition = b"".join(
        f'<item id="alias{index}" href="map.svg" media-type="image/svg+xml"/>'.encode()
        for index in range(4)
    )
    result, _ = evidence(
        replaced("EPUB/book.opf", b"</manifest>", addition + b"</manifest>"),
        policy=InspectionPolicy(max_members=7),
    )
    assert len(result["manifest"]) > result["policy"]["limits"]["max_members"]
    assert result["structural_check"] == "passed"
    assert result["document_text_evidence"]["status"] == "recorded"
    validate_document_text_evidence(result)
