"""Saved whole-library coverage is atomic, pinned and separate from file identity."""

import hashlib
import io
import json
import sqlite3
import uuid
from contextlib import closing

import pytest
import test_catalogue
import test_direct_library
from django.core.management import call_command
from django.core.management.base import CommandError
from librarium import catalogue, direct_library
from librarium import library_reconciliation as reconciliation
from librarium.models import LibraryReconciliation

library = test_direct_library.library
catalogue_fixture = test_catalogue.catalogue
pytestmark = pytest.mark.django_db


def pins(catalogue_fixture):
    with catalogue.snapshot(str(catalogue_fixture[0]), fixture=True) as (_, info):
        return info["version"], info["sha256"]


def run(catalogue_fixture, **changes):
    version, sha256 = pins(catalogue_fixture)
    return reconciliation.reconcile(str(uuid.uuid4()), version, sha256, **changes)


def update(library, sql, args=()):
    test_direct_library.update(library, sql, args)


def test_persists_complete_inventory_and_full_match_evidence_without_file_reads(
    library, catalogue_fixture, monkeypatch
):
    update(library, "UPDATE books SET title='Fixture: The Glass Meridian'")
    update(library, "UPDATE authors SET name='Fixture Author'")
    original = hashlib.sha256((library / "metadata.db").read_bytes()).hexdigest()
    monkeypatch.setattr(direct_library, "read_cover", lambda *a: pytest.fail("cover read"))
    monkeypatch.setattr(direct_library, "book_files", lambda *a: pytest.fail("file read"))
    saved = run(catalogue_fixture)
    data = saved.report
    assert data["total"] == 1
    assert data["counts"] == {
        "matched": 1,
        "unmatched": 0,
        "ambiguous": 0,
        "disagreement": 0,
        "held": 0,
    }
    entry = data["books"][0]
    assert entry["book"]["uuid"] == "book-uuid"
    assert entry["book"]["formats"][0]["format"] == "EPUB"
    assert entry["book"]["formats"][0]["available"] is None
    assert entry["match"]["status"] == "matched"
    assert entry["match"]["catalogue"]["sha256"] == pins(catalogue_fixture)[1]
    assert entry["match"]["ready"] is False
    assert data["file_identity"] == "not_assessed"
    assert LibraryReconciliation.objects.get(pk=saved.pk).report == data
    assert hashlib.sha256((library / "metadata.db").read_bytes()).hexdigest() == original


def test_changes_compare_only_explicit_prior_inventory_preserving_history(
    library, catalogue_fixture
):
    first = run(catalogue_fixture)
    update(library, "UPDATE books SET title='Changed metadata'")
    update(
        library, "INSERT INTO books(id,title,sort,path,uuid) VALUES(2,'New','New','New (2)','new')"
    )
    second = run(catalogue_fixture, previous=str(first.pk))
    assert second.report["changes"] == {
        "added": ["2"],
        "removed": [],
        "changed": ["1"],
        "replaced": [],
        "identity_unknown": [],
    }
    update(library, "DELETE FROM books WHERE id=1")
    third = run(catalogue_fixture, previous=str(second.pk))
    assert third.report["changes"]["removed"] == ["1"]
    assert LibraryReconciliation.objects.get(pk=first.pk).report == first.report
    assert LibraryReconciliation.objects.count() == 3


def test_reused_numeric_id_with_new_uuid_is_a_replacement(library, catalogue_fixture):
    first = run(catalogue_fixture)
    update(library, "UPDATE books SET uuid='replacement'")
    second = run(catalogue_fixture, previous=str(first.pk))
    assert second.report["changes"] == {
        "added": [],
        "removed": [],
        "changed": [],
        "replaced": ["1"],
        "identity_unknown": [],
    }


def test_invalid_metadata_is_held_and_never_counted_as_unmatched(library, catalogue_fixture):
    update(library, "UPDATE books SET title=?", ("x" * 513,))
    saved = run(catalogue_fixture)
    assert saved.report["counts"]["held"] == 1
    assert saved.report["counts"]["unmatched"] == 0
    assert saved.report["books"][0]["reason"] == "metadata_or_matching_limit"


def test_invalid_catalogue_evidence_does_not_publish_partial_coverage(library, catalogue_fixture):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute("DROP TABLE author_alias")
    with pytest.raises(reconciliation.ReconciliationError):
        run(catalogue_fixture)
    assert not LibraryReconciliation.objects.exists()


def test_source_change_during_matching_preserves_previous_report(
    library, catalogue_fixture, monkeypatch
):
    first = run(catalogue_fixture)
    original = reconciliation.library_matching.match

    def changing(*a, **kw):
        result = original(*a, **kw)
        update(library, "UPDATE books SET title='Concurrent change'")
        return result

    monkeypatch.setattr(reconciliation.library_matching, "match", changing)
    with pytest.raises(reconciliation.ReconciliationError):
        run(catalogue_fixture)
    assert LibraryReconciliation.objects.count() == 1
    assert LibraryReconciliation.objects.get(pk=first.pk).report == first.report


def test_exact_replay_survives_unavailable_sources_and_conflicting_pin_refuses(
    library, catalogue_fixture, settings
):
    first = run(catalogue_fixture)
    settings.DIRECT_LIBRARY_ROOT = ""
    again = reconciliation.reconcile(str(first.pk), *pins(catalogue_fixture))
    assert again.pk == first.pk and again.report == first.report
    with pytest.raises(reconciliation.ReconciliationError, match="different"):
        reconciliation.reconcile(str(first.pk), first.catalogue_version, "a" * 64)
    assert LibraryReconciliation.objects.count() == 1


@pytest.mark.parametrize("case", ["library", "unknown", "missing_identity", "oversize", "deadline"])
def test_incomplete_or_wrong_inventory_refuses_publication(
    library, catalogue_fixture, monkeypatch, case
):
    first = run(catalogue_fixture)
    changes = {}
    if case == "library":
        update(library, "UPDATE library_id SET uuid='different-library'")
        changes["previous"] = str(first.pk)
    elif case == "unknown":
        changes["previous"] = str(uuid.uuid4())
    elif case == "missing_identity":
        update(library, "DELETE FROM library_id")
    elif case == "oversize":
        monkeypatch.setattr(reconciliation, "MAX_BOOKS", 0)
    else:
        monkeypatch.setattr(reconciliation, "SECONDS", -1)
    with pytest.raises(reconciliation.ReconciliationError):
        run(catalogue_fixture, **changes)
    assert LibraryReconciliation.objects.count() == 1


def test_report_budget_refuses_instead_of_truncating(library, catalogue_fixture, monkeypatch):
    monkeypatch.setattr(reconciliation, "MAX_REPORT_BYTES", 10)
    with pytest.raises(reconciliation.ReconciliationError):
        run(catalogue_fixture)
    assert not LibraryReconciliation.objects.exists()


def test_command_saves_and_reads_without_exposing_configured_paths(library, catalogue_fixture):
    key = str(uuid.uuid4())
    output = io.StringIO()
    version, sha256 = pins(catalogue_fixture)
    call_command(
        "library_reconcile",
        request_key=key,
        catalogue_version=version,
        sha256=sha256,
        stdout=output,
    )
    data = json.loads(output.getvalue())
    assert data["request_key"] == key
    assert data["total"] == 1 and data["counts"]["disagreement"] == 1
    assert str(library) not in output.getvalue()
    output = io.StringIO()
    call_command("library_reconciliation", key, stdout=output)
    assert json.loads(output.getvalue()) == LibraryReconciliation.objects.get(pk=key).report
    with pytest.raises(CommandError):
        call_command("library_reconciliation", str(uuid.uuid4()), stdout=io.StringIO())


def test_missing_book_identity_is_unknown_instead_of_a_proven_replacement(
    library, catalogue_fixture
):
    first = run(catalogue_fixture)
    update(library, "UPDATE books SET uuid=NULL")
    second = run(catalogue_fixture, previous=str(first.pk))
    assert second.report["changes"]["identity_unknown"] == ["1"]
    assert second.report["changes"]["replaced"] == []


def test_invalid_projection_is_held_and_preserves_inventory_membership(library, catalogue_fixture):
    update(library, "UPDATE data SET name='../unsafe'")
    saved = run(catalogue_fixture)
    assert saved.report["total"] == 1
    assert saved.report["counts"]["held"] == 1
    assert saved.report["books"][0]["book"]["id"] == "1"


def test_empty_library_has_complete_zero_coverage(library, catalogue_fixture):
    update(library, "DELETE FROM books")
    saved = run(catalogue_fixture)
    assert saved.report["total"] == 0 and sum(saved.report["counts"].values()) == 0
    assert saved.report["books"] == []


@pytest.mark.parametrize("status", ["unmatched", "ambiguous", "disagreement"])
def test_nonmatching_statuses_remain_distinct(library, catalogue_fixture, status):
    update(library, "DELETE FROM identifiers")
    if status != "unmatched":
        update(library, "UPDATE books SET title='Fixture: The Glass Meridian'")
    if status == "ambiguous":
        update(library, "INSERT INTO identifiers(book,type,val) VALUES(1,'isbn','invalid')")
    saved = run(catalogue_fixture)
    assert saved.report["counts"][status] == 1
    assert sum(saved.report["counts"].values()) == 1
    assert saved.report["books"][0]["match"]["status"] == status


@pytest.mark.parametrize("version,sha256", [("", ""), ("bad", "a" * 64), ("2026.10.25.1", "bad")])
def test_invalid_pin_does_not_create_report(library, catalogue_fixture, version, sha256):
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.reconcile(str(uuid.uuid4()), version, sha256)
    assert not LibraryReconciliation.objects.exists()


def test_invalid_request_and_self_reference_are_controlled_errors(library, catalogue_fixture):
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.read("../invalid")
    key = str(uuid.uuid4())
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.reconcile(key, *pins(catalogue_fixture), previous=key)


def test_schema_reverse_preserves_saved_evidence(library, catalogue_fixture):
    import importlib

    from django.apps import apps

    guard = importlib.import_module("librarium.migrations.0006_library_reconciliation")
    guard.preserve_reconciliations(apps, None)
    run(catalogue_fixture)
    with pytest.raises(RuntimeError, match="preserve evidence"):
        guard.preserve_reconciliations(apps, None)


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_request_creates_one_saved_report(library, catalogue_fixture, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections

    gate = threading.Barrier(2)
    original = reconciliation.library_matching.match

    def together(*a, **kw):
        result = original(*a, **kw)
        gate.wait(timeout=10)
        return result

    monkeypatch.setattr(reconciliation.library_matching, "match", together)
    key = str(uuid.uuid4())
    selected = pins(catalogue_fixture)

    def reconcile_once():
        close_old_connections()
        try:
            return reconciliation.reconcile(key, *selected).report
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: reconcile_once(), range(2)))
    assert results[0] == results[1]
    assert LibraryReconciliation.objects.count() == 1


def test_recorded_path_change_is_retained_without_opening_moved_files(library, catalogue_fixture):
    first = run(catalogue_fixture)
    update(library, "UPDATE books SET path='New Folder/Book (1)'")
    second = run(catalogue_fixture, previous=str(first.pk))
    assert second.report["changes"]["changed"] == ["1"]
    assert second.report["books"][0]["book"]["library_path"] == "New Folder/Book (1)"


def test_batch_cache_reuses_isbn_normalization_without_changing_evidence(
    library, catalogue_fixture, monkeypatch
):
    from collections import Counter

    from librarium import package_identifiers

    for book_id in range(2, 6):
        update(
            library,
            "INSERT INTO books(id,title,sort,path,uuid) VALUES(?,?,?,?,?)",
            (book_id, "Actual Book", "Actual Book", "Path", f"uuid-{book_id}"),
        )
        update(
            library,
            "INSERT INTO identifiers(book,type,val) VALUES(?,'isbn','9780306406157')",
            (book_id,),
        )
    calls = Counter()
    original = package_identifiers._catalogue_isbn

    def counted(value):
        calls[value] += 1
        return original(value)

    monkeypatch.setattr(package_identifiers, "_catalogue_isbn", counted)
    cached = run(catalogue_fixture).report
    cached_calls = sum(calls.values())
    calls.clear()
    monkeypatch.setattr(reconciliation, "lru_cache", lambda **kw: lambda function: function)
    uncached = run(catalogue_fixture).report
    assert sum(calls.values()) > cached_calls * 3
    assert cached["counts"] == uncached["counts"]
    assert [entry["match"]["candidates"] for entry in cached["books"]] == [
        entry["match"]["candidates"] for entry in uncached["books"]
    ]


@pytest.mark.django_db(transaction=True)
def test_actual_schema_reverse_refuses_populated_reports_and_empty_roundtrip_works(
    library, catalogue_fixture
):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    saved = run(catalogue_fixture)
    before = saved.report
    with pytest.raises(RuntimeError, match="saved reconciliations"):
        MigrationExecutor(connection).migrate([("librarium", "0005_epub_validation_jobs")])
    assert LibraryReconciliation.objects.get(pk=saved.pk).report == before
    LibraryReconciliation.objects.all().delete()
    MigrationExecutor(connection).migrate([("librarium", "0005_epub_validation_jobs")])
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert not LibraryReconciliation.objects.exists()


def test_duplicate_book_keys_refuse_complete_coverage(library, catalogue_fixture):
    update(library, "CREATE TABLE copied_books AS SELECT * FROM books")
    update(library, "DROP TABLE books")
    update(library, "ALTER TABLE copied_books RENAME TO books")
    update(library, "INSERT INTO books SELECT * FROM books")
    with pytest.raises(reconciliation.ReconciliationError, match="duplicate book"):
        run(catalogue_fixture)
    assert not LibraryReconciliation.objects.exists()
