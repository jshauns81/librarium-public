import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from django.http import QueryDict
from test_library_evidence import OTHER, TOKEN, VERSION, item, page, pages, sent, upstream
from test_library_evidence import pin as series_pin  # noqa: F401

LONG = " ".join(["Fixture"] * 30)  # 239 characters; the 25-word prefix is 199
WIDE = "F" * 201


@pytest.fixture
def pin(series_pin, settings):  # noqa: F811
    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany(
            "INSERT INTO work(id, title) VALUES (?, ?)",
            [
                ("w_long", LONG),
                ("w_wide", WIDE),
                ("w_blank", "   "),
                ("w_control", "Fixture\nTitle"),
            ],
        )
    import hashlib

    return {"version": VERSION, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def query(pin, **changes):
    value = QueryDict(mutable=True)
    for key, item_value in {**pin, **changes}.items():
        if item_value is None:
            continue
        for one in item_value if isinstance(item_value, list) else [item_value]:
            value.appendlist(key, str(one))
    return value


def evidence(q, work_id="w_local"):
    from librarium.library_evidence import work

    return work(q, work_id)


def failure(q, work_id="w_local"):
    from librarium.library import LibraryError

    with pytest.raises(LibraryError) as error:
        evidence(q, work_id)
    return error.value


def wanted(n="local", **changes):
    return item(n, work_id=f"w_{n}", title="Fixture: Local Work", **changes)


def test_a_homonym_is_dropped_and_only_the_exact_work_id_is_attached(settings, pin):
    homonym = item(1, title="Fixture: Local Work")
    with upstream(settings, page([homonym, wanted()])) as calls:
        result = evidence(query(pin))
    assert set(result) == {
        "status",
        "source",
        "work_id",
        "lookup",
        "catalogue_version",
        "checked_at",
        "coverage",
        "loading",
        "snapshot",
        "truncated",
        "works",
    }
    assert result["status"] == "ready" and result["source"] == "library_finish"
    assert result["work_id"] == "w_local"
    assert result["lookup"] == "title_candidates_verified_by_id"
    assert result["snapshot"] == TOKEN and result["truncated"] is False
    assert [w["id"] for w in result["works"]] == ["w_local"]
    assert result["works"][0]["copies"] == [
        {"calibre_id": 41, "title": "Fixture copy", "last_known": True}
    ]
    body = json.dumps(result)
    for private in ("w_fixture_1", "private_path", "/book?", "cover_url", "internal diagnostic"):
        assert private not in body
    assert len(calls) == 1
    method, path, headers = calls[0]
    assert method == "GET" and path.startswith("/api/library/browse?")
    assert sent(calls[0]) == {
        "q": ["Fixture: Local Work"],
        "ownership": ["all"],
        "sort": ["title"],
        "limit": ["200"],
        "offset": ["0"],
    }
    assert not {"Cookie", "Authorization", "X-Forwarded-For"} & headers.keys()


def test_only_homonyms_give_ready_empty_evidence_not_a_missing_claim(settings, pin):
    rows = [item(1, title="Fixture: Local Work"), item(2, title="Fixture: Local Work II")]
    with upstream(settings, page(rows)):
        result = evidence(query(pin))
    assert result["status"] == "ready" and result["works"] == []
    assert result["truncated"] is False
    assert "missing" not in json.dumps(result) and "unknown" not in json.dumps(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"owned": [], "ownership": "missing"},
        {"owned": [], "ownership": "unknown", "ownership_current": False},
    ],
)
def test_the_exact_work_without_positive_evidence_is_not_attached(settings, pin, changes):
    with upstream(settings, page([wanted(**changes)], coverage="complete")):
        result = evidence(query(pin))
    assert result["status"] == "ready" and result["works"] == []


def test_contained_and_pending_evidence_for_the_exact_work_are_kept(settings, pin):
    contained = wanted(
        owned=[],
        ownership="contained",
        contained_in=[
            {"calibre_id": 9, "title": "Fixture omnibus", "url": "/x", "last_known": False}
        ],
    )
    with upstream(settings, page([contained])):
        assert evidence(query(pin))["works"][0]["state"] == "contained"
    pending = wanted(
        owned=[],
        ownership="pending",
        candidates=[{"title": "Incoming", "stage": "inbox", "confidence": "possible"}],
    )
    with upstream(settings, page([pending])):
        assert evidence(query(pin))["works"][0]["state"] == "pending"


def test_the_exact_work_is_found_on_a_later_page_under_the_first_token(settings, pin):
    def respond(params):
        result = pages(450)(params)
        if params["offset"] == ["400"]:
            result["items"][10] = wanted()
        return result

    with upstream(settings, respond) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3 and result["truncated"] is False
    assert [w["id"] for w in result["works"]] == ["w_local"]
    assert "snapshot" not in sent(calls[0])
    assert [sent(c)["snapshot"] for c in calls[1:]] == [[TOKEN], [TOKEN]]
    assert all(sent(c)["q"] == ["Fixture: Local Work"] for c in calls)


def test_a_work_beyond_the_request_cap_is_truncated_not_missing(settings, pin):
    with upstream(settings, pages(650)) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3
    assert result["status"] == "ready" and result["truncated"] is True
    assert result["works"] == []


def test_a_duplicate_on_a_later_page_fails_closed(settings, pin):
    def repeat(params):
        result = pages(300)(params)
        if params["offset"] == ["200"]:
            result["items"][0] = item(5)
        return result

    with upstream(settings, repeat) as calls:
        assert failure(query(pin)).status == 502
    assert len(calls) == 2


def test_a_later_page_cannot_relabel_the_first_pages_coverage(settings, pin):
    def respond(params):
        result = pages(300)(params)
        if params["offset"] == ["200"]:
            result["meta"]["coverage"] = "complete"
        return result

    with upstream(settings, respond) as calls:
        assert failure(query(pin)).status == 502
    assert len(calls) == 2


def test_a_changed_token_restarts_once_and_forgets_the_abandoned_attempt(settings, pin):
    def first(params):
        result = pages(300)(params)
        result["items"][0] = wanted()
        return result

    with upstream(
        settings, first, (400, {"error": "changed"}), pages(300, token=OTHER, start=1000)
    ) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3 and "snapshot" not in sent(calls[2])
    assert result["snapshot"] == OTHER and result["truncated"] is True
    assert result["works"] == []


def test_a_change_with_no_budget_left_is_a_conflict(settings, pin):
    with upstream(settings, pages(450), pages(450), (400, {"error": "changed"})) as calls:
        assert failure(query(pin)).status == 409
    assert len(calls) == 3


@pytest.mark.parametrize(
    "second",
    [b"not JSON", (500, b"private error"), b"x" * (2 * 1024 * 1024 + 1)],
    ids=[
        "invalid-json",
        "server-error",
        "oversized-body",
    ],
)
def test_malformed_or_oversized_pages_fail_closed(settings, pin, second):
    with upstream(settings, pages(450), second) as calls:
        error = failure(query(pin))
    assert error.status == 502 and len(calls) == 2
    assert "private" not in str(error) and "127.0.0.1" not in str(error)


def test_all_pages_share_one_deadline(settings, pin):
    import time

    with upstream(settings, pages(650), delay=1.2) as calls:
        started = time.monotonic()
        assert failure(query(pin)).status == 502
        elapsed = time.monotonic() - started
    assert elapsed < 3.6 and len(calls) <= 3


def test_version_mismatch_and_loading_never_attach_works(settings, pin):
    with upstream(settings, page([wanted()], version="2026.10.23.1")) as calls:
        result = evidence(query(pin))
    assert result["status"] == "version_mismatch" and result["works"] == []
    assert len(calls) == 1
    with upstream(settings, page([], version=None, loading=True, coverage="unknown")):
        result = evidence(query(pin))
    assert result["status"] == "loading" and result["works"] == []


def test_a_long_title_searches_a_bounded_whole_word_prefix(settings, pin):
    with upstream(settings, page([])) as calls:
        result = evidence(query(pin), "w_long")
    q = sent(calls[0])["q"][0]
    assert q == " ".join(["Fixture"] * 25) and len(q) <= 200
    assert LONG.startswith(q) and LONG[len(q)] == " "
    assert result["status"] == "ready" and result["works"] == []


@pytest.mark.parametrize("work_id", ["w_wide", "w_blank", "w_control"])
def test_titles_without_a_usable_bounded_search_never_reach_upstream(settings, pin, work_id):
    with upstream(settings, page([wanted()])) as calls:
        result = evidence(query(pin), work_id)
    assert result == {
        "status": "unsupported",
        "work_id": work_id,
        "lookup": "title_candidates_verified_by_id",
    }
    assert calls == []


@pytest.mark.parametrize(
    ("changes", "work_id"),
    [
        ({"version": None}, "w_local"),
        ({"sha256": None}, "w_local"),
        ({"series": "7"}, "w_local"),
        ({"work_id": "w_local"}, "w_local"),
        ({"q": "Fixture"}, "w_local"),
        ({"url": "http://unrelated.invalid"}, "w_local"),
        ({"version": [VERSION, VERSION]}, "w_local"),
        ({"version": "2026.13.40.1"}, "w_local"),
        ({"sha256": "A" * 64}, "w_local"),
        ({}, "local"),
        ({}, "w_"),
        ({}, "w_lo-cal"),
        ({}, "w_local "),
        ({}, "w_" + "a" * 65),
        ({}, "41"),
        ({}, "w_local/../x"),
    ],
)
def test_bad_parameters_never_reach_upstream(settings, pin, changes, work_id):
    with upstream(settings, page([wanted()])) as calls:
        assert failure(query(pin, **changes), work_id).status == 400
    assert calls == []


def test_unconfigured_library_is_explicit_after_validation(settings, pin):
    settings.LIBRARIUM_LIBRARY_URL = ""
    assert evidence(query(pin)) == {"status": "not_configured"}
    assert failure(query(pin), "bad").status == 400


def test_wrong_pin_fixture_catalogue_and_unknown_work_never_reach_upstream(settings, pin):
    with upstream(settings, page([wanted()])) as calls:
        assert failure(query(pin, sha256="0" * 64)).status == 409
        assert failure(query(pin, version="2026.10.23.1")).status == 409
        assert failure(query(pin), "w_absent").status == 404
        settings.LIBRARIUM_CATALOGUE_FIXTURE = True
        assert failure(query(pin)).status == 409
    assert calls == []


def test_the_catalogue_is_closed_and_unchanged_before_library_finish_is_read(
    settings, pin, monkeypatch
):
    from librarium import catalogue, library_evidence

    path = Path(settings.LIBRARIUM_CATALOGUE_DIR) / f"{VERSION}.sqlite"
    before = path.read_bytes()
    open_snapshots = []
    original_snapshot, original_fetch = catalogue.snapshot, library_evidence.fetch

    def tracked(*args, **kwargs):
        open_snapshots.append(True)
        try:
            with original_snapshot(*args, **kwargs) as value:
                yield value
        finally:
            open_snapshots.pop()

    def fetch(params, deadline):
        assert open_snapshots == []
        assert set(params) <= {"q", "ownership", "sort", "limit", "offset", "snapshot"}
        return original_fetch(params, deadline)

    from contextlib import contextmanager

    monkeypatch.setattr(catalogue, "snapshot", contextmanager(tracked))
    monkeypatch.setattr(library_evidence, "fetch", fetch)
    with upstream(settings, page([wanted()])) as calls:
        assert evidence(query(pin))["works"][0]["id"] == "w_local"
    assert len(calls) == 1 and all(c[0] == "GET" for c in calls)
    assert path.read_bytes() == before
