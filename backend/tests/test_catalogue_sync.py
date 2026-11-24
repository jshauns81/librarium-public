"""Publication must wait for the exact snapshot's complete verified cover set."""

import hashlib
import importlib.util
import io
import json
import sqlite3
from contextlib import closing
from urllib.error import HTTPError, URLError

import pytest
import test_catalogue_covers as art


def test_worker_sync_is_available():
    assert importlib.util.find_spec("librarium.catalogue_sync") is not None


class Reply(io.BytesIO):
    status = 200

    def __init__(self, raw, media_type="image/png", **headers):
        super().__init__(raw)
        self.headers = {"Content-Type": media_type, "Content-Length": str(len(raw)), **headers}

    read1 = io.BytesIO.read


@pytest.fixture
def sync(tmp_path, settings, monkeypatch):
    from librarium import catalogue_status, catalogue_sync

    root = tmp_path / "catalogue"
    root.mkdir()
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = str(root / "covers")
    settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR = str(root / "upscaled")
    settings.LIBRARIUM_CATALOGUE_SYNC_ENABLED = True
    settings.LIBRARIUM_CATALOGUE_STATUS_URL = "http://catalogue.example"
    monkeypatch.setattr(catalogue_sync, "SLICE_INTERVAL", 0)
    monkeypatch.setattr(catalogue_sync, "POLL_SECONDS", 0)
    monkeypatch.setattr(catalogue_sync, "RETRY_SECONDS", 0)
    calls, routes = [], {}

    def transport(request, timeout):
        route = request.full_url.removeprefix("http://catalogue.example")
        calls.append(route)
        value = routes[route]
        if isinstance(value, Exception):
            raise value
        return Reply(*value)

    monkeypatch.setattr(catalogue_status, "open_url", transport)

    def publish(version, *, originals=2, derivative=True):
        path = tmp_path / f"{version}.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(art.SCHEMA.read_text())
            db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (version,))
            for i in range(originals):
                raw = art.png(i + 1, 3)
                digest = hashlib.sha256(raw).hexdigest()
                ident = f"w_{i}"
                db.execute("INSERT INTO work(id,title) VALUES (?,?)", (ident, f"Fixture {i}"))
                db.execute(
                    "INSERT INTO work_cover VALUES (?,?,?, ?,3,'image/png')",
                    (ident, "https://untrusted.invalid/image", digest, i + 1),
                )
                routes[f"/v1/work/{ident}/cover/original"] = (raw, "image/png")
                if derivative:
                    up = art.png(i + 3, 6)
                    db.execute(
                        "INSERT INTO cover_derivative VALUES (?,'v1',?,?,6,'image/png','2026-11-10')",
                        (digest, hashlib.sha256(up).hexdigest(), i + 3),
                    )
                    routes[f"/v1/work/{ident}/cover/upscaled"] = (up, "image/png")
        routes["/v1/status"] = (
            json.dumps({"published_version": version}).encode(),
            "application/json",
        )
        routes["/v1/snapshots"] = (
            json.dumps(
                {"snapshots": [{"version": version, "created": "2026-11-10T12:00:00+00:00"}]}
            ).encode(),
            "application/json",
        )
        routes[f"/v1/snapshots/{version}.sqlite"] = (path.read_bytes(), "application/vnd.sqlite3")
        return path

    return catalogue_sync, root, routes, calls, publish


def finish(module, limit=30):
    for _ in range(limit):
        result = module.tick()
        if result["state"] in {"complete", "failed"}:
            return result
    pytest.fail("sync did not finish within its slice bound")


def test_partial_cover_set_blocks_cutover_and_resumes_verified_bytes(sync, monkeypatch):
    module, root, _routes, calls, publish = sync
    publish("2026.11.10.1")
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    result = module.tick()
    assert not (root / "current").exists()
    assert result["state"] == "syncing"
    assert (
        len(list((root / "upscaled").glob("*/*"))) + len(list((root / "covers").glob("*/*"))) == 1
    )
    # A fresh worker resumes the on-disk journal; no trusted in-memory progress is needed.
    import importlib

    importlib.reload(module)
    monkeypatch.setattr(module, "SLICE_INTERVAL", 0)
    monkeypatch.setattr(module, "POLL_SECONDS", 0)
    assert finish(module)["state"] == "complete"
    assert (root / "current").read_text().strip() == "2026.11.10.1"
    assert len([c for c in calls if "/cover/" in c]) == 4
    assert len([c for c in calls if c.endswith(".sqlite")]) == 1


@pytest.mark.parametrize("bad", ["digest", "dimensions", "oversize", "media", "redirect"])
def test_bad_cover_never_cuts_over(sync, bad):
    module, root, routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    route = "/v1/work/w_0/cover/original"
    if bad == "redirect":
        routes[route] = HTTPError("http://catalogue.example", 302, "Found", {}, None)
    else:
        raw, media = routes[route]
        if bad == "digest":
            raw += b"changed"
        elif bad == "oversize":
            raw = b"x" * (module.catalogue_covers.MAX_BODY + 1)
        elif bad == "media":
            media = "text/html"
        else:
            path = root.parent / "2026.11.10.1.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE work_cover SET width=99")
            path = root.parent / "2026.11.10.1.sqlite"
            routes["/v1/snapshots/2026.11.10.1.sqlite"] = (
                path.read_bytes(),
                "application/vnd.sqlite3",
            )
        routes[route] = (raw, media)
    assert finish(module)["state"] == "failed"
    assert not (root / "current").exists()
    assert not list((root / "covers").glob("*/*"))


@pytest.mark.parametrize("bad", ["invalid", "version", "oversize"])
def test_invalid_snapshot_is_not_published(sync, bad, monkeypatch):
    module, root, routes, _calls, publish = sync
    path = publish("2026.11.10.1")
    raw = b"not sqlite"
    if bad == "version":
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE meta SET value='2026.11.09.1'")
        raw = path.read_bytes()
    if bad == "oversize":
        monkeypatch.setattr(module, "MAX_SNAPSHOT", 10)
    routes["/v1/snapshots/2026.11.10.1.sqlite"] = (raw, "application/vnd.sqlite3")
    assert finish(module)["state"] == "failed"
    assert not (root / "current").exists()
    assert not list(root.glob("*.sqlite"))


def test_atomic_cutover_retains_previous_and_prunes_to_three(sync, monkeypatch):
    module, root, _routes, _calls, publish = sync
    for i in range(1, 6):
        previous = (root / "current").read_bytes() if (root / "current").exists() else None
        publish(f"2026.11.10.{i}", originals=i, derivative=False)
        monkeypatch.setattr(module, "BATCH_SIZE", 1)
        result = module.tick()
        if result["state"] != "complete" and previous:
            assert (root / "current").read_bytes() == previous
        assert finish(module)["state"] == "complete"
        assert (root / "current").read_text().strip() == f"2026.11.10.{i}"
        if i > 1:
            assert (root / f"2026.11.10.{i - 1}.sqlite").is_file()
        assert len(list(root.glob("[0-9]*.sqlite"))) == min(3, i)


def test_disabled_and_throttled_worker_does_no_network(sync, settings, monkeypatch):
    module, _root, _routes, calls, publish = sync
    settings.LIBRARIUM_CATALOGUE_SYNC_ENABLED = False
    assert module.tick()["state"] == "disabled"
    assert not calls
    settings.LIBRARIUM_CATALOGUE_SYNC_ENABLED = True
    publish("2026.11.10.1", originals=1, derivative=False)
    monkeypatch.setattr(module, "POLL_SECONDS", 60)
    assert finish(module)["state"] == "complete"
    before = calls[:]
    module.tick()
    assert calls == before


def test_active_snapshot_backfill_precedes_remote_cutover(sync, monkeypatch):
    module, root, _routes, calls, publish = sync
    old = publish("2026.11.09.1", originals=2, derivative=False)
    (root / old.name).write_bytes(old.read_bytes())
    (root / "current").write_text("2026.11.09.1")
    publish("2026.11.10.1", originals=3, derivative=False)
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    module.tick()
    assert not any(c.endswith(".sqlite") for c in calls)
    assert finish(module)["state"] == "complete"
    assert (root / "current").read_text().strip() == "2026.11.10.1"


def test_corrupt_existing_blob_is_repaired_before_cutover(sync):
    module, root, routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    raw = routes["/v1/work/w_0/cover/original"][0]
    digest = hashlib.sha256(raw).hexdigest()
    target = root / "covers" / digest[:2] / digest
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong")
    assert finish(module)["state"] == "complete"
    assert target.read_bytes() == raw


def test_worker_claims_jobs_before_starting_background_scans(monkeypatch):
    from django.core.management import call_command
    from librarium import catalogue_sync
    from librarium.management.commands import inspection_worker

    events = []
    monkeypatch.setattr(inspection_worker, "close_old_connections", lambda: None)
    monkeypatch.setattr(inspection_worker.catalogue_status, "tick", lambda: None)
    monkeypatch.setattr(inspection_worker.library_read_model, "tick", lambda: None)
    monkeypatch.setattr(inspection_worker, "claim", lambda: events.append("claim"))
    monkeypatch.setattr(inspection_worker.cover_reviews, "tick", lambda: events.append("covers"))
    monkeypatch.setattr(catalogue_sync, "tick", lambda: events.append("sync"))
    call_command("inspection_worker", once=True)
    assert events == ["claim", "covers", "sync"]


@pytest.mark.django_db(transaction=True)
def test_health_warns_about_published_lag_and_incomplete_local_covers(sync, monkeypatch):
    from librarium import catalogue_health, catalogue_status

    module, root, _routes, _calls, publish = sync
    old = publish("2026.11.09.1", originals=2, derivative=False)
    (root / old.name).write_bytes(old.read_bytes())
    (root / "current").write_text("2026.11.09.1")
    publish("2026.11.10.1", originals=3, derivative=False)
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    module.tick()
    monkeypatch.setattr(
        catalogue_status,
        "saved",
        lambda now: {
            "state": "observed",
            "status": {
                "published_version": "2026.11.10.1",
                "live": {"state": "idle"},
                "cycles": [],
            },
            "covers": {},
        },
    )
    result = catalogue_health.build()
    reasons = " ".join(result["saved_headline"]["reasons"])
    assert "2026.11.10.1" in reasons and "2026.11.09.1" in reasons
    assert "cover" in reasons.lower()
    assert result["librarium"]["catalogue_sync"]["served_verified"] == 1


@pytest.mark.django_db(transaction=True)
def test_web_reads_health_and_covers_without_fetching(sync, client, monkeypatch):
    from librarium import catalogue_status

    module, _root, _routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    finish(module)

    def forbidden(*args, **kwargs):
        pytest.fail("request handler reached the upstream network")

    monkeypatch.setattr(catalogue_status, "open_url", forbidden)
    assert client.get("/api/catalogue/health").status_code == 200
    info = client.get("/api/catalogue").json()
    detail = client.get(
        "/api/catalogue/works/w_0", {"version": info["version"], "sha256": info["sha256"]}
    ).json()
    assert client.get(detail["cover"]["url"]).status_code == 200


def test_snapshot_cache_refreshes_original_and_upscaled_directories(tmp_path, settings):
    from librarium import catalogue, catalogue_health

    # The old snapshot owns the comparison, and newly arriving bytes own only artwork.
    old = tmp_path / "2026.11.09.1.sqlite"
    new = tmp_path / "2026.11.10.1.sqlite"
    for path in (old, new):
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(art.SCHEMA.read_text())
            db.execute("INSERT INTO meta VALUES ('catalog_version',?)", (path.stem,))
            if path == new:
                db.execute("INSERT INTO work(id,title) VALUES ('w_added','Fixture')")
                db.execute(
                    "INSERT INTO work_cover VALUES ('w_added','https://example.invalid',?,1,1,'image/png')",
                    (art.DIGEST,),
                )
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = str(tmp_path / "covers")
    with catalogue.connection(new) as db:
        info = {
            "version": new.stem,
            "sha256": catalogue.validate(new, catalogue.identity(new), new.stem),
        }
        assert (
            catalogue_health.snapshot_report(db, info, tmp_path)["changes"]["added"][0]["cover"]
            is None
        )
        target = tmp_path / "covers" / art.DIGEST[:2] / art.DIGEST
        target.parent.mkdir(parents=True)
        target.write_bytes(art.PNG)
        assert (
            catalogue_health.snapshot_report(db, info, tmp_path)["changes"]["added"][0]["cover"]
            is not None
        )


def test_obsolete_active_cover_cannot_prevent_new_complete_snapshot(sync):
    module, root, routes, _calls, publish = sync
    old = publish("2026.11.09.1", originals=1, derivative=False)
    (root / old.name).write_bytes(old.read_bytes())
    (root / "current").write_text(old.stem)
    new = publish("2026.11.10.1", originals=1, derivative=False)
    with closing(sqlite3.connect(new)) as db, db:
        raw = art.png(8, 9)
        db.execute(
            "UPDATE work_cover SET sha256=?,width=8,height=9", (hashlib.sha256(raw).hexdigest(),)
        )
    routes["/v1/snapshots/2026.11.10.1.sqlite"] = (new.read_bytes(), "application/vnd.sqlite3")
    routes["/v1/work/w_0/cover/original"] = (raw, "image/png")
    assert module.tick()["state"] == "failed"
    assert finish(module)["state"] == "complete"
    assert (root / "current").read_text().strip() == new.stem


def test_periodic_worker_verification_repairs_deleted_active_cover(sync):
    module, root, routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    assert finish(module)["state"] == "complete"
    digest = hashlib.sha256(routes["/v1/work/w_0/cover/original"][0]).hexdigest()
    target = root / "covers" / digest[:2] / digest
    target.unlink()
    assert finish(module)["state"] == "complete"
    assert target.is_file()


def test_symlink_cover_prefix_never_writes_outside_catalogue(sync, tmp_path):
    module, root, routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    digest = hashlib.sha256(routes["/v1/work/w_0/cover/original"][0]).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "covers").mkdir()
    (root / "covers" / digest[:2]).symlink_to(outside, target_is_directory=True)
    assert finish(module)["state"] == "failed"
    assert not list(outside.iterdir())
    assert not (root / "current").exists()


def test_competing_worker_does_not_fetch_or_modify_progress(sync):
    module, _root, _routes, calls, publish = sync
    publish("2026.11.10.1")
    with module.storage():
        assert module.tick()["state"] == "busy"
    assert not calls


def test_deadline_stops_a_trickling_cover_before_publication(sync, monkeypatch):
    module, root, _routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    original_download = module.download

    def download(url, stream, limit, deadline, media_types):
        if "/cover/" in url:
            deadline = module.time.monotonic() - 1
        return original_download(url, stream, limit, deadline, media_types)

    monkeypatch.setattr(module, "download", download)
    assert module.tick()["state"] == "syncing"
    assert not (root / "current").exists()


def test_dashboard_candidates_are_backfilled_before_unrelated_originals(sync, monkeypatch):
    module, _root, routes, calls, publish = sync
    publish("2026.11.10.1", originals=4, derivative=False)
    routes["/v1/status"] = (
        json.dumps(
            {
                "published_version": "2026.11.10.1",
                "snapshot": {"changes": {"added": [{"id": "w_3"}]}},
            }
        ).encode(),
        "application/json",
    )
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    module.tick()
    assert [c for c in calls if "/cover/" in c] == ["/v1/work/w_3/cover/original"]


def test_nonregular_pointer_and_staging_files_are_refused_without_blocking(sync):
    import os

    module, root, _routes, _calls, publish = sync
    publish("2026.11.10.1")
    os.mkfifo(root / "current")
    # Nonblocking admission is part of the API; the blocking reader must never run.
    with pytest.raises(ValueError):
        module.current(root)


def test_interrupted_atomic_blob_write_is_removed_on_retry(sync):
    module, root, _routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    with module.storage() as (_, fd):
        (root / ".sync-write").write_bytes(b"partial")
        module.atomic(fd, "fixture", b"complete")
    assert (root / "fixture").read_bytes() == b"complete"
    assert not (root / ".sync-write").exists()


def test_active_backfill_prioritises_added_plates_from_retained_comparison(sync, monkeypatch):
    module, root, _routes, calls, publish = sync
    for version, count in (("2026.11.09.1", 3), ("2026.11.10.1", 4)):
        path = publish(version, originals=count, derivative=False)
        (root / path.name).write_bytes(path.read_bytes())
    (root / "current").write_text("2026.11.10.1")
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    module.tick()
    assert [c for c in calls if "/cover/" in c] == ["/v1/work/w_3/cover/original"]


def test_slice_expiry_yields_progress_without_failure_backoff(sync, monkeypatch):
    module, root, _routes, _calls, publish = sync
    publish("2026.11.10.1", originals=2, derivative=False)
    original_fetch = module.fetch_cover
    seen = []

    def fetch(base, row, deadline):
        seen.append(row["work_id"])
        if len(seen) == 2:
            raise module.SliceExpired
        original_fetch(base, row, deadline)

    monkeypatch.setattr(module, "fetch_cover", fetch)
    result = module.tick()
    assert result["state"] == "syncing"
    assert result["verified"] == 1
    assert not (root / "current").exists()
    monkeypatch.setattr(module, "fetch_cover", original_fetch)
    assert finish(module)["state"] == "complete"


def test_socket_timeout_at_slice_deadline_yields_without_minute_backoff(sync, monkeypatch):
    module, root, _routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    clock = [module.time.monotonic()]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    transport = module.catalogue_status.open_url

    def delayed(request, timeout):
        if "/cover/" in request.full_url:
            clock[0] += 20
            raise URLError(TimeoutError())
        return transport(request, timeout)

    monkeypatch.setattr(module.catalogue_status, "open_url", delayed)
    assert module.tick()["state"] == "syncing"
    assert not (root / "current").exists()


def test_superseded_incomplete_snapshot_does_not_accumulate_staging_files(sync):
    module, root, routes, _calls, publish = sync
    publish("2026.11.10.1", originals=1, derivative=False)
    routes["/v1/work/w_0/cover/original"] = HTTPError(
        "http://catalogue.example", 404, "Missing", {}, None
    )
    assert finish(module)["state"] == "failed"
    publish("2026.11.10.2", originals=1, derivative=False)
    assert finish(module)["state"] == "complete"
    assert not list(root.glob(".staging-*.sqlite"))


def test_expired_slice_does_not_probe_any_cover(sync, monkeypatch):
    module, _root, _routes, _calls, publish = sync
    path = publish("2026.11.10.1", originals=3, derivative=False)
    probes = []
    monkeypatch.setattr(module, "cover_signature", lambda row: probes.append(row))
    state = {}
    assert not module.sync_covers(path, state, "http://catalogue.example", -1)
    assert probes == []
    assert state["verified"] == 0
    assert state["total"] == 3


def test_scan_resumes_after_deadline_without_reprobing_verified_prefix(sync, monkeypatch):
    module, root, _routes, _calls, publish = sync
    path = publish("2026.11.10.1", originals=3, derivative=False)
    assert finish(module)["state"] == "complete"
    state = module.load(root)
    state.update(receipts={}, manifest="")
    clock = [0]
    signature = module.cover_signature
    probes = []

    def probe(row):
        probes.append(row["work_id"])
        result = signature(row)
        clock[0] += 1
        return result

    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "cover_signature", probe)
    assert not module.sync_covers(path, state, "http://catalogue.example", 2)
    assert state["verified"] == 1
    with module.storage() as (_, fd):
        module.atomic(fd, module.STATE, json.dumps(state).encode())
    resumed = module.load(root)
    probes.clear()
    assert module.sync_covers(path, resumed, "http://catalogue.example", 100)
    assert "w_0" not in probes
    assert resumed["verified"] == resumed["total"] == 3


def test_batch_exhaustion_stops_probing_and_resumes_next_slice(sync, monkeypatch):
    module, _root, _routes, _calls, publish = sync
    path = publish("2026.11.10.1", originals=3, derivative=False)
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    state = {}
    with module.storage():
        assert not module.sync_covers(path, state, "http://catalogue.example", float("inf"))
        assert state["verified"] == 1
        signature = module.cover_signature
        probes = []

        def probe(row):
            probes.append(row["work_id"])
            return signature(row)

        monkeypatch.setattr(module, "cover_signature", probe)
        assert not module.sync_covers(path, state, "http://catalogue.example", float("inf"))
        assert set(probes) == {"w_1"}
        assert state["verified"] == 2


def test_multi_slice_active_backfill_finishes_before_new_snapshot_is_pulled(sync, monkeypatch):
    module, root, _routes, calls, publish = sync
    old = publish("2026.11.09.1", originals=3, derivative=False)
    (root / old.name).write_bytes(old.read_bytes())
    (root / "current").write_text(old.stem)
    publish("2026.11.10.1", originals=4, derivative=False)
    monkeypatch.setattr(module, "BATCH_SIZE", 1)
    for count in range(1, 4):
        result = module.tick()
        assert result["phase"] == "backfill"
        assert result["served_verified"] == count
        assert not any(c.endswith(".sqlite") for c in calls)
        assert module.load(root).get("backfill_attempted", False) == (count == 3)
    assert finish(module)["state"] == "complete"
    assert (root / "current").read_text().strip() == "2026.11.10.1"


@pytest.mark.parametrize("backfill", [True, False])
def test_mid_slice_error_persists_partial_progress(sync, backfill):
    module, root, routes, _calls, publish = sync
    path = publish("2026.11.10.1", originals=3, derivative=False)
    if backfill:
        (root / path.name).write_bytes(path.read_bytes())
        (root / "current").write_text(path.stem)
    routes["/v1/work/w_1/cover/original"] = URLError("synthetic outage")
    result = module.tick()
    assert result["state"] == "failed"
    assert (result["verified"], result["total"]) == (1, 3)
    if backfill:
        assert (result["served_verified"], result["served_total"]) == (1, 3)
        assert module.load(root)["backfill_attempted"]
    routes["/v1/work/w_1/cover/original"] = (art.png(2, 3), "image/png")
    assert finish(module)["state"] == "complete"


@pytest.mark.parametrize(
    "setting", ["LIBRARIUM_CATALOGUE_COVER_DIR", "LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR"]
)
def test_cover_storage_outside_catalogue_is_refused(sync, settings, tmp_path, setting):
    module, _root, _routes, _calls, _publish = sync
    setattr(settings, setting, str(tmp_path / "outside"))
    with pytest.raises(ValueError), module.storage():
        pytest.fail("outside cover storage admitted")
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("variant", ["covers", "upscaled"])
def test_sync_storage_cannot_overlap_artifacts_at_either_cover_directory(sync, settings, variant):
    module, root, _routes, _calls, _publish = sync
    settings.LIBRARIUM_ARTIFACT_DIR = str(root / variant)
    with pytest.raises(ValueError, match="Overlapping catalogue storage"), module.storage():
        pytest.fail("overlapping artifacts admitted")
    assert not list(root.iterdir())


def test_manifest_change_resets_a_completed_scan(sync, monkeypatch):
    module, _root, _routes, _calls, publish = sync
    first = publish("2026.11.10.1", originals=1, derivative=False)
    state = {}
    with module.storage():
        assert module.sync_covers(first, state, "http://catalogue.example", float("inf"))
        second = publish("2026.11.10.2", originals=2, derivative=False)
        monkeypatch.setattr(module, "BATCH_SIZE", 1)
        assert not module.sync_covers(second, state, "http://catalogue.example", float("inf"))
        assert (state["verified"], state["total"]) == (1, 2)
        assert module.sync_covers(second, state, "http://catalogue.example", float("inf"))
