import fcntl
import hashlib
import io
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.core.management import call_command
from librarium import catalogue
from librarium import reference_production as producer
from test_catalogue import make_snapshot


class Engine:
    def validate_packet(self, packet):
        if packet.get("schema") != "librarium.reference-packet.v1" or not packet.get("records"):
            raise ValueError("Invalid packet")
        return packet

    def apply_packet(self, path, packet):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE work SET title=?", (packet["records"][0]["title"],))
        return {"records": len(packet["records"])}

    def rebuild_database(self, path):
        return {"works": 1}

    def stage_snapshot(self, path, outdir, version):
        output = Path(f"/proc/self/fd/{outdir}") / f"{version}.sqlite"
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(output)) as target:
            source.backup(target)
            target.execute("INSERT OR REPLACE INTO meta VALUES('catalog_version',?)", (version,))
            target.commit()
        output.chmod(0o444)
        return {"version": version, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


@pytest.fixture
def state(tmp_path, settings, monkeypatch):
    root = tmp_path / "private-reference"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_REFERENCE_STATE_DIR = str(root)
    snapshots = tmp_path / "bootstrap"
    source = make_snapshot(snapshots)
    settings.LIBRARIUM_CATALOGUE_DIR = str(snapshots)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    monkeypatch.setattr(producer, "_engine", lambda: Engine())
    return root, source


def packet(title="Imported fixture"):
    return json.dumps(
        {
            "schema": "librarium.reference-packet.v1",
            "source": "lexicanum",
            "observed_at": "2026-10-28T12:00:00Z",
            "records": [
                {
                    "native_id": "fixture-1",
                    "title": title,
                    "authors": [["Fixture Author", "author"]],
                }
            ],
        }
    ).encode()


def bootstrap(state):
    return {
        "bootstrap_version": "2026.10.25.1",
        "bootstrap_sha256": hashlib.sha256(state[1].read_bytes()).hexdigest(),
    }


def test_bootstrap_publication_is_native_admitted_and_preserves_source(state):
    root, source = state
    before = source.read_bytes()
    result = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert result["state"] == "succeeded" and result["fixture"] is True
    assert source.read_bytes() == before
    with catalogue.snapshot(str(root / "published"), result["version"], result["sha256"], True) as (
        db,
        _,
    ):
        assert db.execute("SELECT title FROM work").fetchone()[0] == "Imported fixture"
    status = producer.status()
    assert status["status"] == "manual"
    assert status["current"]["version"] == result["version"]
    assert status["last_outcome"]["request_key"] == result["request_key"]
    assert str(root) not in json.dumps(status)


@pytest.mark.parametrize("damage", ["header", "schema", "version"])
def test_invalid_native_snapshot_health_keeps_selected_catalogue_queues_available(
    state, client, damage
):
    pin = bootstrap(state)
    result = producer.import_packet(packet(), str(uuid.uuid4()), **pin)
    assert producer.status()["status"] == "manual"
    path = state[0] / "published" / f"{result['version']}.sqlite"
    path.chmod(0o600)
    if damage == "header":
        path.write_bytes(b"invalid native snapshot")
    else:
        with closing(sqlite3.connect(path)) as db, db:
            if damage == "schema":
                db.execute("DROP TABLE edition")
            else:
                db.execute("UPDATE meta SET value='2026.01.01.1' WHERE key='catalog_version'")
    path.chmod(0o444)
    assert producer.status()["status"] == "unavailable"
    response = client.get(
        "/api/catalogue/control",
        {"version": pin["bootstrap_version"], "sha256": pin["bootstrap_sha256"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["producer"]["status"] == "unavailable"
    assert data["snapshot"]["version"] == pin["bootstrap_version"]
    assert data["counts"]["incomplete"] == 1 and data["works"][0]["id"] == "w_fixture"
    assert hashlib.sha256(state[1].read_bytes()).hexdigest() == pin["bootstrap_sha256"]


@pytest.mark.parametrize("later_update", [False, True])
def test_retained_generation_hierarchy_is_synced_before_prepared_receipt(
    state, monkeypatch, later_update
):
    if later_update:
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    sync = os.fsync
    write_receipt = producer._json
    synced, prepared = set(), []

    def track_sync(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        sync(fd)
        synced.add(path)

    def track_receipt(fd, name, value):
        if value.get("state") == "prepared":
            prepared.append((value["version"], frozenset(synced)))
        return write_receipt(fd, name, value)

    monkeypatch.setattr(os, "fsync", track_sync)
    monkeypatch.setattr(producer, "_json", track_receipt)
    result = producer.import_packet(
        packet("A native update"), str(uuid.uuid4()), **({} if later_update else bootstrap(state))
    )
    assert result["state"] == "succeeded" and len(prepared) == 1
    version, durable = prepared[0]
    generation = state[0] / "generations" / version
    assert {state[0], generation.parent, generation, generation / "evidence.sqlite"} <= durable


@pytest.mark.parametrize("directory", ["generations", "generation"])
def test_failed_generation_directory_sync_preserves_prior_publication(
    state, monkeypatch, directory
):
    first = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    sync = os.fsync

    def fail_sync(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if (directory == "generations" and path == state[0] / "generations") or (
            directory == "generation"
            and path.parent == state[0] / "generations"
            and path.name != first["version"]
        ):
            raise OSError("simulated directory sync failure")
        return sync(fd)

    monkeypatch.setattr(os, "fsync", fail_sync)
    key = str(uuid.uuid4())
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet("Must not become current"), key)
    assert (state[0] / "published/current").read_text() == first["version"]
    monkeypatch.setattr(os, "fsync", sync)
    assert producer.import_packet(packet("Must not become current"), key)["state"] == "failed"
    assert producer.status()["current"]["version"] == first["version"]


def test_request_replay_conflict_and_later_generation(state):
    key = str(uuid.uuid4())
    first = producer.import_packet(packet(), key, **bootstrap(state))
    assert producer.import_packet(packet(), key) == first
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet("Different"), key)
    assert error.value.status == 409
    next_result = producer.import_packet(packet("New title"), str(uuid.uuid4()))
    assert next_result["version"] != first["version"]
    assert next_result["base_snapshot"]["sha256"] == first["sha256"]
    root = state[0] / "published"
    with catalogue.snapshot(str(root), first["version"], first["sha256"], True) as (db, _):
        assert db.execute("SELECT title FROM work").fetchone()[0] == "Imported fixture"


def test_failure_keeps_prior_current_and_same_key_replays_failed_outcome(state, monkeypatch):
    first = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))

    def refused(*args):
        raise OSError("a private path must not reach public status")

    monkeypatch.setattr(producer, "_activate", refused)
    key = str(uuid.uuid4())
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet("Failed new title"), key)
    assert producer.status()["current"]["sha256"] == first["sha256"]
    assert producer.status()["last_outcome"]["state"] == "failed"
    assert "private path" not in json.dumps(producer.status())
    assert producer.import_packet(packet("Failed new title"), key)["state"] == "failed"


def test_crash_after_cutover_recovers_same_key_without_importing_again(state, monkeypatch):
    class Crash(BaseException):
        pass

    activate = producer._activate

    def interrupted(*args):
        activate(*args)
        raise Crash

    monkeypatch.setattr(producer, "_activate", interrupted)
    key = str(uuid.uuid4())
    with pytest.raises(Crash):
        producer.import_packet(packet(), key, **bootstrap(state))
    monkeypatch.setattr(producer, "_activate", activate)
    result = producer.import_packet(packet(), key)
    assert result["state"] == "succeeded"
    assert producer.status()["current"]["version"] == result["version"]


def test_succeeded_receipt_replay_repairs_pending_bookkeeping_before_next_request(
    state, monkeypatch
):
    atomic = producer._atomic

    def interrupted(fd, name, raw):
        if name == "last":
            raise OSError("lost acknowledgement")
        return atomic(fd, name, raw)

    monkeypatch.setattr(producer, "_atomic", interrupted)
    key = str(uuid.uuid4())
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet(), key, **bootstrap(state))
    assert error.value.code == "reference_recovery_required"
    assert (state[0] / "pending").exists()
    monkeypatch.setattr(producer, "_atomic", atomic)
    result = producer.import_packet(packet(), key)
    assert result["state"] == "succeeded" and not (state[0] / "pending").exists()
    assert (
        producer.import_packet(packet("A later import"), str(uuid.uuid4()))["state"] == "succeeded"
    )


def test_bookkeeping_recovery_does_not_override_a_different_selected_generation(state, monkeypatch):
    first = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    atomic = producer._atomic

    def interrupted(fd, name, raw):
        if name == "last":
            raise OSError("lost acknowledgement")
        return atomic(fd, name, raw)

    monkeypatch.setattr(producer, "_atomic", interrupted)
    key = str(uuid.uuid4())
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet("Next"), key)
    monkeypatch.setattr(producer, "_atomic", atomic)
    (state[0] / "published/current").write_text(first["version"])
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet("Next"), key)
    assert error.value.code == "reference_recovery_required"
    assert (state[0] / "pending").exists()
    assert (state[0] / "published/current").read_text() == first["version"]


def test_recorded_requests_do_not_reinterpret_new_validation_policy(state, monkeypatch):
    key = str(uuid.uuid4())
    result = producer.import_packet(packet(), key, **bootstrap(state))

    def never_parse(*args):
        raise AssertionError("recorded request was reinterpreted")

    monkeypatch.setattr(producer, "_packet", never_parse)
    assert producer.import_packet(packet(), key) == result


def test_active_lock_refuses_without_staging_a_generation(state):
    fd = os.open(state[0] / "producer.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(producer.ProductionError) as error:
            producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
        assert error.value.code == "reference_busy"
        assert not (state[0] / "generations").exists()
    finally:
        os.close(fd)


def test_health_reuses_verified_immutable_pins_and_packet_hashes(state, monkeypatch):
    result = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert producer.status()["status"] == "manual"

    def no_more_hashes(*args, **kwargs):
        raise AssertionError("health reread preserved packet bytes")

    monkeypatch.setattr(producer, "_digest", no_more_hashes)
    for _ in range(3):
        assert producer.status()["current"]["sha256"] == result["sha256"]


@pytest.mark.parametrize(
    "raw", [b"{}", b"[1]", b'{"schema":1,"schema":2}', b"{" + b"x" * (4 * 1024 * 1024)],
    ids=[
        "missing-fields",
        "array",
        "duplicate-schema",
        "oversized-packet",
    ],
)
def test_invalid_packets_leave_state_untouched(state, raw):
    with pytest.raises(producer.ProductionError):
        producer.import_packet(raw, str(uuid.uuid4()), **bootstrap(state))
    assert list(state[0].iterdir()) == []


@pytest.mark.parametrize(
    "kind", ["root-symlink", "permissions", "library-overlap", "artifact-overlap"]
)
def test_private_state_boundaries_refuse_before_writes(state, settings, tmp_path, kind):
    root = state[0]
    if kind == "root-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        settings.LIBRARIUM_REFERENCE_STATE_DIR = str(alias)
    elif kind == "permissions":
        root.chmod(0o755)
    elif kind == "library-overlap":
        settings.DIRECT_LIBRARY_ROOT = str(root)
    else:
        settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert list(root.iterdir()) == []


def test_cli_reads_explicit_stdin_and_prints_receipt(state):
    output = io.StringIO()
    args = bootstrap(state)
    call_command(
        "reference_import",
        "-",
        request_key=str(uuid.uuid4()),
        stdin=io.StringIO(packet().decode()),
        stdout=output,
        **args,
    )
    assert json.loads(output.getvalue())["state"] == "succeeded"


def test_unconfigured_status_is_read_only(settings):
    settings.LIBRARIUM_REFERENCE_STATE_DIR = ""
    assert producer.status()["status"] == "not_configured"


def test_real_retained_engine_bootstrap_update_preserves_source_history_and_work_ids(
    state, settings, monkeypatch, tmp_path
):
    from bl_catalog import native

    working = tmp_path / "retained.sqlite"
    native.init_database(working)
    initial = json.loads(packet("Before import"))
    initial["observed_at"] = "2026-10-27T12:00:00Z"
    native.apply_packet(working, initial)
    native.rebuild_database(working)
    snapshots = tmp_path / "retained-bootstrap"
    snapshots.mkdir(mode=0o700)
    native.stage_snapshot(working, snapshots, "2026.10.25.1")
    source = snapshots / "2026.10.25.1.sqlite"
    source_bytes = source.read_bytes()
    settings.LIBRARIUM_CATALOGUE_DIR = str(snapshots)
    monkeypatch.setattr(producer, "_engine", lambda: native)
    with closing(sqlite3.connect(source)) as db:
        work_ids = {row[0] for row in db.execute("SELECT id FROM work")}
    result = producer.import_packet(
        packet(),
        str(uuid.uuid4()),
        bootstrap_version="2026.10.25.1",
        bootstrap_sha256=hashlib.sha256(source_bytes).hexdigest(),
    )
    assert result["state"] == "succeeded"
    assert source.read_bytes() == source_bytes
    with catalogue.snapshot(
        str(state[0] / "published"), result["version"], result["sha256"], True
    ) as (db, _):
        assert {row[0] for row in db.execute("SELECT id FROM work")} == work_ids
        assert db.execute("SELECT title FROM work").fetchone()[0] == "Imported fixture"
        assert db.execute("SELECT count(*) FROM source_record").fetchone()[0] == 2


def test_nested_directory_and_packet_symlinks_refuse_without_following(state, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (state[0] / "published").symlink_to(outside, target_is_directory=True)
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert list(outside.iterdir()) == []


def test_cli_refuses_symlink_packet_input(state, tmp_path):
    from django.core.management.base import CommandError

    source = tmp_path / "packet.json"
    source.write_bytes(packet())
    alias = tmp_path / "alias.json"
    alias.symlink_to(source)
    with pytest.raises(CommandError):
        call_command(
            "reference_import", str(alias), request_key=str(uuid.uuid4()), **bootstrap(state)
        )
    assert list(state[0].iterdir()) == []


def test_private_root_cannot_be_an_unconfigured_library_or_other_service(state, settings):
    marker = state[0] / "metadata.db"
    marker.write_bytes(b"preserve original library")
    settings.DIRECT_LIBRARY_ROOT = ""
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert list(state[0].iterdir()) == [marker]
    assert marker.read_bytes() == b"preserve original library"


def test_first_native_version_advances_bootstrap_counter_on_same_day(state, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 25, 12, tzinfo=UTC)

    monkeypatch.setattr(producer, "datetime", Clock)
    result = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert result["version"] == "2026.10.25.2"


def test_changed_preserved_packet_cannot_regain_cached_health_or_replay(state):
    key = str(uuid.uuid4())
    producer.import_packet(packet(), key, **bootstrap(state))
    assert producer.status()["status"] == "manual"
    stored = state[0] / "requests" / f"{key}.packet"
    stored.chmod(0o600)
    stored.write_bytes(packet("corrupted saved input"))
    assert producer.status()["status"] == "unavailable"
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet(), key)


def test_interrupted_build_holds_other_requests_and_requires_explicit_new_retry(state, monkeypatch):
    class Crash(BaseException):
        pass

    class InterruptedEngine(Engine):
        def rebuild_database(self, path):
            raise Crash

    monkeypatch.setattr(producer, "_engine", lambda: InterruptedEngine())
    key = str(uuid.uuid4())
    with pytest.raises(Crash):
        producer.import_packet(packet(), key, **bootstrap(state))
    assert producer.status()["last_outcome"]["state"] == "preparing"
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    assert error.value.code == "reference_recovery_required"
    result = producer.import_packet(packet(), key)
    assert result["state"] == "failed" and result["error_code"] == "reference_interrupted"
    assert producer.status()["current"] is None
    monkeypatch.setattr(producer, "_engine", lambda: Engine())
    assert (
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))["state"]
        == "succeeded"
    )


def test_failed_receipt_replay_cleans_interrupted_failure_bookkeeping(state, monkeypatch):
    first = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    atomic = producer._atomic

    def failed_activation(*args):
        raise OSError("publication refused")

    def failed_last(fd, name, raw):
        if name == "last":
            raise OSError("receipt acknowledgement lost")
        return atomic(fd, name, raw)

    monkeypatch.setattr(producer, "_activate", failed_activation)
    monkeypatch.setattr(producer, "_atomic", failed_last)
    key = str(uuid.uuid4())
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet("Failed update"), key)
    assert (state[0] / "pending").exists()
    monkeypatch.setattr(producer, "_atomic", atomic)
    assert producer.import_packet(packet("Failed update"), key)["state"] == "failed"
    assert not (state[0] / "pending").exists()
    assert producer.status()["current"]["sha256"] == first["sha256"]
    assert producer.status()["last_outcome"]["request_key"] == key
    assert producer.status()["last_outcome"]["state"] == "failed"


def test_preparing_receipt_without_pending_has_a_terminal_exact_replay(state, monkeypatch):
    class Crash(BaseException):
        pass

    atomic = producer._atomic

    def lost_pending(fd, name, raw):
        if name == "pending":
            raise Crash
        return atomic(fd, name, raw)

    key = str(uuid.uuid4())
    monkeypatch.setattr(producer, "_atomic", lost_pending)
    with pytest.raises(Crash):
        producer.import_packet(packet(), key, **bootstrap(state))
    assert not (state[0] / "pending").exists()
    monkeypatch.setattr(producer, "_atomic", atomic)
    outcome = producer.import_packet(packet(), key)
    assert outcome["state"] == "failed" and outcome["error_code"] == "reference_interrupted"
    assert producer.status()["last_outcome"]["request_key"] == key
    assert not (state[0] / "published/current").exists()
    assert (
        producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))["state"]
        == "succeeded"
    )


def test_packet_is_not_published_before_its_bytes_are_durable(state, monkeypatch):
    class Crash(BaseException):
        pass

    sync = os.fsync

    def lost_packet_sync(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path.parent.name == "requests" and path.is_file():
            raise Crash
        return sync(fd)

    key = str(uuid.uuid4())
    monkeypatch.setattr(os, "fsync", lost_packet_sync)
    with pytest.raises(Crash):
        producer.import_packet(packet(), key, **bootstrap(state))
    assert not (state[0] / "requests" / f"{key}.packet").exists()
    monkeypatch.setattr(os, "fsync", sync)
    assert producer.import_packet(packet(), key, **bootstrap(state))["state"] == "succeeded"


def test_bootstrap_requires_explicit_exact_pin_and_cannot_replace_existing_native_state(state):
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet(), str(uuid.uuid4()))
    assert error.value.code == "reference_bootstrap_required"
    result = producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet("New"), str(uuid.uuid4()), **bootstrap(state))
    assert error.value.code == "reference_bootstrap_conflict"
    assert producer.status()["current"]["sha256"] == result["sha256"]


def test_replay_cannot_add_a_bootstrap_pin_to_an_existing_native_update(state):
    producer.import_packet(packet(), str(uuid.uuid4()), **bootstrap(state))
    key = str(uuid.uuid4())
    producer.import_packet(packet("Next"), key)
    with pytest.raises(producer.ProductionError) as error:
        producer.import_packet(packet("Next"), key, **bootstrap(state))
    assert error.value.code == "reference_request_conflict"


@pytest.mark.parametrize(
    "field,value", [("fixture", None), ("records", "unknown"), ("base_current", {}), ("source", [])]
)
def test_corrupt_receipt_keeps_status_bounded_and_cannot_replay_as_success(state, field, value):
    key = str(uuid.uuid4())
    producer.import_packet(packet(), key, **bootstrap(state))
    receipt_path = state[0] / "requests" / f"{key}.json"
    receipt = json.loads(receipt_path.read_text())
    receipt[field] = value
    receipt_path.write_text(json.dumps(receipt))
    assert producer.status()["status"] == "unavailable"
    with pytest.raises(producer.ProductionError):
        producer.import_packet(packet(), key)
