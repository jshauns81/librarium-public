"""LF's added_formats transport; Calibre remains the only database owner."""

import base64
import json
import socket
from hashlib import sha256
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from ssl import SSLContext
from threading import RLock, Timer
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPDigestAuthHandler,
    HTTPHandler,
    HTTPPasswordMgrWithDefaultRealm,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

import msgpack

from librarium.delivery_broker import BrokerError, canonical, fingerprint

MAX_BYTES = 32 * 1024 * 1024
HTTP_DEADLINE_SECONDS = 45


class HTTPDeadline:
    def __init__(self):
        self.expires = monotonic() + HTTP_DEADLINE_SECONDS
        self.lock = RLock()
        self.sockets = []
        self.expired = False
        self.timer = Timer(HTTP_DEADLINE_SECONDS, self.interrupt)
        self.timer.daemon = True

    def __enter__(self):
        self.timer.start()
        return self

    def __exit__(self, *args):
        self.timer.cancel()
        self.timer.join()
        self.sockets.clear()

    def remaining(self):
        remaining = self.expires - monotonic()
        if self.expired or remaining <= 0:
            raise TimeoutError
        return min(15, remaining)

    def interrupt(self):
        with self.lock:
            self.expired = True
            for sock in self.sockets:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def watch(self, sock):
        with self.lock:
            try:
                sock.settimeout(self.remaining())
            except OSError:
                sock.close()
                raise
            # urllib clears connection.sock after headers; the body still uses it.
            self.sockets.append(sock)

    def connect(self, address, timeout=None, source_address=None):
        failure = OSError("no server address")
        for family, kind, protocol, _, target in socket.getaddrinfo(
            address[0], address[1], 0, socket.SOCK_STREAM
        ):
            self.remaining()
            sock = socket.socket(family, kind, protocol)
            try:
                self.watch(sock)
                if source_address:
                    sock.bind(source_address)
                sock.connect(target)
                self.remaining()
                return sock
            except OSError as error:
                sock.close()
                failure = error
        raise failure


class DeadlineHTTPConnection(HTTPConnection):
    def __init__(self, *args, deadline, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadline = deadline
        self._create_connection = deadline.connect

    def send(self, data):
        self.deadline.remaining()
        if self.sock is None and self.auto_open:
            self.connect()
        self.deadline.remaining()
        return super().send(data)


class DeadlineHTTPSConnection(DeadlineHTTPConnection, HTTPSConnection):
    _context: SSLContext
    _tunnel_host: str | None

    def connect(self):
        HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(
            self.sock,
            server_hostname=self._tunnel_host or self.host,
            do_handshake_on_connect=False,
        )
        self.deadline.watch(self.sock)
        self.sock.do_handshake()
        self.deadline.remaining()


class DeadlineHTTPHandler(HTTPHandler):
    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def http_open(self, req):
        return self.do_open(
            lambda *args, **kw: DeadlineHTTPConnection(*args, deadline=self.deadline, **kw), req
        )


class DeadlineHTTPSHandler(HTTPSHandler):
    _context: SSLContext

    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def https_open(self, req):
        return self.do_open(
            lambda *args, **kw: DeadlineHTTPSConnection(*args, deadline=self.deadline, **kw),
            req,
            context=self._context,
        )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DigestAuth(HTTPDigestAuthHandler):
    def http_error_401(self, req, fp, code, msg, headers):
        try:
            return super().http_error_401(req, fp, code, msg, headers)
        finally:
            fp.close()


class BasicAuth(HTTPBasicAuthHandler):
    def http_error_401(self, req, fp, code, msg, headers):
        try:
            return super().http_error_401(req, fp, code, msg, headers)
        finally:
            fp.close()


class ContentServer:
    supervised = True
    recovery_required = True

    def __init__(self, url, library_id, library_uuid, *, username="", password=""):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1"})
            or not library_id
            or not library_uuid
        ):
            raise BrokerError("server_configuration_invalid")
        # Without a login, anything that can reach the server could write books
        # around Librarium's approvals, so writable access always authenticates.
        if not username or not password:
            raise BrokerError("server_credentials_required")
        # Digest lets a process squatting on the port test guesses offline, so only
        # a generated secret is accepted (for example secrets.token_urlsafe(32)).
        if len(password) < 32 or len(set(password)) < 12:
            raise BrokerError("server_credentials_weak")
        self.authenticated = False
        self.url = url.rstrip("/")
        self.library_id, self.library_uuid = quote(library_id, safe=""), library_uuid
        self.lock = RLock()
        self.manager = HTTPPasswordMgrWithDefaultRealm()
        self.manager.add_password(None, self.url + "/", username, password)

    def opener(self, deadline, *, authenticated=True):
        handlers = [
            ProxyHandler({}),
            NoRedirect(),
            DeadlineHTTPHandler(deadline),
            DeadlineHTTPSHandler(deadline),
        ]
        if authenticated:
            handlers.append(DigestAuth(self.manager))
            # Basic exposes a reusable password; only answer it inside TLS.
            if urlsplit(self.url).scheme == "https":
                handlers.append(BasicAuth(self.manager))
        return build_opener(*handlers)

    @classmethod
    def configured(cls, environment, library_uuid):
        username = environment.get("LIBRARIUM_CALIBRE_USERNAME", "")
        password = environment.get("LIBRARIUM_CALIBRE_PASSWORD", "")
        secret_file = environment.get("LIBRARIUM_CALIBRE_CREDENTIALS_FILE")
        if secret_file:
            from librarium.delivery_writer import read_secret

            try:
                secret = json.loads(read_secret(secret_file))
                if set(secret) != {"username", "password"}:
                    raise ValueError
                username, password = secret["username"], secret["password"]
            except ValueError, TypeError, KeyError:
                raise BrokerError("server_credentials_invalid") from None
        if type(username) is not str or type(password) is not str:
            raise BrokerError("server_credentials_invalid")
        return cls(
            environment.get("LIBRARIUM_CALIBRE_URL", ""),
            environment.get("LIBRARIUM_CALIBRE_LIBRARY_ID", ""),
            library_uuid,
            username=username,
            password=password,
        )

    def require_authentication(self, deadline):
        """Refuse a server that answers without a login; check once per process."""
        if self.authenticated:
            return
        anonymous = self.opener(deadline, authenticated=False)
        try:
            with anonymous.open(
                Request(self.url + "/ajax/library-info"), timeout=deadline.remaining()
            ):
                deadline.remaining()
        except HTTPError as error:
            error.close()
            deadline.remaining()
            if error.code != 401:
                raise BrokerError("server_unavailable") from None
            self.authenticated = True
            return
        except URLError, OSError, HTTPException, ValueError:
            raise BrokerError("server_unavailable") from None
        raise BrokerError("server_authentication_required")

    def request(self, path, value=None, *, binary=False):
        request = Request(
            self.url + path,
            data=None if value is None else canonical(value),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/x-msgpack" if binary else "application/json",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with HTTPDeadline() as deadline:
                self.require_authentication(deadline)
                with self.opener(deadline).open(request, timeout=deadline.remaining()) as response:
                    limit = MAX_BYTES + 1024 if binary else 512 * 1024
                    data = response.read(limit + 1)
                    deadline.remaining()
                    if len(data) > limit:
                        raise BrokerError("server_response_budget_exceeded")
                    value = (
                        msgpack.unpackb(data, raw=False, strict_map_key=False)
                        if binary
                        else json.loads(data)
                    )
                    deadline.remaining()
                    return value
        except HTTPError as error:
            error.close()
            raise BrokerError("server_unavailable") from None
        except URLError, OSError, HTTPException, ValueError, TypeError, AttributeError:
            raise BrokerError("server_unavailable") from None

    def export(self, *args, binary=False):
        value = self.request(
            "/cdb/cmd/export/0?library_id=" + self.library_id, list(args), binary=binary
        )
        if type(value) is not dict or set(value) != {"result"}:
            raise BrokerError("server_export_failed")
        return value["result"]

    def format(self, book_id, fmt):
        data = self.export("fmt", book_id, fmt, None, binary=True)
        if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
            raise BrokerError("format_unavailable")
        return data

    def observe(self, target):
        with self.lock:
            if type(target) is not dict or set(target) != {"library_uuid", "book_id", "book_uuid"}:
                raise BrokerError("target_invalid")
            text = target["book_id"]
            if (
                type(text) is not str
                or not text.isascii()
                or not text.isdecimal()
                or not 1 <= len(text) <= 12
                or str(int(text)) != text
                or int(text) < 1
            ):
                raise BrokerError("target_invalid")
            book_id = int(text)
            setup = self.export("setup", book_id, "all")
            fields = self.request(
                "/ajax/book/" + text + "/" + self.library_id + "?category_urls=false"
            )
            if (
                target["library_uuid"] != self.library_uuid
                or setup[3] != self.library_uuid
                or fields["uuid"] != target["book_uuid"]
            ):
                raise BrokerError("target_changed")
            formats = fields.get("formats", [])
            if type(formats) is not list or len(formats) > 16:
                raise BrokerError("format_budget_exceeded")
            if "epub" not in formats:
                raise BrokerError("format_unavailable")
            data = self.format(book_id, "EPUB")
            if fields.get("format_metadata", {}).get("epub", {}).get("size") != len(data):
                raise BrokerError("format_bookkeeping_changed")
            cover = self.export("cover", book_id, binary=True)
            others = {
                fmt.upper(): sha256(self.format(book_id, fmt.upper())).hexdigest()
                for fmt in formats
                if fmt != "epub"
            }
            # Download projections and derived page counts change after a replacement.
            for key in (
                "last_modified",
                "pages",
                "format_metadata",
                "cover",
                "thumbnail",
                "main_format",
                "other_formats",
            ):
                fields.pop(key, None)
            metadata = {
                "fields_sha256": fingerprint(fields),
                "cover_sha256": sha256(cover).hexdigest() if cover else None,
                "other_formats": others,
            }
            observed = {"sha256": sha256(data).hexdigest(), "size": len(data), "metadata": metadata}
            return {**observed, "inventory": fingerprint(observed)}

    def prepare_write(self, target, size):
        if not 0 < size <= MAX_BYTES:
            raise BrokerError("format_unavailable")
        exclusion = getattr(self, "exclusion", None)
        if exclusion is not None and not exclusion.verified(self.library_uuid):
            raise BrokerError("independent_writer_not_excluded")

    def replace(self, target, output):
        self.request(
            "/cdb/set-fields/" + target["book_id"] + "/" + self.library_id,
            {
                "changes": {
                    "added_formats": [
                        {
                            "ext": "epub",
                            "data_url": "data:application/epub+zip;base64,"
                            + base64.b64encode(output).decode("ascii"),
                        }
                    ]
                },
                "loaded_book_ids": [int(target["book_id"])],
            },
        )

    def sync(self, target):
        # Server read-back proves bytes, not a remote filesystem fsync or storage backup.
        pass
