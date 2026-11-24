"""Identifier declarations remain bounded observations of synthetic EPUB sources."""

import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
from librarium.epub_inspection import ENVELOPE_BYTES, InspectionPolicy
from test_epub_inspection import archive, codes, fixture_parts, inspect


def publication(metadata, *, version="3.0", attributes="", after=""):
    parts = []
    for path, body in fixture_parts():
        if path == "EPUB/book.opf":
            tail = body.split(b"</metadata>", 1)[1]
            body = (
                f'<package xmlns="http://www.idpf.org/2007/opf" '
                f'xmlns:dc="http://purl.org/dc/elements/1.1/" '
                f'xmlns:opf="http://www.idpf.org/2007/opf" version="{version}" '
                f"{attributes}><metadata>{metadata}</metadata>{after}"
            ).encode() + tail
        parts.append((path, body))
    return archive(parts), dict(parts)["EPUB/book.opf"]


def capture(metadata, **kwargs):
    data, package = publication(metadata, **kwargs)
    report = inspect(data)
    assert report["inspection_complete"] is True, report["findings"]
    return report, package


def test_v5_captures_namespace_qualified_declarations_and_source_provenance():
    metadata = (
        '<dc:identifier id="uuid">urn:uuid:synthetic</dc:identifier>'
        '<dc:identifier id="isbn" opf:scheme="ISBN">0-306-40615-2</dc:identifier>'
        '<meta refines="#isbn" property="identifier-type" scheme="onix:codelist5">02</meta>'
    )
    data, package = publication(
        metadata, attributes='unique-identifier="uuid" prefix="o: https://example.invalid/"'
    )
    before = hashlib.sha256(data).hexdigest()
    report = inspect(data)
    evidence = report["identifier_evidence"]
    assert report["policy"]["version"] == "librarium.epub-structure.v10"
    assert report["package"]["byte_sha256"] == hashlib.sha256(package).hexdigest()
    assert evidence == {
        "schema_version": "librarium.epub-identifiers.v1",
        "package_path": "EPUB/book.opf",
        "package_sha256": hashlib.sha256(package).hexdigest(),
        "package_version": "3.0",
        "unique_identifier": "uuid",
        "prefix": "o: https://example.invalid/",
        "entries": [
            {
                "source_index": 2,
                "value": "urn:uuid:synthetic",
                "id": "uuid",
                "xml_id": None,
                "id_count": 1,
                "xml_id_count": 0,
                "opf_scheme": None,
                "text_only": True,
            },
            {
                "source_index": 3,
                "value": "0-306-40615-2",
                "id": "isbn",
                "xml_id": None,
                "id_count": 1,
                "xml_id_count": 0,
                "opf_scheme": "ISBN",
                "text_only": True,
            },
        ],
        "refinements": [
            {
                "source_index": 4,
                "property": "identifier-type",
                "refines": "#isbn",
                "scheme": "onix:codelist5",
                "value": "02",
                "text_only": True,
                "target_id": "isbn",
                "target_count": 1,
                "target_source_index": 3,
                "association": "identifier",
            }
        ],
    }
    assert hashlib.sha256(data).hexdigest() == before
    assert report["ready"] is False and report["epubcheck"] == "not_run"


def test_absent_and_empty_attributes_remain_distinct_and_xmlns_is_not_a_prefix_mapping():
    report, _ = capture(
        '<dc:identifier scheme="ISBN">9780306406157</dc:identifier>',
        attributes='xmlns:onix="https://example.invalid/"',
    )
    assert report["identifier_evidence"]["unique_identifier"] is None
    assert report["identifier_evidence"]["prefix"] is None
    entry = report["identifier_evidence"]["entries"][0]
    assert entry["id"] is entry["xml_id"] is entry["opf_scheme"] is None
    assert entry["id_count"] == entry["xml_id_count"] == 0
    report, _ = capture(
        '<dc:identifier id="" xml:id="" opf:scheme="">9780306406157</dc:identifier>',
        attributes='unique-identifier="" prefix=""',
    )
    evidence = report["identifier_evidence"]
    assert evidence["unique_identifier"] == evidence["prefix"] == ""
    assert evidence["entries"][0]["opf_scheme"] == ""
    assert evidence["entries"][0]["id_count"] == evidence["entries"][0]["xml_id_count"] == 0


def test_legacy_epub2_dc_metadata_container_is_the_selected_metadata_scope():
    report, _ = capture(
        '<dc-metadata><dc:identifier id="isbn" opf:scheme="ISBN">0306406152</dc:identifier><dc:title>Literal title</dc:title></dc-metadata><x-metadata/>',
        version="2.0",
    )
    assert report["metadata"] == [
        {"name": "identifier", "text": "0306406152"},
        {"name": "title", "text": "Literal title"},
    ]
    assert report["identifier_evidence"]["entries"][0]["source_index"] == 3
    assert report["identifier_evidence"]["entries"][0]["opf_scheme"] == "ISBN"


@pytest.mark.parametrize(
    "metadata,version",
    [
        ("<dc-metadata/><dc-metadata/>", "2.0"),
        (
            "<dc:identifier>one</dc:identifier><dc-metadata><dc:identifier>two</dc:identifier></dc-metadata>",
            "2.0",
        ),
        ("<dc-metadata><dc:identifier>one</dc:identifier></dc-metadata>", "3.0"),
    ],
    ids=[
        "duplicate-containers",
        "mixed-containers",
        "legacy-container-in-epub3",
    ],
)
def test_unsupported_or_ambiguous_metadata_containers_refuse_instead_of_skipping_values(
    metadata, version
):
    report = inspect(publication(metadata, version=version)[0])
    assert report["inspection_complete"] is False
    assert report["identifier_evidence"] is None
    assert "unsupported_package_metadata" in codes(report)


def test_multiple_or_missing_package_metadata_refuses_without_declaration_assurance():
    data, _ = publication(
        "<dc:identifier>one</dc:identifier>",
        after="<metadata><dc:identifier>two</dc:identifier></metadata>",
    )
    report = inspect(data)
    assert "multiple_package_metadata" in codes(report)
    assert report["identifier_evidence"] is None
    data, _ = publication("<dc:identifier>one</dc:identifier>")
    parts = [
        (p, b.replace(b"<metadata><dc:identifier>one</dc:identifier></metadata>", b""))
        for p, b in _parts(data)
    ]
    report = inspect(archive(parts))
    assert "missing_package_metadata" in codes(report)
    assert report["identifier_evidence"] is None


def _parts(data):
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        return [(name, zipped.read(name)) for name in zipped.namelist()]


@pytest.mark.parametrize("refines", ["#isbn", "book.opf#isbn", "./book.opf#isbn", "#%69sbn"])
def test_same_package_references_bind_decoded_targets_without_fetching(refines):
    report, _ = capture(
        f'<dc:identifier id="isbn">9780306406157</dc:identifier><meta property="identifier-type" refines="{refines}" scheme="onix:codelist5">15</meta>'
    )
    refinement = report["identifier_evidence"]["refinements"][0]
    assert refinement["target_id"] == "isbn" and refinement["target_count"] == 1
    assert refinement["association"] == "identifier" and refinement["target_source_index"] == 2


@pytest.mark.parametrize(
    "refines,association,target",
    [
        ("#missing", "unresolved", "missing"),
        (None, "unresolved", None),
        ("", "unresolved", None),
        ("other.opf#isbn", "unsupported", None),
        ("book.opf?x#isbn", "unsupported", None),
        ("https://example.invalid/book.opf#isbn", "unsupported", None),
        ("#%broken", "unsupported", None),
    ],
)
def test_missing_or_unsupported_refinements_remain_literal(refines, association, target):
    attribute = "" if refines is None else f' refines="{refines}"'
    report, _ = capture(
        f'<dc:identifier id="isbn">9780306406157</dc:identifier><meta property="identifier-type"{attribute}>15</meta>'
    )
    item = report["identifier_evidence"]["refinements"][0]
    assert item["refines"] == refines
    assert item["association"] == association and item["target_id"] == target
    assert item["target_count"] == 0 and item["target_source_index"] is None


def test_other_targets_include_source_and_meta_without_becoming_identifier_declarations():
    report, _ = capture(
        '<dc:identifier id="isbn">9780306406157</dc:identifier><dc:source id="source">Other edition</dc:source><meta id="type" property="identifier-type" refines="#source">15</meta><meta property="identifier-type" refines="#type">15</meta>'
    )
    assert [r["association"] for r in report["identifier_evidence"]["refinements"]] == [
        "other",
        "other",
    ]
    assert [r["target_source_index"] for r in report["identifier_evidence"]["refinements"]] == [
        3,
        4,
    ]


def test_package_wide_id_census_counts_aliases_by_element_and_keeps_separate_alias_counts():
    report, _ = capture(
        '<dc:identifier id="isbn" xml:id="alternate">9780306406157</dc:identifier><foreign xmlns="urn:synthetic" xml:id="alternate"/><meta property="identifier-type" refines="#isbn">15</meta><meta property="identifier-type" refines="#alternate">15</meta>'
    )
    evidence = report["identifier_evidence"]
    assert evidence["entries"][0]["id_count"] == 1
    assert evidence["entries"][0]["xml_id_count"] == 2
    assert [r["association"] for r in evidence["refinements"]] == ["identifier", "ambiguous"]
    assert evidence["refinements"][1]["target_count"] == 2
    report, _ = capture(
        '<dc:identifier id="isbn" xml:id="isbn">9780306406157</dc:identifier><meta property="identifier-type" refines="#isbn">15</meta>'
    )
    assert report["identifier_evidence"]["entries"][0]["id_count"] == 1
    assert report["identifier_evidence"]["entries"][0]["xml_id_count"] == 1
    assert report["identifier_evidence"]["refinements"][0]["association"] == "identifier"


def test_manifest_and_duplicate_identifier_ids_keep_refinement_ambiguity():
    report, _ = capture(
        '<dc:identifier id="second">9780306406157</dc:identifier><dc:identifier id="second">0306406152</dc:identifier><meta property="identifier-type" refines="#second">15</meta>'
    )
    evidence = report["identifier_evidence"]
    assert [e["id_count"] for e in evidence["entries"]] == [3, 3]
    assert evidence["refinements"][0]["association"] == "ambiguous"
    assert evidence["refinements"][0]["target_count"] == 3
    assert evidence["refinements"][0]["target_source_index"] is None


def test_only_selected_direct_metadata_is_captured_and_nested_markup_is_not_plain_text():
    report, _ = capture(
        '<dc:identifier id="isbn">978<foreign xmlns="urn:synthetic">0306406157</foreign></dc:identifier><meta property="identifier-type" refines="#isbn">1<foreign xmlns="urn:synthetic">5</foreign></meta><wrapper><dc:identifier id="nested">9780140328721</dc:identifier><meta property="identifier-type">15</meta></wrapper><meta property="p:identifier-type" refines="#isbn">15</meta>'
    )
    evidence = report["identifier_evidence"]
    assert len(evidence["entries"]) == len(evidence["refinements"]) == 1
    assert evidence["entries"][0]["text_only"] is False
    assert evidence["refinements"][0]["text_only"] is False


@pytest.mark.parametrize("attribute", ["id", "xml:id", "opf:scheme"])
def test_identifier_attributes_share_field_budgets(attribute):
    report = inspect(
        publication(f'<dc:identifier {attribute}="' + "x" * 513 + '">value</dc:identifier>')[0]
    )
    assert "field_limit" in codes(report) and report["identifier_evidence"] is None


def test_prefix_refinement_text_records_and_output_share_existing_budgets():
    report = inspect(
        publication(
            "<dc:identifier>value</dc:identifier>", attributes='prefix="' + "x" * 513 + '"'
        )[0]
    )
    assert "field_limit" in codes(report)
    report = inspect(publication('<meta property="identifier-type">' + "x" * 257 + "</meta>")[0])
    assert "metadata_limit" in codes(report)
    metadata = "".join(f'<dc:identifier id="i{n}">value{n}</dc:identifier>' for n in range(30))
    report = inspect(publication(metadata)[0], policy=replace(InspectionPolicy(), max_records=40))
    assert "record_limit" in codes(report) and report["identifier_evidence"] is None
    report = inspect(
        publication(metadata)[0],
        policy=replace(InspectionPolicy(), max_output_bytes=ENVELOPE_BYTES),
    )
    assert "output_bytes_limit" in codes(report) and report["identifier_evidence"] is None


def test_xml_base_remains_refused_before_identifier_capture():
    report = inspect(publication('<dc:identifier xml:base="">value</dc:identifier>')[0])
    assert "unsupported_base_reference" in codes(report)
    assert report["identifier_evidence"] is None


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "path",
        "digest",
        "version",
        "source_index",
        "entry_order",
        "entry_value",
        "id_count",
        "text_only",
        "refinement_index",
        "target_count",
        "target_index",
        "target_id",
        "association",
        "attribute_type",
        "missing_opf_scheme",
        "missing_prefix",
        "missing_scheme",
        "missing_target_position",
    ],
)
def test_validation_refuses_malformed_or_unbound_complete_evidence(change):
    from librarium.identifier_evidence import validate_identifier_evidence

    report, _ = capture(
        '<dc:identifier id="isbn">9780306406157</dc:identifier><meta property="identifier-type" refines="#isbn" scheme="onix:codelist5">15</meta>'
    )
    evidence = report["identifier_evidence"]
    if change == "schema":
        evidence["schema_version"] = "unknown"
    if change == "path":
        evidence["package_path"] = "other.opf"
    if change == "digest":
        evidence["package_sha256"] = "a" * 64
    if change == "version":
        evidence["package_version"] = "2.0"
    if change == "source_index":
        evidence["entries"][0]["source_index"] = True
    if change == "entry_order":
        evidence["entries"].append(deepcopy(evidence["entries"][0]))
    if change == "entry_value":
        evidence["entries"][0]["value"] = "different"
    if change == "id_count":
        evidence["entries"][0]["id_count"] = 0
    if change == "text_only":
        evidence["entries"][0]["text_only"] = 1
    if change == "refinement_index":
        evidence["refinements"][0]["source_index"] = 2
    if change == "target_count":
        evidence["refinements"][0]["target_count"] = 2
    if change == "target_index":
        evidence["refinements"][0]["target_source_index"] = 8
    if change == "target_id":
        evidence["refinements"][0]["target_id"] = "elsewhere"
    if change == "association":
        evidence["refinements"][0]["association"] = "trusted"
    if change == "attribute_type":
        evidence["prefix"] = []
    if change == "missing_opf_scheme":
        del evidence["entries"][0]["opf_scheme"]
    if change == "missing_prefix":
        del evidence["prefix"]
    if change == "missing_scheme":
        del evidence["refinements"][0]["scheme"]
    if change == "missing_target_position":
        evidence["refinements"][0].update(
            refines="#missing", target_id="missing", target_count=0, association="unresolved"
        )
        del evidence["refinements"][0]["target_source_index"]
    with pytest.raises(ValueError):
        validate_identifier_evidence(report)


def test_validation_preserves_historical_absence_and_allows_incomplete_null_capture():
    from librarium.identifier_evidence import validate_identifier_evidence

    report, _ = capture("<dc:identifier>urn:uuid:synthetic</dc:identifier>")
    before = deepcopy(report)
    assert validate_identifier_evidence(report) == report["identifier_evidence"]
    assert report == before
    for number in (1, 2, 3, 4):
        historical = deepcopy(report)
        historical["policy"]["version"] = f"librarium.epub-structure.v{number}"
        historical.pop("identifier_evidence")
        assert validate_identifier_evidence(historical) is None
        historical["identifier_evidence"] = report["identifier_evidence"]
        with pytest.raises(ValueError):
            validate_identifier_evidence(historical)
    report["inspection_complete"] = False
    report["identifier_evidence"] = None
    assert validate_identifier_evidence(report) is None
    report["inspection_complete"] = True
    with pytest.raises(ValueError):
        validate_identifier_evidence(report)
