"""Synthetic ISBN observations never identify book contents or alter source evidence."""

import sqlite3
from contextlib import closing
from copy import deepcopy

import pytest
import test_catalogue
from librarium import catalogue as reader
from librarium import package_comparison

catalogue_fixture = test_catalogue.catalogue


def envelope(values, complete=True):
    return {
        "job_id": "synthetic-job",
        "source_sha256": "a" * 64,
        "report_sha256": "b" * 64,
        "report": {
            "source_sha256": "a" * 64,
            "expected_sha256": "a" * 64,
            "policy": {"version": "librarium.epub-structure.v4"},
            "inspection_complete": complete,
            "metadata": [
                {"name": "title", "text": "Fixture: The Glass Meridian"},
                {"name": "creator", "text": "Fixture Author"},
                *({"name": "identifier", "text": value} for value in values),
            ],
        },
    }


@pytest.fixture
def compare(catalogue_fixture):
    _, path = catalogue_fixture

    def run(values, complete=True):
        original = envelope(values, complete)
        before = deepcopy(original)
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            result = package_comparison.compare(
                original,
                db,
                {"version": "2026.10.27.1", "sha256": "c" * 64, "fixture": True},
                "w_fixture",
            )
        assert original == before
        return result

    return run, path


def add_edition(path, edition="e_other", work="w_other", isbn="9780306406157", fmt="ebook"):
    with closing(sqlite3.connect(path)) as db, db:
        if work:
            db.execute("INSERT OR IGNORE INTO work(id,title) VALUES (?,?)", (work, work))
        db.execute(
            "INSERT INTO edition(id,work_id,format,isbn13) VALUES (?,?,?,?)",
            (edition, work, fmt, isbn),
        )


@pytest.mark.parametrize(
    "value,canonical",
    [
        ("urn:isbn:9780306406157", "9780306406157"),
        ("URN:ISBN:0-306-40615-2", "9780306406157"),
        ("urn:isbn:0306406152", "9780306406157"),
    ],
)
def test_explicit_isbn_urns_match_preserved_catalogue_editions(compare, value, canonical):
    run, _ = compare
    result = run([value])
    assert result["schema_version"] == "librarium.package-comparison.v3"
    assert result["policy_version"] == "librarium.package-metadata.v3"
    assert result["isbn"]["status"] == "same"
    assert [
        {k: v for k, v in e.items() if k in {"source", "canonical_isbn13", "status", "editions"}}
        for e in result["isbn"]["entries"]
    ] == [
        {
            "source": value,
            "canonical_isbn13": canonical,
            "status": "same",
            "editions": [
                {
                    "edition_id": "e_fixture",
                    "work_id": "w_fixture",
                    "format": "ebook",
                    "disputed": False,
                }
            ],
        }
    ]
    assert result["metadata_agrees"] is True and result["ready"] is False
    assert "authenticate" in result["isbn"]["scope"]


@pytest.mark.parametrize(
    "value",
    [
        "urn:uuid:9780306406157",
        "9780306406157",
        "ISBN 9780306406157",
        "",
        "isbn:0306406152",
        "urn:isbn:9780306406157#one",
    ],
)
def test_untyped_or_other_namespace_values_are_not_assumed_to_be_isbns(compare, value):
    result = compare[0]([value])
    assert result["isbn"]["status"] == "unknown"
    assert [
        {k: v for k, v in e.items() if k in {"source", "canonical_isbn13", "status", "editions"}}
        for e in result["isbn"]["entries"]
    ] == [
        {
            "source": value,
            "canonical_isbn13": None,
            "status": "unsupported",
            "editions": [],
        }
    ]


@pytest.mark.parametrize(
    "value",
    [
        "urn:isbn:9780306406158",
        "urn:isbn:0306406153",
        "urn:isbn:1234567890128",
        "urn:isbn:９７８０３０６４０６１５７",
        "urn:isbn:%399780306406157",
        "urn:isbn:978 0306406157",
        "urn:isbn:",
        "urn:isbn:9790000000001",
    ],
    ids=[
        "isbn13-checksum",
        "isbn10-checksum",
        "unsupported-prefix",
        "fullwidth-digits",
        "percent-encoded",
        "embedded-space",
        "empty",
        "unsupported-range",
    ],
)
def test_invalid_or_unsupported_declared_urn_syntax_cannot_establish_agreement(compare, value):
    result = compare[0]([value])
    assert result["isbn"]["status"] == "unknown"
    assert result["isbn"]["entries"][0]["status"] == "invalid"
    assert result["isbn"]["entries"][0]["editions"] == []


def test_isbn10_x_and_979_isbn13_have_correct_independent_canonical_forms(compare):
    run, path = compare
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE edition SET isbn13=NULL,isbn10='080442957X'")
    assert run(["urn:isbn:080442957x"])["isbn"]["entries"][0]["canonical_isbn13"] == "9780804429573"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE edition SET isbn10=NULL,isbn13='9791090636071'")
    result = run(["urn:isbn:9791090636071"])
    assert result["isbn"]["status"] == "same"
    assert result["isbn"]["entries"][0]["canonical_isbn13"] == "9791090636071"


def test_distinct_editions_of_one_work_do_not_become_distinct_work_votes(compare):
    run, path = compare
    add_edition(path, work="w_fixture", fmt="hardback")
    result = run(["urn:isbn:0306406152", "urn:isbn:9780306406157"])
    assert result["isbn"]["status"] == "same"
    assert len(result["isbn"]["entries"][0]["editions"]) == 2
    assert {e["format"] for e in result["isbn"]["entries"][0]["editions"]} == {"ebook", "hardback"}
    assert "identity_votes" not in result and result["ready"] is False


def test_same_isbn_on_another_work_is_ambiguous_even_with_complete_name_agreement(compare):
    run, path = compare
    add_edition(path)
    result = run(["urn:isbn:9780306406157"])
    assert result["metadata_agrees"] is True
    assert result["isbn"]["status"] == "ambiguous"
    assert {e["work_id"] for e in result["isbn"]["entries"][0]["editions"]} == {
        "w_fixture",
        "w_other",
    }


@pytest.mark.parametrize("where", ["primary", "ident"])
def test_spaces_in_typed_catalogue_isbns_cannot_hide_cross_work_collisions(compare, where):
    run, path = compare
    add_edition(path, isbn="978 0 306 40615 7" if where == "primary" else None)
    if where == "ident":
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "INSERT INTO edition_ident VALUES ('e_other','isbn13','978 0 306 40615 7','ok')"
            )
    assert run(["urn:isbn:9780306406157"])["isbn"]["status"] == "ambiguous"


def test_an_edition_whose_work_is_missing_remains_unassigned_ambiguous_evidence(compare):
    run, path = compare
    add_edition(path, work=None)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE edition SET work_id='missing-work' WHERE id='e_other'")
    result = run(["urn:isbn:9780306406157"])
    assert result["isbn"]["status"] == "ambiguous"
    assert (
        next(e for e in result["isbn"]["entries"][0]["editions"] if e["edition_id"] == "e_other")[
            "work_id"
        ]
        is None
    )


def test_uniquely_different_work_is_a_conflict_and_no_match_is_unknown(compare):
    run, path = compare
    add_edition(path, isbn="9780140328721")
    assert run(["urn:isbn:9780140328721"])["isbn"]["status"] == "different"
    assert run(["urn:isbn:9781861972712"])["isbn"]["status"] == "unknown"
    assert run(["urn:isbn:9780306406157", "urn:isbn:9781861972712"])["isbn"]["status"] == "partial"
    assert (
        run(["urn:isbn:9780306406157", "urn:isbn:9780140328721"])["isbn"]["status"] == "different"
    )
    assert run(["urn:isbn:9780306406157", "urn:isbn:bad"])["isbn"]["status"] == "partial"
    assert run(["urn:isbn:9780306406157", "urn:uuid:synthetic"])["isbn"]["status"] == "same"


def test_disputed_and_unassigned_records_cannot_establish_unique_support(compare):
    run, path = compare
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO edition_ident VALUES ('e_fixture','isbn13','9780306406157','disputed')"
        )
    result = run(["urn:isbn:9780306406157"])
    assert result["isbn"]["status"] == "ambiguous"
    assert result["isbn"]["entries"][0]["editions"][0]["disputed"] is True
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM edition_ident")
        db.execute("INSERT INTO edition_ident VALUES ('e_orphan','isbn10','0306406152','ok')")
    assert run(["urn:isbn:9780306406157"])["isbn"]["status"] == "ambiguous"


def test_recorded_identifiers_are_considered_in_addition_to_primary_edition_columns(compare):
    run, path = compare
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE edition SET isbn13=NULL")
        db.execute("INSERT INTO edition_ident VALUES ('e_fixture','isbn10','0-306-40615-2','ok')")
    assert run(["urn:isbn:9780306406157"])["isbn"]["status"] == "same"


def test_incomplete_inspection_never_assesses_isbn_agreement(compare):
    data = compare[0](["urn:isbn:9780306406157"], complete=False)
    assert data["isbn"]["status"] == "unknown"
    assert data["isbn"]["entries"][0]["status"] == "unknown"
    assert data["isbn"]["entries"][0]["editions"] == []


@pytest.mark.parametrize("where", ["primary", "ident"])
def test_oversized_global_isbn_evidence_refuses_instead_of_hiding_a_collision(compare, where):
    run, path = compare
    if where == "primary":
        add_edition(path, isbn="-" * 513 + "9780306406157")
    else:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "INSERT INTO edition_ident VALUES ('e_unassigned','isbn13',?,'ok')",
                ("-" * 513 + "9780306406157",),
            )
    with pytest.raises(reader.CatalogueError) as error:
        run(["urn:isbn:9780306406157"])
    assert error.value.status == 422


def test_excess_global_matches_refuse_before_claiming_unique_support(compare):
    run, path = compare
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany(
            "INSERT INTO edition(id,work_id,isbn13) VALUES (?,'w_fixture','9780306406157')",
            [(f"e_many_{n}",) for n in range(256)],
        )
    with pytest.raises(reader.CatalogueError) as error:
        run(["urn:isbn:9780306406157"])
    assert error.value.status == 422


def test_raw_alias_row_budget_applies_before_deduplicating_equivalent_isbns(compare):
    run, path = compare
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany(
            "INSERT INTO edition_ident VALUES ('e_fixture','isbn13',?,'ok')",
            [("-" * n + "9780306406157",) for n in range(257)],
        )
    with pytest.raises(reader.CatalogueError) as error:
        run(["urn:isbn:9780306406157"])
    assert error.value.status == 422


def test_repeated_source_urns_cannot_expand_more_than_the_combined_reference_budget(compare):
    run, path = compare
    for n in range(4):
        add_edition(path, edition=f"e_same_{n}", work="w_fixture")
    with pytest.raises(reader.CatalogueError) as error:
        run(["urn:isbn:9780306406157"] * 64)
    assert error.value.status == 422


def test_missing_identifier_table_refuses_only_when_an_isbn_needs_complete_evidence(compare):
    run, path = compare
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE edition_ident")
    assert run(["urn:uuid:synthetic"])["isbn"]["status"] == "unknown"
    with pytest.raises(reader.CatalogueError) as error:
        run(["urn:isbn:9780306406157"])
    assert error.value.status == 503
