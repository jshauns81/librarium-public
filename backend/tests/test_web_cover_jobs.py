"""Search custody, restart/cancellation and the existing append-only selection path."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from librarium import cover_sources
from librarium.models import CoverSearch, PreparedCover
from tests.test_cover_candidates import choose, request, store
from tests.test_cover_candidates import covers as covers_fixture
from tests.test_cover_candidates import library as library_fixture
from tests.test_cover_candidates import page as page_fixture
from tests.test_cover_facts import jpeg

covers, library, page = covers_fixture, library_fixture, page_fixture
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup_search(page, covers, settings, client, tmp_path):
    store(covers, settings)
    settings.LIBRARIUM_COVER_SOURCES_ENABLED = True
    settings.LIBRARIUM_ARTIFACT_DIR = str(tmp_path / "artifacts")
    (tmp_path / "artifacts").mkdir(mode=0o700)
    url, params = request(page, client)
    return url.removesuffix("/choices") + "/searches", params


def start(client, url, params, sources=None, query=None, key=None):
    return client.post(
        url,
        {
            **params,
            "query": query or {"title": "Synthetic One", "author": "Example Writer", "isbn": ""},
            "sources": sources or ["apple"],
            "image_url": "",
        },
        content_type="application/json",
        REMOTE_USER="reviewer",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


def test_disabled_and_unauthenticated_search_cannot_start(setup_search, client, settings):
    url, params = setup_search
    assert client.post(url, {}, content_type="application/json").status_code == 401
    settings.LIBRARIUM_COVER_SOURCES_ENABLED = False
    assert start(client, url, params).status_code == 503
    assert not CoverSearch.objects.exists()


@pytest.mark.parametrize("state", ["results", "partial"])
def test_durable_results_select_through_existing_path(setup_search, client, monkeypatch, state):
    url, params = setup_search
    raw = jpeg((600, 900), art=True)
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: {
            "state": state,
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                    "by_isbn": False,
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: raw)
    key = str(uuid.uuid4())
    result = start(client, url, params, key=key)
    assert result.status_code == 202
    assert start(client, url, params, key=key).json()["id"] == result.json()["id"]
    cover_sources.tick()
    job = CoverSearch.objects.get()
    assert job.state == "complete" and job.statuses["apple"] == state
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = next(c for c in data["candidates"] if c["source_name"] == "Apple Books")
    assert web["reason"] and web["width"] == 600
    assert web["match"] == 1.0 and web["confidence"] == "strong"
    assert client.get(web["url"], REMOTE_USER="reviewer").status_code == 200
    assert choose(client, choices_url, params, data, web["id"]).status_code == 201
    assert PreparedCover.objects.count() == 1


def test_expired_lease_resumes_and_cancel_fences_late_result(setup_search, client, monkeypatch):
    url, params = setup_search
    started = start(client, url, params).json()
    CoverSearch.objects.filter(pk=started["id"]).update(
        state="running", lease_until=timezone.now() - timedelta(seconds=1), lease_token=uuid.uuid4()
    )

    def cancelled(*a):
        cover_sources.cancel(started["id"])
        return {"state": "empty", "candidates": []}

    monkeypatch.setattr(cover_sources, "source_search", cancelled)
    cover_sources.tick()
    row = CoverSearch.objects.get()
    assert row.state == "cancelled" and not row.candidates


def test_empty_unavailable_and_rate_limit_are_distinct(setup_search, client, monkeypatch):
    url, params = setup_search
    start(client, url, params, sources=["apple", "hardcover", "google"])
    states = iter(["empty", "unavailable", "rate_limited"])
    monkeypatch.setattr(
        cover_sources, "source_search", lambda *a: {"state": next(states), "candidates": []}
    )
    for _ in range(3):
        cover_sources.tick()
    assert set(CoverSearch.objects.get().statuses.values()) == {
        "empty",
        "unavailable",
        "rate_limited",
    }


def test_omnibus_candidate_is_visible_but_server_refuses_it(setup_search, client, monkeypatch):
    url, params = setup_search
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": "Synthetic One Omnibus",
                    "author": "Example Writer",
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                    "by_isbn": True,
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    assert start(client, url, params).status_code == 202
    cover_sources.tick()
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = next(c for c in data["candidates"] if c["source_name"] == "Apple Books")
    assert not web["selectable"] and "Omnibus" in web["reason"]
    assert choose(client, choices_url, params, data, web["id"]).status_code == 409


@pytest.mark.parametrize("match", [0.7499, 0.75, 0.9])
def test_explicit_wiki_source_runs_alongside_other_sources_regardless_of_score(
    setup_search, client, monkeypatch, match
):
    url, params = setup_search
    start(client, url, params, sources=["lexicanum", "apple"])
    calls = []

    def search(q, source, key):
        calls.append(source)
        if source == "lexicanum":
            return {"state": "empty", "candidates": []}
        return {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": q["title"],
                    "author": q["author"],
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                    "by_isbn": True,
                }
            ],
        }

    monkeypatch.setattr(cover_sources, "source_search", search)
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    cover_sources.tick()
    row = CoverSearch.objects.get()
    row.candidates[0]["match"] = match
    row.save(update_fields=["candidates"])
    cover_sources.tick()
    assert set(calls) == {"apple", "lexicanum"} and len(calls) == 2
    assert CoverSearch.objects.get().statuses["lexicanum"] == "empty"


def test_paste_stays_bound_to_target_and_stale_current_cover_cannot_be_selected(
    setup_search, client, monkeypatch
):
    url, params = setup_search
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    value = {
        **params,
        "query": {"title": "Synthetic One", "author": "", "isbn": ""},
        "sources": [],
        "image_url": "https://is1-ssl.mzstatic.com/a.jpg",
    }
    assert (
        client.post(
            url,
            value,
            content_type="application/json",
            REMOTE_USER="reviewer",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).status_code
        == 202
    )
    cover_sources.tick()
    row = CoverSearch.objects.get()
    assert row.candidates[0]["query"] == value["query"]
    row.binding["current_cover_sha256"] = "f" * 64
    row.save(update_fields=["binding"])
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    assert not any(c["source_name"] == "Image URL" for c in data["candidates"])


def test_saved_web_selection_survives_later_queries(setup_search, client, monkeypatch):
    url, params = setup_search
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda q, *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": q["title"],
                    "author": q["author"],
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                    "by_isbn": False,
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    start(client, url, params)
    cover_sources.tick()
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = next(c for c in data["candidates"] if c["source_name"] == "Apple Books")
    assert choose(client, choices_url, params, data, web["id"]).status_code == 201
    saved = PreparedCover.objects.get()
    saved_candidate = dict(saved.candidate)
    for i in range(4):
        start(client, url, params, query={"title": f"Another title {i}", "author": "A", "isbn": ""})
        cover_sources.tick()
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    assert data["selection"]["status"] == "awaiting_approval"
    assert data["selection"]["candidate_id"] == web["id"]
    assert len([c for c in data["candidates"] if c["label"] == "Web"]) == 1
    saved.refresh_from_db()
    assert saved.candidate == saved_candidate


def test_metadata_only_image_changes_keep_saved_canonical_selection(
    setup_search, client, monkeypatch
):
    url, params = setup_search
    raw = jpeg((600, 900), art=True)
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: raw)
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda q, *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": q["title"],
                    "author": q["author"],
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                }
            ],
        },
    )
    start(client, url, params)
    cover_sources.tick()
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    old = next(c for c in data["candidates"] if c["label"] == "Web")
    assert choose(client, choices_url, params, data, old["id"]).status_code == 201
    saved = PreparedCover.objects.get()
    evidence = dict(saved.candidate)
    raw = jpeg((600, 900), art=True, comment=b"Synthetic changed source metadata")
    start(client, url, params)
    cover_sources.tick()
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = [c for c in data["candidates"] if c["label"] == "Web"]
    assert len(web) == 1
    # The saved record itself stands for its image; a same-bytes newer record is not a second choice.
    assert web[0]["sha256"] == old["sha256"] and web[0]["id"] == old["id"]
    assert data["selection"]["status"] == "awaiting_approval"
    assert data["selection"]["candidate_id"] == old["id"]
    saved.refresh_from_db()
    assert saved.candidate == evidence


@pytest.mark.parametrize("paste", [False, True], ids=["refined-search", "pasted-image"])
def test_newest_results_have_capacity_after_full_search(setup_search, client, monkeypatch, paste):
    url, params = setup_search
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda q, *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": q["title"],
                    "author": q["author"],
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                }
            ],
        },
    )
    assert start(client, url, params).status_code == 202
    cover_sources.tick()
    old = CoverSearch.objects.get()
    import hashlib

    original_candidate = old.candidates[0]
    old.candidates = [
        dict(
            original_candidate,
            id=str(uuid.uuid4()),
            sha256=hashlib.sha256(str(i).encode()).hexdigest(),
        )
        for i in range(23)
    ] + [dict(original_candidate, id=str(uuid.uuid4()))]
    old.save(update_fields=["candidates"])
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    selected_id = old.candidates[-1]["id"]
    assert choose(client, choices_url, params, data, selected_id).status_code == 201
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((610, 910), art=True))
    if paste:
        result = client.post(
            url,
            {
                **params,
                "query": old.query,
                "sources": [],
                "image_url": "https://images.example.org/new.jpg",
            },
            content_type="application/json",
            REMOTE_USER="reviewer",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    else:
        result = start(client, url, params, query={**old.query, "title": "Refined title"})
    assert result.status_code == 202
    cover_sources.tick()
    latest = CoverSearch.objects.get(pk=result.json()["id"])
    assert len(latest.candidates) == 1
    visible = cover_sources.candidates(old.entry, old.binding, PreparedCover.objects.get())
    assert len(visible) == 24
    assert selected_id in {c["id"] for c in visible}
    assert latest.candidates[0]["id"] in {c["id"] for c in visible}
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    assert data["selection"]["status"] == "awaiting_approval"
    assert choose(client, choices_url, params, data, latest.candidates[0]["id"]).status_code == 201


@pytest.mark.django_db(transaction=True)
def test_populated_picker_upgrade_keeps_prepared_evidence_and_can_reapply():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    prior = [("librarium", "0014_prepared_cover")]
    current = [("librarium", "0015_cover_search")]
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(prior)
        apps = executor.loader.project_state(prior).apps
        entry = apps.get_model("librarium", "CoverReviewEntry").objects.create(
            library_uuid="fixture-library",
            book_uuid="fixture-book",
            calibre_id=42,
            title="Synthetic retained selection",
        )
        saved = apps.get_model("librarium", "PreparedCover").objects.create(
            request_key=uuid.uuid4(),
            entry=entry,
            actor="reviewer",
            request={},
            binding={"target": "synthetic"},
            candidate={"id": "retained"},
        )
        for target in (current, prior, current):
            MigrationExecutor(connection).migrate(target)
            retained = PreparedCover.objects.get(pk=saved.pk)
            assert retained.candidate == {"id": "retained"} and retained.binding == {
                "target": "synthetic"
            }
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def test_missing_candidate_artifact_is_retryable_and_never_saved(
    setup_search, client, settings, monkeypatch
):
    from pathlib import Path

    url, params = setup_search
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                    "by_isbn": False,
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    start(client, url, params)
    cover_sources.tick()
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = next(c for c in data["candidates"] if c["source_name"] == "Apple Books")
    (Path(settings.LIBRARIUM_ARTIFACT_DIR) / ("web-" + web["sha256"])).unlink()
    assert choose(client, choices_url, params, data, web["id"]).status_code == 503
    assert not PreparedCover.objects.exists()


def test_paste_explicitly_requires_no_provider_sources(setup_search, client):
    url, params = setup_search
    value = {
        **params,
        "query": {"title": "Novel", "author": "", "isbn": ""},
        "sources": ["apple"],
        "image_url": "https://is1-ssl.mzstatic.com/a.jpg",
    }
    reply = client.post(
        url,
        value,
        content_type="application/json",
        REMOTE_USER="reviewer",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert reply.status_code == 400
    assert not CoverSearch.objects.exists()


def test_actor_daily_quota_is_not_reset_by_cancel(setup_search, client):
    url, params = setup_search
    for _ in range(20):
        response = start(client, url, params)
        assert response.status_code == 202
        cover_sources.cancel(response.json()["id"])
    assert start(client, url, params).status_code == 429


@pytest.mark.parametrize("isbn", [[], {}, 1])
def test_provider_isbn_is_typed_before_image_fetch(isbn, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        cover_sources, "source_image", lambda *a: pytest.fail("untyped ISBN fetched")
    )
    with pytest.raises(ValueError):
        cover_sources.admit(
            {
                "src": "Apple Books",
                "title": "Novel",
                "isbn": isbn,
                "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
            },
            SimpleNamespace(),
            "apple",
        )


def test_provider_cannot_supply_an_arbitrary_image_host(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        cover_sources, "source_image", lambda *a: pytest.fail("unlisted host fetched")
    )
    assert (
        cover_sources.admit(
            {"src": "Apple Books", "title": "Novel", "urls": ["https://images.example.org/a.jpg"]},
            SimpleNamespace(),
            "apple",
        )
        is None
    )


def test_retention_preserves_prepared_and_shared_artifacts(
    setup_search, client, settings, monkeypatch
):
    import hashlib
    import io
    import os
    import time
    from pathlib import Path

    from librarium import artifacts

    url, params = setup_search
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    start(client, url, params)
    cover_sources.tick()
    row = CoverSearch.objects.get()
    c = row.candidates[0]
    PreparedCover.objects.create(
        request_key=uuid.uuid4(),
        entry=row.entry,
        actor="reviewer",
        request={},
        binding=row.binding,
        candidate=c,
    )
    CoverSearch.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=8))
    orphan = b"unselected derivative"
    digest = hashlib.sha256(orphan).hexdigest()
    artifacts.ingest_web(io.BytesIO(orphan), digest, expected_size=len(orphan))
    artifacts.ingest(io.BytesIO(orphan), digest, expected_size=len(orphan))
    path = Path(settings.LIBRARIUM_ARTIFACT_DIR) / ("web-" + digest)
    os.utime(path, (time.time() - 8 * 86400,) * 2)
    cover_sources.retain()
    assert not path.exists()
    assert artifacts.read("source", digest, len(orphan)) == orphan
    assert cover_sources.verify_candidate(c)
    assert CoverSearch.objects.get(pk=row.pk).candidates == [c]


def test_search_rpc_already_waits_longer_than_child_limit(monkeypatch, settings):
    import io
    from unittest.mock import Mock

    settings.LIBRARIUM_COVER_SOURCES_SECRET = "fixture-" * 8
    response = io.BytesIO(b'{"state":"empty","candidates":[]}')
    response.status = 200
    response.getheader = lambda *a: str(len(response.getvalue()))
    connection = Mock()
    connection.getresponse.return_value = response
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(cover_sources.http.client, "HTTPConnection", constructor)
    cover_sources.source_search(
        {"title": "Novel", "author": "", "isbn": ""}, "apple", str(uuid.uuid4())
    )
    assert constructor.call_args.kwargs["timeout"] == 95


@pytest.mark.django_db(transaction=True)
def test_selection_holds_retention_lock_when_verifying_web_bytes(setup_search, client, monkeypatch):
    from django.db import connection

    url, params = setup_search
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    start(client, url, params)
    cover_sources.tick()
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = next(c for c in data["candidates"] if c["source_name"] == "Apple Books")
    original = cover_sources.verify_candidate

    def verified(c):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=%s",
                [cover_sources.cover_candidates.LOCK],
            )
            assert cursor.fetchone()[0] == 1, "selection verification races retention"
        return original(c)

    monkeypatch.setattr(cover_sources, "verify_candidate", verified)
    assert choose(client, choices_url, params, data, web["id"]).status_code == 201


def test_actor_concurrency_cap_applies_across_books(setup_search, client, monkeypatch):
    from librarium.models import CoverReviewEntry

    _url, params = setup_search
    entries = [
        CoverReviewEntry.objects.create(
            library_uuid="quota-fixture", book_uuid=f"quota-{n}", calibre_id=100 + n, title="Novel"
        )
        for n in range(3)
    ]

    def choices(entry_id, params):
        return {}, CoverReviewEntry.objects.get(pk=entry_id), {}, "", ""

    monkeypatch.setattr(cover_sources.cover_candidates, "choices", choices)
    value = {
        **params,
        "query": {"title": "Novel", "author": "", "isbn": ""},
        "sources": ["apple"],
        "image_url": "",
    }
    first = cover_sources.start(entries[0].pk, value, str(uuid.uuid4()), "quota-reviewer")
    cover_sources.start(entries[1].pk, value, str(uuid.uuid4()), "quota-reviewer")
    with pytest.raises(cover_sources.cover_candidates.ChoiceError) as error:
        cover_sources.start(entries[2].pk, value, str(uuid.uuid4()), "quota-reviewer")
    assert error.value.status == 429
    cover_sources.cancel(first.pk)
    assert (
        cover_sources.start(entries[2].pk, value, str(uuid.uuid4()), "quota-reviewer").state
        == "queued"
    )


def test_expired_search_cannot_be_selected_while_shared_bytes_survive(
    setup_search, client, monkeypatch
):
    url, params = setup_search
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://is1-ssl.mzstatic.com/a.jpg"],
                }
            ],
        },
    )
    monkeypatch.setattr(cover_sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    start(client, url, params)
    cover_sources.tick()
    choices_url = url.removesuffix("/searches") + "/choices"
    data = client.get(choices_url, params, REMOTE_USER="reviewer").json()
    web = next(c for c in data["candidates"] if c["source_name"] == "Apple Books")
    original = cover_sources.cover_candidates.choices

    def expired(*args):
        result = original(*args)
        CoverSearch.objects.all().delete()
        return result

    monkeypatch.setattr(cover_sources.cover_candidates, "choices", expired)
    assert choose(client, choices_url, params, data, web["id"]).status_code == 409
    assert not PreparedCover.objects.exists()


@pytest.mark.parametrize("state", ["not_configured", "partial"])
def test_terminal_coverage_states_are_persisted_without_retry(
    setup_search, client, monkeypatch, state
):
    url, params = setup_search
    start(client, url, params)
    calls = []
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda *a: calls.append(a) or {"state": state, "candidates": []},
    )
    cover_sources.tick()
    cover_sources.tick()
    row = CoverSearch.objects.get()
    assert row.state == "complete" and row.statuses["apple"] == state
    assert len(calls) == 1


@pytest.mark.django_db(transaction=True)
def test_sources_start_together_and_checkpoint_before_slowest_finishes(
    setup_search, client, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    url, params = setup_search
    started = start(client, url, params, sources=["apple", "google", "hardcover"]).json()
    barrier = threading.Barrier(3)
    release = threading.Event()

    def search(q, source, *a):
        barrier.wait(timeout=3)
        if source == "hardcover":
            assert release.wait(8)
        return {"state": "empty", "candidates": []}

    monkeypatch.setattr(cover_sources, "source_search", search)

    def run():
        try:
            return cover_sources.tick()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run)
        try:
            import time

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                row = CoverSearch.objects.get(pk=started["id"])
                if row.statuses["apple"] == "empty" and row.statuses["google"] == "empty":
                    break
                time.sleep(0.02)
            assert row.statuses == {"apple": "empty", "google": "empty", "hardcover": "running"}
            assert row.source_timings["apple"]["finished_at"]
            assert row.source_timings["apple"]["duration_ms"] >= 0
            assert not future.done()
        finally:
            release.set()
        assert future.result(timeout=10)
    row.refresh_from_db()
    assert row.state == "complete" and all(v == "empty" for v in row.statuses.values())
    assert all(v["started_at"] and v["finished_at"] for v in row.source_timings.values())


@pytest.mark.django_db(transaction=True)
def test_parallel_cancellation_and_replaced_lease_fence_every_late_checkpoint(
    setup_search, client, monkeypatch
):
    url, params = setup_search
    row_id = start(client, url, params, sources=["apple", "google"]).json()["id"]
    import threading

    gate = threading.Barrier(2)

    def search(q, source, *args):
        gate.wait(3)
        if source == "apple":
            cover_sources.cancel(row_id)
        return {"state": "empty", "candidates": []}

    monkeypatch.setattr(cover_sources, "source_search", search)
    cover_sources.tick()
    row = CoverSearch.objects.get(pk=row_id)
    assert row.state == "cancelled"
    assert set(row.statuses.values()) <= {"empty", "cancelled"} and not row.candidates
    old = row.lease_token
    CoverSearch.objects.filter(pk=row_id).update(
        state="running",
        lease_token=uuid.uuid4(),
        lease_until=timezone.now() + timedelta(seconds=60),
        statuses={"apple": "running", "google": "empty"},
    )
    cover_sources._checkpoint(row, old, "apple", "failed", [])
    row.refresh_from_db()
    assert row.statuses["apple"] == "running"


@pytest.mark.django_db(transaction=True)
def test_resume_retries_only_unfinished_sources_and_retains_completed_timing(
    setup_search, client, monkeypatch
):
    url, params = setup_search
    row_id = start(client, url, params, sources=["apple", "google"]).json()["id"]
    timing = {
        "started_at": timezone.now().isoformat(),
        "finished_at": timezone.now().isoformat(),
        "duration_ms": 1,
    }
    CoverSearch.objects.filter(pk=row_id).update(
        state="running",
        lease_token=uuid.uuid4(),
        lease_until=timezone.now() - timedelta(seconds=1),
        statuses={"apple": "empty", "google": "running"},
        source_timings={"apple": timing},
    )
    calls = []
    monkeypatch.setattr(
        cover_sources,
        "source_search",
        lambda q, source, *a: calls.append(source) or {"state": "empty", "candidates": []},
    )
    cover_sources.tick()
    row = CoverSearch.objects.get(pk=row_id)
    assert calls == ["google"] and row.state == "complete"
    assert row.source_timings["apple"] == timing
    assert row.source_timings["google"]["finished_at"]
