"""A Postgres read model of the Calibre library. Calibre stays the source of truth.

The worker imports one complete observation whenever the direct reader's inventory token
changes. Listings, search, recent and series then read only these rows and touch nothing on
the library share. Detail, cover and file routes keep reading the real library.
"""

import hashlib
import logging
import math
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import UTC, datetime

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import Exists, F, Func, OuterRef, Prefetch, Q, TextField, Value
from django.db.models.functions import Collate, StrIndex

from librarium import direct_library
from librarium.direct_library import DirectLibraryError, text
from librarium.models import (
    CalibreAuthor,
    CalibreBook,
    CalibreBookAuthor,
    CalibreBookLanguage,
    CalibreFormat,
    CalibreIdentifier,
    CalibreLanguage,
    CalibrePublisher,
    CalibreSeries,
    LibraryReadModel,
)

logger = logging.getLogger(__name__)

MAX_BOOKS = 10000  # The reconciliation report's limit.
OBSERVE_SECONDS = 120.0
HASH_SECONDS = 10.0
HASH_BATCH = 500
# One import at a time across workers; the value only has to be unique to this lock.
LOCK = 0x4C524D31
FAILURES = (DirectLibraryError, OSError, ValueError, TypeError, OverflowError, sqlite3.Error)


class ReadModelError(Exception):
    pass


def sqlite_lower(value: str) -> str:
    """Fold a search exactly as the direct reader's SQLite lower() does (ASCII only)."""
    with closing(sqlite3.connect(":memory:")) as db:
        return db.execute("SELECT lower(?)", (value,)).fetchone()[0]


def signed(info) -> str:
    return ":".join(str(value) for value in direct_library.signature(info))


# Reading Calibre. Bulk queries replace the direct reader's per-book ones; every value goes
# through the same helpers and limits, and parity() proves the result book by book.


def relations(db, table, sql, ids):
    grouped: dict[int, list] = {}
    if (
        table
        and not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    ):
        return grouped
    for row in db.execute(sql):
        if row[0] in ids:
            selected = grouped.setdefault(row[0], [])
            selected.append(row)
            if len(selected) > direct_library.MAX_RELATIONS:
                raise ReadModelError(
                    f"Calibre book {row[0]} has more metadata relationships than the reader shows"
                )
    return grouped


def read_catalogue(db) -> dict:
    added = "substr(timestamp,1,2001)" if direct_library.has_added(db) else "NULL"
    rows = db.execute(
        "SELECT id,substr(title,1,2001) title,lower(title) title_lower,sort,"
        "substr(path,1,4097) path,substr(uuid,1,2001) uuid,series_index,"
        f"substr(pubdate,1,2001) pubdate,{added} added FROM books ORDER BY id LIMIT ?",
        (MAX_BOOKS + 1,),
    ).fetchall()
    if len(rows) > MAX_BOOKS:
        raise ReadModelError("The library exceeds the read model's book limit")
    ids = {row["id"] for row in rows}
    return {
        "books": rows,
        "authors": relations(
            db,
            None,
            "SELECT l.book,a.id,substr(a.name,1,2001),lower(a.name) FROM books_authors_link l "
            "JOIN authors a ON a.id=l.author ORDER BY l.book,l.id",
            ids,
        ),
        "series": relations(
            db,
            "series",
            "SELECT l.book,s.id,substr(s.name,1,2001) FROM books_series_link l "
            "JOIN series s ON s.id=l.series ORDER BY l.book,l.id",
            ids,
        ),
        "publishers": relations(
            db,
            "publishers",
            "SELECT l.book,p.id,substr(p.name,1,2001) FROM books_publishers_link l "
            "JOIN publishers p ON p.id=l.publisher ORDER BY l.book,l.id",
            ids,
        ),
        "languages": relations(
            db,
            "languages",
            "SELECT l.book,a.id,substr(a.lang_code,1,2001) FROM books_languages_link l "
            "JOIN languages a ON a.id=l.lang_code ORDER BY l.book,l.item_order,l.id",
            ids,
        ),
        "identifiers": relations(
            db,
            "identifiers",
            "SELECT book,substr(type,1,2001),substr(val,1,2001) FROM identifiers ORDER BY book,id",
            ids,
        ),
        "formats": relations(
            db,
            None,
            "SELECT book,id,substr(format,1,33) format,substr(name,1,2001) name,"
            "uncompressed_size FROM data ORDER BY book,format,id",
            ids,
        ),
    }


def book_record(row, read) -> dict:
    """One book as direct_library.project() would see it, plus the keys the model needs."""
    book_id = row["id"]
    if type(book_id) is not int or not 1 <= book_id <= 2**63 - 1:
        raise ValueError
    series = read["series"].get(book_id, [])
    publishers = read["publishers"].get(book_id, [])
    if len(series) > 1 or len(publishers) > 1:
        raise ReadModelError(f"Calibre book {book_id} has conflicting single-value metadata")
    position = row["series_index"]
    if position is not None and (type(position) not in {int, float} or not math.isfinite(position)):
        raise ValueError
    if row["sort"] is not None and not isinstance(row["sort"], str):
        raise ValueError
    return {
        "id": book_id,
        "uuid": text(row["uuid"]),
        "title": text(row["title"]),
        "title_lower": row["title_lower"],
        "sort": row["sort"],
        "path": text(row["path"], 4096) or "",
        "series": (series[0][1], text(series[0][2])) if series else None,
        "series_index": position,
        "publisher": (publishers[0][1], text(publishers[0][2])) if publishers else None,
        "published_at": direct_library.publication_date(row["pubdate"]),
        "added_at": text(row["added"]),
        "authors": [
            (value[1], text(value[2]), value[3]) for value in read["authors"].get(book_id, [])
        ],
        "languages": [(value[1], text(value[2])) for value in read["languages"].get(book_id, [])],
        "identifiers": [
            (text(value[1]), text(value[2])) for value in read["identifiers"].get(book_id, [])
        ],
        "formats": [
            {"id": value["id"], **direct_library.format_entry(value)}
            for value in read["formats"].get(book_id, [])
        ],
        "cover": None,
    }


def observe() -> tuple[dict, bool, list[dict]]:
    with direct_library.snapshot(seconds=OBSERVE_SECONDS) as (db, _, info):
        if not info["library_uuid"]:
            raise ReadModelError("A recorded library UUID is required for the read model")
        has_added = direct_library.has_added(db)
        read = read_catalogue(db)
        books = []
        for row in read["books"]:
            try:
                books.append(book_record(row, read))
            except (ValueError, TypeError, OverflowError, DirectLibraryError) as error:
                raise ReadModelError(
                    f"Calibre book {row['id']} cannot be represented in the read model"
                ) from error
    return info, has_added, books


# Facts about files, recorded once. A file or cover whose stat signature is unchanged keeps
# what an earlier import learned, so a metadata edit does not reread the whole share.


def file_facts(root: int, book: dict, known: dict) -> tuple[int, int]:
    """Mirrors direct_library.book_files, keeping signatures so later imports can reuse work.

    Returns how many stat calls and cover header reads this book sent to the share.
    """
    stats = reads = 0
    for entry in book["formats"]:
        entry.update(size_bytes=None, available=False, signature=None, sha256=None)
    book["cover_signature"] = None
    try:
        with direct_library.folder(root, direct_library.components(book["path"])) as parent:
            for entry in book["formats"]:
                stats += 1
                info = direct_library.file_stat(parent, entry["name"])
                if info is None:
                    continue
                entry.update(size_bytes=info.st_size, available=True, signature=signed(info))
                entry["sha256"] = known.get(
                    ("file", book["path"], entry["name"], entry["signature"])
                )
            stats += 1
            info = direct_library.file_stat(parent, "cover.jpg")
            if info is None:
                return stats, reads
            book["cover_signature"] = signed(info)
            key = ("cover", book["path"], book["cover_signature"])
            if key in known:
                book["cover"] = known[key]
                return stats, reads
            reads += 1
            try:
                book["cover"] = direct_library.cover_info(parent)
            except OSError, ValueError, TypeError:
                pass
    except OSError, ValueError, TypeError:
        pass
    return stats, reads


def known_facts() -> dict:
    known: dict = {}
    for path, name, signature, digest in CalibreFormat.objects.filter(
        signature__isnull=False, sha256__isnull=False
    ).values_list("book__path", "name", "signature", "sha256"):
        if digest:
            known["file", path, name, signature] = digest
    for path, signature, media_type, width, height in CalibreBook.objects.filter(
        cover_signature__isnull=False
    ).values_list("path", "cover_signature", "cover_media_type", "cover_width", "cover_height"):
        known["cover", path, signature] = (
            {"media_type": media_type, "width": width, "height": height} if media_type else None
        )
    return known


def observe_files(books: list[dict], known: dict) -> dict:
    """Observe every book's files; returns the stat calls and cover reads sent to the share."""
    with (
        direct_library.directory() as root,
        ThreadPoolExecutor(max_workers=direct_library.PROBES) as pool,
    ):
        counted = list(pool.map(lambda book: file_facts(root, book, known), books))
    return {
        "stats": sum(stats for stats, _ in counted),
        "covers_read": sum(reads for _, reads in counted),
    }


@transaction.atomic
def store(info: dict, has_added: bool, books: list[dict]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK])
        for model in (
            CalibreBookAuthor,
            CalibreBookLanguage,
            CalibreIdentifier,
            CalibreFormat,
            CalibreBook,
            CalibreAuthor,
            CalibreSeries,
            CalibrePublisher,
            CalibreLanguage,
        ):
            cursor.execute(f"DELETE FROM {connection.ops.quote_name(model._meta.db_table)}")
    authors: dict[int, CalibreAuthor] = {}
    series: dict[int, CalibreSeries] = {}
    publishers: dict[int, CalibrePublisher] = {}
    languages: dict[int, CalibreLanguage] = {}
    for book in books:
        for author_id, name, lowered in book["authors"]:
            authors[author_id] = CalibreAuthor(calibre_id=author_id, name=name, name_lower=lowered)
        if book["series"]:
            series[book["series"][0]] = CalibreSeries(*book["series"])
        if book["publisher"]:
            publishers[book["publisher"][0]] = CalibrePublisher(*book["publisher"])
        for language_id, code in book["languages"]:
            languages[language_id] = CalibreLanguage(calibre_id=language_id, lang_code=code)
    CalibreAuthor.objects.bulk_create(authors.values(), batch_size=1000)
    CalibreSeries.objects.bulk_create(series.values(), batch_size=1000)
    CalibrePublisher.objects.bulk_create(publishers.values(), batch_size=1000)
    CalibreLanguage.objects.bulk_create(languages.values(), batch_size=1000)
    CalibreBook.objects.bulk_create(
        (
            CalibreBook(
                calibre_id=book["id"],
                uuid=book["uuid"],
                title=book["title"],
                title_lower=book["title_lower"],
                sort=book["sort"],
                path=book["path"],
                series_id=book["series"][0] if book["series"] else None,
                series_index=book["series_index"],
                publisher_id=book["publisher"][0] if book["publisher"] else None,
                published_at=book["published_at"],
                added_at=book["added_at"],
                cover_media_type=book["cover"]["media_type"] if book["cover"] else None,
                cover_width=book["cover"]["width"] if book["cover"] else None,
                cover_height=book["cover"]["height"] if book["cover"] else None,
                cover_signature=book["cover_signature"],
            )
            for book in books
        ),
        batch_size=1000,
    )
    CalibreBookAuthor.objects.bulk_create(
        (
            CalibreBookAuthor(book_id=book["id"], author_id=value[0], position=position)
            for book in books
            for position, value in enumerate(book["authors"])
        ),
        batch_size=1000,
    )
    CalibreBookLanguage.objects.bulk_create(
        (
            CalibreBookLanguage(book_id=book["id"], language_id=value[0], position=position)
            for book in books
            for position, value in enumerate(book["languages"])
        ),
        batch_size=1000,
    )
    CalibreIdentifier.objects.bulk_create(
        (
            CalibreIdentifier(book_id=book["id"], position=position, type=kind, value=value)
            for book in books
            for position, (kind, value) in enumerate(book["identifiers"])
        ),
        batch_size=1000,
    )
    CalibreFormat.objects.bulk_create(
        (
            CalibreFormat(
                calibre_id=entry["id"],
                book_id=book["id"],
                position=position,
                format=entry["format"],
                name=entry["name"],
                recorded_size=entry["recorded_size_bytes"],
                size=entry["size_bytes"],
                signature=entry["signature"],
                sha256=entry["sha256"],
            )
            for book in books
            for position, entry in enumerate(book["formats"])
        ),
        batch_size=1000,
    )
    now = datetime.now(UTC)
    LibraryReadModel.objects.update_or_create(
        pk=1,
        defaults={
            "root": settings.DIRECT_LIBRARY_ROOT,
            "library_uuid": info["library_uuid"],
            "token": info["token"],
            "has_added": has_added,
            "books": len(books),
            "imported_at": now,
            "observed_at": now,
            "stale": False,
            "error": "",
        },
    )


@contextmanager
def importing():
    """Only one process imports at a time; others skip rather than queue."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK + 1])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK + 1])


def current_token() -> str:
    with direct_library.directory() as root:
        return direct_library.token_of(
            direct_library.state(root, time.monotonic() + OBSERVE_SECONDS)
        )


def refresh(force: bool = False) -> dict:
    """Import the library if its inventory token moved since the last import."""
    with importing() as acquired:
        if not acquired:
            return {"imported": False, "busy": True}
        model = LibraryReadModel.objects.filter(pk=1).first()
        try:
            token = current_token()
            if (
                not force
                and model is not None
                and model.token == token
                and model.root == settings.DIRECT_LIBRARY_ROOT
            ):
                LibraryReadModel.objects.filter(pk=1, token=token).update(
                    observed_at=datetime.now(UTC), stale=False, error=""
                )
                return {"imported": False, "token": token, "books": model.books}
            # Calibre moved on; serve the direct reader until the new import is complete.
            started = time.monotonic()
            LibraryReadModel.objects.filter(pk=1).update(stale=True)
            known = known_facts()
            info, has_added, books = observe()
            work = observe_files(books, known)
            # File facts were gathered outside the metadata fence; confirm it still holds.
            with direct_library.snapshot(info["token"], seconds=OBSERVE_SECONDS):
                pass
        except ReadModelError as error:
            fail(str(error))
            raise
        except FAILURES as error:
            message = str(error) if isinstance(error, DirectLibraryError) else type(error).__name__
            fail(message)
            raise ReadModelError(message) from error
        store(info, has_added, books)
        seconds = round(time.monotonic() - started, 1)
        logger.info(
            "library_read_model_imported books=%s seconds=%s stats=%s covers_read=%s",
            len(books),
            seconds,
            work["stats"],
            work["covers_read"],
        )
        return {
            "imported": True,
            "token": info["token"],
            "library_uuid": info["library_uuid"],
            "books": len(books),
            "seconds": seconds,
            **work,
        }


def fail(message: str) -> None:
    LibraryReadModel.objects.update_or_create(
        pk=1, defaults={"stale": True, "error": message[:2000]}
    )
    logger.warning("library_read_model_refresh_failed %s", message)


class Interrupted(Exception):
    """The hashing slice ran out; the file stays pending for a later slice."""


def digest(parent: int, name: str, expected: str, deadline: float) -> str:
    with direct_library.file_in(parent, name) as (stream, before):
        if signed(before) != expected:
            raise ValueError
        value = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            if time.monotonic() > deadline:
                raise Interrupted
            value.update(chunk)
        if signed(os.fstat(stream.fileno())) != expected:
            raise ValueError
    return value.hexdigest()


def hash_pending(seconds: float = HASH_SECONDS) -> int:
    """Hash recorded files not yet hashed, within a time budget; later ticks continue.

    Smallest files go first so one large file cannot hold back the rest. A file too large
    for any worker slice waits for `library_read_model refresh --hash-seconds N`.
    """
    deadline = time.monotonic() + seconds
    pending = list(
        CalibreFormat.objects.filter(sha256__isnull=True, signature__isnull=False)
        .select_related("book")
        .order_by("size", "calibre_id")[:HASH_BATCH]
    )
    hashed = 0
    if not pending:
        return hashed
    with direct_library.directory() as root:
        for entry in pending:
            if time.monotonic() > deadline:
                break
            try:
                parts = direct_library.components(entry.book.path)
                with direct_library.folder(root, parts) as parent:
                    value = digest(parent, entry.name, entry.signature or "", deadline)
            except Interrupted:
                break
            except OSError, ValueError, TypeError:
                # The file moved or changed since import; the next import observes it again.
                value = ""
            hashed += CalibreFormat.objects.filter(
                pk=entry.pk, signature=entry.signature, sha256__isnull=True
            ).update(sha256=value)
    if hashed:
        logger.info("library_read_model_hashed files=%s", hashed)
    return hashed


_next_tick = 0.0


def tick(*, raise_errors=False) -> bool:
    """Refresh at most once per interval; optionally propagate recorded import failures."""
    global _next_tick
    if settings.LIBRARY_READ_MODEL == "off" or not settings.DIRECT_LIBRARY_ROOT:
        return False
    now = time.monotonic()
    if now < _next_tick:
        return False
    _next_tick = now + settings.LIBRARY_READ_MODEL_SECONDS
    try:
        refresh()
        hash_pending()
    except ReadModelError:
        if raise_errors:
            raise
    except DatabaseError:
        raise
    except Exception:
        logger.exception("library_read_model_tick_failed")
    return True


# Serving. Each answer reads one consistent Postgres snapshot of the imported rows.


def serving() -> bool:
    return settings.LIBRARY_READ_MODEL == "serve" and bool(settings.DIRECT_LIBRARY_ROOT)


def current() -> LibraryReadModel | None:
    if not serving():
        return None
    model = LibraryReadModel.objects.filter(pk=1).first()
    if (
        model is None
        or not model.token
        or model.stale
        or model.root != settings.DIRECT_LIBRARY_ROOT
    ):
        return None
    return model


def refused(token: str) -> None:
    """The direct reader refused the model's token: Calibre changed, so stop serving it."""
    if not token or settings.LIBRARY_READ_MODEL == "off":
        return
    try:
        LibraryReadModel.objects.filter(pk=1, token=token, stale=False).update(stale=True)
    except DatabaseError:
        logger.exception("library_read_model_stale_mark_failed")


@contextmanager
def consistent():
    outermost = not connection.in_atomic_block
    with transaction.atomic():
        if outermost:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield


def inventory(model: LibraryReadModel) -> dict:
    return {
        "token": model.token,
        "observed_at": model.observed_at.isoformat() if model.observed_at else None,
        "scope": "metadata",
        "library_uuid": model.library_uuid,
    }


def nocase(field: str) -> Func:
    """Calibre declares sort and name columns NOCASE: SQLite folds ASCII case, then compares bytes."""
    return Func(
        F(field),
        Value("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        Value("abcdefghijklmnopqrstuvwxyz"),
        function="TRANSLATE",
        output_field=TextField(),
    )


def title_order():
    # SQLite puts NULL first; Postgres needs that and the bytewise comparison spelled out.
    return (Collate(nocase("sort"), "C").asc(nulls_first=True), F("calibre_id").asc())


def recent_order(has_added: bool):
    if not has_added:
        return (F("calibre_id").desc(),)
    return (Collate("added_at", "C").desc(nulls_last=True), F("calibre_id").desc())


def series_order():
    return (
        F("series_index").asc(nulls_last=True),
        Collate(nocase("sort"), "C").asc(nulls_first=True),
        F("calibre_id").asc(),
    )


def entries(books, token: str) -> list[dict]:
    books = books.select_related("series", "publisher").prefetch_related(
        Prefetch(
            "author_links",
            queryset=CalibreBookAuthor.objects.select_related("author").order_by("position"),
        ),
        Prefetch(
            "language_links",
            queryset=CalibreBookLanguage.objects.select_related("language").order_by("position"),
        ),
        Prefetch("identifiers", queryset=CalibreIdentifier.objects.order_by("position")),
        Prefetch("formats", queryset=CalibreFormat.objects.order_by("position")),
    )
    return [project(book, token) for book in books]


def project(book: CalibreBook, token: str) -> dict:
    """The listing shape of direct_library.project(), key for key."""
    book_id = str(book.calibre_id)
    cover = None
    if book.cover_media_type:
        cover = {
            "media_type": book.cover_media_type,
            "width": book.cover_width,
            "height": book.cover_height,
            "url": direct_library.cover_url(book_id, token),
        }
    return {
        "id": book_id,
        "uuid": book.uuid,
        "title": book.title,
        "authors": [link.author.name for link in book.author_links.all()],
        "series": book.series.name if book.series else None,
        "series_index": book.series_index if book.series else None,
        "publisher": book.publisher.name if book.publisher else None,
        "published_at": book.published_at,
        "added_at": book.added_at,
        "languages": [link.language.lang_code for link in book.language_links.all()],
        "identifiers": [
            {"type": item.type, "value": item.value} for item in book.identifiers.all()
        ],
        "formats": [
            {
                "format": item.format,
                "name": item.name,
                "size_bytes": item.size,
                "recorded_size_bytes": item.recorded_size,
                "available": item.size is not None,
            }
            for item in book.formats.all()
        ],
        "cover": cover,
    }


def browse(query="", page=1, inventory_token="", order="") -> dict | None:
    """direct_library.browse() from the read model, or None when the model cannot serve."""
    direct_library.check_browse(query, page, order)
    direct_library.check_token(inventory_token)
    if not serving():
        return None
    with consistent():
        model = current()
        if model is None:
            return None
        if inventory_token and inventory_token != model.token:
            raise direct_library.changed()
        books = CalibreBook.objects.all()
        if query:
            folded = sqlite_lower(query)
            books = books.alias(found=StrIndex("title_lower", Value(folded))).filter(
                Q(found__gt=0)
                | Exists(
                    CalibreBookAuthor.objects.filter(book=OuterRef("pk"))
                    .alias(found=StrIndex("author__name_lower", Value(folded)))
                    .filter(found__gt=0)
                )
            )
        count = books.count()
        size = direct_library.PAGE_SIZE
        start = (page - 1) * size
        ordering = recent_order(model.has_added) if order == "recent" else title_order()
        return {
            "configured": True,
            "source": "calibre",
            "read_only": True,
            "inventory": inventory(model),
            "total": count,
            "page": page,
            "pages": max(1, math.ceil(count / size)),
            "page_size": size,
            "books": entries(books.order_by(*ordering)[start : start + size], model.token),
        }


def series(name: str, inventory_token="") -> dict | None:
    """direct_library.series() from the read model, or None when the model cannot serve."""
    direct_library.check_series(name)
    direct_library.check_token(inventory_token)
    if not serving():
        return None
    with consistent():
        model = current()
        if model is None:
            return None
        if inventory_token and inventory_token != model.token:
            raise direct_library.changed()
        books = (
            CalibreBook.objects.alias(series_key=nocase("series__name"))
            .filter(series_key=sqlite_lower(name))
            .order_by(*series_order())
        )
        return {
            "source": "calibre",
            "read_only": True,
            "inventory": inventory(model),
            "books": entries(books[: direct_library.SERIES_LIMIT], model.token),
        }


# Parity: the read model against the direct reader, for every book and both orders.


def parity() -> dict:
    # Imported here: reconciliation reaches the views, which import this module.
    from librarium import library_reconciliation

    model = LibraryReadModel.objects.filter(pk=1).exclude(token="").first()
    if model is None:
        raise ReadModelError("No complete read model has been imported yet")
    try:
        with direct_library.snapshot(seconds=OBSERVE_SECONDS) as (db, root, info):
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM books ORDER BY id LIMIT ?", (MAX_BOOKS + 1,)
                ).fetchall()
            ]
            if len(ids) > MAX_BOOKS:
                raise ReadModelError("The library exceeds the read model's book limit")
            direct = direct_library.with_files(
                root, [direct_library.entry(db, root, book_id, info) for book_id in ids], info
            )
            title = [str(row[0]) for row in db.execute("SELECT id FROM books ORDER BY sort,id")]
            recent = [
                str(row[0])
                for row in db.execute(
                    "SELECT id FROM books ORDER BY timestamp DESC,id DESC"
                    if direct_library.has_added(db)
                    else "SELECT id FROM books ORDER BY id DESC"
                )
            ]
    except FAILURES as error:
        raise ReadModelError(str(error)) from error
    with consistent():
        served = entries(CalibreBook.objects.order_by("calibre_id"), model.token)

        def ids_by(ordering):
            return [
                str(value)
                for value in CalibreBook.objects.order_by(*ordering).values_list(
                    "calibre_id", flat=True
                )
            ]

        order = {
            "title": ids_by(title_order()) == title,
            "recent": ids_by(recent_order(model.has_added)) == recent,
        }
    old = {book["id"]: book for book in direct}
    new = {book["id"]: book for book in served}
    changes = library_reconciliation.compare(old, new)
    differences = {
        key: [field for field in old[key] if old[key][field] != new[key].get(field)]
        for key in sorted(old.keys() & new.keys(), key=int)
        if old[key] != new[key]
    }
    current_model = (model.token, model.library_uuid) == (info["token"], info["library_uuid"])
    return {
        "parity": current_model and not any(changes.values()) and all(order.values()),
        "current": current_model,
        "inventory": {key: value for key, value in info.items() if key != "observed_at"},
        "model": {
            "token": model.token,
            "imported_at": model.imported_at.isoformat() if model.imported_at else None,
            "stale": model.stale,
        },
        "books": len(old),
        "changes": changes,
        "differences": differences,
        "order": order,
    }
