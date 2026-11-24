"""Recorded author spellings stay inside one immutable synthetic catalogue."""

import sqlite3
from contextlib import closing

import pytest
import test_catalogue
from test_catalogue import VERSION, make_snapshot, pin

catalogue = test_catalogue.catalogue


def edit(path, sql, values=()):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(sql, values)


def alias(path, name="Fixture Pen Name", author=1):
    edit(path, "INSERT INTO author_alias VALUES (?,?)", (author, name))


def test_alias_search_finds_canonical_work_and_selected_author_group(client, catalogue):
    _, path = catalogue
    alias(path)
    token = pin(client)
    result = client.get("/api/catalogue/works", {**token, "q": "Pen Name"})
    assert result.status_code == 200
    data = result.json()
    assert data["total"] == 1
    assert data["works"][0]["authors"] == [
        {"id": "1", "name": "Fixture Author", "version": VERSION}
    ]
    evidence = data["author_evidence"]
    assert evidence["snapshot"] == {**token, "fixture": True}
    assert evidence["schema_version"] == "librarium.author-groups.v1"
    assert evidence["status"] == "available" and evidence["truncated"] is False
    assert evidence["groups"] == [
        {
            "author": {"id": "1", "name": "Fixture Author", "version": VERSION},
            "status": "complete",
            "canonical_owners": 1,
            "aliases": [{"name": "Fixture Pen Name", "owners": 1}],
            "alias_count": 1,
            "matched_aliases": [{"name": "Fixture Pen Name", "owners": 1}],
            "matched_alias_count": 1,
        }
    ]
    selected = client.get("/api/catalogue/works", {**token, "author": 1}).json()
    assert selected["author_evidence"]["groups"][0]["aliases"] == evidence["groups"][0]["aliases"]
    detail = client.get("/api/catalogue/works/w_fixture", token).json()
    assert detail["author_evidence"]["groups"] == selected["author_evidence"]["groups"]


def test_alias_search_is_literal_deduplicated_and_keeps_canonical_pagination(client, catalogue):
    _, path = catalogue
    alias(path, "Literal %_\\ spelling")
    alias(path, "Second %_\\ spelling")
    for index in range(30):
        edit(
            path, "INSERT INTO work(id,title) VALUES (?,?)", (f"w_{index:02}", f"Volume {index:02}")
        )
        edit(path, "INSERT INTO work_author VALUES (?,1,'author')", (f"w_{index:02}",))
    token = pin(client)
    first = client.get("/api/catalogue/works", {**token, "q": "%_\\"}).json()
    second = client.get("/api/catalogue/works", {**token, "q": "%_\\", "page": 2}).json()
    assert first["total"] == second["total"] == 31
    ids = [w["id"] for page in (first, second) for w in page["works"]]
    assert len(ids) == len(set(ids)) == 31
    assert ids == ["w_fixture", *(f"w_{i:02}" for i in range(30))]
    assert client.get("/api/catalogue/works", {**token, "q": "' OR 1=1 --"}).json()["total"] == 0


def test_alias_evidence_checks_owners_globally_including_uncredited_authors(client, catalogue):
    _, path = catalogue
    alias(path, "Shared Fixture Credit")
    edit(path, "INSERT INTO author VALUES (2,'Shared Fixture Credit',NULL)")
    alias(path, "Fixture Author", 2)
    token = pin(client)
    data = client.get("/api/catalogue/works", {**token, "q": "Shared Fixture"}).json()
    group = data["author_evidence"]["groups"][0]
    assert group["canonical_owners"] == 2
    assert group["aliases"] == [{"name": "Shared Fixture Credit", "owners": 2}]
    assert data["works"][0]["authors"][0]["id"] == "1"


@pytest.mark.parametrize(
    "damage,state",
    [
        ("missing", "missing"),
        ("schema", "incompatible"),
        ("view", "incompatible"),
        ("blank", "invalid"),
        ("oversize", "invalid"),
        ("blob", "invalid"),
        ("orphan", "invalid"),
        ("duplicate", "invalid"),
        ("control", "invalid"),
    ],
)
def test_unusable_alias_evidence_keeps_canonical_browse_truthful(client, catalogue, damage, state):
    _, path = catalogue
    if damage in {"missing", "schema", "view", "duplicate"}:
        edit(path, "DROP TABLE author_alias")
        if damage == "schema":
            edit(path, "CREATE TABLE author_alias(other TEXT)")
        elif damage == "view":
            edit(path, "CREATE VIEW author_alias AS SELECT id author_id,name FROM author")
        elif damage == "duplicate":
            edit(path, "CREATE TABLE author_alias(author_id INTEGER,name TEXT)")
            alias(path)
            alias(path)
    else:
        value = {
            "blank": " ",
            "oversize": "x" * 513,
            "blob": b"bytes",
            "control": "bad\x00name",
        }.get(damage, "Orphan")
        alias(path, value, 999 if damage == "orphan" else 1)
    token = pin(client)
    data = client.get("/api/catalogue/works", {**token, "q": "Fixture Author", "author": 1}).json()
    assert data["total"] == 1
    assert data["author_evidence"] == {
        "schema_version": "librarium.author-groups.v1",
        "snapshot": {**token, "fixture": True},
        "status": state,
        "groups": [],
        "truncated": False,
    }
    assert client.get("/api/catalogue/works", {**token, "q": "Pen Name"}).json()["total"] == 0


def test_alias_caps_keep_exact_counts_and_collisions_outside_display(client, catalogue):
    _, path = catalogue
    for index in range(40):
        alias(path, f"Alias {index:02}")
    edit(path, "INSERT INTO author VALUES (2,'Alias 39',NULL)")
    token = pin(client)
    group = client.get("/api/catalogue/works", {**token, "author": 1, "q": "Alias 39"}).json()[
        "author_evidence"
    ]["groups"][0]
    assert group["status"] == "truncated" and group["alias_count"] == 40
    assert len(group["aliases"]) == 32
    assert group["matched_aliases"] == [{"name": "Alias 39", "owners": 2}]
    group = client.get("/api/catalogue/works", {**token, "author": 1, "q": "Alias"}).json()[
        "author_evidence"
    ]["groups"][0]
    assert group["matched_alias_count"] == 40 and len(group["matched_aliases"]) == 8


def test_pinned_alias_groups_never_reuse_ids_from_new_pointer_or_changed_bytes(client, catalogue):
    root, path = catalogue
    alias(path, "Old Recorded Name")
    token = pin(client)
    newer = make_snapshot(root, "2026.10.25.2")
    edit(newer, "UPDATE author SET name='Different Person' WHERE id=1")
    alias(newer, "New Recorded Name")
    old = client.get("/api/catalogue/works", {**token, "q": "Old Recorded Name"}).json()
    assert old["author_evidence"]["groups"][0]["author"]["name"] == "Fixture Author"
    assert (
        client.get("/api/catalogue/works", {**token, "q": "New Recorded Name"}).json()["total"] == 0
    )
    edit(path, "UPDATE author_alias SET name='Changed' ")
    assert client.get("/api/catalogue/works", {**token, "author": 1}).status_code == 409


def test_group_author_cap_cannot_describe_incomplete_credits_as_complete(client, catalogue):
    _, path = catalogue
    for author_id in range(2, 67):
        edit(path, "INSERT INTO author VALUES (?, ?, NULL)", (author_id, f"Author {author_id:02}"))
        edit(path, "INSERT INTO work_author VALUES ('w_fixture',?,'author')", (author_id,))
    data = client.get("/api/catalogue/works/w_fixture", pin(client)).json()
    assert len(data["authors"]) == 66
    assert data["author_evidence"]["truncated"] is True
    assert len(data["author_evidence"]["groups"]) == 64


def test_matching_cap_is_explicit_even_when_the_whole_group_fits(client, catalogue):
    _, path = catalogue
    for index in range(9):
        alias(path, f"Match {index}")
    group = client.get("/api/catalogue/works", {**pin(client), "q": "Match"}).json()[
        "author_evidence"
    ]["groups"][0]
    assert group["status"] == "truncated"
    assert group["alias_count"] == len(group["aliases"]) == 9
    assert group["matched_alias_count"] == 9 and len(group["matched_aliases"]) == 8


def test_empty_recorded_group_and_unknown_author_are_distinct(client, catalogue):
    token = pin(client)
    selected = client.get("/api/catalogue/works", {**token, "author": 1}).json()
    group = selected["author_evidence"]["groups"][0]
    assert group["status"] == "complete" and group["alias_count"] == 0
    assert group["aliases"] == group["matched_aliases"] == []
    missing = client.get("/api/catalogue/works", {**token, "author": 999}).json()
    assert missing["selected_author"] is None and missing["author_evidence"]["groups"] == []


def test_alias_search_respects_author_roles_and_combined_author_series_context(client, catalogue):
    _, path = catalogue
    alias(path)
    edit(path, "INSERT INTO work(id,title) VALUES ('w_editor','Edited Volume')")
    edit(path, "INSERT INTO work_author VALUES ('w_editor',1,'editor')")
    token = pin(client)
    data = client.get(
        "/api/catalogue/works", {**token, "q": "Pen Name", "series": 1, "author": 1}
    ).json()
    assert [work["id"] for work in data["works"]] == ["w_fixture"]
    assert data["selected_author"]["id"] == data["selected_series"]["id"] == "1"
    assert client.get("/api/catalogue/works", {**token, "q": "Pen Name"}).json()["total"] == 1


def test_group_ownership_uses_existing_unicode_global_comparison_once(
    client, catalogue, monkeypatch
):
    from librarium import package_comparison

    _, path = catalogue
    for index in range(2, 26):
        edit(path, "INSERT INTO author VALUES (?,?,NULL)", (index, f"Author {index}"))
        edit(path, "INSERT INTO work_author VALUES ('w_fixture',?,'author')", (index,))
        alias(path, f"Shared Alias {index}", index)
    alias(path, "Caf\u00e9 Credit")
    edit(path, "INSERT INTO author VALUES (99,'CAFE\u0301 CREDIT',NULL)")
    calls = []
    original = package_comparison.name_owners

    def owners(db, names):
        calls.append(len(names))
        return original(db, names)

    monkeypatch.setattr(package_comparison, "name_owners", owners)
    data = client.get("/api/catalogue/works/w_fixture", pin(client)).json()
    assert len(data["author_evidence"]["groups"]) == 25
    group = next(g for g in data["author_evidence"]["groups"] if g["author"]["id"] == "1")
    assert group["aliases"] == [{"name": "Caf\u00e9 Credit", "owners": 2}]
    assert len(calls) == 1


def test_malformed_duplicate_work_credits_do_not_repeat_complete_groups(client, catalogue):
    _, path = catalogue
    edit(path, "DROP TABLE work_author")
    edit(path, "CREATE TABLE work_author(work_id TEXT,author_id INTEGER,role TEXT)")
    for _ in range(2):
        edit(path, "INSERT INTO work_author VALUES ('w_fixture',1,'author')")
    data = client.get("/api/catalogue/works/w_fixture", pin(client)).json()
    assert data["author_evidence"]["status"] == "invalid"
    assert data["author_evidence"]["groups"] == []
