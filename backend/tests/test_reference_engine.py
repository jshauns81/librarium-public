import copy
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from bl_catalog import native
from librarium import catalogue


def packet(*records, observed_at="2026-10-28T12:00:00Z"):
    return {
        "schema": "librarium.reference-packet.v1",
        "source": "lexicanum",
        "observed_at": observed_at,
        "records": list(records)
        or [
            {
                "native_id": "fixture-1",
                "title": "Fixture Native Book",
                "authors": [["Fixture Author", "author"]],
                "type": "novel",
                "format": "ebook",
                "isbn13": "9780306406157",
                "work_ids": {"lexicanum": "wh40k:Fixture_Native_Book_(Novel)"},
            }
        ],
    }


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "evidence.sqlite"
    native.init_database(path)
    return path


def query(path, sql, params=()):
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql, params).fetchall()


def test_import_history_replay_and_a_b_a_currentness(database):
    original = packet()
    untouched = copy.deepcopy(original)
    first = native.apply_packet(database, original)
    assert first["added"] == 1 and original == untouched
    assert native.apply_packet(database, original)["added"] == 0
    changed = copy.deepcopy(original)
    changed["observed_at"] = "2026-10-28T13:00:00Z"
    changed["records"][0]["title"] = "Later Fixture Title"
    native.apply_packet(database, changed)
    native.rebuild_database(database)
    assert query(database, "SELECT title FROM work") == [("Later Fixture Title",)]
    original["observed_at"] = "2026-10-28T14:00:00Z"
    native.apply_packet(database, original)
    native.rebuild_database(database)
    assert query(database, "SELECT title FROM work") == [("Fixture Native Book",)]
    assert query(database, "SELECT count(*) FROM source_record") == [(2,)]
    original["observed_at"] = "2026-10-28T11:00:00Z"
    native.apply_packet(database, original)
    assert query(database, "SELECT max(last_seen_at) FROM source_record") == [
        ("2026-10-28T14:00:00.000000+00:00",)
    ]


def test_rebuild_preserves_ids_and_aliases_across_a_work_merge(database):
    records = [
        {
            "native_id": "one",
            "title": "Fixture Alpha",
            "authors": [["Fixture Author", "author"]],
            "format": "ebook",
            "isbn13": "9780306406157",
        },
        {
            "native_id": "two",
            "title": "Fixture Beta",
            "authors": [["Fixture Author", "author"]],
            "format": "paperback",
            "isbn13": "9780743411608",
        },
    ]
    native.apply_packet(database, packet(*records))
    native.rebuild_database(database)
    old = {row[0] for row in query(database, "SELECT id FROM work")}
    assert len(old) == 2
    for record in records:
        record["work_ids"] = {"wikidata": "Q100000001"}
    native.apply_packet(database, packet(*records, observed_at="2026-10-28T13:00:00Z"))
    native.rebuild_database(database)
    current = {row[0] for row in query(database, "SELECT id FROM work")}
    assert len(current) == 1 and current <= old
    aliases = query(database, "SELECT old_id,new_id FROM id_alias WHERE old_id LIKE 'w_%'")
    assert aliases == [(next(iter(old - current)), next(iter(current)))]
    native.rebuild_database(database)
    assert query(database, "SELECT old_id,new_id FROM id_alias WHERE old_id LIKE 'w_%'") == aliases


def test_staged_snapshot_is_admitted_immutable_and_does_not_select_current(database, tmp_path):
    native.apply_packet(database, packet())
    native.rebuild_database(database)
    out = tmp_path / "published"
    out.mkdir()
    (out / "current").write_text("2026.10.27.1")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    value = native.stage_snapshot(database, out, "2026.10.28.1")
    target = out / "2026.10.28.1.sqlite"
    assert value["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert value["size_bytes"] == target.stat().st_size
    assert target.read_bytes()[18:20] == b"\x01\x01"
    assert target.stat().st_mode & 0o222 == 0
    assert (out / "current").read_text() == "2026.10.27.1"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with catalogue.snapshot(str(out), value["version"], value["sha256"], fixture=True) as (
        db,
        info,
    ):
        assert info["version"] == "2026.10.28.1"
        assert db.execute("SELECT count(*) FROM work").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        native.stage_snapshot(database, out, "2026.10.28.1")


def test_held_directory_descriptor_is_explicit_and_remains_owned_by_caller(database, tmp_path):
    native.apply_packet(database, packet())
    native.rebuild_database(database)
    out = tmp_path / "staged"
    out.mkdir()
    descriptor = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
    try:
        held = os.fstat(descriptor)
        value = native.stage_snapshot(database, descriptor, "2026.10.28.1")
        assert value["version"] == "2026.10.28.1"
        assert os.fstat(descriptor).st_ino == held.st_ino
        with pytest.raises(ValueError):
            native.stage_snapshot(database, f"/proc/self/fd/{descriptor}", "2026.10.28.2")
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "version", ["../../outside", "2026.02.30.1", "2026.10.28.0", "2026.10.28.01"]
)
def test_stage_refuses_invalid_versions_before_publication(database, tmp_path, version):
    with pytest.raises(ValueError):
        native.stage_snapshot(database, tmp_path, version)
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(source="unknown-provider"),
        lambda value: value.update(source=[]),
        lambda value: value.update(schema="another-packet"),
        lambda value: value.update(records=[]),
        lambda value: value.update(observed_at="not-a-time"),
        lambda value: value["records"][0].update(source="google"),
        lambda value: value["records"][0].update(title={"unsupported": "structure"}),
        lambda value: value["records"][0].update(series=[["Series", float("nan")]]),
        lambda value: value["records"][0].update(authors=[["Name", "invented-role"]]),
        lambda value: value["records"][0].update(contents=[{"title": "A story", "type": []}]),
    ],
)
def test_packet_refusals_happen_before_any_evidence_is_written(database, change):
    value = packet()
    change(value)
    with pytest.raises(ValueError):
        native.apply_packet(database, value)
    assert query(database, "SELECT count(*) FROM source_record") == [(0,)]


def test_duplicate_native_ids_and_packet_size_are_refused_before_writing(database, monkeypatch):
    value = packet()
    value["records"].append(copy.deepcopy(value["records"][0]))
    with pytest.raises(native.PacketError, match="repeat"):
        native.apply_packet(database, value)
    monkeypatch.setattr(native, "MAX_PACKET_BYTES", 16)
    with pytest.raises(native.PacketError, match="4 MiB"):
        native.apply_packet(database, packet())
    assert query(database, "SELECT count(*) FROM source_record") == [(0,)]


def test_failed_snapshot_copy_removes_temporary_files_without_changing_current(
    database, tmp_path, monkeypatch
):
    out = tmp_path / "published"
    out.mkdir()
    (out / "current").write_text("retained")

    def failed_copy(source, destination):
        destination.write_bytes(b"partial staged copy")
        raise OSError("simulated unavailable space")

    monkeypatch.setattr(native, "_copy_db", failed_copy)
    with pytest.raises(OSError, match="unavailable space"):
        native.stage_snapshot(database, out, "2026.10.28.1")
    assert sorted(path.name for path in out.iterdir()) == ["current"]
    assert (out / "current").read_text() == "retained"


def test_snapshot_descriptor_must_name_a_directory(database, tmp_path):
    with database.open("rb") as file:
        with pytest.raises(ValueError, match="directory"):
            native.stage_snapshot(database, file.fileno(), "2026.10.28.1")
        assert os.fstat(file.fileno()).st_size > 0
    with pytest.raises(ValueError, match="descriptor"):
        native.stage_snapshot(database, True, "2026.10.28.1")


def test_retained_engine_provenance_matches_packaged_source():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "upstream/manifests/librarium-reference-engine.json").read_text())
    assert manifest["commit"] == native.ENGINE_REVISION
    assert manifest["native_facade"]["policy_version"] == native.POLICY_VERSION
    for entry in manifest["files"]:
        source = root / entry["destination"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["local_sha256"]
    facade = manifest["native_facade"]
    assert (
        hashlib.sha256((root / facade["path"]).read_bytes()).hexdigest() == facade["local_sha256"]
    )
