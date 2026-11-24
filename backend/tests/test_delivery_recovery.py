"""A verified recovery baseline is required for each content-server operation."""

import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from librarium.delivery_authorization import seal
from librarium.delivery_writer import WriterError
from test_delivery_writer import KEY, writer_grant


def session(payload):
    payload["supervised_session"] = {
        "session_id": str(uuid.uuid4()),
        "target": payload["request"]["target"],
        "confirmed_by_sha256": "a" * 64,
        "confirmed_at": datetime.now(UTC).isoformat(),
        "other_writers_stopped": True,
    }
    return payload["supervised_session"]["session_id"]


def backup_fixture(tmp_path, broker, artifacts):
    root = tmp_path / "backup"
    root.mkdir(mode=0o700)
    for kind in ("library", "broker"):
        (root / kind).mkdir(mode=0o700)
    shutil.copytree(artifacts, root / "artifacts")
    with closing(sqlite3.connect(root / "library/metadata.db")) as db, db:
        db.execute("CREATE TABLE library_id(uuid TEXT)")
        db.execute("INSERT INTO library_id VALUES (?)", ("fixture-library",))
    with closing(sqlite3.connect(root / "broker/journal.sqlite3")) as db:
        broker.db.backup(db)
    (root / "library/book").mkdir()
    (root / "library/book/content.epub").write_bytes(b"original fixture book")
    (root / "artifacts/unrelated").write_bytes(b"retained unrelated evidence")
    (root / "broker/journal.identity").write_text(broker.journal_id)
    (root / "database.dump").write_bytes(b"synthetic-dump-for-byte-integrity-tests")
    for path in root.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return root


def ready(tmp_path, mode="delivery"):
    from librarium.delivery_recovery import RecoveryGate, capture_baseline, verify_baseline

    owner, broker, service, payload = writer_grant(tmp_path, mode)
    owner.supervised = owner.recovery_required = True
    sid = session(payload)
    root = backup_fixture(tmp_path, broker, service.artifacts)
    manifest = capture_baseline(root, sid)
    verification = verify_baseline(root, sid)
    payload["supervised_session"]["confirmed_at"] = datetime.now(UTC).isoformat()
    service.recovery = RecoveryGate(root)
    return owner, broker, service, payload, root, manifest, verification


def test_operational_writer_refuses_without_a_verified_baseline(tmp_path):
    owner, broker, service, payload = writer_grant(tmp_path)
    owner.supervised = owner.recovery_required = True
    session(payload)
    with pytest.raises(WriterError, match="recovery_baseline_required"):
        service.execute(seal(payload, KEY))
    assert owner.calls == 0
    assert broker.existing(payload["request"]["operation_id"]) is None
    assert not broker.paused()
    broker.close()


@pytest.mark.parametrize("mode", ["delivery", "undo"])
def test_verified_baseline_binds_recovery_manifest_before_send_and_replay_needs_no_backup(
    tmp_path, mode
):
    owner, broker, service, payload, root, manifest, verification = ready(tmp_path, mode)
    operation = payload["request"]["operation_id"]
    seen = []

    def boundary(stage):
        if stage == "send_started":
            saved = json.loads((broker.root / "recovery" / (operation + ".json")).read_bytes())
            assert saved["baseline"]["generation_id"] == manifest["generation_id"]
            assert saved["baseline"]["manifest_sha256"] == verification["manifest_sha256"]
            assert saved["original"] == payload["original"]
            assert saved["replacement"] == payload["replacement"]
            assert saved["session"] == payload["supervised_session"]
            seen.append(stage)

    broker.boundary = boundary
    grant = seal(payload, KEY)
    assert service.execute(grant)["classification"] == "applied"
    assert seen == ["send_started"]
    shutil.rmtree(root)
    assert service.execute(grant)["classification"] == "applied"
    assert broker.reconcile(operation)["classification"] == "applied"
    assert owner.calls == 1
    broker.close()


@pytest.mark.parametrize(
    "change",
    [
        "missing_receipt",
        "manifest",
        "original",
        "replacement",
        "validation",
        "session",
        "journal",
        "component",
    ],
)
def test_invalid_baseline_refuses_before_intent(tmp_path, change):
    owner, broker, service, payload, root, _, _ = ready(tmp_path)
    sid = payload["supervised_session"]["session_id"]
    if change == "missing_receipt":
        (root / "verifications" / (sid + ".json")).unlink()
    elif change == "manifest":
        (root / "manifest.json").write_text("{}")
    elif change in {"original", "replacement", "validation"}:
        descriptor = payload[change]
        (root / "artifacts" / (descriptor["kind"] + "-" + descriptor["sha256"])).write_bytes(
            b"changed"
        )
    elif change == "session":
        session(payload)
    elif change == "journal":
        receipt = root / "verifications" / (sid + ".json")
        value = json.loads(receipt.read_bytes())
        value["journal_id"] = str(uuid.uuid4())
        receipt.write_text(json.dumps(value))
    else:
        (root / "database.dump").write_bytes(b"changed")
    with pytest.raises(WriterError, match="recovery_"):
        service.execute(seal(payload, KEY))
    assert owner.calls == 0
    assert broker.existing(payload["request"]["operation_id"]) is None
    assert not broker.paused()
    broker.close()


@pytest.mark.parametrize("stage", ["prepared", "send_started"])
def test_changed_backup_during_preflight_never_sends_and_post_intent_keeps_hold(tmp_path, stage):
    owner, broker, service, payload, root, _, _ = ready(tmp_path)

    def change(name):
        if name == stage:
            (root / "manifest.json").write_text("{}")

    broker.boundary = change
    with pytest.raises(WriterError, match="recovery_"):
        service.execute(seal(payload, KEY))
    assert owner.calls == 0
    assert broker.paused() is (stage == "send_started")
    recorded = broker.existing(payload["request"]["operation_id"])
    assert recorded
    assert not any(name == "receipt" for name, _ in recorded[1])
    broker.close()


def test_unrelated_journal_advancement_invalidates_baseline(tmp_path):
    owner, broker, service, payload, _, _, _ = ready(tmp_path)
    other = dict(payload["request"], operation_id=str(uuid.uuid4()))
    broker.cancel(other)
    with pytest.raises(WriterError, match="recovery_journal_changed"):
        service.execute(seal(payload, KEY))
    assert owner.calls == 0
    broker.close()


def test_equal_counts_with_different_historical_journal_bytes_refuse(tmp_path):
    from librarium.delivery_broker import canonical, fingerprint
    from librarium.delivery_recovery import RecoveryGate, capture_baseline, verify_baseline

    owner, broker, service, payload = writer_grant(tmp_path)
    owner.supervised = owner.recovery_required = True
    sid = session(payload)
    other = dict(payload["request"], operation_id=str(uuid.uuid4()))
    broker.cancel(other)
    root = backup_fixture(tmp_path, broker, service.artifacts)
    capture_baseline(root, sid)
    verify_baseline(root, sid)
    payload["supervised_session"]["confirmed_at"] = datetime.now(UTC).isoformat()
    service.recovery = RecoveryGate(root)
    broker.db.execute("DROP TRIGGER operations_no_update")
    other["mode"] = "undo"
    broker.db.execute(
        "UPDATE operations SET request_sha256=?,payload=? WHERE id=?",
        (fingerprint(other), canonical(other).decode(), other["operation_id"]),
    )
    try:
        with pytest.raises(WriterError, match="recovery_journal_changed"):
            service.execute(seal(payload, KEY))
        assert owner.calls == 0
    finally:
        broker.close()


@pytest.mark.parametrize("action", ["capture", "verify"])
def test_offline_caller_can_retry_after_fsync_failure_without_replacing_evidence(
    tmp_path, monkeypatch, action
):
    import os

    from librarium import delivery_recovery as recovery

    _owner, broker, service, payload = writer_grant(tmp_path)
    sid = session(payload)
    root = backup_fixture(tmp_path, broker, service.artifacts)
    if action == "verify":
        recovery.capture_baseline(root, sid)
    original = os.fsync
    calls = []

    def fail(fd):
        calls.append(fd)
        if len(calls) == (1 if action == "capture" else 2):
            raise OSError("synthetic sync failure")
        original(fd)

    monkeypatch.setattr(recovery.os, "fsync", fail)
    run = recovery.capture_baseline if action == "capture" else recovery.verify_baseline
    path = (
        root / "manifest.json" if action == "capture" else root / "verifications" / (sid + ".json")
    )
    try:
        with pytest.raises(WriterError, match="recovery_"):
            run(root, sid)
        before = path.read_bytes()
        monkeypatch.setattr(recovery.os, "fsync", original)
        value = run(root, sid)
        assert value["session_id"] == sid
        assert path.read_bytes() == before
    finally:
        broker.close()


def test_verification_pins_only_the_bytes_it_actually_hashed(tmp_path, monkeypatch):
    from librarium import delivery_recovery as recovery

    _owner, broker, service, payload = writer_grant(tmp_path)
    sid = session(payload)
    root = backup_fixture(tmp_path, broker, service.artifacts)
    recovery.capture_baseline(root, sid)
    original = recovery.baseline_facts

    def change_after_hashing(root):
        value = original(root)
        (root / "library/book/content.epub").write_bytes(b"changed after hashing")
        return value

    monkeypatch.setattr(recovery, "baseline_facts", change_after_hashing)
    try:
        with pytest.raises(WriterError, match="recovery_evidence_changed"):
            recovery.verify_baseline(root, sid)
        assert not (root / "verifications" / (sid + ".json")).exists()
    finally:
        broker.close()


@pytest.mark.parametrize("stage", ["prepared", "send_started"])
def test_recovery_package_is_rechecked_before_send(tmp_path, stage):
    owner, broker, service, payload, _, _, _ = ready(tmp_path)
    path = broker.root / "recovery" / (payload["request"]["operation_id"] + ".json")

    def change(name):
        if name == stage:
            path.write_bytes(b"{}")

    broker.boundary = change
    try:
        with pytest.raises(WriterError, match="recovery_package_changed"):
            service.execute(seal(payload, KEY))
        assert owner.calls == 0
        assert broker.paused() is (stage == "send_started")
    finally:
        broker.close()


def test_existing_identical_bytes_are_synced_after_a_previous_sync_failure(tmp_path, monkeypatch):
    import os

    from librarium import delivery_recovery as recovery

    calls = []

    def fail(fd):
        calls.append(fd)
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(recovery.os, "fsync", fail)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for _ in range(2):
            with pytest.raises(WriterError, match="recovery_evidence_unavailable"):
                recovery.write_new(fd, "operation.json", {"binding": "fixture"})
        assert len(calls) == 2
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "change", ["unknown", "duplicate", "future", "naive", "library", "mode", "symlink"]
)
def test_verification_receipt_is_strict_and_protected(tmp_path, change):
    owner, broker, service, payload, root, _, _ = ready(tmp_path)
    path = root / "verifications" / (payload["supervised_session"]["session_id"] + ".json")
    value = json.loads(path.read_bytes())
    if change == "unknown":
        value["restore_tested"] = True
    elif change == "future":
        value["verified_at"] = "2999-01-01T00:00:00+00:00"
    elif change == "naive":
        value["verified_at"] = "2026-01-01T00:00:00"
    elif change == "library":
        value["library_uuid"] = "other-library"
    elif change == "mode":
        path.chmod(0o644)
    elif change == "symlink":
        moved = root / "other.json"
        path.rename(moved)
        path.symlink_to(moved)
    if change not in {"mode", "symlink"}:
        text = json.dumps(value)
        if change == "duplicate":
            text = text[:-1] + ',"schema":"librarium.recovery-verification.v1"}'
        path.write_text(text)
    try:
        with pytest.raises(WriterError, match="recovery_"):
            service.execute(seal(payload, KEY))
        assert owner.calls == 0
    finally:
        broker.close()


def test_write_failure_cannot_record_intent_or_reach_the_owner(tmp_path, monkeypatch):
    from librarium import delivery_recovery as recovery

    owner, broker, service, payload, _, _, _ = ready(tmp_path)

    def unavailable(*args):
        raise OSError("synthetic capacity failure")

    monkeypatch.setattr(recovery.os, "fsync", unavailable)
    try:
        with pytest.raises(WriterError, match="recovery_evidence_unavailable"):
            service.execute(seal(payload, KEY))
        assert owner.calls == 0
        assert broker.existing(payload["request"]["operation_id"]) is None
        assert not broker.paused()
    finally:
        broker.close()


def test_runtime_does_not_rehash_the_whole_library(tmp_path, monkeypatch):
    from librarium import delivery_recovery as recovery

    owner, broker, service, payload, _, _, _ = ready(tmp_path)
    monkeypatch.setattr(recovery, "inventory", lambda *args: pytest.fail("runtime inventory"))
    try:
        assert service.execute(seal(payload, KEY))["classification"] == "applied"
        assert owner.calls == 1
    finally:
        broker.close()


@pytest.mark.parametrize("name", ["library/book/content.epub", "artifacts/unrelated"])
def test_mutated_nested_baseline_evidence_refuses_even_when_not_selected(tmp_path, name):
    owner, broker, service, payload, root, _, _ = ready(tmp_path)
    (root / name).write_bytes(b"changed evidence")
    try:
        with pytest.raises(WriterError, match="recovery_"):
            service.execute(seal(payload, KEY))
        assert owner.calls == 0
        assert broker.existing(payload["request"]["operation_id"]) is None
    finally:
        broker.close()


@pytest.mark.parametrize("mode", ["delivery", "undo"])
@pytest.mark.parametrize("stage", ["prepared", "final"])
@pytest.mark.parametrize("expiry", ["review", "session"])
def test_authority_expiring_during_recovery_read_is_rechecked(
    tmp_path, monkeypatch, mode, stage, expiry
):
    from librarium import delivery_session, delivery_writer

    owner, broker, service, payload, _, _, _ = ready(tmp_path, mode)
    started = datetime.now(UTC)

    class Clock(datetime):
        current = started

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(delivery_writer, "datetime", Clock)
    monkeypatch.setattr(delivery_session, "datetime", Clock)
    payload["review_expires_at"] = (
        started + timedelta(minutes=1 if expiry == "review" else 10)
    ).isoformat()
    check = service.recovery.check_operation
    calls = []

    def expire(*args):
        result = check(*args)
        calls.append(1)
        if len(calls) == (1 if stage == "prepared" else 2):
            Clock.current = started + timedelta(minutes=2 if expiry == "review" else 6)
        return result

    monkeypatch.setattr(service.recovery, "check_operation", expire)
    try:
        result = service.execute(seal(payload, KEY))
        assert result["classification"] == "not_applied"
        assert result["reason"] == "sealed_stale_grant"
        assert owner.calls == 0
        assert not broker.paused()
        if stage == "prepared":
            assert not any(
                name == "send_started"
                for name, _ in broker.existing(payload["request"]["operation_id"])[1]
            )
    finally:
        broker.close()


def test_content_server_configuration_has_no_optional_recovery_bypass(tmp_path, monkeypatch):
    import secrets

    from librarium.delivery_content_server import ContentServer
    from librarium.delivery_writer import WriterService

    owner, broker, service, payload = writer_grant(tmp_path)
    session(payload)
    adapter = ContentServer(
        "http://127.0.0.1:8168",
        "library",
        "fixture-library",
        username="fixture",
        password=secrets.token_urlsafe(32),
    )
    broker.owner = adapter
    monkeypatch.delenv("LIBRARIUM_DELIVERY_RECOVERY_DIR", raising=False)
    monkeypatch.setenv("LIBRARIUM_DELIVERY_RECOVERY_ENABLED", "0")
    service = WriterService(broker, service.artifacts, KEY, "a" * 64)
    try:
        with pytest.raises(WriterError, match="recovery_baseline_required"):
            service.execute(seal(payload, KEY))
        assert owner.calls == 0
        assert broker.existing(payload["request"]["operation_id"]) is None
    finally:
        broker.close()


@pytest.mark.parametrize("components", [None, 1, [], "invalid"])
def test_cli_capture_redacts_malformed_existing_manifest(tmp_path, components):
    import subprocess
    import sys
    from pathlib import Path

    _owner, broker, _service, payload, root, manifest, _receipt = ready(tmp_path)
    try:
        manifest["components"] = components
        (root / "manifest.json").write_text(json.dumps(manifest))
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "scripts/delivery_recovery.py"),
                "capture",
                "--root",
                str(root),
                "--session-id",
                payload["supervised_session"]["session_id"],
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 1
        assert json.loads(result.stdout) == {"error": "recovery_evidence_invalid"}
        assert result.stderr == ""
        assert str(root) not in result.stdout
    finally:
        broker.close()


def test_cli_verifies_existing_backup_and_never_echoes_private_paths(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    from librarium.delivery_recovery import capture_baseline

    _owner, broker, service, payload = writer_grant(tmp_path)
    sid = session(payload)
    root = backup_fixture(tmp_path, broker, service.artifacts)
    capture_baseline(root, sid)
    project = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        str(project / "scripts/delivery_recovery.py"),
        "verify",
        "--root",
        str(root),
        "--session-id",
        sid,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["session_id"] == sid
        assert str(root) not in result.stdout + result.stderr
        broken = subprocess.run(
            command[:-1] + ["invalid"], capture_output=True, text=True, check=False
        )
        assert broken.returncode == 1
        assert json.loads(broken.stdout) == {"error": "recovery_binding_invalid"}
        assert str(root) not in broken.stdout + broken.stderr
    finally:
        broker.close()


@pytest.mark.parametrize(
    "change", ["symlink", "hardlink", "special", "component_missing", "source_changed"]
)
def test_offline_verification_refuses_incomplete_or_aliased_components(tmp_path, change):
    from librarium.delivery_recovery import capture_baseline, verify_baseline

    _owner, broker, service, payload = writer_grant(tmp_path)
    sid = session(payload)
    root = backup_fixture(tmp_path, broker, service.artifacts)
    path = root / "library/extra"
    if change == "symlink":
        path.symlink_to(root / "database.dump")
    elif change == "hardlink":
        import os

        os.link(root / "database.dump", path)
    elif change == "special":
        import os

        os.mkfifo(path)
    elif change == "component_missing":
        (root / "database.dump").unlink()
    else:
        capture_baseline(root, sid)
        (root / "library/metadata.db").write_bytes(b"changed")
        with pytest.raises(WriterError, match="recovery_"):
            verify_baseline(root, sid)
        broker.close()
        return
    with pytest.raises(WriterError, match="recovery_"):
        capture_baseline(root, sid)
    assert not (root / "manifest.json").exists()
    broker.close()
