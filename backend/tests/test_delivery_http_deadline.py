"""Real trickling peers cannot extend the content-server request budget."""

import secrets
import socket
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest
from librarium import delivery_content_server as transport
from librarium.delivery_broker import BrokerError


@contextmanager
def peer(action, *, tls=None):
    stopped = Event()
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append((self.path, self.headers.get("Authorization")))
            try:
                action(self, stopped)
            except OSError:
                pass

        do_POST = do_GET

        def log_message(self, *args):
            pass

    listener = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls:
        listener.socket = tls.wrap_socket(listener.socket, server_side=True)
    thread = Thread(target=listener.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield (
            transport.ContentServer(
                f"{'https' if tls else 'http'}://127.0.0.1:{listener.server_port}",
                "library",
                "fixture-library",
                username="fixture",
                password=secrets.token_urlsafe(32),
            ),
            seen,
        )
    finally:
        stopped.set()
        listener.shutdown()
        thread.join(timeout=2)
        listener.server_close()


def reply(handler, code=200, body=b"{}", *, challenge=False):
    handler.send_response(code)
    if challenge:
        handler.send_header(
            "WWW-Authenticate", 'Digest realm="calibre", nonce="fixture", qop="auth"'
        )
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


@pytest.mark.parametrize(
    "stage",
    [
        "probe_status",
        "probe_headers",
        "probe_open_headers",
        "challenge_headers",
        "authenticated_headers",
        "body",
    ],
)
def test_absolute_deadline_interrupts_every_http_stage(monkeypatch, stage):
    monkeypatch.setattr(transport, "HTTP_DEADLINE_SECONDS", 0.25, raising=False)

    def action(handler, stopped):
        probe = handler.path == "/ajax/library-info"
        authenticated = bool(handler.headers.get("Authorization"))
        slow = (
            (probe and stage.startswith("probe_"))
            or (not probe and not authenticated and stage == "challenge_headers")
            or (authenticated and stage in {"authenticated_headers", "body"})
        )
        if not slow:
            reply(handler, 401 if probe or not authenticated else 200, challenge=True)
            return
        if stage == "probe_status":
            handler.wfile.write(b"HTTP/1.1 ")
        elif stage == "body":
            handler.send_response(200)
            handler.send_header("Content-Length", "22")
            handler.end_headers()
            handler.wfile.write(b"{}")
        elif stage == "probe_open_headers":
            handler.wfile.write(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
        else:
            handler.wfile.write(b"HTTP/1.1 401 Unauthorized\r\nX-Trickle: ")
        for _ in range(20):
            if stopped.wait(0.04):
                return
            handler.wfile.write(b" " if stage == "body" else b"x")
        if stage != "body":
            handler.wfile.write(b"\r\nContent-Length: 0\r\n\r\n")

    with peer(action) as (server, seen):
        started = time.monotonic()
        with pytest.raises(BrokerError, match="^server_unavailable$"):
            server.request("/write", {"synthetic": True})
        assert time.monotonic() - started < 0.65
        if stage.startswith("probe_"):
            assert [path for path, _ in seen] == ["/ajax/library-info"]
            assert not server.authenticated


def test_probe_challenge_and_retry_share_one_deadline(monkeypatch):
    monkeypatch.setattr(transport, "HTTP_DEADLINE_SECONDS", 0.25, raising=False)

    def action(handler, stopped):
        if stopped.wait(0.12):
            return
        authenticated = bool(handler.headers.get("Authorization"))
        reply(handler, 200 if authenticated else 401, challenge=True)

    with peer(action) as (server, seen):
        started = time.monotonic()
        with pytest.raises(BrokerError, match="^server_unavailable$"):
            server.request("/write", {})
        assert time.monotonic() - started < 0.65
        assert len(seen) >= 2


def test_timeout_eof_cannot_accept_a_complete_json_prefix_or_affect_the_next_request(monkeypatch):
    monkeypatch.setattr(transport, "HTTP_DEADLINE_SECONDS", 0.25, raising=False)
    deadlines = []

    class TrackedDeadline(transport.HTTPDeadline):
        def __init__(self):
            super().__init__()
            deadlines.append(self)

    monkeypatch.setattr(transport, "HTTPDeadline", TrackedDeadline)

    def action(handler, stopped):
        if handler.path == "/ajax/library-info" or not handler.headers.get("Authorization"):
            reply(handler, 401, challenge=True)
        elif handler.path == "/slow":
            handler.send_response(200)
            handler.send_header("Content-Length", "100")
            handler.end_headers()
            handler.wfile.write(b"{}")
            stopped.wait(0.8)
        else:
            reply(handler)

    with peer(action) as (server, _):
        with pytest.raises(BrokerError, match="^server_unavailable$"):
            server.request("/slow")
        assert server.request("/fast") == {}
        assert len(deadlines) == 2
        assert all(not deadline.timer.is_alive() and not deadline.sockets for deadline in deadlines)


def test_connect_attempts_share_the_remaining_budget(monkeypatch):
    now = [0.0]
    attempts = []
    monkeypatch.setattr(transport, "monotonic", lambda: now[0])
    monkeypatch.setattr(transport, "HTTP_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.1", 443))] * 3,
    )

    class Connection:
        def settimeout(self, value):
            self.timeout = value

        def connect(self, target):
            attempts.append(self.timeout)
            now[0] += min(0.6, self.timeout)
            raise TimeoutError

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *args: Connection())
    with transport.HTTPDeadline() as deadline, pytest.raises(TimeoutError):
        deadline.connect(("example.org", 443))
    assert attempts == pytest.approx([1, 0.4])


def test_expiry_during_connect_cannot_send_request_bytes(monkeypatch):
    now = [0.0]
    sent = []
    monkeypatch.setattr(transport, "monotonic", lambda: now[0])
    with transport.HTTPDeadline() as deadline:
        connection = transport.DeadlineHTTPConnection("127.0.0.1", deadline=deadline)

        class Socket:
            def sendall(self, data):
                sent.append(data)

        def connect():
            now[0] = deadline.expires + 1
            connection.sock = Socket()

        monkeypatch.setattr(connection, "connect", connect)
        with pytest.raises(TimeoutError):
            connection.send(b"POST /write HTTP/1.1\r\n")
        connection.sock = None
    assert not sent


def test_deadline_bounds_a_stalled_tls_handshake(monkeypatch):
    monkeypatch.setattr(transport, "HTTP_DEADLINE_SECONDS", 0.25)
    stopped = Event()
    connected = Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def accept():
            with listener.accept()[0] as connection:
                connection.recv(4096)
                connected.set()
                stopped.wait(0.8)

        thread = Thread(target=accept)
        thread.start()
        try:
            server = transport.ContentServer(
                f"https://127.0.0.1:{listener.getsockname()[1]}",
                "library",
                "fixture-library",
                username="fixture",
                password=secrets.token_urlsafe(32),
            )
            started = time.monotonic()
            with pytest.raises(BrokerError, match="^server_unavailable$"):
                server.request("/write", {})
            assert time.monotonic() - started < 0.65
            assert connected.is_set()
            assert not server.authenticated
        finally:
            stopped.set()
            thread.join(timeout=2)
