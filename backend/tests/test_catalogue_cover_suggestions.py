"""Local suggestions keep uncertainty visible and require an explicit choice."""

import sqlite3
from contextlib import closing

import pytest
from librarium import cover_candidates
from tests.test_cover_candidates import choose, request, store
from tests.test_cover_candidates import covers as covers_fixture
from tests.test_cover_candidates import library as library_fixture
from tests.test_cover_candidates import page as page_fixture

covers, library, page = covers_fixture, library_fixture, page_fixture
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("alias", [False, True])
def test_exact_title_or_alias_does_not_claim_catalogue_absence(
    page, covers, settings, client, alias
):
    store(covers, settings)
    if alias:
        with closing(sqlite3.connect(covers[0])) as db, db:
            db.execute("UPDATE work SET title='Another Publication' WHERE id='w_fixture'")
            db.execute("INSERT INTO work_alias VALUES('w_fixture','Fixture Cover')")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["source"] == {"status": "complete", "reason": ""}
    assert data["default_candidate_id"] is not None


@pytest.mark.parametrize("alias", [False, True])
def test_near_title_and_author_offer_verified_art_without_a_default(
    page, covers, settings, client, alias
):
    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work SET title='Fixture Covers' WHERE id='w_fixture'")
        if alias:
            db.execute("UPDATE work SET title='Another Publication' WHERE id='w_fixture'")
            db.execute("INSERT INTO work_alias VALUES('w_fixture','Fixture Covers')")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["candidates"] and data["default_candidate_id"] is None
    assert data["source"]["reason"] == "No exact catalogue entry."
    c = data["candidates"][0]
    assert c["catalogue_suggestion"] and 0.6 < c["catalogue_confidence"] < 1
    assert c["selectable"] and "Catalogue suggestion" in c["reason"]
    assert choose(client, url, params, data, c["id"]).status_code == 201
    assert (
        client.get(url, params, REMOTE_USER="reviewer").json()["selection"]["status"]
        == "awaiting_approval"
    )
    queue = client.get("/api/cover-reviews", REMOTE_USER="reviewer").json()
    assert next(e for e in queue["entries"] if e["book_id"] == "1")["selection_pending"]


def test_different_author_cannot_become_a_fuzzy_suggestion(page, covers, settings, client):
    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work SET title='Fixture Covers'")
        db.execute("UPDATE author SET name='Unrelated Person'")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert not data["candidates"]
    assert data["source"]["reason"] == "No catalogue entry for this book."


def test_catalogue_absence_is_independent_of_web_candidates(
    page, covers, settings, client, monkeypatch
):
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("DELETE FROM work")
    monkeypatch.setattr(cover_candidates, "latest", lambda *a: None)
    from librarium import cover_sources

    monkeypatch.setattr(
        cover_sources, "candidates", lambda *a: [{"id": "web", "label": "Web", "selectable": False}]
    )
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["candidates"]
    assert data["source"] == {"status": "empty", "reason": "No catalogue entry for this book."}


def test_contained_story_offers_parent_art_with_relationship_and_no_default(
    page, covers, settings, client
):
    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute(
            "UPDATE work SET title='Collected Stories',type='anthology' WHERE id='w_fixture'"
        )
        db.execute("INSERT INTO work(id,title,type) VALUES('story','Fixture Cover','short_story')")
        db.execute("INSERT INTO work_author VALUES('story',1,'author')")
        db.execute("INSERT INTO work_contains VALUES('w_fixture','story',1)")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["candidates"] and data["default_candidate_id"] is None
    c = data["candidates"][0]
    assert c["catalogue_suggestion"] and c["relationship"] == "contained_in"
    assert not c["selectable"] and "Contains" in c["reason"]


def test_saved_exact_choice_cannot_silently_become_a_suggestion(page, covers, settings, client):
    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data).status_code == 201
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work SET title='Fixture Covers' WHERE id='w_fixture'")
    _, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["selection"]["status"] == "stale"


def test_catalogue_work_kind_blocks_a_fuzzy_anthology_even_without_title_suffix(
    page, covers, settings, client
):
    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work SET title='Fixture Covers',type='anthology' WHERE id='w_fixture'")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["candidates"] and not any(c["selectable"] for c in data["candidates"])


def test_author_typo_replaces_blocked_exact_title_with_explicit_suggestion(
    page, covers, settings, client
):
    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE author SET name='Some Writter'")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert len(data["candidates"]) == 2
    assert all(c.get("catalogue_suggestion") and c["selectable"] for c in data["candidates"])
    assert data["default_candidate_id"] is None
    candidate = data["candidates"][0]
    assert choose(client, url, params, data, candidate["id"]).status_code == 201
    assert (
        client.get(url, params, REMOTE_USER="reviewer").json()["selection"]["status"]
        == "awaiting_approval"
    )


def test_more_than_sixteen_matches_keep_choices_and_web_results_available(
    page, covers, settings, client, monkeypatch
):
    from librarium import cover_sources

    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work SET title='Fixture Covers' WHERE id='w_fixture'")
        for n in range(20):
            work = f"franchise_{n:02}"
            db.execute(
                "INSERT INTO work(id,title,type) VALUES(?,?,'novel')", (work, f"Fixture Cover {n}")
            )
            db.execute("INSERT INTO work_author VALUES(?,1,'author')", (work,))
    monkeypatch.setattr(
        cover_sources, "candidates", lambda *a: [{"id": "web", "selectable": False}]
    )
    url, params = request(page, client)
    reply = client.get(url, params, REMOTE_USER="reviewer")
    assert reply.status_code == 200
    data = reply.json()
    assert data["candidates"][-1]["id"] == "web"
    suggestions = [c for c in data["candidates"] if c.get("catalogue_suggestion")]
    assert suggestions and len(suggestions) <= 8
    assert all(c["work_id"] == "w_fixture" for c in suggestions)
    assert data["default_candidate_id"] is None


def test_any_shared_author_can_support_a_multi_author_suggestion(covers):
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("INSERT INTO author VALUES(1,'Example Writer','Writer')")
        db.execute("INSERT INTO work_author VALUES('w_fixture',1,'author')")
        suggestions = cover_candidates.catalogue_suggestions(
            db,
            {
                "title": "Fixture Covers",
                "authors": ["Example Writer", "Other Contributor"],
                "identifiers": [],
            },
            {"status": "unmatched", "identifiers": []},
        )
    assert [s["work_id"] for s in suggestions] == ["w_fixture"]
