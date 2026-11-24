"""Bounded offline entry points around the retained BLC catalogue engines.

Paths name caller-owned staging state. The caller owns filesystem admission,
serialization, generation receipts and the active-pointer commit. These helpers
never contact providers, open Calibre or select a published snapshot as current.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from bl_catalog.config import load_sources
from bl_catalog.db.store import Evidence, connect
from bl_catalog.publish import _copy_db, _finalise_copy, resolved_hash
from bl_catalog.record import Record
from bl_catalog.resolve.run import ROLES, WORK_TYPES, rebuild

ENGINE_REVISION = "a8f274487f09399a6fe90f4210bb50fc0c3a0701"
POLICY_VERSION = "librarium.reference-engine.v1"
PACKET_SCHEMA = "librarium.reference-packet.v1"
MAX_PACKET_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 1000
MAX_TEXT = 16384
MAX_RELATIONS = 64
MAX_CONTENTS = 128
MAX_DATABASE = 512 * 1024 * 1024
SQL_SECONDS = 60
VERSION = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]{0,8}\Z")
IDENT_KIND = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
RECORD_KEYS = {value.name for value in fields(Record)} - {"source"}
TEXT_FIELDS = RECORD_KEYS - {
    "raw",
    "authors",
    "series",
    "aliases",
    "tags",
    "contents",
    "contained_in",
    "work_ids",
    "edition_ids",
    "word_count",
    "pages",
    "runtime_minutes",
    "price",
    "in_print",
    "narrators",
}


class PacketError(ValueError):
    """An unsupported packet is refused before opening writable evidence state."""


def _text(value, maximum=MAX_TEXT, *, empty=True):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or "\x00" in value
        or (not empty and not value.strip())
    ):
        raise PacketError("Reference text exceeds its limit or has an invalid type")
    return value


def _tree(value, depth=0, budget=None):
    budget = [100000] if budget is None else budget
    budget[0] -= 1
    if depth > 12 or budget[0] < 0:
        raise PacketError("Reference packet structure exceeds its limit")
    if value is None or type(value) in {bool, int}:
        if type(value) is int and abs(value) > 2**63 - 1:
            raise PacketError("Reference integer exceeds its limit")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise PacketError("Reference numbers must be finite")
        return
    if isinstance(value, str):
        _text(value, 100000)
        return
    if isinstance(value, list):
        for item in value:
            _tree(item, depth + 1, budget)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _text(key, 256)
            _tree(item, depth + 1, budget)
        return
    raise PacketError("Reference packets must contain JSON values")


def _list(value, maximum=MAX_RELATIONS):
    if not isinstance(value, list) or len(value) > maximum:
        raise PacketError("Reference metadata relationships exceed their limit")
    return value


def _number(value):
    if type(value) not in {int, float} or not math.isfinite(value) or abs(value) > 10**9:
        raise PacketError("Reference numeric metadata is invalid")


def _validate_record(record):
    if not isinstance(record, dict) or set(record) - RECORD_KEYS:
        raise PacketError("Reference record contains unsupported fields")
    _text(record.get("native_id"), 512, empty=False)
    if "raw" in record and not isinstance(record["raw"], dict):
        raise PacketError("Reference raw provenance must be an object")
    for name in TEXT_FIELDS:
        if record.get(name) is not None:
            _text(record[name], 512 if name == "native_id" else MAX_TEXT)
    if record.get("type") is not None and record["type"] not in WORK_TYPES:
        raise PacketError("Reference work type is unsupported")
    for name in ("authors", "series", "tags"):
        for pair in _list(record.get(name, [])):
            if not isinstance(pair, list) or len(pair) != 2:
                raise PacketError("Reference relationships must contain two values")
            _text(pair[0], 512, empty=False)
            if name == "series":
                if pair[1] is not None:
                    _number(pair[1])
            else:
                _text(pair[1], 512, empty=False)
                if name == "authors" and pair[1] not in ROLES:
                    raise PacketError("Reference author role is unsupported")
    for name in ("aliases", "contained_in", "narrators"):
        for value in _list(record.get(name, [])):
            _text(value, 512, empty=False)
    for name in ("work_ids", "edition_ids"):
        mapping = record.get(name, {})
        if not isinstance(mapping, dict) or len(mapping) > MAX_RELATIONS:
            raise PacketError("Reference identifier relationships exceed their limit")
        for kind, value in mapping.items():
            if not IDENT_KIND.fullmatch(kind):
                raise PacketError("Reference identifier kind is unsupported")
            _text(value, 512, empty=False)
    for name in ("word_count", "pages", "runtime_minutes"):
        value = record.get(name)
        if value is not None and (type(value) is not int or not 0 <= value <= 10**9):
            raise PacketError("Reference numeric metadata is invalid")
    if record.get("price") is not None:
        _number(record["price"])
        if record["price"] < 0:
            raise PacketError("Reference price cannot be negative")
    if record.get("in_print") is not None and type(record["in_print"]) is not bool:
        raise PacketError("Reference print availability must be a boolean")
    for item in _list(record.get("contents", []), MAX_CONTENTS):
        if not isinstance(item, dict) or set(item) - {"title", "authors", "type", "position"}:
            raise PacketError("Reference contents entries contain unsupported fields")
        _text(item.get("title"), MAX_TEXT, empty=False)
        for name in _list(item.get("authors", [])):
            _text(name, 512, empty=False)
        if item.get("type") is not None:
            _text(item["type"], 512, empty=False)
            if item["type"] not in WORK_TYPES:
                raise PacketError("Reference contents type is unsupported")
        if item.get("position") is not None:
            _number(item["position"])


def validate_packet(packet):
    """Return an isolated, validated JSON packet with a canonical UTC observation."""
    if not isinstance(packet, dict) or set(packet) != {
        "schema",
        "source",
        "observed_at",
        "records",
    }:
        raise PacketError("Use a reference packet with schema, source, observed_at and records")
    _tree(packet)
    try:
        raw = json.dumps(packet, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as error:
        raise PacketError("Reference packet cannot be encoded safely") from error
    if len(raw) > MAX_PACKET_BYTES:
        raise PacketError("Reference packet exceeds the 4 MiB limit")
    value = json.loads(raw)
    if (
        value["schema"] != PACKET_SCHEMA
        or not isinstance(value["source"], str)
        or value["source"] not in load_sources()
    ):
        raise PacketError("Reference packet schema or source is unsupported")
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        offset = observed.utcoffset()
        if observed.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise PacketError("Reference observation must be an ISO UTC timestamp") from error
    value["observed_at"] = observed.astimezone(UTC).isoformat(timespec="microseconds")
    records = _list(value["records"], MAX_RECORDS)
    if not records:
        raise PacketError("Reference packet must contain records")
    seen = set()
    for record in records:
        _validate_record(record)
        if record["native_id"] in seen:
            raise PacketError("A reference packet cannot repeat one native record ID")
        seen.add(record["native_id"])
    return value


@contextmanager
def _database(path, *, readonly=False):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DATABASE:
        raise ValueError("Use a bounded regular staging database")
    with closing(connect(path, readonly=readonly)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
        deadline = time.monotonic() + SQL_SECONDS
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        yield db


def init_database(path):
    """Initialize caller-owned staging state with the retained complete BLC schema."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError("The staging database already exists")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    with _database(path) as db, db:
        db.executemany(
            "INSERT INTO source(name,origin_group,priority) VALUES(?,?,?)",
            [
                (source.name, source.origin_group, source.priority)
                for source in load_sources().values()
            ],
        )


def apply_packet(path, packet):
    """Retain source history and refresh existing observations without clock regression."""
    value = validate_packet(packet)
    added = 0
    with _database(path) as db:
        evidence = Evidence(db)
        for payload in value["records"]:
            record = Record(source=value["source"], **payload)
            held = db.execute(
                "SELECT last_seen_at FROM source_record WHERE source=? AND native_id=? AND content_hash=?",
                (record.source, record.native_id, record.content_hash()),
            ).fetchone()
            seen_at = max(value["observed_at"], held[0]) if held else value["observed_at"]
            added += evidence.add(record, seen_at=seen_at) is not None
        with db:
            db.execute(
                "INSERT INTO harvest_log(source,query,status,http_status,fetched_at) VALUES(?,?,'imported',NULL,?)",
                (value["source"], "offline reference packet", value["observed_at"]),
            )
    if Path(path).stat().st_size > MAX_DATABASE:
        raise ValueError("The staged reference database exceeds its size limit")
    return {
        "source": value["source"],
        "observed_at": value["observed_at"],
        "records": len(value["records"]),
        "added": added,
        "refreshed": len(value["records"]) - added,
    }


def rebuild_database(path):
    """Run the retained transactional resolver; anchors and aliases are never rebuilt away."""
    with _database(path) as db:
        report = asdict(rebuild(db))
        report["resolved_sha256"] = resolved_hash(db)
    if Path(path).stat().st_size > MAX_DATABASE:
        raise ValueError("The staged reference database exceeds its size limit")
    return report


def _valid_version(version):
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("Use a dated catalogue version with a positive serial")
    datetime.strptime(version[:10], "%Y.%m.%d")


def stage_snapshot(path, outdir: Path | int, version):
    """Stage a snapshot in a directory or held directory fd; never select it as current."""
    _valid_version(version)
    if isinstance(outdir, int):
        if type(outdir) is not int:
            raise ValueError("Use a held directory descriptor")
        directory = os.dup(outdir)
    else:
        outdir = Path(outdir)
        if outdir.is_symlink() or not outdir.is_dir():
            raise ValueError("Use a caller-owned staging publication directory")
        directory = os.open(outdir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISDIR(os.fstat(directory).st_mode):
            raise ValueError("The staging descriptor must name a directory")
        return _stage_at(path, directory, version)
    finally:
        os.close(directory)


def _stage_at(path, directory, version):
    outdir = Path("/proc/self/fd") / str(directory)
    final = outdir / f"{version}.sqlite"
    if final.exists() or final.is_symlink():
        raise FileExistsError("This staged catalogue version is already reserved")
    temporary = outdir / f".snapshot-{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    try:
        with _database(path, readonly=True) as db:
            _copy_db(db, temporary)
        resolved = _finalise_copy(temporary, version)
        with closing(sqlite3.connect(temporary)) as snapshot, snapshot:
            snapshot.executemany(
                "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [
                    ("librarium_engine_revision", ENGINE_REVISION),
                    ("librarium_engine_policy", POLICY_VERSION),
                ],
            )
        size = temporary.stat().st_size
        if size > MAX_DATABASE or not stat.S_ISREG(temporary.stat().st_mode):
            raise ValueError("The staged snapshot exceeds its size limit")
        with temporary.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
        temporary.chmod(0o444)
        os.link(temporary, final, follow_symlinks=False)
        os.fsync(directory)
        return {
            "version": version,
            "sha256": digest,
            "size_bytes": size,
            "resolved_sha256": resolved,
        }
    finally:
        for candidate in (
            temporary,
            Path(str(temporary) + "-journal"),
            Path(str(temporary) + "-wal"),
            Path(str(temporary) + "-shm"),
        ):
            candidate.unlink(missing_ok=True)
