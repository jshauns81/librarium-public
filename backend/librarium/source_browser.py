"""Network-only Chrome owner. Stdlib-only; also runs on the pinned image's Python 3.12."""

import base64
import fcntl
import json
import os
import select
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from librarium.cover_source_fetch import public
from librarium.cover_source_protocol import (
    BROWSER_HOSTS,
    GOODREADS_IMAGES,
    NON_ARTICLE_NAMESPACES,
    WIKI_HOSTS,
    browser_authenticated,
    browser_url,
)

MAX_PAGE = 2 * 1024 * 1024
MAX_IMAGE = 16 * 1024 * 1024


def profile_owner(directory):
    descriptor = os.open(directory / ".role-owner", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def destination(authority):
    if authority not in {host + ":443" for host in BROWSER_HOSTS}:
        raise ValueError("Unsupported browser destination.")
    answers = socket.getaddrinfo(authority[:-4], 443, type=socket.SOCK_STREAM)
    if not answers or len(answers) > 32 or not all(public(answer[4][0]) for answer in answers):
        raise ValueError("Nonpublic browser destination.")
    return answers[0]


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 2

    def __init__(self, *args, capacity=2, **kwargs):
        self.capacity = threading.BoundedSemaphore(capacity)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(
                    b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 16\r\nConnection: close\r\n\r\n{"state":"busy"}'
                )
                request.shutdown(socket.SHUT_WR)
                deadline, remaining = time.monotonic() + 0.1, 8192
                while remaining:
                    left = deadline - time.monotonic()
                    if left <= 0 or not select.select([request], [], [], left)[0]:
                        break
                    chunk = request.recv(remaining)
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


class Proxy(BaseHTTPRequestHandler):
    """HTTPS CONNECT only. Check every DNS answer; connect the numeric pinned address."""

    def log_message(self, *args):
        pass

    def do_CONNECT(self):
        try:
            family, kind, protocol, _, address = destination(self.path)
            with socket.socket(family, kind, protocol) as upstream:
                upstream.settimeout(5)
                upstream.connect(address)
                self.send_response(200)
                self.end_headers()
                deadline, total = time.monotonic() + 80, 0
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([self.connection, upstream], [], [], 1)
                    for source in ready:
                        chunk = source.recv(65536)
                        if not chunk:
                            return
                        total += len(chunk)
                        if total > 20 * 1024 * 1024:
                            return
                        (upstream if source is self.connection else self.connection).sendall(chunk)
        except (ValueError, OSError):
            pass
        finally:
            self.close_connection = True


class Browser:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None

    def stop(self):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None

    def load(self, target, kind):
        browser_url(target, "image" if kind == "image" else kind)
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.stop()
                for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
                    (Path("/data/profile") / name).unlink(missing_ok=True)
                self.process = subprocess.Popen(
                    ["/usr/bin/xvfb-run", "-a", "node", "/role/browser.cjs"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env={k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG"}},
                    start_new_session=True,
                )
            assert self.process.stdin is not None and self.process.stdout is not None
            command = {
                "url": target,
                "kind": kind,
                "wikis": WIKI_HOSTS,
                "images": GOODREADS_IMAGES,
                "namespaces": NON_ARTICLE_NAMESPACES,
            }
            try:
                self.process.stdin.write(json.dumps(command).encode() + b"\n")
                self.process.stdin.flush()
                # readline cannot be allowed to wait forever after the first byte.
                deadline, raw = time.monotonic() + 80, bytearray()
                while not raw.endswith(b"\n"):
                    left = deadline - time.monotonic()
                    if left <= 0 or not select.select([self.process.stdout], [], [], left)[0]:
                        raise TimeoutError
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk or len(raw) + len(chunk) > 24 * 1024 * 1024:
                        raise ValueError
                    raw.extend(chunk)
                result = json.loads(raw)
                if result.get("state") != "ok":
                    return {
                        "state": result.get("state")
                        if result.get("state")
                        in {"challenged", "timed_out", "rate_limited", "empty"}
                        else "failed"
                    }
                browser_url(result["url"], "image" if kind == "image" else kind)
                if kind == "image":
                    data = base64.b64decode(result["data"], validate=True)
                    if not 0 < len(data) <= MAX_IMAGE:
                        raise ValueError
                    return {"state": "ok", "data": data}
                if type(result.get("html")) is not str or len(result["html"].encode()) > MAX_PAGE:
                    raise ValueError
                if kind == "lexicanum":
                    if type(result.get("xml")) is not str or len(result["xml"].encode()) > MAX_PAGE:
                        raise ValueError
                    if result.get("cover_url"):
                        browser_url(result["cover_url"], "image")
                        if result["cover_url"].split("/")[2] != target.split("/")[2]:
                            raise ValueError
                return result
            except (ValueError, OSError, TimeoutError):
                self.stop()
                return {"state": "unavailable"}


class Handler(BaseHTTPRequestHandler):
    browser = Browser()

    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            length = self.headers.get("Content-Length", "")
            if (
                not length.isdecimal()
                or not 0 < int(length) <= 4096
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type") != "application/json"
            ):
                raise ValueError
            raw = self.rfile.read(int(length))
            if len(raw) != int(length):
                raise ValueError
            if not browser_authenticated(
                os.environ["LIBRARIUM_SOURCE_BROWSER_SECRET"],
                self.path,
                raw,
                self.headers.get("X-Source-Time", ""),
                self.headers.get("X-Source-Signature", ""),
            ):
                self.send_error(403)
                return
            value = json.loads(raw)
            if (
                self.path not in {"/goodreads", "/lexicanum", "/lexicanum_search", "/image"}
                or type(value) is not dict
                or set(value) != {"url"}
            ):
                raise ValueError
            result = self.browser.load(value["url"], self.path[1:])
            data = result.pop("data", None)
            body = data if data is not None else json.dumps(result).encode()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/octet-stream" if data is not None else "application/json",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, OSError, KeyError, TypeError):
            self.send_error(422)


def main():
    secret = os.environ.get("LIBRARIUM_SOURCE_BROWSER_SECRET", "")
    if len(secret) < 32 or not secret.isascii() or any(ord(c) <= 32 for c in secret):
        raise ValueError("Configure the protected source-browser key.")
    Path("/data/profile").mkdir(exist_ok=True)
    owner = profile_owner(Path("/data/profile"))
    # Only this role owns this profile; a replaced container leaves stale singleton links.
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        (Path("/data/profile") / name).unlink(missing_ok=True)
    proxy = BoundedServer(("127.0.0.1", 8127), Proxy, capacity=16)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        BoundedServer(
            (socket.gethostbyname("source-browser-control-listener"), 8126), Handler
        ).serve_forever()
    finally:
        Handler.browser.stop()
        os.close(owner)


if __name__ == "__main__":
    main()
