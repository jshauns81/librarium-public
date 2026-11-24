"""A library shelf is a complete pinned join, never a grouped alphabetical page."""

import copy
import hashlib
import importlib
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest
from test_library_evidence import TOKEN, VERSION, item, page, upstream


@pytest.fixture
def shelves_pin(tmp_path, settings):
    root = tmp_path / "catalogue"
    root.mkdir()
    path = root / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript((Path(__file__).parent / "fixtures/blc-schema.sql").read_text())
        db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (VERSION,))
        db.execute("INSERT INTO series VALUES (7, 'Gaunt''s Ghosts')")
        db.execute("INSERT INTO series VALUES (8, 'Last Chancers')")
        for n, position in enumerate([3, 0, None, -1, 1.5, 2, 4, 5]):
            db.execute(
                "INSERT INTO work(id,title,type) VALUES (?,?,'novel')",
                (f"w_fixture_{n}", f"Title {n}"),
            )
            db.execute("INSERT INTO work_series VALUES (?,7,?)", (f"w_fixture_{n}", position))
        db.execute("INSERT INTO work_series VALUES ('w_fixture_0',8,1)")
        db.execute("INSERT INTO work(id,title,type) VALUES ('w_fixture_8','Alone','novel')")
    (root / "current").write_text(VERSION)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = False
    return {"version": VERSION, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def response(items=None, **meta):
    values = items if items is not None else [item(n) for n in range(9)]
    return page(values, **meta)


def test_shelves_join_every_membership_and_restore_recorded_order(client, settings, shelves_pin):
    # LF has discarded positions and the extra membership. The pinned catalogue owns order.
    with upstream(settings, response()) as calls:
        r = client.get("/api/library/shelves", shelves_pin)
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 9 and d["series_total"] == 3
        assert d["catalogue_snapshot"]["sha256"] == shelves_pin["sha256"]
        assert d["coverage"] == "partial" and d["truncated"] is False
        gaunt, last, alone = d["shelves"]
        assert gaunt["name"] == "Gaunt's Ghosts" and gaunt["total"] == 8
        assert [w["id"] for w in gaunt["works"]] == [
            "w_fixture_3",
            "w_fixture_4",
            "w_fixture_5",
            "w_fixture_0",
            "w_fixture_6",
        ]
        assert gaunt["position_counts"] == {"numbered": 6, "zero": 1, "unpositioned": 1}
        assert gaunt["counts"]["saved"] == 8
        assert last["works"][0]["id"] == "w_fixture_0"
        assert alone["id"] is None and alone["name"] == "Standalone and collected"
        assert alone["catalogue_total"] == 1
        assert alone["works"][0]["series"] == []
        assert len(calls) == 1 and "sort=title" in calls[0][1]
        assert "private_path" not in r.content.decode() and "cover_url" not in r.content.decode()
        assert r["Cache-Control"] == "no-store"


def test_shelves_read_beyond_the_first_alphabetical_page_under_one_token(
    client, settings, shelves_pin
):
    values = [item(n) for n in range(201)]
    with upstream(
        settings, page(values[:200], total=201), page(values[200:], total=201, offset=200)
    ) as calls:
        d = client.get("/api/library/shelves", shelves_pin).json()
        assert d["total"] == 201
        assert d["shelves"][0]["works"][0]["id"] == "w_fixture_3"
        # Unrecognised LF identities cannot be assigned catalogue memberships.
        assert d["unlinked_total"] == 192
        assert "snapshot=" + TOKEN in calls[1][1]


@pytest.mark.parametrize("mutation", ["token", "date", "coverage", "total", "duplicate"])
def test_shelves_never_mix_checks_or_duplicate_work_rows(client, settings, shelves_pin, mutation):
    first = page([item(n) for n in range(200)], total=201)
    second = page([item(200)], total=201, offset=200)
    if mutation == "token":
        second["meta"]["snapshot"] = "b" * 24
    elif mutation == "date":
        second["meta"]["taken_at"] = "2026-10-26T00:00:00+00:00"
    elif mutation == "coverage":
        second["meta"]["coverage"] = "unknown"
    elif mutation == "total":
        second.update(total=202, distinct_total=202, items=[item(200), item(201)])
    else:
        second["items"] = [item(0)]
    with upstream(settings, first, second):
        r = client.get("/api/library/shelves", {**shelves_pin, "snapshot": TOKEN})
        assert r.status_code == (409 if mutation == "token" else 502)
        assert r.json().get("code") == ("library_check_changed" if mutation == "token" else None)
        assert "shelves" not in r.json()


def test_shelves_truncation_does_not_claim_a_partial_alphabetical_prefix_is_recorded_order(
    client, settings, shelves_pin, monkeypatch
):
    from librarium import library_shelves

    monkeypatch.setattr(library_shelves, "MAX_INDEX_WORKS", 200)
    monkeypatch.setattr(library_shelves, "MAX_PAGES", 1)
    with upstream(settings, page([item(n) for n in range(200)], total=201)) as calls:
        d = client.get("/api/library/shelves", shelves_pin).json()
        assert d["truncated"] is True and d["shelves"] == []
        assert d["total"] == 201 and len(calls) == 1


def test_shelves_mismatch_attaches_no_library_evidence(client, settings, shelves_pin):
    with upstream(settings, response(version="2026.10.25.1")):
        d = client.get("/api/library/shelves", shelves_pin).json()
        assert d["status"] == "version_mismatch" and d["shelves"] == []


def test_loading_check_defers_series_reads_until_the_token_is_stable(client, settings, shelves_pin):
    with upstream(settings, page([item(n) for n in range(200)], total=1000, loading=True)) as calls:
        result = client.get("/api/library/shelves", shelves_pin)
        assert result.status_code == 200
        data = result.json()
        assert data["status"] == "ready" and data["loading"] is True
        assert data["shelves"] == [] and data["works"] == []
        assert len(calls) == 1


def large_source(settings, monkeypatch, shelves_pin, total=801):
    from librarium import library

    # URL loading must not bind another consumer to this fixture's temporary fetch.
    importlib.import_module("librarium.library_evidence")
    calls = []
    settings.LIBRARIUM_LIBRARY_URL = "http://lf.invalid"

    def fetch(params, deadline=None):
        calls.append((dict(params), threading.current_thread().name, deadline))
        start = params["offset"]
        return page(
            [item(n) for n in range(start, min(start + 200, total))], total=total, offset=start
        )

    monkeypatch.setattr(library, "fetch", fetch)
    return calls, fetch


def await_shelves(client, pin):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        result = client.get("/api/library/shelves", pin)
        if result.status_code != 200 or result.json()["status"] != "preparing":
            return result
        time.sleep(0.01)
    pytest.fail("Background shelves did not finish")


def test_large_index_is_nonblocking_single_flight_and_reused_across_pages(
    client, settings, shelves_pin, monkeypatch
):
    from librarium import library

    calls, fetch = large_source(settings, monkeypatch, shelves_pin)
    release, started = threading.Event(), threading.Event()

    def blocked(params, deadline=None):
        if params["offset"]:
            started.set()
            assert release.wait(3)
        return fetch(params, deadline)

    monkeypatch.setattr(library, "fetch", blocked)
    try:
        before = time.monotonic()
        result = client.get("/api/library/shelves", shelves_pin)
        assert result.status_code == 200
        data = result.json()
        assert data["status"] == "preparing" and not data["loading"]
        assert data["shelves"] == [] and data["works"] == []
        assert time.monotonic() - before < 0.5
        assert started.wait(1)
        assert client.get("/api/library/shelves", shelves_pin).json()["status"] == "preparing"
    finally:
        release.set()
    data = await_shelves(client, shelves_pin).json()
    assert data["series_scope"] == "matching" and data["series_total"] == 3
    assert data["page_size"] == 4
    assert all(s["total"] > 0 for s in data["shelves"])
    assert data["unlinked_total"] == 792
    # Entire no-series membership is grouped, not an incomplete LF tail.
    assert data["shelves"][-1]["works"][0]["id"] == "w_fixture_8"
    assert data["shelves"][-1]["total"] == 1
    assert data["shelves"][0]["catalogue_total"] == 8
    assert [p["offset"] for p, _, _ in calls if p["offset"]].count(200) == 1
    client.get("/api/library/shelves", {**shelves_pin, "page": 2})
    assert len([p for p, _, _ in calls if p["offset"]]) == 4
    assert all(name != threading.current_thread().name for p, name, _ in calls if p["offset"])
    assert all(p["snapshot"] == TOKEN for p, _, _ in calls if p["offset"])


@pytest.mark.parametrize("mutation", ["token", "date", "coverage", "total", "duplicate"])
def test_background_index_refuses_mixed_or_duplicate_pages(
    client, settings, shelves_pin, monkeypatch, mutation
):
    from librarium import library

    _, fetch = large_source(settings, monkeypatch, shelves_pin)

    def changed(params, deadline=None):
        result = fetch(params, deadline)
        if params["offset"] == 200:
            if mutation == "token":
                result["meta"]["snapshot"] = "b" * 24
            elif mutation == "date":
                result["meta"]["taken_at"] = "2026-10-26T00:00:00+00:00"
            elif mutation == "coverage":
                result["meta"]["coverage"] = "unknown"
            elif mutation == "total":
                result.update(total=802, distinct_total=802)
            else:
                result["items"][0] = item(0)
        return result

    monkeypatch.setattr(library, "fetch", changed)
    client.get("/api/library/shelves", shelves_pin)
    result = await_shelves(client, shelves_pin)
    assert result.status_code == (409 if mutation == "token" else 502)
    assert result.json().get("code") == ("library_check_changed" if mutation == "token" else None)
    assert "shelves" not in result.json()


def test_index_is_scoped_to_filters_pin_and_check_and_discards_stale_results(
    client, settings, shelves_pin, monkeypatch
):
    from librarium import library

    calls, fetch = large_source(settings, monkeypatch, shelves_pin)
    current_token = TOKEN

    def checked(params, deadline=None):
        return {**fetch(params, deadline), "meta": {**page([])["meta"], "snapshot": current_token}}

    monkeypatch.setattr(library, "fetch", checked)
    client.get("/api/library/shelves", shelves_pin)
    assert await_shelves(client, shelves_pin).status_code == 200
    first_count = len([p for p, _, _ in calls if p["offset"]])
    other = {**shelves_pin, "q": "title", "ownership": "direct"}
    assert client.get("/api/library/shelves", other).json()["status"] == "preparing"
    assert await_shelves(client, other).json()["status"] == "ready"
    assert len([p for p, _, _ in calls if p["offset"]]) == first_count * 2
    current_token = "b" * 24
    assert client.get("/api/library/shelves", shelves_pin).json()["status"] == "preparing"
    assert await_shelves(client, shelves_pin).json()["snapshot"] == current_token
    # LF can re-advertise an earlier check. Its complete, pinned index remains reusable.
    current_token = TOKEN
    count = len([p for p, _, _ in calls if p["offset"]])
    assert client.get("/api/library/shelves", shelves_pin).json()["status"] == "ready"
    assert len([p for p, _, _ in calls if p["offset"]]) == count


def test_large_index_checks_catalogue_again_before_publication(
    client, settings, shelves_pin, monkeypatch
):
    from librarium import library_shelves

    large_source(settings, monkeypatch, shelves_pin)
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    release, started = threading.Event(), threading.Event()
    context = library_shelves.catalogue_context

    def blocked(*args):
        # The coordinator has joined every background GET before revalidating.
        if threading.current_thread().name == "library-match-index":
            started.set()
            assert release.wait(3)
        return context(*args)

    monkeypatch.setattr(library_shelves, "catalogue_context", blocked)
    try:
        client.get("/api/library/shelves", shelves_pin)
        index = next(reversed(library_shelves._indexes.values()))
        assert started.wait(1)
        path.unlink()
    finally:
        release.set()
    assert index.ready.wait(3)
    assert index.error is not None and index.error.status == 409
    assert await_shelves(client, shelves_pin).status_code == 409


def test_empty_series_are_excluded_and_search_series_names_lead(client, settings, shelves_pin):
    # Last Chancers matches fewer works, but its matching name leads search.
    with upstream(settings, response()):
        data = client.get("/api/library/shelves", {**shelves_pin, "q": "Last"}).json()
        assert [s["name"] for s in data["shelves"]] == [
            "Last Chancers",
            "Gaunt's Ghosts",
            "Standalone and collected",
        ]
    with upstream(settings, response([item(8)])):
        assert [
            s["name"] for s in client.get("/api/library/shelves", shelves_pin).json()["shelves"]
        ] == ["Standalone and collected"]


def test_series_ties_ignore_articles_and_leading_punctuation_and_unseries_is_last():
    from librarium.library_shelves import group

    metadata = {
        f"w_fixture_{n}": {
            "title": "Title",
            "sort_title": "Title",
            "first_published": None,
            "series": [{"id": str(n), "name": name, "position": 1}] if name else [],
        }
        for n, name in enumerate(["The Zebra", "“An Ant", "A Bear", "Antlers", None])
    }
    from librarium import library

    params = {"offset": 0, "limit": 200}
    works = library.project(response([item(n) for n in range(5)]), params, 1)["works"]
    shelves, _ = group(works, metadata, {})
    assert [s["name"] for s in shelves] == [
        "“An Ant",
        "Antlers",
        "A Bear",
        "The Zebra",
        "Standalone and collected",
    ]


def test_shared_positions_preview_novel_then_earliest_publication_then_title(
    client, settings, shelves_pin
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        for n, kind, year in [
            (0, "anthology", "1980"),
            (1, "novel", "2001"),
            (2, "novel", "1999"),
            (3, "novel", "1999"),
        ]:
            db.execute(
                "UPDATE work SET type=?,first_published=? WHERE id=?",
                (kind, year, f"w_fixture_{n}"),
            )
            db.execute(
                "UPDATE work_series SET position=1 WHERE work_id=? AND series_id=7",
                (f"w_fixture_{n}",),
            )
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response()):
        shelf = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]
        assert [w["id"] for w in shelf["works"]] == [
            "w_fixture_2",
            "w_fixture_4",
            "w_fixture_5",
            "w_fixture_6",
            "w_fixture_7",
        ]
        lead = shelf["works"][0]
        assert lead["shelf_alternates"] == 3
        assert lead["series"][0]["lead_work_id"] == "w_fixture_2"
        assert shelf["total"] == 8 and shelf["counts"]["saved"] == 8


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"page": 0},
        {"page": 10001},
        {"q": "x" * 201},
        {"q": ["one", "two"]},
        {"ownership": "invented"},
        {"snapshot": "wrong"},
        {"sort": "title"},
        {"group": "other"},
        {"group": ["standalone", "standalone"]},
        {"url": "http://elsewhere.invalid"},
        {"sha256": "wrong"},
    ],
)
def test_bad_shelves_parameters_never_reach_lf(client, settings, shelves_pin, params):
    query = {} if not params else {**shelves_pin, **params}
    with upstream(settings, response()) as calls:
        assert client.get("/api/library/shelves", query).status_code == 400
        assert calls == []


def test_shelves_pin_failure_and_post_never_reach_lf(client, settings, shelves_pin):
    with upstream(settings, response()) as calls:
        result = client.get("/api/library/shelves", {**shelves_pin, "sha256": "f" * 64})
        assert result.status_code == 409
        assert "code" not in result.json()
        assert (
            client.post("/api/library/shelves", {}, content_type="application/json").status_code
            == 405
        )
        assert calls == []


def test_shelves_keep_unknown_pending_and_current_match_counts_distinct(
    client, settings, shelves_pin
):
    d = response(
        [
            item(0),
            item(1, owned=[], ownership="missing"),
            item(
                2,
                owned=[],
                ownership="pending",
                candidates=[{"title": "Candidate", "stage": "inbox", "confidence": "possible"}],
            ),
        ]
    )
    d["meta"]["coverage"] = "complete"
    with upstream(settings, d):
        shelf = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]
        assert shelf["counts"] == {
            "saved": 0,
            "direct": 1,
            "contained": 0,
            "pending": 1,
            "missing": 1,
            "unknown": 0,
        }
    d = copy.deepcopy(d)
    d["meta"]["coverage"] = "partial"
    with upstream(settings, d):
        counts = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]["counts"]
        assert counts["unknown"] == 1 and counts["missing"] == 0 and counts["saved"] == 1


@pytest.mark.parametrize("changed", ["coverage", "total"])
def test_cached_index_rejects_inconsistent_metadata_under_the_same_token(
    client, settings, shelves_pin, monkeypatch, changed
):
    from librarium import library

    _, fetch = large_source(settings, monkeypatch, shelves_pin)
    client.get("/api/library/shelves", shelves_pin)
    assert await_shelves(client, shelves_pin).json()["status"] == "ready"

    def inconsistent(params, deadline=None):
        value = fetch(params, deadline)
        if changed == "coverage":
            value["meta"]["coverage"] = "unknown"
        else:
            value.update(total=802, distinct_total=802)
        return value

    monkeypatch.setattr(library, "fetch", inconsistent)
    assert client.get("/api/library/shelves", shelves_pin).status_code == 502


def test_full_catalogue_details_identify_shared_position_non_leads(client, settings, shelves_pin):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "UPDATE work_series SET position=1 WHERE series_id=7 AND work_id IN ('w_fixture_0','w_fixture_1')"
        )
        db.execute("UPDATE work SET type='anthology',first_published='1980' WHERE id='w_fixture_0'")
        db.execute("UPDATE work SET first_published='2000' WHERE id='w_fixture_1'")
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = client.get("/api/catalogue/works/w_fixture_0", shelves_pin)
    assert result.status_code == 200
    assert result.json()["series"][0]["lead_work_id"] == "w_fixture_1"
    assert result.json()["series"][0]["position_total"] == 2


def test_failed_background_read_is_retryable_and_all_gets_retain_the_read_deadline(
    client, settings, shelves_pin, monkeypatch
):
    from librarium import library

    calls, fetch = large_source(settings, monkeypatch, shelves_pin)
    failing = True

    def sometimes(params, deadline=None):
        assert deadline is not None and 0 < deadline - time.monotonic() <= 3
        if params["offset"] and failing:
            raise library.LibraryError("The library service is unavailable. Try again shortly.")
        return fetch(params, deadline)

    monkeypatch.setattr(library, "fetch", sometimes)
    client.get("/api/library/shelves", shelves_pin)
    assert await_shelves(client, shelves_pin).status_code == 502
    failing = False
    client.get("/api/library/shelves", shelves_pin)
    result = await_shelves(client, shelves_pin)
    assert result.status_code == 200 and result.json()["status"] == "ready"
    assert len([p for p, _, _ in calls if p["offset"]]) == 4


def test_preparation_is_bounded_when_another_filter_arrives_and_old_checks_are_in_flight(
    client, settings, shelves_pin, monkeypatch
):
    from librarium import library

    calls, fetch = large_source(settings, monkeypatch, shelves_pin)
    release, started = threading.Event(), threading.Event()
    current = TOKEN

    def blocked(params, deadline=None):
        result = fetch(params, deadline)
        result["meta"]["snapshot"] = params["snapshot"] or current
        if params["offset"] and params["snapshot"] == TOKEN:
            started.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(library, "fetch", blocked)
    try:
        client.get("/api/library/shelves", shelves_pin)
        assert started.wait(1)
        assert (
            client.get("/api/library/shelves", {**shelves_pin, "q": "other"}).json()["status"]
            == "preparing"
        )
        current = "b" * 24
        assert client.get("/api/library/shelves", shelves_pin).json()["status"] == "preparing"
        # No second coordinator or queued per-filter network run was started.
        assert len([p for p, _, _ in calls if p["offset"]]) <= 3
    finally:
        release.set()
    result = await_shelves(client, shelves_pin)
    assert result.status_code == 200 and result.json()["snapshot"] == current


def test_changed_catalogue_pin_has_its_own_index(client, settings, shelves_pin, monkeypatch):
    calls, _ = large_source(settings, monkeypatch, shelves_pin)
    client.get("/api/library/shelves", shelves_pin)
    assert await_shelves(client, shelves_pin).json()["status"] == "ready"
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE series SET name='Changed series' WHERE id=7")
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    client.get("/api/library/shelves", shelves_pin)
    result = await_shelves(client, shelves_pin)
    assert result.json()["shelves"][0]["name"] == "Changed series"
    assert len([p for p, _, _ in calls if p["offset"]]) == 8


def test_umbrella_and_unnumbered_series_join_the_complete_closing_shelf(
    client, settings, shelves_pin
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM work_series")
        db.execute("DELETE FROM work")
        db.execute("DELETE FROM series")
        db.executemany(
            "INSERT INTO series VALUES (?,?)",
            [(7, "Warhammer"), (8, "A real series"), (9, "Unnumbered only"), (10, "Realm")],
        )
        # Real-shaped umbrella: 96 unpositioned catalogue works, not five empty folios.
        for n in range(96):
            db.execute(
                "INSERT INTO work(id,title,type,setting) VALUES (?,?,'anthology','Warhammer')",
                (f"w_fixture_{n}", f"Collected {95 - n:02}"),
            )
            db.execute("INSERT INTO work_series VALUES (?,7,NULL)", (f"w_fixture_{n}",))
        for n, title in enumerate(
            [
                "Numbered novel",
                "Unpositioned story",
                "A standalone",
                "Unnumbered only",
                "Realm collected",
            ],
            start=96,
        ):
            db.execute(
                "INSERT INTO work(id,title,type,setting) VALUES (?,?,'novel','Realm')",
                (f"w_fixture_{n}", title),
            )
        db.executemany(
            "INSERT INTO work_series VALUES (?,?,?)",
            [
                ("w_fixture_95", 8, 2),
                ("w_fixture_96", 8, 1),
                ("w_fixture_97", 8, None),
                ("w_fixture_99", 9, None),
                ("w_fixture_100", 10, 1),
            ],
        )
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(n) for n in [0, 1, 95, 96, 97, 98, 99, 100]])):
        data = client.get("/api/library/shelves", shelves_pin).json()
    assert data["series_total"] == 2
    real, closing_shelf = data["shelves"]
    assert real["name"] == "A real series" and real["catalogue_total"] == real["total"] == 3
    assert [w["id"] for w in real["works"]] == ["w_fixture_96", "w_fixture_95", "w_fixture_97"]
    assert real["position_counts"] == {"numbered": 2, "zero": 0, "unpositioned": 1}
    assert closing_shelf["id"] is None and closing_shelf["name"] == "Standalone and collected"
    assert closing_shelf["catalogue_total"] == 98 and closing_shelf["total"] == 5
    assert [w["id"] for w in closing_shelf["works"]] == [
        "w_fixture_98",
        "w_fixture_1",
        "w_fixture_0",
        "w_fixture_100",
        "w_fixture_99",
    ]
    assert all(not w["series"] for w in closing_shelf["works"])


@pytest.mark.parametrize(
    "name",
    [
        "Warhammer",
        "Warhammer 40,000",
        "Warhammer Fantasy",
        "Warhammer Age of Sigmar",
        "Warhammer Horror",
    ],
)
def test_named_umbrella_is_excluded_even_with_a_numbered_membership(
    client, settings, shelves_pin, name
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE series SET name=? WHERE id=7", (name,))
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(1)])):
        shelves = client.get("/api/library/shelves", shelves_pin).json()["shelves"]
    assert len(shelves) == 1 and shelves[0]["name"] == "Standalone and collected"
    detail = client.get("/api/catalogue/works/w_fixture_1", shelves_pin).json()
    assert detail["series"][0]["shelf_eligible"] is False


@pytest.mark.parametrize(
    "name",
    [
        "The Horus Heresy - Black Library recommended reading order",
        "The Horus Heresy - READING ORDER",
    ],
)
def test_reading_lists_do_not_duplicate_series_shelves_or_hide_catalogue_works(
    client, settings, shelves_pin, name
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO series VALUES (9,?)", (name,))
        db.executemany(
            "INSERT INTO work_series VALUES (?,9,?)",
            [("w_fixture_0", 1), ("w_fixture_8", 2)],
        )
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(0), item(8)])):
        data = client.get("/api/library/shelves", shelves_pin).json()
    assert data["total"] == 2
    assert [s["name"] for s in data["shelves"]] == [
        "Gaunt's Ghosts",
        "Last Chancers",
        "Standalone and collected",
    ]
    assert data["shelves"][0]["works"][0]["id"] == "w_fixture_0"
    assert data["shelves"][-1]["works"][0]["id"] == "w_fixture_8"
    assert data["shelves"][-1]["catalogue_total"] == 1
    detail = client.get("/api/catalogue/works/w_fixture_0", shelves_pin).json()
    assert next(s for s in detail["series"] if s["id"] == "9")["shelf_eligible"] is False
    # Reading lists remain browsable as catalogue groups, including All N.
    catalogue = client.get("/api/catalogue/works", {**shelves_pin, "series": "9"}).json()
    assert catalogue["total"] == 2
    assert [w["id"] for w in catalogue["works"]] == ["w_fixture_0", "w_fixture_8"]


def test_shelf_representative_retains_the_unmatched_canonical_catalogue_lead(
    client, settings, shelves_pin
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "UPDATE work_series SET position=1 WHERE series_id=7 AND work_id IN ('w_fixture_0','w_fixture_1')"
        )
        db.execute("UPDATE work SET first_published='2006-04-01' WHERE id='w_fixture_0'")
        db.execute("UPDATE work SET first_published='2006' WHERE id='w_fixture_1'")
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(0)])):
        shelf = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]
    representative = shelf["works"][0]
    assert representative["id"] == "w_fixture_0" and representative["shelf_alternates"] == 0
    detail = client.get("/api/catalogue/works/w_fixture_0", shelves_pin).json()
    for context in [representative, detail]:
        membership = next(s for s in context["series"] if s["id"] == "7")
        assert membership["lead_work_id"] == "w_fixture_0"
        assert membership["position_total"] == 2


def test_shelf_credits_use_deduplicated_canonical_author_roles_over_matched_works(
    client, settings, shelves_pin
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany(
            "INSERT INTO author VALUES (?,?,NULL)",
            [(1, "Dan Abnett"), (2, "Dan Abnett"), (3, "An Editor"), (4, "A Contributor")],
        )
        db.executemany(
            "INSERT INTO work_author VALUES (?,?,?)",
            [
                ("w_fixture_0", 1, "author"),
                ("w_fixture_0", 2, "author"),
                ("w_fixture_0", 3, "editor"),
                ("w_fixture_1", 1, "author"),
                ("w_fixture_2", 4, "author"),
            ],
        )
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(n) for n in range(4)])):
        shelf = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]
    assert shelf["credit"]["names"] == ["Dan Abnett"]
    assert shelf["works"][0]["authors"] == []  # Missing canonical credits never fall back to LF.
    credited = next(w for w in shelf["works"] if w["id"] == "w_fixture_0")
    assert credited["authors"] == ["Dan Abnett"]


@pytest.mark.parametrize(
    "credits, expected",
    [
        ([["Zed"], ["Zed"], ["Amy"], []], ["Zed"]),
        ([["Zed"], ["Amy"], ["Bea"], ["Cal"]], ["Zed", "Amy"]),
        ([["Zed", "Amy"], ["Bea"], ["Cal"], ["Dee"], [], []], []),
        ([["Zed"], ["Amy"], ["Bea"], ["Cal"], ["Dee"], []], []),
    ],
)
def test_shelf_credit_thresholds_count_works_once_and_do_not_alphabetise(credits, expected):
    from librarium import library
    from librarium.library_shelves import group

    works = library.project(
        response([item(n) for n in range(len(credits))]), {"limit": 200, "offset": 0}, 1
    )["works"]
    metadata = {
        w["id"]: {
            "title": w["title"],
            "sort_title": w["title"],
            "first_published": None,
            "series": [],
            "authors": names,
        }
        for w, names in zip(works, credits, strict=True)
    }
    shelves, _ = group(works, metadata, {})
    assert shelves[0]["credit"]["names"] == expected


def test_zero_and_unpositioned_entries_are_individual_after_numbered_positions(
    client, settings, shelves_pin
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work_series SET position=0 WHERE work_id='w_fixture_0'")
        db.execute("UPDATE work_series SET position=NULL WHERE work_id='w_fixture_4'")
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(n) for n in range(5)])):
        shelf = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]
    assert [w["id"] for w in shelf["works"]] == [
        "w_fixture_3",
        "w_fixture_0",
        "w_fixture_1",
        "w_fixture_2",
        "w_fixture_4",
    ]
    assert all(w["shelf_alternates"] == 0 for w in shelf["works"])


def test_standalone_listing_includes_every_title_and_pages_with_the_current_filters(
    client, settings, shelves_pin
):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        for n in range(9, 38):
            db.execute(
                "INSERT INTO work(id,title,type) VALUES (?,?,'novel')",
                (f"w_fixture_{n}", f"Alone {n:02}"),
            )
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response([item(n) for n in range(38)])) as calls:
        query = {**shelves_pin, "group": "standalone", "q": "Alone", "ownership": "direct"}
        first = client.get("/api/library/shelves", query)
        assert first.status_code == 200
        data = first.json()
        assert data["total"] == 30 and data["page_size"] == 24
        assert len(data["works"]) == 24 and "shelves" not in data
        assert data["works"][0]["id"] == "w_fixture_8"
        second = client.get("/api/library/shelves", {**query, "page": 2}).json()
        assert len(second["works"]) == 6
        assert len({w["id"] for w in data["works"] + second["works"]}) == 30
        assert all("q=Alone" in url and "ownership=direct" in url for _, url, _ in calls)


def test_preview_uses_known_publication_date_before_year_only(client, settings, shelves_pin):
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work_series SET position=1 WHERE series_id=7")
        db.execute("UPDATE work SET first_published='2006'")
        db.execute("UPDATE work SET first_published='2006-04-01' WHERE id='w_fixture_1'")
    shelves_pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with upstream(settings, response()):
        shelf = client.get("/api/library/shelves", shelves_pin).json()["shelves"][0]
    assert shelf["works"][0]["id"] == "w_fixture_1"


@pytest.mark.parametrize("failure", ["configuration", "unexpected"])
@pytest.mark.parametrize("completion", ["before_response", "after_response"])
def test_unexpected_background_failure_is_recorded_without_a_thread_exception(
    client, settings, shelves_pin, monkeypatch, failure, completion
):
    from django.core.exceptions import ImproperlyConfigured
    from librarium import library, library_shelves

    _, fetch = large_source(settings, monkeypatch, shelves_pin)
    release, started = threading.Event(), threading.Event()
    match_index = library_shelves.match_index

    def broken(params, deadline=None):
        if params["offset"]:
            started.set()
            assert release.wait(5)
            raise (ImproperlyConfigured if failure == "configuration" else OSError)(
                "private detail"
            )
        return fetch(params, deadline)

    def scheduled_index(*args):
        index = match_index(*args)
        if completion == "before_response":
            # Model a descheduled request while the background read finishes.
            assert index.ready.wait(5)
        return index

    monkeypatch.setattr(library_shelves, "match_index", scheduled_index)
    monkeypatch.setattr(library, "fetch", broken)
    if completion == "before_response":
        release.set()
    try:
        result = client.get("/api/library/shelves", shelves_pin)
        index = next(reversed(library_shelves._indexes.values()))
        assert started.wait(5)
        if completion == "after_response":
            assert result.status_code == 200
            assert result.json()["status"] == "preparing"
            assert not index.ready.is_set()
        else:
            assert result.status_code == 502
            assert "private detail" not in result.content.decode()
    finally:
        release.set()
        # Drain the coordinator before monkeypatches or settings are restored.
        assert next(reversed(library_shelves._indexes.values())).ready.wait(5)
    assert index.error is not None
    result = client.get("/api/library/shelves", shelves_pin)
    assert result.status_code == 502
    assert "private detail" not in result.content.decode()
