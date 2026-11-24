"""Worker-owned, bounded read-only BLC telemetry; request handlers read Postgres only."""

import hashlib
import json
import math
import re
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from librarium.models import CatalogueStatus

MAX_BYTES = 1024 * 1024
POLL_SECONDS = 60
STALE_SECONDS = 300
TOTAL_SECONDS = 5
TOKEN = re.compile(r"[A-Za-z0-9_. -]{1,100}\Z")
_next_check = 0.0
_check_url = ""


class ResponseTooLarge(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Operator-selected origins only, with neither ambient proxy settings nor redirects.
open_url = build_opener(ProxyHandler({}), NoRedirect()).open


def base_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        raise ValueError("Invalid status URL")
    _ = url.port
    return value.rstrip("/")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Non-finite JSON value")


def fetch_json(url: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with open_url(request, timeout=remaining) as reply:
        if reply.status != 200:
            raise ValueError("Unexpected status")
        if int(reply.headers.get("Content-Length", "0")) > MAX_BYTES:
            raise ResponseTooLarge
        parts, size = [], 0
        while chunk := reply.read1(min(65536, MAX_BYTES + 1 - size)):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ResponseTooLarge
            if time.monotonic() >= deadline:
                raise TimeoutError
            parts.append(chunk)
        data = json.loads(
            b"".join(parts), object_pairs_hook=unique_object, parse_constant=invalid_constant
        )
    if not isinstance(data, dict):
        raise TypeError("Expected object")
    return data


def reason(value) -> str:
    """Retain only an HTTP code, never request paths or response bodies."""
    if not isinstance(value, str):
        return "Source unavailable"
    match = re.search(r"\b([45]\d\d)\b", value)
    if not match:
        return "Source unavailable"
    code = int(match[1])
    kind = {
        401: "API key rejected",
        403: "Access refused",
        404: "Record unavailable",
        429: "Rate limit reached",
    }.get(code, "Source request failed")
    return f"{kind} ({code})"


def text(value):
    if not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 for c in value):
        raise ValueError
    return value


def token(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value) or "query" in value.lower():
        raise ValueError
    return value


def stamp(value):
    value = text(value)
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError
    return value


def number(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 10**15:
        raise ValueError
    return value


def flag(value):
    if type(value) is not bool:
        raise ValueError
    return value


def nullable(rule):
    return lambda value: None if value is None else rule(value)


def fields(schema):
    def validate(value):
        if not isinstance(value, dict) or len(value) > 128:
            raise ValueError
        return {key: rule(value[key]) for key, rule in schema.items() if key in value}

    return validate


def entries(rule, limit=64):
    def validate(value):
        if not isinstance(value, dict) or len(value) > limit:
            raise ValueError
        return {
            token(key): rule(item)
            for key, item in value.items()
            if "query" not in key.lower() and "error_sample" not in key.lower()
        }

    return validate


def items(rule, limit=300):
    def validate(value):
        if not isinstance(value, list) or len(value) > limit:
            raise ValueError
        return [rule(item) for item in value]

    return validate


COUNTS = fields({"asked": number, "new": number, "new_records": number, "errors": number})
WORK = fields(
    {
        "id": token,
        "title": text,
        "type": nullable(token),
        "authors": items(text, 64),
        "flags": items(token, 64),
    }
)
CATALOGUE = fields(
    {
        **dict.fromkeys(
            ("works", "editions", "authors", "series", "with_isbn", "with_synopsis"), number
        ),
        "by_type": entries(number),
        "by_format": entries(number),
    }
)
CHANGES = fields(
    {
        **dict.fromkeys(("added_count", "removed_count", "merged_count", "retitled_count"), number),
        "from_version": nullable(token),
        "to_version": token,
        "first": flag,
        "added": items(WORK),
        "removed": items(WORK),
        "retitled": items(fields({"id": token, "from": text, "to": text})),
    }
)
LIVE = fields(
    {
        "state": token,
        "paused": flag,
        "stalled": flag,
        "age_s": nullable(number),
        **dict.fromkeys(
            ("updated_at", "cycle_started_at", "next_cycle_at", "phase_started_at"), nullable(stamp)
        ),
        "phase": nullable(token),
        "phase_source": nullable(token),
        "phase_done": number,
        "phase_total": nullable(number),
        "sources": entries(COUNTS),
        "recent": items(fields({"source": token, "title": text, "at": stamp}), 30),
    }
)
CYCLE = fields(
    {
        "started_at": stamp,
        "duration_s": number,
        "stages": entries(fields({"status": token})),
        "tripped": items(token, 64),
        "tripped_reasons": entries(reason),
        "per_source": entries(
            lambda value: COUNTS(value) if isinstance(value, dict) else number(value)
        ),
        "budget_spent": items(token, 64),
        "budget_deferred": entries(number),
        "changed": nullable(flag),
        "version": nullable(token),
        **dict.fromkeys(
            (
                "inbox_new_records",
                "harvest_new_records",
                "harvest_errors",
                "works",
                "editions",
                "disputed",
                "pruned",
            ),
            number,
        ),
    }
)
STATUS = fields(
    {
        "now": stamp,
        "published_version": nullable(token),
        "live": LIVE,
        "snapshot": nullable(
            fields({"version": token, "catalogue": CATALOGUE, "changes": CHANGES})
        ),
        "cycles": items(CYCLE, 30),
        "control": fields({"enabled": flag}),
    }
)
COVERS = fields(
    {
        "catalog_version": nullable(token),
        "checked_at": stamp,
        "last_download_at": nullable(stamp),
        "scan_state": token,
        **dict.fromkeys(
            (
                "downloaded_images",
                "downloaded_bytes",
                "queued_images",
                "failed_uploads",
                "published_books",
            ),
            number,
        ),
        "upscale": fields(
            {
                "enabled": flag,
                "paused": flag,
                "state": token,
                "stage": nullable(token),
                "updated_at": nullable(stamp),
                "progress": nullable(fields({"done": number, "total": number})),
                "control_enabled": flag,
                **dict.fromkeys(("queued", "completed", "failed"), number),
            }
        ),
    }
)


def validate(status, covers) -> dict:
    clean, art = STATUS(status), COVERS(covers)
    if not {"live", "cycles", "snapshot"} <= clean.keys() or "state" not in clean["live"]:
        raise ValueError
    if "upscale" not in art or not {"state", "paused"} <= art["upscale"].keys():
        raise ValueError
    if any("started_at" not in cycle for cycle in clean["cycles"]):
        raise ValueError
    return {"status": clean, "covers": art}


def source_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def tick(now: datetime | None = None) -> bool:
    global _next_check, _check_url
    url = settings.LIBRARIUM_CATALOGUE_STATUS_URL
    if not url:
        return False
    monotonic = time.monotonic()
    if _check_url == url and monotonic < _next_check:
        return False
    _check_url, _next_check = url, monotonic + POLL_SECONDS
    now = now or timezone.now()
    key = source_key(url)
    previous = CatalogueStatus.objects.filter(pk=1).first()
    expected = (previous.source_key, previous.attempted_at) if previous else ("", None)
    if (
        previous
        and previous.source_key == key
        and previous.attempted_at
        and (now - previous.attempted_at).total_seconds() < POLL_SECONDS
    ):
        _next_check = monotonic + max(
            0.5, POLL_SECONDS - (now - previous.attempted_at).total_seconds()
        )
        return False
    payload, failure = None, ""
    try:
        base = base_url(url)
        deadline = time.monotonic() + TOTAL_SECONDS
        payload = validate(
            fetch_json(base + "/v1/status", deadline),
            fetch_json(base + "/v1/covers/status", deadline),
        )
    except ResponseTooLarge:
        failure = "Status response too large"
    except TimeoutError:
        failure = "Status request timed out"
    except HTTPError as error:
        failure = f"Status service returned HTTP {error.code}"
        error.close()
    except URLError as error:
        failure = (
            "Status request timed out"
            if isinstance(error.reason, TimeoutError)
            else "Status service unreachable"
        )
    except OSError:
        failure = "Status service unreachable"
    except ValueError, TypeError, KeyError, RecursionError:
        failure = "Invalid status response"
    # Fetch without a transaction; a concurrent worker's newer copy wins at publication.
    with transaction.atomic():
        CatalogueStatus.objects.get_or_create(pk=1)
        row = CatalogueStatus.objects.select_for_update(skip_locked=True).filter(pk=1).first()
        if (
            row is None
            or (row.source_key, row.attempted_at) != expected
            or settings.LIBRARIUM_CATALOGUE_STATUS_URL != url
        ):
            return False
        if row.source_key != key:
            row.payload, row.fetched_at = {}, None
        row.source_key, row.attempted_at, row.failure = key, now, failure
        if payload is not None:
            row.payload, row.fetched_at, row.failure = payload, now, ""
        row.save()
    return True


def saved(now: datetime | None = None) -> dict:
    url = settings.LIBRARIUM_CATALOGUE_STATUS_URL
    missing = {"state": "unavailable", "reason": "BL Catalog status is not configured."}
    if not url:
        return missing
    row = CatalogueStatus.objects.filter(pk=1, source_key=source_key(url)).first()
    if row is None or row.fetched_at is None:
        return {
            "state": "unavailable",
            "reason": row.failure
            if row and row.failure
            else "Waiting for the first BL Catalog status poll.",
        }
    age = max(0, int(((now or timezone.now()) - row.fetched_at).total_seconds()))
    return {
        "state": "stale" if age > STALE_SECONDS else "observed",
        "fetched_at": row.fetched_at.isoformat(),
        "age_seconds": age,
        "failure": row.failure,
        **row.payload,
    }
