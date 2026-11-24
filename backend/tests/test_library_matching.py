"""Native library metadata agreement preserves ambiguity and source spellings."""

import json
import sqlite3
from contextlib import closing

import pytest
import test_catalogue
import test_direct_library
from django.test import RequestFactory
from librarium import catalogue, direct_library, library_matching

catalogue_fixture = test_catalogue.catalogue
library = test_direct_library.library


def book(**changes):
    return {
        "id": "1",
        "uuid": "book-uuid",
        "title": "Fixture: The Glass Meridian",
        "authors": ["Fixture Author"],
        "identifiers": [],
        **changes,
    }


def assess(catalogue_fixture, value):
    root, _ = catalogue_fixture
    with catalogue.snapshot(str(root), fixture=True) as (db, info):
        return library_matching.match(value, db, info, {"token": "a" * 64})


def alter(catalogue_fixture, sql, args=()):
    with closing(sqlite3.connect(catalogue_fixture[1])) as db, db:
        db.execute(sql, args)


def test_exact_title_and_complete_alias_credits_keep_calibre_spelling(catalogue_fixture):
    alter(catalogue_fixture, "INSERT INTO author_alias VALUES (1,'Other Spelling')")
    data = assess(catalogue_fixture, book(authors=["Other Spelling"]))
    assert data["status"] == "matched" and data["basis"] == "title_and_authors"
    assert data["book"]["authors"] == ["Other Spelling"]
    assert data["candidates"][0]["author_matches"][0]["basis"] == "alias"
    assert data["ready"] is False


def test_partial_coauthor_and_global_alias_collision_never_match(catalogue_fixture):
    alter(catalogue_fixture, "INSERT INTO author VALUES(2,'Second Author','Second')")
    alter(catalogue_fixture, "INSERT INTO work_author VALUES('w_fixture',2,'author')")
    assert assess(catalogue_fixture, book())["status"] == "disagreement"
    alter(catalogue_fixture, "INSERT INTO author_alias VALUES(2,'Fixture Author')")
    data = assess(catalogue_fixture, book())
    assert data["status"] == "ambiguous"


def test_unique_isbn_with_wrong_title_explains_disagreement(catalogue_fixture):
    value = book(title="Another book", identifiers=[{"type": "isbn", "value": "0306406152"}])
    data = assess(catalogue_fixture, value)
    assert data["status"] == "disagreement"
    assert data["identifiers"][0]["canonical_isbn13"] == "9780306406157"
    assert data["candidates"][0]["identifier_match"] is True


@pytest.mark.parametrize("case", ["collision", "disputed", "orphan"])
def test_identifier_ambiguity_cannot_fall_through_to_favorable_names(catalogue_fixture, case):
    if case == "collision":
        alter(catalogue_fixture, "INSERT INTO work(id,title) VALUES('other','Different')")
        alter(
            catalogue_fixture,
            "INSERT INTO edition(id,work_id,isbn13) VALUES('other','other','9780306406157')",
        )
    elif case == "disputed":
        alter(
            catalogue_fixture,
            "INSERT INTO edition_ident VALUES('e_fixture','isbn13','9780306406157','disputed')",
        )
    else:
        alter(catalogue_fixture, "INSERT INTO edition(id,isbn13) VALUES('other','9780306406157')")
    assert (
        assess(catalogue_fixture, book(identifiers=[{"type": "isbn", "value": "9780306406157"}]))[
            "status"
        ]
        == "ambiguous"
    )


def test_explicit_work_identifier_alias_and_conflicting_identifiers(catalogue_fixture):
    alter(catalogue_fixture, "INSERT INTO id_alias VALUES('old','w_fixture')")
    data = assess(catalogue_fixture, book(identifiers=[{"type": "bl_catalog", "value": "old"}]))
    assert data["status"] == "matched" and data["basis"] == "identifier_and_metadata"
    assert data["identifiers"][0]["work_id"] == "w_fixture"
    alter(catalogue_fixture, "INSERT INTO work(id,title) VALUES('other','Different')")
    identifiers = [
        {"type": "bl_catalog", "value": "other"},
        {"type": "isbn", "value": "9780306406157"},
    ]
    assert assess(catalogue_fixture, book(identifiers=identifiers))["status"] == "ambiguous"


def test_unknown_title_and_unsupported_ids_stay_unmatched(catalogue_fixture):
    data = assess(
        catalogue_fixture,
        book(title="Unlisted", identifiers=[{"type": "hardcover-id", "value": "123"}]),
    )
    assert data["status"] == "unmatched"
    assert data["identifiers"][0]["status"] == "unsupported"
    assert data["candidates"] == []


def test_duplicate_title_candidates_are_ambiguous(catalogue_fixture):
    alter(
        catalogue_fixture,
        "INSERT INTO work(id,title) VALUES('other','Fixture: The Glass Meridian')",
    )
    alter(catalogue_fixture, "INSERT INTO work_author VALUES('other',1,'author')")
    assert assess(catalogue_fixture, book())["status"] == "ambiguous"


def test_match_budget_refuses_instead_of_truncating(catalogue_fixture):
    with pytest.raises(catalogue.CatalogueError, match="limit"):
        assess(catalogue_fixture, book(authors=["a"] * 65))
    with pytest.raises(catalogue.CatalogueError, match="limit"):
        assess(catalogue_fixture, book(title="x" * 513))


def test_endpoint_binds_inventory_and_catalogue_and_refuses_duplicate_params(
    library, catalogue_fixture
):
    token = direct_library.browse()["inventory"]["token"]
    root, _ = catalogue_fixture
    with catalogue.snapshot(str(root), fixture=True) as (_, info):
        params = {"inventory": token, "version": info["version"], "sha256": info["sha256"]}
    request = RequestFactory().get("/api/direct-library/books/1/match", params)
    reply = library_matching.match_book(request, "1")
    assert reply.status_code == 200
    assert json.loads(reply.content)["inventory"]["token"] == token
    request.GET = request.GET.copy()
    request.GET.appendlist("inventory", token)
    assert library_matching.match_book(request, "1").status_code == 400


def test_recorded_title_alias_keeps_canonical_title_and_reports_basis(catalogue_fixture):
    alter(catalogue_fixture, "INSERT INTO work_alias VALUES('w_fixture','Alternative title')")
    data = assess(catalogue_fixture, book(title="Alternative title"))
    assert data["status"] == "matched"
    assert data["candidates"][0]["title"] == "Fixture: The Glass Meridian"
    assert data["candidates"][0]["title_basis"] == "recorded_alias"


def test_invalid_isbn_and_cyclic_work_alias_refuse_favorable_fallback(catalogue_fixture):
    data = assess(catalogue_fixture, book(identifiers=[{"type": "isbn", "value": "12345"}]))
    assert data["status"] == "ambiguous"
    alter(catalogue_fixture, "INSERT INTO id_alias VALUES('a','b')")
    alter(catalogue_fixture, "INSERT INTO id_alias VALUES('b','a')")
    data = assess(catalogue_fixture, book(identifiers=[{"type": "bl_catalog", "value": "a"}]))
    assert data["status"] == "ambiguous"


def test_candidate_budget_and_repeated_identifier_reference_budget_refuse(catalogue_fixture):
    for index in range(25):
        alter(
            catalogue_fixture,
            "INSERT INTO work(id,title) VALUES(?,?)",
            (f"duplicate{index}", "Fixture: The Glass Meridian"),
        )
    with pytest.raises(catalogue.CatalogueError, match="limit"):
        assess(catalogue_fixture, book())


def test_repeated_isbns_cannot_expand_more_than_combined_reference_budget(catalogue_fixture):
    for index in range(16):
        alter(
            catalogue_fixture,
            "INSERT INTO edition(id,work_id,isbn13) VALUES(?,'w_fixture','9780306406157')",
            (f"edition{index}",),
        )
    with pytest.raises(catalogue.CatalogueError, match="limit"):
        assess(
            catalogue_fixture, book(identifiers=[{"type": "isbn", "value": "9780306406157"}] * 16)
        )


def test_match_endpoint_rejects_stale_inventory_and_changed_catalogue(library, catalogue_fixture):
    token = direct_library.browse()["inventory"]["token"]
    root, _ = catalogue_fixture
    with catalogue.snapshot(str(root), fixture=True) as (_, info):
        params = {"inventory": token, "version": info["version"], "sha256": info["sha256"]}
    bad_inventory = RequestFactory().get("/match", {**params, "inventory": "0" * 64})
    assert library_matching.match_book(bad_inventory, "1").status_code == 409
    bad_catalogue = RequestFactory().get("/match", {**params, "sha256": "0" * 64})
    assert library_matching.match_book(bad_catalogue, "1").status_code == 409
    missing_pin = RequestFactory().get("/match")
    assert library_matching.match_book(missing_pin, "1").status_code == 400
