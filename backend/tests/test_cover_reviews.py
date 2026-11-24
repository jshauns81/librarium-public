"""Read-only whole-library census and shared compare-and-set queue journeys."""

import hashlib
import json
import uuid
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from librarium import cover_reviews, library_read_model
from librarium.models import CoverCensus, CoverReviewEntry
from tests.test_cover_facts import jpeg
from tests.test_library_read_model import library as library_fixture
from tests.test_library_read_model import update

pytestmark = pytest.mark.django_db
library = library_fixture
BASE = "/api/cover-reviews"


@pytest.fixture(autouse=True)
def census_refresh_clock(settings, monkeypatch):
    settings.LIBRARY_READ_MODEL_SECONDS = 0
    monkeypatch.setattr(library_read_model, "_next_tick", 0)


@pytest.fixture(autouse=True)
def observation_clock(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(cover_reviews, "time", SimpleNamespace(monotonic=lambda: clock.now))
    yield clock
    cover_reviews.shutdown_observations()


@pytest.fixture
def controlled_observations(monkeypatch):
    class Pool:
        def __init__(self):
            self.tasks = []
            self.on_wait = self.complete

        def submit(self, fn, *args):
            future = Future()
            self.tasks.append((future, fn, args))
            return future

        def complete(self, futures):
            for future, fn, args in self.tasks:
                if future in futures and not future.done():
                    future.set_result(fn(*args))

        def wait(self, futures, **kwargs):
            self.on_wait(set(futures))
            return (
                {future for future in futures if future.done()},
                {future for future in futures if not future.done()},
            )

        def shutdown(self, **kwargs):
            for future, _, _ in self.tasks:
                future.cancel()

    cover_reviews.shutdown_observations()
    pool = Pool()
    monkeypatch.setattr(cover_reviews, "ThreadPoolExecutor", lambda **kwargs: pool)
    monkeypatch.setattr(cover_reviews, "wait", pool.wait)
    return pool


def start():
    return cover_reviews.start(str(uuid.uuid4()))


def drain():
    for _ in range(50):
        if not cover_reviews.tick(batch_size=2):
            return
    raise AssertionError("census did not settle")


def entry(book="uuid-1"):
    return CoverReviewEntry.objects.get(library_uuid="library-uuid", book_uuid=book)


def fixture_covers(root):
    for path in ["Writer/Actual Book (1)", "Other/beta (3)", "Writer/Unicode (5)"]:
        (root / path / "cover.jpg").write_bytes(jpeg(art=True))
    (root / "Gone/Zeta (4)").mkdir(parents=True)


def post(client, path, body, key=None):
    return client.post(
        path,
        json.dumps(body),
        content_type="application/json",
        REMOTE_USER="reviewer",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


def test_full_scan_beyond_page_resume_and_non_epub(library):
    fixture_covers(library)
    update(library, "DELETE FROM data WHERE book=3")
    library_read_model.refresh()
    before = {
        str(p.relative_to(library)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in library.rglob("*")
        if p.is_file()
    }
    census = start()
    assert census.remaining == 5
    cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert (census.scanned, census.remaining, census.cursor) == (2, 3, 2)
    drain()
    census.refresh_from_db()
    assert (census.state, census.scanned, census.remaining, census.unresolved) == (
        "complete",
        5,
        0,
        0,
    )
    assert entry("uuid-3").facts["width"] == 1000
    assert entry("uuid-2").facts["reasons"] == ["missing"]
    after = {
        str(p.relative_to(library)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in library.rglob("*")
        if p.is_file()
    }
    assert before == after


def test_unresolved_never_claims_complete_or_missing(library):
    library_read_model.refresh()
    census = start()
    drain()
    census.refresh_from_db()
    assert census.state == "partial" and census.unresolved >= 2 and census.remaining == 0
    assert entry("uuid-5").facts["status"] == "unresolved"
    assert entry("uuid-4").facts["reasons"] == []  # missing folder is not proof of no cover


def test_inventory_change_keeps_cursor_and_finishes_the_same_census(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    update(library, "UPDATE books SET title='Changed' WHERE id=3")
    library_read_model.refresh()
    cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.cursor == 4 and census.scanned == 4
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5
    assert CoverCensus.objects.count() == 1


def test_skip_replay_conflict_unskip_and_changed_cover(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    route = f"{BASE}/{current.pk}/skip"
    key = str(uuid.uuid4())
    body = {"revision": current.revision, "skipped": True}
    first = post(client, route, body, key)
    assert first.status_code == 200 and first.json()["state"] == "skipped"
    assert post(client, route, body, key).json() == first.json()
    assert post(client, route, body).status_code == 409
    (library / "Zola/Emile Story (2)/cover.jpg").write_bytes(jpeg((999, 1199), art=True))
    library_read_model.refresh(force=True)
    start()
    drain()
    current.refresh_from_db()
    assert current.state == "skipped" and current.changed_since_skipped
    assert post(client, route, {"revision": current.revision, "skipped": False}).status_code == 200
    assert (
        post(client, route, body, key).json() == first.json()
    )  # cannot replay a write after unskip
    current.refresh_from_db()
    assert current.state == "todo"


def test_recreated_numeric_id_and_other_library_never_inherit_skip(library):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    old = entry("uuid-2")
    cover_reviews.set_skip(old.pk, old.revision, True, str(uuid.uuid4()), "reviewer")
    update(library, "DELETE FROM books WHERE id=2")
    library_read_model.refresh()
    start()
    drain()
    old.refresh_from_db()
    assert not old.present
    update(
        library,
        "INSERT INTO books(id,title,sort,path,uuid) VALUES(2,'New','New','Zola/Emile Story (2)','new-book')",
    )
    library_read_model.refresh()
    start()
    drain()
    assert entry("new-book").state == "todo"
    update(library, "UPDATE library_id SET uuid='other-library'")
    library_read_model.refresh()
    start()
    drain()
    assert (
        CoverReviewEntry.objects.get(library_uuid="other-library", book_uuid="new-book").state
        == "todo"
    )


def test_api_filters_paging_auth_csrf_local_preview(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    assert client.get(BASE).status_code == 401
    assert client.get(BASE, HTTP_REMOTE_USER="spoof").status_code == 401
    result = client.get(BASE + "?reason=missing&page=1", REMOTE_USER="reviewer")
    assert result.status_code == 200 and result.headers["Cache-Control"] == "no-store"
    assert result.json()["total"] == 2
    assert client.get(BASE + "?reason=bad", REMOTE_USER="reviewer").status_code == 400
    assert client.get(BASE + "?page=1&page=2", REMOTE_USER="reviewer").status_code == 400
    current = entry()
    result = client.get(f"{BASE}/{current.pk}/cover", REMOTE_USER="reviewer")
    assert result.status_code == 200 and result.headers["Content-Type"] == "image/jpeg"
    result = Client(enforce_csrf_checks=True).post(
        f"{BASE}/{current.pk}/skip", b"{}", content_type="application/json", REMOTE_USER="reviewer"
    )
    assert result.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_populated_upgrade_preserves_books_and_starts_no_census(library):
    library_read_model.refresh()
    before = list(library_read_model.CalibreBook.objects.values_list("pk", "uuid", "path"))
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0012_cataloguestatus")])
    try:
        old = executor.loader.project_state([("librarium", "0012_cataloguestatus")]).apps
        assert (
            list(
                old.get_model("librarium", "CalibreBook").objects.values_list("pk", "uuid", "path")
            )
            == before
        )
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
    assert list(library_read_model.CalibreBook.objects.values_list("pk", "uuid", "path")) == before
    assert not CoverCensus.objects.exists() and not CoverReviewEntry.objects.exists()


def test_queue_covers_more_than_one_listing_page(library, client):
    fixture_covers(library)
    update(
        library,
        """WITH RECURSIVE n(i) AS (SELECT 10 UNION ALL SELECT i+1 FROM n WHERE i<34)
        INSERT INTO books(id,title,sort,path,uuid)
        SELECT i,'Extra book','Extra book','Zola/Emile Story (2)','extra-'||i FROM n""",
    )
    library_read_model.refresh()
    census = start()
    drain()
    census.refresh_from_db()
    assert census.scanned == 30 and census.state == "complete"
    first = client.get(BASE, REMOTE_USER="reviewer").json()
    second = client.get(BASE + "?page=2", REMOTE_USER="reviewer").json()
    assert first["total"] == 27 and first["pages"] == 2
    assert len(first["entries"]) == 24 and len(second["entries"]) == 3
    assert len({row["book_uuid"] for row in first["entries"] + second["entries"]}) == 27
    assert client.get(BASE + "?state=done", REMOTE_USER="reviewer").json()["total"] == 0


def test_crashed_worker_lease_reclaims_and_live_lease_is_not_stolen(library):
    from datetime import timedelta

    from django.utils import timezone

    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    CoverCensus.objects.filter(pk=census.pk).update(
        state="running",
        lease_token=uuid.uuid4(),
        lease_until=timezone.now() + timedelta(seconds=60),
    )
    assert cover_reviews.tick() is False
    CoverCensus.objects.filter(pk=census.pk).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5


def test_cancel_during_read_never_publishes_or_advances(library, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    original = cover_reviews.source_facts

    def cancelled(*args, **kwargs):
        result = original(*args, **kwargs)
        cover_reviews.cancel(census.pk)
        return result

    monkeypatch.setattr(cover_reviews, "source_facts", cancelled)
    cover_reviews.tick()
    census.refresh_from_db()
    assert census.state == "cancelled" and census.scanned == 0 and census.remaining == 5
    assert not CoverReviewEntry.objects.exists()


def test_identity_unknown_is_counted_separately_and_duplicates_abstain(library):
    fixture_covers(library)
    update(library, "UPDATE books SET uuid=NULL WHERE id=1")
    update(library, "UPDATE books SET uuid='duplicate' WHERE id IN (2,3)")
    library_read_model.refresh()
    census = start()
    drain()
    census.refresh_from_db()
    assert census.state == "partial" and census.unresolved == 3
    assert {issue["book_id"] for issue in census.identity_issues} == {"1", "2", "3"}
    assert not CoverReviewEntry.objects.filter(book_uuid="duplicate").exists()


def test_live_change_refreshes_without_restarting_and_stale_start_is_refused(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    update(library, "UPDATE books SET title='Changed outside the model' WHERE id=3")
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.error == ""
    library_read_model.LibraryReadModel.objects.update(stale=True)
    with pytest.raises(cover_reviews.ReviewError, match="Refresh"):
        start()


def test_failed_read_can_be_retried_and_cover_changes_without_metadata_edit(library):
    library_read_model.refresh()
    start()
    drain()
    before = entry("uuid-5")
    fixture_covers(library)
    # Metadata stayed fixed. A new explicit census still stats every local cover.
    start()
    drain()
    after = entry("uuid-5")
    assert after.facts["status"] == "known" and after.revision > before.revision


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"revision":1,"revision":2,"skipped":true}',
        b'{"revision":NaN,"skipped":true}',
        b'{"revision":true,"skipped":true}',
        b'{"revision":1,"skipped":"yes"}',
        b'{"path":"cover.jpg"}',
        b"x" * 4097,
    ],
    ids=[
        "array",
        "duplicate",
        "nonfinite",
        "bool-revision",
        "string-skip",
        "unknown-field",
        "large",
    ],
)
def test_strict_mutations_do_not_change_state(library, client, raw):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    result = client.post(
        f"{BASE}/{current.pk}/skip",
        raw,
        content_type="application/json",
        REMOTE_USER="reviewer",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert result.status_code in {400, 413}
    current.refresh_from_db()
    assert current.state == "todo" and current.revision == 1


def test_explicit_request_idempotency_and_no_automatic_worker_activation(library, client):
    library_read_model.refresh()
    assert cover_reviews.tick() is False
    key = str(uuid.uuid4())
    first = post(client, BASE + "/census", {}, key)
    assert first.status_code == 202
    again = post(client, BASE + "/census", {}, key)
    assert again.json()["id"] == first.json()["id"] and CoverCensus.objects.count() == 1
    assert post(client, BASE + "/census", {}).status_code == 409
    assert post(client, f"{BASE}/censuses/{first.json()['id']}/cancel", {}).status_code == 200
    assert cover_reviews.tick() is False


@pytest.mark.django_db(transaction=True)
def test_two_devices_concurrent_cas_has_one_winner(library):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return cover_reviews.set_skip(
                current.pk, current.revision, True, str(uuid.uuid4()), "reviewer"
            )["state"]
        except cover_reviews.ReviewError as error:
            return error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["conflict", "skipped"]


def test_preview_refuses_replacement_hash_id_and_deleted_entry(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry()
    route = f"{BASE}/{current.pk}/cover"
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1200), art=True))
    assert client.get(route, REMOTE_USER="reviewer").status_code == 409
    update(library, "UPDATE books SET uuid='replacement' WHERE id=1")
    library_read_model.refresh()
    assert client.get(route, REMOTE_USER="reviewer").status_code == 409


def test_cover_symlink_and_missing_parent_remain_unresolved(library):
    fixture_covers(library)
    path = library / "Writer/Actual Book (1)/cover.jpg"
    path.unlink()
    path.symlink_to(library / "Other/beta (3)/cover.jpg")
    library_read_model.refresh()
    start()
    drain()
    assert entry().facts["status"] == "unresolved"


def test_preview_serves_every_admitted_cover_size(library, client):
    from librarium import catalogue_covers

    fixture_covers(library)
    raw = jpeg(art=True) + b"\0" * catalogue_covers.MAX_BODY
    assert catalogue_covers.MAX_BODY < len(raw) < cover_reviews.cover_facts.MAX_BYTES
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(raw)
    library_read_model.refresh()
    start()
    drain()
    current = entry()
    assert current.facts["status"] == "known"
    result = client.get(f"{BASE}/{current.pk}/cover", REMOTE_USER="reviewer")
    assert result.status_code == 200
    assert hashlib.sha256(result.content).hexdigest() == hashlib.sha256(raw).hexdigest()


def test_slow_inventory_fence_yields_without_publishing_unchecked_books(library, monkeypatch):
    fixture_covers(library)
    (library / "Writer/Actual Book (1)/cover.jpg").unlink()
    library_read_model.refresh()
    census = start()
    clock = [0.0]
    original = library_read_model.current_token

    def slow_inventory():
        clock[0] += 20.0
        return original()

    from types import SimpleNamespace

    monkeypatch.setattr(cover_reviews, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(library_read_model, "current_token", slow_inventory)
    assert cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.cursor == 0 and census.scanned == 0 and census.remaining == 5


@pytest.mark.parametrize("validating", [False, True])
@pytest.mark.parametrize("failure", ["transport", "timeout"])
def test_decoder_transport_failure_retries_without_publishing(
    library, monkeypatch, validating, failure
):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    if validating:
        cover_reviews.tick(batch_size=100)
        (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    with monkeypatch.context() as patch:
        if failure == "timeout":
            patch.setattr(cover_reviews.cover_facts, "WALL_SECONDS", 0.0)
        else:
            patch.setattr(
                cover_reviews.cover_facts,
                "inspect_cover",
                lambda raw, **kwargs: cover_reviews.cover_facts.unknown("inspection_failed"),
            )
        cover_reviews.tick(batch_size=1)
    census.refresh_from_db()
    assert census.state == "running" and census.validation_cursor == 0
    if validating:
        assert census.cursor == census.scanned == 5 and entry().facts["width"] == 1000
    else:
        assert census.cursor == census.scanned == 0 and not CoverReviewEntry.objects.exists()
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5 and census.unresolved == 0
    assert entry().facts["width"] == (1100 if validating else 1000)
    assert cover_reviews.start(str(census.request_key)).pk == census.pk
    assert CoverCensus.objects.count() == 1


def test_slow_closing_fence_keeps_progress_across_ticks(library, monkeypatch, observation_clock):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    monkeypatch.setattr(library_read_model, "_next_tick", float("inf"))
    original = library_read_model.current_token
    calls = 0

    def slow_closing_fence():
        nonlocal calls
        calls += 1
        result = original()
        if calls % 3 == 2:
            observation_clock.now += cover_reviews.SLICE_SECONDS * 2
        return result

    monkeypatch.setattr(library_read_model, "current_token", slow_closing_fence)
    cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.cursor == census.scanned == 2
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5 and census.unresolved == 0
    assert set(CoverReviewEntry.objects.values_list("book_uuid", flat=True)) == {
        "uuid-1",
        "uuid-2",
        "uuid-3",
        "uuid-4",
        "uuid-5",
    }
    assert cover_reviews.start(str(census.request_key)).pk == census.pk


def test_census_overlaps_independent_sandboxed_decoders(library, settings, monkeypatch):
    from threading import Barrier

    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = 8
    together = Barrier(3)
    original = cover_reviews.cover_facts.inspect_cover

    def decode(raw, **kwargs):
        together.wait(timeout=3)
        return original(raw, **kwargs)

    monkeypatch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
    cover_reviews.tick(batch_size=5)
    census.refresh_from_db()
    assert census.scanned == 5 and census.remaining == 0
    assert entry().facts["width"] == entry("uuid-3").facts["width"] == 1000


def test_metadata_bytes_changed_during_decode_refuse_publication(library, monkeypatch):
    from librarium import direct_library

    fixture_covers(library)
    # Hide stat changes to require the complete metadata digest, including interior pages.
    monkeypatch.setattr(direct_library, "signature", lambda info: (1, 1, info.st_size, 0, 0))
    library_read_model.refresh()
    census = start()
    original = cover_reviews.cover_facts.inspect_cover

    def decode(raw, **kwargs):
        update(library, "UPDATE books SET uuid='uuid-x' WHERE id=1")
        return original(raw, **kwargs)

    monkeypatch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
    cover_reviews.tick(batch_size=1)
    census.refresh_from_db()
    assert census.cursor == census.scanned == 0
    assert census.state == "running" and census.lease_token is None
    assert not CoverReviewEntry.objects.exists()


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_metadata_fences_are_per_chunk_on_the_main_thread(library, settings, monkeypatch, workers):
    import threading

    fixture_covers(library)
    library_read_model.refresh()
    start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = workers
    monkeypatch.setattr(library_read_model, "_next_tick", float("inf"))
    original = library_read_model.current_token
    calls = []
    decoder = cover_reviews.cover_facts.inspect_cover
    active, peak = 0, 0
    guard = threading.Lock()
    together = threading.Barrier(min(workers, 3))
    started = 0

    def decode(raw, **kwargs):
        nonlocal active, peak, started
        with guard:
            active += 1
            peak = max(active, peak)
            started += 1
            first_wave = started <= together.parties
        try:
            if first_wave:
                together.wait(timeout=10)
            return decoder(raw, **kwargs)
        finally:
            with guard:
                active -= 1

    def token():
        calls.append(threading.get_ident())
        return original()

    monkeypatch.setattr(library_read_model, "current_token", token)
    monkeypatch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
    cover_reviews.tick(batch_size=5)
    assert calls == [threading.get_ident()] * 3
    assert peak == min(workers, 3)


def test_late_chunk_metadata_edit_refuses_even_the_first_completed_result(
    library, settings, monkeypatch
):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = 1
    original = cover_reviews.cover_facts.inspect_cover
    decoded = []

    def decode(raw, **kwargs):
        result = original(raw, **kwargs)
        decoded.append(result)
        if len(decoded) == 2:
            update(library, "UPDATE books SET uuid='changed-after-first-decode' WHERE id=1")
        return result

    monkeypatch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
    cover_reviews.tick(batch_size=3)
    census.refresh_from_db()
    assert len(decoded) == 2
    assert census.cursor == census.scanned == 0
    assert not CoverReviewEntry.objects.exists()


@pytest.mark.parametrize("validating", [False, True])
def test_cover_replaced_mid_decode_is_requeued(library, monkeypatch, validating):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover = library / "Writer/Actual Book (1)/cover.jpg"
    if validating:
        cover_reviews.tick(batch_size=100)
        cover.write_bytes(jpeg((1100, 1300), art=True))
    original = cover_reviews.cover_facts.inspect_cover
    replacement = jpeg((1200, 1700), art=True)

    def decode(raw, **kwargs):
        cover.write_bytes(replacement)
        return original(raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
        cover_reviews.tick(batch_size=1)
    census.refresh_from_db()
    assert census.state == "running" and census.validation_cursor == 0
    if validating:
        assert entry().facts["width"] == 1000
    else:
        assert census.cursor == 0 and not CoverReviewEntry.objects.exists()
    drain()
    census.refresh_from_db()
    assert census.state == "complete"
    assert entry().facts["sha256"] == hashlib.sha256(replacement).hexdigest()


def test_same_stat_cover_replacement_refuses_publication(library, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover = library / "Writer/Actual Book (1)/cover.jpg"
    original = cover_reviews.cover_facts.inspect_cover

    def decode(raw, **kwargs):
        cover.write_bytes(jpeg((1200, 1700), art=True))
        return original(raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(library_read_model, "signed", lambda info: "same-stat")
        patch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
        cover_reviews.tick(batch_size=1)
    census.refresh_from_db()
    assert census.cursor == 0 and not CoverReviewEntry.objects.exists()


def test_slice_deadline_interrupts_decoders_and_retries(
    library, settings, monkeypatch, observation_clock, controlled_observations
):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = 2
    pool = controlled_observations

    def expire(futures):
        observation_clock.now += cover_reviews.SLICE_SECONDS

    pool.on_wait = expire
    cover_reviews.tick(batch_size=100)
    assert pool.tasks and all(future.cancelled() for future, _, _ in pool.tasks)
    assert all(args[1]() for _, _, args in pool.tasks)
    census.refresh_from_db()
    assert census.cursor == 0 and census.validation_cursor == 0
    assert census.lease_token is None and not CoverReviewEntry.objects.exists()
    pool.on_wait = pool.complete
    drain()
    census.refresh_from_db()
    assert census.state == "complete"


@pytest.mark.parametrize("validating", [False, True])
def test_deadline_keeps_completed_prefix_and_requeues_slow_suffix(
    library, settings, monkeypatch, validating, observation_clock, controlled_observations
):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = 1
    pool = controlled_observations
    if validating:
        cover_reviews.tick(batch_size=100)
        (library / "Other/beta (3)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    first = len(pool.tasks)

    def completed_prefix(futures):
        if not validating:
            pool.complete({future for future, _, _ in pool.tasks[first : first + 2]})
        observation_clock.now += cover_reviews.SLICE_SECONDS * 0.95

    pool.on_wait = completed_prefix
    cover_reviews.tick(batch_size=3)
    assert pool.tasks[-1][0].cancelled()
    assert pool.tasks[-1][2][1]()
    census.refresh_from_db()
    if validating:
        assert census.validation_cursor == 2 and census.cursor == 5
        assert entry("uuid-3").facts["width"] == 1000
    else:
        assert census.cursor == census.scanned == 2
        assert not CoverReviewEntry.objects.filter(book_uuid="uuid-3").exists()
    pool.on_wait = pool.complete
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and entry("uuid-3").facts["status"] == "known"


def test_executor_is_reused_and_explicitly_closed(library, settings, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = 2
    real = cover_reviews.ThreadPoolExecutor
    created = []

    def pool(**kwargs):
        result = real(**kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(cover_reviews, "ThreadPoolExecutor", pool)
    if hasattr(cover_reviews, "shutdown_observations"):
        cover_reviews.shutdown_observations()
    cover_reviews.tick(batch_size=2)
    cover_reviews.tick(batch_size=2)
    assert len(created) == 1
    cover_reviews.shutdown_observations()
    assert all(not thread.is_alive() for thread in created[0]._threads)


def test_deadline_cancels_queued_work_without_waiting_for_a_slow_thread(
    library, settings, monkeypatch, observation_clock, controlled_observations
):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    settings.COVER_CENSUS_OBSERVATION_WORKERS = 2
    pool = controlled_observations
    started = False

    def stalled(futures):
        nonlocal started
        if not started:
            pool.tasks[0][0].set_running_or_notify_cancel()
            started = True
        observation_clock.now += cover_reviews.SLICE_SECONDS

    pool.on_wait = stalled
    cover_reviews.tick(batch_size=5)
    assert len(pool.tasks) == 5
    assert not pool.tasks[0][0].done()
    assert all(future.cancelled() for future, _, _ in pool.tasks[1:])
    assert all(args[1]() for _, _, args in pool.tasks)
    assert not CoverReviewEntry.objects.exists()
    cover_reviews.tick(batch_size=5)
    assert len(pool.tasks) == 5
    census.refresh_from_db()
    assert census.state == "running" and census.cursor == census.scanned == 0
    pool.tasks[0][0].set_result(cover_reviews.cover_facts.unknown("inspection_failed"))
    pool.on_wait = pool.complete
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5


@pytest.mark.parametrize("fail", [False, True])
def test_worker_exit_closes_the_census_executor(monkeypatch, fail):
    from librarium.management.commands import inspection_worker

    command = inspection_worker.Command()
    closed = []

    def run(**kwargs):
        if fail:
            raise RuntimeError("synthetic worker exit")

    monkeypatch.setattr(command, "run_worker", run)
    monkeypatch.setattr(cover_reviews, "shutdown_observations", lambda: closed.append(True))
    if fail:
        with pytest.raises(RuntimeError, match="synthetic worker exit"):
            command.handle()
    else:
        command.handle()
    assert closed == [True]


@pytest.mark.parametrize("refresh", [False, True])
def test_unrelated_metadata_edit_does_not_block_skip_or_preview(library, client, refresh):
    fixture_covers(library)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((600, 900), art=True))
    library_read_model.refresh()
    start()
    drain()
    current = entry()
    update(library, "UPDATE books SET title='Unrelated edit' WHERE id=3")
    if refresh:
        library_read_model.refresh()
    assert client.get(f"{BASE}/{current.pk}/cover", REMOTE_USER="reviewer").status_code == 200
    assert (
        post(
            client,
            f"{BASE}/{current.pk}/skip",
            {
                "revision": current.revision,
                "skipped": True,
            },
        ).status_code
        == 200
    )


def test_skip_refuses_cover_replaced_since_observation(library, client):
    fixture_covers(library)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((600, 900), art=True))
    library_read_model.refresh()
    start()
    drain()
    current = entry()
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    assert (
        post(
            client,
            f"{BASE}/{current.pk}/skip",
            {
                "revision": current.revision,
                "skipped": True,
            },
        ).status_code
        == 409
    )
    current.refresh_from_db()
    assert current.state == "todo"


def test_rename_keeps_skip_revision_until_cover_changes(library, client):
    fixture_covers(library)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((600, 900), art=True))
    library_read_model.refresh()
    start()
    drain()
    current = entry()
    result = cover_reviews.set_skip(
        current.pk, current.revision, True, str(uuid.uuid4()), "reviewer"
    )
    (library / "Writer/Actual Book (1)").rename(library / "Writer/Renamed (1)")
    update(library, "UPDATE books SET title='Renamed',path='Writer/Renamed (1)' WHERE id=1")
    library_read_model.refresh()
    assert client.get(f"{BASE}/{current.pk}/cover", REMOTE_USER="reviewer").status_code == 200
    start()
    drain()
    current.refresh_from_db()
    assert current.title == "Renamed" and current.state == "skipped"
    assert not current.changed_since_skipped and current.revision == result["revision"]
    (library / "Writer/Renamed (1)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    start()
    drain()
    current.refresh_from_db()
    assert current.changed_since_skipped and current.revision > result["revision"]


def test_restored_uuid_in_the_same_library_inherits_skip(library):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    cover_reviews.set_skip(current.pk, current.revision, True, str(uuid.uuid4()), "reviewer")
    update(library, "DELETE FROM books WHERE id=2")
    library_read_model.refresh()
    start()
    drain()
    update(
        library,
        "INSERT INTO books(id,title,sort,path,uuid) VALUES(8,'Restored','Restored','Zola/Emile Story (2)','uuid-2')",
    )
    library_read_model.refresh()
    start()
    drain()
    current.refresh_from_db()
    assert current.present and current.state == "skipped" and current.calibre_id == 8
    assert not current.changed_since_skipped


@pytest.mark.parametrize("new_uuid", [None, "uuid-3"])
def test_invalidated_identity_leaves_queue(library, client, new_uuid):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    update(library, "UPDATE books SET uuid=? WHERE id=2", (new_uuid,))
    library_read_model.refresh()
    start()
    drain()
    current.refresh_from_db()
    assert not current.present
    if new_uuid:
        assert not entry("uuid-3").present
    result = client.get(BASE + "?reason=missing", REMOTE_USER="reviewer").json()
    assert str(current.pk) not in {row["id"] for row in result["entries"]}


def test_identity_issue_sample_is_bounded_with_exact_count(library):
    fixture_covers(library)
    update(
        library,
        """WITH RECURSIVE n(i) AS (SELECT 10 UNION ALL SELECT i+1 FROM n WHERE i<114)
        INSERT INTO books(id,title,sort,path,uuid)
        SELECT i,'Unknown','Unknown','Zola/Emile Story (2)',NULL FROM n""",
    )
    library_read_model.refresh()
    census = start()
    for _ in range(6):
        cover_reviews.tick(batch_size=100)
    census.refresh_from_db()
    assert census.state == "partial" and census.remaining == 0 and census.unresolved == 105
    data = cover_reviews.census_data(census)
    assert len(data["identity_issues"]) == 100 and data["identity_issue_count"] == 105


def test_census_reobserves_changed_earlier_cover_without_restarting(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    update(library, "UPDATE books SET title='Unrelated edit' WHERE id=3")
    cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.cursor == 4
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5
    assert entry().facts["width"] == 1100


def test_census_reconciles_insert_and_delete_before_its_cursor(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    update(library, "DELETE FROM books WHERE id=1")
    update(
        library,
        "INSERT INTO books(id,title,sort,path,uuid) VALUES(1,'New','New','Zola/Emile Story (2)','uuid-new')",
    )
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.total == census.scanned == 5
    assert entry("uuid-new").present and not entry("uuid-1").present


def test_metadata_snapshot_interruption_retries_with_the_same_cursor(library, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    update(library, "UPDATE books SET title='Changed' WHERE id=3")
    with monkeypatch.context() as patch:

        def interrupted(*args, **kwargs):
            raise library_read_model.ReadModelError("fixture interrupted snapshot")

        patch.setattr(library_read_model, "refresh", interrupted)
        cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.state == "running" and census.cursor == 2
    assert census.lease_token is None
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5 and census.error == ""


def test_edit_on_each_batch_cannot_starve_the_census(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    for i in range(10):
        update(library, "UPDATE books SET title=? WHERE id=3", (f"Edit {i}",))
        if not cover_reviews.tick(batch_size=2):
            break
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5


def test_cover_only_change_behind_cursor_is_checked_before_completion(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and entry().facts["width"] == 1100


@pytest.mark.parametrize("during_read", [False, True])
def test_stale_model_retries_and_completes_the_same_census(library, monkeypatch, during_read):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    token = library_read_model.LibraryReadModel.objects.get(pk=1).token
    with monkeypatch.context() as patch:
        patch.setattr(library_read_model, "_next_tick", float("inf"))
        if during_read:
            original = cover_reviews.source_facts

            def stale(*args, **kwargs):
                result = original(*args, **kwargs)
                library_read_model.refused(token)
                return result

            patch.setattr(cover_reviews, "source_facts", stale)
        else:
            update(library, "UPDATE books SET title='Changed' WHERE id=3")
            library_read_model.refused(token)
        cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.state == "running" and census.cursor == 2 and census.scanned == 2
    assert census.error == "unavailable" and census.finished_at is None
    assert census.lease_token is None and census.lease_until is None
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 5 and census.error == ""
    assert cover_reviews.start(str(census.request_key)).pk == census.pk
    assert CoverCensus.objects.count() == 1


def test_library_uuid_change_still_ends_the_census(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=2)
    update(library, "UPDATE library_id SET uuid='different-library'")
    cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.state == "partial" and census.error == "inventory_changed"
    assert census.cursor == 2 and census.finished_at is not None


def test_validation_resumes_within_the_slice_budget(library, monkeypatch):
    from types import SimpleNamespace

    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=100)
    (library / "Writer/Unicode (5)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    original = cover_reviews.source_signature
    clock, checked, seen = [0.0], [], set()

    def slow_stat(book):
        checked.append(book.pk)
        result = original(book)
        if book.pk not in seen:
            seen.add(book.pk)
            clock[0] += cover_reviews.SLICE_SECONDS * 0.6
        return result

    monkeypatch.setattr(cover_reviews, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(cover_reviews, "source_signature", slow_stat)
    for expected in [2, 4, 5]:
        seen.clear()
        before = len(checked)
        cover_reviews.tick(batch_size=100)
        census.refresh_from_db()
        assert 0 < len(checked) - before <= 2
        assert census.validation_cursor == expected and census.cursor == 5
        assert census.state == "running" and census.lease_token is None
    drain()
    census.refresh_from_db()
    assert checked == [1, 2, 3, 4, 5, 5]  # Changed cover is checked again before publication.
    assert census.state == "complete" and census.scanned == 5
    assert entry("uuid-5").facts["width"] == 1100


def test_validation_revisits_an_earlier_cover_after_inventory_refresh(library):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=100)
    cover_reviews.tick(batch_size=2)
    census.refresh_from_db()
    assert census.validation_cursor == 2
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1300), art=True))
    update(library, "UPDATE books SET title='Changed' WHERE id=3")
    drain()
    census.refresh_from_db()
    assert census.state == "complete" and entry().facts["width"] == 1100


def test_unchanged_completion_keeps_queue_and_skip_available(library, client, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    cover_reviews.tick(batch_size=100)
    original = library_read_model.observe

    def observe():
        assert client.get(BASE, REMOTE_USER="reviewer").status_code == 200
        current = entry("uuid-2")
        assert (
            post(
                client,
                f"{BASE}/{current.pk}/skip",
                {
                    "revision": current.revision,
                    "skipped": True,
                },
            ).status_code
            == 200
        )
        return original()

    monkeypatch.setattr(library_read_model, "observe", observe)
    before = library_read_model.LibraryReadModel.objects.get(pk=1).imported_at
    drain()
    census.refresh_from_db()
    assert census.state == "complete"
    assert library_read_model.LibraryReadModel.objects.get(pk=1).imported_at == before
    assert client.get(BASE, REMOTE_USER="reviewer").status_code == 200
    current = entry("uuid-2")
    assert (
        post(
            client, f"{BASE}/{current.pk}/skip", {"revision": current.revision, "skipped": True}
        ).status_code
        == 200
    )


@pytest.mark.django_db(transaction=True)
def test_unresolved_skip_verifies_outside_transaction(library, monkeypatch):
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-5")
    original = cover_reviews.cover_facts.inspect_cover
    observations = []

    def decode(raw):
        observations.append(connection.in_atomic_block)
        return original(raw)

    monkeypatch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
    result = cover_reviews.set_skip(
        current.pk, current.revision, True, str(uuid.uuid4()), "reviewer"
    )
    assert result["state"] == "skipped"
    assert observations == [False]


@pytest.mark.django_db(transaction=True)
def test_publish_proceeds_during_skip_decode(library, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections

    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-5")
    census = start()
    lease = uuid.uuid4()
    CoverCensus.objects.filter(pk=census.pk).update(state="running", lease_token=lease)
    book = library_read_model.CalibreBook.objects.get(pk=5)
    decoding, release = Event(), Event()
    original = cover_reviews.cover_facts.inspect_cover

    def decode(raw):
        decoding.set()
        assert release.wait(10)
        return original(raw)

    def skip():
        close_old_connections()
        try:
            return cover_reviews.set_skip(
                current.pk, current.revision, True, str(uuid.uuid4()), "reviewer"
            )
        finally:
            close_old_connections()

    def publish():
        close_old_connections()
        try:
            return cover_reviews.publish(
                census.pk, lease, book, current.facts, current.source_signature
            )
        finally:
            close_old_connections()

    monkeypatch.setattr(cover_reviews.cover_facts, "inspect_cover", decode)
    with ThreadPoolExecutor(max_workers=2) as pool:
        skipping = pool.submit(skip)
        try:
            assert decoding.wait(5)
            publishing = pool.submit(publish)
            assert publishing.result(timeout=2)
        finally:
            release.set()
        assert skipping.result(timeout=10)["state"] == "skipped"


def test_failed_imports_respect_refresh_interval(library, settings, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    settings.LIBRARY_READ_MODEL_SECONDS = 30
    from types import SimpleNamespace

    update(library, "UPDATE books SET title='Changed' WHERE id=3")
    token = library_read_model.current_token()
    clock = [100.0]
    monkeypatch.setattr(library_read_model, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(library_read_model, "current_token", lambda: token)
    attempts = []

    def oversized():
        attempts.append(clock[0])
        raise library_read_model.ReadModelError("fixture oversize import")

    monkeypatch.setattr(library_read_model, "observe", oversized)
    for now in [100.0, 100.5, 101.0, 129.9, 130.0]:
        clock[0] = now
        cover_reviews.tick()
    assert attempts == [100.0, 130.0]
    census.refresh_from_db()
    assert census.state == "running" and census.error == "unavailable"


@pytest.mark.parametrize("unavailable", ["disabled", "stale"])
def test_unavailable_model_has_an_accurate_census_error(library, settings, unavailable):
    fixture_covers(library)
    library_read_model.refresh()
    census = start()
    if unavailable == "disabled":
        settings.LIBRARY_READ_MODEL = "off"
    else:
        settings.LIBRARY_READ_MODEL_SECONDS = 30
        library_read_model._next_tick = float("inf")
        library_read_model.LibraryReadModel.objects.filter(pk=1).update(stale=True)
    cover_reviews.tick()
    census.refresh_from_db()
    assert census.state == "running" and census.error == "unavailable"
    assert census.lease_token is None


def test_entries_do_not_advertise_an_unused_inventory_token(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    response = client.get(BASE, REMOTE_USER="reviewer")
    assert response.status_code == 200
    assert response.json()["inventory"]
    assert all("inventory" not in row for row in response.json()["entries"])


@pytest.mark.django_db(transaction=True)
def test_skip_waits_for_a_busy_snapshot_before_taking_locks(library, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import BoundedSemaphore, Event

    from django.db import close_old_connections
    from librarium import direct_library

    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    slots = BoundedSemaphore(1)
    slots.acquire()
    attempting = Event()

    class ReaderSlots:
        def acquire(self, *, blocking=True, timeout=None):
            if blocking:
                attempting.set()
                return slots.acquire(timeout=timeout)
            result = slots.acquire(blocking=False)
            attempting.set()
            return result

        def release(self):
            slots.release()

    def skip():
        close_old_connections()
        try:
            return cover_reviews.set_skip(
                current.pk, current.revision, True, str(uuid.uuid4()), "reviewer"
            )
        finally:
            close_old_connections()

    monkeypatch.setattr(direct_library, "SLOTS", ReaderSlots())
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(skip)
        try:
            assert attempting.wait(5)
        finally:
            slots.release()
        assert result.result(timeout=10)["state"] == "skipped"


@pytest.mark.parametrize("changed", ["cover", "identity"])
def test_skip_rechecks_stats_after_preflight(library, monkeypatch, changed):
    from contextlib import contextmanager

    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry()
    original = cover_reviews.current_entry

    @contextmanager
    def replaced(*args, **kwargs):
        with original(*args, **kwargs) as result:
            yield result
        if changed == "cover":
            (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((1100, 1300)))
        else:
            update(library, "UPDATE books SET uuid='replacement' WHERE id=1")

    monkeypatch.setattr(cover_reviews, "current_entry", replaced)
    with pytest.raises(cover_reviews.ReviewError, match="changed"):
        cover_reviews.set_skip(current.pk, current.revision, True, str(uuid.uuid4()), "reviewer")
    current.refresh_from_db()
    assert current.state == "todo" and current.revision == 1


def test_concurrent_request_key_replays_after_an_initial_cache_miss(library, monkeypatch):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    current = entry("uuid-2")
    key = str(uuid.uuid4())
    original = cover_reviews.replay
    winner = []
    interleaved = False

    def replay(*args):
        nonlocal interleaved
        result = original(*args)
        if result is None and not interleaved:
            interleaved = True
            winner.append(
                cover_reviews.set_skip(current.pk, current.revision, True, key, "reviewer")
            )
        return result

    monkeypatch.setattr(cover_reviews, "replay", replay)
    result = cover_reviews.set_skip(current.pk, current.revision, True, key, "reviewer")
    assert result == winner[0] and result["revision"] == 2


def test_interrupted_import_retains_the_inventory_changed_error(library, monkeypatch):
    from librarium import direct_library

    library_read_model.refresh()
    census = start()
    update(library, "UPDATE books SET title='Changed' WHERE id=3")

    def interrupted():
        raise direct_library.changed()

    monkeypatch.setattr(library_read_model, "observe", interrupted)
    cover_reviews.tick()
    census.refresh_from_db()
    assert census.state == "running" and census.error == "inventory_changed"


def test_wall_counts_authors_and_reason_order_are_global(library, client):
    fixture_covers(library)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((500, 800), art=True))
    (library / "Other/beta (3)/cover.jpg").write_bytes(
        jpeg((600, 900), comment=b"Generated cover: calibre 7.10")
    )
    library_read_model.refresh()
    start()
    drain()
    data = client.get(BASE, REMOTE_USER="reviewer").json()
    assert [row["book_id"] for row in data["entries"]] == ["2", "4", "3", "1"]
    assert data["entries"][0]["authors"] == ["Émile Author"]
    assert data["counts"] == {"todo": 4, "done": 0, "skipped": 0}
    filtered = client.get(BASE + "?reason=missing", REMOTE_USER="reviewer").json()
    assert filtered["counts"] == data["counts"] and filtered["total"] == 2


def test_done_means_a_previously_flagged_cover_now_passes_census(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    missing = entry("uuid-2")
    assert missing.state == "todo"

    (library / "Zola/Emile Story (2)/cover.jpg").write_bytes(jpeg(art=True))
    library_read_model.refresh(force=True)
    start()
    drain()
    done = client.get(BASE + "?state=done", REMOTE_USER="reviewer").json()
    assert [row["book_uuid"] for row in done["entries"]] == ["uuid-2"]
    assert done["counts"] == {"todo": 1, "done": 1, "skipped": 0}
    (library / "Zola/Emile Story (2)/cover.jpg").unlink()
    library_read_model.refresh(force=True)
    start()
    drain()
    missing.refresh_from_db()
    assert missing.state == "todo"


def test_hidden_healthy_cover_cannot_be_skipped_or_unskipped_into_done(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    healthy = entry()
    assert healthy.facts["reasons"] == [] and healthy.state == "todo"
    for skipped in (True, False):
        reply = post(
            client, f"{BASE}/{healthy.pk}/skip", {"revision": healthy.revision, "skipped": skipped}
        )
        assert reply.status_code == 409
        healthy.refresh_from_db()
        assert healthy.state == "todo" and healthy.revision == 1
    done = client.get(BASE + "?state=done", REMOTE_USER="reviewer").json()
    assert done["entries"] == [] and done["counts"]["done"] == 0


def test_unskip_a_previously_flagged_cover_can_follow_a_healthy_census(library, client):
    fixture_covers(library)
    library_read_model.refresh()
    start()
    drain()
    missing = entry("uuid-2")
    assert (
        post(
            client, f"{BASE}/{missing.pk}/skip", {"revision": missing.revision, "skipped": True}
        ).status_code
        == 200
    )
    (library / "Zola/Emile Story (2)/cover.jpg").write_bytes(jpeg(art=True))
    start()
    drain()
    missing.refresh_from_db()
    assert missing.state == "skipped" and not missing.facts["reasons"]
    result = post(
        client, f"{BASE}/{missing.pk}/skip", {"revision": missing.revision, "skipped": False}
    )
    assert result.status_code == 200 and result.json()["state"] == "done"


def test_queue_exposes_recorded_isbn_for_initial_cover_search(library, client):
    fixture_covers(library)
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(jpeg((600, 900), art=True))
    library_read_model.refresh()
    start()
    drain()
    reply = client.get(BASE, REMOTE_USER="reviewer")
    assert reply.status_code == 200
    row = next(r for r in reply.json()["entries"] if r["book_uuid"] == "uuid-1")
    assert row["isbn"] == "9780306406157"
