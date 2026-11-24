"""Native Calibre metadata and original-file reads, with no incumbent service."""

import atexit
import hashlib
import math
import os
import re
import sqlite3
import stat
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings

from librarium import catalogue_covers

PAGE_SIZE = 24
MAX_DATABASE = 512 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_TEXT = 2000
MAX_RELATIONS = 64
SECONDS = 3.0
SLOTS = threading.BoundedSemaphore(4)
IDENTITY = re.compile(r"[0-9a-f]{64}\Z")
FORMAT = re.compile(r"[A-Z0-9_]{1,32}\Z")
_METADATA_LOCK = threading.Lock()
_METADATA: tuple[tuple, tempfile.TemporaryDirectory] | None = None


def _discard_metadata():
    global _METADATA
    if _METADATA is not None:
        _METADATA[1].cleanup()
        _METADATA = None


atexit.register(_discard_metadata)


class DirectLibraryError(Exception):
    def __init__(self, message: str, status: int = 503, code: str = "direct_library_invalid"):
        super().__init__(message)
        self.status = status
        self.code = code


def changed():
    return DirectLibraryError(
        "The library changed during this view. Refresh the library and select the book again.",
        409,
        "direct_library_changed",
    )


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def components(path: str) -> list[str]:
    if not isinstance(path, str) or not path or len(path) > 4096 or "\\" in path or "\x00" in path:
        raise ValueError
    values = path.split("/")
    if any(value in {"", ".", ".."} for value in values):
        raise ValueError
    return values


@contextmanager
def directory():
    selected = getattr(settings, "DIRECT_LIBRARY_ROOT", "")
    if not selected:
        raise DirectLibraryError(
            "A read-only Calibre library has not been connected.",
            503,
            "direct_library_unconfigured",
        )
    if not isinstance(selected, str) or not selected.startswith("/"):
        raise ValueError
    with ExitStack() as stack:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open("/", flags)
        stack.callback(os.close, fd)
        for part in components(selected[1:]):
            fd = os.open(part, flags, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd


@contextmanager
def folder(root: int, parts: list[str]):
    with ExitStack() as stack:
        parent = root
        for part in parts:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            stack.callback(os.close, parent)
        yield parent


@contextmanager
def file_in(parent: int, name: str, limit: int | None = None):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (limit is not None and info.st_size > limit):
            raise ValueError
        yield stream, info


@contextmanager
def source_file(root: int, relative: str, limit: int | None = None):
    parts = components(relative)
    with folder(root, parts[:-1]) as parent, file_in(parent, parts[-1], limit) as opened:
        yield opened


def source_digest(stream, deadline):
    # Checkpoints and recycled WALs can preserve headers and stat identity while pages change.
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_DATABASE or time.monotonic() > deadline:
            raise DirectLibraryError("The library read exceeded its safety limit.")
        digest.update(chunk)
    return digest.hexdigest()


def state(root: int, deadline=None) -> dict:
    if deadline is None:
        deadline = time.monotonic() + SECONDS
    result: dict = {}
    for name in ("metadata.db", "metadata.db-wal", "metadata.db-journal"):
        try:
            with source_file(root, name, MAX_DATABASE) as (stream, info):
                digest = source_digest(stream, deadline)
                if signature(os.fstat(stream.fileno())) != signature(info):
                    raise changed()
                result[name] = (*signature(info), digest)
        except FileNotFoundError:
            if name == "metadata.db":
                raise
            result[name] = None
    if result["metadata.db-journal"] and result["metadata.db-journal"][2]:
        raise DirectLibraryError(
            "Calibre is updating the library. Retry after its current update finishes.",
            503,
            "direct_library_busy",
        )
    if sum(value[2] for value in result.values() if value) > MAX_DATABASE:
        raise DirectLibraryError("The library metadata exceeds this reader's safety limit.")
    return result


def check_token(value: str):
    if value and (not isinstance(value, str) or not IDENTITY.fullmatch(value)):
        raise ValueError


@contextmanager
def _metadata_snapshot(root, before, deadline):
    global _METADATA
    if not _METADATA_LOCK.acquire(timeout=max(0, deadline - time.monotonic())):
        raise DirectLibraryError(
            "The library reader is busy. Retry shortly.", 503, "direct_library_busy"
        )
    try:
        key = (signature(os.fstat(root))[:2], repr(before))
        if _METADATA is None or _METADATA[0] != key:
            _discard_metadata()
            scratch = tempfile.TemporaryDirectory(prefix="librarium-calibre-")
            try:
                for name in ("metadata.db", "metadata.db-wal"):
                    if not before[name] or not before[name][2]:
                        continue
                    with source_file(root, name, MAX_DATABASE) as (stream, info):
                        if signature(info) != before[name][:5]:
                            raise changed()
                        if name.endswith("-wal"):
                            header = stream.read(32)
                            page_size = int.from_bytes(header[8:12], "big")
                            if (
                                len(header) != 32
                                or int.from_bytes(header[:4], "big") not in {0x377F0682, 0x377F0683}
                                or int.from_bytes(header[4:8], "big") != 3007000
                                or not 512 <= page_size <= 65536
                                or page_size & (page_size - 1)
                            ):
                                raise DirectLibraryError(
                                    "The library transaction log could not be read safely."
                                )
                            stream.seek(0)
                        copied_digest = hashlib.sha256()
                        with open(Path(scratch.name) / name, "xb") as target:
                            while chunk := stream.read(1024 * 1024):
                                target.write(chunk)
                                copied_digest.update(chunk)
                                if time.monotonic() > deadline or target.tell() > MAX_DATABASE:
                                    raise DirectLibraryError(
                                        "The library read exceeded its safety limit."
                                    )
                        if copied_digest.hexdigest() != before[name][5]:
                            raise changed()
                if state(root, deadline) != before:
                    raise changed()
            except BaseException:
                scratch.cleanup()
                raise
            _METADATA = (key, scratch)
        # A single private copy is retained per process. Holding the lock through
        # connection close prevents replacement while another request is reading it.
        yield _METADATA[1].name
    except sqlite3.Error:
        _discard_metadata()
        raise
    finally:
        _METADATA_LOCK.release()


def token_of(observed: dict) -> str:
    """The inventory token names one observation of the metadata files from state()."""
    return hashlib.sha256(repr(observed).encode()).hexdigest()


@contextmanager
def snapshot(inventory: str = "", *, seconds: float | None = None, wait: bool = False):
    check_token(inventory)
    acquired = SLOTS.acquire(timeout=SECONDS) if wait else SLOTS.acquire(blocking=False)
    if not acquired:
        raise DirectLibraryError(
            "The library reader is busy. Retry shortly.", 503, "direct_library_busy"
        )
    deadline = time.monotonic() + (SECONDS if seconds is None else seconds)
    try:
        with directory() as root:
            before = state(root, deadline)
            token = token_of(before)
            if inventory and token != inventory:
                raise changed()
            # SQLite sees only private copies, including committed WAL frames. It cannot
            # create SHM, recover a journal or acquire a writer lock in the source library.
            with _metadata_snapshot(root, before, deadline) as scratch:
                uri = (Path(scratch) / "metadata.db").as_uri() + "?mode=ro"
                with ExitStack() as stack:
                    db = sqlite3.connect(uri, uri=True, timeout=0.2)
                    stack.callback(db.close)
                    db.row_factory = sqlite3.Row
                    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
                    db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 64 * 1024)
                    db.execute("PRAGMA query_only=ON")
                    db.execute("PRAGMA trusted_schema=OFF")
                    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                    db.execute("BEGIN")
                    required = {"books", "authors", "books_authors_link", "data"}
                    actual = {
                        row[0]
                        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    if not required <= actual:
                        raise DirectLibraryError(
                            "The connected metadata is not a supported Calibre library."
                        )
                    library_uuid = None
                    if "library_id" in actual:
                        identities = db.execute(
                            "SELECT substr(uuid,1,2001) FROM library_id LIMIT 2"
                        ).fetchall()
                        if len(identities) != 1:
                            raise ValueError
                        library_uuid = text(identities[0][0])
                    info = {
                        "token": token,
                        "observed_at": datetime.now(UTC).isoformat(),
                        "scope": "metadata",
                        "library_uuid": library_uuid,
                    }
                    yield db, root, info
                    if state(root, deadline) != before:
                        raise changed()
    except DirectLibraryError:
        raise
    except (OSError, sqlite3.Error, ValueError, OverflowError) as error:
        raise DirectLibraryError(
            "The Calibre library could not be read safely. Check the read-only connection and retry."
        ) from error
    finally:
        SLOTS.release()


def text(value, maximum=MAX_TEXT) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError
    return value


def publication_date(value) -> str | None:
    recorded = text(value)
    if not recorded:
        return None
    try:
        stamp = datetime.fromisoformat(recorded)
    except ValueError:
        return recorded
    # Match Calibre's is_date_undefined without shifting the recorded calendar date.
    if stamp.year < 101 or (stamp.year, stamp.month, stamp.day) == (101, 1, 1):
        return None
    return recorded


def rows(db, sql: str, values: tuple) -> list:
    selected = db.execute(sql, values).fetchmany(MAX_RELATIONS + 1)
    if len(selected) > MAX_RELATIONS:
        raise DirectLibraryError(
            "A book has more metadata relationships than this reader can safely show."
        )
    return selected


def optional_rows(db, table: str, sql: str, values: tuple) -> list:
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return rows(db, sql, values)
    return []


def has_added(db) -> bool:
    """Calibre records when each book arrived; minimal libraries may not."""
    return any(row[1] == "timestamp" for row in db.execute("PRAGMA table_info(books)"))


def record(db, book_id: str):
    if (
        not isinstance(book_id, str)
        or not re.fullmatch(r"[1-9][0-9]{0,18}", book_id)
        or int(book_id) > 2**63 - 1
    ):
        raise DirectLibraryError("Select a valid library book.", 400, "direct_library_request")
    added = "substr(timestamp,1,2001)" if has_added(db) else "NULL"
    row = db.execute(
        "SELECT id,substr(title,1,2001) title,substr(path,1,4097) path,"
        "substr(uuid,1,2001) uuid,series_index,substr(pubdate,1,2001) pubdate,"
        f"{added} added FROM books WHERE id=?",
        (book_id,),
    ).fetchone()
    if row is None:
        raise DirectLibraryError(
            "The selected library book is unavailable.", 404, "direct_library_missing"
        )
    return row


def format_rows(db, book_id: str) -> list:
    return rows(
        db,
        "SELECT substr(format,1,33) format,substr(name,1,2001) name,uncompressed_size "
        "FROM data WHERE book=? ORDER BY format,id",
        (book_id,),
    )


def format_name(row) -> str:
    kind = text(row["format"])
    name = text(row["name"])
    if not kind or not FORMAT.fullmatch(kind) or not name or len(components(name)) != 1:
        raise ValueError
    return name + "." + kind.lower()


def format_entry(row) -> dict:
    recorded = row["uncompressed_size"]
    return {
        "format": row["format"],
        "name": format_name(row),
        "size_bytes": None,
        "recorded_size_bytes": recorded if type(recorded) is int and recorded >= 0 else None,
        "available": None,
    }


def file_stat(parent: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def file_size(parent: int, name: str) -> int | None:
    info = file_stat(parent, name)
    return info.st_size if info else None


def cover_metadata(head: bytes, size: int) -> dict:
    media_type = None
    dimensions = None
    for kind, parser in (
        ("image/png", catalogue_covers.png_dimensions),
        ("image/jpeg", catalogue_covers.jpeg_dimensions),
        ("image/gif", catalogue_covers.gif_dimensions),
    ):
        try:
            dimensions = parser(head[: catalogue_covers.MAX_HEADER])
            media_type = kind
            break
        except ValueError:
            continue
    if dimensions is None:
        dimensions = catalogue_covers.webp_dimensions(head[: catalogue_covers.MAX_HEADER], size)
        media_type = "image/webp"
    if not catalogue_covers.dimensions_allowed(*dimensions):
        raise ValueError
    return {"media_type": media_type, "width": dimensions[0], "height": dimensions[1]}


def read_cover(root, path, *, limit=catalogue_covers.MAX_BODY) -> tuple[bytes, dict]:
    with source_file(root, path + "/cover.jpg", limit) as (stream, before):
        raw = stream.read(limit + 1)
        if len(raw) != before.st_size or signature(os.fstat(stream.fileno())) != signature(before):
            raise ValueError
    return raw, cover_metadata(raw, len(raw))


# Most covers name their size in the first few kilobytes; a header cut short never
# parses, so only covers with long preambles read on to the full header.
FIRST_HEADER = 64 * 1024


def cover_info(parent: int) -> dict:
    """What a listing needs about a cover, from its header alone; the cover route reads it all."""
    with file_in(parent, "cover.jpg", catalogue_covers.MAX_BODY) as (stream, before):
        head = stream.read(FIRST_HEADER)
        try:
            value = cover_metadata(head, before.st_size)
        except ValueError:
            if len(head) < FIRST_HEADER:
                raise
            head += stream.read(catalogue_covers.MAX_HEADER - len(head))
            value = cover_metadata(head, before.st_size)
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise ValueError
    return value


def cover_url(book_id: str, token: str) -> str:
    return f"/api/direct-library/books/{book_id}/cover?" + urlencode({"inventory": token})


def book_files(root: int, path: str, book: dict, inventory: dict) -> None:
    """Fills in which recorded files exist and the cover, opening the book's folder once."""
    for entry in book["formats"]:
        entry["available"] = False
    try:
        parts = components(path)
        with folder(root, parts) as parent:
            for entry in book["formats"]:
                entry["size_bytes"] = file_size(parent, entry["name"])
                entry["available"] = entry["size_bytes"] is not None
            try:
                cover = cover_info(parent)
            except OSError, ValueError, TypeError:
                return
    except OSError, ValueError, TypeError:
        return
    cover["url"] = cover_url(book["id"], inventory["token"])
    book["cover"] = cover


PROBES = 8


def with_files(root: int, items: list[tuple[str, dict]], inventory: dict) -> list[dict]:
    """Each file check is a network round trip on a shared library, so a page runs them side by side."""

    def check(item: tuple[str, dict]) -> None:
        book_files(root, item[0], item[1], inventory)

    if len(items) > 1:
        with ThreadPoolExecutor(max_workers=min(PROBES, len(items))) as pool:
            list(pool.map(check, items))
    else:
        for item in items:
            check(item)
    return [book for _, book in items]


def project(db, root, row, inventory: dict, detail=False, *, read_files=True):
    book_id = str(row["id"])
    path = text(row["path"], 4096) or ""
    authors = [
        text(value[0])
        for value in rows(
            db,
            "SELECT substr(a.name,1,2001) FROM books_authors_link l JOIN authors a ON a.id=l.author "
            "WHERE l.book=? ORDER BY l.id",
            (book_id,),
        )
    ]
    series = optional_rows(
        db,
        "series",
        "SELECT substr(s.name,1,2001) FROM books_series_link l "
        "JOIN series s ON s.id=l.series WHERE l.book=? ORDER BY l.id",
        (book_id,),
    )
    publishers = optional_rows(
        db,
        "publishers",
        "SELECT substr(p.name,1,2001) FROM books_publishers_link l "
        "JOIN publishers p ON p.id=l.publisher WHERE l.book=? ORDER BY l.id",
        (book_id,),
    )
    languages = optional_rows(
        db,
        "languages",
        "SELECT substr(a.lang_code,1,2001) FROM books_languages_link l "
        "JOIN languages a ON a.id=l.lang_code WHERE l.book=? ORDER BY l.item_order,l.id",
        (book_id,),
    )
    identifiers = optional_rows(
        db,
        "identifiers",
        "SELECT substr(type,1,2001),substr(val,1,2001) FROM identifiers WHERE book=? ORDER BY id",
        (book_id,),
    )
    if len(series) > 1 or len(publishers) > 1:
        raise DirectLibraryError("A library book has conflicting single-value metadata.")
    position = row["series_index"]
    if position is not None and (type(position) not in {int, float} or not math.isfinite(position)):
        raise ValueError
    book = {
        "id": book_id,
        "uuid": text(row["uuid"]),
        "title": text(row["title"]),
        "authors": authors,
        "series": text(series[0][0]) if series else None,
        "series_index": position if series else None,
        "publisher": text(publishers[0][0]) if publishers else None,
        "published_at": publication_date(row["pubdate"]),
        "added_at": text(row["added"]),
        "languages": [text(value[0]) for value in languages],
        "identifiers": [{"type": text(value[0]), "value": text(value[1])} for value in identifiers],
        "formats": [format_entry(value) for value in format_rows(db, book_id)],
        "cover": None,
    }
    if read_files:
        book_files(root, path, book, inventory)
    if detail:
        comments = optional_rows(
            db,
            "comments",
            "SELECT substr(text,1,100001) FROM comments WHERE book=? ORDER BY id",
            (book_id,),
        )
        if len(comments) > 1:
            raise ValueError
        book["description"] = text(comments[0][0], 100000) if comments else None
    return book


def entry(db, root, book_id, inventory) -> tuple[str, dict]:
    row = record(db, str(book_id))
    return text(row["path"], 4096) or "", project(db, root, row, inventory, read_files=False)


def check_browse(query, page, order):
    if (
        order not in ("", "recent")
        or not isinstance(query, str)
        or len(query) > 200
        or "\x00" in query
        or type(page) is not int
        or not 1 <= page <= 10000
    ):
        raise DirectLibraryError(
            "Use a valid page and search of up to 200 characters.", 400, "direct_library_request"
        )


def browse(query="", page=1, inventory="", order=""):
    check_browse(query, page, order)
    with snapshot(inventory) as (db, root, info):
        where = (
            (
                "WHERE instr(lower(b.title),lower(?))>0 OR EXISTS (SELECT 1 FROM books_authors_link l "
                "JOIN authors a ON a.id=l.author WHERE l.book=b.id AND instr(lower(a.name),lower(?))>0)"
            )
            if query
            else ""
        )
        params = (query, query) if query else ()
        count = db.execute("SELECT count(*) FROM books b " + where, params).fetchone()[0]
        ids = db.execute(
            "SELECT b.id FROM books b "
            + where
            + (
                (
                    " ORDER BY b.timestamp DESC,b.id DESC LIMIT ? OFFSET ?"
                    if has_added(db)
                    else " ORDER BY b.id DESC LIMIT ? OFFSET ?"
                )
                if order == "recent"
                else " ORDER BY b.sort,b.id LIMIT ? OFFSET ?"
            ),
            (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        books = with_files(root, [entry(db, root, row[0], info) for row in ids], info)
        result = {
            "configured": True,
            "source": "calibre",
            "read_only": True,
            "inventory": info,
            "total": count,
            "page": page,
            "pages": max(1, math.ceil(count / PAGE_SIZE)),
            "page_size": PAGE_SIZE,
            "books": books,
        }
    return result


SERIES_LIMIT = 200


def check_series(name):
    if not isinstance(name, str) or not name or len(name) > 200 or "\x00" in name:
        raise DirectLibraryError(
            "Name one series of up to 200 characters.", 400, "direct_library_request"
        )


def series(name: str, inventory=""):
    """Every owned book in one Calibre series, in reading order, for the series strip."""
    check_series(name)
    with snapshot(inventory) as (db, root, info):
        ids = db.execute(
            "SELECT b.id FROM books b JOIN books_series_link l ON l.book=b.id "
            "JOIN series s ON s.id=l.series WHERE s.name=? "
            "ORDER BY b.series_index IS NULL, b.series_index, b.sort, b.id LIMIT ?",
            (name, SERIES_LIMIT),
        ).fetchall()
        books = with_files(root, [entry(db, root, row[0], info) for row in ids], info)
    return {"source": "calibre", "read_only": True, "inventory": info, "books": books}


def detail(book_id: str, inventory=""):
    with snapshot(inventory) as (db, root, info):
        result = {"inventory": info, "book": project(db, root, record(db, book_id), info, True)}
    return result


def cover(book_id: str, inventory=""):
    with snapshot(inventory) as (db, root, _):
        row = record(db, book_id)
        try:
            value = read_cover(root, text(row["path"], 4096))
        except (OSError, ValueError, TypeError) as error:
            raise DirectLibraryError(
                "This library cover is unavailable.", 404, "direct_library_missing"
            ) from error
    return value


@contextmanager
def open_format(book_id: str, selected_format: str, inventory: str):
    if (
        not inventory
        or not isinstance(selected_format, str)
        or not FORMAT.fullmatch(selected_format)
    ):
        raise DirectLibraryError(
            "Select a recorded format from the current library view.", 400, "direct_library_request"
        )
    with snapshot(inventory) as (db, root, info):
        row = record(db, book_id)
        selected = [
            value for value in format_rows(db, book_id) if value["format"] == selected_format
        ]
        if len(selected) != 1:
            raise DirectLibraryError(
                "The selected book format is unavailable.", 404, "direct_library_missing"
            )
        name = format_name(selected[0])
        with source_file(root, (text(row["path"], 4096) or "") + "/" + name, MAX_FILE) as (
            stream,
            before,
        ):
            yield (
                stream,
                {
                    "book_id": book_id,
                    "inventory": info,
                    "format": selected_format,
                    "name": name,
                    "size_bytes": before.st_size,
                    "uuid": text(row["uuid"]),
                    "library_uuid": info["library_uuid"],
                },
            )
            if signature(os.fstat(stream.fileno())) != signature(before):
                raise changed()
