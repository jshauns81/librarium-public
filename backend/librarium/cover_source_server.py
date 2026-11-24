"""Librarium network-only role: typed search and public image fetch, no DB or mounts."""

import hmac
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from librarium.cover_source_fetch import Refused, SourceFailure, fetch
from librarium.cover_source_protocol import SOURCES, STATES, image_request, request

CAPACITY = threading.BoundedSemaphore(8)
SEARCH_LOCK = threading.Lock()
CACHE: dict[str, tuple[float, bytes]] = {}
PROVIDER_STATE: dict = {}
SOURCE_LOCKS = {s: threading.Lock() for s in SOURCES}


def secret():
    value = os.environ.get("LIBRARIUM_COVER_SOURCES_SECRET", "")
    if len(value) < 32 or not value.isascii() or any(ord(c) <= 32 for c in value):
        raise ValueError("Configure the protected cover-control secret.")
    return value


def control_address():
    return socket.gethostbyname("cover-control-listener")


def run_child(raw, path):
    env = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    source = request(json.loads(raw))[1] if path == "/search" else None
    if os.environ.get("HARDCOVER_TOKEN") and source == "hardcover":
        env["HARDCOVER_TOKEN"] = os.environ["HARDCOVER_TOKEN"]
    if os.environ.get("GOOGLE_BOOKS_API_KEY") and source == "google":
        env["GOOGLE_BOOKS_API_KEY"] = os.environ["GOOGLE_BOOKS_API_KEY"]
    if path == "/search":
        raw = json.dumps(
            {"value": json.loads(raw), "state": PROVIDER_STATE.get(source, {})}
        ).encode()
    result = subprocess.run(
        [sys.executable, "-m", "librarium.cover_source_server", path],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        timeout=90,
        check=True,
    )
    if len(result.stdout) > 16 * 1024 * 1024:
        raise ValueError
    if path == "/search":
        result_value = json.loads(result.stdout)
        PROVIDER_STATE[source] = result_value["state"]
        return json.dumps(result_value["reply"], allow_nan=False).encode()
    return result.stdout


def search_reply(value, raw):
    q, source = request(value)
    key = json.dumps([q, source], sort_keys=True)
    started = time.monotonic()
    state, count = "failed", 0
    try:
        with SOURCE_LOCKS[source]:
            with SEARCH_LOCK:
                hit = CACHE.get(key)
                output = hit[1] if hit and time.monotonic() - hit[0] < 6 * 3600 else None
            if output is None:
                output = run_child(raw, "/search")
                if json.loads(output)["state"] in {"results", "empty"}:
                    with SEARCH_LOCK:
                        if len(CACHE) >= 128:
                            CACHE.pop(next(iter(CACHE)))
                        CACHE[key] = (time.monotonic(), output)
            reply = json.loads(output)
            state = reply["state"] if reply["state"] in STATES else "failed"
            count = min(6, len(reply["candidates"]))
            return output
    except subprocess.TimeoutExpired:
        state = "timed_out"
        raise
    finally:
        print(
            json.dumps(
                {
                    "source": source,
                    "state": state,
                    "count": count,
                    "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                }
            ),
            file=sys.stderr,
            flush=True,
        )


class Server(ThreadingHTTPServer):
    request_queue_size = 4

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(5)
        return sock, address

    def process_request(self, request, client_address):
        if not CAPACITY.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            CAPACITY.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            CAPACITY.release()


def execute(value):
    from librarium import cover_providers as p

    q, source = request(value)
    import time

    p._deadline.at = time.monotonic() + 80
    funcs = {
        "apple": p.src_apple,
        "google": p.src_google,
        "openlibrary": p.src_openlibrary,
        "hardcover": p.src_hardcover,
        "lexicanum": p.src_lexicanum,
    }
    try:
        items = funcs[source](q["title"], q["author"], q["isbn"])[:6]
        state = "results" if items else "empty"
        if source == "lexicanum" and getattr(p._lx_tl, "incomplete", False):
            state = "partial"
        return {"state": state, "candidates": items}
    except SourceFailure as e:
        return {"state": e.state, "candidates": []}
    except ValueError, KeyError, TypeError, Refused:
        return {"state": "failed", "candidates": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.connection.settimeout(5)
        try:
            supplied = self.headers.get("X-Cover-Control", "")
            if not supplied.isascii() or not hmac.compare_digest(supplied, secret()):
                self.send_error(403)
                return
            length = self.headers.get("Content-Length", "")
            if (
                not length.isdecimal()
                or not 0 < int(length) <= 4096
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Type") != "application/json"
            ):
                raise ValueError
            raw = self.rfile.read(int(length))
            value = json.loads(raw)
            if self.path == "/search":
                request(value)
            elif self.path == "/image":
                image_request(value)
            else:
                raise ValueError
            output = (
                search_reply(value, raw) if self.path == "/search" else run_child(raw, "/image")
            )
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/json" if self.path == "/search" else "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)
        except subprocess.TimeoutExpired:
            self.send_error(504)
        except ValueError, OSError, subprocess.SubprocessError:
            self.send_error(422)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # The parent deadline bounds DNS as well as network IO in this fresh process.
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        value = json.loads(sys.stdin.buffer.read(16385))
        if sys.argv[1] == "/search":
            from librarium import cover_providers as p

            state = value["state"]
            p._host_next.update(state.get("pace", {}))
            p._wb_state.update(state.get("wayback", {}))
            reply = execute(value["value"])
            print(
                json.dumps(
                    {
                        "reply": reply,
                        "state": {
                            "pace": p._host_next,
                            "wayback": p._wb_state,
                        },
                    },
                    allow_nan=False,
                )
            )
        else:
            try:
                image_request(value)
                sys.stdout.buffer.write(fetch(value["url"], source=value["source"]))
            except SourceFailure, Refused:
                sys.exit(2)
    else:
        secret()
        server = Server((control_address(), 8124), Handler)
        server.request_queue_size = 4
        server.serve_forever()
