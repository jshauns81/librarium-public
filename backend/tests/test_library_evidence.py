import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.http import QueryDict

VERSION = "2026.10.24.2"
TOKEN = "a" * 24
OTHER = "b" * 24
SCHEMA = Path(__file__).parent / "fixtures/blc-schema.sql"


@pytest.fixture
def pin(tmp_path, settings):
    root = tmp_path / "catalogue"
    root.mkdir()
    path = root / f"{VERSION}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (VERSION,))
        db.execute("INSERT INTO work(id, title) VALUES ('w_local', 'Fixture: Local Work')")
        db.execute("INSERT INTO series VALUES (7, 'Fixture Archive')")
        db.execute("INSERT INTO series VALUES (2305843009213693951, 'Fixture Large Archive')")
        db.execute("INSERT INTO work_series VALUES ('w_local', 7, 1)")
    (root / "current").write_text(VERSION)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = False
    return {"version": VERSION, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def item(n, series_id=7, name="Fixture Archive", position=1, **changes):
    value = {
        "work_id": f"w_fixture_{n}",
        "title": f"Fixture title {n}",
        "type": "novel",
        "authors": ["Fixture Author"],
        "series": [{"series_id": series_id, "name": name, "position": position}],
        "owned": [
            {
                "calibre_id": 41,
                "title": "Fixture copy",
                "url": "/book?calibre=41",
                "last_known": True,
            }
        ],
        "contained_in": [],
        "candidates": [],
        "ownership": "owned",
        "ownership_current": True,
        "cover_url": "/api/catalogue/cover?work=w_fixture",
        "private_path": "/books/do-not-forward.epub",
    }
    value.update(changes)
    return value


def page(items, total=None, offset=0, token=TOKEN, version=VERSION, **meta):
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "distinct_total": len(items) if total is None else total,
        "offset": offset,
        "limit": 200,
        "meta": {
            "catalogue_version": version,
            "taken_at": "2026-10-25T02:21:21+00:00",
            "coverage": "partial",
            "problem": "internal diagnostic not for forwarding",
            "snapshot": token,
            "loading": False,
            **meta,
        },
    }


def pages(total, token=TOKEN, start=0, version=VERSION):
    """Return a responder serving a consistent multi-page listing for ``token``."""

    def respond(params):
        offset = int(params.get("offset", ["0"])[0])
        count = max(0, min(200, total - offset))
        return page(
            [item(start + offset + i) for i in range(count)],
            total,
            offset=offset,
            token=token,
            version=version,
        )

    return respond


@contextmanager
def upstream(settings, *responses, delay=0.0):
    """Serve responses in order; each is a dict, bytes, (status, body) or callable(params)."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path, dict(self.headers)))
            params = parse_qs(urlsplit(self.path).query)
            spec = responses[min(len(calls), len(responses)) - 1]
            if callable(spec):
                spec = spec(params)
            status, body = spec if isinstance(spec, tuple) else (200, spec)
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            time.sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)
            except BrokenPipeError, ConnectionResetError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    settings.LIBRARIUM_LIBRARY_URL = f"http://127.0.0.1:{server.server_port}"
    try:
        yield calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def query(pin, **changes):
    value = QueryDict(mutable=True)
    for key, item_value in {"series": "7", **pin, **changes}.items():
        if item_value is None:
            continue
        for one in item_value if isinstance(item_value, list) else [item_value]:
            value.appendlist(key, str(one))
    return value


def evidence(q):
    from librarium.library_evidence import series

    return series(q)


def failure(q):
    from librarium.library import LibraryError

    with pytest.raises(LibraryError) as error:
        evidence(q)
    return error.value


def sent(call):
    return parse_qs(urlsplit(call[1]).query, keep_blank_values=True)


def test_one_fixed_series_read_returns_selected_metadata_only(settings, pin):
    with upstream(settings, page([item(1)])) as calls:
        result = evidence(query(pin))
    assert set(result) == {
        "status",
        "source",
        "series_id",
        "catalogue_version",
        "checked_at",
        "coverage",
        "loading",
        "snapshot",
        "truncated",
        "works",
    }
    assert result["status"] == "ready" and result["series_id"] == "7"
    assert result["catalogue_version"] == VERSION and result["snapshot"] == TOKEN
    assert result["truncated"] is False and result["coverage"] == "partial"
    assert result["works"][0]["copies"] == [
        {"calibre_id": 41, "title": "Fixture copy", "last_known": True}
    ]
    body = json.dumps(result)
    for private in ("private_path", "/book?", "cover_url", "internal diagnostic", "127.0.0.1"):
        assert private not in body
    assert len(calls) == 1
    method, path, headers = calls[0]
    assert method == "GET" and path.startswith("/api/library/browse?")
    assert sent(calls[0]) == {
        "series": ["7"],
        "ownership": ["all"],
        "sort": ["title"],
        "limit": ["200"],
        "offset": ["0"],
    }
    assert not {"Cookie", "Authorization", "X-Forwarded-For"} & headers.keys()


def test_numeric_name_matches_and_non_evidence_rows_are_dropped(settings, pin):
    rows = [
        item(1),
        item(2, series_id=12, name="7"),
        item(3, owned=[], ownership="missing"),
        item(4, owned=[], ownership="unknown", ownership_current=False),
    ]
    with upstream(settings, page(rows)):
        result = evidence(query(pin))
    assert [w["id"] for w in result["works"]] == ["w_fixture_1"]
    assert all(w["state"] in {"direct", "contained", "pending"} for w in result["works"])


def test_large_signed64_series_ids_are_supported_end_to_end(settings, pin):
    big = 2305843009213693951
    with upstream(settings, page([item(1, series_id=big, name="Fixture Large Archive")])) as calls:
        result = evidence(query(pin, series=big))
    assert sent(calls[0])["series"] == [str(big)]
    assert result["series_id"] == str(big) and result["works"][0]["series"][0]["id"] == str(big)


def test_membership_ids_cross_the_wire_as_exact_strings(settings, pin):
    big = 2305843009213693951
    rows = [
        item(1, series_id=big, name="Fixture Large Archive"),
        item(2, series_id=big + 1, name="Fixture Neighbour"),
        item(3, series_id=2**63 - 1, name="Fixture Limit"),
    ]
    with upstream(settings, page(rows)):
        wire = json.dumps(evidence(query(pin, series=big)))
    assert f'"id": "{big}"' in wire and f"{big + 1}" not in wire
    assert [w["id"] for w in json.loads(wire)["works"]] == ["w_fixture_1"]

    from librarium.library import project

    body = json.dumps(project(page(rows), {"limit": 200, "offset": 0}, 1))
    assert [w["series"][0]["id"] for w in json.loads(body)["works"]] == [
        str(big),
        str(big + 1),
        str(2**63 - 1),
    ]


def test_version_mismatch_never_attaches_works(settings, pin):
    with upstream(settings, pages(450, version="2026.10.23.1")) as calls:
        result = evidence(query(pin))
    assert result["status"] == "version_mismatch"
    assert result["catalogue_version"] == "2026.10.23.1"
    assert result["works"] == [] and len(calls) == 1


def test_loading_without_a_catalogue_is_not_an_empty_series(settings, pin):
    d = page([], version=None, loading=True, coverage="unknown")
    with upstream(settings, d):
        result = evidence(query(pin))
    assert result["status"] == "loading" and result["works"] == []
    assert result["coverage"] == "unknown" and result["loading"] is True


def test_loading_with_a_matching_catalogue_is_partial_not_complete(settings, pin):
    with upstream(settings, page([item(1)], loading=True, coverage="complete")):
        result = evidence(query(pin))
    assert result["status"] == "ready" and result["coverage"] == "partial"
    assert result["works"][0]["current"] is False


def test_current_contained_pending_and_positions_keep_existing_semantics(settings, pin):
    contained = item(
        2,
        position=2.5,
        owned=[],
        ownership="contained",
        contained_in=[
            {"calibre_id": 9, "title": "Fixture omnibus", "url": "/x", "last_known": False}
        ],
    )
    pending = item(
        3,
        position=None,
        owned=[],
        ownership="pending",
        candidates=[{"title": "Incoming", "stage": "inbox", "confidence": "possible", "url": "/y"}],
    )
    with upstream(settings, page([item(1), contained, pending])):
        partial = evidence(query(pin))
    assert [w["state"] for w in partial["works"]] == ["direct", "contained", "pending"]
    assert [w["current"] for w in partial["works"]] == [False, False, False]
    assert partial["works"][1]["series"][0]["position"] == 2.5
    assert partial["works"][2]["series"][0]["position"] is None
    assert partial["works"][1]["contained_in"][0]["last_known"] is True
    assert partial["works"][2]["candidates"] == [
        {"title": "Incoming", "stage": "inbox", "confidence": "possible"}
    ]
    with upstream(settings, page([item(1)], coverage="complete")):
        complete = evidence(query(pin))
    assert complete["coverage"] == "complete" and complete["works"][0]["current"] is True


def test_multi_page_reads_keep_the_first_token(settings, pin):
    with upstream(settings, pages(450)) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3 and result["truncated"] is False
    assert len(result["works"]) == 450
    assert [sent(c)["offset"] for c in calls] == [["0"], ["200"], ["400"]]
    assert "snapshot" not in sent(calls[0])
    assert [sent(c)["snapshot"] for c in calls[1:]] == [[TOKEN], [TOKEN]]


def test_scans_past_the_request_cap_are_explicitly_truncated(settings, pin):
    with upstream(settings, pages(650)) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3
    assert result["truncated"] is True and len(result["works"]) == 600


def test_a_work_repeated_on_a_later_page_fails_closed(settings, pin):
    def repeat(params):
        result = pages(300)(params)
        if params["offset"] == ["200"]:
            result["items"][0] = item(5)
        return result

    with upstream(settings, repeat) as calls:
        error = failure(query(pin))
    assert error.status == 502 and len(calls) == 2


@pytest.mark.parametrize(
    "later",
    [
        {"total": 401},
        {"version": "2026.10.23.1"},
        {"version": None},
        {"taken_at": "2026-10-25T02:30:00+00:00"},
        {"taken_at": None},
        {"coverage": "complete"},
        {"coverage": "unknown"},
        {"loading": True},
    ],
)
def test_later_pages_cannot_relabel_the_first_pages_evidence(settings, pin, later):
    def respond(params):
        result = pages(300)(params)
        if params["offset"] == ["200"]:
            total = later.get("total", 300)
            result = page(
                [item(200 + i) for i in range(min(200, total - 200))],
                total,
                offset=200,
                version=later.get("version", VERSION),
                **{k: v for k, v in later.items() if k not in {"total", "version"}},
            )
        return result

    with upstream(settings, respond) as calls:
        error = failure(query(pin))
    assert error.status == 502 and len(calls) == 2
    assert "private" not in str(error) and "127.0.0.1" not in str(error)


def test_a_restart_forgets_the_abandoned_attempts_works_and_metadata(settings, pin):
    with upstream(
        settings,
        pages(300),
        (400, {"error": "changed"}),
        lambda params: page([item(i) for i in range(200)], 300, token=OTHER, coverage="complete"),
    ) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3 and result["snapshot"] == OTHER
    assert result["coverage"] == "complete" and result["truncated"] is True
    assert [w["id"] for w in result["works"]] == [f"w_fixture_{i}" for i in range(200)]


def test_changed_snapshot_restarts_once_without_combining_tokens(settings, pin):
    with upstream(
        settings, pages(300), (400, {"error": "changed"}), pages(300, token=OTHER, start=1000)
    ) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3
    assert "snapshot" not in sent(calls[2]) and sent(calls[2])["offset"] == ["0"]
    assert result["snapshot"] == OTHER and result["truncated"] is True
    assert len(result["works"]) == 200
    assert all(int(w["id"].rsplit("_", 1)[1]) >= 1000 for w in result["works"])


def test_a_silently_changed_token_also_restarts(settings, pin):
    with upstream(settings, pages(300), pages(300, token=OTHER), pages(300, token=OTHER)) as calls:
        result = evidence(query(pin))
    assert len(calls) == 3 and result["snapshot"] == OTHER and result["truncated"] is True


def test_a_change_with_no_request_budget_left_is_a_conflict(settings, pin):
    with upstream(settings, pages(450), pages(450), (400, {"error": "changed"})) as calls:
        error = failure(query(pin))
    assert error.status == 409 and len(calls) == 3


def test_a_second_change_after_the_restart_is_a_conflict(settings, pin, monkeypatch):
    from librarium import library_evidence

    monkeypatch.setattr(library_evidence, "MAX_REQUESTS", 6)
    changed = (400, {"error": "changed"})
    with upstream(settings, pages(450), changed, pages(450, token=OTHER), changed) as calls:
        error = failure(query(pin))
    assert error.status == 409 and len(calls) == 4


@pytest.mark.parametrize("endpoint", ["/api/library/series", "/api/library/works/w_local"])
def test_repeated_check_changes_have_one_classification_on_evidence_routes(
    client, settings, pin, monkeypatch, endpoint
):
    from librarium import library_evidence

    monkeypatch.setattr(library_evidence, "MAX_REQUESTS", 6)
    changed = (400, {"error": "changed"})
    params = {**pin, **({"series": "7"} if endpoint.endswith("series") else {})}
    with upstream(settings, pages(450), changed, pages(450, token=OTHER), changed) as calls:
        result = client.get(endpoint, params)
    assert result.status_code == 409
    assert result.json()["code"] == "library_check_changed"
    assert len(calls) == 4


@pytest.mark.parametrize(
    "second",
    [b"not JSON", (500, b"private error"), b"x" * (2 * 1024 * 1024 + 1)],
    ids=[
        "invalid-json",
        "server-error",
        "oversized-body",
    ],
)
def test_malformed_later_pages_fail_closed_without_partial_results(settings, pin, second):
    with upstream(settings, pages(450), second) as calls:
        error = failure(query(pin))
    assert error.status == 502 and len(calls) == 2
    assert "private" not in str(error) and "127.0.0.1" not in str(error)


def test_works_without_a_matching_catalogue_version_are_unsupported(settings, pin):
    with upstream(settings, page([item(1)], version=None)):
        assert failure(query(pin)).status == 502


def test_all_pages_share_one_deadline(settings, pin):
    with upstream(settings, pages(650), delay=1.2) as calls:
        started = time.monotonic()
        error = failure(query(pin))
        elapsed = time.monotonic() - started
    assert error.status == 502 and elapsed < 3.6 and len(calls) <= 3


@pytest.mark.parametrize(
    "changes",
    [
        {"series": None},
        {"version": None},
        {"sha256": None},
        {"url": "http://unrelated.invalid"},
        {"page": "2"},
        {"series": ["7", "8"]},
        {"series": "+7"},
        {"series": "07"},
        {"series": " 7"},
        {"series": "7_0"},
        {"series": "0"},
        {"series": "-1"},
        {"series": "1e3"},
        {"series": str(2**63)},
        {"series": "9" * 40},
        {"version": "2026.13.40.1"},
        {"sha256": "A" * 64},
    ],
)
def test_bad_parameters_never_reach_upstream(settings, pin, changes):
    with upstream(settings, page([item(1)])) as calls:
        assert failure(query(pin, **changes)).status == 400
    assert calls == []


def test_unconfigured_library_is_explicit_after_validation(settings, pin):
    settings.LIBRARIUM_LIBRARY_URL = ""
    assert evidence(query(pin)) == {"status": "not_configured"}
    assert failure(query(pin, series="0")).status == 400


def test_wrong_pin_fixture_catalogue_and_unknown_series_never_reach_upstream(settings, pin):
    with upstream(settings, page([item(1)])) as calls:
        assert failure(query(pin, sha256="0" * 64)).status == 409
        assert failure(query(pin, version="2026.10.23.1")).status == 409
        assert failure(query(pin, series="8")).status == 404
        settings.LIBRARIUM_CATALOGUE_FIXTURE = True
        assert failure(query(pin)).status == 409
    assert calls == []
