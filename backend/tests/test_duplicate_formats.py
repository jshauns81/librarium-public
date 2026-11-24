"""Exact byte evidence includes every recorded format without interpreting its content."""

import os
import sqlite3
from contextlib import closing

import pytest
import test_book_assessment as fixtures
from test_incoming_assessment import assess, incoming

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
artifact_store = fixtures.artifact_store
selected = fixtures.selected
pytestmark = pytest.mark.django_db


def add_format(selected, raw, kind="PDF", name="Other"):
    path = selected.path.parent / (name + "." + kind.lower())
    path.write_bytes(raw)
    with closing(sqlite3.connect(selected.library / "metadata.db")) as db, db:
        db.execute("INSERT INTO data VALUES(2,1,?,1,?)", (kind, name))
    fixtures.refresh(selected)
    return path


def test_identical_bytes_in_other_format_are_found_even_on_native_origin_record(selected):
    path = add_format(selected, selected.raw)
    result = fixtures.run(selected)
    assert result["duplicates"]["scope"] == "all_recorded_formats"
    assert result["duplicates"]["recorded_files"] == 2
    assert result["duplicates"]["epub_files"] == 1
    assert result["duplicates"]["exact_bytes"]["books"] == [
        {"book_id": "1", "format": "PDF", "sha256": selected.job.target_id}
    ]
    assert result["duplicates"]["other_formats"]["byte_comparison"] == "complete"
    assert result["duplicates"]["other_formats"]["status"] == "unconfirmed"
    assert "exact_byte_duplicates_found" in result["blockers"]
    assert path.read_bytes() == selected.raw


def test_different_size_other_format_uses_actual_size_and_never_clears_semantics(
    selected, monkeypatch
):
    from librarium import book_assessment

    path = add_format(selected, b"Different rendition")
    original = book_assessment._hash_stream

    def check(stream, *args):
        assert os.fstat(stream.fileno()).st_ino != path.stat().st_ino
        return original(stream, *args)

    monkeypatch.setattr(book_assessment, "_hash_stream", check)
    result = assess(selected, incoming(selected))
    assert result["duplicates"]["different_size"] == 1
    assert result["duplicates"]["exact_bytes"]["count"] == 1
    assert result["duplicates"]["other_formats"]["byte_comparison"] == "complete"
    assert "other_format_duplicates_unconfirmed" in result["blockers"]
    assert "semantic_duplicates_unconfirmed" in result["blockers"]


@pytest.mark.parametrize("kind", ["missing", "symlink", "malformed"])
def test_unreadable_other_format_prevents_negative_byte_clearance(selected, kind):
    path = add_format(selected, selected.raw) if kind != "malformed" else None
    if kind == "malformed":
        with closing(sqlite3.connect(selected.library / "metadata.db")) as db, db:
            db.execute("INSERT INTO data VALUES(2,1,'BAD/FORMAT',1,'Other')")
        fixtures.refresh(selected)
    else:
        path.unlink()
        if kind == "symlink":
            path.symlink_to(selected.path)
    if kind == "malformed":
        from librarium import book_assessment

        with pytest.raises(book_assessment.AssessmentError, match="book identity"):
            fixtures.run(selected)
        return
    result = fixtures.run(selected)
    assert result["duplicates"]["complete"] is False
    assert result["duplicates"]["exact_bytes"]["status"] == "unconfirmed"
    assert result["duplicates"]["unreadable_count"] >= 1
    assert "duplicate_scan_incomplete" in result["blockers"]


def test_other_format_changed_after_hash_loses_verified_match(selected, monkeypatch):
    from librarium import book_assessment

    path = add_format(selected, selected.raw)
    original = book_assessment._hash_stream

    def changing(stream, size, budget):
        digest = original(stream, size, budget)
        if result_calls[0] == 1:
            path.write_bytes(selected.raw[:-1] + bytes([selected.raw[-1] ^ 1]))
        result_calls[0] += 1
        return digest

    result_calls = [0]
    monkeypatch.setattr(book_assessment, "_hash_stream", changing)
    result = fixtures.run(selected)
    assert result["duplicates"]["complete"] is False
    assert result["duplicates"]["exact_bytes"]["books"] == []


def test_format_count_limit_refuses_unbounded_census(selected, monkeypatch):
    from librarium import book_assessment

    add_format(selected, selected.raw)
    monkeypatch.setattr(book_assessment, "MAX_FILES", 1, raising=False)
    with pytest.raises(book_assessment.AssessmentError, match="format limit"):
        fixtures.run(selected)
