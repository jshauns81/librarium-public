"""Selected metadata from Library Finish's read endpoint; no library writer access."""

import http.client
import json
import math
import re
import socket
import threading
import time
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from librarium.validation import bounded_text

MAX_BODY = 2 * 1024 * 1024
PAGE_SIZE = 24
VERSION = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]+")
TOKEN = re.compile(r"[a-f0-9]{24}")
WORK = re.compile(r"w_[A-Za-z0-9_]{1,64}")
OWNERSHIP = {"all", "owned", "direct", "contained", "pending", "missing", "unknown"}


class LibraryError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status

    def payload(self):
        return {"error": str(self)}


class LibraryCheckChanged(LibraryError):
    def __init__(self, message="The library check changed. Reload the library before continuing."):
        super().__init__(message, 409)

    def payload(self):
        return {**super().payload(), "code": "library_check_changed"}


def origin(value: str):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not bounded_text(value, 300)
        ):
            raise ValueError
        return parsed.scheme, parsed.hostname, parsed.port
    except ValueError:
        raise ImproperlyConfigured(
            "LIBRARIUM_LIBRARY_URL must be an HTTP(S) server origin without credentials or paths"
        ) from None


def parameters(query):
    try:
        if set(query) - {"q", "page", "ownership", "sort", "snapshot"} or any(
            len(query.getlist(key)) != 1 for key in query
        ):
            raise ValueError
        q = query.get("q", "")
        page = int(query.get("page", "1"))
        ownership = query.get("ownership", "owned")
        sort = query.get("sort", "title")
        token = query.get("snapshot", "")
        if (
            not bounded_text(q, 200)
            or not 1 <= page <= 10000
            or ownership not in OWNERSHIP
            or sort not in {"title", "author"}
            or (token and not TOKEN.fullmatch(token))
        ):
            raise ValueError
        return {
            "q": q.strip(),
            "offset": (page - 1) * PAGE_SIZE,
            "limit": PAGE_SIZE,
            "ownership": ownership,
            "sort": sort,
            "snapshot": token,
            "show_missing": "1",
        }, page
    except ValueError, TypeError:
        raise LibraryError(
            "Use valid library filters and a search of up to 200 characters.", 400
        ) from None


def fetch(params: dict, deadline: float | None = None):
    scheme, host, port = origin(settings.LIBRARIUM_LIBRARY_URL)
    connection_type = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    if deadline is None:
        deadline = time.monotonic() + 3
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LibraryError("The library service took too long. Try again shortly.")
    conn = connection_type(host, port, timeout=min(1, remaining))
    timer = None
    try:
        conn.connect()
        transport = conn.sock
        assert transport is not None
        transport.settimeout(max(0.01, deadline - time.monotonic()))

        def expire():
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(max(0.01, deadline - time.monotonic()), expire)
        timer.daemon = True
        timer.start()
        conn.request(
            "GET",
            "/api/library/browse?" + urlencode(params),
            headers={
                "Accept": "application/json",
                "Connection": "close",
            },
        )
        with conn.getresponse() as response:
            if response.status == 400 and params.get("snapshot"):
                raise LibraryCheckChanged()
            if (
                response.status != 200
                or response.getheader("Content-Type", "").split(";")[0] != "application/json"
            ):
                raise LibraryError("The library service is unavailable. Try again shortly.")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
                raise ValueError
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ValueError
            data = json.loads(raw)
            if time.monotonic() >= deadline:
                raise LibraryError("The library service took too long. Try again shortly.")
            return data
    except OSError, http.client.HTTPException:
        raise LibraryError("The library service is unavailable. Try again shortly.") from None
    except ValueError, UnicodeError, RecursionError:
        raise LibraryError("The library service returned an unsupported response.") from None
    finally:
        if timer:
            timer.cancel()
        conn.close()


def mapping(value):
    if not isinstance(value, dict):
        raise TypeError
    return value


def text(value, size=1000):
    if not isinstance(value, str) or not bounded_text(value, size):
        raise ValueError
    return value


def integer(value, maximum=1_000_000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError
    return value


def rows(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError
    return value


def boolean(value):
    if type(value) is not bool:
        raise ValueError
    return value


def copies(values, current):
    result = []
    for raw in rows(values, 1000):
        item = mapping(raw)
        book_id = integer(item["calibre_id"], 2**53 - 1)
        if not book_id:
            raise ValueError
        result.append(
            {
                "calibre_id": book_id,
                "title": text(item["title"]),
                "last_known": boolean(item["last_known"]) or not current,
            }
        )
    return result


def project(data, params, page):
    try:
        data = mapping(data)
        meta = mapping(data["meta"])
        version = meta["catalogue_version"]
        if version is not None and (not isinstance(version, str) or not VERSION.fullmatch(version)):
            raise ValueError
        token = text(meta["snapshot"], 24)
        if not TOKEN.fullmatch(token):
            raise ValueError
        if params.get("snapshot") and token != params["snapshot"]:
            raise LibraryCheckChanged()
        coverage = meta["coverage"]
        if coverage not in {"complete", "partial", "unknown"}:
            raise ValueError
        loading = boolean(meta["loading"])
        checked = meta.get("taken_at")
        if checked is not None:
            checked = text(checked, 50)
            if datetime.fromisoformat(checked).utcoffset() is None:
                raise ValueError
        complete = coverage == "complete" and not loading and bool(version) and bool(checked)
        if coverage == "complete" and not complete:
            coverage = "partial"
        limit = params["limit"]
        if integer(data["offset"]) != params["offset"] or integer(data["limit"]) != limit:
            raise ValueError
        total = integer(data["total"])
        if integer(data["distinct_total"]) != total:
            raise ValueError
        works, ids = [], set()
        for raw in rows(data["items"], limit):
            item = mapping(raw)
            wid = text(item["work_id"], 66)
            if not WORK.fullmatch(wid) or wid in ids or not version:
                raise ValueError
            ids.add(wid)
            current = boolean(item["ownership_current"]) and complete
            owned, contained = copies(item["owned"], current), copies(item["contained_in"], current)
            candidates = []
            for candidate in rows(item["candidates"], 1000):
                candidate = mapping(candidate)
                if candidate["stage"] not in {"inbox", "shelve"} or candidate["confidence"] not in {
                    "possible",
                    "confirmed",
                }:
                    raise ValueError
                candidates.append({k: text(candidate[k]) for k in ("title", "stage", "confidence")})
            state = item["ownership"]
            expected = (
                "owned"
                if owned
                else "contained"
                if contained
                else "pending"
                if candidates
                else "missing"
                if current
                else "unknown"
            )
            if state not in {expected, "missing", "unknown"} or (
                state in {"missing", "unknown"} and (owned or contained or candidates)
            ):
                raise ValueError
            state = (
                "direct"
                if state == "owned"
                else "unknown"
                if state == "missing" and not current
                else state
            )
            series = []
            for membership in rows(item["series"], 100):
                membership = mapping(membership)
                position = membership["position"]
                if position is not None and (
                    type(position) not in (int, float)
                    or not math.isfinite(position)
                    or not 0 < position < 100000
                ):
                    raise ValueError
                series.append(
                    {
                        "id": str(integer(membership["series_id"], 2**63 - 1)),
                        "name": text(membership["name"]),
                        "position": position,
                    }
                )
            kind = item["type"]
            if kind not in {"novel", "novella", "short_story", "anthology", "omnibus"}:
                raise ValueError
            works.append(
                {
                    "id": wid,
                    "title": text(item["title"]),
                    "kind": kind,
                    "authors": [text(a) for a in rows(item["authors"], 100)],
                    "series": series,
                    "state": state,
                    "current": current,
                    "copies": owned,
                    "contained_in": contained,
                    "candidates": candidates,
                }
            )
        if len(works) != min(limit, max(0, total - params["offset"])):
            raise ValueError
        return {
            "status": "ready",
            "source": "library_finish",
            "catalogue_version": version,
            "checked_at": checked,
            "coverage": coverage,
            "loading": loading,
            "snapshot": token,
            "page": page,
            "page_size": limit,
            "total": total,
            "works": works,
        }
    except KeyError, ValueError, TypeError, OverflowError:
        raise LibraryError("The library service returned an unsupported response.") from None


def browse(query):
    params, page = parameters(query)
    if not settings.LIBRARIUM_LIBRARY_URL:
        return {"status": "not_configured"}
    return {**project(fetch(params), params, page), "finish_origin": settings.LIBRARIUM_LIBRARY_URL}
