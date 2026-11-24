"""Durable source jobs and independently admitted candidates; no library writer."""

import contextlib
import hashlib
import http.client
import io
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from bl_catalog.resolve import titles as catalogue_titles
from django.conf import settings
from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from librarium import (
    artifacts,
    cover_admission,
    cover_candidates,
    cover_facts,
    cover_reviews,
    cover_source_image,
    direct_library,
)
from librarium import cover_source_rules as rules
from librarium.cover_source_fetch import SourceFailure
from librarium.cover_source_protocol import SOURCES, STATES, image_url
from librarium.cover_source_protocol import query as validate_query
from librarium.models import CoverSearch, PreparedCover

LOCK = cover_candidates.LOCK + 1
MAX_CANDIDATES = 24
ADMISSION_WORKERS = 3
# Shared across source pools: network reads and decoder children share this ceiling,
# and each freed slot goes to the source served least recently (see cover_admission).
_admission_slots = cover_admission.Slots(ADMISSION_WORKERS)
_perf = time.perf_counter
# The image record `_admit_task` is filling on this thread; `admit` adds its fetch and decode time.
_trace = threading.local()


def _ms(start):
    return max(0, int((_perf() - start) * 1000))


@contextlib.contextmanager
def _timed(field):
    record = getattr(_trace, "record", None)
    start = _perf()
    try:
        yield
    finally:
        if record is not None:
            record[field] += _ms(start)


def _image_record():
    """Bounded, private-data-free timing of one image's admission, in milliseconds.

    `attempts` counts image requests made for this candidate (its fallback URLs); redirect hops
    happen inside the isolated fetcher and are not visible to this process.
    """
    return {
        "slot_wait_ms": 0,
        "fetch_ms": 0,
        "process_ms": 0,
        "bytes": 0,
        "attempts": 0,
        "outcome": "failed",
    }


def available():
    return settings.LIBRARIUM_COVER_SOURCES_ENABLED


def require_enabled():
    if not available():
        raise cover_candidates.ChoiceError(
            "Web cover sources are not enabled. Stored choices remain available.",
            "sources_unavailable",
            503,
        )


def source_call(path, value, maximum):
    # Fixed internal authority; callers cannot select a service or upstream transport.
    seconds = 20 if path == "/image" else 95
    secret = settings.LIBRARIUM_COVER_SOURCES_SECRET
    if len(secret) < 32 or not secret.isascii():
        raise ValueError("Configure the protected cover-control secret.")
    c = http.client.HTTPConnection("cover-sources", 8124, timeout=seconds)
    deadline = time.monotonic() + seconds
    try:
        c.request(
            "POST",
            path,
            json.dumps(value).encode(),
            {"Content-Type": "application/json", "X-Cover-Control": secret},
        )
        r = c.getresponse()
        if r.status != 200:
            raise ValueError
        length = r.getheader("Content-Length", "")
        if not length.isdecimal() or not 0 < int(length) <= maximum:
            raise ValueError
        raw = bytearray()
        while len(raw) < int(length):
            if time.monotonic() >= deadline:
                raise TimeoutError
            if c.sock:
                c.sock.settimeout(max(0.1, deadline - time.monotonic()))
            chunk = r.read(min(65536, int(length) - len(raw)))
            if not chunk:
                raise ValueError
            raw.extend(chunk)
        return bytes(raw)
    finally:
        c.close()


def source_search(query, source, request_id, *, retry=False):
    if source in {"goodreads", "lexicanum_live"}:
        from librarium import cover_browser_sources

        return (
            cover_browser_sources.goodreads(query, retry=retry)
            if source == "goodreads"
            else cover_browser_sources.lexicanum(query)
        )
    return json.loads(
        source_call(
            "/search", {"query": query, "sources": [source], "request_id": request_id}, 128 * 1024
        )
    )


def source_image(url, source):
    if source in {"goodreads", "lexicanum_live"}:
        from librarium.cover_browser_sources import browser_call

        result = browser_call("/image", {"url": url}, cover_facts.MAX_BYTES)
        if not isinstance(result, bytes):
            raise SourceFailure(result["state"])
        return result
    return source_call("/image", {"url": url, "source": source}, cover_facts.MAX_BYTES)


def data(row):
    return {
        "id": str(row.pk),
        "entry_id": str(row.entry_id),
        "query": row.query,
        "state": row.state,
        "sources": [
            {
                "id": s,
                "name": SOURCES[s],
                # Development data once held a state older pickers cannot decode.
                "state": "empty" if row.statuses[s] == "unmatched" else row.statuses[s],
                **row.source_timings.get(s, {}),
            }
            for s in row.sources
        ],
        "candidate_count": len(row.candidates),
    }


def start(entry_id, value, key, actor):
    require_enabled()
    if type(value.get("refresh_browser", False)) is not bool or (
        value.get("refresh_browser") and value["sources"] != ["goodreads"]
    ):
        raise ValueError
    q = validate_query(value["query"])
    sources = value["sources"]
    image = value["image_url"]
    if type(image) is not str or len(image) > 4096:
        raise ValueError
    if image:
        if sources != []:
            raise ValueError("Pasted images require an empty sources list.")
        image_url(image, "paste")
        sources = ["paste"]
    elif (
        type(sources) is not list
        or not 1 <= len(sources) <= 7
        or any(type(s) is not str or s not in SOURCES or s == "paste" for s in sources)
        or len(set(sources)) != len(sources)
    ):
        raise ValueError
    if "lexicanum_live" in sources and "lexicanum" not in sources:
        sources = [*sources, "lexicanum"]
    sources = [s for s in SOURCES if s in sources]
    key = cover_reviews.request_uuid(key)
    params = {k: value[k] for k in ("revision", "inventory", "version", "sha256")}
    _, entry, binding, _, _ = cover_candidates.choices(entry_id, params)
    with transaction.atomic():
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK])
        old = CoverSearch.objects.filter(request_key=key).first()
        if old:
            if old.entry_id != entry_id or old.actor != actor or old.request != value:
                raise cover_candidates.ChoiceError("This request key was already used.")
            return old
        actor_rows = CoverSearch.objects.filter(actor=actor)
        if (
            actor_rows.filter(state__in=["queued", "running"]).count() >= 2
            or actor_rows.filter(created_at__gte=timezone.now() - timedelta(days=1)).count() >= 20
        ):
            raise cover_candidates.ChoiceError(
                "Search limit reached. Finish active searches or try again tomorrow.",
                "search_limit",
                429,
            )
        if CoverSearch.objects.filter(entry=entry, state__in=["queued", "running"]).exists():
            raise cover_candidates.ChoiceError(
                "Cancel the current search before starting another.", "search_active"
            )
        return CoverSearch.objects.create(
            request_key=key,
            entry=entry,
            actor=actor,
            request=value,
            binding=binding,
            query=q,
            sources=sources,
            image_url=image,
            statuses=dict.fromkeys(sources, "pending"),
        )


def cancel(search_id):
    with transaction.atomic():
        row = CoverSearch.objects.select_for_update().get(pk=search_id)
        if row.state in ("queued", "running"):
            row.state = "cancelled"
            row.lease_token = None
            row.lease_until = None
            row.statuses = {
                k: ("cancelled" if v in ("pending", "running") else v)
                for k, v in row.statuses.items()
            }
            row.save(update_fields=["state", "lease_token", "lease_until", "statuses"])
        return data(row)


def checked_url(url):
    if type(url) is not str or len(url) > 4096 or any(ord(c) <= 32 for c in url) or "\\" in url:
        raise ValueError
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username is not None
        or p.password is not None
        or p.port not in (None, 443)
        or p.fragment
    ):
        raise ValueError
    if (
        cover_candidates.known_placeholder(url)
        or p.path.rsplit("/", 1)[-1].casefold() == "book2.jpg"
    ):
        raise ValueError
    return url


def admit(item, row, source, deadline=None):
    if (
        type(item) is not dict
        or type(item.get("urls")) is not list
        or not 1 <= len(item["urls"]) <= 3
    ):
        raise ValueError
    name = item.get("src")
    if name != SOURCES[source]:
        raise ValueError
    for field in ("title", "author", "isbn"):
        if (item.get(field) is not None or field != "isbn") and (
            type(item.get(field, "")) is not str
            or len(item.get(field, "")) > (32 if field == "isbn" else 600)
        ):
            raise ValueError
    if type(item.get("by_isbn", False)) is not bool:
        raise ValueError
    for url in item["urls"]:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError
        try:
            url = image_url(checked_url(url), source)
            record = getattr(_trace, "record", None)
            if record is not None:
                record["attempts"] += 1
            with _timed("fetch_ms"):
                raw = source_image(url, source)
            if record is not None:
                record["bytes"] = len(raw)
            with _timed("process_ms"):
                prepared = cover_source_image.prepare(raw)
                output = prepared["data"]
                facts = cover_facts.inspect_cover(output)
                if (
                    facts["status"] != "known"
                    or facts["blank"]
                    or facts["placeholder"]
                    or (facts["width"], facts["height"]) != (prepared["width"], prepared["height"])
                ):
                    raise ValueError
                original_sha = hashlib.sha256(raw).hexdigest()
                sha = hashlib.sha256(output).hexdigest()
                artifacts.ingest_web(io.BytesIO(output), sha, expected_size=len(output))
            mismatch = rules.kind_mismatch(row.entry.title, item.get("title"))
            c = {
                "id": str(uuid.uuid5(row.pk, sha + url)),
                "policy": cover_candidates.POLICY,
                "work_id": "web",
                "sha256": sha,
                "original_sha256": original_sha,
                "original_size": len(raw),
                "size": len(output),
                "label": "Web",
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "width": facts["width"],
                "height": facts["height"],
                "media_type": "image/jpeg",
                "method": "web_original",
                "pipeline": "metadata-stripped-jpeg-v1",
                "source": url,
                "source_name": name,
                "reach_method": "server_browser"
                if source in {"goodreads", "lexicanum_live"}
                else "archive"
                if source == "lexicanum"
                else "image_url"
                if source == "paste"
                else "server_api",
                "source_url": url,
                "selectable": not mismatch,
                "meets_width_floor": facts["width"] >= 1000,
                "reason": mismatch
                or "Chosen from a web search; confirm the book and edition visually.",
                "by_isbn": item.get("by_isbn", False),
                "isbn": item.get("isbn"),
                "_fp": prepared["fingerprint"],
                "search_id": str(row.pk),
                "query": row.query,
            }
            return c
        except ValueError, OSError, artifacts.ArtifactError:
            continue
    return None


def candidate_key(candidate):
    for field in ("sha256", "original_sha256"):
        value = candidate.get(field)
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            return ("hash", value)
    url = candidate.get("source_url") or candidate.get("source")
    try:
        p = urlsplit(checked_url(url))
        return ("url", p._replace(netloc=p.hostname.lower(), path=p.path or "/").geturl())
    except ValueError, TypeError:
        return ("id", candidate["id"])


APPLE_RENDITION = re.compile(r"/\d{2,5}x\d{2,5}bb\.(jpg|png|webp)$")


def _apple_artwork(candidate):
    """(artwork path key, rendition segment) of an Apple image URL, else (None, None).

    The key is host, path without its size-and-format segment, and query; the segment is
    that `/<w>x<h>bb.<ext>` tail."""
    try:
        p = urlsplit(checked_url(candidate.get("source_url") or candidate.get("source")))
    except ValueError, TypeError:
        return None, None
    host = p.hostname.lower()
    if host != "mzstatic.com" and not host.endswith(".mzstatic.com"):
        return None, None
    found = APPLE_RENDITION.search(p.path)
    if found is None:
        return None, None
    return ("apple_artwork", host, p.path[: found.start()], p.query), found.group(0)


def choose_images(records, saved, saved_url, limit):
    """One choice per image from every record at once, so the result never depends on order.

    `records` are {"item", "url", "rank"} (higher rank is newer). Same canonical bytes (or, for
    a legacy record without a digest, the same normalised URL) are one image. The images on
    one Apple artwork path merge into a single choice only when each lives entirely on that
    path and no two different byte groups have the same size AND the same format (that pair
    means the artwork was replaced, not that this is another rendition; the same size in two
    formats, such as jpg and webp, is one artwork in two encodings and does merge). Nothing
    else merges and nothing chains. A choice is shown by the saved record when it is a member, else its newest member;
    the saved record is always present, and the cap evicts other choices, never it.
    """
    members = [dict(r) for r in records]
    if saved is not None and not any(r["item"]["id"] == saved["id"] for r in members):
        members.append({"item": saved, "url": saved_url, "rank": float("-inf")})
    by_bytes: dict[Any, list[dict[str, Any]]] = {}
    for r in members:
        r["path"], r["segment"] = _apple_artwork(r["item"])
        by_bytes.setdefault(candidate_key(r["item"]), []).append(r)
    groups = list(by_bytes.values())
    on_path: dict[Any, list[int]] = {}
    for index, group in enumerate(groups):
        for path in {r["path"] for r in group if r["path"] is not None}:
            on_path.setdefault(path, []).append(index)
    owner = list(range(len(groups)))  # a merged group's choice is its first group's
    for path, indexes in on_path.items():
        segments = [{r["segment"] for r in groups[i]} for i in indexes]
        alone = all({r["path"] for r in groups[i]} == {path} for i in indexes)
        distinct = sum(len(s) for s in segments) == len(set().union(*segments))
        if len(indexes) > 1 and alone and distinct:
            for i in indexes:
                owner[i] = indexes[0]
    choices_by_owner: dict[int, list[dict[str, Any]]] = {}
    for index, group in enumerate(groups):
        choices_by_owner.setdefault(owner[index], []).extend(group)
    choices = list(choices_by_owner.values())

    def newest(choice):
        return max(r["rank"] for r in choice)

    def shown(choice):
        exact = [r for r in choice if saved is not None and r["item"]["id"] == saved["id"]]
        return exact[0] if exact else max(choice, key=lambda r: r["rank"])

    choices.sort(key=lambda c: (-newest(c), shown(c)["item"]["id"]))
    if len(choices) > limit:
        home = next(
            (
                c
                for c in choices
                if saved is not None and any(r["item"]["id"] == saved["id"] for r in c)
            ),
            None,
        )
        others = [c for c in choices if c is not home]
        keep = others[: limit - (home is not None)]
        choices = [c for c in choices if c is home or any(c is k for k in keep)]
    return [{**shown(c)["item"], "url": shown(c)["url"]} for c in choices]


def candidates(entry, binding, selected=None):
    """Recent web choices for this book, one per image (see `choose_images`)."""
    saved = (
        selected.candidate
        if selected
        and selected.binding == binding
        and selected.candidate.get("method") == "web_original"
        else None
    )
    records: list[dict[str, Any]] = []
    rows = CoverSearch.objects.filter(entry=entry).order_by("-created_at", "-id")[:4]
    for row in rows:
        if row.binding != binding:
            continue
        for item in row.candidates:
            records.append(
                {
                    "item": item,
                    "url": f"/api/cover-reviews/{entry.pk}/images/{row.pk}/{item['id']}",
                    "rank": -len(records),
                }
            )
    saved_url = (
        f"/api/cover-reviews/{entry.pk}/images/{saved['search_id']}/{saved['id']}" if saved else ""
    )
    out = choose_images(records, saved, saved_url, MAX_CANDIDATES)
    out.sort(key=lambda c: c.get("match") or 0, reverse=True)
    return out


def verify_candidate(c):
    try:
        raw = artifacts.read("web", c["sha256"], c["size"])
    except artifacts.ArtifactError:
        raise cover_candidates.ChoiceError(
            "This image is unavailable. Refresh the choices or search again.",
            "image_unavailable",
            503,
        ) from None
    facts = cover_facts.inspect_cover(raw)
    if (
        facts["status"] != "known"
        or facts["sha256"] != c["sha256"]
        or (facts["width"], facts["height"]) != (c["width"], c["height"])
        or facts["blank"]
        or facts["placeholder"]
    ):
        raise cover_candidates.ChoiceError("The selected image could not be verified.")
    if rules.kind_mismatch(c.get("target_title"), c["title"]):
        raise cover_candidates.ChoiceError("A single book and an omnibus cannot share this choice.")
    return raw


def verify_for_selection(candidate, entry_id, binding):
    row = CoverSearch.objects.filter(
        pk=candidate["search_id"], entry_id=entry_id, binding=binding
    ).first()
    expected = {k: v for k, v in candidate.items() if k != "url"}
    if row is None or expected not in row.candidates:
        raise cover_candidates.ChoiceError(
            "This search expired. Search again before selecting a cover.", "search_expired"
        )
    return verify_candidate(candidate)


_last_retention = 0.0


def retain():
    """Expire seven-day search evidence; append-only choices and their bytes survive."""
    from django.db import connection

    cutoff = timezone.now() - timedelta(days=7)
    with transaction.atomic():
        # Selection takes this same lock before recording PreparedCover.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [cover_candidates.LOCK])
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK])
        saved = list(PreparedCover.objects.values_list("candidate", flat=True))
        saved_ids = {c["id"] for c in saved}
        rows = (
            CoverSearch.objects.select_for_update()
            .filter(created_at__lt=cutoff)
            .exclude(state__in=["queued", "running"])
        )
        removed = 0
        for row in rows.iterator():
            keep = [c for c in row.candidates if c["id"] in saved_ids]
            if keep:
                if keep != row.candidates:
                    row.candidates = keep
                    row.save(update_fields=["candidates"])
            else:
                row.delete()
                removed += 1
                if removed == 64:
                    break
        live = {c["sha256"] for c in saved}
        for items in CoverSearch.objects.values_list("candidates", flat=True).iterator():
            live.update(c["sha256"] for c in items)
        artifacts.expire_web(live, cutoff.timestamp())


def tick():
    if not available():
        return False
    global _last_retention
    if time.monotonic() - _last_retention > 300:
        retain()
        _last_retention = time.monotonic()
    now = timezone.now()
    with transaction.atomic():
        row = (
            CoverSearch.objects.select_for_update(skip_locked=True)
            .filter(Q(state="queued") | Q(state="running", lease_until__lt=now))
            .order_by("created_at")
            .first()
        )
        if row is None:
            return False
        if row.attempts >= 20:
            row.state = "failed"
            row.statuses = {
                k: ("failed" if v in ("pending", "running") else v) for k, v in row.statuses.items()
            }
            row.save()
            return True
        sources = [s for s in row.sources if row.statuses[s] in ("pending", "running")]
        if not sources:
            return False
        row.state = "running"
        row.lease_token = uuid.uuid4()
        row.lease_until = now + timedelta(seconds=300)
        row.attempts += 1
        row.statuses = {**row.statuses, **dict.fromkeys(sources, "running")}
        row.source_timings = {
            **row.source_timings,
            **{
                source: {"started_at": now.isoformat(), "finished_at": None, "duration_ms": None}
                for source in sources
            },
        }
        row.save()
        token = row.lease_token
    # Load the FK before starting threads; each thread owns its database connection.
    _ = row.entry
    timings: dict[str, dict[str, Any]] = {source: {} for source in sources}
    known = _Known(row)
    if len(sources) == 1:
        source = sources[0]
        state, admitted = _run_source(row, token, source, timings[source], known)
        _checkpoint(row, token, source, state, admitted, timings[source])
    else:
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            futures = {
                executor.submit(_source_task, row, token, source, timings[source], known): source
                for source in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    state, admitted = future.result()
                except ValueError, TypeError, KeyError, OSError:
                    state, admitted = "failed", []
                _checkpoint(row, token, source, state, admitted, timings[source])
    return True


def _source_task(row, token, source, timing=None, known=None):
    try:
        return _run_source(row, token, source, timing, known)
    finally:
        connections.close_all()


def _admit_task(item, row, token, source, deadline, record=None):
    record = _image_record() if record is None else record
    key = (row.pk, source)
    acquired = False
    waited = _perf()
    try:
        acquired = _admission_slots.acquire(key, max(0, deadline - time.monotonic()))
        record["slot_wait_ms"] = _ms(waited)
        if not acquired or time.monotonic() >= deadline:
            record["outcome"] = "timed_out"
            return "timed_out", None
        if not CoverSearch.objects.filter(pk=row.pk, lease_token=token, state="running").exists():
            record["outcome"] = "cancelled"
            return "cancelled", None
        _trace.record = record
        admitted = admit(item, row, source, deadline)
        record["outcome"] = "admitted" if admitted else "rejected"
        return None, admitted
    except SourceFailure as error:
        record["outcome"] = error.state
        return error.state, None
    except TimeoutError:
        record["outcome"] = "timed_out"
        return "timed_out", None
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        http.client.HTTPException,
        artifacts.ArtifactError,
    ):
        return "failed", None
    finally:
        _trace.record = None
        if acquired:
            _admission_slots.release(key)
        connections.close_all()


class _Known:
    """The catalogue titles for one search: resolved at most once, and only if a source needs
    them, so every source shares one lookup."""

    def __init__(self, row):
        self._row = row
        self._lock = threading.Lock()
        self._titles: list[str] | None = None

    def __call__(self):
        with self._lock:
            if self._titles is None:
                self._titles = cover_candidates.matched_work_titles(
                    self._row.entry, self._row.request
                )
            return self._titles


def _plausible(item, row, source, known):
    """False for a provider hit whose title names a clearly different work.

    The edition-key matcher is a spelling heuristic, not a translator, so a zero gets one more
    chance: the hit is kept when its whole normalised title equals the canonical title or a
    recorded alias of the catalogue work this book exactly matches. Equality only; with no exact
    match there is no evidence. One ISBN lookup or pasted image already identifies its book, and
    an unreadable item fails in admission.
    """
    if source == "paste" or type(item) is not dict or item.get("by_isbn") is True:
        return True
    title = item.get("title")
    if type(title) is not str:
        return True
    if rules.title_fit(row.query["title"], row.query["author"], title) > 0:
        return True
    key = catalogue_titles.title_key(title)
    return bool(key) and any(key == catalogue_titles.title_key(t) for t in known())


def _run_source(row, token, source, timing=None, known=None):
    """Search one source and admit its images; fills `timing` with where the time went."""
    timing = {} if timing is None else timing
    known = known or list
    result: dict[str, Any]
    slice_deadline = time.monotonic() + 240
    state = "failed"
    admitted: list[dict[str, Any]] = []
    try:
        if source == "paste":
            result = {
                "state": "results",
                "candidates": [
                    {
                        "src": "Image URL",
                        "title": row.entry.title or "",
                        "author": "",
                        "urls": [row.image_url],
                        "by_isbn": False,
                    }
                ],
            }
        else:
            began = _perf()
            try:
                result = (
                    source_search(row.query, source, str(row.pk), retry=True)
                    if row.request.get("refresh_browser")
                    else source_search(row.query, source, str(row.pk))
                )
            finally:
                timing["metadata_ms"] = _ms(began)
        if (
            type(result) is not dict
            or set(result) != {"state", "candidates"}
            or result["state"] not in STATES
            or type(result["candidates"]) is not list
            or len(result["candidates"]) > 6
        ):
            raise ValueError
        state = result["state"]
        if state not in {"results", "partial"} and result["candidates"]:
            raise ValueError
        if state in {"results", "partial"}:
            items = [item for item in result["candidates"] if _plausible(item, row, source, known)]
            timing["title_results"] = len(result["candidates"])
            timing["title_mismatch"] = len(result["candidates"]) - len(items)
            records = [_image_record() for _ in items]
            began = _perf()
            with ThreadPoolExecutor(max_workers=ADMISSION_WORKERS) as executor:
                futures = [
                    executor.submit(_admit_task, item, row, token, source, slice_deadline, record)
                    for item, record in zip(items, records, strict=True)
                ]
                outcomes = [future.result() for future in futures]
            timing["admission_ms"] = _ms(began)
            timing["images"] = records
            failures = [error for error, _ in outcomes if error]
            if "cancelled" in failures:
                return "cancelled", []
            for _, c in outcomes:
                if c and not any(x["sha256"] == c["sha256"] for x in row.candidates + admitted):
                    admitted.append(c)
            if failures:
                state = "partial" if admitted or state == "partial" else failures[0]
            rules.score(admitted, row.query["title"], row.query["author"])
            current_fp = None
            if row.entry.facts.get("sha256") and not row.entry.facts.get("placeholder"):
                try:
                    with cover_reviews.current_entry(row.entry) as (root, book):
                        current_raw, _ = direct_library.read_cover(
                            root, book["path"], limit=cover_facts.MAX_BYTES
                        )
                    if (
                        hashlib.sha256(current_raw).hexdigest()
                        == row.binding["current_cover_sha256"]
                    ):
                        current_fp = cover_source_image.prepare(current_raw)["fingerprint"]
                except (
                    ValueError,
                    OSError,
                    cover_reviews.ReviewError,
                    direct_library.DirectLibraryError,
                ):
                    pass
            for c in admitted:
                # Weak titles stay as choices but are never eligible to be the recommended pick.
                c["_weak"] = (
                    source != "paste"
                    and not c["by_isbn"]
                    and rules.title_fit(row.query["title"], row.query["author"], c["title"])
                    < catalogue_titles.MATCH
                )
            rules.rank(admitted, current_fp, row.entry.title)
            for c in admitted:
                weak = c.pop("_weak")
                if weak:
                    c["why"] = "Weak title match"
                c["confidence"] = (
                    "possible" if weak or c.get("match") is None or c["match"] < 0.75 else "strong"
                )
                c["reason"] = (
                    c["reason"]
                    if not c["selectable"]
                    else c["why"] + "; confirm the edition visually."
                )
                c["target_title"] = row.entry.title
            if not admitted and state == "results":
                # Still "empty" on the wire; `title_results` and `title_mismatch` let the picker say why.
                state = "empty"
    except SourceFailure as error:
        state = error.state
    except TimeoutError:
        state = "timed_out"
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        http.client.HTTPException,
        artifacts.ArtifactError,
    ):
        state = "failed"
    return state, admitted


def _checkpoint(row, token, source, state, admitted, measured=None):
    # Only these keys, and at most one record per candidate, are kept from a run's measurements.
    measured = {
        **{
            k: measured[k]
            for k in ("metadata_ms", "admission_ms", "title_results", "title_mismatch")
            if k in (measured or {})
        },
        **({"images": measured["images"][:6]} if measured and "images" in measured else {}),
    }
    with transaction.atomic():
        current = CoverSearch.objects.select_for_update().get(pk=row.pk)
        if (
            current.state != "running"
            or current.lease_token != token
            or current.lease_until is None
            or current.lease_until <= timezone.now()
        ):
            return True
        known = {c["sha256"] for c in current.candidates}
        current.candidates = (
            current.candidates + [c for c in admitted if c["sha256"] not in known]
        )[:MAX_CANDIDATES]
        timing = current.source_timings[source]
        finished = timezone.now()
        current.source_timings = {
            **current.source_timings,
            source: {
                **timing,
                **measured,
                "finished_at": finished.isoformat(),
                "duration_ms": max(
                    0,
                    int(
                        (finished - datetime.fromisoformat(timing["started_at"])).total_seconds()
                        * 1000
                    ),
                ),
            },
        }
        current.statuses = {**current.statuses, source: state}
        if not any(s in {"pending", "running"} for s in current.statuses.values()):
            current.state = "complete"
            current.lease_token = None
            current.lease_until = None
        current.save()
    return True
