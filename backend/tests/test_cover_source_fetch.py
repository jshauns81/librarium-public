"""Public-only transport must bind validation to the actual connected address."""

import io
import ipaddress
import socket
from unittest.mock import Mock
from urllib.parse import urlunsplit

import pytest
from librarium import cover_source_fetch as fetch


def answer(address):
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 443),
        )
    ]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.169.254",
        str(ipaddress.IPv4Address(0x0A000001)),
        "::1",
        "::ffff:8.8.8.8",
        "fe80::1",
        "64:ff9b::808:808",
        "2002:0808:0808::1",
    ],
    ids=[
        "loopback",
        "metadata",
        "private-network",
        "ipv6-loopback",
        "mapped",
        "link-local",
        "translation",
        "six-to-four",
    ],
)
def test_nonpublic_and_embedded_destinations_are_refused(address):
    with pytest.raises(fetch.Refused):
        fetch.check_url("https://images.example.org/a", resolve=lambda *a, **k: answer(address))


def test_all_dns_answers_must_be_public():
    with pytest.raises(fetch.Refused):
        fetch.check_url(
            "https://images.example.org/a",
            resolve=lambda *a, **k: answer("8.8.8.8") + answer("127.0.0.1"),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/a",
        urlunsplit(("https", "user@example.org", "/a", "", "")),
        "https://example.org:8443/a",
        "file:///a",
        "https://example.org/a\r\nX: a",
    ],
    ids=["http", "userinfo", "nonstandard-port", "file", "control-character"],
)
def test_only_credential_free_https_on_standard_port(url):
    with pytest.raises(fetch.Refused):
        fetch.check_url(url)


def test_pinned_connection_does_not_resolve_again(monkeypatch):
    sock = Mock()
    monkeypatch.setattr(fetch.socket, "socket", Mock(return_value=sock))
    monkeypatch.setattr(
        fetch.socket, "getaddrinfo", Mock(side_effect=AssertionError("second DNS lookup"))
    )
    context = Mock()
    c = fetch.PinnedHTTPS("images.example.org", answer("8.8.8.8")[0], 3, context)
    c.connect()
    sock.connect.assert_called_once_with(("8.8.8.8", 443))
    context.wrap_socket.assert_called_once_with(sock, server_hostname="images.example.org")


def response(status=200, headers=None, raw=b"payload"):
    r = io.BytesIO(raw)
    r.status = status
    r.getheader = lambda k, default=None: (headers or {}).get(k, default)
    return r


def test_redirect_to_private_is_checked_before_connect(monkeypatch):
    monkeypatch.setattr(
        fetch.socket,
        "getaddrinfo",
        lambda host, *a, **k: answer("8.8.8.8" if host == "images.example.org" else "127.0.0.1"),
    )
    connect = Mock(return_value=response(302, {"Location": "https://private.example.org/a"}))
    monkeypatch.setattr(fetch, "_request", connect)
    with pytest.raises(fetch.Refused):
        fetch.fetch("https://images.example.org/a")
    assert connect.call_count == 1


def test_oversized_body_is_refused(monkeypatch):
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: answer("8.8.8.8"))
    monkeypatch.setattr(fetch, "_request", lambda *a, **k: response(raw=b"x" * 11))
    with pytest.raises(fetch.Refused):
        fetch.fetch("https://images.example.org/a", maximum=10)


@pytest.mark.parametrize(
    "address", ["fec0::1", "3fff::1", "192.88.99.1", "2001:20::1", "2001:2::1"]
)
def test_special_purpose_ranges_are_explicitly_refused(address):
    assert not fetch.public(address)


def test_non_ascii_path_is_a_clean_refusal():
    with pytest.raises(fetch.Refused):
        fetch.check_url("https://example.org/café.jpg", resolve=lambda *a, **k: answer("8.8.8.8"))


def test_provider_image_redirect_cannot_escape_its_allowlist(monkeypatch):
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: answer("8.8.8.8"))
    connect = Mock(return_value=response(302, {"Location": "https://other.example.org/a.jpg"}))
    monkeypatch.setattr(fetch, "_request", connect)
    with pytest.raises(fetch.Refused):
        fetch.fetch("https://covers.openlibrary.org/a.jpg", source="openlibrary")
    assert connect.call_count == 1


@pytest.mark.parametrize(
    "source,url",
    [
        ("apple", "https://is1-ssl.mzstatic.com/a.jpg"),
        ("google", "https://books.google.com/a.jpg"),
        ("openlibrary", "https://covers.openlibrary.org/a.jpg"),
        ("hardcover", "https://assets.hardcover.app/a.jpg"),
        ("lexicanum", "https://web.archive.org/a.jpg"),
        ("paste", "https://images.example.org/a.jpg"),
    ],
)
def test_provider_image_allowlist_has_explicit_open_paste_lane(source, url):
    from librarium.cover_source_protocol import image_url

    assert image_url(url, source) == url
    if source != "paste":
        with pytest.raises(ValueError):
            image_url("https://images.example.org/a.jpg", source)
        with pytest.raises(ValueError):
            image_url(url.replace("/a.jpg", ".example.org/a.jpg"), source)


def test_dripping_headers_cannot_outlive_fetch_deadline(monkeypatch):
    import threading
    import time
    from urllib.parse import urlsplit

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    stop = threading.Event()

    def serve():
        sock, _ = listener.accept()
        with sock:
            sock.recv(4096)
            try:
                for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\nx":
                    sock.sendall(bytes([byte]))
                    if stop.wait(0.03):
                        break
            except OSError:
                pass

    thread = threading.Thread(target=serve)
    thread.start()
    address = answer("127.0.0.1")[0]
    address = (*address[:4], listener.getsockname())
    monkeypatch.setattr(fetch, "check_url", lambda *a: (urlsplit("https://example.org/a"), address))
    context = Mock()
    context.wrap_socket.side_effect = lambda sock, **kw: sock
    monkeypatch.setattr(fetch.ssl, "create_default_context", lambda: context)
    before = time.monotonic()
    try:
        with pytest.raises(fetch.SourceFailure) as error:
            fetch.fetch("https://example.org/a", seconds=0.15)
        assert error.value.state == "timed_out"
        assert time.monotonic() - before < 1
    finally:
        stop.set()
        thread.join(timeout=2)
        listener.close()


@pytest.mark.parametrize(
    "host",
    [
        "wh40k.lexicanum.com",
        "whfb.lexicanum.com",
        "ageofsigmar.lexicanum.com",
        "catalogue.lexicanum.com",
    ],
)
def test_live_lexicanum_is_refused_before_dns_even_for_pasted_urls(monkeypatch, host):
    from librarium.cover_source_protocol import image_url

    url = f"https://{host}/a.jpg"
    resolve = Mock(return_value=answer("8.8.8.8"))
    monkeypatch.setattr(fetch.socket, "getaddrinfo", resolve)
    for source in ("lexicanum", "paste"):
        with pytest.raises(ValueError):
            image_url(url, source)
    with pytest.raises(fetch.Refused):
        fetch.check_url(url)
    resolve.assert_not_called()


def test_google_key_is_never_forwarded_on_redirect(monkeypatch):
    from librarium import cover_providers as p

    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "fixture-key")
    monkeypatch.setattr(p, "_pace", lambda *a: None)
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: answer("8.8.8.8"))
    calls = []

    def request(parts, *args):
        calls.append(parts)
        return response(302, {"Location": "https://example.org/?key=fixture-key"})

    monkeypatch.setattr(fetch, "_request", request)
    with pytest.raises(fetch.Refused):
        p.src_google("Novel", "Author", "")
    assert len(calls) == 1


def test_hardcover_admits_its_published_asset_host_only():
    from librarium.cover_source_protocol import image_url

    # Hardcover's GraphQL image.url values are served from this host.
    url = "https://assets.hardcover.app/external_data/12345678/0123456789abcdef.jpeg"
    assert image_url(url, "hardcover") == url
    for refused in (
        "https://images.hardcover.app/a.jpg",
        "https://cdn.assets.hardcover.app/a.jpg",
        "https://hardcover.app/a.jpg",
    ):
        with pytest.raises(ValueError):
            image_url(refused, "hardcover")
