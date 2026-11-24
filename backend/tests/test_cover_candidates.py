"""Local catalogue admission and persisted choices never call a library writer."""

import hashlib
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from librarium import library_read_model
from tests.test_catalogue_covers import covers as covers_fixture
from tests.test_cover_facts import jpeg
from tests.test_cover_suggestions import page as page_fixture
from tests.test_library_read_model import library as library_fixture
from tests.test_library_read_model import update

pytestmark = pytest.mark.django_db
covers = covers_fixture
library = library_fixture
page = page_fixture


@pytest.fixture(autouse=True)
def isolated_admission_cache():
    from librarium import cover_candidates

    cover_candidates._ADMISSION.clear()
    yield
    cover_candidates._ADMISSION.clear()


def store(covers, settings, *, enhanced_width=1000, original=None):
    original = original or jpeg((315, 508), art=True)
    derivative = jpeg((enhanced_width, 1600), art=True)
    original_sha, derivative_sha = (
        hashlib.sha256(raw).hexdigest() for raw in (original, derivative)
    )
    settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR = str(
        covers[1].parent.parent.parent / "enhanced"
    )
    for root, digest, raw in (
        (settings.LIBRARIUM_CATALOGUE_COVER_DIR, original_sha, original),
        (settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR, derivative_sha, derivative),
    ):
        target = Path(root) / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute(
            "UPDATE work_cover SET sha256=?,width=315,height=508,media_type='image/jpeg'",
            (original_sha,),
        )
        db.execute(
            "INSERT INTO cover_derivative VALUES(?, 'realesrgan-x4plus-v1', ?, ?, 1600, 'image/jpeg', '2026-11-11')",
            (original_sha, derivative_sha, enhanced_width),
        )
    return original_sha, derivative_sha


def request(page, client):
    params, queue = page
    entry = next(e for e in queue["entries"] if e["book_id"] == "1")
    pin = client.get("/api/catalogue").json()
    return f"/api/cover-reviews/{entry['id']}/choices", {
        "revision": entry["revision"],
        "inventory": params["inventory"],
        "version": pin["version"],
        "sha256": pin["sha256"],
    }


def choose(client, url, params, data, candidate=None, key=None):
    return client.post(
        url,
        {
            **params,
            "candidate_id": candidate or data["default_candidate_id"],
            "selection_id": data["selection"]["id"] if data["selection"] else None,
        },
        content_type="application/json",
        REMOTE_USER="reviewer",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


def test_original_and_enhanced_default_are_real_verified_local_choices(
    page, covers, settings, client
):
    original, enhanced = store(covers, settings)
    url, params = request(page, client)
    reply = client.get(url, params, REMOTE_USER="reviewer")
    assert reply.status_code == 200
    data = reply.json()
    assert [c["label"] for c in data["candidates"]] == ["Enhanced", "Original"]
    assert [c["sha256"] for c in data["candidates"]] == [enhanced, original]
    assert data["default_candidate_id"] == data["candidates"][0]["id"]
    assert data["candidates"][1]["width"] == 315
    assert data["candidates"][1]["selectable"]
    assert data["source"]["status"] == "complete"
    assert reply["Cache-Control"] == "no-store"


@pytest.mark.parametrize("width,default", [(999, "Original"), (1000, "Enhanced")])
def test_enhanced_default_width_floor_is_strict(page, covers, settings, client, width, default):
    store(covers, settings, enhanced_width=width)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert (
        next(c["label"] for c in data["candidates"] if c["id"] == data["default_candidate_id"])
        == default
    )


def test_selection_survives_reload_and_unrelated_catalogue_refresh(page, covers, settings, client):
    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    key = str(uuid.uuid4())
    saved = choose(client, url, params, data, key=key)
    assert saved.status_code == 201
    assert choose(client, url, params, data, key=key).json() == saved.json()
    assert saved.json()["selection"]["status"] == "awaiting_approval"
    assert (
        client.get(url, params, REMOTE_USER="reviewer").json()["selection"]
        == saved.json()["selection"]
    )
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work SET synopsis='Unrelated editorial update'")
    _, refreshed = request(page, client)
    assert (
        client.get(url, refreshed, REMOTE_USER="reviewer").json()["selection"]
        == saved.json()["selection"]
    )
    queue = client.get("/api/cover-reviews", REMOTE_USER="reviewer").json()
    entry = next(e for e in queue["entries"] if e["book_id"] == "1")
    assert entry["state"] == "todo" and entry["selection_pending"]


@pytest.mark.parametrize(
    "damage", ["absent", "corrupt", "mismatch", "relation", "placeholder", "old_snapshot"]
)
def test_bad_original_never_admits_its_derivative(page, covers, settings, client, damage):
    original, _ = store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        if damage == "relation":
            db.execute("UPDATE cover_derivative SET original_sha256=?", ("f" * 64,))
        if damage == "placeholder":
            db.execute(
                "UPDATE work_cover SET source_url='https://wh40k.lexicanum.com/wiki/Special:FilePath/No_Cover.jpg'"
            )
        if damage == "old_snapshot":
            db.execute("DROP TABLE work_cover")
        if damage == "mismatch":
            db.execute("UPDATE work_cover SET width=999")
    target = Path(settings.LIBRARIUM_CATALOGUE_COVER_DIR) / original[:2] / original
    if damage == "absent":
        target.unlink()
    if damage == "corrupt":
        target.write_bytes(b"bad pixels")
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    if damage == "relation":
        assert [c["label"] for c in data["candidates"]] == ["Original"]
    else:
        assert not any(c["selectable"] for c in data["candidates"])
    assert data["default_candidate_id"] is None or damage == "relation"


def test_stale_pin_revision_candidate_and_cross_device_save_refuse(page, covers, settings, client):
    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data, candidate=str(uuid.uuid4())).status_code == 409
    assert choose(client, url, {**params, "sha256": "f" * 64}, data).status_code == 409
    assert choose(client, url, {**params, "revision": 999}, data).status_code == 409
    assert choose(client, url, params, data).status_code == 201
    assert choose(client, url, params, data).status_code == 409


def test_identity_or_current_cover_change_refuses_old_selection(
    page, covers, settings, client, library
):
    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data).status_code == 201
    update(library, "UPDATE books SET uuid='reused-id' WHERE id=1")
    library_read_model.refresh()
    assert client.get(url, params, REMOTE_USER="reviewer").status_code == 409


def test_choices_require_authentication(page, client):
    url, params = request(page, client)
    assert client.get(url, params).status_code == 401


@pytest.mark.parametrize(
    "case", ["disputed_isbn", "collection", "missing_work", "ambiguous", "merged_work"]
)
def test_nonexact_or_disputed_identity_has_no_selectable_art(
    page, covers, settings, client, library, case
):
    store(covers, settings)
    if case in {"disputed_isbn", "collection"}:
        update(library, "INSERT INTO identifiers(book,type,val) VALUES(1,'isbn','9780306406157')")
        library_read_model.refresh()
        page[0]["inventory"] = client.get("/api/cover-reviews", REMOTE_USER="reviewer").json()[
            "inventory"
        ]
    with closing(sqlite3.connect(covers[0])) as db, db:
        if case == "disputed_isbn":
            db.execute(
                "INSERT INTO edition(id,work_id,isbn13) VALUES('e_fixture','w_fixture','9780306406157')"
            )
            db.execute(
                "INSERT INTO edition_ident VALUES('e_fixture','isbn13','9780306406157','disputed')"
            )
        elif case == "collection":
            db.execute(
                "UPDATE work SET title='A Different Collection',type='omnibus' WHERE id='w_fixture'"
            )
            db.execute(
                "INSERT INTO edition(id,work_id,isbn13) VALUES('e_fixture','w_fixture','9780306406157')"
            )
        elif case == "missing_work":
            db.execute("DELETE FROM work WHERE id='w_fixture'")
        elif case == "merged_work":
            db.execute("DELETE FROM work WHERE id='w_fixture'")
            db.execute("INSERT INTO id_alias VALUES('w_fixture','missing')")
        else:
            db.execute("INSERT INTO work(id,title) VALUES('other','Fixture Cover')")
            db.execute("INSERT INTO work_author VALUES('other',1,'author')")
    url, params = request(page, client)
    result = client.get(url, params, REMOTE_USER="reviewer")
    assert result.status_code == 200
    data = result.json()
    assert data["default_candidate_id"] is None
    assert not any(c["selectable"] for c in data["candidates"])
    if case in {"collection", "disputed_isbn", "ambiguous"}:
        assert data["candidates"] and "Not selectable" in data["candidates"][0]["reason"]
        assert (
            choose(client, url, params, data, candidate=data["candidates"][0]["id"]).status_code
            == 409
        )


@pytest.mark.parametrize("damage", ["pipeline", "original", "width", "policy"])
def test_saved_choice_is_refused_when_evidence_changes(page, covers, settings, client, damage):
    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    saved = choose(client, url, params, data)
    assert saved.status_code == 201
    if damage == "policy":
        from librarium import cover_candidates

        # A policy upgrade invalidates old bindings and candidate identities.
        cover_candidates_policy = cover_candidates.POLICY
        try:
            cover_candidates.POLICY = "librarium.cover-choice.v2"
            assert (
                client.get(url, params, REMOTE_USER="reviewer").json()["selection"]["status"]
                == "stale"
            )
        finally:
            cover_candidates.POLICY = cover_candidates_policy
        return
    with closing(sqlite3.connect(covers[0])) as db, db:
        if damage == "pipeline":
            db.execute("UPDATE cover_derivative SET pipeline='a different method'")
        if damage == "original":
            db.execute("UPDATE cover_derivative SET original_sha256=?", ("f" * 64,))
        if damage == "width":
            db.execute("UPDATE cover_derivative SET width=999")
    _, params = request(page, client)
    stale = client.get(url, params, REMOTE_USER="reviewer").json()["selection"]
    assert stale["status"] == "stale" and "changed" in stale["reason"]


def test_new_current_cover_requires_new_choice_even_after_census(
    page, covers, settings, client, library
):
    from librarium.models import CoverReviewEntry
    from tests.test_cover_reviews import drain, start

    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data).status_code == 201
    row = CoverReviewEntry.objects.get(pk=data["entry_id"])
    from librarium import direct_library

    with direct_library.snapshot() as (db, _root, _):
        record = direct_library.record(db, str(row.calibre_id))
    (library / record["path"] / "cover.jpg").write_bytes(jpeg((600, 900), art=True))
    assert client.get(url, params, REMOTE_USER="reviewer").status_code == 409
    library_read_model.refresh()
    start()
    drain()
    queue = client.get("/api/cover-reviews", REMOTE_USER="reviewer").json()
    entry = next(e for e in queue["entries"] if e["book_id"] == "1")
    params.update(revision=entry["revision"], inventory=queue["inventory"])
    stale = client.get(url, params, REMOTE_USER="reviewer").json()["selection"]
    assert stale["status"] == "stale" and "current cover changed" in stale["reason"]


def test_selection_is_app_owned_only_and_does_not_change_library_or_catalogue(
    page, covers, settings, client, library
):
    store(covers, settings)
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for root in (
            library,
            covers[0].parent,
            Path(settings.LIBRARIUM_CATALOGUE_COVER_DIR),
            Path(settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR),
        )
        for p in root.rglob("*")
        if p.is_file()
    }
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data).status_code == 201
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in before.items())


@pytest.mark.parametrize("case", ["extra", "bad_revision", "duplicate", "nonjson", "overlong"])
def test_strict_choice_http_parameters(page, client, case):
    url, params = request(page, client)
    if case == "extra":
        result = client.get(
            url, {**params, "work_id": "caller-selected-work"}, REMOTE_USER="reviewer"
        )
    elif case == "bad_revision":
        result = client.get(url, {**params, "revision": "01"}, REMOTE_USER="reviewer")
    elif case == "duplicate":
        result = client.get(url, {**params, "revision": ["1", "1"]}, REMOTE_USER="reviewer")
    elif case == "nonjson":
        result = client.post(url, "{}", content_type="text/plain", REMOTE_USER="reviewer")
    else:
        result = client.post(
            url, " " * 4097, content_type="application/json", REMOTE_USER="reviewer"
        )
    assert result.status_code in {400, 413, 415}


def test_selection_http_keeps_csrf_boundary(page, covers, settings, client):
    from django.test import Client

    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    secured = Client(enforce_csrf_checks=True)
    assert choose(secured, url, params, data).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_populated_upgrade_preserves_cover_review_and_is_reversible():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    prior = [("librarium", "0013_cover_census")]
    current = [("librarium", "0014_prepared_cover")]
    try:
        executor.migrate(prior)
        old = executor.loader.project_state(prior).apps
        entry = old.get_model("librarium", "CoverReviewEntry").objects.create(
            library_uuid="fixture-library",
            book_uuid="fixture-book",
            calibre_id=42,
            title="Synthetic retained review",
            facts={"status": "known", "reasons": ["missing"]},
            revision=3,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        from librarium.models import CoverReviewEntry, PreparedCover

        assert CoverReviewEntry.objects.get(pk=entry.pk).revision == 3
        assert not PreparedCover.objects.exists()
        executor = MigrationExecutor(connection)
        executor.migrate(prior)
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        assert CoverReviewEntry.objects.get(pk=entry.pk).title == "Synthetic retained review"
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.parametrize("damage", ["truncated_pixels", "blank", "generated"])
def test_real_decoder_refuses_placeholder_or_corrupt_original_before_derivative(
    page, covers, settings, client, damage
):
    raw = jpeg((315, 508), art=True)
    if damage == "truncated_pixels":
        raw = raw[: len(raw) // 2]
    if damage == "blank":
        raw = jpeg((315, 508), blank=True)
    if damage == "generated":
        raw = jpeg((315, 508), comment=b"Generated cover: calibre 7")
    store(covers, settings, original=raw)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert data["candidates"] == [] and data["source"]["status"] == "unavailable"


def test_unresolved_current_cover_can_compare_but_cannot_record_a_choice(
    page, covers, settings, client, library
):
    from librarium import direct_library
    from tests.test_cover_reviews import drain, start

    store(covers, settings)
    with direct_library.snapshot() as (db, _root, _):
        record = direct_library.record(db, "1")
    (library / record["path"] / "cover.jpg").write_bytes(b"corrupt current image")
    library_read_model.refresh()
    start()
    drain()
    queue = client.get("/api/cover-reviews", REMOTE_USER="reviewer").json()
    entry = next(e for e in queue["entries"] if e["book_id"] == "1")
    url, params = request((page[0], queue), client)
    params["inventory"] = queue["inventory"]
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert entry["facts"]["status"] == "unresolved" and data["candidates"]
    result = choose(client, url, params, data)
    assert (
        result.status_code == 409 and "current cover could not be checked" in result.json()["error"]
    )


def test_placeholder_digest_association_blocks_relabelled_original_and_derivative(
    page, covers, settings, client
):
    original, _ = store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute(
            "INSERT INTO cover_asset VALUES('https://wh40k.lexicanum.com/wiki/Special:FilePath/No_Cover.jpg',?,315,508,'image/jpeg')",
            (original,),
        )
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert not data["candidates"] and data["source"]["status"] == "unavailable"


@pytest.mark.parametrize("operation", ["choices", "save"])
def test_art_inspection_releases_library_snapshot_and_revalidates(
    page, covers, settings, client, monkeypatch, operation
):
    from contextlib import contextmanager

    from librarium import cover_candidates, cover_facts, direct_library

    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    snapshot = direct_library.snapshot
    inspect = cover_facts.inspect_cover
    import time
    from types import SimpleNamespace

    active = 0
    elapsed = 0
    inspections = []
    monkeypatch.setattr(
        direct_library, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + elapsed)
    )

    @contextmanager
    def tracked_snapshot(*args, **kwargs):
        nonlocal active
        with snapshot(*args, **kwargs) as value:
            active += 1
            try:
                yield value
            finally:
                active -= 1

    def check(raw):
        nonlocal elapsed
        assert active == 0, "Catalogue decoding held the library snapshot"
        inspections.append(raw)
        result = inspect(raw)
        elapsed += 4.0
        return result

    cover_candidates._ADMISSION.clear()
    monkeypatch.setattr(direct_library, "snapshot", tracked_snapshot)
    monkeypatch.setattr(cover_facts, "inspect_cover", check)
    result = (
        choose(client, url, params, data)
        if operation == "save"
        else client.get(url, params, REMOTE_USER="reviewer")
    )
    assert result.status_code in {200, 201}
    assert inspections


@pytest.mark.parametrize("change", ["metadata", "cover"])
def test_changes_during_inspection_are_refused(
    page, covers, settings, client, library, monkeypatch, change
):
    from librarium import cover_candidates, cover_facts, direct_library

    store(covers, settings)
    url, params = request(page, client)
    inspect = cover_facts.inspect_cover
    with direct_library.snapshot() as (db, _, _):
        path = direct_library.record(db, "1")["path"]

    def check(raw):
        result = inspect(raw)
        if change == "metadata":
            update(library, "UPDATE books SET title='Changed during check' WHERE id=1")
        else:
            (library / path / "cover.jpg").write_bytes(b"changed")
        return result

    cover_candidates._ADMISSION.clear()
    monkeypatch.setattr(cover_facts, "inspect_cover", check)
    assert client.get(url, params, REMOTE_USER="reviewer").status_code == 409


@pytest.mark.parametrize("variant", ["original", "enhanced"])
@pytest.mark.parametrize("operation", ["choices", "save"])
def test_transient_decoder_failure_is_retryable_and_not_cached(
    page, covers, settings, client, monkeypatch, variant, operation
):
    from librarium import cover_candidates, cover_facts
    from librarium.models import PreparedCover

    original, enhanced = store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    inspect = cover_facts.inspect_cover
    unavailable = True

    def check(raw):
        if unavailable and hashlib.sha256(raw).hexdigest() == (
            original if variant == "original" else enhanced
        ):
            return cover_facts.unknown("inspection_failed", hashlib.sha256(raw).hexdigest())
        return inspect(raw)

    cover_candidates._ADMISSION.clear()
    monkeypatch.setattr(cover_facts, "inspect_cover", check)
    result = (
        choose(client, url, params, data)
        if operation == "save"
        else client.get(url, params, REMOTE_USER="reviewer")
    )
    assert result.status_code == 503
    assert result.json()["code"] == "inspection_unavailable"
    assert "couldn't check the catalogue right now" in result.json()["error"]
    assert not PreparedCover.objects.exists()
    unavailable = False
    assert client.get(url, params, REMOTE_USER="reviewer").status_code == 200


def test_unselectable_candidates_are_not_decoded(page, covers, settings, client, monkeypatch):
    from librarium import cover_facts

    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES('other','Fixture Cover')")
        db.execute("INSERT INTO work_author VALUES('other',1,'author')")
    url, params = request(page, client)

    def forbidden(raw):
        raise AssertionError("Unselectable art was decoded")

    monkeypatch.setattr(cover_facts, "inspect_cover", forbidden)
    result = client.get(url, params, REMOTE_USER="reviewer")
    assert result.status_code == 200 and result.json()["candidates"]
    assert not any(c["selectable"] for c in result.json()["candidates"])


def test_verified_content_is_decoded_once_across_reads_and_save_but_rechecks_bytes(
    page, covers, settings, client, monkeypatch
):
    from librarium import cover_candidates, cover_facts

    original, _ = store(covers, settings)
    url, params = request(page, client)
    inspect = cover_facts.inspect_cover
    calls = []

    def check(raw):
        calls.append(hashlib.sha256(raw).hexdigest())
        return inspect(raw)

    cover_candidates._ADMISSION.clear()
    monkeypatch.setattr(cover_facts, "inspect_cover", check)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert client.get(url, params, REMOTE_USER="reviewer").status_code == 200
    assert choose(client, url, params, data).status_code == 201
    assert len(calls) == len(set(calls)) == 2
    target = Path(settings.LIBRARIUM_CATALOGUE_COVER_DIR) / original[:2] / original
    target.write_bytes(b"replaced despite cached hash")
    assert not client.get(url, params, REMOTE_USER="reviewer").json()["candidates"]


@pytest.mark.parametrize(
    "source,name",
    [("https://images.example.org/front.jpg", "images.example.org"), ("", "Recorded source")],
)
def test_source_name_comes_from_recorded_url(page, covers, settings, client, source, name):
    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("UPDATE work_cover SET source_url=?", (source,))
    url, params = request(page, client)
    assert (
        client.get(url, params, REMOTE_USER="reviewer").json()["candidates"][0]["source_name"]
        == name
    )


def test_missing_source_row_is_unavailable_not_an_invalid_request(monkeypatch):
    from unittest.mock import Mock

    from librarium import catalogue_covers, cover_candidates

    db = Mock()
    db.execute.return_value.fetchone.return_value = None
    monkeypatch.setattr(catalogue_covers, "metadata", lambda *a, **kw: {"sha256": "a" * 64})
    choices, reason = cover_candidates.work_choices(db, {}, {"work_id": "w_fixture"}, True)
    assert choices == [] and "source" in reason.lower() and "unavailable" in reason.lower()


@pytest.mark.parametrize(
    "damage", ["title", "author", "identifiers", "artwork", "pipeline", "policy"]
)
def test_wall_rechecks_full_selection_binding(
    page, covers, settings, client, library, damage, monkeypatch
):
    from librarium import cover_candidates

    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data).status_code == 201
    if damage == "policy":
        monkeypatch.setattr(cover_candidates, "POLICY", "librarium.cover-choice.v2")
    elif damage in {"title", "author", "identifiers"}:
        sql = {
            "title": "UPDATE books SET title='Changed title' WHERE id=1",
            "author": "UPDATE authors SET name='Another Writer'",
            "identifiers": "INSERT INTO identifiers(book,type,val) VALUES(1,'isbn','9780306406157')",
        }[damage]
        update(library, sql)
        library_read_model.refresh()
    else:
        with closing(sqlite3.connect(covers[0])) as db, db:
            db.execute(
                "DELETE FROM work_cover"
                if damage == "artwork"
                else "UPDATE cover_derivative SET pipeline='different'"
            )
    result = client.get("/api/cover-reviews", REMOTE_USER="reviewer")
    assert result.status_code == 200
    row = next(e for e in result.json()["entries"] if e["book_id"] == "1")
    assert row["selection_pending"] is False


def test_wall_reads_saved_selections_once_for_the_whole_page(page, client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        result = client.get("/api/cover-reviews", REMOTE_USER="reviewer")
    assert result.status_code == 200 and len(result.json()["entries"]) > 1
    selects = [q["sql"] for q in queries if 'FROM "librarium_preparedcover"' in q["sql"]]
    assert len(selects) == 1


def test_wall_discards_pending_status_if_catalogue_changes_after_validation(
    page, covers, settings, client, monkeypatch
):
    from contextlib import contextmanager

    from librarium import catalogue

    store(covers, settings)
    url, params = request(page, client)
    data = client.get(url, params, REMOTE_USER="reviewer").json()
    assert choose(client, url, params, data).status_code == 201
    snapshot = catalogue.snapshot

    @contextmanager
    def changed_snapshot(*args, **kwargs):
        with snapshot(*args, **kwargs) as value:
            yield value
        raise catalogue.CatalogueError("Snapshot changed", 409)

    monkeypatch.setattr(catalogue, "snapshot", changed_snapshot)
    result = client.get("/api/cover-reviews", REMOTE_USER="reviewer")
    assert result.status_code == 200
    row = next(e for e in result.json()["entries"] if e["book_id"] == "1")
    assert row["selection_pending"] is False
