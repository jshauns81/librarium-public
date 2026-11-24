"""Page-sized suggestions reuse the exact matcher without trusting client identities."""

import sqlite3
from contextlib import closing, contextmanager

import pytest
from librarium import catalogue, catalogue_covers, direct_library, library_read_model
from librarium.models import CoverReviewEntry
from tests.test_catalogue_covers import DIGEST
from tests.test_catalogue_covers import covers as covers_fixture
from tests.test_cover_reviews import drain, start
from tests.test_library_read_model import library as library_fixture
from tests.test_library_read_model import update

pytestmark = pytest.mark.django_db
BASE = "/api/cover-reviews/suggestions"
covers = covers_fixture
library = library_fixture


@pytest.fixture
def page(library, covers, client, settings):
    settings.LIBRARY_READ_MODEL_SECONDS = 0
    update(library, "UPDATE books SET title='Fixture Cover' WHERE id=1")
    update(library, "DELETE FROM identifiers")
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("INSERT INTO author VALUES(1,'Some Writer','Writer')")
        db.execute("INSERT INTO work_author VALUES('w_fixture',1,'author')")
    library_read_model.refresh()
    start()
    drain()
    queue = client.get("/api/cover-reviews", REMOTE_USER="reviewer").json()
    pin = client.get("/api/catalogue").json()
    params = {
        "inventory": queue["inventory"],
        "version": pin["version"],
        "sha256": pin["sha256"],
        "entry": [f"{e['id']}:{e['revision']}" for e in queue["entries"]],
    }
    return params, queue


def test_one_snapshot_for_the_page_and_only_exact_supported_art(page, client, monkeypatch):
    params, queue = page
    original = direct_library.snapshot
    snapshots = []
    queries = []
    original_catalogue = catalogue.snapshot

    @contextmanager
    def catalogue_snapshot(*args, **kwargs):
        with original_catalogue(*args, **kwargs) as (db, info):
            db.set_trace_callback(queries.append)
            yield db, info

    def no_file_reads(*args, **kwargs):
        raise AssertionError("Matching must not inspect every book's files or covers")

    @contextmanager
    def snapshot(*args, **kwargs):
        snapshots.append(args)
        with original(*args, **kwargs) as value:
            yield value

    monkeypatch.setattr(direct_library, "snapshot", snapshot)
    monkeypatch.setattr(catalogue, "snapshot", catalogue_snapshot)
    monkeypatch.setattr(direct_library, "book_files", no_file_reads)
    reply = client.get(BASE, params, REMOTE_USER="reviewer")
    assert reply.status_code == 200
    data = reply.json()
    assert len(snapshots) == 1
    assert sum("SELECT id,library_match_name(title) AS spelling" in q for q in queries) == 1
    assert sum("SELECT spelling,min(author_id)" in q for q in queries) == 1
    assert data["inventory"] == params["inventory"]
    assert data["snapshot"]["sha256"] == params["sha256"]
    assert len(data["entries"]) == len(queue["entries"])
    selected = next(e for e in data["entries"] if e["book_id"] == "1")
    assert selected["work_id"] == "w_fixture" and selected["cover"]["sha256"] == DIGEST
    assert all(e["cover"] is None for e in data["entries"] if e["book_id"] != "1")
    assert reply["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "case", ["many", "duplicate", "revision", "inventory", "pin", "extra", "empty"]
)
def test_refuses_unbounded_or_stale_page_requests(page, client, case):
    params, _ = page
    params = dict(params)
    if case == "many":
        params["entry"] = params["entry"] * 25
    elif case == "duplicate":
        params["entry"] = [params["entry"][0]] * 2
    elif case == "revision":
        params["entry"] = [params["entry"][0].split(":")[0] + ":999"]
    elif case == "inventory":
        params["inventory"] = "a" * 64
    elif case == "pin":
        params["sha256"] = "b" * 64
    elif case == "extra":
        params["work"] = "w_fixture"
    else:
        params.pop("entry")
    assert client.get(BASE, params, REMOTE_USER="reviewer").status_code in {400, 409}


def test_suggestions_require_an_operator(page, client):
    assert client.get(BASE, page[0]).status_code == 401


def test_mid_read_inventory_change_refuses_the_entire_batch(page, library, client, monkeypatch):
    original = catalogue_covers.metadata

    def metadata(*args, **kwargs):
        update(library, "UPDATE books SET title='Changed' WHERE id=1")
        return original(*args, **kwargs)

    monkeypatch.setattr(catalogue_covers, "metadata", metadata)
    assert client.get(BASE, page[0], REMOTE_USER="reviewer").status_code == 409


def test_ambiguous_metadata_never_supplies_suggested_art(page, covers, client):
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES('other','Fixture Cover')")
        db.execute("INSERT INTO work_author VALUES('other',1,'author')")
    pin = client.get("/api/catalogue").json()
    params = {**page[0], "version": pin["version"], "sha256": pin["sha256"]}
    reply = client.get(BASE, params, REMOTE_USER="reviewer")
    assert reply.status_code == 200
    assert all(e["cover"] is None for e in reply.json()["entries"])


@pytest.mark.parametrize(
    "change",
    [
        {"book_uuid": "different"},
        {"library_uuid": "different"},
        {"present": False},
        {"state": "done"},
    ],
)
def test_stale_entry_identity_or_queue_membership_refuses_the_batch(page, client, change):
    entry = page[1]["entries"][0]
    CoverReviewEntry.objects.filter(pk=entry["id"]).update(**change)
    assert client.get(BASE, page[0], REMOTE_USER="reviewer").status_code == 409


@pytest.mark.parametrize("changed", ["catalogue", "revision"])
def test_post_match_changes_refuse_the_entire_batch(page, covers, client, monkeypatch, changed):
    original = catalogue_covers.metadata

    def metadata(*args, **kwargs):
        result = original(*args, **kwargs)
        if changed == "catalogue":
            with closing(sqlite3.connect(covers[0])) as db, db:
                db.execute("UPDATE work SET title='Changed' WHERE id='w_fixture'")
        else:
            CoverReviewEntry.objects.filter(pk=page[1]["entries"][0]["id"]).update(revision=99)
        return result

    monkeypatch.setattr(catalogue_covers, "metadata", metadata)
    assert client.get(BASE, page[0], REMOTE_USER="reviewer").status_code == 409
