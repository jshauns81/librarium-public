"""Retained pure projection of existing cover assets; no downloads or image library."""

import html
import json
import logging
import re
import sqlite3
import unicodedata
from urllib.parse import quote

from bl_catalog.resolve.editions import current_records
from bl_catalog.sources.lexicanum import WIKIS

log = logging.getLogger(__name__)


def lexicanum_cover_url(raw: dict) -> str | None:
    """An original-file redirect derived only from a known wiki and an image filename."""
    if not isinstance(raw, dict) or raw.get("wiki") not in WIKIS:
        return None
    fields = raw.get("fields")
    value = fields.get("image") if isinstance(fields, dict) else None
    if not isinstance(value, str):
        return None
    filename = html.unescape(value).strip()
    if filename.startswith("[[") and filename.endswith("]]"):
        filename = filename[2:-2].split("|", 1)[0].strip()
    filename = re.sub(r"^(?:File|Image)\s*:\s*", "", filename, flags=re.IGNORECASE)
    if (
        not filename
        or len(filename) > 255
        or filename in {".", ".."}
        or any(char in filename for char in "/\\:#?[]{}|<>")
        or any(unicodedata.category(char).startswith("C") for char in filename)
    ):
        return None
    filename = filename.replace(" ", "_")
    return f"https://{raw['wiki']}.lexicanum.com/wiki/Special:FilePath/{quote(filename, safe='')}"


def _current_cover_records(conn: sqlite3.Connection) -> dict[int, str]:
    current = current_records(conn)
    out = {}
    for rid, parsed in conn.execute(
        "SELECT id, parsed_json FROM source_record WHERE source='lexicanum' ORDER BY id"
    ):
        if rid not in current:
            continue
        try:
            source_url = lexicanum_cover_url(json.loads(parsed))
        except TypeError, ValueError:
            log.warning("invalid stored Lexicanum raw data on record %s", rid)
            continue
        if source_url:
            out[rid] = source_url
    return out


def rebuild_work_covers(conn: sqlite3.Connection) -> None:
    """Choose the widest available cover of each work's current Lexicanum records.

    This writes inside the caller's resolver transaction and never commits it. Stored assets
    are retained independently of resolved work IDs, so merges and rebuilds preserve files.
    """
    records = _current_cover_records(conn)
    assets = {
        row[0]: tuple(row)
        for row in conn.execute(
            "SELECT source_url, sha256, width, height, media_type FROM cover_asset"
        )
    }
    chosen: dict[str, tuple] = {}
    for rid, work_id in conn.execute(
        "SELECT record_id, entity_id FROM record_link WHERE entity='work' ORDER BY record_id"
    ):
        asset = assets.get(records.get(rid))
        if asset is None:
            continue
        held = chosen.get(work_id)
        # Source URL breaks equal-size ties consistently across runs.
        if held is None or (-asset[2], -asset[3], asset[0]) < (-held[2], -held[3], held[0]):
            chosen[work_id] = asset
    conn.execute("DELETE FROM work_cover")
    conn.executemany(
        "INSERT INTO work_cover (work_id, source_url, sha256, width, height, media_type)"
        " VALUES (?,?,?,?,?,?)",
        [(work_id, *asset) for work_id, asset in sorted(chosen.items())],
    )
