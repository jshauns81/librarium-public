"""The packaged reference probe exercises native production without provider access."""

import json
import os
import runpy
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/reference_container_acceptance.py"


def probe():
    return runpy.run_path(str(SCRIPT))


def test_probe_detects_changed_or_new_bootstrap_files(tmp_path):
    acceptance = probe()
    root = tmp_path / "bootstrap"
    root.mkdir()
    source = root / "snapshot.sqlite"
    source.write_bytes(b"synthetic immutable source")
    before = acceptance["tree_state"](root)
    acceptance["unchanged"](root, before)
    source.write_bytes(b"changed source")
    with pytest.raises(AssertionError):
        acceptance["unchanged"](root, before)
    source.write_bytes(b"synthetic immutable source")
    (root / "snapshot.sqlite-shm").write_bytes(b"unexpected SQLite output")
    with pytest.raises(AssertionError):
        acceptance["unchanged"](root, before)


def test_probe_forbids_provider_socket_creation():
    acceptance = probe()
    with acceptance["offline"](), pytest.raises(AssertionError, match="network"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_probe_builds_an_admitted_immutable_bootstrap_without_provider_access(tmp_path):
    from librarium import catalogue

    acceptance = probe()
    with acceptance["offline"]():
        source, pin = acceptance["prepare_bootstrap"](tmp_path)
    before = acceptance["tree_state"](source)
    assert all(path.stat().st_mode & 0o222 == 0 for path in source.iterdir())
    with catalogue.snapshot(str(source), pin["version"], pin["sha256"], fixture=True) as (db, _):
        assert db.execute("SELECT title FROM work").fetchone()[0] == "Fixture Native Book"
        assert db.execute("SELECT count(*) FROM source_record").fetchone()[0] == 1
    acceptance["unchanged"](source, before)


def test_runtime_catalogue_fixture_passes_unpinned_startup_admission(tmp_path):
    from librarium import catalogue

    acceptance = probe()
    root = tmp_path / "catalogue"
    root.mkdir()
    with acceptance["offline"]():
        pin = acceptance["prepare_catalogue"](root)
    with catalogue.snapshot(str(root)) as (db, admitted):
        assert admitted["version"] == pin["version"]
        assert admitted["sha256"] == pin["sha256"]
        assert db.execute("SELECT count(*) FROM work").fetchone()[0] == 1
    assert all(path.stat().st_mode & 0o222 == 0 for path in root.iterdir())


def test_runtime_fixture_refuses_to_replace_existing_catalogue(tmp_path):
    acceptance = probe()
    root = tmp_path / "catalogue"
    root.mkdir()
    (root / "current").write_text("retained synthetic snapshot")
    before = acceptance["tree_state"](root)
    with pytest.raises(AssertionError, match="empty"):
        acceptance["prepare_catalogue"](root)
    acceptance["unchanged"](root, before)


def test_runtime_catalogue_preparation_uses_the_stdin_command(tmp_path):
    from librarium import catalogue

    root = tmp_path / "catalogue"
    root.mkdir()
    result = subprocess.run(
        [sys.executable, "-", "prepare-catalogue", str(root)],
        input=SCRIPT.read_bytes(),
        env={**os.environ, "PYTHONPATH": str(SCRIPT.parents[2] / "backend")},
        capture_output=True,
        timeout=60,
        check=True,
    )
    pin = json.loads(result.stdout)
    with catalogue.snapshot(str(root)) as (_, admitted):
        assert admitted["sha256"] == pin["sha256"]


def test_packaged_probe_runs_retained_engines_and_native_orchestration(tmp_path):
    result = probe()["exercise"](tmp_path)
    assert result["work_id"]
    assert result["history_records"] == 2
    assert result["stable_identity"] is True
    assert result["idempotent"] is True
    assert result["reopened"] is True
    assert result["source_unchanged"] is True
    assert result["producer_status"] == "manual"
    assert result["refused_requests"] == 3
