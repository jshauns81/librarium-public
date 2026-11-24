"""Real pinned server on loopback; all books, users and journals are disposable."""

import importlib.util
import json
import os
import secrets
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from hashlib import file_digest, sha256
from pathlib import Path

import pytest
from librarium.delivery_broker import Broker, BrokerError
from librarium.delivery_content_server import ContentServer

PROJECT = Path(__file__).resolve().parents[1]


# Generated per run; a long random secret is required by the transport.
PASSWORD = secrets.token_urlsafe(32)


@pytest.fixture
def server(tmp_path, request):
    configured = os.environ.get("LIBRARIUM_CALIBRE_RUNTIME")
    if not configured:
        if os.environ.get("LIBRARIUM_REQUIRE_NATIVE") == "1":
            pytest.fail("pinned runtime required")
        pytest.skip("pinned synthetic Calibre runtime required")
    runtime = Path(configured)
    pin = json.loads((PROJECT / "scripts/calibre_delivery_runtime.json").read_text())
    with (runtime.parent / "calibre-9.17.0-x86_64.txz").open("rb") as stream:
        assert file_digest(stream, "sha256").hexdigest() == pin["sha256"]
    spec = importlib.util.spec_from_file_location(
        "epub_fixture", PROJECT / ".github/scripts/synthetic_epub_fixtures.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    original = helper.sources()["epub3"]
    output = helper.epub3(title="Synthetic output", creators=["Fixture Author"], complete_nav=True)
    source = tmp_path / "source.epub"
    source.write_bytes(original)
    env = {
        **os.environ,
        "CALIBRE_CONFIG_DIRECTORY": str(tmp_path / "config"),
        "QT_QPA_PLATFORM": "offscreen",
    }
    subprocess.run(
        [
            str(runtime / "calibredb"),
            "add",
            "--with-library",
            str(tmp_path / "library"),
            str(source),
        ],
        env=env,
        capture_output=True,
        check=True,
    )
    with closing(
        sqlite3.connect((tmp_path / "library/metadata.db").as_uri() + "?mode=ro", uri=True)
    ) as db:
        library_uuid = db.execute("SELECT uuid FROM library_id").fetchone()[0]
        book_uuid = db.execute("SELECT uuid FROM books WHERE id=1").fetchone()[0]
    # Create the synthetic account without putting a password into command arguments.
    account = tmp_path / "account"
    account.write_text(PASSWORD)
    account.chmod(0o600)
    setup = tmp_path / "users.py"
    setup.write_text(
        "from calibre.srv.users import UserManager\nimport sys\n"
        "UserManager(sys.argv[-1]).add_user('fixture', open(sys.argv[-2]).read())\n"
    )
    subprocess.run(
        [
            str(runtime / "calibre-debug"),
            "-e",
            str(setup),
            "--",
            str(account),
            str(tmp_path / "users.sqlite"),
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    port = os.environ.get("LIBRARIUM_CALIBRE_PORT", "8168")
    adapter = ContentServer(
        "http://127.0.0.1:" + port,
        "library",
        library_uuid,
        username="fixture",
        password=PASSWORD,
    )
    log = (tmp_path / "server.log").open("wb")
    process = subprocess.Popen(
        [
            str(runtime / "calibre-debug"),
            "-e",
            str(PROJECT / "scripts/calibre_content_server_fixture.py"),
            "--",
            str(tmp_path / "library"),
            "--listen-on=127.0.0.1",
            "--port=" + port,
            "--enable-auth",
            "--auth-mode=" + getattr(request, "param", "digest"),
            "--userdb=" + str(tmp_path / "users.sqlite"),
        ],
        env={**env, "LIBRARIUM_SERVER_FIXTURE_ROOT": str(tmp_path)},
        stdout=log,
        stderr=log,
    )
    target = {"library_uuid": library_uuid, "book_id": "1", "book_uuid": book_uuid}
    deadline = time.monotonic() + 20
    try:
        while True:
            assert process.poll() is None, (tmp_path / "server.log").read_text()
            try:
                adapter.observe(target)
                break
            except BrokerError:
                assert time.monotonic() < deadline, (tmp_path / "server.log").read_text()
                time.sleep(0.05)
        state = tmp_path / "state"
        state.mkdir(mode=0o700)
        broker = Broker(state, adapter)
        yield adapter, broker, target, original, output, process, tmp_path
        broker.close()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        log.close()


def intent(adapter, target, output, mode="delivery"):
    return {
        "operation_id": str(uuid.uuid4()),
        "target": target,
        "before": adapter.observe(target),
        "output": {"sha256": sha256(output).hexdigest(), "size": len(output)},
        "mode": mode,
    }


@pytest.mark.parametrize("server", ["digest"], indirect=True)
def test_deliver_and_guarded_undo(server):
    adapter, broker, target, original, output, _, _ = server
    assert adapter.format(1, "EPUB") == original
    with pytest.raises(BrokerError, match="target_changed"):
        adapter.observe({**target, "book_uuid": str(uuid.uuid4())})
    with pytest.raises(BrokerError, match="target_changed"):
        adapter.observe({**target, "library_uuid": str(uuid.uuid4())})
    request = intent(adapter, target, output)
    receipt = broker.execute(request, output)
    assert receipt["classification"] == "applied"
    assert adapter.format(1, "EPUB") == output
    undo = intent(adapter, target, original, "undo")
    assert broker.execute(undo, original)["classification"] == "applied"
    assert adapter.format(1, "EPUB") == original
    assert broker.execute(undo, original)["classification"] == "applied"


@pytest.mark.parametrize("mode", ["delivery", "undo"])
def test_changed_bytes_refuse_without_a_send(server, mode):
    adapter, broker, target, original, output, _, _ = server
    if mode == "undo":
        assert (
            broker.execute(intent(adapter, target, output), output)["classification"] == "applied"
        )
        original, output = output, original
    request = intent(adapter, target, output, mode)
    adapter.replace(target, original + b"later change")
    assert broker.execute(request, output)["classification"] == "not_applied"
    assert adapter.format(1, "EPUB") == original + b"later change"
    # Nothing was sent, so the refusal stays with this request.
    assert not broker.paused()


def test_lost_reply_never_resends_and_keeps_global_hold(server):
    adapter, broker, target, _, output, _, _ = server
    request = intent(adapter, target, output)
    replace = adapter.replace
    calls = []

    def lost(target, data):
        calls.append(target)
        replace(target, data)
        raise BrokerError("server_unavailable")

    adapter.replace = lost
    with pytest.raises(BrokerError):
        broker.execute(request, output)
    assert broker.reconcile(request["operation_id"])["classification"] == "applied"
    assert broker.execute(request, output)["classification"] == "applied"
    assert len(calls) == 1
    with pytest.raises(BrokerError, match="recovery_required"):
        broker.execute(intent(adapter, target, output), output)


def test_server_killed_after_send_started_holds_without_resend(server):
    adapter, broker, target, _, output, process, _ = server
    request = intent(adapter, target, output)

    def boundary(stage):
        if stage == "send_started":
            process.kill()
            process.wait(timeout=10)

    broker.boundary = boundary
    with pytest.raises(BrokerError):
        broker.execute(request, output)
    assert broker.reconcile(request["operation_id"])["classification"] == "unobservable"
    assert broker.paused()


def test_plugin_transformation_diverges_and_pauses(server):
    adapter, broker, target, _, output, _, root = server
    request = intent(adapter, target, output)
    (root / "transform-arm").touch()
    receipt = broker.execute(request, output)
    assert receipt["classification"] == "diverged"
    assert receipt["reason"] == "readback_mismatch"
    assert broker.paused()


@pytest.mark.parametrize("mode", ["delivery", "undo"])
def test_real_server_sigkill_during_format_copy(server, mode):
    from concurrent.futures import ThreadPoolExecutor

    adapter, broker, target, original, output, process, root = server
    if mode == "undo":
        assert (
            broker.execute(intent(adapter, target, output), output)["classification"] == "applied"
        )
        original, output = output, original
    request = intent(adapter, target, output, mode)
    (root / "kill-arm").touch()
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(broker.execute, request, output)
        deadline = time.monotonic() + 20
        while not (root / "copy-paused").exists():
            assert not pending.done(), pending.result()
            assert time.monotonic() < deadline
            time.sleep(0.02)
        process.kill()
        process.wait(timeout=10)
        with pytest.raises(BrokerError):
            pending.result(timeout=10)
    assert broker.paused()
    assert broker.reconcile(request["operation_id"])["classification"] == "unobservable"
    # Inspect the stopped synthetic library only: Calibre's atomic replace kept the original.
    with closing(
        sqlite3.connect((root / "library/metadata.db").as_uri() + "?mode=ro", uri=True)
    ) as db:
        folder = db.execute("SELECT path FROM books WHERE id=1").fetchone()[0]
        name = db.execute("SELECT name FROM data WHERE book=1 AND format='EPUB'").fetchone()[0]
    assert (root / "library" / folder / (name + ".epub")).read_bytes() == original


def test_receipt_remains_stable_after_server_housekeeping(server):
    adapter, broker, target, _, output, _, _ = server
    before = adapter.request("/ajax/book/1/library?category_urls=false")
    request = intent(adapter, target, output)
    assert broker.execute(request, output)["classification"] == "applied"
    time.sleep(3)
    after = adapter.request("/ajax/book/1/library?category_urls=false")
    drift = {
        k: (before.get(k), after.get(k))
        for k in before.keys() | after.keys()
        if before.get(k) != after.get(k) and k not in {"last_modified", "format_metadata", "pages"}
    }
    assert not drift, drift
    assert broker.reconcile(request["operation_id"])["classification"] == "applied"
