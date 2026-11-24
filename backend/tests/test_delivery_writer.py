"""The narrow writer accepts sealed digest-bound grants, never arbitrary paths."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from librarium.delivery_authorization import seal
from librarium.delivery_writer import WriterError, WriterService, read_artifact, read_secret
from test_delivery_broker import fixture

KEY = b"synthetic-reviewer-signing-key-" * 2


def artifact(root, kind, data):
    descriptor = {"kind": kind, "sha256": sha256(data).hexdigest(), "size": len(data)}
    path = root / (kind + "-" + descriptor["sha256"])
    path.write_bytes(data)
    path.chmod(0o600)
    return descriptor


def writer_grant(tmp_path, mode="delivery"):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    owner, broker, request = fixture(state)
    store = tmp_path / "artifacts"
    store.mkdir(mode=0o700)
    source = artifact(store, "source", b"original")
    corrected = artifact(store, "corrected", b"corrected")
    if mode == "undo":
        owner.data = b"corrected"
        request["before"] = owner.observe(request["target"])
        request["output"] = {"sha256": source["sha256"], "size": source["size"]}
        request["mode"] = mode
    validation = artifact(
        store,
        "report",
        json.dumps(
            {
                "policy": "librarium.output-validation.v1",
                "verdict": "passed",
                "output": {"sha256": corrected["sha256"], "size": corrected["size"]},
                "checks": {
                    name: {"status": "passed"}
                    for name in ("structure", "epubcheck", "preservation")
                },
            }
        ).encode(),
    )
    service = WriterService(broker, store, KEY, "a" * 64)
    payload = {
        "policy": "librarium.epub-delivery.v1",
        "runtime_sha256": "a" * 64,
        "request": request,
        "original": source,
        "replacement": corrected if mode == "delivery" else source,
        "validation": validation,
        "evidence": [],
        "intent_sha256": "b" * 64,
        "writer_instance": {
            "journal_id": getattr(broker, "journal_id", "fixture"),
            "boot_nonce": getattr(broker, "boot_nonce", "fixture"),
        },
    }
    payload["review_expires_at"] = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    return owner, broker, service, payload


@pytest.mark.parametrize("supervised", [False, True])
def test_writer_rechecks_saved_validation_and_bytes_before_send(tmp_path, supervised):
    owner, broker, service, payload = writer_grant(tmp_path)
    request, corrected = payload["request"], payload["replacement"]
    if supervised:
        owner.supervised = True
        with pytest.raises(WriterError, match="supervised_session_required"):
            service.execute(seal(payload, KEY))
        payload["supervised_session"] = {
            "session_id": str(uuid.uuid4()),
            "target": request["target"],
            "confirmed_by_sha256": "a" * 64,
            "confirmed_at": datetime.now(UTC).isoformat(),
            "other_writers_stopped": True,
        }
    signed = seal(payload, KEY)
    assert service.execute(signed)["classification"] == "applied"
    assert owner.calls == 1
    (service.artifacts / ("corrected-" + corrected["sha256"])).write_bytes(b"corrupted")
    assert service.execute(signed)["classification"] == "applied"
    assert owner.calls == 1
    broker.close()


@pytest.mark.parametrize("mode", ["delivery", "undo"])
@pytest.mark.parametrize("expiry", ["review", "session"])
@pytest.mark.parametrize("stage", ["artifact", "first_observation", "final_observation"])
def test_expiry_during_preflight_is_sealed_without_sending(
    tmp_path, monkeypatch, mode, expiry, stage
):
    from librarium import delivery_session, delivery_writer
    from librarium.delivery_broker import Broker, BrokerError

    owner, broker, service, payload = writer_grant(tmp_path, mode)
    request = payload["request"]
    owner.supervised = True
    start = datetime.now(UTC)

    class Clock(datetime):
        current = start

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(delivery_writer, "datetime", Clock)
    monkeypatch.setattr(delivery_session, "datetime", Clock)
    payload["review_expires_at"] = (
        start + timedelta(minutes=1 if expiry == "review" else 10)
    ).isoformat()
    payload["supervised_session"] = {
        "session_id": str(uuid.uuid4()),
        "target": request["target"],
        "confirmed_by_sha256": "a" * 64,
        "confirmed_at": start.isoformat(),
        "other_writers_stopped": True,
    }

    def expire():
        Clock.current = start + timedelta(minutes=2 if expiry == "review" else 6)

    observe, read = owner.observe, delivery_writer.read_artifact
    observations = 0

    def slow_observe(target):
        nonlocal observations
        observations += 1
        if stage == "first_observation" or stage == "final_observation" and observations == 2:
            expire()
        return observe(target)

    def slow_artifact(*args):
        if stage == "artifact":
            expire()
        return read(*args)

    monkeypatch.setattr(owner, "observe", slow_observe)
    monkeypatch.setattr(delivery_writer, "read_artifact", slow_artifact)
    signed = seal(payload, KEY)
    try:
        result = service.execute(signed)
        assert result["classification"] == "not_applied"
        assert result["reason"] == "sealed_stale_grant"
        assert owner.calls == 0
        assert not broker.paused()
        events = broker.existing(request["operation_id"])[1]
        assert any(name == "send_started" for name, _ in events) == (stage == "final_observation")
    finally:
        broker.close()

    restarted = Broker(tmp_path / "state", owner)
    try:
        recovered = WriterService(restarted, service.artifacts, KEY, "a" * 64)
        assert recovered.execute(signed)["classification"] == "not_applied"
        assert (
            recovered.broker.reconcile(request["operation_id"])["classification"] == "not_applied"
        )
        assert not restarted.paused()
        assert not restarted.db.execute("SELECT * FROM targets").fetchall()
        with pytest.raises(BrokerError, match="session_consumed"):
            restarted.claim_session(payload["supervised_session"]["session_id"], str(uuid.uuid4()))
        assert owner.calls == 0
    finally:
        restarted.close()


@pytest.mark.parametrize("after_intent", [False, True])
def test_failed_expiry_seal_preserves_recovery_uncertainty(tmp_path, monkeypatch, after_intent):
    from librarium.delivery_broker import Broker

    owner, broker, request = fixture(tmp_path)
    owner.supervised = True
    append = broker.append
    checks = 0

    def send_authorized():
        nonlocal checks
        checks += 1
        return after_intent and checks == 1

    def failed_receipt(operation_id, stage, payload, **kwargs):
        if stage == "receipt":
            raise OSError("synthetic receipt storage failure")
        return append(operation_id, stage, payload, **kwargs)

    monkeypatch.setattr(broker, "append", failed_receipt)
    try:
        with pytest.raises(OSError, match="synthetic receipt storage failure"):
            broker.execute(request, b"corrected", send_authorized=send_authorized)
        assert owner.calls == 0
    finally:
        broker.close()

    restarted = Broker(tmp_path, owner)
    try:
        result = restarted.reconcile(request["operation_id"])
        assert result["classification"] == ("unobservable" if after_intent else "not_applied")
        assert restarted.paused() == after_intent
        assert owner.calls == 0
    finally:
        restarted.close()


@pytest.mark.parametrize("mode", ["delivery", "undo"])
def test_unsupervised_writer_also_rechecks_expiry_after_artifact_reads(tmp_path, monkeypatch, mode):
    from librarium import delivery_writer

    owner, broker, service, payload = writer_grant(tmp_path, mode)
    later = datetime.now(UTC) + timedelta(minutes=6)
    read = delivery_writer.read_artifact

    class Expired(datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    def slow_artifact(*args):
        data = read(*args)
        monkeypatch.setattr(delivery_writer, "datetime", Expired)
        return data

    monkeypatch.setattr(delivery_writer, "read_artifact", slow_artifact)
    try:
        assert service.execute(seal(payload, KEY))["classification"] == "not_applied"
        assert owner.calls == 0
    finally:
        broker.close()


def test_artifact_reads_refuse_symlinks_and_wrong_hashes(tmp_path):
    descriptor = artifact(tmp_path, "source", b"fixture")
    assert read_artifact(tmp_path, descriptor) == b"fixture"
    path = tmp_path / ("source-" + descriptor["sha256"])
    path.unlink()
    path.symlink_to("absent")
    with pytest.raises(WriterError):
        read_artifact(tmp_path, descriptor)


def test_private_secret_file_requires_owned_regular_non_shared_bytes(tmp_path):
    path = tmp_path / "key"
    path.write_bytes(KEY)
    path.chmod(0o600)
    assert read_secret(path) == KEY
    path.chmod(0o644)
    with pytest.raises(WriterError):
        read_secret(path)


def test_writer_configuration_is_disabled_and_synthetic_only_by_default():
    from librarium.delivery_writer import configuration

    with pytest.raises(WriterError, match="writer_disabled"):
        configuration({})
    with pytest.raises(WriterError, match="synthetic_only_required"):
        configuration({"LIBRARIUM_DELIVERY_ENABLED": "1"})


def test_transport_authentication_rejects_non_ascii_and_absent_headers():
    from librarium.delivery_writer import transport_authenticated

    assert not transport_authenticated("Bearer é", KEY)
    assert not transport_authenticated(None, KEY)
    assert transport_authenticated("Bearer " + KEY.hex(), KEY)


def test_expired_rpc_budget_cannot_read_credentials_or_send():
    from librarium.delivery_client import rpc, rpc_deadline

    with rpc_deadline(0), pytest.raises(WriterError, match="timeout"):
        rpc("/v1/capability")


def test_library_exclusion_crosses_state_directories_and_verifies_identity(tmp_path):
    from librarium.delivery_writer import SyntheticLibraryLock

    marker = tmp_path / "librarium-synthetic-owner.json"
    marker.write_text(
        json.dumps(
            {
                "schema": "librarium.synthetic-owner.v1",
                "library_uuid": "fixture",
                "sole_owner": True,
            }
        )
    )
    marker.chmod(0o600)
    with SyntheticLibraryLock(tmp_path, "fixture") as lock:
        assert lock.verified("fixture")
        with (
            pytest.raises(WriterError, match="independent_writer_not_excluded"),
            SyntheticLibraryLock(tmp_path, "fixture"),
        ):
            pass
        marker.rename(tmp_path / "old-marker")
        marker.write_text("{}")
        assert not lock.verified("fixture")
    with (
        pytest.raises(WriterError, match="synthetic_owner_unconfirmed"),
        SyntheticLibraryLock(tmp_path, "fixture"),
    ):
        pass


@pytest.fixture
def http_writer(tmp_path):
    from threading import Thread
    from types import SimpleNamespace

    from librarium.delivery_writer import make_server

    owner, broker, request = fixture(tmp_path)
    owner.library_uuid = "fixture"
    owner.exclusion = SimpleNamespace(verified=lambda identity: identity == "fixture")
    service = WriterService(broker, tmp_path, KEY, "a" * 64)
    server = make_server(service, KEY)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield service, request
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
        broker.close()


@pytest.mark.parametrize(
    "case,status",
    [
        ("capability", 200),
        ("auth", 401),
        ("duplicate_auth", 401),
        ("transfer", 409),
        ("length", 409),
        ("invalid_json", 409),
        ("unknown", 404),
        ("malformed_signed", 503),
    ],
)
def test_writer_http_boundary(http_writer, case, status):
    import http.client

    service, _ = http_writer
    path = "/v1/capability" if case in {"capability", "auth", "duplicate_auth"} else "/v1/execute"
    if case == "unknown":
        path = "/missing"
    connection = http.client.HTTPConnection("127.0.0.1", 8133, timeout=5)
    body = b"{" if case == "invalid_json" else b"{}"
    if case == "malformed_signed":
        service.execute = lambda _: (_ for _ in ()).throw(AttributeError("private detail"))
    connection.putrequest(
        "GET" if case in {"capability", "auth", "duplicate_auth", "unknown"} else "POST", path
    )
    if case != "auth":
        connection.putheader("Authorization", "Bearer " + KEY.hex())
    if case == "duplicate_auth":
        connection.putheader("Authorization", "Bearer " + KEY.hex())
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(2**21) if case == "length" else str(len(body)))
    if case == "transfer":
        connection.putheader("Transfer-Encoding", "chunked")
    connection.endheaders(body)
    response = connection.getresponse()
    data = json.loads(response.read())
    assert response.status == status
    assert "private detail" not in str(data)
    if case == "capability":
        assert data["exclusion"] == "sole_owner"
    connection.close()


@pytest.mark.parametrize(
    "status,body,error",
    [
        (200, b'{"ok":true}', None),
        (409, b'{"error":"target_reserved"}', "target_reserved"),
        (200, b"invalid", "invalid_json"),
        (200, b"x" * (1024 * 1024 + 1), "writer_response_invalid"),
    ],
    ids=[
        "success",
        "target-reserved",
        "invalid-json",
        "oversized-response",
    ],
)
def test_dispatcher_rpc_transport(tmp_path, monkeypatch, settings, status, body, error):
    from types import SimpleNamespace

    from librarium import delivery_client

    path = tmp_path / "token"
    path.write_bytes(KEY)
    path.chmod(0o600)
    settings.LIBRARIUM_WRITER_TOKEN_FILE = str(path)
    sent = []
    connection = SimpleNamespace(
        request=lambda *args, **kwargs: sent.append((args, kwargs)),
        getresponse=lambda: SimpleNamespace(status=status, read=lambda size: body),
        close=lambda: sent.append("closed"),
    )
    monkeypatch.setattr(
        delivery_client.http.client, "HTTPConnection", lambda *args, **kwargs: connection
    )
    if error:
        with pytest.raises(WriterError, match=error):
            delivery_client.rpc("/v1/cancel", {})
    else:
        assert delivery_client.rpc("/v1/cancel", {}) == {"ok": True}
    assert sent[-1] == "closed"


def test_new_journal_scoped_undo_executes_after_ordinary_restart(tmp_path, monkeypatch):
    from librarium.delivery_broker import Broker

    owner, broker, delivery = fixture(tmp_path)
    broker.execute(delivery, b"corrected")
    identity, nonce = broker.journal_id, broker.boot_nonce
    broker.close()
    restarted = Broker(tmp_path, owner)
    assert restarted.journal_id == identity and restarted.boot_nonce != nonce
    request = {
        **delivery,
        "operation_id": str(uuid.uuid4()),
        "mode": "undo",
        "before": owner.observe(delivery["target"]),
        "output": {"sha256": sha256(b"original").hexdigest(), "size": 8},
    }
    service = WriterService(restarted, tmp_path, KEY, "a" * 64)
    payload = {
        "policy": "librarium.epub-delivery.v1",
        "runtime_sha256": "a" * 64,
        "request": request,
        "original": {},
        "replacement": {},
        "validation": {},
        "evidence": [],
        "intent_sha256": "b" * 64,
        "writer_instance": {
            "journal_id": identity,
            "boot_nonce": None,
            "approved_at": datetime.now(UTC).isoformat(),
        },
        "review_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    monkeypatch.setattr(
        service, "_execute", lambda value: restarted.execute(value["request"], b"original")
    )
    assert service.execute(seal(payload, KEY))["classification"] == "applied"
    assert owner.data == b"original" and owner.calls == 2
    assert not restarted.db.execute("SELECT * FROM targets").fetchall()
    restarted.close()


def test_journal_scoped_undo_from_before_restart_is_sealed(tmp_path, monkeypatch):
    from librarium.delivery_broker import Broker

    owner, broker, request = fixture(tmp_path)
    identity = broker.journal_id
    approved = datetime.now(UTC).isoformat()
    broker.close()
    restarted = Broker(tmp_path, owner)
    request["mode"] = "undo"
    service = WriterService(restarted, tmp_path, KEY, "a" * 64)
    payload = {
        "policy": "librarium.epub-delivery.v1",
        "runtime_sha256": "a" * 64,
        "request": request,
        "original": {},
        "replacement": {},
        "validation": {},
        "evidence": [],
        "intent_sha256": "b" * 64,
        "writer_instance": {"journal_id": identity, "boot_nonce": None, "approved_at": approved},
        "review_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    monkeypatch.setattr(service, "_execute", lambda _: pytest.fail("stale grant sent"))
    assert service.execute(seal(payload, KEY))["classification"] == "not_applied"
    assert owner.calls == 0
    restarted.close()
