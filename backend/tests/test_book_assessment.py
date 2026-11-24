"""Independent observations bind synthetic preserved EPUBs and complete native inventories."""

import hashlib
import io
import os
import sqlite3
import uuid
from contextlib import closing
from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_catalogue
import test_direct_library
import test_file_inspections
from librarium import catalogue, file_inspections, library_reconciliation
from test_epub_inspection import archive, fixture_parts
from test_file_inspections import complete

library = test_direct_library.library
catalogue_fixture = test_catalogue.catalogue
artifact_store = test_file_inspections.store
pytestmark = pytest.mark.django_db


@pytest.fixture
def selected(library, catalogue_fixture, artifact_store):
    parts = []
    for name, body in fixture_parts():
        if name == "EPUB/book.opf":
            body = body.replace(
                b"</metadata>",
                b"<dc:creator>Fixture Author</dc:creator>"
                b"<dc:identifier>urn:isbn:9780306406157</dc:identifier></metadata>",
            )
            body = body.replace(b"A synthetic volume", b"Fixture: The Glass Meridian")
        parts.append((name, body))
    raw = archive(parts)
    path = library / "Writer/Actual Book (1)/Actual Book - Some Writer.epub"
    path.write_bytes(raw)
    test_direct_library.update(library, "UPDATE books SET title='Fixture: The Glass Meridian'")
    test_direct_library.update(library, "UPDATE authors SET name='Fixture Author'")
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute("UPDATE edition SET format='epub'")
    with catalogue.snapshot(str(catalogue_fixture[0]), fixture=True) as (_, pin):
        pass
    saved = library_reconciliation.reconcile(uuid.uuid4(), pin["version"], pin["sha256"])
    origin = {
        "library_uuid": saved.report["inventory"]["library_uuid"],
        "book_id": "1",
        "inventory": saved.report["inventory"]["token"],
        "format": "EPUB",
    }
    job = complete(
        file_inspections.enqueue(
            io.BytesIO(raw), uuid.uuid4(), hashlib.sha256(raw).hexdigest(), path.name, origin=origin
        )
    )
    return SimpleNamespace(
        raw=raw,
        path=path,
        library=library,
        catalogue=catalogue_fixture,
        pin=pin,
        saved=saved,
        job=job,
    )


def run(selected, **kwargs):
    from librarium import book_assessment

    return book_assessment.assess(
        selected.job,
        selected.pin["version"],
        selected.pin["sha256"],
        "w_fixture",
        reconciliation=selected.saved,
        **kwargs,
    )


def refresh(selected):
    selected.saved = library_reconciliation.reconcile(
        uuid.uuid4(), selected.pin["version"], selected.pin["sha256"]
    )
    selected.job.input["library_origin"]["inventory"] = selected.saved.report["inventory"]["token"]
    from librarium.services import fingerprint

    selected.job.input_fingerprint = fingerprint(selected.job.input)
    selected.job.result["input_fingerprint"] = selected.job.input_fingerprint
    selected.job.save()


def add_book(selected, raw, *, title="Unrelated title", author="Different Writer", size=1):
    root = selected.library
    folder = root / "Another (2)"
    folder.mkdir()
    path = folder / "Other.epub"
    path.write_bytes(raw)
    with closing(sqlite3.connect(root / "metadata.db")) as db, db:
        db.execute(
            "INSERT INTO books(id,title,sort,path,uuid) VALUES(2,?,?,'Another (2)','other-uuid')",
            (title, title),
        )
        db.execute("INSERT INTO authors VALUES(2,?)", (author,))
        db.execute("INSERT INTO books_authors_link VALUES(2,2,2)")
        db.execute("INSERT INTO data VALUES(2,2,'EPUB',?,'Other')", (size,))
    refresh(selected)
    return path


def test_assesses_declared_identity_separately_and_never_admits_a_correction(selected):
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in selected.library.rglob("*")
        if p.is_file()
    }
    preserved = deepcopy(selected.job.result)
    result = run(selected)
    assert result["schema_version"] == "librarium.book-assessment.v6"
    assert result["job_id"] == str(selected.job.pk)
    assert result["source_sha256"] == selected.job.target_id
    assert result["report_sha256"] == selected.job.result["report_sha256"]
    assert result["reconciliation_key"] == str(selected.saved.pk)
    assert result["catalogue"] == selected.pin
    assert result["inventory"]["token"] == selected.saved.report["inventory"]["token"]
    assert result["file_work_identity"]["status"] == "supported"
    assert result["file_work_identity"]["basis"] == "preserved_package_declarations"
    assert result["file_work_identity"]["content_authentication"] == "not_assessed"
    assert result["source_attribution"]["status"] == "unconfirmed"
    assert result["source_attribution"]["whole_file_identity"] == "unconfirmed"
    assert result["source_attribution"]["report_sha256"] == selected.job.result["report_sha256"]
    assert "source_attribution_unconfirmed" in result["blockers"]
    assert result["edition_identity"]["status"] == "supported"
    assert result["edition_identity"]["edition_id"] == "e_fixture"
    assert result["current_library_bytes"]["status"] == "same_bytes"
    assert result["duplicates"]["exact_bytes"]["status"] == "none_found"
    assert result["duplicates"]["same_work"]["status"] == "unconfirmed"
    assert result["ready"] is False and result["correction_admission"] == "held"
    assert "content_identity_unconfirmed" in result["blockers"]
    assert "semantic_duplicates_unconfirmed" in result["blockers"]
    assert "writer_not_authorized" in result["blockers"]
    selected.job.refresh_from_db()
    assert selected.job.result == preserved
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in selected.library.rglob("*")
        if p.is_file()
    }


def test_same_bytes_under_unrelated_metadata_are_found_despite_wrong_recorded_sizes(selected):
    add_book(selected, selected.raw, size=17)
    result = run(selected)
    copies = result["duplicates"]["exact_bytes"]
    assert copies["status"] == "found" and copies["count"] == 1
    assert copies["books"] == [{"book_id": "2", "format": "EPUB", "sha256": selected.job.target_id}]
    assert result["duplicates"]["same_work"]["candidates"] == []
    assert "exact_byte_duplicates_found" in result["blockers"]


@pytest.mark.parametrize(
    ("title", "status"),
    [("Fixture: The Glass Meridian", "corroborated"), ("A contradictory work", "conflicting")],
)
def test_source_attribution_is_separate_and_never_clears_admission(selected, title, status):
    from test_epub_inspection import page

    parts = [
        (
            name,
            page(
                '<section epub:type="titlepage"><h1 id="one" epub:type="title">'
                f'{title}</h1><p epub:type="author">Fixture Author</p></section>'
            )
            if name == "EPUB/first.xhtml"
            else raw,
        )
        for name, raw in fixture_parts()
    ]
    raw = archive(parts)
    selected.job = complete(
        file_inspections.enqueue(
            io.BytesIO(raw), uuid.uuid4(), hashlib.sha256(raw).hexdigest(), "incoming.epub"
        )
    )
    before = selected.path.read_bytes()
    result = run(selected)
    attribution = result["source_attribution"]
    assert attribution["status"] == status
    assert attribution["source_sha256"] == selected.job.target_id
    assert attribution["report_sha256"] == selected.job.result["report_sha256"]
    assert attribution["catalogue"]["work_id"] == "w_fixture"
    assert (
        attribution["whole_file_identity"] == attribution["content_authentication"] == "unconfirmed"
    )
    assert "content_identity_unconfirmed" in result["blockers"]
    assert "semantic_duplicates_unconfirmed" in result["blockers"]
    assert "writer_not_authorized" in result["blockers"]
    assert result["ready"] is False and result["correction_admission"] == "held"
    assert selected.path.read_bytes() == before


def test_same_work_metadata_candidates_do_not_become_identical_files(selected):
    add_book(
        selected,
        b"A different electronic rendition",
        title="Fixture: The Glass Meridian",
        author="Fixture Author",
    )
    result = run(selected)
    assert result["duplicates"]["exact_bytes"]["status"] == "none_found"
    same = result["duplicates"]["same_work"]
    assert same["status"] == "possible"
    assert same["candidates"][0]["book_id"] == "2"
    assert "title_and_creators" in same["candidates"][0]["basis"]
    assert "possible_same_work_duplicates" in result["blockers"]


def test_unreadable_epub_never_produces_no_duplicate_claim(selected):
    path = add_book(selected, selected.raw)
    path.unlink()
    result = run(selected)
    assert result["duplicates"]["exact_bytes"]["status"] == "unconfirmed"
    assert result["duplicates"]["complete"] is False
    assert result["duplicates"]["unreadable"] == [{"book_id": "2", "reason": "file_unavailable"}]
    assert "duplicate_scan_incomplete" in result["blockers"]


def test_oversized_different_size_books_do_not_require_reading_their_contents(
    selected, monkeypatch
):
    from librarium import book_assessment

    path = add_book(selected, b"a" * (len(selected.raw) + 10))
    original = book_assessment._hash_stream

    def hashing(stream, size, budget):
        assert os.fstat(stream.fileno()).st_ino != path.stat().st_ino
        return original(stream, size, budget)

    monkeypatch.setattr(book_assessment, "_hash_stream", hashing)
    result = run(selected)
    assert result["duplicates"]["different_size"] == 1
    assert result["duplicates"]["hashed"] == 0


@pytest.mark.parametrize("kind", ["catalogue", "inventory", "selected_book", "partial"])
def test_incompatible_coverage_is_rejected_before_duplicate_claims(selected, kind):
    from librarium import book_assessment

    if kind == "catalogue":
        selected.saved.catalogue_sha256 = "0" * 64
    elif kind == "inventory":
        selected.saved.report["inventory"]["token"] = "0" * 64
    elif kind == "selected_book":
        selected.saved.report["books"][0]["book"]["id"] = "2"
    else:
        selected.saved.report["total"] += 1
    with pytest.raises(book_assessment.AssessmentError, match="reconciliation"):
        run(selected)


def test_changed_current_selected_bytes_do_not_become_no_duplicates(selected):
    selected.path.write_bytes(selected.raw[:-1] + b"!")
    result = run(selected)
    assert result["current_library_bytes"]["status"] == "different_bytes"
    assert result["duplicates"]["exact_bytes"]["status"] == "unconfirmed"
    assert "library_source_bytes_changed" in result["blockers"]


def test_changed_metadata_refuses_the_historical_inventory(selected):
    from librarium import book_assessment

    test_direct_library.update(selected.library, "UPDATE books SET title='Changed'")
    with pytest.raises(book_assessment.AssessmentError, match="changed"):
        run(selected)


def test_cancellation_stops_before_publishing_assessment(selected):
    from librarium import book_assessment

    with pytest.raises(book_assessment.AssessmentError, match="cancelled"):
        run(selected, cancel_check=lambda: True)


def test_budget_exhaustion_remains_unconfirmed(selected, monkeypatch):
    from librarium import book_assessment

    add_book(selected, selected.raw)
    monkeypatch.setattr(book_assessment, "MAX_TOTAL_BYTES", len(selected.raw) + 1)
    result = run(selected)
    assert result["duplicates"]["complete"] is False
    assert result["duplicates"]["exact_bytes"]["status"] == "unconfirmed"
    assert "duplicate_scan_incomplete" in result["blockers"]


def test_selected_file_changed_after_initial_hash_is_not_reported_as_same_bytes(
    selected, monkeypatch
):
    from librarium import book_assessment

    add_book(selected, selected.raw)
    original = book_assessment._hash_stream
    calls = 0

    def changing(stream, size, budget):
        nonlocal calls
        digest = original(stream, size, budget)
        calls += 1
        if calls == 2:
            selected.path.write_bytes(selected.raw[:-1] + b"!")
        return digest

    monkeypatch.setattr(book_assessment, "_hash_stream", changing)
    result = run(selected)
    assert result["current_library_bytes"]["status"] != "same_bytes"
    assert result["duplicates"]["complete"] is False
    assert "library_source_bytes_changed" in result["blockers"]


@pytest.mark.parametrize(
    "changes,work_state,edition_state",
    [
        ({"isbn": "unknown"}, "unconfirmed", "unconfirmed"),
        ({"isbn": "partial"}, "unconfirmed", "unconfirmed"),
        ({"isbn": "different"}, "conflicting", "conflicting"),
        ({"isbn": "ambiguous"}, "ambiguous", "ambiguous"),
        ({"title": "different"}, "conflicting", "conflicting"),
        ({"creators": "ambiguous"}, "ambiguous", "ambiguous"),
        ({"complete": False}, "unconfirmed", "unconfirmed"),
        ({"capture": "not_recorded"}, "unconfirmed", "unconfirmed"),
        ({"format": "paperback"}, "supported", "unconfirmed"),
        ({"format": "ebook"}, "supported", "unconfirmed"),
        ({"format": None}, "supported", "unconfirmed"),
        ({"two_editions": True}, "supported", "ambiguous"),
    ],
)
def test_identity_keeps_metadata_conflicts_and_edition_uncertainty_separate(
    changes, work_state, edition_state
):
    from librarium import book_assessment

    comparison = {
        "inspection_complete": changes.get("complete", True),
        "catalogue": {"work_id": "selected"},
        "title": {"status": changes.get("title", "same")},
        "creators": {"status": changes.get("creators", "same")},
        "isbn": {
            "status": changes.get("isbn", "same"),
            "capture": changes.get("capture", "recorded"),
            "entries": [
                {
                    "editions": [
                        {
                            "edition_id": "one",
                            "work_id": "selected",
                            "format": changes.get("format", "epub"),
                            "disputed": False,
                        }
                    ]
                }
            ],
        },
    }
    if changes.get("two_editions"):
        comparison["isbn"]["entries"][0]["editions"].append(
            {"edition_id": "two", "work_id": "selected", "format": "epub", "disputed": False}
        )
    work, edition = book_assessment.identity(comparison)
    assert work["status"] == work_state
    assert edition["status"] == edition_state
    assert work["content_authentication"] == "not_assessed"


def test_library_metadata_match_does_not_supply_missing_epub_identity_evidence(selected):
    parts = []
    for name, body in fixture_parts():
        if name == "EPUB/book.opf":
            body = body.replace(b"A synthetic volume", b"Fixture: The Glass Meridian")
            body = body.replace(
                b"</metadata>", b"<dc:creator>Fixture Author</dc:creator></metadata>"
            )
        parts.append((name, body))
    raw = archive(parts)
    selected.path.write_bytes(raw)
    selected.job = complete(
        file_inspections.enqueue(
            io.BytesIO(raw),
            uuid.uuid4(),
            hashlib.sha256(raw).hexdigest(),
            selected.path.name,
            origin=selected.job.input["library_origin"],
        )
    )
    assert selected.saved.report["books"][0]["match"]["status"] == "matched"
    result = run(selected)
    assert result["current_library_bytes"]["status"] == "same_bytes"
    assert result["file_work_identity"]["status"] == "unconfirmed"
    assert result["edition_identity"]["status"] == "unconfirmed"
    assert "declared_work_identity_unconfirmed" in result["blockers"]


def test_cross_work_isbn_ownership_ambiguity_in_actual_preserved_report_is_held(selected):
    with closing(sqlite3.connect(selected.catalogue[1])) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES ('w_other','Unrelated work')")
        db.execute(
            "INSERT INTO edition(id,work_id,format,isbn13) VALUES ('e_other','w_other','epub','9780306406157')"
        )
    with catalogue.snapshot(str(selected.catalogue[0]), fixture=True) as (_, pin):
        selected.pin = pin
    refresh(selected)
    result = run(selected)
    assert result["file_work_identity"]["status"] == "ambiguous"
    assert result["edition_identity"]["status"] == "ambiguous"
    assert "declared_work_identity_ambiguous" in result["blockers"]


def test_cancellation_interrupts_hashing_chunks():
    from librarium import book_assessment

    polls = 0

    def cancelled():
        nonlocal polls
        polls += 1
        return polls > 1

    stream = io.BytesIO(b"x" * (2 * 1024 * 1024))
    with pytest.raises(book_assessment.AssessmentError, match="cancelled"):
        book_assessment._hash_stream(
            stream, len(stream.getvalue()), book_assessment._Budget(cancelled)
        )
    assert stream.tell() == 1024 * 1024


def test_duplicate_changed_after_hash_is_not_retained_as_verified_match(selected, monkeypatch):
    from contextlib import contextmanager

    from librarium import book_assessment, direct_library

    duplicate = add_book(selected, selected.raw)
    original = direct_library.source_file
    opened = 0

    @contextmanager
    def changed_before_recheck(*args, **kwargs):
        nonlocal opened
        if args[1] == "Writer/Actual Book (1)/Actual Book - Some Writer.epub":
            opened += 1
            if opened == 2:
                duplicate.write_bytes(selected.raw[:-1] + bytes([selected.raw[-1] ^ 1]))
        with original(*args, **kwargs) as value:
            yield value

    monkeypatch.setattr(direct_library, "source_file", changed_before_recheck)
    result = book_assessment.assess(
        selected.job,
        selected.pin["version"],
        selected.pin["sha256"],
        "w_fixture",
        reconciliation=selected.saved,
    )
    assert result["duplicates"]["complete"] is False
    assert result["duplicates"]["exact_bytes"]["status"] == "unconfirmed"
    assert result["duplicates"]["exact_bytes"]["books"] == []


def test_new_assessment_scope_does_not_present_a_correction_gate():
    from librarium import book_assessment

    assert "orrection" not in book_assessment.SCOPE
