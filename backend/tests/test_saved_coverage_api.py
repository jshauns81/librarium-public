import uuid

import pytest
import test_library_reconciliation as fixtures
from librarium.models import LibraryReconciliation

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
pytestmark = pytest.mark.django_db


def test_discovery_and_pages_preserve_report_pins_without_reopening_sources(
    library, catalogue_fixture, client, settings
):
    first = fixtures.run(catalogue_fixture)
    fixtures.update(library, "UPDATE books SET title='Later'")
    second = fixtures.run(catalogue_fixture)
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    reply = client.get("/api/library/reconciliations")
    assert reply.status_code == 200
    data = reply.json()
    assert data["total"] == 2
    assert {r["request_key"] for r in data["reports"]} == {str(first.pk), str(second.pk)}
    assert all("books" not in r and "changes" not in r for r in data["reports"])
    reply = client.get(f"/api/library/reconciliations/{first.pk}", {"status": "disagreement"})
    assert reply.status_code == 200
    data = reply.json()
    assert data["observation"] == "historical"
    assert data["request_key"] == str(first.pk)
    assert data["catalogue"] == first.report["catalogue"]
    assert data["inventory"] == first.report["inventory"]
    assert data["total"] == 1 and data["books"] == first.report["books"]
    assert data["file_identity"] == data["duplicates"] == "not_assessed"
    assert data["ready"] is False
    assert (
        client.get(f"/api/library/reconciliations/{first.pk}", {"status": "unmatched"}).json()[
            "total"
        ]
        == 0
    )
    assert LibraryReconciliation.objects.count() == 2


def test_control_only_promotes_selected_coverage_when_both_sources_match(
    library, catalogue_fixture, client, settings
):
    saved = fixtures.run(catalogue_fixture)
    params = dict(zip(("version", "sha256"), fixtures.pins(catalogue_fixture), strict=True))
    path = "/api/catalogue/control"
    assert client.get(path, params).json()["counts"]["unmatched"] is None
    params["reconciliation"] = str(saved.pk)
    data = client.get(path, params).json()
    assert data["library_matching"]["status"] == "matches_selected_sources"
    assert data["library_matching"]["counts"] == saved.report["counts"]
    assert data["counts"]["unmatched"] == 0
    fixtures.update(library, "UPDATE books SET title='Changed'")
    data = client.get(path, params).json()
    assert data["library_matching"]["status"] == "historical"
    assert data["counts"]["unmatched"] is None
    assert data["library_matching"]["counts"] == saved.report["counts"]
    settings.DIRECT_LIBRARY_ROOT = ""
    data = client.get(path, params).json()
    assert data["library_matching"]["status"] == "unconfirmed"
    assert data["counts"]["unmatched"] is None


def test_control_catalogue_digest_mismatch_keeps_coverage_historical(
    library, catalogue_fixture, client
):
    saved = fixtures.run(catalogue_fixture)
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute("UPDATE work SET title='New catalogue bytes'")
    version, digest = fixtures.pins(catalogue_fixture)
    data = client.get(
        "/api/catalogue/control",
        {"version": version, "sha256": digest, "reconciliation": str(saved.pk)},
    ).json()
    assert data["library_matching"]["status"] == "historical"
    assert data["counts"]["unmatched"] is None


@pytest.mark.parametrize("query", [{"page": "0"}, {"page": "10001"}, {"x": "x"}, "page=1&page=2"])
def test_saved_report_discovery_rejects_unbounded_or_duplicate_parameters(client, query):
    reply = (
        client.get("/api/library/reconciliations?" + query)
        if isinstance(query, str)
        else client.get("/api/library/reconciliations", query)
    )
    assert reply.status_code == 400


def test_saved_report_errors_and_methods(library, catalogue_fixture, client):
    saved = fixtures.run(catalogue_fixture)
    path = f"/api/library/reconciliations/{saved.pk}"
    for query in (
        {"status": "invented"},
        {"page": "-1"},
        {"page": "x"},
        {"x": "x"},
        "status=held&status=matched",
    ):
        reply = (
            client.get(path + "?" + query) if isinstance(query, str) else client.get(path, query)
        )
        assert reply.status_code == 400
    assert client.get(f"/api/library/reconciliations/{uuid.uuid4()}").status_code == 404
    assert client.post(path).status_code == 405
    assert client.post("/api/library/reconciliations").status_code == 405


def test_report_paging_is_bounded_and_stable(library, catalogue_fixture, client):
    for key in range(2, 29):
        fixtures.update(
            library,
            "INSERT INTO books(id,title,sort,path,uuid) VALUES(?,?,?,?,?)",
            (key, "Book", "Book", "Book", str(key)),
        )
    saved = fixtures.run(catalogue_fixture)
    data = client.get(f"/api/library/reconciliations/{saved.pk}", {"page": 2}).json()
    assert data["total"] == 28 and data["pages"] == 2
    assert len(data["books"]) == 4
    assert [e["book"]["id"] for e in data["books"]] == ["25", "26", "27", "28"]


recycled_wal = fixtures.test_direct_library.recycled_wal


def test_recycled_wal_never_promotes_saved_counts_as_current(
    library, recycled_wal, catalogue_fixture, client
):
    saved = fixtures.run(catalogue_fixture)
    params = {**saved.report["catalogue"], "reconciliation": str(saved.pk)}
    params.pop("fixture")
    assert (
        client.get("/api/catalogue/control", params).json()["library_matching"]["status"]
        == "matches_selected_sources"
    )
    recycled_wal.execute("UPDATE books SET title='Changed after saved coverage'")
    recycled_wal.commit()
    reply = client.get("/api/catalogue/control", params)
    assert reply.status_code == 200
    data = reply.json()
    assert data["library_matching"]["status"] == "historical"
    assert data["counts"]["unmatched"] is None
    assert data["library_matching"]["counts"] == saved.report["counts"]


def test_wal_fence_deadline_keeps_current_counts_unconfirmed(
    library, recycled_wal, catalogue_fixture, client, monkeypatch
):
    from librarium import direct_library

    saved = fixtures.run(catalogue_fixture)
    monkeypatch.setattr(direct_library, "SECONDS", -1)
    params = {key: saved.report["catalogue"][key] for key in ("version", "sha256")}
    params["reconciliation"] = str(saved.pk)
    reply = client.get("/api/catalogue/control", params)
    assert reply.status_code == 200
    assert reply.json()["library_matching"]["status"] == "unconfirmed"
    assert reply.json()["counts"]["unmatched"] is None


checkpointed_wal = fixtures.test_direct_library.checkpointed_wal


def test_checkpointed_database_never_promotes_saved_counts_as_current(
    library, checkpointed_wal, catalogue_fixture, client
):
    saved = fixtures.run(catalogue_fixture)
    params = {key: saved.report["catalogue"][key] for key in ("version", "sha256")}
    params["reconciliation"] = str(saved.pk)
    assert (
        client.get("/api/catalogue/control", params).json()["library_matching"]["status"]
        == "matches_selected_sources"
    )
    checkpointed_wal.execute("UPDATE books SET title='Changed after checkpoint'")
    checkpointed_wal.commit()
    assert checkpointed_wal.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    reply = client.get("/api/catalogue/control", params)
    assert reply.status_code == 200
    assert reply.json()["library_matching"]["status"] == "historical"
    assert reply.json()["counts"]["unmatched"] is None
    assert reply.json()["library_matching"]["counts"] == saved.report["counts"]
