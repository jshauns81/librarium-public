"""Alias evidence comes only from the one catalogue work this book exactly matches."""

import sqlite3
from contextlib import closing

import pytest
from librarium import cover_candidates
from librarium.models import CoverReviewEntry
from tests.test_cover_candidates import covers as covers_fixture
from tests.test_cover_candidates import library as library_fixture
from tests.test_cover_candidates import page as page_fixture
from tests.test_cover_candidates import request

covers, library, page = covers_fixture, library_fixture, page_fixture
pytestmark = pytest.mark.django_db


def catalogue(covers, *statements):
    with closing(sqlite3.connect(covers[0])) as db, db:
        for statement in statements:
            db.execute(*statement) if isinstance(statement, tuple) else db.execute(statement)


def titles(page, client):
    url, params = request(page, client)
    entry = CoverReviewEntry.objects.get(pk=url.split("/")[3])
    return cover_candidates.matched_work_titles(entry, params)


def test_titles_are_the_canonical_title_and_recorded_aliases_of_the_matched_work(
    page, covers, client
):
    catalogue(covers, "INSERT INTO work_alias VALUES('w_fixture','Titre Etranger')")
    found = titles(page, client)
    assert "Fixture Cover" in found and "Titre Etranger" in found


def test_a_homonymous_work_by_someone_else_contributes_nothing(page, covers, client):
    catalogue(
        covers,
        "INSERT INTO work_alias VALUES('w_fixture','Titre Etranger')",
        "INSERT INTO work(id, title) VALUES ('w_other', 'Fixture Cover')",
        "INSERT INTO author VALUES(2,'Another Person','Person')",
        "INSERT INTO work_author VALUES('w_other',2,'author')",
        "INSERT INTO work_alias VALUES('w_other','It')",
    )
    found = titles(page, client)
    assert "Titre Etranger" in found and "It" not in found


def test_no_exact_catalogue_match_means_no_alias_evidence(page, covers, client):
    catalogue(
        covers,
        "INSERT INTO work_alias VALUES('w_fixture','Titre Etranger')",
        "DELETE FROM work_author",
    )
    assert titles(page, client) == []


def test_two_equally_exact_works_are_ambiguous_and_give_no_evidence(page, covers, client):
    catalogue(
        covers,
        "INSERT INTO work_alias VALUES('w_fixture','Titre Etranger')",
        "INSERT INTO work(id, title) VALUES ('w_twin', 'Fixture Cover')",
        "INSERT INTO work_author VALUES('w_twin',1,'author')",
        "INSERT INTO work_alias VALUES('w_twin','It')",
    )
    assert titles(page, client) == []


def test_an_unavailable_snapshot_gives_no_evidence_instead_of_failing(page, covers, client):
    url, params = request(page, client)
    entry = CoverReviewEntry.objects.get(pk=url.split("/")[3])
    stale = {**params, "sha256": "0" * 64}
    assert cover_candidates.matched_work_titles(entry, stale) == []
    assert cover_candidates.matched_work_titles(entry, {}) == []


def test_an_empty_catalogue_gives_no_evidence(page, covers, client):
    catalogue(covers, "DELETE FROM work_alias", "DELETE FROM work_author", "DELETE FROM work_cover")
    assert titles(page, client) == []
