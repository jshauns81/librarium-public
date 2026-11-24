"""The browser is a separate, authenticated, public-only retrieval boundary."""

import http.client
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from librarium import cover_source_protocol as protocol


def test_browser_auth_binds_method_path_body_and_time():
    sign = getattr(protocol, "browser_signature", None)
    assert callable(sign), "source-browser HMAC protocol is missing"
    signature = sign("x" * 32, "/goodreads", b'{"query":"Novel"}', "100")
    assert protocol.browser_authenticated(
        "x" * 32, "/goodreads", b'{"query":"Novel"}', "100", signature, now=100
    )
    for path, body, stamp, now in [
        ("/image", b'{"query":"Novel"}', "100", 100),
        ("/goodreads", b"{}", "100", 100),
        ("/goodreads", b'{"query":"Novel"}', "101", 100),
        ("/goodreads", b'{"query":"Novel"}', "100", 200),
    ]:
        assert not protocol.browser_authenticated("x" * 32, path, body, stamp, signature, now=now)


def test_browser_urls_are_closed_and_original_images_only():
    check = getattr(protocol, "browser_url", None)
    assert callable(check), "source-browser URL policy is missing"
    check("https://www.goodreads.com/search?q=Novel", "goodreads")
    check("https://wh40k.lexicanum.com/wiki/Novel", "lexicanum")
    check("https://wh40k.lexicanum.com/wiki/Novel:_The_Sequel", "lexicanum")
    check("https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg", "image")
    for url, kind in [
        ("https://www.goodreads.com.evil.example/search?q=x", "goodreads"),
        ("https://www.goodreads.com/logout", "goodreads"),
        ("https://user" + "@www.goodreads.com/search?q=x", "goodreads"),
        ("https://wh40k.lexicanum.com/wiki/Special:Export/Novel", "lexicanum"),
        ("https://wh40k.lexicanum.com/wiki/Novel?action=edit", "lexicanum"),
        (
            "https://wh40k.lexicanum.com/mediawiki/images/thumb/a/ab/Novel.jpg/100px-Novel.jpg",
            "image",
        ),
        ("https://wh40k.lexicanum.com/mediawiki/images/a/ab/Book2.jpg", "image"),
        ("https://en.lexicanum.com/wiki/Novel", "lexicanum"),
        ("https://127.0.0.1/a.jpg", "image"),
        ("https://www.goodreads.com:444/search?q=x", "goodreads"),
    ]:
        with pytest.raises(ValueError):
            check(url, kind)


def test_proxy_checks_every_dns_answer_and_pins_the_connect(monkeypatch):
    from librarium import source_browser

    public = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    private = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [public, private])
    with pytest.raises(ValueError):
        source_browser.destination("www.goodreads.com:443")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [public])
    assert source_browser.destination("www.goodreads.com:443") == public
    with pytest.raises(ValueError):
        source_browser.destination("localhost:443")


def test_goodreads_book_navigation_params_are_admitted_but_actions_are_refused():
    url = "https://www.goodreads.com/book/show/123.Novel?from_search=true&from_srp=true&qid=abc&rank=1"
    assert protocol.browser_url(url, "goodreads") == url
    for suffix in ("?action=edit", "?redirect=https://evil.example", "?unknown=", "/other"):
        with pytest.raises(ValueError):
            protocol.browser_url(
                "https://www.goodreads.com/book/show/123.Novel" + suffix, "goodreads"
            )


def test_goodreads_current_cdn_is_restricted_to_goodreads_book_images():
    url = "https://m.media-amazon.com/images/S/compressed.photo.goodreads.com/books/1/2.jpg"
    assert protocol.browser_url(url, "image") == url
    assert protocol.image_url(url, "goodreads") == url
    for other in (
        "https://m.media-amazon.com/images/I/unrelated.jpg",
        "https://m.media-amazon.com.evil.example/images/S/compressed.photo.goodreads.com/books/1/2.jpg",
        url + "?action=edit",
    ):
        with pytest.raises(ValueError):
            protocol.browser_url(other, "image")


def test_connect_eof_releases_the_slot_while_client_stays_open(monkeypatch):
    from librarium import source_browser

    upstream = socket.socket()
    upstream.bind(("127.0.0.1", 0))
    upstream.listen()
    monkeypatch.setattr(
        source_browser,
        "destination",
        lambda _: (socket.AF_INET, socket.SOCK_STREAM, 0, "", upstream.getsockname()),
    )

    class PersistentProxy(source_browser.Proxy):
        protocol_version = "HTTP/1.1"

    server = source_browser.BoundedServer(("127.0.0.1", 0), PersistentProxy, capacity=1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = socket.create_connection(server.server_address, timeout=1)
    try:
        client.sendall(b"CONNECT www.goodreads.com:443 HTTP/1.1\r\nHost: www.goodreads.com\r\n\r\n")
        peer, _ = upstream.accept()
        try:
            headers = bytearray()
            while not headers.endswith(b"\r\n\r\n"):
                chunk = client.recv(1)
                assert chunk and len(headers) < 4096
                headers.extend(chunk)
            assert headers.startswith(b"HTTP/1.1 200")
        finally:
            peer.close()
        # Leave the client open: upstream EOF alone must end the handler.
        assert client.recv(1) == b""
        assert server.capacity.acquire(timeout=1)
        server.capacity.release()
    finally:
        client.close()
        upstream.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_a_profile_has_exactly_one_role_owner(tmp_path):
    from librarium import source_browser

    owner = getattr(source_browser, "profile_owner", None)
    assert callable(owner), "profile ownership must exclude a second role"
    first = owner(tmp_path)
    try:
        with pytest.raises(BlockingIOError):
            owner(tmp_path)
    finally:
        os.close(first)
    os.close(owner(tmp_path))


def test_authenticated_queue_is_bounded_and_reports_busy(monkeypatch):
    from librarium import source_browser

    entered = threading.Barrier(3)
    release = threading.Event()

    class Browser:
        def load(self, *args):
            entered.wait(timeout=5)
            assert release.wait(5)
            return {"state": "empty"}

    monkeypatch.setenv("LIBRARIUM_SOURCE_BROWSER_SECRET", "x" * 32)
    monkeypatch.setattr(source_browser.Handler, "browser", Browser())
    server = source_browser.BoundedServer(("127.0.0.1", 0), source_browser.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call():
        c = http.client.HTTPConnection(*server.server_address, timeout=3)
        raw = json.dumps({"url": "https://www.goodreads.com/search?q=Novel"}).encode()
        stamp = str(int(time.time()))
        try:
            c.request(
                "POST",
                "/goodreads",
                raw,
                {
                    "Content-Type": "application/json",
                    "X-Source-Time": stamp,
                    "X-Source-Signature": protocol.browser_signature(
                        "x" * 32, "/goodreads", raw, stamp
                    ),
                },
            )
            response = c.getresponse()
            return response.status, json.loads(response.read())
        finally:
            c.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call) for _ in range(2)]
            try:
                entered.wait(timeout=5)
                assert call() == (503, {"state": "busy"})
            finally:
                release.set()
            assert all(f.result() == (200, {"state": "empty"}) for f in futures)
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_busy_response_survives_an_in_progress_upload():
    from librarium import source_browser

    server = source_browser.BoundedServer(("127.0.0.1", 0), source_browser.Handler, capacity=1)
    assert server.capacity.acquire(blocking=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=3) as client:
            client.sendall(
                b"POST /goodreads HTTP/1.1\r\nHost: localhost\r\n"
                b"Content-Length: 4096\r\nContent-Type: application/json\r\n\r\n"
            )
            assert client.recv(1, socket.MSG_PEEK) == b"H"
            client.sendall(b"x" * 4096)
            client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while chunk := client.recv(4096):
                response.extend(chunk)
            assert response.startswith(b"HTTP/1.1 503 Service Unavailable\r\n")
            assert response.endswith(b'{"state":"busy"}')
    finally:
        server.capacity.release()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_busy_slow_client_does_not_block_later_connections():
    from librarium import source_browser

    server = source_browser.BoundedServer(("127.0.0.1", 0), source_browser.Handler, capacity=1)
    assert server.capacity.acquire(blocking=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=2) as slow:
            assert slow.recv(1, socket.MSG_PEEK) == b"H"
            with socket.create_connection(server.server_address, timeout=2) as following:
                assert following.recv(64).startswith(b"HTTP/1.1 503")
    finally:
        server.capacity.release()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
