"""Saved Library Finish evidence for one pinned catalogue series or work; no library writer access.

Library Finish has no exact work lookup. A work is looked up by searching its pinned catalogue
title and keeping only rows whose work ID matches exactly; homonyms are never attached, and a
work absent from the bounded search is reported as no evidence, never as missing."""

import re
import time

from django.conf import settings

from librarium import catalogue
from librarium.library import WORK, LibraryCheckChanged, LibraryError, fetch, project
from librarium.validation import bounded_text

SERIES = re.compile(r"[1-9][0-9]{0,18}")
LIMIT = 200
MAX_REQUESTS = 3
BUDGET = 3
EVIDENCE = {"direct", "contained", "pending"}
INVALID = "Use one catalogue series with its catalogue version and fingerprint."
INVALID_WORK = "Use one catalogue work with its catalogue version and fingerprint."
LOOKUP = "title_candidates_verified_by_id"
SEARCH = 200
# The longest prefix of at most SEARCH characters that ends where a word ends.
PREFIX = re.compile(rf"(.{{1,{SEARCH}}})(?=\s|$)", re.DOTALL)
CHANGED = "The library check changed. Reload the library before continuing."
UNSUPPORTED = "The library service returned an unsupported response."
# Every page under one token must describe the same check as the first page.
CONSISTENT = ("catalogue_version", "checked_at", "coverage", "loading", "total")


def parameters(query):
    if set(query) != {"series", "version", "sha256"} or any(
        len(query.getlist(key)) != 1 for key in query
    ):
        raise LibraryError(INVALID, 400)
    raw, version, sha256 = query["series"], query["version"], query["sha256"]
    if (
        not SERIES.fullmatch(raw)
        or int(raw) > 2**63 - 1
        or not catalogue.valid_version(version)
        or not catalogue.DIGEST.fullmatch(sha256)
    ):
        raise LibraryError(INVALID, 400)
    return int(raw), version, sha256


def pinned(version: str, sha256: str, sql: str, key, missing: str):
    """Return one row from the pinned published catalogue; the database closes on return."""
    try:
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR, version, sha256, settings.LIBRARIUM_CATALOGUE_FIXTURE
        ) as (db, info):
            if info["fixture"]:
                raise LibraryError(
                    "Library evidence needs the published catalogue, not fixture data.", 409
                )
            row = db.execute(sql, (key,)).fetchone()
            if not row:
                raise LibraryError(missing, 404)
            row = tuple(row)
    except catalogue.CatalogueError as error:
        raise LibraryError(str(error), error.status) from None
    return row


def scan(filters: dict, version: str):
    """Read evidence pages under one token, restarting once if the saved check changes.

    ``filters`` is a fixed trusted selection (one series, or one title search), never user input.
    """
    deadline = time.monotonic() + BUDGET
    requests, restarted = 0, False
    while True:
        token, works, offset, seen, first = "", [], 0, set(), None
        try:
            while True:
                params = {
                    **filters,
                    "ownership": "all",
                    "sort": "title",
                    "limit": LIMIT,
                    "offset": offset,
                }
                if token:
                    params["snapshot"] = token
                requests += 1
                result = project(fetch(params, deadline), params, offset // LIMIT + 1)
                token = result["snapshot"]
                if first is None:
                    first = {key: result[key] for key in CONSISTENT}
                    if result["catalogue_version"] != version:
                        return result, [], False
                elif any(result[key] != first[key] for key in CONSISTENT):
                    raise LibraryError(UNSUPPORTED)
                for work in result["works"]:
                    if work["id"] in seen:
                        raise LibraryError(UNSUPPORTED)
                    seen.add(work["id"])
                works += result["works"]
                offset += LIMIT
                if offset >= result["total"]:
                    return result, works, False
                if requests >= MAX_REQUESTS:
                    return result, works, True
        except LibraryCheckChanged:
            if restarted or requests >= MAX_REQUESTS:
                raise LibraryCheckChanged(CHANGED) from None
            restarted = True


def report(result, works, truncated, version, keep):
    lf_version = result["catalogue_version"]
    status = (
        "loading"
        if lf_version is None
        else "version_mismatch"
        if lf_version != version
        else "ready"
    )
    return {
        "status": status,
        "source": "library_finish",
        "catalogue_version": lf_version,
        "checked_at": result["checked_at"],
        "coverage": result["coverage"],
        "loading": result["loading"],
        "snapshot": result["snapshot"],
        "truncated": truncated,
        "works": [work for work in works if work["state"] in EVIDENCE and keep(work)]
        if status == "ready"
        else [],
    }


def series(query):
    series_id, version, sha256 = parameters(query)
    if not settings.LIBRARIUM_LIBRARY_URL:
        return {"status": "not_configured"}
    pinned(
        version, sha256, "SELECT 1 FROM series WHERE id=?", series_id, "Catalogue series not found."
    )
    result, works, truncated = scan({"series": str(series_id)}, version)
    return {
        "series_id": str(series_id),
        **report(
            result,
            works,
            truncated,
            version,
            lambda work: any(s["id"] == str(series_id) for s in work["series"]),
        ),
    }


def search(title: str):
    """Return a bounded title search, or None when no usable one exists.

    Titles over SEARCH characters use their longest whole-word prefix within the limit.
    """
    title = title.strip()
    if len(title) > SEARCH:
        match = PREFIX.match(title)
        title = match.group(1).rstrip() if match else ""
    return title if title and bounded_text(title, SEARCH) else None


def work(query, work_id: str):
    """Evidence for one pinned catalogue work, suitable for GET /api/library/works/<work_id>."""
    if (
        set(query) != {"version", "sha256"}
        or any(len(query.getlist(key)) != 1 for key in query)
        or not isinstance(work_id, str)
        or not WORK.fullmatch(work_id)
        or not catalogue.valid_version(query["version"])
        or not catalogue.DIGEST.fullmatch(query["sha256"])
    ):
        raise LibraryError(INVALID_WORK, 400)
    version, sha256 = query["version"], query["sha256"]
    if not settings.LIBRARIUM_LIBRARY_URL:
        return {"status": "not_configured"}
    (title,) = pinned(
        version, sha256, "SELECT title FROM work WHERE id=?", work_id, "Catalogue work not found."
    )
    q = search(title) if isinstance(title, str) else None
    if q is None:
        return {"status": "unsupported", "work_id": work_id, "lookup": LOOKUP}
    result, works, truncated = scan({"q": q}, version)
    return {
        "work_id": work_id,
        "lookup": LOOKUP,
        **report(result, works, truncated, version, lambda work: work["id"] == work_id),
    }
