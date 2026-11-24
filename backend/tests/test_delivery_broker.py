"""Persist/send failures must never turn a recovery read into a second write."""

import uuid
from copy import deepcopy
from hashlib import sha256
from threading import RLock

import pytest
from librarium.delivery_broker import Broker, BrokerError


def digest(data):
    return sha256(data).hexdigest()


class Owner:
    def __init__(self):
        self.lock = RLock()
        self.data = b"original"
        self.metadata = {"title": "Fixture", "other": digest(b"other")}
        self.calls = 0
        self.library_revision = 0

    def observe(self, target):
        if target != {
            "library_uuid": "fixture-library",
            "book_id": "1",
            "book_uuid": "fixture-book",
        }:
            raise BrokerError("target_changed")
        return {
            "sha256": digest(self.data),
            "size": len(self.data),
            "metadata": deepcopy(self.metadata),
            "inventory": digest(repr((self.metadata, self.data, self.library_revision)).encode()),
        }

    def prepare_write(self, target, size):
        pass

    def sync(self, target):
        pass

    def replace(self, target, data):
        self.data = data
        self.calls += 1


def fixture(tmp_path, boundary=lambda name: None):
    owner = Owner()
    request = {
        "operation_id": str(uuid.uuid4()),
        "target": {"library_uuid": "fixture-library", "book_id": "1", "book_uuid": "fixture-book"},
        "before": owner.observe(
            {"library_uuid": "fixture-library", "book_id": "1", "book_uuid": "fixture-book"}
        ),
        "output": {"sha256": digest(b"corrected"), "size": 9},
        "mode": "delivery",
    }
    return owner, Broker(tmp_path, owner, boundary=boundary), request


def test_persist_before_native_call_and_exact_receipt(tmp_path):
    seen = []
    owner, broker, request = fixture(tmp_path, seen.append)
    result = broker.execute(request, b"corrected")
    assert result["classification"] == "applied"
    assert result["request_sha256"] == digest(broker.canonical(request))
    assert seen == ["prepared", "send_started", "native_returned", "readback", "receipt"]
    assert broker.execute(request, b"corrected") == result
    assert owner.calls == 1
    broker.close()


@pytest.mark.parametrize(
    "boundary", ["prepared", "send_started", "native_returned", "readback", "receipt"]
)
def test_loss_at_every_boundary_recovers_without_resend(tmp_path, boundary):
    class LostReply(Exception):
        pass

    def fail(name):
        if name == boundary:
            raise LostReply

    owner, broker, request = fixture(tmp_path, fail)
    with pytest.raises(LostReply):
        broker.execute(request, b"corrected")
    calls = owner.calls
    broker.close()
    restarted = Broker(tmp_path, owner)
    result = restarted.reconcile(request["operation_id"])
    assert result["classification"] == (
        "not_applied"
        if boundary == "prepared"
        else "unobservable"
        if boundary == "send_started"
        else "applied"
    )
    restarted.execute(request, b"corrected")
    assert owner.calls == calls
    restarted.close()


def test_changed_source_and_changed_target_refuse_before_send(tmp_path):
    owner, broker, request = fixture(tmp_path)
    owner.data = b"external"
    result = broker.execute(request, b"corrected")
    assert result["classification"] == "not_applied"
    assert owner.calls == 0
    broker.close()


def test_changed_key_payload_and_digest_corruption_refuse(tmp_path):
    owner, broker, request = fixture(tmp_path)
    broker.execute(request, b"corrected")
    changed = deepcopy(request)
    changed["mode"] = "undo"
    with pytest.raises(BrokerError, match="operation_conflict"):
        broker.execute(changed, b"corrected")
    with pytest.raises(BrokerError, match="artifact_changed"):
        broker.execute({**request, "operation_id": str(uuid.uuid4())}, b"corrupted")
    assert owner.calls == 1
    broker.close()


def test_aba_keeps_applied_history_and_reports_present_drift(tmp_path):
    owner, broker, request = fixture(tmp_path)
    applied = broker.execute(request, b"corrected")
    owner.data = b"original"
    now = broker.reconcile(request["operation_id"])
    assert now["classification"] == "diverged"
    assert now["historical_receipt"] == applied
    assert now["reason"] == "epub_changed_after_receipt"
    assert owner.calls == 1
    broker.close()


def test_absent_journal_is_not_no_send_and_never_claims_causality(tmp_path):
    owner, broker, request = fixture(tmp_path)
    assert broker.reconcile(request["operation_id"])["classification"] == "unobservable"
    assert owner.calls == 0
    broker.close()


def test_failed_journal_commit_cannot_reach_mutation(tmp_path, monkeypatch):
    owner, broker, request = fixture(tmp_path)

    def full(*args, **kwargs):
        raise OSError("full")

    monkeypatch.setattr(broker, "append", full)
    with pytest.raises(OSError):
        broker.execute(request, b"corrected")
    assert owner.calls == 0
    broker.close()


@pytest.mark.parametrize("failed_commit", [1, 2, 3])
@pytest.mark.parametrize("mode", ["delivery", "undo"])
def test_failed_durable_transaction_recovers_without_false_finality(tmp_path, failed_commit, mode):
    import sqlite3

    owner, broker, request = fixture(tmp_path)
    request["mode"] = mode
    connection = broker.db

    class CommitFailure:
        commits = 0

        def execute(self, statement, *args):
            if statement == "COMMIT":
                self.commits += 1
                if self.commits == failed_commit:
                    raise sqlite3.OperationalError("injected durable transaction failure")
            return connection.execute(statement, *args)

    broker.db = CommitFailure()
    try:
        with pytest.raises(sqlite3.OperationalError, match="durable transaction failure"):
            broker.execute(request, b"corrected")
    finally:
        broker.db = connection
        broker.close()
    restarted = Broker(tmp_path, owner)
    try:
        calls = owner.calls
        outcome = restarted.reconcile(request["operation_id"])
        assert (
            outcome["classification"]
            == {1: "unobservable", 2: "not_applied", 3: "applied"}[failed_commit]
        )
        assert calls == (1 if failed_commit == 3 else 0)
        if failed_commit != 1:
            assert restarted.execute(request, b"corrected") == outcome
        assert owner.calls == calls
    finally:
        restarted.close()


def test_single_owner_journal_lock_survives_requests(tmp_path):
    owner, broker, _request = fixture(tmp_path)
    with pytest.raises(BrokerError, match="owner_busy"):
        Broker(tmp_path, owner)
    broker.close()


def test_cancellation_is_a_durable_no_send_tombstone(tmp_path):
    owner, broker, request = fixture(tmp_path)
    result = broker.cancel(request)
    assert result["classification"] == "not_applied"
    assert result["reason"] == "cancelled_before_send"
    assert broker.execute(request, b"corrected") == result
    assert owner.calls == 0
    broker.close()


def test_cancellation_after_send_returns_applied_receipt(tmp_path):
    owner, broker, request = fixture(tmp_path)
    result = broker.execute(request, b"corrected")
    assert broker.cancel(request) == result
    assert owner.calls == 1
    broker.close()


def test_guarded_undo_preserves_later_metadata_and_does_not_erase_delivery(tmp_path):
    owner, broker, request = fixture(tmp_path)
    applied = broker.execute(request, b"corrected")
    owner.metadata["title"] = "Later metadata edit"
    undo = {
        **deepcopy(request),
        "operation_id": str(uuid.uuid4()),
        "mode": "undo",
        "before": owner.observe(request["target"]),
        "output": {"sha256": digest(b"original"), "size": 8},
    }
    result = broker.execute(undo, b"original")
    assert result["classification"] == "applied"
    assert owner.metadata["title"] == "Later metadata edit"
    assert broker.existing(request["operation_id"])[1][-1] == ("receipt", applied)
    owner.data = b"later"
    second = {**undo, "operation_id": str(uuid.uuid4())}
    assert broker.execute(second, b"original")["classification"] == "not_applied"
    assert owner.data == b"later"
    broker.close()


def test_uncertain_operation_reserves_target_against_another_key(tmp_path):
    class Stopped(Exception):
        pass

    def stop(name):
        if name == "send_started":
            raise Stopped

    owner, broker, request = fixture(tmp_path, stop)
    with pytest.raises(Stopped):
        broker.execute(request, b"corrected")
    broker.boundary = lambda name: None
    with pytest.raises(BrokerError, match="target_reserved"):
        broker.execute({**request, "operation_id": str(uuid.uuid4())}, b"corrected")
    assert owner.calls == 0
    broker.close()


def test_restart_changes_boot_nonce_and_missing_journal_fails_closed(tmp_path):
    owner, broker, _ = fixture(tmp_path)
    identity, nonce = broker.journal_id, broker.boot_nonce
    broker.close()
    restarted = Broker(tmp_path, owner)
    assert restarted.journal_id == identity
    assert restarted.boot_nonce != nonce
    restarted.close()
    (tmp_path / "journal.sqlite3").unlink()
    with pytest.raises(BrokerError, match="journal_missing"):
        Broker(tmp_path, owner)
    assert owner.calls == 0


def test_full_storage_refuses_before_persist_or_send(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from librarium import delivery_broker

    owner, broker, request = fixture(tmp_path)
    monkeypatch.setattr(
        delivery_broker.os, "statvfs", lambda _: SimpleNamespace(f_bavail=0, f_frsize=4096)
    )
    try:
        with pytest.raises(BrokerError, match="storage_full"):
            broker.execute(request, b"corrected")
        assert owner.calls == 0
        assert broker.existing(request["operation_id"]) is None
    finally:
        broker.close()


def test_torn_journal_does_not_become_an_empty_authorization_store(tmp_path):
    import sqlite3

    owner, broker, _ = fixture(tmp_path)
    broker.close()
    (tmp_path / "journal.sqlite3").write_bytes(b"torn journal")
    with pytest.raises(sqlite3.DatabaseError):
        Broker(tmp_path, owner)
    assert owner.calls == 0


def test_never_sent_fence_releases_target_for_fresh_operation(tmp_path):
    owner, broker, request = fixture(tmp_path)
    owner.data = b"external"
    result = broker.execute(request, b"corrected")
    assert result["classification"] == "not_applied"
    assert owner.calls == 0
    fresh = {
        **request,
        "operation_id": str(uuid.uuid4()),
        "before": owner.observe(request["target"]),
    }
    assert broker.execute(fresh, b"corrected")["classification"] == "applied"
    assert broker.reconcile(request["operation_id"])["classification"] == "not_applied"
    broker.close()


def test_cancel_consumes_unobservable_target_without_future_send(tmp_path, monkeypatch):
    owner, broker, request = fixture(tmp_path)
    original = owner.observe
    monkeypatch.setattr(
        owner, "observe", lambda target: (_ for _ in ()).throw(BrokerError("inventory_changed"))
    )
    result = broker.cancel(request)
    assert result["classification"] == "not_applied"
    assert result["observed"] is None
    monkeypatch.setattr(owner, "observe", original)
    assert broker.execute(request, b"corrected")["classification"] == "not_applied"
    assert owner.calls == 0
    broker.close()


@pytest.mark.parametrize("reason", ["expiry", "restart"])
@pytest.mark.parametrize("mode", ["delivery", "undo"])
def test_stale_writer_grant_is_durably_sealed(tmp_path, reason, mode):
    from datetime import UTC, datetime, timedelta

    from librarium.delivery_authorization import seal
    from librarium.delivery_writer import WriterService

    owner, broker, request = fixture(tmp_path)
    request["mode"] = mode
    service = WriterService(broker, tmp_path, b"k" * 32, "a" * 64)
    payload = {
        "policy": "librarium.epub-delivery.v1",
        "runtime_sha256": "a" * 64,
        "request": request,
        "original": {},
        "replacement": {},
        "validation": {},
        "evidence": [],
        "intent_sha256": "b" * 64,
        "review_expires_at": (
            datetime.now(UTC) + timedelta(minutes=-1 if reason == "expiry" else 5)
        ).isoformat(),
        "writer_instance": {
            "journal_id": broker.journal_id,
            "boot_nonce": "old" if reason == "restart" else broker.boot_nonce,
        },
    }
    grant = seal(payload, b"k" * 32)
    result = service.execute(grant)
    assert result["classification"] == "not_applied"
    assert broker.existing(request["operation_id"]) is not None
    assert service.cancel(grant)["classification"] == "not_applied"
    assert owner.calls == 0
    broker.close()


def test_unrelated_inventory_change_does_not_refuse_delivery_or_undo(tmp_path):
    owner, broker, request = fixture(tmp_path)
    owner.library_revision += 1
    applied = broker.execute(request, b"corrected")
    assert applied["classification"] == "applied"
    owner.library_revision += 1
    assert broker.reconcile(request["operation_id"])["classification"] == "applied"
    undo = {
        **request,
        "operation_id": str(uuid.uuid4()),
        "mode": "undo",
        "before": owner.observe(request["target"]),
        "output": {"sha256": digest(b"original"), "size": 8},
    }
    owner.library_revision += 1
    assert broker.execute(undo, b"original")["classification"] == "applied"
    broker.close()


def test_cancelled_operation_cannot_diverge_or_reserve_after_later_writes(tmp_path):
    owner, broker, request = fixture(tmp_path)
    broker.cancel(request)
    owner.library_revision += 1
    owner.metadata["title"] = "Later metadata"
    owner.data = b"later"
    assert broker.reconcile(request["operation_id"])["classification"] == "not_applied"
    assert not broker.db.execute("SELECT * FROM targets").fetchall()
    broker.close()


def test_applied_receipt_follows_durability_and_failed_sync_remains_recoverable(
    tmp_path, monkeypatch
):
    owner, broker, request = fixture(tmp_path)
    events = []
    broker.boundary = events.append

    def failed_sync(target):
        events.append("sync_failed")
        raise OSError("injected fsync failure")

    monkeypatch.setattr(owner, "sync", failed_sync)
    with pytest.raises(OSError, match="fsync failure"):
        broker.execute(request, b"corrected")
    assert "receipt" not in events
    assert broker.existing(request["operation_id"])[1][-1][0] == "send_started"
    monkeypatch.setattr(owner, "sync", lambda _: events.append("durable"))
    original_append = broker.append

    def append(*args, **kwargs):
        if args[1] == "receipt":
            assert events[-1] == "durable"
        return original_append(*args, **kwargs)

    monkeypatch.setattr(broker, "append", append)
    assert broker.reconcile(request["operation_id"])["classification"] == "applied"
    assert owner.calls == 1
    broker.close()


def test_never_sent_tombstone_does_not_claim_another_operations_reservation(tmp_path):
    owner, broker, request = fixture(tmp_path)
    broker.append(request["operation_id"], "prepared", request["before"], request=request)
    old = {**request, "operation_id": str(uuid.uuid4())}
    result = broker.cancel(old)
    assert result["classification"] == "not_applied"
    assert broker.db.execute("SELECT operation_id FROM targets").fetchall() == [
        (request["operation_id"],)
    ]
    assert broker.existing(old["operation_id"]) is not None
    assert owner.calls == 0
    broker.close()


def test_unobservable_cancel_later_reports_present_without_changing_never_sent_history(
    tmp_path, monkeypatch
):
    owner, broker, request = fixture(tmp_path)
    observe = owner.observe
    monkeypatch.setattr(
        owner, "observe", lambda _: (_ for _ in ()).throw(BrokerError("inventory_changed"))
    )
    cancelled = broker.cancel(request)
    monkeypatch.setattr(owner, "observe", observe)
    result = broker.reconcile(request["operation_id"])
    assert result["classification"] == "not_applied"
    assert result["observed"] is None
    assert result["present"] == owner.observe(request["target"])
    assert broker.existing(request["operation_id"])[1][-1] == ("receipt", cancelled)
    broker.close()


@pytest.mark.parametrize("path", ["cancel", "precondition", "stale_grant"])
def test_independent_journal_restore_cannot_prove_output_was_never_sent(tmp_path, path):
    import sqlite3
    from contextlib import closing

    from librarium.delivery_authorization import seal
    from librarium.delivery_writer import WriterService

    owner, broker, request = fixture(tmp_path)
    with closing(sqlite3.connect(":memory:")) as snapshot:
        broker.db.backup(snapshot)
        assert broker.execute(request, b"corrected")["classification"] == "applied"
        snapshot.backup(broker.db)
    assert broker.existing(request["operation_id"]) is None
    if path == "precondition":
        result = broker.execute(request, b"corrected")
    elif path == "cancel":
        result = broker.cancel(request)
    else:
        service = WriterService(broker, tmp_path, b"k" * 32, "a" * 64)
        payload = {
            "policy": "librarium.epub-delivery.v1",
            "runtime_sha256": "a" * 64,
            "request": request,
            "original": {},
            "replacement": {},
            "validation": {},
            "evidence": [],
            "intent_sha256": "b" * 64,
            "review_expires_at": "2000-01-01T00:00:00+00:00",
            "writer_instance": {"journal_id": broker.journal_id, "boot_nonce": "old"},
        }
        result = service.execute(seal(payload, b"k" * 32))
    assert result["classification"] == "unobservable"
    assert result["reason"] == "output_already_present"
    assert result["observed"]["sha256"] == request["output"]["sha256"]
    assert broker.existing(request["operation_id"]) is None
    assert owner.calls == 1
    assert broker.cancel(request)["classification"] == "unobservable"
    broker.close()
