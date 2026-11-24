"""Read published BLC snapshots without importing its engines or owning its records."""

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

VERSION = re.compile(r"\d{4}\.\d{2}\.\d{2}\.[1-9]\d{0,8}")
DIGEST = re.compile(r"[a-f0-9]{64}")
UMBRELLA_SERIES = {
    "warhammer",
    "warhammer 40,000",
    "warhammer fantasy",
    "warhammer age of sigmar",
    "warhammer horror",
}
CONTRACT = {
    "meta": {"key", "value"},
    "work": {"id", "title", "sort_title", "synopsis", "type", "first_published"},
    "author": {"id", "name"},
    "work_author": {"work_id", "author_id", "role"},
    "series": {"id", "name"},
    "work_series": {"work_id", "series_id", "position"},
    "edition": {"id", "work_id", "format", "isbn10", "isbn13", "publisher", "release_date"},
    "field_support": {
        "entity",
        "entity_id",
        "field",
        "value",
        "score",
        "agree_json",
        "disagree_json",
    },
}


class CatalogueError(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def valid_version(value: str) -> bool:
    if not VERSION.fullmatch(value):
        return False
    try:
        datetime.strptime(value[:10], "%Y.%m.%d")
    except ValueError:
        return False
    return True


def identity(path: Path) -> tuple:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def connection(path: Path, seconds: float = 2):
    db = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA mmap_size=536870912")
        deadline = time.monotonic() + seconds
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        yield db
    finally:
        db.close()


@lru_cache(maxsize=8)
def validate(path: Path, signature: tuple, version: str) -> str:
    if signature[2] > 512 * 1024 * 1024:
        raise CatalogueError("Catalogue snapshot exceeds the supported size")
    with path.open("rb") as stream:
        header = stream.read(100)
        if not header.startswith(b"SQLite format 3\x00") or header[18:20] != b"\x01\x01":
            raise CatalogueError("Catalogue must be a self-contained published SQLite snapshot")
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with connection(path, seconds=10) as db:
        if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise CatalogueError("Catalogue snapshot failed its integrity check")
        tables = {
            row["name"] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")
        }
        for table, required in CONTRACT.items():
            if table not in tables or not required <= {
                row["name"] for row in db.execute(f'PRAGMA table_info("{table}")')
            }:
                raise CatalogueError("Catalogue snapshot has an incompatible schema")
        row = db.execute("SELECT value FROM meta WHERE key='catalog_version'").fetchone()
        if not row or row[0] != version:
            raise CatalogueError("Catalogue snapshot version does not match its filename")
    if identity(path) != signature:
        raise CatalogueError("Catalogue snapshot changed during validation")
    return digest


@contextmanager
def snapshot(
    root: str, version: str = "", sha256: str = "", fixture: bool = False, *, seconds: float = 2
):
    if (
        bool(version) != bool(sha256)
        or (version and not valid_version(version))
        or (sha256 and not DIGEST.fullmatch(sha256))
    ):
        raise CatalogueError("Use a valid catalogue version and fingerprint together", 400)
    if not root:
        raise CatalogueError("No catalogue snapshot is configured")
    pinned = bool(version)
    try:
        directory = Path(root).resolve(strict=True)
        if not version:
            pointer = directory / "current"
            if pointer.is_symlink() or pointer.stat().st_size > 80:
                raise CatalogueError("Catalogue snapshot pointer is invalid")
            version = pointer.read_text().strip()
            if not valid_version(version):
                raise CatalogueError("Catalogue snapshot pointer is invalid")
        path = directory / f"{version}.sqlite"
        if path.is_symlink() or not path.is_file():
            raise CatalogueError(
                "Selected catalogue snapshot is unavailable", 409 if pinned else 503
            )
        signature = identity(path)
        digest = validate(path, signature, version)
        if sha256 and digest != sha256:
            raise CatalogueError(
                "Selected catalogue snapshot changed; select the current snapshot", 409
            )
        with connection(path, seconds=seconds) as db:
            if identity(path) != signature:
                raise CatalogueError("Catalogue snapshot changed during opening", 409)
            yield db, {"version": version, "sha256": digest, "fixture": fixture}
            if identity(path) != signature:
                raise CatalogueError("Catalogue snapshot changed during reading", 409)
    except (OSError, sqlite3.Error, UnicodeError, ValueError) as error:
        raise CatalogueError(
            "Catalogue snapshot is unavailable or invalid", 409 if pinned else 503
        ) from error


def shelving_series(db) -> set[str]:
    excluded = set(UMBRELLA_SERIES)
    if "setting" in {row["name"] for row in db.execute("PRAGMA table_info(work)")}:
        excluded.update(
            row[0].strip().casefold()
            for row in db.execute("SELECT DISTINCT setting FROM work WHERE setting IS NOT NULL")
        )
    return {
        str(row["id"])
        for row in db.execute(
            "SELECT s.id,s.name FROM series s WHERE EXISTS "
            "(SELECT 1 FROM work_series ws WHERE ws.series_id=s.id AND ws.position IS NOT NULL)"
        )
        if row["name"].strip().casefold() not in excluded
        and "reading order" not in row["name"].casefold()
    }


def people(db, work_id: str, version: str, eligible: set[str] | None = None) -> dict:
    eligible = shelving_series(db) if eligible is None else eligible
    return {
        "authors": [
            {"id": str(row["id"]), "name": row["name"], "version": version}
            for row in db.execute(
                "SELECT a.id, a.name FROM author a JOIN work_author wa ON wa.author_id=a.id "
                "WHERE wa.work_id=? AND wa.role='author' ORDER BY a.name, a.id",
                (work_id,),
            )
        ],
        "series": [
            {
                **dict(row),
                "id": str(row["id"]),
                "version": version,
                "shelf_eligible": str(row["id"]) in eligible,
            }
            for row in db.execute(
                "SELECT s.id, s.name, ws.position, "
                "(SELECT count(*) FROM work_series members WHERE members.series_id=s.id) work_count "
                "FROM series s JOIN work_series ws ON ws.series_id=s.id "
                "WHERE ws.work_id=? ORDER BY s.name, s.id",
                (work_id,),
            )
        ],
    }


def search_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def series_index(db, info: dict, query: str, page: int) -> dict:
    pattern = search_pattern(query)
    total = db.execute(
        "SELECT count(*) FROM series WHERE name LIKE ? ESCAPE '\\'", (pattern,)
    ).fetchone()[0]
    rows = db.execute(
        "SELECT s.id, s.name, (SELECT count(*) FROM work_series ws JOIN work w ON w.id=ws.work_id "
        "WHERE ws.series_id=s.id) work_count FROM series s WHERE s.name LIKE ? ESCAPE '\\' "
        "ORDER BY s.name COLLATE NOCASE, s.id LIMIT 24 OFFSET ?",
        (pattern, (page - 1) * 24),
    )
    return {
        "snapshot": info,
        "series": [{**dict(row), "id": str(row["id"]), "version": info["version"]} for row in rows],
        "total": total,
        "page": page,
        "page_size": 24,
    }


def series_credit(db, series_id: int) -> dict:
    """Credit authors by distinct member coverage across the complete pinned series."""
    total = db.execute(
        "SELECT count(*) FROM work_series ws JOIN work w ON w.id=ws.work_id WHERE ws.series_id=?",
        (series_id,),
    ).fetchone()[0]
    ranked = db.execute(
        "SELECT a.name,count(DISTINCT ws.work_id) credited,count(*) OVER () author_total "
        "FROM work_series ws JOIN work_author wa ON wa.work_id=ws.work_id "
        "JOIN author a ON a.id=wa.author_id WHERE ws.series_id=? AND wa.role='author' "
        "GROUP BY a.name ORDER BY credited DESC,min(a.id),a.name LIMIT 2",
        (series_id,),
    ).fetchall()
    names = []
    if len(ranked) == 2 and ranked[1]["credited"] * 2 >= total:
        names = [row["name"] for row in ranked]
    elif ranked and ranked[0]["credited"] * 2 >= total:
        names = [ranked[0]["name"]]
    elif len(ranked) == 2:
        together = db.execute(
            "SELECT count(DISTINCT ws.work_id) FROM work_series ws "
            "JOIN work_author wa ON wa.work_id=ws.work_id JOIN author a ON a.id=wa.author_id "
            "WHERE ws.series_id=? AND wa.role='author' AND a.name IN (?,?)",
            (series_id, ranked[0]["name"], ranked[1]["name"]),
        ).fetchone()[0]
        if together * 2 >= total:
            names = [row["name"] for row in ranked]
    return {"names": names, "others": (ranked[0]["author_total"] if ranked else 0) - len(names)}


def browse(
    db, info: dict, query: str, series: int | None, page: int, author: int | None = None
) -> dict:
    from librarium import author_groups

    alias_state = author_groups.availability(db)
    pattern = search_pattern(query)
    alias_search = (
        r" OR EXISTS (SELECT 1 FROM author_alias aa WHERE aa.author_id=a.id "
        r"AND aa.name LIKE ? ESCAPE '\')"
        if alias_state == "available"
        else ""
    )
    where = r"""(w.title LIKE ? ESCAPE '\' OR EXISTS (
        SELECT 1 FROM work_author wa JOIN author a ON a.id=wa.author_id
        WHERE wa.work_id=w.id AND wa.role='author' AND (a.name LIKE ? ESCAPE '\'"""
    where += (
        alias_search
        + r""")) OR EXISTS (
        SELECT 1 FROM work_series ws JOIN series s ON s.id=ws.series_id
        WHERE ws.work_id=w.id AND s.name LIKE ? ESCAPE '\'))"""
    )
    args: list = [pattern, pattern, *([pattern] if alias_search else []), pattern]
    selected_author = None
    selected_series = None
    source = "work w"
    joined: list = []
    order = "coalesce(w.sort_title,w.title) COLLATE NOCASE, w.id"
    if author is not None:
        person = db.execute("SELECT id, name FROM author WHERE id=?", (author,)).fetchone()
        if person:
            selected_author = {
                **dict(person),
                "id": str(person["id"]),
                "version": info["version"],
            }
        where += (
            " AND EXISTS (SELECT 1 FROM work_author wa WHERE wa.work_id=w.id "
            "AND wa.author_id=? AND wa.role='author')"
        )
        args.append(author)
    if series is not None:
        membership = db.execute("SELECT id, name FROM series WHERE id=?", (series,)).fetchone()
        if membership:
            selected_series = {
                **dict(membership),
                "id": str(membership["id"]),
                "version": info["version"],
                "credit": series_credit(db, series),
            }
        # (work_id, series_id) is the key, so the join keeps one row per work.
        source += " JOIN work_series sp ON sp.work_id=w.id AND sp.series_id=?"
        joined.append(series)
        # 0 is a recorded position, not a missing one; it sorts after the numbered
        # run and before unpositioned members instead of ahead of 1.
        order = (
            "CASE WHEN sp.position IS NULL THEN 2 WHEN sp.position=0 THEN 1 ELSE 0 END, "
            "sp.position, " + order
        )
    params = [*joined, *args]
    position_counts = None
    if series is None:
        total = db.execute(f"SELECT count(*) FROM {source} WHERE {where}", params).fetchone()[0]
    else:
        counted = db.execute(
            "SELECT count(*), coalesce(sum(sp.position<>0),0), coalesce(sum(sp.position=0),0), "
            f"coalesce(sum(sp.position IS NULL),0) FROM {source} WHERE {where}",
            params,
        ).fetchone()
        total = counted[0]
        position_counts = {
            "numbered": counted[1],
            "zero": counted[2],
            "unpositioned": counted[3],
        }
    rows = db.execute(
        f"SELECT w.id, w.title, w.type, w.first_published, "
        f"(SELECT count(*) FROM edition e WHERE e.work_id=w.id) edition_count "
        f"FROM {source} WHERE {where} ORDER BY {order} LIMIT 24 OFFSET ?",
        [*params, (page - 1) * 24],
    ).fetchall()
    eligible = shelving_series(db)
    return {
        "snapshot": info,
        "author_evidence": author_groups.evidence(
            db,
            info,
            author_groups.authors_for(db, [row["id"] for row in rows], author, query, pattern)
            if alias_state == "available"
            else [],
            alias_state,
            query,
            pattern,
        ),
        "selected_author": selected_author,
        "selected_series": selected_series,
        "position_counts": position_counts,
        "works": [
            {**dict(row), **people(db, row["id"], info["version"], eligible)} for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": 24,
    }


def publication_key(value: str | None) -> tuple[int, int, int]:
    """Compare ISO date prefixes, keeping unknown month/day after known parts."""
    match = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?![\d-])", value or "")
    if not match:
        return 9999, 99, 99
    year, month, day = match.groups()
    return int(year), int(month) if month else 99, int(day) if day else 99


def position_leads(db, series_ids: list[str] | None = None) -> dict:
    """Canonical leads from every pinned member, independent of library matches."""
    if series_ids == []:
        return {}
    restriction = ""
    if series_ids is not None:
        restriction = f" AND ws.series_id IN ({','.join('?' for _ in series_ids)})"
    db.create_function(
        "publication_order",
        1,
        lambda value: "-".join(f"{part:04}" for part in publication_key(value)),
        deterministic=True,
    )
    rows = db.execute(
        "SELECT series_id,position,lead_work_id,position_total FROM ("
        "SELECT ws.series_id,ws.position,w.id AS lead_work_id,"
        "count(*) OVER (PARTITION BY ws.series_id,ws.position) AS position_total,"
        "row_number() OVER (PARTITION BY ws.series_id,ws.position "
        "ORDER BY w.type='novel' DESC,publication_order(w.first_published),"
        "lower(w.title),w.id) AS rank "
        "FROM work_series ws JOIN work w ON w.id=ws.work_id "
        "WHERE ws.position IS NOT NULL AND ws.position!=0" + restriction + ") WHERE rank=1",
        series_ids or [],
    )
    return {
        (str(row["series_id"]), row["position"]): {
            "lead_work_id": row["lead_work_id"],
            "position_total": row["position_total"],
        }
        for row in rows
    }


def detail(db, info: dict, work_id: str) -> dict:
    from librarium import author_groups

    row = db.execute(
        "SELECT id, title, synopsis, type, first_published FROM work WHERE id=?", (work_id,)
    ).fetchone()
    if not row:
        raise CatalogueError("Catalogue work not found", 404)
    support = []
    for evidence in db.execute(
        "SELECT field, value, agree_json, disagree_json FROM field_support "
        "WHERE entity='work' AND entity_id=? ORDER BY field, value LIMIT 100",
        (work_id,),
    ):
        agree, disagree = json.loads(evidence["agree_json"]), json.loads(evidence["disagree_json"])
        if (
            not isinstance(agree, list)
            or not all(isinstance(item, str) for item in agree)
            or not isinstance(disagree, list)
            or not all(
                isinstance(item, dict) and isinstance(item.get("origin"), str) and "value" in item
                for item in disagree
            )
        ):
            raise CatalogueError("Catalogue source support is invalid")
        support.append(
            {
                "field": evidence["field"],
                "value": evidence["value"],
                "agree": agree,
                "disagree": disagree,
            }
        )
    editions = [
        dict(e)
        for e in db.execute(
            "SELECT id, format, isbn10, isbn13, publisher, release_date FROM edition WHERE work_id=? ORDER BY id LIMIT 200",
            (work_id,),
        )
    ]
    context = people(db, work_id, info["version"])
    leads = position_leads(db, [s["id"] for s in context["series"]])
    for membership in context["series"]:
        membership.update(leads.get((membership["id"], membership["position"]), {}))
    return {
        **dict(row),
        **context,
        "snapshot": info,
        "author_evidence": author_groups.evidence(
            db,
            info,
            db.execute(
                "SELECT a.id,a.name FROM author a JOIN work_author wa ON wa.author_id=a.id "
                "WHERE wa.work_id=? AND wa.role='author' ORDER BY a.name,a.id LIMIT 65",
                (work_id,),
            ).fetchall(),
            author_groups.availability(db),
        ),
        "ownership": "unconfirmed",
        "editions": editions,
        "support": support,
        "edition_count": db.execute(
            "SELECT count(*) FROM edition WHERE work_id=?", (work_id,)
        ).fetchone()[0],
    }
