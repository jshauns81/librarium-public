"""Real SIGKILL writer proof, using only fresh pinned-Calibre synthetic libraries."""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from hashlib import file_digest, sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT = Path(__file__).resolve().parents[2]
STAGES = (
    "prepared",
    "send_started",
    "native_copy",
    "native_returned",
    "readback",
    "receipt",
)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def put(path, value):
    pending = path.with_name(path.name + ".pending")
    pending.write_text(json.dumps(value))
    pending.chmod(0o600)
    os.replace(pending, path)


def load(path):
    return json.loads(path.read_text())


def child(phase, root):
    sys.path.insert(0, str(PROJECT / "backend"))
    from calibre.db.legacy import LibraryDatabase
    from librarium.delivery_broker import Broker
    from librarium.delivery_native import NativeOwner

    marker = load(root / "fixture.json")
    database = LibraryDatabase(str(root / "library"))
    stage = os.environ.get("PROOF_KILL_STAGE")
    mode = os.environ["PROOF_OPERATION_MODE"]

    def boundary(name):
        if phase == "execute" and name == stage:
            put(root / "paused.json", {"stage": name})
            while True:
                signal.pause()

    owner = NativeOwner(
        database.new_api,
        marker["library_uuid"],
        boundary=boundary if stage == "native_copy" else None,
    )
    target = {
        "library_uuid": marker["library_uuid"],
        "book_id": "1",
        "book_uuid": owner.cache.field_for("uuid", 1),
    }
    broker = Broker(root / "state", owner, boundary=boundary)
    try:
        if phase == "prepare":
            output = (root / "corrected.epub").read_bytes()
            request = {
                "operation_id": str(uuid.uuid4()),
                "mode": "delivery",
                "target": target,
                "before": owner.observe(target),
                "output": {"sha256": sha256(output).hexdigest(), "size": len(output)},
            }
            if mode == "undo":
                require(
                    broker.execute(request, output)["classification"] == "applied",
                    "undo_fixture_delivery_failed",
                )
                output = (root / "original.epub").read_bytes()
                request = {
                    **request,
                    "operation_id": str(uuid.uuid4()),
                    "mode": "undo",
                    "before": owner.observe(target),
                    "output": {
                        "sha256": sha256(output).hexdigest(),
                        "size": len(output),
                    },
                }
            (root / "replacement.epub").write_bytes(output)
            put(root / "request.json", request)
        elif phase == "execute":
            broker.execute(
                load(root / "request.json"), (root / "replacement.epub").read_bytes()
            )
        else:
            request = load(root / "request.json")
            attempted_resends = 0

            def unexpected_replace(*args):
                nonlocal attempted_resends
                attempted_resends += 1
                raise RuntimeError("recovery_attempted_native_mutation")

            owner.replace = unexpected_replace
            before = owner.observe(target) if stage != "native_copy" else None
            result = broker.reconcile(request["operation_id"])
            # An execute replay is still observation-only, including after process death.
            replay = broker.execute(request, (root / "replacement.epub").read_bytes())
            require(
                replay["classification"] == result["classification"],
                "replay_changed_classification",
            )
            after = owner.observe(target) if before else None
            require(before == after, "recovery_repeated_mutation")
            put(root / "resends.json", {"count": attempted_resends})
            put(root / "result.json", result)
    finally:
        broker.close()
        database.close()


def main():
    runtime = Path(os.environ["LIBRARIUM_CALIBRE_RUNTIME"]).resolve()
    pin = load(PROJECT / "scripts/calibre_delivery_runtime.json")
    archive_path = Path(
        os.environ.get(
            "LIBRARIUM_WRITER_ARCHIVE",
            str(runtime.parent / "calibre-9.17.0-x86_64.txz"),
        )
    )
    with archive_path.open("rb") as archive:
        require(
            file_digest(archive, "sha256").hexdigest() == pin["sha256"],
            "runtime_pin_changed",
        )
    spec = spec_from_file_location(
        "synthetic_fixtures", PROJECT / ".github/scripts/synthetic_epub_fixtures.py"
    )
    fixtures = module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    report = {"resends": 0, "delivery": {}, "undo": {}}
    started = time.monotonic()
    for mode in ("delivery", "undo"):
        for stage in STAGES:
            with TemporaryDirectory(prefix="librarium-delivery-kill-") as temporary:
                root = Path(temporary)
                for leaf in ("state", "config", "scratch"):
                    (root / leaf).mkdir(mode=0o700)
                env = {
                    **os.environ,
                    "CALIBRE_CONFIG_DIRECTORY": str(root / "config"),
                    "CALIBRE_TEMP_DIR": str(root / "scratch"),
                    "QT_QPA_PLATFORM": "offscreen",
                    "PROOF_KILL_STAGE": stage,
                    "PROOF_OPERATION_MODE": mode,
                }
                (root / "original.epub").write_bytes(fixtures.sources()["epub3"])
                (root / "corrected.epub").write_bytes(
                    fixtures.epub3(
                        title="Synthetic changed output",
                        creators=["Fixture Author"],
                        complete_nav=True,
                    )
                )
                result = subprocess.run(
                    [
                        str(runtime / "calibredb"),
                        "add",
                        "--with-library",
                        str(root / "library"),
                        str(root / "original.epub"),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                require(result.returncode == 0, result.stdout + result.stderr)
                with sqlite3.connect(
                    (root / "library/metadata.db").as_uri() + "?mode=ro", uri=True
                ) as db:
                    library_uuid = db.execute("SELECT uuid FROM library_id").fetchone()[
                        0
                    ]
                put(root / "fixture.json", {"library_uuid": library_uuid})

                def launch(phase, *, root=root, env=env):
                    return subprocess.Popen(
                        [
                            str(runtime / "calibre-debug"),
                            "-e",
                            str(Path(__file__).resolve()),
                            "--",
                            "child",
                            phase,
                            str(root),
                        ],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        start_new_session=True,
                    )

                prepared = launch("prepare")
                stdout, stderr = prepared.communicate(timeout=20)
                require(prepared.returncode == 0, stdout + stderr)
                process = launch("execute")
                try:
                    deadline = time.monotonic() + 20
                    while not (root / "paused.json").exists():
                        if process.poll() is not None:
                            stdout, stderr = process.communicate()
                            raise RuntimeError(stdout + stderr)
                        require(
                            time.monotonic() < deadline,
                            "native_boundary_timeout:" + stage,
                        )
                        time.sleep(0.02)
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=10)
                    require(
                        load(root / "paused.json")["stage"] == stage,
                        "wrong_native_boundary",
                    )
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate(timeout=10)
                recovered = launch("reconcile")
                stdout, stderr = recovered.communicate(timeout=20)
                require(recovered.returncode == 0, stdout + stderr)
                report[mode][stage] = load(root / "result.json")["classification"]
                report["resends"] += load(root / "resends.json")["count"]
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child(sys.argv[2], Path(sys.argv[3]))
    else:
        main()
