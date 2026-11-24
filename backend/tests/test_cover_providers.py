"""Provider parity fixtures exercise retained parsing without live calls."""

import pytest
from librarium import cover_providers as p
from librarium.cover_source_fetch import SourceFailure


def test_hardcover_missing_is_not_configured_and_rejected_is_unavailable(monkeypatch):
    monkeypatch.setattr(p, "HC_TOKEN", "")
    with pytest.raises(SourceFailure, match="not_configured"):
        p.src_hardcover("A", "B", "")
    monkeypatch.setattr(p, "HC_TOKEN", "synthetic")
    monkeypatch.setattr(
        p.S, "post", lambda *a, **k: (_ for _ in ()).throw(SourceFailure("unavailable"))
    )
    with pytest.raises(SourceFailure, match="unavailable"):
        p.src_hardcover("A", "B", "")


def test_apple_isbn_then_title_and_hires(monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        return p.Reply(
            b'{"results":[]}'
            if "lookup" in url
            else b'{"results":[{"artworkUrl100":"https://example.org/100x100bb.jpg","trackName":"Novel"}]}'
        )

    monkeypatch.setattr(p, "_get", get)
    out = p.src_apple("Novel", "Author", "9780306406157")
    assert len(calls) == 2 and out[0]["urls"] == ["https://example.org/1600x1600bb.jpg"]
    assert not out[0]["by_isbn"]


@pytest.mark.parametrize("encoded", [False, True])
def test_hardcover_search_json_scalar_and_missing_images(monkeypatch, encoded):
    import json

    results = {
        "hits": [
            {
                "document": {
                    "title": "Novel",
                    "author_names": ["Author"],
                    "image": {"url": "https://assets.hardcover.app/a.jpg"},
                }
            },
            {"document": {"title": "No artwork", "image": None}},
        ]
    }
    monkeypatch.setattr(p, "HC_TOKEN", "synthetic")
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return p.Reply(
            json.dumps(
                {"data": {"search": {"results": json.dumps(results) if encoded else results}}}
            ).encode()
        )

    monkeypatch.setattr(p.S, "post", post)
    result = p.src_hardcover("Novel", "Author", "")
    assert len(result) == 1 and result[0]["urls"] == ["https://assets.hardcover.app/a.jpg"]
    assert calls[0]["headers"] == {"authorization": "Bearer synthetic"}


def test_google_and_openlibrary_fixture_parsing(monkeypatch):
    monkeypatch.setattr(
        p,
        "_get",
        lambda *a, **kw: p.Reply(
            b'{"items":[{"id":"abc","volumeInfo":{"title":"Novel","authors":["Author"],"imageLinks":{}}}],"docs":[{"title":"Novel","cover_i":42,"author_name":["Author"]}]}'
        ),
    )
    assert "frontcover/abc" in p.src_google("Novel", "Author", "")[0]["urls"][0]
    assert "default=false" in p.src_openlibrary("Novel", "Author", "")[0]["urls"][0]


def test_book2_and_non_publication_infobox_are_excluded():
    assert (
        p.lx_infobox(
            '<table><a href="/wiki/File:Book2.jpg" class="image"><img src="/Book2.jpg" /></a><td>Author</td><td>A</td></table>'
        )
        is None
    )
    assert (
        p.lx_infobox(
            '<table><a href="/wiki/File:A.jpg" class="image"><img src="/A.jpg" /></a><td>Faction</td><td>A</td></table>'
        )
        is None
    )


@pytest.fixture
def archive_transport(monkeypatch):
    import threading

    from librarium import cover_source_fetch as transport
    from tests.test_cover_source_fetch import answer

    monkeypatch.setattr(p, "_pace", lambda *a: None)
    monkeypatch.setattr(p, "_lx_cache", {})
    monkeypatch.setattr(p, "_wb_state", {"until": 0.0})
    monkeypatch.setattr(p, "_deadline", threading.local())
    monkeypatch.setattr(transport.socket, "getaddrinfo", lambda *a, **k: answer("8.8.8.8"))
    monkeypatch.setattr(p.time, "sleep", lambda *a: None)
    return transport


def test_lexicanum_search_requests_only_archived_pages_and_images(archive_transport, monkeypatch):
    from tests.test_cover_source_fetch import response

    requests = []

    def request(parts, *a):
        assert parts.hostname == "web.archive.org", "live wiki request"
        requests.append(parts.geturl())
        if "/web/" in parts.path:
            return response(
                raw=b'<table><a href="/wiki/File:Novel.jpg" class="image"><img src="/mediawiki/images/a/Novel.jpg" /></a><td>Author</td><td>Author</td></table>'
            )
        if "fl=original" in parts.query:
            return response(raw=b"https://wh40k.lexicanum.com/wiki/Novel_(Novel)")
        return response(
            raw=b"20260101000000 https://wh40k.lexicanum.com/mediawiki/images/a/Novel.jpg 12345"
        )

    monkeypatch.setattr(archive_transport, "_request", request)
    out = p.src_lexicanum("Novel", "Author")
    assert requests and out
    assert out[0]["src"] == "Lexicanum (archived copy)"
    assert all(url.startswith("https://web.archive.org/web/") for url in out[0]["urls"])


@pytest.mark.parametrize("status,state", [(503, "unavailable"), (429, "rate_limited")])
def test_wayback_http_failures_have_distinct_source_states(
    archive_transport, monkeypatch, status, state
):
    from librarium import cover_source_server as server
    from tests.test_cover_source_fetch import response

    requests = []

    def request(parts, *a):
        assert parts.hostname == "web.archive.org", "live wiki request"
        requests.append(parts.geturl())
        return response(status)

    monkeypatch.setattr(archive_transport, "_request", request)
    result = server.execute(
        {
            "query": {"title": "Novel", "author": "Author", "isbn": ""},
            "sources": ["lexicanum"],
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
    )
    assert result == {"state": state, "candidates": []}
    assert len(requests) == (2 if status == 503 else 1)
    if status == 429:
        assert p._wb_state["until"] > p.time.time()


def test_wayback_failure_is_not_successful_empty(monkeypatch):
    monkeypatch.setattr(p, "_lx_raw", lambda *a, **k: p.Reply(b"", 403))
    monkeypatch.setattr(p.time, "sleep", lambda *a: None)
    monkeypatch.setattr(p, "_wb_state", {"until": 0.0})
    with pytest.raises(SourceFailure, match="unavailable"):
        p._wb("https://web.archive.org/a")


@pytest.mark.parametrize("key", ["", "fixture-google-key"])
def test_google_optional_key_changes_only_google_params(monkeypatch, key):
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", key)
    calls = []
    monkeypatch.setattr(p, "_get", lambda url, **kw: calls.append((url, kw)) or p.Reply(b"{}"))
    p.src_google("Novel", "Author", "")
    expected = {"q": 'intitle:"Novel" inauthor:"Author"', "maxResults": 5}
    if key:
        expected["key"] = key
    assert calls[0][1]["params"] == expected


@pytest.mark.parametrize(
    "doc,segment",
    [
        ({"cover_edition_key": "OL123M"}, "/olid/OL123M"),
        ({"editions": {"docs": [{"key": "/books/OL123M", "cover_i": 72}]}}, "/id/72"),
        ({"isbn": ["invalid", "9780306406157"]}, "/isbn/9780306406157"),
    ],
)
def test_openlibrary_edition_covers_without_work_cover(monkeypatch, doc, segment):
    import json

    calls = []

    def get(url, **kw):
        calls.append(kw["params"])
        return p.Reply(
            json.dumps({"docs": [{"title": "Novel", "author_name": ["Author"], **doc}]}).encode()
        )

    monkeypatch.setattr(p, "_get", get)
    out = p.src_openlibrary("Novel", "Author", "")
    assert len(out) == 1 and segment in out[0]["urls"][0]
    assert out[0]["urls"][0].endswith("-L.jpg?default=false")
    assert "cover_edition_key" in calls[0]["fields"]
    assert calls[0]["title"] == "Novel" and calls[0]["author"] == "Author"


@pytest.mark.parametrize(
    "editions", [[{"cover_i": 9}], "unexpected", {"docs": "unexpected"}, {"docs": [None, 7]}]
)
def test_openlibrary_malformed_editions_keep_other_covers(monkeypatch, editions):
    import json

    body = {
        "docs": [{"title": "Novel", "author_name": ["Author"], "cover_i": 41, "editions": editions}]
    }
    monkeypatch.setattr(p, "_get", lambda url, **kw: p.Reply(json.dumps(body).encode()))
    out = p.src_openlibrary("Novel", "Author", "")
    assert len(out) == 1 and "/id/41" in out[0]["urls"][0]


@pytest.mark.parametrize(
    "title,first",
    [
        ("Gotrek and Felix: Synthetic Novel", "whfb.lexicanum.com"),
        ("Age of Sigmar: Synthetic Novel", "ageofsigmar.lexicanum.com"),
        ("Horus Heresy: Synthetic Novel", "wh40k.lexicanum.com"),
    ],
)
def test_archive_spends_budget_on_likely_wiki_first(monkeypatch, title, first):
    monkeypatch.setattr(p, "_lx_cache", {})
    calls = []

    def wayback(host, title, deadline):
        calls.append(host)
        return [
            (
                title,
                {"caption_links": [], "caption": "", "author": "Author"},
                ["https://web.archive.org/a.jpg"],
            )
        ]

    monkeypatch.setattr(p, "_lx_wayback", wayback)
    assert p.src_lexicanum(title, "Author")
    assert calls == [first]


def test_archive_partial_keeps_original_image_when_thumbnail_times_out(monkeypatch):
    from librarium import cover_source_server as server

    monkeypatch.setattr(p, "_lx_cache", {})
    monkeypatch.setattr(p, "_wb_state", {"until": 0.0})

    def wb(url, **kw):
        params = kw.get("params", {})
        if "/web/" in url:
            return p.Reply(
                b'<table><a href="/wiki/File:Novel.jpg" class="image"><img src="/mediawiki/images/a/Novel.jpg" /></a><td>Author</td><td>Author</td></table>'
            )
        if params.get("fl") == "original":
            return p.Reply(b"https://wh40k.lexicanum.com/wiki/Novel_(Novel)")
        if params.get("matchType") == "prefix":
            raise SourceFailure("timed_out")
        return p.Reply(
            b"20260101000000 https://wh40k.lexicanum.com/mediawiki/images/a/Novel.jpg 12345"
        )

    monkeypatch.setattr(p, "_wb", wb)
    result = server.execute(
        {
            "query": {"title": "Novel", "author": "Author", "isbn": ""},
            "sources": ["lexicanum"],
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
    )
    assert result["state"] == "partial" and len(result["candidates"]) == 1
    assert not p._lx_cache


def test_archive_budget_exhaustion_after_empty_wiki_is_partial(monkeypatch):
    from librarium import cover_source_server as server

    monkeypatch.setattr(p, "_lx_cache", {})
    calls = []

    def wayback(host, title, deadline):
        calls.append(host)
        if len(calls) > 1:
            raise SourceFailure("timed_out")
        return []

    monkeypatch.setattr(p, "_lx_wayback", wayback)
    result = server.execute(
        {
            "query": {"title": "Novel", "author": "Author", "isbn": ""},
            "sources": ["lexicanum"],
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
    )
    assert result == {"state": "partial", "candidates": []}
    assert not p._lx_cache


def test_archive_pacing_refuses_wait_that_would_exhaust_budget(monkeypatch):
    monkeypatch.setattr(p, "_host_next", {"web.archive.org": p.time.time() + 10})
    monkeypatch.setattr(p._deadline, "at", p.time.monotonic() + 0.01, raising=False)
    waits = []
    monkeypatch.setattr(p.time, "sleep", waits.append)
    with pytest.raises(SourceFailure, match="timed_out"):
        p._pace("https://web.archive.org/cdx/search/cdx")
    assert waits == []


def test_archive_retry_does_not_sleep_past_deadline(monkeypatch):
    monkeypatch.setattr(p, "_wb_state", {"until": 0.0})
    monkeypatch.setattr(p._lx_tl, "deadline", p.time.time() + 0.1, raising=False)
    monkeypatch.setattr(p, "_lx_raw", lambda *a, **kw: p.Reply(b"", 503))
    waits = []
    monkeypatch.setattr(p.time, "sleep", waits.append)
    with pytest.raises(SourceFailure, match="timed_out"):
        p._wb("https://web.archive.org/a")
    assert not waits


def test_archive_network_request_is_clamped_to_wiki_deadline(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(p, "_pace", lambda *a: None)
    monkeypatch.setattr(p._lx_tl, "deadline", p.time.time() + 0.25, raising=False)
    monkeypatch.setattr(p._deadline, "at", None, raising=False)
    get = Mock(return_value=p.Reply(b""))
    monkeypatch.setattr(p.S, "get", get)
    p._lx_raw("https://web.archive.org/a", timeout=30)
    assert 0 < get.call_args.kwargs["timeout"] <= 0.25
    assert p._deadline.at is None


def test_archive_backoff_without_checked_wikis_stays_rate_limited(monkeypatch):
    from librarium import cover_source_server as server

    monkeypatch.setattr(p, "_lx_cache", {})
    monkeypatch.setattr(p, "_wb_state", {"until": p.time.time() + 60})
    result = server.execute(
        {
            "query": {"title": "Novel", "author": "Author", "isbn": ""},
            "sources": ["lexicanum"],
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
    )
    assert result == {"state": "rate_limited", "candidates": []}
