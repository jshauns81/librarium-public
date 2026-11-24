"""Declared identifier types are bounded source observations, not identity votes."""

import sqlite3
from contextlib import closing
from copy import deepcopy

import pytest
import test_catalogue
from librarium import package_identifiers

catalogue_fixture = test_catalogue.catalogue
ONIX = "http://www.editeur.org/ONIX/book/codelists/current.html#"


def captured(value="9780306406157", *, version="3.0", scheme=None, code="15", prefix=None):
    return {
        "schema_version": "librarium.epub-identifiers.v1",
        "package_path": "EPUB/book.opf",
        "package_sha256": "d" * 64,
        "package_version": version,
        "unique_identifier": "book",
        "prefix": prefix,
        "entries": [
            {
                "source_index": 2,
                "value": value,
                "id": "book",
                "xml_id": None,
                "opf_scheme": scheme,
                "id_count": 1,
                "xml_id_count": 0,
                "text_only": True,
            }
        ],
        "refinements": []
        if code is None
        else [
            {
                "source_index": 3,
                "property": "identifier-type",
                "refines": "#book",
                "scheme": "onix:codelist5",
                "value": code,
                "text_only": True,
                "target_id": "book",
                "target_count": 1,
                "target_source_index": 2,
                "association": "identifier",
            }
        ],
    }


@pytest.fixture
def assess(catalogue_fixture):
    _, path = catalogue_fixture

    def run(evidence, complete=True, values=None):
        original = deepcopy(evidence)
        if values is None:
            values = [e["value"] for e in evidence["entries"]]
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            result = package_identifiers.compare_isbns(
                values, db, "w_fixture", complete, evidence=evidence
            )
        assert evidence == original
        return result

    return run


@pytest.mark.parametrize(
    "value,code,basis",
    [
        ("9780306406157", "15", "onix_isbn13"),
        ("0306406152", "02", "onix_isbn10"),
        ("urn:isbn:9780306406157", "15", "urn"),
    ],
)
def test_bare_isbns_need_a_supported_type_with_source_provenance(assess, value, code, basis):
    result = assess(captured(value, code=code))
    assert result["capture"] == "recorded"
    assert result["status"] == "same"
    entry = result["entries"][0]
    assert entry["source"] == value and entry["canonical_isbn13"] == "9780306406157"
    assert entry["basis"] == basis
    assert entry["source_position"] == {
        "path": "EPUB/book.opf",
        "document_sha256": "d" * 64,
        "source_index": 2,
    }
    assert entry["declarations"][0]["scheme_iri"] == ONIX + "codelist5"


def test_epub2_qualified_scheme_is_a_declaration_without_a_refinement(assess):
    result = assess(captured("0-306-40615-2", version="2.0", scheme="ISBN", code=None))
    assert result["status"] == "same"
    entry = result["entries"][0]
    assert entry["basis"] == "opf_scheme"
    assert entry["declarations"] == [
        {
            "kind": "opf_scheme",
            "source_index": 2,
            "value": "ISBN",
            "scheme": None,
            "scheme_iri": None,
            "refines": None,
            "association": "identifier",
        }
    ]


@pytest.mark.parametrize("scheme", [None, "ISBN", "codelist5", "other:codelist5"])
def test_a_code_without_resolved_onix_scheme_does_not_declare_an_isbn(assess, scheme):
    evidence = captured()
    evidence["refinements"][0]["scheme"] = scheme
    result = assess(evidence)
    assert result["status"] == "unknown"
    assert result["entries"][0]["status"] == "unsupported"
    assert "unsupported_identifier_type_scheme" in result["entries"][0]["reason_codes"]


@pytest.mark.parametrize(
    "prefix,scheme,expected",
    [
        ("books: " + ONIX, "books:codelist5", "same"),
        ("onix: " + ONIX, "onix:codelist5", "same"),
        ("onix: https://example.invalid/types#", "onix:codelist5", "unknown"),
        (
            "books: https://www.editeur.org/ONIX/book/codelists/current.html#",
            "books:codelist5",
            "unknown",
        ),
        ("books: " + ONIX + " books: " + ONIX, "books:codelist5", "unknown"),
        ("books: " + ONIX + " onix:", "onix:codelist5", "unknown"),
        ("", "onix:codelist5", "unknown"),
        ("books:\u00a0" + ONIX, "books:codelist5", "unknown"),
        ("books:\t" + ONIX, "books:codelist5", "unknown"),
        (
            "books: http:",
            "books://www.editeur.org/ONIX/book/codelists/current.html#codelist5",
            "unknown",
        ),
        (
            "books: http://www.editeur.org/ONIX/book/codelists/",
            "books:current.html#codelist5",
            "same",
        ),
    ],
    ids=[
        "books-prefix",
        "onix-prefix",
        "foreign-binding",
        "unrecognized-uri",
        "duplicate-prefix",
        "empty-prefix-binding",
        "missing-prefix",
        "nonbreaking-separator",
        "tab-separator",
        "colon-only-binding",
        "split-codelist-uri",
    ],
)
def test_explicit_prefix_bindings_override_reserved_names_without_uri_guessing(
    assess, prefix, scheme, expected
):
    evidence = captured(prefix=prefix)
    evidence["refinements"][0]["scheme"] = scheme
    assert assess(evidence)["status"] == expected


@pytest.mark.parametrize("code", ["03", "06", "ISBN", "2", "", "99"])
def test_other_codes_and_free_text_are_unassessed_not_conformance_failures(assess, code):
    result = assess(captured(code=code))
    assert result["status"] == "unknown"
    assert result["entries"][0]["status"] == "unsupported"
    assert "unsupported_identifier_type_code" in result["entries"][0]["reason_codes"]


@pytest.mark.parametrize("value,code", [("0306406152", "15"), ("9780306406157", "02")])
def test_onix_type_length_is_checked_before_canonical_conversion(assess, value, code):
    entry = assess(captured(value, code=code))["entries"][0]
    assert entry["status"] == "invalid"
    assert "isbn_type_length_mismatch" in entry["reason_codes"]


@pytest.mark.parametrize("change", ["duplicate", "contradictory", "ambiguous_target", "markup"])
def test_unusable_type_evidence_cannot_be_bypassed_by_a_favorable_urn(assess, change):
    evidence = captured("urn:isbn:9780306406157")
    if change == "duplicate":
        other = deepcopy(evidence["refinements"][0])
        other["source_index"] = 4
        evidence["refinements"].append(other)
    elif change == "contradictory":
        evidence["refinements"][0]["value"] = "06"
    elif change == "ambiguous_target":
        evidence["refinements"][0].update(
            association="ambiguous", target_count=2, target_source_index=None
        )
    else:
        evidence["refinements"][0]["text_only"] = False
    result = assess(evidence)
    assert result["status"] == "ambiguous"
    assert result["entries"][0]["status"] == "ambiguous"
    assert result["entries"][0]["editions"] == []


def test_another_element_and_refinement_chains_do_not_type_a_bare_identifier(assess):
    evidence = captured()
    evidence["refinements"][0].update(
        association="other", target_id="source", target_source_index=6
    )
    assert assess(evidence)["entries"][0]["status"] == "unsupported"
    evidence["refinements"][0].update(
        association="other", target_id="other-meta", target_source_index=3
    )
    assert assess(evidence)["entries"][0]["status"] == "unsupported"


def test_identifier_child_markup_is_not_flattened_into_affirmative_isbn_evidence(assess):
    evidence = captured("urn:isbn:9780306406157", code=None)
    evidence["entries"][0]["text_only"] = False
    entry = assess(evidence)["entries"][0]
    assert entry["status"] == "unsupported"
    assert entry["reason_codes"] == ["identifier_not_text"]


def test_historical_absence_and_captured_empty_evidence_are_distinct(assess):
    legacy = assess(None, values=["urn:isbn:9780306406157"])
    assert legacy["capture"] == "not_recorded" and legacy["status"] == "same"
    assert legacy["entries"][0]["basis"] == "urn"
    assert legacy["entries"][0]["source_position"] is None
    assert legacy["entries"][0]["declarations"] == []
    evidence = captured(code=None)
    evidence["entries"] = []
    empty = assess(evidence)
    assert empty["capture"] == "recorded" and empty["entries"] == []
    assert (
        assess(None, complete=False, values=["urn:isbn:9780306406157"])["capture"] == "incomplete"
    )


def test_incomplete_inspection_never_uses_declared_types_for_catalogue_agreement(assess):
    entry = assess(captured(), complete=False)["entries"][0]
    assert entry["status"] == "unknown" and entry["editions"] == []
    assert "inspection_incomplete" in entry["reason_codes"]


def test_declaration_references_are_bounded_before_catalogue_lookup(assess):
    from librarium.catalogue import CatalogueError

    evidence = captured()
    first = evidence["refinements"][0]
    evidence["refinements"] = [{**first, "source_index": n + 3} for n in range(257)]
    with pytest.raises(CatalogueError) as error:
        assess(evidence)
    assert error.value.status == 422


@pytest.mark.parametrize(
    "ident,reference,state",
    [
        ("isbn number", "isbn%20number", "unknown"),
        ("123", "123", "unknown"),
        ("é-book", "%C3%A9-book", "same"),
    ],
)
def test_refinements_require_legal_xml_ids_in_actual_packages(assess, ident, reference, state):
    from librarium.identifier_evidence import validate_identifier_evidence
    from test_epub_inspection import archive, fixture_parts, inspect

    addition = (
        f'<dc:identifier id="{ident}">9780306406157</dc:identifier>'
        f'<meta property="identifier-type" refines="#{reference}" scheme="onix:codelist5">15</meta>'
    ).encode()
    parts = [
        (
            path,
            body.replace(b"</metadata>", addition + b"</metadata>")
            if path == "EPUB/book.opf"
            else body,
        )
        for path, body in fixture_parts()
    ]
    report = inspect(archive(parts))
    evidence = validate_identifier_evidence(report)
    result = assess(evidence)
    assert result["status"] == state
    assert result["entries"][-1]["status"] == ("unsupported" if state == "unknown" else "same")


def test_non_ascii_meta_padding_is_preserved_instead_of_manufacturing_a_type_code(assess):
    from librarium.identifier_evidence import validate_identifier_evidence
    from test_epub_inspection import archive, fixture_parts, inspect

    addition = (
        b'<dc:identifier id="isbn">9780306406157</dc:identifier>'
        b'<meta property="identifier-type" refines="#isbn" scheme="onix:codelist5">&#160;15&#160;</meta>'
    )
    report = inspect(
        archive(
            [
                (
                    p,
                    b.replace(b"</metadata>", addition + b"</metadata>")
                    if p == "EPUB/book.opf"
                    else b,
                )
                for p, b in fixture_parts()
            ]
        )
    )
    evidence = validate_identifier_evidence(report)
    assert evidence["refinements"][0]["value"] == "\u00a015\u00a0"
    assert assess(evidence)["status"] == "unknown"


@pytest.mark.parametrize("scheme", ["\u00a0ISBN\u00a0", "IſBN"])
def test_non_ascii_opf_scheme_text_does_not_manufacture_a_supported_scheme(assess, scheme):
    from librarium.identifier_evidence import validate_identifier_evidence
    from test_epub_identifiers import publication
    from test_epub_inspection import inspect

    data, _ = publication(
        f'<dc:identifier opf:scheme="{scheme}">9780306406157</dc:identifier>',
        version="2.0",
    )
    evidence = validate_identifier_evidence(inspect(data))
    assert evidence["entries"][0]["opf_scheme"] == scheme
    assert assess(evidence)["status"] == "unknown"


@pytest.mark.parametrize("custom_prefix", [False, True])
def test_expanded_scheme_iri_can_exceed_either_raw_attribute_limit(assess, custom_prefix):
    from librarium.identifier_evidence import validate_identifier_evidence
    from test_epub_identifiers import publication
    from test_epub_inspection import inspect

    base = "https://example.invalid/" + "b" * (509 - len("https://example.invalid/"))
    prefix = "x: " + base if custom_prefix else None
    reference = "r" * 510 if custom_prefix else "x" * 500
    scheme = ("x:" if custom_prefix else "onix:") + reference
    expected = (base if custom_prefix else ONIX) + reference
    data, _ = publication(
        '<dc:identifier id="isbn">9780306406157</dc:identifier>'
        f'<meta property="identifier-type" refines="#isbn" scheme="{scheme}">15</meta>',
        attributes=f'prefix="{prefix}"' if prefix else "",
    )
    evidence = validate_identifier_evidence(inspect(data))
    assert len(scheme) <= 512 and (prefix is None or len(prefix) <= 512)
    assert 512 < len(expected) <= 1024
    result = assess(evidence)
    entry = result["entries"][0]
    assert result["status"] == "unknown" and entry["status"] == "unsupported"
    assert entry["reason_codes"] == ["unsupported_identifier_type_scheme"]
    assert entry["declarations"][0]["scheme"] == scheme
    assert entry["declarations"][0]["scheme_iri"] == expected
