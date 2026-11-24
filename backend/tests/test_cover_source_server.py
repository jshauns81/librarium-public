"""Source process boundary accepts only its typed nonwriting interface."""

import pytest
from librarium import cover_source_server as server
from librarium.cover_source_protocol import request


@pytest.mark.parametrize(
    "extra", [{"path": "/library"}, {"url": "https://example.org"}, {"token": "secret"}]
)
def test_search_rejects_unknown_capabilities(extra):
    with pytest.raises(ValueError):
        request(
            {
                "query": {"title": "Novel", "author": "A", "isbn": ""},
                "sources": ["apple"],
                "request_id": "00000000-0000-4000-8000-000000000001",
                **extra,
            }
        )


def test_complete_cache_keeps_empty_distinct_from_incomplete(monkeypatch):
    server.CACHE.clear()
    calls = []

    def run(raw, path):
        calls.append(path)
        return b'{"state":"empty","candidates":[]}'

    monkeypatch.setattr(server, "run_child", run)
    value = {
        "query": {"title": "Novel", "author": "A", "isbn": ""},
        "sources": ["apple"],
        "request_id": "00000000-0000-4000-8000-000000000001",
    }
    assert server.search_reply(value, b"{}") == server.search_reply(value, b"{}")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value", [("sources", [{}]), ("request_id", []), ("request_id", None)]
)
def test_malformed_request_values_are_typed_refusals(field, value):
    body = {
        "query": {"title": "Novel", "author": "A", "isbn": ""},
        "sources": ["apple"],
        "request_id": "00000000-0000-4000-8000-000000000001",
    }
    body[field] = value
    with pytest.raises(ValueError):
        request(body)


def test_child_does_not_hold_cache_lock(monkeypatch):
    server.CACHE.clear()

    def run(raw, path):
        assert server.SEARCH_LOCK.acquire(blocking=False), "cache lock held during child"
        server.SEARCH_LOCK.release()
        return b'{"state":"empty","candidates":[]}'

    monkeypatch.setattr(server, "run_child", run)
    server.search_reply(
        {
            "query": {"title": "Lock test", "author": "", "isbn": ""},
            "sources": ["apple"],
            "request_id": "00000000-0000-4000-8000-000000000001",
        },
        b"{}",
    )


def test_hardcover_token_only_reaches_its_own_child(monkeypatch):
    import json
    from types import SimpleNamespace

    monkeypatch.setenv("HARDCOVER_TOKEN", "fixture-key")

    def run(*args, **kwargs):
        assert "HARDCOVER_TOKEN" not in kwargs["env"]
        return SimpleNamespace(stdout=b'{"state":{},"reply":{"state":"empty","candidates":[]}}')

    monkeypatch.setattr(server.subprocess, "run", run)
    server.run_child(
        json.dumps(
            {
                "query": {"title": "Novel", "author": "", "isbn": ""},
                "sources": ["apple"],
                "request_id": "00000000-0000-4000-8000-000000000001",
            }
        ).encode(),
        "/search",
    )


def test_role_rejects_missing_and_wrong_secret_before_work(monkeypatch):
    import http.client
    import threading

    monkeypatch.setenv("LIBRARIUM_COVER_SOURCES_SECRET", "fixture-" * 8)
    monkeypatch.setattr(server, "search_reply", lambda *a: b'{"state":"empty","candidates":[]}')
    instance = server.Server(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=instance.serve_forever)
    thread.start()
    try:
        for token, expected in [("", 403), ("wrong", 403), ("fixture-" * 8, 200)]:
            c = http.client.HTTPConnection(*instance.server_address, timeout=2)
            c.request(
                "POST",
                "/search",
                '{"query":{"title":"Novel","author":"","isbn":""},"sources":["apple"],"request_id":"00000000-0000-4000-8000-000000000001"}',
                {"Content-Type": "application/json", "X-Cover-Control": token},
            )
            r = c.getresponse()
            assert r.status == expected
            r.read()
            c.close()
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join()


def test_control_listener_uses_only_its_control_alias(monkeypatch):
    from unittest.mock import Mock

    resolver = Mock(return_value="192.0.2.1")
    monkeypatch.setattr(server.socket, "gethostbyname", resolver)
    assert server.control_address() == "192.0.2.1"
    resolver.assert_called_once_with("cover-control-listener")


def test_different_providers_can_run_children_concurrently(monkeypatch):
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor

    server.CACHE.clear()
    ready = threading.Barrier(2)

    def run(raw, path):
        ready.wait(timeout=2)
        return b'{"state":"empty","candidates":[]}'

    monkeypatch.setattr(server, "run_child", run)

    def search(source):
        value = {
            "query": {"title": "Parallel test", "author": "", "isbn": ""},
            "sources": [source],
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
        return server.search_reply(value, json.dumps(value).encode())

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(search, ["apple", "google"]))
    assert replies == [b'{"state":"empty","candidates":[]}'] * 2


@pytest.mark.parametrize("source", ["google", "apple", "hardcover", None])
def test_google_key_reaches_only_google_search_child(monkeypatch, source):
    import json
    from types import SimpleNamespace

    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "fixture-key")

    def run(*args, **kwargs):
        assert kwargs["env"].get("GOOGLE_BOOKS_API_KEY") == (
            "fixture-key" if source == "google" else None
        )
        return SimpleNamespace(stdout=b'{"state":{},"reply":{"state":"empty","candidates":[]}}')

    monkeypatch.setattr(server.subprocess, "run", run)
    raw = (
        {
            "query": {"title": "Novel", "author": "", "isbn": ""},
            "sources": [source],
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
        if source
        else {"url": "https://example.org/a.jpg", "source": "paste"}
    )
    server.run_child(json.dumps(raw).encode(), "/search" if source else "/image")


@pytest.mark.parametrize("state", ["results", "partial", "not_configured"])
def test_search_logs_only_closed_operational_fields_including_cache(monkeypatch, capsys, state):
    import json

    server.CACHE.clear()
    value = {
        "query": {"title": "private-query", "author": "private-author", "isbn": ""},
        "sources": ["google"],
        "request_id": "00000000-0000-4000-8000-000000000001",
    }
    reply = {
        "state": state,
        "candidates": [
            {"title": "private-title", "urls": ["https://example.org/private?key=private-key"]}
        ]
        if state in {"results", "partial"}
        else [],
    }
    monkeypatch.setattr(server, "run_child", lambda *a: json.dumps(reply).encode())
    for _ in range(2):
        server.search_reply(value, json.dumps(value).encode())
    logs = capsys.readouterr().err.splitlines()
    assert len(logs) == 2
    for line in logs:
        row = json.loads(line)
        assert set(row) == {"source", "state", "count", "duration_ms"}
        assert row["source"] == "google" and row["state"] == state
        assert row["count"] == len(reply["candidates"]) and row["duration_ms"] >= 0
        assert "private" not in line
