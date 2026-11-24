"""Browser results keep the existing image-child and immutable picker admission."""

import pytest
from librarium import cover_browser_sources, cover_sources
from librarium.models import CoverSearch
from tests.test_cover_facts import jpeg
from tests.test_web_cover_jobs import covers as covers_fixture
from tests.test_web_cover_jobs import library as library_fixture
from tests.test_web_cover_jobs import page as page_fixture
from tests.test_web_cover_jobs import setup_search as setup_search_fixture
from tests.test_web_cover_jobs import start

setup_search, page, covers, library = (
    setup_search_fixture,
    page_fixture,
    covers_fixture,
    library_fixture,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_live_request_retains_archive_fallback_after_a_challenge(setup_search, client, monkeypatch):
    url, params = setup_search
    monkeypatch.setattr(
        cover_browser_sources, "lexicanum", lambda *a: {"state": "challenged", "candidates": []}
    )
    monkeypatch.setattr(
        cover_sources, "source_call", lambda *a: b'{"state":"empty","candidates":[]}'
    )
    result = start(client, url, params, sources=["lexicanum_live"])
    assert result.status_code == 202
    cover_sources.tick()
    row = CoverSearch.objects.get()
    assert row.sources == ["lexicanum_live", "lexicanum"]
    assert row.statuses == {"lexicanum_live": "challenged", "lexicanum": "empty"}
    assert row.state == "complete"


def test_goodreads_bytes_go_through_image_child_with_browser_provenance(
    setup_search, client, monkeypatch
):
    url, params = setup_search
    monkeypatch.setattr(
        cover_browser_sources,
        "goodreads",
        lambda *a, **kw: {
            "state": "results",
            "candidates": [
                {
                    "src": "Goodreads",
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://i.gr-assets.com/2.jpg"],
                }
            ],
        },
    )
    raw = jpeg((600, 900), art=True)
    monkeypatch.setattr(cover_browser_sources, "browser_call", lambda *a: raw)
    assert start(client, url, params, sources=["goodreads"]).status_code == 202
    cover_sources.tick()
    row = CoverSearch.objects.get()
    assert row.statuses["goodreads"] == "results"
    candidate = row.candidates[0]
    assert candidate["reach_method"] == "server_browser"
    assert candidate["pipeline"] == "metadata-stripped-jpeg-v1"
    assert candidate["width"] == 600


def test_browser_setting_defaults_off(settings):
    assert settings.LIBRARIUM_SOURCE_BROWSER_ENABLED is False
