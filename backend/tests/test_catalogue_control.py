import json
import sqlite3
from contextlib import closing

import pytest
import test_catalogue
from django.test import RequestFactory
from librarium import catalogue, catalogue_control

catalogue_fixture = test_catalogue.catalogue


@pytest.mark.parametrize("disagreement", ['{"source":"publisher"}', "null", '"unknown"'])
def test_malformed_disagreement_shapes_stay_in_attention_queue(catalogue_fixture, disagreement):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute(
            "INSERT INTO field_support VALUES('work','w_fixture','title','x',0.5,'[]',?)",
            (disagreement,),
        )
    assert control(catalogue_fixture, queue="conflicts")[1]["counts"]["conflicts"] == 1


def test_blank_canonical_author_is_incomplete(catalogue_fixture):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute("UPDATE work SET type='novel'")
        db.execute("UPDATE author SET name=' '")
    _, data = control(catalogue_fixture)
    assert "w_fixture" in {row["id"] for row in data["works"]}


def control(catalogue_fixture, **params):
    root, _ = catalogue_fixture
    with catalogue.snapshot(str(root), fixture=True) as (_, info):
        args = {"version": info["version"], "sha256": info["sha256"], **params}
    reply = catalogue_control.control(RequestFactory().get("/api/catalogue/control", args))
    return reply.status_code, json.loads(reply.content)


def test_control_counts_actionable_records_without_fabricating_producer_health(catalogue_fixture):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES('incomplete','Missing credits')")
        db.execute("INSERT INTO work(id,title) VALUES('duplicate','Fixture: The Glass Meridian')")
        db.execute(
            "INSERT INTO field_support VALUES('work','w_fixture','title','title',0.5,'[]','[\"other source\"]')"
        )
        db.execute(
            "INSERT INTO harvest_log(source,query,status,http_status,fetched_at) VALUES('fixture','private search','error',500,'2026-10-27T01:00:00Z')"
        )
    code, data = control(catalogue_fixture)
    assert code == 200
    assert data["counts"] == {
        "incomplete": 3,
        "conflicts": 1,
        "possible_duplicates": 2,
        "unmatched": None,
    }
    assert data["producer"]["status"] == "not_configured"
    assert data["library_matching"]["status"] == "not_assessed"
    assert "private search" not in json.dumps(data)
    assert data["source_observations"][0]["last_recorded_status"] == "error"
    assert data["source_observations"][0]["live"] is False


def test_each_queue_returns_only_its_rows_and_literal_reasons(catalogue_fixture):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES('duplicate','Fixture: The Glass Meridian')")
        db.execute(
            "INSERT INTO field_support VALUES('edition','e_fixture','publisher','x',0.5,'[]','[1]')"
        )
    _, data = control(catalogue_fixture, queue="conflicts")
    assert [w["id"] for w in data["works"]] == ["w_fixture"]
    assert data["works"][0]["reasons"] == ["Recorded source disagreements"]
    _, data = control(catalogue_fixture, queue="possible_duplicates")
    assert {w["id"] for w in data["works"]} == {"duplicate", "w_fixture"}
    assert data["works"][0]["reasons"] == ["Another catalogue work has the same normalized title"]


def test_control_paging_and_invalid_parameters(catalogue_fixture):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.executemany(
            "INSERT INTO work(id,title) VALUES(?,?)",
            [(f"w_{i}", f"Title {i:02}") for i in range(30)],
        )
    _, data = control(catalogue_fixture, page=2)
    assert len(data["works"]) == 7 and data["total"] == 31 and data["pages"] == 2
    assert control(catalogue_fixture, queue="invented")[0] == 400
    assert control(catalogue_fixture, page=0)[0] == 400
    assert (
        catalogue_control.control(RequestFactory().get("/api/catalogue/control")).status_code == 400
    )


def test_control_reports_native_producer_health_without_changing_the_queue_pin(
    catalogue_fixture, monkeypatch
):
    from librarium import reference_production

    native = {
        "status": "manual",
        "message": "Native imports run on request; automatic fetching is disabled.",
        "current": {"version": "2026.10.28.1", "sha256": "c" * 64, "fixture": True},
        "last_outcome": {"state": "succeeded", "records": 2},
    }
    monkeypatch.setattr(reference_production, "status", lambda: native)
    _, data = control(catalogue_fixture)
    assert data["producer"] == native
    assert data["snapshot"]["version"] == "2026.10.25.1"
    assert data["counts"]["unmatched"] is None


def test_producer_failure_does_not_hide_catalogue_attention_queues(catalogue_fixture, monkeypatch):
    from librarium import reference_production

    monkeypatch.setattr(
        reference_production,
        "status",
        lambda: {
            "status": "unavailable",
            "message": "Native import state needs recovery.",
            "current": None,
            "last_outcome": None,
        },
    )
    code, data = control(catalogue_fixture)
    assert code == 200 and data["producer"]["status"] == "unavailable"
    assert data["counts"]["incomplete"] > 0
