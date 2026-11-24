"""Series headings use canonical author roles across the complete pinned series."""

import sqlite3
from contextlib import closing

import pytest
from test_catalogue import make_snapshot, pin


@pytest.fixture
def catalogue(tmp_path, settings):
    root = tmp_path / "catalogue"
    path = make_snapshot(root)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    return root, path


def credit(client, token, **filters):
    response = client.get("/api/catalogue/works", {**token, "series": "1", **filters})
    assert response.status_code == 200
    return response.json()["selected_series"]["credit"]


@pytest.mark.parametrize(
    "assignments,expected",
    [
        ([[1], [1], [1], [2], [3]], {"names": ["Z Primary"], "others": 2}),
        ([[1], [1], [2], [3], [4]], {"names": ["Z Primary", "Y Second"], "others": 2}),
        ([[1, 2], [1, 2], [3], [4], [5], [6]], {"names": [], "others": 6}),
        ([[], [], [], [], []], {"names": [], "others": 0}),
        ([[1, 2]] * 8 + [[3], [4]], {"names": ["Z Primary", "Y Second"], "others": 2}),
        (
            [[1, 2]] * 5 + [[1], [1], [2], [3], [4], [5]],
            {"names": ["Z Primary", "Y Second"], "others": 3},
        ),
    ],
)
def test_series_credit_counts_canonical_names_and_distinct_work_coverage(
    client, catalogue, assignments, expected
):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM work_author")
        db.execute("DELETE FROM work_series")
        db.execute("DELETE FROM author")
        for number, name in enumerate(
            ["Z Primary", "Y Second", "A Third", "B Fourth", "C Fifth", "D Sixth"], 1
        ):
            db.execute("INSERT INTO author(id,name) VALUES (?,?)", (number, name))
        # Duplicate canonical names and editor credits must not inflate coverage.
        db.execute("INSERT INTO author(id,name) VALUES (7,'Z Primary')")
        db.execute("INSERT INTO author(id,name) VALUES (8,'Editor Only')")
        for number, authors in enumerate(assignments):
            work = f"w_credit_{number}"
            db.execute("INSERT INTO work(id,title) VALUES (?,?)", (work, f"Credit {number}"))
            db.execute("INSERT INTO work_series VALUES (?,1,?)", (work, number + 1))
            for author in authors:
                db.execute("INSERT INTO work_author VALUES (?,?,'author')", (work, author))
            if 1 in authors:
                db.execute("INSERT INTO work_author VALUES (?,7,'author')", (work,))
            db.execute("INSERT INTO work_author VALUES (?,8,'editor')", (work,))
    token = pin(client)
    assert credit(client, token) == expected
    # A filtered page, an empty late page or an author lens must not rewrite series credit.
    assert credit(client, token, q="Credit 0") == expected
    assert credit(client, token, page=2) == expected
    assert credit(client, token, author=2) == expected


def test_nonseries_browsing_does_not_acquire_series_credit(client, catalogue):
    token = pin(client)
    assert credit(client, token) == {"names": ["Fixture Author"], "others": 0}
    assert client.get("/api/catalogue/works", token).json()["selected_series"] is None
    assert (
        client.get("/api/catalogue/works", {**token, "series": 9}).json()["selected_series"] is None
    )
