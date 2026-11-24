"""Synthetic native reference acceptance inside the exact built application image."""

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

BOOTSTRAP_VERSION = "2026.10.28.1"
FIRST_KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-reference-image-first-v1"))
SECOND_KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-reference-image-second-v1"))
INVALID_KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-reference-image-invalid-v1"))
BLOCKED_KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-reference-image-blocked-v1"))


def packet(*, revised=False, bootstrap=False):
    return {
        "schema": "librarium.reference-packet.v1",
        "source": "lexicanum",
        "observed_at": "2026-10-28T11:00:00Z"
        if bootstrap
        else "2026-10-28T13:00:00Z"
        if revised
        else "2026-10-28T12:00:00Z",
        "records": [
            {
                "native_id": "fixture-1",
                "title": "Fixture Native Book Revised" if revised else "Fixture Native Book",
                "authors": [["Fixture Author", "author"]],
                "type": "novel",
                "format": "ebook",
                "isbn13": "9780306406157",
                "work_ids": {"lexicanum": "wh40k:Fixture_Native_Book_(Novel)"},
            }
        ],
    }


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@contextmanager
def offline():
    with patch(
        "socket.socket",
        side_effect=AssertionError("Native producer attempted network access"),
    ):
        yield


def tree_state(root):
    result: dict[str, dict[str, int | str]] = {}
    for path in sorted(Path(root).rglob("*")):
        info = path.lstat()
        relative = str(path.relative_to(root))
        if stat.S_ISDIR(info.st_mode):
            result[relative + "/"] = {"mode": stat.S_IMODE(info.st_mode)}
        else:
            assert stat.S_ISREG(info.st_mode), "Bootstrap includes a nonregular file"
            result[relative] = {
                "mode": stat.S_IMODE(info.st_mode),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    return result


def unchanged(root, before):
    assert tree_state(root) == before, "Native production changed the selected bootstrap source"


def prepare_bootstrap(workspace):
    from bl_catalog import native

    source = workspace / "bootstrap"
    source.mkdir(mode=0o700)
    database = workspace / "seed.sqlite"
    native.init_database(database)
    native.apply_packet(database, packet(bootstrap=True))
    native.rebuild_database(database)
    info = native.stage_snapshot(database, source, BOOTSTRAP_VERSION)
    (source / "current").write_text(BOOTSTRAP_VERSION + "\n", encoding="utf-8")
    for path in source.iterdir():
        path.chmod(0o444)
    assert (
        hashlib.sha256((source / f"{BOOTSTRAP_VERSION}.sqlite").read_bytes()).hexdigest()
        == info["sha256"]
    )
    return source, info


def prepare_catalogue(root):
    """Copy the existing synthetic bootstrap into an empty caller-owned mount."""
    assert root.is_dir() and not root.is_symlink(), "Catalogue fixture requires a directory"
    assert not any(root.iterdir()), "Catalogue fixture requires an empty directory"
    with tempfile.TemporaryDirectory(prefix="librarium-runtime-reference-") as workspace:
        source, pin = prepare_bootstrap(Path(workspace))
        for path in source.iterdir():
            shutil.copy2(path, root / path.name)
    return {"version": pin["version"], "sha256": pin["sha256"]}


def publication(published, receipt):
    from librarium import catalogue

    with catalogue.snapshot(
        str(published), receipt["version"], receipt["sha256"], fixture=True
    ) as (db, info):
        works = [dict(row) for row in db.execute("SELECT id,title FROM work ORDER BY id")]
        records = [
            dict(row)
            for row in db.execute(
                "SELECT content_hash,last_seen_at FROM source_record "
                "WHERE source='lexicanum' AND native_id='fixture-1' ORDER BY fetched_at,id"
            )
        ]
    assert info["version"] == receipt["version"] and info["sha256"] == receipt["sha256"]
    return works, records


def refused(action, error_type):
    try:
        action()
    except error_type:
        return
    raise AssertionError("The native producer accepted a request that should be refused")


def replay_in_new_process(state, source, raw):
    from librarium import reference_production

    program = """
import os,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','librarium.settings')
import django
django.setup()
from django.core.management import call_command
from unittest.mock import patch
with patch('socket.socket',side_effect=AssertionError('Native producer attempted network access')):
    call_command('reference_import','-',request_key=sys.argv[1])
"""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "librarium.settings",
        "PYTHONPATH": str(Path(reference_production.__file__).resolve().parents[1]),
        "LIBRARIUM_REFERENCE_STATE_DIR": str(state),
        "LIBRARIUM_CATALOGUE_DIR": str(source),
        "LIBRARIUM_CATALOGUE_FIXTURE": "1",
        "LIBRARIUM_LIBRARY_URL": "",
        "LIBRARIUM_DIRECT_LIBRARY_ROOT": "",
        "LIBRARIUM_ARTIFACT_DIR": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", program, FIRST_KEY],
        input=raw,
        capture_output=True,
        timeout=15,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert len(result.stdout) < 64 * 1024, "The native receipt exceeded its output limit"
    return json.loads(result.stdout)


def exercise(workspace):
    from django.core.management import call_command
    from django.test import RequestFactory, override_settings
    from librarium import catalogue_control, reference_production

    assert os.geteuid() != 0, "The packaged producer must run as a non-root user"
    workspace = Path(workspace)
    with offline():
        source, bootstrap = prepare_bootstrap(workspace)
        original = tree_state(source)
        state = workspace / "reference"
        state.mkdir(mode=0o700)
        with override_settings(
            LIBRARIUM_REFERENCE_STATE_DIR=str(state),
            LIBRARIUM_CATALOGUE_DIR=str(source),
            LIBRARIUM_CATALOGUE_FIXTURE=True,
            LIBRARIUM_LIBRARY_URL="",
            DIRECT_LIBRARY_ROOT="",
            LIBRARIUM_ARTIFACT_DIR="",
        ):
            output = io.StringIO()
            first_raw = encoded(packet())
            call_command(
                "reference_import",
                "-",
                request_key=FIRST_KEY,
                bootstrap_version=bootstrap["version"],
                bootstrap_sha256=bootstrap["sha256"],
                stdin=io.StringIO(first_raw.decode()),
                stdout=output,
            )
            first = json.loads(output.getvalue())
            assert first["state"] == "succeeded" and first["fixture"] is True
            assert first["packet_sha256"] == hashlib.sha256(first_raw).hexdigest()
            published = state / "published"
            first_works, _ = publication(published, first)
            assert len(first_works) == 1 and first_works[0]["title"] == "Fixture Native Book"
            before_replay = tree_state(published)
            replay = reference_production.import_packet(first_raw, FIRST_KEY)
            assert replay == first
            assert tree_state(published) == before_replay, (
                "A repeated request published another snapshot"
            )

            latest_raw = encoded(packet(revised=True))
            latest = reference_production.import_packet(latest_raw, SECOND_KEY)
            assert latest["state"] == "succeeded" and latest["version"] != first["version"]
            latest_works, history = publication(published, latest)
            assert latest_works == [
                {"id": first_works[0]["id"], "title": "Fixture Native Book Revised"}
            ]
            assert len(history) == 2 and len({row["content_hash"] for row in history}) == 2
            latest_seen = [datetime.fromisoformat(row["last_seen_at"]) for row in history]
            assert latest_seen == [
                datetime.fromisoformat("2026-10-28T12:00:00+00:00"),
                datetime.fromisoformat("2026-10-28T13:00:00+00:00"),
            ]
            assert publication(published, first)[0] == first_works, (
                "A new update changed an earlier snapshot"
            )
            before_reopen = tree_state(published)
            assert replay_in_new_process(state, source, first_raw) == first
            assert tree_state(published) == before_reopen, (
                "Reopening an old request changed the current publication"
            )

            status = reference_production.status()
            assert status["status"] == "manual" and status["current"]["sha256"] == latest["sha256"]
            assert status["last_outcome"]["request_key"] == SECOND_KEY
            assert status["last_outcome"]["state"] == "succeeded"
            with override_settings(LIBRARIUM_CATALOGUE_DIR=str(published)):
                request = RequestFactory().get(
                    "/api/catalogue/control",
                    {
                        "version": latest["version"],
                        "sha256": latest["sha256"],
                    },
                )
                control = catalogue_control.control(request)
                assert control.status_code == 200, control.content
                assert json.loads(control.content)["producer"]["status"] == "manual"

            active = tree_state(published)
            refused(
                lambda: reference_production.import_packet(latest_raw, FIRST_KEY),
                reference_production.ProductionError,
            )
            refused(
                lambda: reference_production.import_packet(
                    encoded({**packet(), "schema": "invalid"}), INVALID_KEY
                ),
                reference_production.ProductionError,
            )
            blocked = packet(revised=True)
            blocked["observed_at"] = "2026-10-28T14:00:00Z"
            blocked["records"][0]["title"] = "Fixture Native Book Held"
            mode = stat.S_IMODE(published.stat().st_mode)
            published.chmod(0o500)
            try:
                refused(
                    lambda: reference_production.import_packet(encoded(blocked), BLOCKED_KEY),
                    reference_production.ProductionError,
                )
            finally:
                published.chmod(mode)
            assert tree_state(published) == active, "A refused request changed the active snapshot"
            unchanged(source, original)
            return {
                "work_id": first_works[0]["id"],
                "history_records": len(history),
                "stable_identity": True,
                "idempotent": True,
                "reopened": True,
                "source_unchanged": True,
                "producer_status": status["status"],
                "refused_requests": 3,
            }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if len(sys.argv) != 3 or sys.argv[1] != "prepare-catalogue":
            raise SystemExit("Use prepare-catalogue with an empty fixture directory")
        with offline():
            result = prepare_catalogue(Path(sys.argv[2]))
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "librarium.settings")
    import django

    django.setup()
    with tempfile.TemporaryDirectory(prefix="librarium-reference-image-") as workspace:
        result = exercise(Path(workspace))
    print(
        "PASS: offline native reference import, stable identity, immutable publication, replay and preserved bootstrap"
    )
    print(json.dumps(result, sort_keys=True))
