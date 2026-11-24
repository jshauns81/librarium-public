"""Retained deterministic hashing and immutable snapshot-copy helpers.

The native facade stages explicit versions; its caller owns current-pointer
publication. Incumbent pointer replacement and retention deletion are excluded.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

RESOLVED_TABLES = (
    "author",
    "author_alias",
    "cover_derivative",
    "edition",
    "edition_ident",
    "field_support",
    "id_alias",
    "id_anchor",
    "record_link",
    "series",
    "work",
    "work_alias",
    "work_author",
    "work_contains",
    "work_cover",
    "work_ident",
    "work_series",
    "work_tag",
)


def resolved_hash(conn: sqlite3.Connection) -> str:
    """sha256 over the resolved tables' contents.

    Tables are visited in sorted name order and rows in ORDER BY of every column, so the
    result depends on the values only: not on rowids, insertion order or the evidence layer.
    """
    h = hashlib.sha256()
    for table in sorted(RESOLVED_TABLES):
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        if not cols:
            raise RuntimeError(f"resolved table missing: {table}")
        quoted = ", ".join(f'"{c}"' for c in cols)
        h.update(f"\x00table:{table}:{','.join(cols)}\n".encode())
        # Fetch as plain tuples whatever the connection's row_factory is.
        cur = conn.cursor()
        cur.row_factory = None
        for row in cur.execute(f'SELECT {quoted} FROM "{table}" ORDER BY {quoted}'):
            h.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())
            h.update(b"\n")
    return h.hexdigest()


def _copy_db(src: sqlite3.Connection, dest_path: Path) -> None:
    """Consistent copy of ``src`` into a fresh file at ``dest_path`` (SQLite backup API)."""
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        dest.close()


def _finalise_copy(tmp: Path, version: str) -> str:
    """Stamp the version into the copy and make it a self-contained file; return its hash."""
    dest = sqlite3.connect(tmp)
    try:
        with dest:
            dest.execute(
                "INSERT INTO meta (key, value) VALUES ('catalog_version', ?)"
                " ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                (version,),
            )
        # The live DB is WAL; a read-only snapshot must not need -wal/-shm sidecar files.
        mode = dest.execute("PRAGMA journal_mode=DELETE").fetchone()
        if mode is None or str(mode[0]).lower() != "delete":
            raise RuntimeError(f"could not switch snapshot to journal_mode=delete (got {mode!r})")
        return resolved_hash(dest)
    finally:
        dest.close()
