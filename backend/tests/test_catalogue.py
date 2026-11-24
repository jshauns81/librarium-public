import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

VERSION = "2026.10.25.1"
SCHEMA = Path(__file__).parent / "fixtures/blc-schema.sql"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2006", (2006, 99, 99)),
        ("2006-04", (2006, 4, 99)),
        ("2006-04-01", (2006, 4, 1)),
        ("2006-04-01T12:00:00Z", (2006, 4, 1)),
        (None, (9999, 99, 99)),
        ("", (9999, 99, 99)),
        ("not recorded", (9999, 99, 99)),
    ],
)
def test_publication_prefixes_sort_unknown_parts_after_known_parts(value, expected):
    from librarium.catalogue import publication_key

    assert publication_key(value) == expected


def test_canonical_lead_uses_known_dates_before_year_or_month_only(client, catalogue):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work SET type='novel',first_published='2006' WHERE id='w_fixture'")
        for work_id, published in [("w_month", "2006-04"), ("w_day", "2006-04-01")]:
            db.execute(
                "INSERT INTO work(id,title,type,first_published) VALUES (?,?,'novel',?)",
                (work_id, work_id, published),
            )
            db.execute("INSERT INTO work_series VALUES (?,1,2)", (work_id,))
    data = client.get("/api/catalogue/works/w_fixture", pin(client)).json()
    assert data["series"][0]["lead_work_id"] == "w_day"
    assert data["series"][0]["work_count"] == 3


def make_snapshot(root: Path, version: str = VERSION, title: str = "Fixture: The Glass Meridian"):
    root.mkdir(exist_ok=True)
    path = root / f"{version}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (version,))
        db.execute(
            "INSERT INTO work(id, title, synopsis) VALUES ('w_fixture', ?, 'Fictional contract data')",
            (title,),
        )
        db.execute("INSERT INTO author VALUES (1, 'Fixture Author', 'Author')")
        db.execute("INSERT INTO work_author VALUES ('w_fixture', 1, 'author')")
        db.execute("INSERT INTO series VALUES (1, 'Fixture Series')")
        db.execute("INSERT INTO work_series VALUES ('w_fixture', 1, 2)")
        db.execute(
            "INSERT INTO edition(id, work_id, format, isbn13) VALUES ('e_fixture', 'w_fixture', 'ebook', '9780306406157')"
        )
        db.execute(
            "INSERT INTO field_support VALUES ('work', 'w_fixture', 'title', ?, 0.8, ?, '[]')",
            (title, '["publisher"]'),
        )
    (root / "current").write_text(version)
    return path


@pytest.fixture
def catalogue(tmp_path, settings):
    root = tmp_path / "catalogue"
    path = make_snapshot(root)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    return root, path


def pin(client):
    response = client.get("/api/catalogue")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    return {"version": data["version"], "sha256": data["sha256"]}


@pytest.mark.parametrize("series, expected", [(2**63 - 1, 200), (2**63, 400), (10**100, 400)])
def test_series_query_respects_sqlite_integer_bounds(client, catalogue, series, expected):
    result = client.get("/api/catalogue/works", {**pin(client), "series": series})
    assert result.status_code == expected
    if expected == 200:
        assert result.json()["total"] == 0


@pytest.mark.parametrize(
    "author, expected",
    [(1, 200), (0, 400), (-1, 400), (2**63 - 1, 200), (2**63, 400), (10**100, 400)],
)
def test_author_query_respects_sqlite_integer_bounds(client, catalogue, author, expected):
    result = client.get("/api/catalogue/works", {**pin(client), "author": author})
    assert result.status_code == expected
    if expected == 200 and author != 1:
        assert result.json()["total"] == 0


def test_unconfigured_catalogue_is_an_explicit_empty_state(client, settings):
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    assert client.get("/api/catalogue").json() == {"status": "not_configured"}


def wsgi_boot(root):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
from librarium import catalogue
catalogue.validate.cache_clear()
from librarium.wsgi import application
before = catalogue.validate.cache_info().misses
from django.test import Client
result = Client().get('/api/catalogue', HTTP_HOST='localhost')
print(json.dumps({'before_request': before, 'after_request': catalogue.validate.cache_info().misses, 'status': result.status_code}))
""",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "LIBRARIUM_CATALOGUE_DIR": str(root),
            "LIBRARIUM_CATALOGUE_FIXTURE": "1",
            "LIBRARIUM_PUBLIC_ORIGIN": "",
            "LIBRARIUM_TRUST_PROXY": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_wsgi_admits_the_catalogue_before_accepting_the_first_request(catalogue):
    root, _ = catalogue
    result = wsgi_boot(root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"before_request": 1, "after_request": 1, "status": 200}


def test_wsgi_refuses_to_start_with_a_configured_invalid_catalogue(tmp_path):
    result = wsgi_boot(tmp_path)
    assert result.returncode != 0
    assert "Catalogue" in result.stderr


def test_schema_fixture_is_exact_committed_upstream_contract():
    assert (
        hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
        == "dff500b1f4ae5537fe6a613ee32cd78e7f8a7db83e5280dbcbdc8de822ad27d3"
    )


def test_browse_and_detail_are_pinned_readonly_and_do_not_claim_ownership(client, catalogue):
    root, path = catalogue
    before = path.read_bytes()
    token = pin(client)
    listing = client.get("/api/catalogue/works", token).json()
    assert listing["total"] == 1
    assert listing["selected_author"] is None
    assert listing["selected_series"] is None
    assert listing["works"][0]["type"] is None
    assert listing["works"][0]["first_published"] is None
    assert listing["works"][0]["authors"][0] == {
        "id": "1",
        "name": "Fixture Author",
        "version": VERSION,
    }
    assert listing["works"][0]["series"][0]["version"] == VERSION
    detail = client.get("/api/catalogue/works/w_fixture", token).json()
    assert detail["authors"][0] == {
        "id": "1",
        "name": "Fixture Author",
        "version": VERSION,
    }
    assert detail["ownership"] == "unconfirmed"
    assert detail["editions"][0]["isbn13"] == "9780306406157"
    assert detail["support"][0]["agree"] == ["publisher"]
    assert detail["snapshot"]["fixture"] is True
    assert detail["snapshot"]["sha256"] == token["sha256"]
    assert path.read_bytes() == before
    assert sorted(p.name for p in root.iterdir()) == [f"{VERSION}.sqlite", "current"]


@pytest.mark.parametrize(
    "alternative",
    [
        '"Another title"',
        '["Another author", "A third author"]',
        '{"name":"Another series","position":2}',
    ],
)
def test_disagreements_preserve_upstream_origin_and_alternative_value(
    client, catalogue, alternative
):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "UPDATE field_support SET disagree_json=?",
            ('[{"origin":"lexicanum","value":' + alternative + "}]",),
        )
    detail = client.get("/api/catalogue/works/w_fixture", pin(client))
    assert detail.status_code == 200
    import json

    assert detail.json()["support"][0]["disagree"] == [
        {"origin": "lexicanum", "value": json.loads(alternative)}
    ]


def test_pointer_changes_cannot_mix_versions_or_reuse_series_ids(client, catalogue):
    root, _ = catalogue
    token = pin(client)
    make_snapshot(root, "2026.10.25.2", "Fixture: A Different Catalogue")
    assert client.get("/api/catalogue").json()["version"] == "2026.10.25.2"
    old = client.get("/api/catalogue/works/w_fixture", token).json()
    assert old["title"] == "Fixture: The Glass Meridian"
    assert old["series"][0]["version"] == VERSION
    assert old["authors"][0]["version"] == VERSION
    assert client.get("/api/catalogue/works", {**token, "series": 1}).json()["total"] == 1
    assert client.get("/api/catalogue/works", {**token, "author": 1}).json()["total"] == 1


@pytest.mark.parametrize(
    "query,total",
    [("Fixture Author", 1), ("Fixture Series", 1), ("absent", 0), ("%", 0), ("' OR 1=1 --", 0)],
)
def test_search_is_literal_and_matches_author_series_and_title(client, catalogue, query, total):
    assert client.get("/api/catalogue/works", {**pin(client), "q": query}).json()["total"] == total


def test_replaced_or_retained_away_snapshot_requires_explicit_reselection(client, catalogue):
    _, path = catalogue
    token = pin(client)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work SET title='Changed bytes'")
    assert client.get("/api/catalogue/works", token).status_code == 409
    path.unlink()
    assert client.get("/api/catalogue/works/w_fixture", token).status_code == 409


@pytest.mark.parametrize(
    "params",
    [
        {"version": "../../secret"},
        {"page": 0},
        {"q": "a" * 201},
        {"series": "bad"},
        {"author": "bad"},
        {"sha256": "x"},
        {"q": "\x00"},
    ],
)
def test_invalid_query_is_rejected(client, catalogue, params):
    assert client.get("/api/catalogue/works", params).status_code == 400


def test_detail_requires_pin_and_missing_work_is_404(client, catalogue):
    assert client.get("/api/catalogue/works/w_fixture").status_code == 400
    assert client.get("/api/catalogue/works/w_absent", pin(client)).status_code == 404
    assert client.post("/api/catalogue/works").status_code == 405
    assert client.get("/api/catalogue/works", {"series": 1}).status_code == 400
    assert client.get("/api/catalogue/works", {"author": 1}).status_code == 400


@pytest.mark.parametrize(
    "damage", ["schema", "version", "view", "corrupt", "symlink", "pointer", "wal"]
)
def test_invalid_snapshot_is_unavailable_without_leaking_paths(client, catalogue, tmp_path, damage):
    root, path = catalogue
    if damage == "corrupt":
        path.write_bytes(b"not a SQLite database")
    elif damage == "symlink":
        outside = tmp_path / "outside.sqlite"
        path.rename(outside)
        path.symlink_to(outside)
    elif damage == "pointer":
        (root / "current").write_text("../../outside")
    else:
        with closing(sqlite3.connect(path)) as db, db:
            if damage == "schema":
                db.execute("DROP TABLE field_support")
            elif damage == "view":
                db.execute("ALTER TABLE work RENAME TO hidden_work")
                db.execute("CREATE VIEW work AS SELECT * FROM hidden_work")
            elif damage == "wal":
                db.execute("PRAGMA journal_mode=WAL")
            else:
                db.execute("UPDATE meta SET value='wrong' WHERE key='catalog_version'")
    response = client.get("/api/catalogue")
    assert response.status_code == 503
    assert str(tmp_path) not in response.content.decode()


def test_series_browse_orders_positions_before_titles_and_paginates(client, catalogue):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        # The existing member is position 2. Include a fractional volume, ties,
        # an unnumbered member and enough volumes to cross a page boundary.
        members = [("w_half", "Z: A prelude", 0.5), ("w_tie", "A: Companion", 2)]
        members += [(f"w_volume{i:02}", f"Volume {i:02}", i) for i in range(3, 28)]
        members += [("w_unknown", "A: Unnumbered", None)]
        for wid, title, position in members:
            db.execute("INSERT INTO work(id, title) VALUES (?, ?)", (wid, title))
            db.execute("INSERT INTO work_series VALUES (?, 1, ?)", (wid, position))
        db.execute("INSERT INTO work(id, title) VALUES ('w_outside', 'Outside this series')")
        db.execute("INSERT INTO series VALUES (2, 'Other Series')")
        db.execute("INSERT INTO work_series VALUES ('w_half', 2, 99)")
    before = path.read_bytes()
    token = pin(client)
    first = client.get("/api/catalogue/works", {**token, "series": 1}).json()
    second = client.get("/api/catalogue/works", {**token, "series": 1, "page": 2}).json()
    assert first["selected_series"] == {
        "id": "1",
        "name": "Fixture Series",
        "version": VERSION,
        "credit": {"names": [], "others": 1},
    }
    ids = [w["id"] for w in first["works"] + second["works"]]
    assert ids[:3] == ["w_half", "w_tie", "w_fixture"]
    assert ids[-1] == "w_unknown"
    assert len(ids) == len(set(ids)) == first["total"] == 29
    assert "w_outside" not in ids
    assert second["page"] == 2
    assert first["snapshot"] == second["snapshot"]
    assert path.read_bytes() == before


def test_series_browse_groups_numbered_then_literal_zero_then_unpositioned(client, catalogue):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO author VALUES (2, 'Zero Author', 'Author, Zero')")
        db.execute("INSERT INTO series VALUES (2, 'Other Series')")
        # Literal zeros sort before 1 under plain numeric order; they outnumber
        # one page so the numbered run must still open the first page.
        members = [("w_neg_big", "M: Before the start", -1.5), ("w_neg", "A: Prologue", -1)]
        members += [("w_half", "Z: Interlude", 0.5)]
        members += [(f"w_vol{i:02}", f"Volume {i:02}", i) for i in range(3, 9)]
        members += [(f"w_zero{i:02}", f"A Zero {i:02}", 0) for i in range(20)]
        members += [("w_zero_tie_b", "A Zero 05", 0.0), ("w_zero_tie_a", "A Zero 05", 0)]
        members += [(f"w_none{i}", f"A None {i}", None) for i in range(3)]
        for wid, title, position in members:
            db.execute("INSERT INTO work(id, title) VALUES (?, ?)", (wid, title))
            db.execute("INSERT INTO work_series VALUES (?, 1, ?)", (wid, position))
        # Membership in another series must not move a work between groups.
        db.execute("INSERT INTO work_series VALUES ('w_zero00', 2, 1)")
        db.execute("INSERT INTO work_series VALUES ('w_none0', 2, 0)")
        db.execute("INSERT INTO work_series VALUES ('w_neg', 2, NULL)")
        for wid in ("w_neg", "w_zero03", "w_zero04", "w_none1"):
            db.execute("INSERT INTO work_author VALUES (?, 2, 'author')", (wid,))
    before = path.read_bytes()
    token = pin(client)
    first = client.get("/api/catalogue/works", {**token, "series": 1}).json()
    second = client.get("/api/catalogue/works", {**token, "series": 1, "page": 2}).json()
    ids = [w["id"] for w in first["works"] + second["works"]]
    numbered = ["w_neg_big", "w_neg", "w_half", "w_fixture"] + [f"w_vol{i:02}" for i in range(3, 9)]
    zeros = [f"w_zero{i:02}" for i in range(6)] + ["w_zero_tie_a", "w_zero_tie_b"]
    zeros += [f"w_zero{i:02}" for i in range(6, 20)]
    assert ids == numbered + zeros + ["w_none0", "w_none1", "w_none2"]
    assert len(first["works"]) == 24 and first["total"] == len(ids) == 35
    counts = {"numbered": 10, "zero": 22, "unpositioned": 3}
    assert first["position_counts"] == second["position_counts"] == counts
    assert first["selected_series"] == {
        "id": "1",
        "name": "Fixture Series",
        "version": VERSION,
        "credit": {"names": [], "others": 2},
    }
    assert first["snapshot"] == second["snapshot"]

    # Counts follow the exact filtered result, not the page or the whole series.
    searched = client.get("/api/catalogue/works", {**token, "series": 1, "q": "Zero 0"}).json()
    assert searched["position_counts"] == {"numbered": 0, "zero": 12, "unpositioned": 0}
    assert searched["total"] == 12
    by_author = client.get("/api/catalogue/works", {**token, "series": 1, "author": 2}).json()
    assert [w["id"] for w in by_author["works"]] == ["w_neg", "w_zero03", "w_zero04", "w_none1"]
    assert by_author["position_counts"] == {"numbered": 1, "zero": 2, "unpositioned": 1}
    other = client.get("/api/catalogue/works", {**token, "series": 2}).json()
    assert [w["id"] for w in other["works"]] == ["w_zero00", "w_none0", "w_neg"]
    assert other["position_counts"] == {"numbered": 1, "zero": 1, "unpositioned": 1}
    empty = client.get("/api/catalogue/works", {**token, "series": 1, "q": "absent"}).json()
    assert empty["position_counts"] == {"numbered": 0, "zero": 0, "unpositioned": 0}

    unfiltered = client.get("/api/catalogue/works", token).json()
    assert unfiltered["position_counts"] is None
    assert (
        client.get("/api/catalogue/works", {**token, "author": 2}).json()["position_counts"] is None
    )
    # Literal zeros stay zero in the per-work series evidence.
    assert first["works"][0]["series"][0]["position"] == -1.5
    zero_row = next(w for w in second["works"] if w["id"] == "w_zero19")
    assert zero_row["series"] == [
        {
            "id": "1",
            "name": "Fixture Series",
            "position": 0.0,
            "version": VERSION,
            "work_count": 35,
            "shelf_eligible": True,
        }
    ]
    assert path.read_bytes() == before


def test_series_search_preserves_selected_context_even_with_no_results(client, catalogue):
    result = client.get("/api/catalogue/works", {**pin(client), "series": 1, "q": "absent"})
    assert result.status_code == 200
    assert result.json()["works"] == []
    assert result.json()["selected_series"]["name"] == "Fixture Series"


def test_unknown_series_has_explicit_context_without_claiming_members(client, catalogue):
    result = client.get("/api/catalogue/works", {**pin(client), "series": 999})
    assert result.status_code == 200
    assert result.json()["selected_series"] is None
    assert result.json()["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "series=1&series=2",
        "author=1&author=2",
        "page=1&page=2",
        "series=1&extra=x",
        "author=1&extra=x",
    ],
)
def test_ambiguous_catalogue_filters_are_rejected(client, catalogue, query):
    from urllib.parse import urlencode

    result = client.get("/api/catalogue/works?" + urlencode(pin(client)) + "&" + query)
    assert result.status_code == 400


def test_series_index_is_searchable_counted_paginated_and_snapshot_bound(client, catalogue):
    root, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany(
            "INSERT INTO series VALUES (?, ?)", [(i, f"Series {i:02}") for i in range(2, 28)]
        )
        db.execute("INSERT INTO work(id, title) VALUES ('w_second', 'Second member')")
        db.execute("INSERT INTO work_series VALUES ('w_second', 1, 3)")
    token = pin(client)
    first = client.get("/api/catalogue/series", token)
    assert first.status_code == 200
    data = first.json()
    assert data["total"] == 27
    assert len(data["series"]) == 24
    assert data["series"][0] == {
        "id": "1",
        "name": "Fixture Series",
        "version": VERSION,
        "work_count": 2,
    }
    assert data["snapshot"]["sha256"] == token["sha256"]
    second = client.get("/api/catalogue/series", {**token, "page": 2}).json()
    assert len(second["series"]) == 3
    assert second["series"][0]["id"] == "25"
    assert client.get("/api/catalogue/series", {**token, "q": "Fixture"}).json()["total"] == 1
    assert client.get("/api/catalogue/series", {**token, "q": "%"}).json()["total"] == 0
    assert client.get("/api/catalogue/series", {**token, "q": "' OR 1=1 --"}).json()["total"] == 0
    assert client.get("/api/catalogue/series").status_code == 400
    assert client.post("/api/catalogue/series", token).status_code == 405
    make_snapshot(root, "2026.10.25.2")
    assert client.get("/api/catalogue/series", token).json()["total"] == 27
    path.unlink()
    assert client.get("/api/catalogue/series", token).status_code == 409


@pytest.mark.parametrize(
    "query", ["q=" + "a" * 201, "page=0", "page=1&page=2", "series=1"],
    ids=[
        "query-too-long",
        "page-zero",
        "page-duplicate",
        "unknown-filter",
    ],
)
def test_series_index_rejects_invalid_or_ambiguous_filters(client, catalogue, query):
    from urllib.parse import urlencode

    result = client.get("/api/catalogue/series?" + urlencode(pin(client)) + "&" + query)
    assert result.status_code == 400


def test_series_identity_survives_javascript_integer_precision_limits(client, catalogue):
    _, path = catalogue
    series_id = 2**53 + 1
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO series VALUES (?, 'Exact identity')", (series_id,))
        db.execute("INSERT INTO work_series VALUES ('w_fixture', ?, 1)", (series_id,))
    token = pin(client)
    index = client.get("/api/catalogue/series", {**token, "q": "Exact"}).json()
    assert index["series"][0]["id"] == str(series_id)
    listing = client.get("/api/catalogue/works", {**token, "series": str(series_id)}).json()
    assert listing["selected_series"]["id"] == str(series_id)
    assert next(s for s in listing["works"][0]["series"] if s["name"] == "Exact identity")[
        "id"
    ] == str(series_id)


def test_author_browse_filters_exact_homonyms_excludes_non_author_roles_and_includes_bibliography_fields(
    client, catalogue
):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO author VALUES (2, 'Fixture Author', 'Author')")
        db.execute(
            "INSERT INTO work(id, title, sort_title, type, first_published) "
            "VALUES ('w_homonym', 'Homonym Work', 'Homonym Work', 'novel', '2021-05')"
        )
        db.execute("INSERT INTO work_author VALUES ('w_homonym', 2, 'author')")
        db.execute(
            "INSERT INTO work(id, title, sort_title, type, first_published) "
            "VALUES ('w_alpha', 'The Alpha Tome', 'Alpha Tome, The', 'anthology', '1999')"
        )
        db.execute("INSERT INTO work_author VALUES ('w_alpha', 1, 'author')")
        db.execute(
            "INSERT INTO work(id, title, type, first_published) "
            "VALUES ('w_edited', 'Edited Anthology', 'anthology', '2020')"
        )
        db.execute("INSERT INTO work_author VALUES ('w_edited', 1, 'editor')")
        db.execute("INSERT INTO work_author VALUES ('w_edited', 1, 'narrator')")
        db.execute("INSERT INTO work_author VALUES ('w_edited', 1, 'cover_artist')")
    before = path.read_bytes()
    token = pin(client)
    author1 = client.get("/api/catalogue/works", {**token, "author": 1}).json()
    assert author1["selected_author"] == {"id": "1", "name": "Fixture Author", "version": VERSION}
    assert author1["selected_series"] is None
    assert [w["id"] for w in author1["works"]] == ["w_alpha", "w_fixture"]
    assert author1["works"][0]["type"] == "anthology"
    assert author1["works"][0]["first_published"] == "1999"
    assert author1["works"][1]["type"] is None
    assert author1["works"][1]["first_published"] is None

    author2 = client.get("/api/catalogue/works", {**token, "author": 2}).json()
    assert author2["selected_author"] == {"id": "2", "name": "Fixture Author", "version": VERSION}
    assert [w["id"] for w in author2["works"]] == ["w_homonym"]
    assert author2["works"][0]["type"] == "novel"
    assert author2["works"][0]["first_published"] == "2021-05"
    assert path.read_bytes() == before


def test_combined_author_series_and_query_preserves_series_order_and_context(client, catalogue):
    _, path = catalogue
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO author VALUES (2, 'Second Author', 'Author, Second')")
        db.execute(
            "INSERT INTO work(id, title, type, first_published) "
            "VALUES ('w_prequel', 'Z: Prequel Meridian', 'novella', '2018')"
        )
        db.execute("INSERT INTO work_author VALUES ('w_prequel', 1, 'author')")
        db.execute("INSERT INTO work_series VALUES ('w_prequel', 1, 1)")
        db.execute(
            "INSERT INTO work(id, title) VALUES ('w_other_author_in_series', 'A: Other Series Entry')"
        )
        db.execute("INSERT INTO work_author VALUES ('w_other_author_in_series', 2, 'author')")
        db.execute("INSERT INTO work_series VALUES ('w_other_author_in_series', 1, 0.5)")
        db.execute(
            "INSERT INTO work(id, title) VALUES ('w_author_outside_series', 'A: Standalone Meridian')"
        )
        db.execute("INSERT INTO work_author VALUES ('w_author_outside_series', 1, 'author')")
    token = pin(client)
    combined = client.get(
        "/api/catalogue/works", {**token, "author": 1, "series": 1, "q": "Meridian"}
    ).json()
    assert combined["selected_author"] == {"id": "1", "name": "Fixture Author", "version": VERSION}
    assert combined["selected_series"] == {
        "id": "1",
        "name": "Fixture Series",
        "version": VERSION,
        "credit": {"names": ["Fixture Author"], "others": 1},
    }
    assert [w["id"] for w in combined["works"]] == ["w_prequel", "w_fixture"]

    empty = client.get(
        "/api/catalogue/works", {**token, "author": 1, "series": 1, "q": "absent"}
    ).json()
    assert empty["works"] == []
    assert empty["total"] == 0
    assert empty["selected_author"] == {"id": "1", "name": "Fixture Author", "version": VERSION}
    assert empty["selected_series"] == combined["selected_series"]


def test_unknown_author_has_explicit_null_context_without_claiming_works(client, catalogue):
    result = client.get("/api/catalogue/works", {**pin(client), "author": 999})
    assert result.status_code == 200
    data = result.json()
    assert data["selected_author"] is None
    assert data["total"] == 0
    assert data["works"] == []


def test_author_identity_survives_javascript_integer_precision_limits(client, catalogue):
    _, path = catalogue
    author_id = 2**53 + 1
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO author VALUES (?, 'Precision Author', 'Author, Precision')", (author_id,)
        )
        db.execute("INSERT INTO work_author VALUES ('w_fixture', ?, 'author')", (author_id,))
    token = pin(client)
    listing = client.get("/api/catalogue/works", {**token, "author": str(author_id)}).json()
    assert listing["selected_author"] == {
        "id": str(author_id),
        "name": "Precision Author",
        "version": VERSION,
    }
    assert next(a for a in listing["works"][0]["authors"] if a["name"] == "Precision Author")[
        "id"
    ] == str(author_id)
    detail = client.get("/api/catalogue/works/w_fixture", token).json()
    assert next(a for a in detail["authors"] if a["name"] == "Precision Author")["id"] == str(
        author_id
    )
