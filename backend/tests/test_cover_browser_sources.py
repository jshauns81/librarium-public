"""Ported LF Goodreads cache/fallback behavior with worker-owned PostgreSQL state."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.utils import timezone
from librarium import cover_browser_sources as provider
from librarium.cover_providers import gr_parse
from librarium.models import SourceBrowserPage

pytestmark = pytest.mark.django_db
BOOK = (
    '<script type="application/ld+json">'
    + json.dumps(
        {
            "@type": "Book",
            "name": "Novel (Series, #1)",
            "image": "https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1/2._SY75_.jpg",
            "author": [{"name": "Example Writer"}],
        }
    )
    + "</script>"
)
URL = "https://www.goodreads.com/book/show/123-Novel"
EMPTY = '<div data-testid="no-book-search-results">No books</div>'


def query(**values):
    return {"title": "Novel", "author": "Example Writer", "isbn": "", **values}


def test_cache_survives_calls_is_query_keyed_expires_and_retry_bypasses(monkeypatch):
    calls = []

    def call(path, value, maximum):
        calls.append(value)
        return {"state": "ok", "html": BOOK, "url": URL}

    monkeypatch.setattr(provider, "browser_call", call)
    for _ in range(2):
        result = provider.goodreads(query())
        assert result["state"] == "results"
        assert result["candidates"][0]["urls"][0].endswith("/2.jpg")
    assert len(calls) == 1 and SourceBrowserPage.objects.count() == 1
    provider.goodreads(query(), retry=True)
    provider.goodreads(query(author="Other Writer"))
    assert len(calls) == 3
    SourceBrowserPage.objects.update(checked_at=timezone.now() - timedelta(hours=7))
    provider.goodreads(query())
    assert len(calls) == 4


def test_valid_empty_is_cached_and_isbn_falls_back_to_title(monkeypatch):
    calls = []

    def call(path, value, maximum):
        calls.append(value["url"])
        return {
            "state": "ok",
            "html": EMPTY if "978" in value["url"] else BOOK,
            "url": value["url"] if "978" in value["url"] else URL,
        }

    monkeypatch.setattr(provider, "browser_call", call)
    assert provider.goodreads(query(isbn="9781234567897"))["state"] == "results"
    assert provider.goodreads(query(isbn="9781234567897"))["state"] == "results"
    assert len(calls) == 2 and not provider.goodreads(query())["candidates"][0]["by_isbn"]
    assert SourceBrowserPage.objects.count() == 2


@pytest.mark.parametrize("state", ["challenged", "unavailable", "busy", "timed_out"])
def test_failures_and_challenge_pages_are_never_cached(monkeypatch, state):
    monkeypatch.setattr(provider, "browser_call", lambda *a: {"state": state})
    assert provider.goodreads(query())["state"] == state
    assert not SourceBrowserPage.objects.exists()
    monkeypatch.setattr(
        provider,
        "browser_call",
        lambda *a: {"state": "ok", "html": "<title>Just a moment...</title>", "url": URL},
    )
    assert provider.goodreads(query())["state"] == "challenged"
    assert not SourceBrowserPage.objects.exists()


def test_cache_rows_are_bounded(monkeypatch):
    monkeypatch.setattr(provider, "CACHE_ROWS", 2)
    monkeypatch.setattr(
        provider, "browser_call", lambda *a: {"state": "ok", "html": EMPTY, "url": URL}
    )
    for title in ("First", "Second", "Third"):
        provider.goodreads(query(title=title))
    assert SourceBrowserPage.objects.count() == 2


def test_live_wiki_export_and_original_cover_keep_browser_provenance(monkeypatch):
    html = '<div id="mw-content-text"><table><tr><td><a href="/wiki/File:Novel.jpg" class="image"><img src="/mediawiki/images/thumb/a/ab/Novel.jpg/200px-Novel.jpg" /></a></td></tr><tr><th>Author</th><td>Example Writer</td></tr></table></div>'
    xml = '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.10/"><page><title>Novel</title><revision><text>book</text></revision></page></mediawiki>'
    monkeypatch.setattr(
        provider,
        "browser_call",
        lambda *a: {
            "state": "ok",
            "html": html,
            "xml": xml,
            "url": "https://wh40k.lexicanum.com/wiki/Novel",
            "cover_url": "https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg",
        },
    )
    result = provider.lexicanum(query())
    assert result["state"] == "results"
    assert result["candidates"][0]["reach_method"] == "server_browser"
    assert result["candidates"][0]["urls"] == [
        "https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg"
    ]


@pytest.mark.parametrize(
    "markup, url",
    [
        (
            '<div class="Book" data-testid="book-item-content"><a href="/book/show/123"><img class="ResponsiveImage" src="https://i.gr-assets.com/2._SX50_.jpg" alt="Novel Book Cover"></a></div><div data-testid="book-item-title"><a href="/book/show/123">Novel</a><span class="ContributorLink__name">Example Writer</span></div>',
            "https://www.goodreads.com/search?q=Novel",
        ),
        (
            '<tr itemscope itemtype="http://schema.org/Book"><img class="bookCover" src="https://i.gr-assets.com/2._SY75_.jpg"><span itemprop=\'name\'>Novel</span><a class="authorName"><span itemprop="name">Example Writer</span></a></tr>',
            "https://www.goodreads.com/search?q=Novel",
        ),
        (BOOK, URL),
    ],
    ids=["next-search", "legacy-table", "jsonld-book"],
)
def test_goodreads_layouts_and_original_resolution(markup, url):
    item = gr_parse(markup, url, True)[0]
    assert item["title"] == "Novel"
    assert item["author"] == "Example Writer"
    assert item["urls"][0].endswith("/2.jpg")
    assert item["by_isbn"] is True


def test_jsonld_placeholder_is_not_a_candidate():
    assert gr_parse(BOOK.replace("/2._SY75_.jpg", "/nophoto.jpg"), URL) == []


def test_adversarial_html_cannot_hold_the_worker_in_a_parser():
    parse = getattr(provider, "parse_page", None)
    assert callable(parse), "browser HTML must be parsed in a bounded fresh child"
    with pytest.raises(ValueError):
        parse(
            "lexicanum",
            "<table>" * 299000,
            "https://wh40k.lexicanum.com/wiki/Novel",
            xml='<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.10/"><page><title>Novel</title><revision><text>book</text></revision></page></mediawiki>',
        )


@pytest.mark.django_db(transaction=True)
def test_cache_migration_reverse_and_reapply_preserve_search_and_selection():
    import uuid

    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from librarium.models import CoverReviewEntry, CoverSearch, PreparedCover

    prior = [("librarium", "0015_cover_search")]
    current = [("librarium", "0017_cover_source_timings")]
    try:
        MigrationExecutor(connection).migrate(prior)
        entry = CoverReviewEntry.objects.create(
            library_uuid="synthetic-library",
            book_uuid="synthetic-book",
            calibre_id=42,
            title="Synthetic Novel",
        )
        HistoricalSearch = (
            MigrationExecutor(connection)
            .loader.project_state(prior)
            .apps.get_model("librarium", "CoverSearch")
        )
        search = HistoricalSearch.objects.create(
            request_key=uuid.uuid4(),
            entry_id=entry.pk,
            actor="reviewer",
            request={},
            binding={"fixture": True},
            query={"title": "Novel"},
            sources=["apple"],
        )
        selection = PreparedCover.objects.create(
            request_key=uuid.uuid4(),
            entry=entry,
            actor="reviewer",
            request={},
            binding={"fixture": True},
            candidate={"id": "saved"},
        )
        for target in (current, prior, current):
            MigrationExecutor(connection).migrate(target)
            assert CoverSearch.objects.values_list("binding", flat=True).get(pk=search.pk) == {
                "fixture": True
            }
            assert PreparedCover.objects.get(pk=selection.pk).candidate == {"id": "saved"}
            if target == current:
                assert CoverSearch.objects.get(pk=search.pk).source_timings == {}
                CoverSearch.objects.filter(pk=search.pk).update(
                    source_timings={"apple": {"duration_ms": 12}}
                )
                assert SourceBrowserPage.objects.count() == 0
                SourceBrowserPage.objects.create(
                    query_key="f" * 64, html=EMPTY, url=URL, checked_at=timezone.now()
                )
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def test_missing_exact_article_uses_wiki_search_and_exports_disambiguated_book(monkeypatch):
    calls = []

    def call(path, value, *args):
        calls.append((path, value["url"]))
        if "Special%3ASearch" in value["url"]:
            return {
                "state": "ok",
                "url": value["url"],
                "html": '<ul class="mw-search-results"><li><div class="mw-search-result-heading"><a href="/wiki/Novel_(Short_Story)">Novel (Short Story)</a></div><div class="searchresult">Example Writer</div></li></ul>',
            }
        if value["url"].endswith("Novel_(Short_Story)"):
            return {"state": "ok", "url": value["url"], "html": "book", "xml": "export"}
        return {"state": "empty"}

    monkeypatch.setattr(provider, "browser_call", call)
    monkeypatch.setattr(
        provider,
        "parse_page",
        lambda kind, *a, **kw: (
            [
                {
                    "url": "https://wh40k.lexicanum.com/wiki/Novel_(Short_Story)",
                    "title": "Novel (Short Story)",
                    "snippet": "Example Writer",
                }
            ]
            if kind == "lexicanum_search"
            else {
                "name": "Novel (Short Story)",
                "box": {
                    "img": "/mediawiki/images/a/ab/Novel.jpg",
                    "author": "Example Writer",
                    "caption": "Novel",
                    "caption_links": [],
                },
            }
        ),
    )
    result = provider.lexicanum(query())
    assert result["state"] == "results"
    assert any("Special%3ASearch" in url and "Example" in url for _, url in calls)
    assert result["candidates"][0]["urls"] == [
        "https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg"
    ]


def test_wiki_search_parser_keeps_only_same_wiki_article_links():
    html = '<ul class="mw-search-results"><li><div class="mw-search-result-heading"><a href="/wiki/Novel_(Audio_Drama)">Novel</a></div><div class="searchresult">Example Writer</div></li><li><div class="mw-search-result-heading"><a href="https://example.org/wiki/Other">Other</a></div></li><li><div class="mw-search-result-heading"><a href="/wiki/Special:Export/Novel">Export</a></div></li></ul>'
    result = provider.parse_page(
        "lexicanum_search",
        html,
        "https://wh40k.lexicanum.com/mediawiki/index.php?title=Special%3ASearch&search=Novel&fulltext=1&limit=5&ns0=1",
    )
    assert len(result) == 1 and result[0]["title"] == "Novel"
    assert result[0]["snippet"] == "Novel Example Writer"


@pytest.mark.parametrize(
    "extra", ["&action=edit", "&limit=500", "&search=Other", "&redirect=https://example.org"]
)
def test_wiki_search_has_a_closed_query_vocabulary(extra):
    from librarium.cover_source_protocol import browser_url

    with pytest.raises(ValueError):
        browser_url(
            "https://wh40k.lexicanum.com/mediawiki/index.php?title=Special%3ASearch&search=Novel&fulltext=1&limit=5&ns0=1"
            + extra,
            "lexicanum_search",
        )


def test_unrecognised_wiki_search_page_cannot_prove_no_match():
    with pytest.raises(ValueError):
        provider.parse_page(
            "lexicanum_search",
            "<html>Unexpected layout</html>",
            "https://wh40k.lexicanum.com/mediawiki/index.php?title=Special%3ASearch&search=Novel&fulltext=1&limit=5&ns0=1",
        )


def test_image_watchdog_starts_after_slow_wiki_releases_browser(settings, monkeypatch):
    settings.LIBRARIUM_SOURCE_BROWSER_ENABLED = True
    settings.LIBRARIUM_SOURCE_BROWSER_SECRET = "x" * 48
    wiki_running, release_wiki, image_started = (threading.Event() for _ in range(3))
    timers = []

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds = seconds

        def start(self):
            timers.append(self.seconds)
            if self.seconds == 20:
                image_started.set()

        def cancel(self):
            pass

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path, *args):
            self.path = path

        def getresponse(self):
            if self.path == "/lexicanum":
                wiki_running.set()
                assert release_wiki.wait(3)
            return self

        status = 200

        def getheader(self, key, default=""):
            return str(len(self.read())) if key == "Content-Length" else "application/octet-stream"

        def read(self, *args):
            return b"pixels" if self.path == "/image" else b'{"state":"empty"}'

        def close(self):
            pass

    monkeypatch.setattr(provider.threading, "Timer", Timer)
    monkeypatch.setattr(provider.http.client, "HTTPConnection", Connection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        wiki = pool.submit(provider.browser_call, "/lexicanum", {"url": "wiki"})
        assert wiki_running.wait(2)
        image = pool.submit(provider.browser_call, "/image", {"url": "image"})
        try:
            assert not image_started.wait(0.15), "Image deadline consumed while browser is occupied"
        finally:
            release_wiki.set()
        assert wiki.result() == {"state": "empty"}
        assert image.result() == b"pixels"
    assert timers == [85, 20]


def test_browser_queue_timeout_is_bounded_without_starting_transport(settings, monkeypatch):
    settings.LIBRARIUM_SOURCE_BROWSER_ENABLED = True
    settings.LIBRARIUM_SOURCE_BROWSER_SECRET = "x" * 48
    monkeypatch.setattr(provider, "BROWSER_QUEUE_SECONDS", 0)
    with provider.BROWSER_LOCK:
        assert provider.browser_call("/image", {"url": "image"}) == {"state": "busy"}


def test_browser_transport_failure_releases_queue_lock(settings, monkeypatch):
    settings.LIBRARIUM_SOURCE_BROWSER_ENABLED = True
    settings.LIBRARIUM_SOURCE_BROWSER_SECRET = "x" * 48

    def refused(*args):
        raise ValueError("Synthetic transport construction failure")

    monkeypatch.setattr(provider, "_browser_call", refused)
    with pytest.raises(ValueError, match="Synthetic transport"):
        provider.browser_call("/image", {"url": "image"})
    assert provider.BROWSER_LOCK.acquire(blocking=False)
    provider.BROWSER_LOCK.release()


@pytest.mark.parametrize(
    "marker,snippet",
    [
        ("Fixture Tale (Short Story)", "Example Writer"),
        ("Fixture Tale (Audio Drama)", "Example Writer"),
        ("Fixture Tale (Novel)", "Example Writer"),
        ("Fixture Tale", "A book by Example Writer"),
    ],
)
def test_wiki_search_skips_lore_before_export_and_before_two_result_cap(
    monkeypatch, marker, snippet
):
    calls = []
    host = "https://wh40k.lexicanum.com"
    hits = [
        {
            "url": host + f"/wiki/Fixture_Tale_(Lore_{n})",
            "title": "Fixture Tale",
            "snippet": "Example Writer",
        }
        for n in range(2)
    ] + [
        {
            "url": host + "/wiki/Fixture_Tale_(Publication)",
            "title": marker,
            "snippet": snippet,
        }
    ]

    def call(path, value, *args):
        calls.append((path, value["url"]))
        if path == "/lexicanum_search":
            return {"state": "ok", "url": value["url"], "html": "search"}
        if value["url"].endswith("_(Publication)"):
            return {"state": "ok", "url": value["url"], "html": "book", "xml": "export"}
        return {"state": "empty"}

    monkeypatch.setattr(provider, "browser_call", call)
    monkeypatch.setattr(
        provider,
        "parse_page",
        lambda kind, *a, **kw: (
            hits
            if kind == "lexicanum_search"
            else {
                "name": "Fixture Tale",
                "box": {
                    "img": "/mediawiki/images/a/ab/Fixture_Tale.jpg",
                    "author": "Example Writer",
                    "caption": "Fixture Tale",
                    "caption_links": [],
                },
            }
        ),
    )
    assert provider.lexicanum(query(title="Fixture Tale"))["state"] == "results"
    assert not any("Lore_" in url for _, url in calls)
    assert calls[-1] == ("/lexicanum", hits[-1]["url"])
