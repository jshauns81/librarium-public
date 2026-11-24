"""Bounded library shelves joined to a pinned catalogue.

Small results group within the request deadline. Large results build one complete
match index in a bounded background reader; requests never wait for that build.
The pinned local catalogue owns membership, positions, totals and preview leads.
"""

import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from django.conf import settings

from librarium import catalogue, library
from librarium.library_evidence import CONSISTENT

LIMIT = 200
MAX_PAGES = 3
CONCURRENCY = 3
BUDGET = 3
PAGE_SIZE = 4
PREVIEW_SIZE = 5
MAX_CATALOGUE_WORKS = 50000
MAX_MEMBERSHIPS = 100000
MAX_AUTHOR_CREDITS = 100000
INDEX_BUDGET = 30
MAX_INDEX_WORKS = 50000
MAX_INDEXES = 4
UNSUPPORTED = "The library service returned an unsupported response."


def parameters(query):
    if (
        not {"version", "sha256"} <= set(query)
        or set(query) - {"version", "sha256", "q", "page", "ownership", "snapshot", "group"}
        or query.get("group", "standalone") != "standalone"
        or any(len(query.getlist(k)) != 1 for k in query)
        or not catalogue.valid_version(query["version"])
        or not catalogue.DIGEST.fullmatch(query["sha256"])
    ):
        raise library.LibraryError("Use valid library filters and a pinned catalogue.", 400)
    filters = query.copy()
    del filters["version"], filters["sha256"]
    filters.pop("group", None)
    params, page = library.parameters(filters)
    params.update(limit=LIMIT, offset=0)
    return params, page


def catalogue_context(version, sha256):
    """Close SQLite before network reads; bounded snapshot admission/SQL still apply."""
    try:
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            version,
            sha256,
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
        ) as (db, info):
            if info["fixture"]:
                raise library.LibraryError("Library shelves need the published catalogue.", 409)
            works = {
                row["id"]: {**dict(row), "series": [], "authors": []}
                for row in db.execute(
                    "SELECT id,title,sort_title,type,first_published,setting FROM work LIMIT ?",
                    (MAX_CATALOGUE_WORKS + 1,),
                )
            }
            if len(works) > MAX_CATALOGUE_WORKS:
                raise library.LibraryError("The catalogue exceeds the bounded shelves read.")
            credits = db.execute(
                "SELECT wa.work_id,a.name FROM work_author wa JOIN author a ON a.id=wa.author_id "
                "WHERE wa.role='author' ORDER BY wa.work_id,wa.author_id LIMIT ?",
                (MAX_AUTHOR_CREDITS + 1,),
            ).fetchall()
            if len(credits) > MAX_AUTHOR_CREDITS:
                raise library.LibraryError("The catalogue exceeds the bounded shelves read.")
            for credit in credits:
                if credit["work_id"] not in works:
                    continue
                names = works[credit["work_id"]]["authors"]
                if credit["name"] not in names:
                    names.append(credit["name"])
            totals: dict[str | None, int] = {}
            memberships = db.execute(
                "SELECT ws.work_id,s.id,s.name,ws.position FROM work_series ws "
                "JOIN series s ON s.id=ws.series_id ORDER BY s.name,s.id LIMIT ?",
                (MAX_MEMBERSHIPS + 1,),
            ).fetchall()
            if len(memberships) > MAX_MEMBERSHIPS:
                raise library.LibraryError("The catalogue exceeds the bounded shelves read.")
            shelved_ids = catalogue.shelving_series(db)
            leads = catalogue.position_leads(db)
            for row in memberships:
                if row["work_id"] not in works:
                    continue
                position = row["position"]
                if position is not None and (
                    type(position) not in (int, float) or not math.isfinite(position)
                ):
                    raise library.LibraryError(
                        "The catalogue has an unsupported recorded position."
                    )
                if str(row["id"]) not in shelved_ids:
                    continue
                sid = str(row["id"])
                works[row["work_id"]]["series"].append(
                    {
                        "id": sid,
                        "name": row["name"],
                        "position": position,
                        "shelf_eligible": True,
                        **leads.get((sid, position), {}),
                    }
                )
                totals[sid] = totals.get(sid, 0) + 1
            totals[None] = sum(not work["series"] for work in works.values())
            for work in works.values():
                for membership in work["series"]:
                    membership["work_count"] = totals[membership["id"]]
            return works, totals, info
    except catalogue.CatalogueError as error:
        raise library.LibraryError(str(error), error.status) from None


def read_index(params, first=None, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + BUDGET

    def read(offset, token):
        selection = {**params, "offset": offset, "snapshot": token}
        return library.project(library.fetch(selection, deadline), selection, offset // LIMIT + 1)

    first = first if first is not None else read(0, params["snapshot"])
    total = first["total"]
    if total > MAX_PAGES * LIMIT:
        return first, [], True
    values = list(first["works"])
    # Transport interrupts sockets at the shared deadline. At most three fixed GETs
    # run together; no caller-supplied URL, credentials or executor survives return.
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        for result in executor.map(
            lambda offset: read(offset, first["snapshot"]), range(LIMIT, total, LIMIT)
        ):
            if any(result[k] != first[k] for k in CONSISTENT):
                raise library.LibraryError(UNSUPPORTED)
            values.extend(result["works"])
    if len({work["id"] for work in values}) != len(values):
        raise library.LibraryError(UNSUPPORTED)
    return first, values, False


def normalised_name(name):
    name = re.sub(r"^[\W_]+", "", name.casefold())
    return re.sub(r"^(the|an|a)\s+", "", name)


def group(works, metadata, totals, query=""):
    groups: dict[str | None, dict] = {}
    unlinked = 0
    for raw in works:
        context = metadata.get(raw["id"])
        if context is None:
            unlinked += 1
            continue
        work = {
            **raw,
            "series": [dict(s) for s in context["series"]],
            "kind": context.get("type") or raw["kind"],
            "first_published": context["first_published"],
            "authors": context.get("authors", []),
        }
        for membership in work["series"] or [
            {"id": None, "name": "Standalone and collected", "position": None}
        ]:
            sid = membership["id"]
            shelf = groups.setdefault(
                sid,
                {
                    "id": sid,
                    "name": membership["name"],
                    "works": [],
                    "catalogue_total": totals.get(sid),
                },
            )
            shelf["works"].append(
                (work, membership["position"], context["sort_title"] or context["title"])
            )

    def shelf_order(shelf):
        return (
            shelf["id"] is None,
            bool(query) and query.casefold() not in shelf["name"].casefold(),
            -sum(w["state"] in {"direct", "contained"} for w, _, _ in shelf["works"]),
            normalised_name(shelf["name"]),
            shelf["id"] or "",
        )

    result = []
    for shelf in sorted(groups.values(), key=shelf_order):
        entries = sorted(
            shelf["works"],
            key=lambda entry: (
                2 if entry[1] is None else 1 if entry[1] == 0 else 0,
                entry[1] or 0,
                entry[2].casefold(),
                entry[0]["id"],
            ),
        )
        counts = dict.fromkeys(("saved", "direct", "contained", "pending", "missing", "unknown"), 0)
        positions = dict.fromkeys(("numbered", "zero", "unpositioned"), 0)
        kinds: dict[str, int] = {}
        author_works: dict[str, set[str]] = {}
        by_position: dict[float, list[dict]] = {}
        for work, position, _title in entries:
            state = (
                "saved"
                if not work["current"] and work["state"] in {"direct", "contained"}
                else work["state"]
            )
            counts[state] += 1
            positions[
                "unpositioned" if position is None else "zero" if position == 0 else "numbered"
            ] += 1
            kinds[work["kind"]] = kinds.get(work["kind"], 0) + 1
            for name in work["authors"]:
                author_works.setdefault(name, set()).add(work["id"])
            if position is not None and position != 0:
                by_position.setdefault(position, []).append(work)
        ranked = sorted(author_works, key=lambda name: -len(author_works[name]))
        credit_names = []
        if ranked and len(author_works[ranked[0]]) * 2 >= len(entries):
            credit_names = ranked[:1]
        elif len(ranked) > 1 and len(author_works[ranked[0]] | author_works[ranked[1]]) * 2 >= len(
            entries
        ):
            credit_names = ranked[:2]
        leads = {}
        for position, members in by_position.items():
            lead = min(
                members,
                key=lambda w: (
                    w["kind"] != "novel",
                    catalogue.publication_key(w["first_published"]),
                    w["title"].casefold(),
                    w["id"],
                ),
            )
            leads[position] = lead["id"]
        preview = []
        for work, position, _ in entries:
            if position is None or position == 0 or leads[position] == work["id"]:
                preview.append(
                    {
                        **work,
                        "shelf_alternates": len(by_position[position]) - 1
                        if position is not None and position != 0
                        else 0,
                    }
                )
        result.append(
            {
                **shelf,
                "total": len(entries),
                "counts": counts,
                "counts_complete": True,
                "inspected": len(entries),
                "position_counts": positions,
                "kinds": kinds,
                "credit": {"names": credit_names, "others": len(ranked) - len(credit_names)},
                "_works": [work for work, _, _ in entries],
                "works": preview[:PREVIEW_SIZE],
            }
        )
    return result, unlinked


@dataclass
class MatchIndex:
    proof: tuple = ()
    ready: threading.Event = field(default_factory=threading.Event)
    groups: list[dict] = field(default_factory=list)
    unlinked: int = 0
    error: library.LibraryError | None = None


_indexes: OrderedDict[tuple, MatchIndex] = OrderedDict()
_index_lock = threading.Lock()
_build_slot = threading.BoundedSemaphore(1)


def match_index(params, first, metadata, totals, info):
    key = (
        settings.LIBRARIUM_LIBRARY_URL,
        settings.LIBRARIUM_CATALOGUE_DIR,
        info["version"],
        info["sha256"],
        first["snapshot"],
        params["q"],
        params["ownership"],
    )
    with _index_lock:
        cached = _indexes.get(key)
        if cached is not None:
            if cached.proof != tuple(first[k] for k in CONSISTENT):
                raise library.LibraryError(UNSUPPORTED)
            _indexes.move_to_end(key)
            if cached.ready.is_set() and cached.error is not None:
                del _indexes[key]
            return cached
        # No executor queue or unbounded per-filter threads. A later poll can
        # start this filter after the single active build releases its slot.
        if not _build_slot.acquire(blocking=False):
            return None
        cached = MatchIndex(proof=tuple(first[k] for k in CONSISTENT))
        _indexes[key] = cached
        while len(_indexes) > MAX_INDEXES:
            _indexes.popitem(last=False)

    def build():
        deadline = time.monotonic() + INDEX_BUDGET

        def read(offset):
            with _index_lock:
                if _indexes.get(key) is not cached:
                    raise library.LibraryCheckChanged(
                        "The library check changed. Reload the library."
                    )
            selection = {**params, "offset": offset, "snapshot": first["snapshot"]}
            # Each GET retains the existing three-second read/one-second connect
            # bounds and 2 MiB cap; the complete background run has a 30s cap.
            result = library.project(
                library.fetch(selection, min(deadline, time.monotonic() + BUDGET)),
                selection,
                offset // LIMIT + 1,
            )
            if any(result[k] != first[k] for k in CONSISTENT):
                raise library.LibraryError(UNSUPPORTED)
            return result["works"]

        try:
            values = list(first["works"])
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
                for more in executor.map(read, range(LIMIT, first["total"], LIMIT)):
                    values.extend(more)
            if len({w["id"] for w in values}) != len(values):
                raise library.LibraryError(UNSUPPORTED)
            # Revalidate the immutable pin before publishing any evidence.
            catalogue_context(info["version"], info["sha256"])
            groups, unlinked = group(values, metadata, totals, params["q"])
            if time.monotonic() >= deadline:
                raise library.LibraryError("Preparing shelves took too long. Reload the library.")
            with _index_lock:
                if _indexes.get(key) is cached:
                    cached.groups, cached.unlinked = groups, unlinked
        except library.LibraryError as error:
            cached.error = error
        except Exception:  # noqa: BLE001 - the coordinator must publish every failed read
            # Background failures must reach the next poll, never leave an
            # indefinitely preparing UI or expose exception/source details.
            cached.error = library.LibraryError(UNSUPPORTED)
        finally:
            cached.ready.set()
            _build_slot.release()

    try:
        threading.Thread(target=build, name="library-match-index", daemon=True).start()
    except RuntimeError:
        cached.error = library.LibraryError("Preparing shelves is unavailable. Try again shortly.")
        cached.ready.set()
        _build_slot.release()
    return cached


def shelves(query):
    params, page = parameters(query)
    if not settings.LIBRARIUM_LIBRARY_URL:
        return {"status": "not_configured"}
    metadata, totals, info = catalogue_context(query["version"], query["sha256"])
    deadline = time.monotonic() + BUDGET
    raw = library.fetch(params, deadline)
    first = library.project(raw, params, 1)
    status = (
        "loading"
        if first["catalogue_version"] is None
        else "version_mismatch"
        if first["catalogue_version"] != info["version"]
        else "ready"
    )
    truncated, unlinked, series_total, selected = False, 0, 0, []
    groups = []
    if status == "ready" and not first["loading"]:
        if first["total"] <= MAX_PAGES * LIMIT:
            first, works, truncated = read_index(params, first, deadline)
            groups, unlinked = group(works, metadata, totals, params["q"])
        elif first["total"] > MAX_INDEX_WORKS:
            truncated = True
        else:
            index = match_index(params, first, metadata, totals, info)
            status = "preparing"
            if index is not None and index.ready.is_set():
                if index.error is not None:
                    raise index.error
                groups, unlinked = index.groups, index.unlinked
                status = "ready"
        series_total = len(groups)
        selected = groups[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    standalone = query.get("group") == "standalone"
    standalone_works: list[dict] = next((s["_works"] for s in groups if s["id"] is None), [])
    selected_works = (
        standalone_works[(page - 1) * 24 : page * 24]
        if standalone
        else list({w["id"]: w for shelf in selected for w in shelf["works"]}.values())
    )
    return {
        "finish_origin": settings.LIBRARIUM_LIBRARY_URL,
        **{
            k: first[k]
            for k in (
                "source",
                "catalogue_version",
                "checked_at",
                "coverage",
                "loading",
                "snapshot",
                "total",
            )
        },
        "status": status,
        "catalogue_snapshot": info,
        "truncated": truncated,
        "unlinked_total": unlinked,
        "series_total": series_total,
        "series_scope": "matching",
        "page": page,
        "page_size": 24 if standalone else PAGE_SIZE,
        **({"total": len(standalone_works)} if standalone and status == "ready" else {}),
        **(
            {}
            if standalone
            else {"shelves": [{k: v for k, v in s.items() if k != "_works"} for s in selected]}
        ),
        "works": selected_works,
    }
