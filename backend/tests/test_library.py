import copy
import json
import json.scanner
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

VERSION = "2026.10.24.2"
TOKEN = "a" * 24


def payload():
    return {
        "items": [
            {
                "work_id": "w_fixture",
                "title": "Fixture: The Glass Meridian",
                "type": "novel",
                "authors": ["Fixture Author"],
                "series": [{"series_id": 7, "name": "Fixture Archive", "position": 2}],
                "owned": [
                    {
                        "calibre_id": 41,
                        "title": "Fixture Calibre title",
                        "url": "/book?calibre=41",
                        "last_known": True,
                    }
                ],
                "contained_in": [],
                "candidates": [],
                "ownership": "owned",
                "ownership_current": False,
                "cover_url": "/api/catalogue/cover?work=w_fixture",
                "private_path": "/books/do-not-forward.epub",
            }
        ],
        "total": 1,
        "distinct_total": 1,
        "offset": 0,
        "limit": 24,
        "facets": {"authors": ["Fixture Author"]},
        "meta": {
            "catalogue_version": VERSION,
            "taken_at": "2026-10-25T02:21:21+00:00",
            "coverage": "partial",
            "problem": "internal diagnostic not for forwarding",
            "snapshot": TOKEN,
            "loading": False,
        },
    }


@contextmanager
def upstream(settings, body=None, status=200, headers=None, drip=False):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path, dict(self.headers)))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            raw = body if isinstance(body, bytes) else json.dumps(body or payload()).encode()
            try:
                if drip:
                    for _ in range(60):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.1)
                else:
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


def test_library_not_configured_and_session_discovery(client, settings):
    settings.LIBRARIUM_LIBRARY_URL = ""
    assert client.get("/api/library").json() == {"status": "not_configured"}
    assert client.get("/api/session").json()["library"] is False


def test_library_uses_one_fixed_get_and_exposes_selected_fields_only(client, settings):
    with upstream(settings) as calls:
        r = client.get(
            "/api/library",
            {"q": "Glass & Meridian", "ownership": "owned"},
            HTTP_COOKIE="session=never-forward",
            HTTP_AUTHORIZATION="Bearer never-forward",
        )
        assert r.status_code == 200
        d = r.json()
        assert d["source"] == "library_finish"
        assert d["coverage"] == "partial" and d["checked_at"] == "2026-10-25T02:21:21+00:00"
        assert d["snapshot"] == TOKEN and d["catalogue_version"] == VERSION
        assert d["works"][0]["state"] == "direct"
        assert d["works"][0]["copies"] == [
            {"calibre_id": 41, "title": "Fixture Calibre title", "last_known": True}
        ]
        assert d["works"][0]["current"] is False
        assert (
            "private_path" not in r.content.decode()
            and "internal diagnostic" not in r.content.decode()
        )
        assert "cover_url" not in r.content.decode() and "/book?" not in r.content.decode()
        assert r["Cache-Control"] == "no-store"
        assert client.get("/api/session").json()["library"] is True
        assert len(calls) == 1
        method, path, headers = calls[0]
        assert method == "GET" and path.startswith("/api/library/browse?")
        assert "q=Glass+%26+Meridian" in path and "limit=24" in path and "show_missing=1" in path
        assert not {"Cookie", "Authorization", "X-Forwarded-For"} & headers.keys()


def test_partial_coverage_cannot_turn_unknown_into_missing_or_fresh(client, settings):
    d = payload()
    d["items"][0].update(owned=[], ownership="missing", ownership_current=True)
    with upstream(settings, d):
        item = client.get("/api/library").json()["works"][0]
        assert item["state"] == "unknown" and item["current"] is False


def test_contained_and_pending_stay_distinct_from_direct_matches(client, settings):
    d = payload()
    direct = d["items"][0]
    contained = copy.deepcopy(direct)
    contained.update(
        work_id="w_contained", owned=[], contained_in=direct["owned"], ownership="contained"
    )
    pending = copy.deepcopy(direct)
    pending.update(
        work_id="w_pending",
        owned=[],
        ownership="pending",
        candidates=[
            {
                "title": "Possible fixture",
                "stage": "inbox",
                "confidence": "possible",
                "url": "/book?file=18",
            }
        ],
    )
    d.update(items=[direct, contained, pending], total=3, distinct_total=3)
    with upstream(settings, d):
        rows = client.get("/api/library").json()["works"]
        assert [r["state"] for r in rows] == ["direct", "contained", "pending"]
        assert rows[1]["copies"] == [] and rows[1]["contained_in"][0]["calibre_id"] == 41
        assert rows[2]["candidates"] == [
            {"title": "Possible fixture", "stage": "inbox", "confidence": "possible"}
        ]


@pytest.mark.parametrize(
    "params",
    [
        {"url": "http://unrelated.invalid"},
        {"page": "0"},
        {"page": "10001"},
        {"q": "a" * 201},
        {"q": "a\n"},
        {"ownership": "anything"},
        {"sort": "catalogue"},
        {"snapshot": "bad"},
        {"q": ["one", "two"]},
    ],
)
def test_bad_library_parameters_never_reach_upstream(client, settings, params):
    with upstream(settings) as calls:
        assert client.get("/api/library", params).status_code == 400
        assert calls == []


def test_snapshot_changes_require_explicit_reload(client, settings):
    with upstream(settings, {"error": "The book list changed"}, status=400) as calls:
        r = client.get("/api/library", {"page": 2, "snapshot": TOKEN})
        assert r.status_code == 409
        assert "Reload" in r.json()["error"]
        assert r.json()["code"] == "library_check_changed"
        assert "snapshot=" + TOKEN in calls[0][1]


@pytest.mark.parametrize(
    "mutation", ["token", "version", "identity", "coverage", "bool_id", "row_count"]
)
def test_malformed_upstream_contract_fails_closed(client, settings, mutation):
    d = payload()
    if mutation == "token":
        d["meta"]["snapshot"] = "bad"
    if mutation == "version":
        d["meta"]["catalogue_version"] = "not-a-version"
    if mutation == "identity":
        d["items"][0]["work_id"] = "../writer"
    if mutation == "coverage":
        d["meta"]["coverage"] = "sure"
    if mutation == "bool_id":
        d["items"][0]["owned"][0]["calibre_id"] = True
    if mutation == "row_count":
        d["items"] *= 25
    with upstream(settings, d):
        r = client.get("/api/library")
        assert r.status_code == 502
        assert r.json() == {"error": "The library service returned an unsupported response."}


@pytest.mark.parametrize(
    "body,status,headers",
    [
        (b"not JSON", 200, {}),
        (b"x" * (2 * 1024 * 1024 + 1), 200, {}),
        (b"{}", 302, {"Location": "/api/writer"}),
        (b"private error", 500, {}),
    ],
    ids=[
        "invalid-json",
        "oversized-body",
        "redirect",
        "server-error",
    ],
)
def test_errors_large_bodies_and_redirects_are_bounded_and_not_forwarded(
    client, settings, body, status, headers
):
    with upstream(settings, body, status, headers) as calls:
        assert client.get("/api/library").status_code == 502
        assert len(calls) == 1


def test_slow_drip_cannot_hold_a_web_worker_indefinitely(client, settings):
    with upstream(settings, drip=True):
        started = time.monotonic()
        assert client.get("/api/library").status_code == 502
        assert time.monotonic() - started < 4


def test_loading_is_not_an_empty_library_claim(client, settings):
    d = payload()
    d.update(items=[], total=0, distinct_total=0)
    d["meta"].update(catalogue_version=None, loading=True, coverage="unknown")
    with upstream(settings, d):
        r = client.get("/api/library").json()
        assert r["loading"] is True and r["coverage"] == "unknown" and r["works"] == []


def test_library_has_no_http_writer(client, settings):
    with upstream(settings) as calls:
        assert client.post("/api/library", "{}", content_type="application/json").status_code == 405
        assert calls == []


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "http://user:secret@localhost",
        "http://localhost/api/write",
        "http://localhost?url=elsewhere",
        "http://localhost#fragment",
        "http://localhost:99999",
        "http://localhost\n",
    ],
)
def test_configured_origin_cannot_contain_credentials_paths_or_controls(value):
    from django.core.exceptions import ImproperlyConfigured
    from librarium.library import origin

    with pytest.raises(ImproperlyConfigured):
        origin(value)


def test_complete_dated_check_can_report_no_matched_copy(client, settings):
    d = payload()
    d["meta"]["coverage"] = "complete"
    d["items"][0].update(owned=[], ownership="missing", ownership_current=True)
    with upstream(settings, d):
        result = client.get("/api/library").json()
        assert result["coverage"] == "complete"
        assert result["works"][0]["state"] == "missing"
        assert result["works"][0]["current"] is True


def test_successful_response_cannot_silently_change_the_requested_snapshot(client, settings):
    with upstream(settings):
        result = client.get("/api/library", {"snapshot": "b" * 24})
        assert result.status_code == 409
        assert result.json()["code"] == "library_check_changed"


def test_unpinned_upstream_error_cannot_supply_a_recovery_code(client, settings):
    with upstream(
        settings,
        {"error": "changed", "code": "library_check_changed"},
        status=400,
    ):
        result = client.get("/api/library")
        assert result.status_code == 502
        assert "code" not in result.json()


def test_deeply_nested_or_incomplete_upstream_json_is_an_unsupported_response(client, settings):
    with upstream(settings, b"[" * 2000 + b"0" + b"]" * 2000):
        assert client.get("/api/library").status_code == 502
    d = payload()
    d.update(total=2, distinct_total=2)
    with upstream(settings, d):
        assert client.get("/api/library").status_code == 502


def test_upstream_json_decoder_recursion_uses_the_supported_error_contract(
    client, settings, monkeypatch
):
    decoder = json.JSONDecoder()
    decoder.scan_once = json.scanner.py_make_scanner(decoder)
    monkeypatch.setattr(json, "_default_decoder", decoder)
    with upstream(settings, b"[" * 2000 + b"0" + b"]" * 2000):
        result = client.get("/api/library")
        assert result.status_code == 502
        assert result.json() == {"error": "The library service returned an unsupported response."}
