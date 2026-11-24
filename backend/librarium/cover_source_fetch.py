"""Bounded HTTPS with every DNS answer checked and TLS pinned to a checked address.

Public-address checks and redirect policy derive from LF safe_fetch; connection
binding closes its check/lookup gap. No proxy, cookie jar or ambient auth is used.
"""

import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
from urllib.parse import urlencode, urljoin, urlsplit

from librarium.cover_source_protocol import image_url, live_wiki_host

IO_TIMEOUT = 5
DENY_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "fec0::/10",
        "3fff::/20",
        "192.88.99.0/24",
        "2001::/23",
        "2002::/16",
        "198.18.0.0/15",
        "192.0.0.0/24",
        "100.64.0.0/10",
        "0.0.0.0/8",
        (0x0A000000, 8),  # RFC 1918
        "127.0.0.0/8",
        "169.254.0.0/16",
        (0xAC100000, 12),  # RFC 1918
        (0xC0A80000, 16),  # RFC 1918
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "100::/64",
        "2001:db8::/32",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)

MAX_BYTES = 16 * 1024 * 1024


class Refused(ValueError):
    pass


class SourceFailure(Exception):
    def __init__(self, state, status=None):
        self.state = state
        self.status = status
        super().__init__(state)


def public(address):
    ip = ipaddress.ip_address(address)
    return (
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not (
            isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)
        )
        and not any(ip in network for network in DENY_NETWORKS)
    )


def check_url(url, resolve=None):
    try:
        if (
            not isinstance(url, str)
            or not url.isascii()
            or len(url) > 4096
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)
            or "\\" in url
        ):
            raise ValueError
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.port not in (None, 443)
            or p.fragment
            or live_wiki_host(p.hostname)
        ):
            raise ValueError
        found = (resolve or socket.getaddrinfo)(p.hostname, 443, type=socket.SOCK_STREAM)
        if not found or len(found) > 32 or not all(public(i[4][0]) for i in found):
            raise ValueError
        return p, found[0]
    except (OSError, ValueError, UnicodeError):
        raise Refused("Use an HTTPS image address on a public website.") from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout, context):
        super().__init__(host, timeout=min(IO_TIMEOUT, timeout), context=context)
        self.address = address
        self.tls_context = context

    def connect(self):
        family, socktype, proto, _, destination = self.address
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(self.timeout)
            sock.connect(destination)
            self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _request(parts, address, timeout, method, body, headers):
    c = PinnedHTTPS(parts.hostname, address, timeout, ssl.create_default_context())
    try:
        c.request(
            method,
            (parts.path or "/") + ("?" + parts.query if parts.query else ""),
            body=body,
            headers=headers,
        )
        sock = c.sock

        def interrupt():
            try:
                if sock:
                    sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

        watchdog = threading.Timer(timeout, interrupt)
        watchdog.daemon = True
        watchdog.start()
        r = c.getresponse()
        r.__dict__["_cover_watchdog"] = watchdog
        # HTTPResponse.close also releases its socket file; the connection is never pooled.
        r.__dict__["_cover_connection"] = c
        return r
    except BaseException:
        if "watchdog" in locals():
            watchdog.cancel()
        c.close()
        raise


def fetch(
    url,
    *,
    maximum=MAX_BYTES,
    seconds=15,
    method="GET",
    payload=None,
    token=None,
    deadline=None,
    source=None,
    follow_redirects=True,
):
    deadline = min(deadline or float("inf"), time.monotonic() + seconds)
    headers = {"User-Agent": "Librarium-Cover-Sources/1.0", "Accept-Encoding": "identity"}
    body = json.dumps(payload).encode() if payload is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        if urlsplit(url).hostname != "api.hardcover.app":
            raise Refused("Credential destination refused.")
        headers["Authorization"] = (
            token if token.lower().startswith("bearer ") else "Bearer " + token
        )
    for hop in range(6):
        if time.monotonic() >= deadline:
            raise SourceFailure("timed_out")
        if source is not None:
            try:
                image_url(url, source)
            except ValueError as error:
                raise Refused(str(error)) from None
        parts, address = check_url(url)
        try:
            r = _request(
                parts, address, max(0.1, deadline - time.monotonic()), method, body, headers
            )
            try:
                if r.status in (301, 302, 303, 307, 308):
                    if not follow_redirects or token or method != "GET" or hop == 5:
                        raise Refused("This request cannot follow that redirect.")
                    url = urljoin(url, r.getheader("Location") or "")
                    continue
                if r.status == 429:
                    raise SourceFailure("rate_limited", r.status)
                if r.status in (401, 403):
                    raise SourceFailure("unavailable", r.status)
                if r.status < 200 or r.status >= 300:
                    raise SourceFailure("failed", r.status)
                if r.getheader("Content-Encoding", "identity") != "identity":
                    raise Refused("Compressed transport refused.")
                length = r.getheader("Content-Length")
                if length and (not length.isdecimal() or int(length) > maximum):
                    raise Refused("The response is too large.")
                data = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise SourceFailure("timed_out")
                    connection = getattr(r, "_cover_connection", None)
                    if connection and connection.sock:
                        connection.sock.settimeout(
                            min(IO_TIMEOUT, max(0.1, deadline - time.monotonic()))
                        )
                    chunk = r.read(min(65536, maximum + 1 - len(data)))
                    if not chunk:
                        return bytes(data)
                    data.extend(chunk)
                    if len(data) > maximum:
                        raise Refused("The response is too large.")
            finally:
                watchdog = getattr(r, "_cover_watchdog", None)
                if watchdog:
                    watchdog.cancel()
                r.close()
                connection = getattr(r, "_cover_connection", None)
                if connection:
                    connection.close()
        except TimeoutError:
            raise SourceFailure("timed_out") from None
        except (OSError, http.client.HTTPException):
            raise SourceFailure("timed_out" if time.monotonic() >= deadline else "failed") from None
    raise Refused("Too many redirects.")


def query_url(url, params):
    return (
        url
        + ("&" if "?" in url else "?")
        + urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    )
