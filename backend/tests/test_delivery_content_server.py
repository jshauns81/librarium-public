"""Content-server bytes and failure fences, independent of Calibre's download cache."""

import secrets
import uuid
from copy import deepcopy
from urllib.parse import urlunsplit

import pytest
from librarium.delivery_broker import BrokerError
from librarium.delivery_content_server import ContentServer
from test_delivery_broker import fixture

# Generated per run, like the operator's own secret; never a committed literal.
STRONG = secrets.token_urlsafe(32)


def test_transport_uses_raw_export_and_lf_added_formats():
    server = ContentServer(
        "http://127.0.0.1:8168", "library", "fixture-library", username="u", password=STRONG
    )
    calls = []

    def request(path, value=None, **kw):
        calls.append((path, value))
        return {"result": b"original"}

    server.request = request
    assert server.format(1, "EPUB") == b"original"
    server.replace({"book_id": "1"}, b"corrected")
    assert calls[0] == ("/cdb/cmd/export/0?library_id=library", ["fmt", 1, "EPUB", None])
    path, body = calls[1]
    assert path == "/cdb/set-fields/1/library"
    assert body["changes"]["added_formats"][0]["ext"] == "epub"
    assert set(body["changes"]) == {"added_formats"}


def test_transport_refuses_unsafe_endpoints():
    for url in (
        urlunsplit(("http", "fixture:synthetic-only@example.org", "", "", "")),
        "http://example.org",
        "https://example.org?a=b",
    ):
        with pytest.raises(BrokerError, match="server_configuration_invalid"):
            ContentServer(url, "library", "uuid", username="u", password=STRONG)


@pytest.mark.parametrize("failure", ["reply", "readback"])
def test_content_server_failure_pauses_every_target_across_restart(tmp_path, failure):
    owner, broker, request = fixture(tmp_path)
    owner.supervised = True
    original = owner.replace
    if failure == "reply":

        def lost(target, data):
            original(target, data)
            raise BrokerError("server_unavailable")

        owner.replace = lost
        with pytest.raises(BrokerError):
            broker.execute(request, b"corrected")
    else:
        if failure == "readback":

            def transformed(target, data):
                original(target, b"transformed")

            owner.replace = transformed
        else:
            owner.data = b"changed"
        broker.execute(request, b"corrected")
    broker.close()
    from librarium.delivery_broker import Broker

    restarted = Broker(tmp_path, owner)
    fresh = deepcopy(request)
    fresh["operation_id"] = str(uuid.uuid4())
    fresh["target"]["book_id"] = "2"
    with pytest.raises(BrokerError, match="recovery_required"):
        restarted.execute(fresh, b"corrected")
    restarted.close()


def test_supervision_requires_fresh_named_confirmation_for_exact_target(tmp_path):
    import json
    from datetime import UTC, datetime

    from librarium.delivery_session import approval_session, validate_session
    from librarium.delivery_writer import WriterError

    target = {"library_uuid": "library", "book_id": "1", "book_uuid": "book"}
    path = tmp_path / "session"
    with pytest.raises(WriterError, match="supervised_session_required"):
        approval_session(str(path), target, "reviewer", b"k" * 32)
    confirmation = {
        "session_id": str(uuid.uuid4()),
        "target": target,
        "confirmed_by": "reviewer",
        "confirmed_at": datetime.now(UTC).isoformat(),
        "other_writers_stopped": True,
    }
    path.write_text(json.dumps(confirmation))
    path.chmod(0o600)
    session = approval_session(str(path), target, "reviewer", b"k" * 32)
    assert "reviewer" not in str(session)
    validate_session(session, target)
    with pytest.raises(WriterError):
        validate_session(session, {**target, "book_id": "2"})
    with pytest.raises(WriterError):
        approval_session(str(path), target, "someone-else", b"k" * 32)
    with pytest.raises(WriterError):
        validate_session({**session, "confirmed_at": "2000-01-01T00:00:00+00:00"}, target)


def test_session_is_consumed_by_only_one_operation(tmp_path):
    _owner, broker, request = fixture(tmp_path)
    broker.claim_session("synthetic-session", request["operation_id"])
    broker.claim_session("synthetic-session", request["operation_id"])
    with pytest.raises(BrokerError, match="session_consumed"):
        broker.claim_session("synthetic-session", str(uuid.uuid4()))
    broker.close()


def test_restart_latches_unfinished_send_even_after_successful_reconciliation(tmp_path):
    owner, broker, request = fixture(tmp_path)
    owner.supervised = True

    def death(stage):
        if stage == "native_returned":
            raise KeyboardInterrupt

    broker.boundary = death
    # Simulate process death, which cannot run the normal exception/pause handler.
    with pytest.raises(KeyboardInterrupt):
        broker._execute(request, b"corrected")
    broker.close()
    from librarium.delivery_broker import Broker

    restarted = Broker(tmp_path, owner)
    assert restarted.reconcile(request["operation_id"])["classification"] == "applied"
    assert restarted.paused()
    restarted.close()


def test_server_credentials_file_and_environment_never_enter_diagnostics(tmp_path):
    import json

    from librarium.delivery_content_server import NoRedirect

    secret = tmp_path / "credentials"
    secret.write_text(json.dumps({"username": "synthetic-reviewer", "password": STRONG}))
    secret.chmod(0o600)
    adapter = ContentServer.configured(
        {
            "LIBRARIUM_CALIBRE_URL": "http://127.0.0.1:8168",
            "LIBRARIUM_CALIBRE_LIBRARY_ID": "library",
            "LIBRARIUM_CALIBRE_CREDENTIALS_FILE": str(secret),
        },
        "uuid",
    )
    assert adapter.library_uuid == "uuid"
    assert STRONG not in repr(adapter)
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org") is None
    with pytest.raises(BrokerError, match="server_credentials_required"):
        ContentServer.configured(
            {
                "LIBRARIUM_CALIBRE_URL": "https://example.org",
                "LIBRARIUM_CALIBRE_LIBRARY_ID": "library",
                "LIBRARIUM_CALIBRE_PASSWORD": "synthetic-password",
            },
            "uuid",
        )


def test_authenticated_dispatcher_hold_is_durable_for_every_target(tmp_path):
    import http.client
    import json
    from threading import Thread

    from librarium.delivery_writer import WriterService, make_server

    owner, broker, request = fixture(tmp_path)
    owner.supervised = True
    token = b"t" * 32
    server = make_server(WriterService(broker, tmp_path, b"k" * 32, "a" * 64), token, port=8167)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bearer = "Bearer " + token.hex()

    def hold(operation_id, credential=bearer):
        connection = http.client.HTTPConnection("127.0.0.1", 8167, timeout=5)
        try:
            connection.request(
                "POST",
                "/v1/hold",
                json.dumps({"operation_id": operation_id}),
                {"Content-Type": "application/json", "Authorization": credential},
            )
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    try:
        # A hold names an operation this writer recorded; an unknown id never latches.
        assert hold(str(uuid.uuid4())) != 200
        assert hold(request["operation_id"]) != 200
        assert not broker.paused()
        assert broker.execute(request, b"corrected")["classification"] == "applied"
        assert not broker.paused()
        assert hold(request["operation_id"], "invalid") == 401
        assert hold(request["operation_id"]) == 200
        assert broker.paused()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        broker.close()
    from librarium.delivery_broker import Broker

    restarted = Broker(tmp_path, owner)
    assert restarted.paused()
    restarted.close()


def test_source_changed_after_send_intent_is_rechecked_before_the_server_write(tmp_path):
    owner, broker, request = fixture(tmp_path)
    owner.supervised = True

    def change(stage):
        if stage == "send_started":
            owner.data = b"changed just before send"

    broker.boundary = change
    receipt = broker.execute(request, b"corrected")
    assert receipt["classification"] == "diverged"
    assert receipt["reason"] == "precondition_changed"
    assert owner.calls == 0
    assert broker.paused()
    assert broker.execute(request, b"corrected")["classification"] == "diverged"
    assert owner.calls == 0
    broker.close()


def test_reconciling_an_unknown_operation_reports_it_without_pausing_writes(tmp_path):
    owner, broker, _ = fixture(tmp_path)
    owner.supervised = True
    result = broker.reconcile(str(uuid.uuid4()))
    assert result["classification"] == "unobservable"
    assert result["reason"] == "journal_absent"
    assert not broker.paused()
    broker.close()


def test_a_cancelled_unsent_operation_cannot_latch_the_writer_pause(tmp_path):
    owner, broker, request = fixture(tmp_path)
    owner.supervised = True
    assert broker.cancel(request)["classification"] == "not_applied"
    with pytest.raises(BrokerError, match="operation_unknown"):
        broker.hold(request["operation_id"])
    assert not broker.paused()
    broker.close()


@pytest.mark.parametrize("challenge", ["Basic", "basic"])
def test_plain_http_never_answers_a_basic_challenge_with_credentials(challenge):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    seen = []

    class Squatter(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.headers.get("Authorization"))
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(401)
            self.send_header("WWW-Authenticate", challenge + ' realm="calibre"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST

        def log_message(self, *args):
            pass

    listener = HTTPServer(("127.0.0.1", 0), Squatter)
    thread = Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    try:
        server = ContentServer(
            f"http://127.0.0.1:{listener.server_port}",
            "library",
            "fixture-library",
            username="fixture",
            password=STRONG,
        )
        with pytest.raises(BrokerError):
            server.format(1, "EPUB")
    finally:
        listener.shutdown()
        thread.join(timeout=5)
        listener.server_close()
    assert seen and all(value is None for value in seen)


def test_writable_access_requires_credentials():
    with pytest.raises(BrokerError, match="server_credentials_required"):
        ContentServer("http://127.0.0.1:8168", "library", "fixture-library")


def test_a_server_that_accepts_unauthenticated_requests_is_refused():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    class Open(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_GET

        def log_message(self, *args):
            pass

    listener = HTTPServer(("127.0.0.1", 0), Open)
    thread = Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    try:
        server = ContentServer(
            f"http://127.0.0.1:{listener.server_port}",
            "library",
            "fixture-library",
            username="fixture",
            password=STRONG,
        )
        with pytest.raises(BrokerError, match="server_authentication_required"):
            server.format(1, "EPUB")
    finally:
        listener.shutdown()
        thread.join(timeout=5)
        listener.server_close()


@pytest.mark.parametrize(
    "password",
    ["library123", "a" * 48, "abcdefghij" * 4, STRONG[:31]],
    ids=["common", "repeated", "patterned", "short-random"],
)
def test_guessable_passwords_are_refused_before_any_request(password):
    # Digest still lets a port squatter test guesses offline, so only generated
    # high-entropy secrets are accepted.
    with pytest.raises(BrokerError, match="server_credentials_weak"):
        ContentServer(
            "http://127.0.0.1:8168", "library", "fixture-library", username="u", password=password
        )


@pytest.mark.parametrize("failure", ["precondition", "target_changed"])
def test_a_refusal_before_any_send_does_not_pause_other_targets(tmp_path, failure):
    # Nothing is written before send intent, and the peer answering pre-send reads
    # may not be the real server, so a pre-send refusal stays scoped to its request.
    owner, broker, request = fixture(tmp_path)
    owner.supervised = True
    if failure == "precondition":
        owner.data = b"changed"
        assert broker.execute(request, b"corrected")["classification"] == "not_applied"
    else:
        observe = owner.observe

        def impostor(target):
            raise BrokerError("target_changed")

        owner.observe = impostor
        with pytest.raises(BrokerError, match="target_changed"):
            broker.execute(request, b"corrected")
        owner.observe = observe
    assert not broker.paused()
    broker.close()
