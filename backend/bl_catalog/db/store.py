"""SQLite connection and the append-only evidence store."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from bl_catalog.record import Record, hash_claims


def _schema() -> str:
    return resources.files("bl_catalog.db").joinpath("schema.sql").read_text(encoding="utf-8")


def connect(
    path: Path, readonly: bool = False, check_same_thread: bool = True, *, immutable: bool = False
) -> sqlite3.Connection:
    """Open the catalogue database.

    Read-write opens use WAL and (re)apply the idempotent schema. Read-only opens never
    write: no schema, no WAL switch. ``check_same_thread=False`` lets a connection move
    between threads: the API may release a pooled connection on a different worker thread
    than the one that acquired it, though no connection is ever used by two threads at once.

    ``immutable`` (read-only only) is for published snapshots, which never change after their
    rename. SQLite then skips the file locks and change checks it otherwise makes for every
    statement. On a FUSE filesystem each of those checks can require a round trip.
    """
    path = Path(path)
    if immutable and not readonly:
        raise ValueError("an immutable connection must be read-only")
    if readonly:
        flags = "mode=ro&immutable=1" if immutable else "mode=ro"
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?{flags}", uri=True, check_same_thread=check_same_thread
        )
    else:
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_schema())
    return conn


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class Evidence:
    """Append-only evidence: records are only ever added, and their content is never changed.
    The one deletion is ``prune_strays`` (other publishers' books an open title search found).

    Seeing identical content again only bumps that row's ``last_seen_at``. The *current*
    record for a (source, native_id) is therefore the row with the greatest ``last_seen_at``:
    if a source goes A -> B -> A, A's row is current again.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, rec: Record, seen_at: str | None = None) -> int | None:
        """Store a record and its claims. Returns the new record id, or None when a row with
        the same (source, native_id, content_hash) already exists (its last_seen_at is bumped).

        ``seen_at`` (an ISO timestamp from ``now_iso()``) stamps the row instead of the current
        time. Callers pass one stamp for every record of one page or query, so the records a
        fetch yields together share an identical ``last_seen_at``: the resolver relies on that
        to tell a page's latest records from leftovers of an earlier fetch."""
        claims = rec.to_claims()
        content_hash = hash_claims(claims)
        now = seen_at or now_iso()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO source_record"
                " (source, native_id, fetched_at, cache_ref, parsed_json, content_hash, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (source, native_id, content_hash) DO NOTHING",
                (
                    rec.source,
                    rec.native_id,
                    now,
                    rec.cache_ref,
                    json.dumps(rec.raw, sort_keys=True, ensure_ascii=False, default=str),
                    content_hash,
                    now,
                ),
            )
            if cur.rowcount == 0:
                self.conn.execute(
                    "UPDATE source_record SET last_seen_at=?"
                    " WHERE source=? AND native_id=? AND content_hash=?",
                    (now, rec.source, rec.native_id, content_hash),
                )
                return None
            record_id = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO claim (record_id, entity, field, value, value_norm)"
                " VALUES (?, ?, ?, ?, ?)",
                [(record_id, *c) for c in claims],
            )
        return record_id

    def log(self, source: str, query: str, status: str, http_status: int | None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO harvest_log (source, query, status, http_status, fetched_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (source, query, status, http_status, now_iso()),
            )

    def last_fetched(self, source: str, query: str) -> datetime | None:
        """When (source, query) last completed with status 'ok'; failed attempts don't count,
        so a resumable run retries them."""
        row = self.conn.execute(
            "SELECT max(fetched_at) FROM harvest_log WHERE source=? AND query=? AND status='ok'",
            (source, query),
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None


# Sources whose title search returns anyone's books. One of their records with no publisher, no
# ISBN any other source knows and no author any other source names is someone else's book
# ("Mercy" by Catherine Miller, found asking for the BL short story "Mercy").
OPEN_SEARCH_SOURCES = ("hardcover", "google")

_STRAYS = f"""
WITH known_isbn AS (
    SELECT cl.value_norm FROM claim cl JOIN source_record r ON r.id = cl.record_id
    WHERE cl.field = 'isbn13' AND r.source NOT IN {OPEN_SEARCH_SOURCES!r}),
known_author AS (
    SELECT cl.value_norm FROM claim cl JOIN source_record r ON r.id = cl.record_id
    WHERE cl.field = 'author' AND r.source NOT IN {OPEN_SEARCH_SOURCES!r})
SELECT r.id FROM source_record r
WHERE r.source IN {OPEN_SEARCH_SOURCES!r}
  AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.record_id = r.id AND c.field = 'publisher')
  AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.record_id = r.id AND c.field = 'isbn13'
                  AND c.value_norm IN (SELECT value_norm FROM known_isbn))
  AND NOT EXISTS (SELECT 1 FROM claim c WHERE c.record_id = r.id AND c.field = 'author'
                  AND c.value_norm IN (SELECT value_norm FROM known_author))
"""


def prune_strays(conn: sqlite3.Connection) -> int:
    """Delete stray records of the open-search sources (and their claims and links); return
    how many. Idempotent, and run before every rebuild so a stray never reaches the catalogue."""
    with conn:
        ids = [row[0] for row in conn.execute(_STRAYS)]
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ",".join("?" * len(chunk))
            conn.execute(f"DELETE FROM record_link WHERE record_id IN ({marks})", chunk)
            conn.execute(f"DELETE FROM claim WHERE record_id IN ({marks})", chunk)
            conn.execute(f"DELETE FROM source_record WHERE id IN ({marks})", chunk)
    return len(ids)
