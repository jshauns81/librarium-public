"""Source title/credit attribution stays separate from package declarations and admission."""

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from html import escape

import pytest
from librarium import attribution_comparison, file_inspections
from test_epub_inspection import archive, fixture_parts, inspect, page


@pytest.fixture
def db():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(
            "CREATE TABLE work(id TEXT,title TEXT);"
            "CREATE TABLE author(id INTEGER,name TEXT);"
            "CREATE TABLE author_alias(author_id INTEGER,name TEXT);"
            "CREATE TABLE work_author(work_id TEXT,author_id INTEGER,role TEXT);"
            "INSERT INTO work VALUES('selected','A synthetic volume');"
            "INSERT INTO author VALUES(1,'Fixture Writer');"
            "INSERT INTO author_alias VALUES(1,'Fixture Alias');"
            "INSERT INTO work_author VALUES('selected',1,'author');"
        )
        yield connection


def titlepage(title="A synthetic volume", names=("Fixture Writer",)):
    credits = "".join(f'<p epub:type="author">{escape(name)}</p>' for name in names)
    return (
        '<section epub:type="titlepage"><h1 id="one" epub:type="title">'
        f"{escape(title)}</h1>{credits}</section>"
    )


def envelope(body=None):
    source = archive(
        [(name, page(body) if name == "EPUB/first.xhtml" else raw) for name, raw in fixture_parts()]
        if body is not None
        else fixture_parts()
    )
    report = inspect(source)
    return {
        "job_id": "fixture-job",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "report_sha256": hashlib.sha256(json.dumps(report).encode()).hexdigest(),
        "report": report,
    }


PIN = {"version": "fixture-v1", "sha256": "a" * 64, "fixture": True}


def compare(db, value=None):
    return attribution_comparison.compare(value or envelope(titlepage()), db, PIN, "selected")


def test_complete_source_title_and_authors_corroborate_without_authenticating(db):
    value = envelope(titlepage(names=("Fixture Alias",)))
    original = deepcopy(value)
    result = compare(db, value)
    assert result["status"] == "corroborated"
    assert result["policy_version"] == "librarium.source-attribution-comparison.v1"
    assert result["observation_policy"] == "librarium.epub-source-attribution.v1"
    assert result["job_id"] == value["job_id"]
    assert result["source_sha256"] == value["source_sha256"]
    assert result["report_sha256"] == value["report_sha256"]
    assert result["catalogue"] == {
        **PIN,
        "work_id": "selected",
        "title": "A synthetic volume",
        "authors": [{"id": "1", "name": "Fixture Writer"}],
    }
    assert result["observation_ids"] == ["source-title-1"]
    assert result["title"]["status"] == "same"
    assert result["creators"]["matches"][0]["basis"] == "alias"
    assert result["whole_file_identity"] == result["content_authentication"] == "unconfirmed"
    assert result["ready"] is False
    assert value == original


@pytest.mark.parametrize(
    ("title", "names"),
    [("A contradictory title", ("Fixture Writer",)), ("A synthetic volume", ("Another Writer",))],
)
def test_source_conflict_is_not_hidden_by_matching_package_metadata(db, title, names):
    value = envelope(titlepage(title, names))
    assert value["report"]["metadata"][1]["text"] == "A synthetic volume"
    assert compare(db, value)["status"] == "conflicting"


@pytest.mark.parametrize(
    "body",
    [None, '<h1 id="one">A synthetic volume</h1><p>Fixture Writer</p>', titlepage(names=())],
    ids=[
        "missing-body",
        "unclassified-body",
        "missing-credit",
    ],
)
def test_metadata_or_unclassified_or_missing_credit_cannot_corroborate(db, body):
    assert compare(db, envelope(body))["status"] == "unconfirmed"


def test_partial_coauthors_are_unconfirmed_and_complete_credits_can_corroborate(db):
    db.executescript(
        "INSERT INTO author VALUES(2,'Second Writer');"
        "INSERT INTO work_author VALUES('selected',2,'author');"
    )
    result = compare(db)
    assert result["status"] == "unconfirmed"
    assert result["creators"]["status"] == "partial"
    assert (
        compare(db, envelope(titlepage(names=("Fixture Alias", "Second Writer"))))["status"]
        == "corroborated"
    )


def test_global_alias_collision_is_ambiguous(db):
    db.executescript(
        "INSERT INTO author VALUES(2,'Other Writer');INSERT INTO author_alias VALUES(2,'Fixture Alias');"
    )
    assert compare(db, envelope(titlepage(names=("Fixture Alias",))))["status"] == "ambiguous"


def test_repeated_semantic_blocks_remain_ambiguous_even_when_equal(db):
    body = titlepage() + titlepage().replace('id="one"', 'id="repeat"')
    assert compare(db, envelope(body))["status"] == "ambiguous"


def test_wrapped_second_title_before_narrative_tail_preserves_ambiguity(db):
    second = titlepage().replace('id="one"', 'id="two"')
    body = titlepage() + f"<div>{second}</div>Narrative follows the title pages."
    assert compare(db, envelope(body))["status"] == "ambiguous"


@pytest.mark.parametrize("version", ["librarium.epub-structure.v5", "librarium.epub-structure.v6"])
def test_historical_absence_is_unconfirmed_without_new_observations(db, version):
    value = envelope()
    value["report"].pop("source_attribution", None)
    value["report"]["policy"]["version"] = version
    result = compare(db, value)
    assert result["status"] == "unconfirmed"
    assert result["capture"] == "not_captured"
    assert result["observation_ids"] == []
    assert result["observation_policy"] is None


def test_mixed_source_pin_is_refused(db):
    value = envelope(titlepage())
    value["source_sha256"] = "b" * 64
    with pytest.raises(file_inspections.InspectionError, match="attribution"):
        compare(db, value)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("expected_sha256", "b" * 64), ("source_sha256", []), ("source_sha256", "b" * 64)],
)
def test_altered_report_source_binding_is_a_controlled_refusal(db, field, replacement):
    value = envelope(titlepage())
    value["report"][field] = replacement
    with pytest.raises(file_inspections.InspectionError, match="attribution"):
        compare(db, value)


def test_malformed_capture_is_refused_without_a_corroboration_claim(db):
    value = envelope(titlepage())
    value["report"]["source_attribution"]["policy"] = "unknown-policy"
    with pytest.raises(file_inspections.InspectionError, match="attribution"):
        compare(db, value)


def test_unknown_work_is_not_replaced_by_a_metadata_match(db):
    from librarium.catalogue import CatalogueError

    with pytest.raises(CatalogueError):
        attribution_comparison.compare(envelope(titlepage()), db, PIN, "missing")
