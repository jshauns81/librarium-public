"""Idle-worker replication of published snapshots and their exact cover bytes."""

import fcntl
import hashlib
import http.client
import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

from django.conf import settings

from librarium import catalogue, catalogue_covers, catalogue_status
from librarium.library import WORK

BATCH_SIZE = 32
BUDGET_SECONDS = 10
SLICE_INTERVAL = 1
POLL_SECONDS = 60
RETRY_SECONDS = 60
MAX_SNAPSHOT = 512 * 1024 * 1024
MAX_STATE = 32 * 1024 * 1024
MAX_COVERS = 100_000
RETAIN = 3
STATE = ".catalogue-sync.json"
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class SliceExpired(Exception):
    pass


def version_key(value: str) -> tuple[int, ...]:
    return tuple(map(int, value.split(".")))


def configuration_key() -> str:
    return hashlib.sha256(
        json.dumps(
            [
                settings.LIBRARIUM_CATALOGUE_STATUS_URL,
                settings.LIBRARIUM_CATALOGUE_COVER_DIR,
                settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR,
            ]
        ).encode()
    ).hexdigest()


def load(directory: Path) -> dict:
    try:
        fd = os.open(directory / STATE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE:
                raise ValueError("Invalid sync state")
            value = json.loads(stream.read(MAX_STATE + 1))
        if not isinstance(value, dict) or value.get("key") != configuration_key():
            return {}
        return value
    except FileNotFoundError:
        return {}


def saved() -> dict:
    """Read the worker's progress without fetching or admitting any cover in web."""
    if not settings.LIBRARIUM_CATALOGUE_DIR:
        return {"state": "unavailable"}
    try:
        value = load(Path(settings.LIBRARIUM_CATALOGUE_DIR))
        return {
            k: v
            for k, v in value.items()
            if k
            in {
                "state",
                "phase",
                "version",
                "verified",
                "total",
                "failure",
                "updated_at",
                "served_version",
                "served_verified",
                "served_total",
                "published_version",
                "published_created_at",
                "completed_at",
            }
        } or {"state": "unavailable"}
    except OSError, ValueError, TypeError:
        return {"state": "unavailable"}


def atomic(fd: int, name: str, raw: bytes, mode: int = 0o644):
    temporary = ".sync-write"
    try:
        os.unlink(temporary, dir_fd=fd)
    except FileNotFoundError:
        pass
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


@contextmanager
def storage():
    root = Path(settings.LIBRARIUM_CATALOGUE_DIR)
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("Invalid catalogue storage")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    for name in ("LIBRARIUM_ARTIFACT_DIR", "DIRECT_LIBRARY_ROOT", "LIBRARIUM_REFERENCE_STATE_DIR"):
        value = getattr(settings, name, "")
        if value:
            other = Path(value).resolve()
            if root == other or root in other.parents or other in root.parents:
                raise ValueError("Overlapping catalogue storage")
    dirs = [
        Path(settings.LIBRARIUM_CATALOGUE_COVER_DIR),
        Path(settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR),
    ]
    for directory in dirs:
        relative = directory.relative_to(root)
        if not relative.parts or ".." in relative.parts:
            raise ValueError("Cover storage must be inside catalogue storage")
        fd = os.open(root, DIR_FLAGS)
        try:
            for component in relative.parts:
                try:
                    os.mkdir(component, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(component, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
        finally:
            os.close(fd)
    if dirs[0] == dirs[1] or dirs[0] in dirs[1].parents or dirs[1] in dirs[0].parents:
        raise ValueError("Cover variants need separate directories")
    fd = os.open(root, DIR_FLAGS)
    try:
        lock = os.open(
            ".catalogue-sync.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=fd,
        )
        try:
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Invalid sync lock")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield root, None
            else:
                yield root, fd
        finally:
            os.close(lock)
    finally:
        os.close(fd)


def download(url: str, stream, limit: int, deadline: float, media_types: set[str]):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SliceExpired
    with catalogue_status.open_url(Request(url, method="GET"), timeout=min(5, remaining)) as reply:
        if (
            reply.status != 200
            or reply.headers.get("Content-Type", "").split(";")[0].strip().lower()
            not in media_types
        ):
            raise ValueError("Unexpected download response")
        length = reply.headers.get("Content-Length")
        if length is not None and not 0 < int(length) <= limit:
            raise ValueError("Download exceeds size limit")
        size = 0
        while chunk := reply.read1(min(65536, limit + 1 - size)):
            size += len(chunk)
            if time.monotonic() >= deadline:
                raise SliceExpired
            if size > limit:
                raise ValueError("Download exceeded size limit")
            stream.write(chunk)
        if not size or (length is not None and size != int(length)):
            raise ValueError("Incomplete download")


def pull_snapshot(base: str, root: Path, fd: int, version: str, deadline: float) -> Path:
    for obsolete in root.glob(".staging-*.sqlite"):
        staged_version = obsolete.name.removeprefix(".staging-").removesuffix(".sqlite")
        if catalogue.valid_version(staged_version) and staged_version != version:
            obsolete.unlink()
    path = root / f".staging-{version}.sqlite"
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise ValueError("Invalid staging file")
        catalogue.validate(path, catalogue.identity(path), version)
        return path
    temporary = ".snapshot-download"
    handle = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            download(
                base + f"/v1/snapshots/{version}.sqlite",
                stream,
                MAX_SNAPSHOT,
                deadline,
                {"application/vnd.sqlite3", "application/octet-stream"},
            )
            stream.flush()
            os.fsync(stream.fileno())
        candidate = root / temporary
        catalogue.validate(candidate, catalogue.identity(candidate), version)
        os.chmod(candidate, 0o444)
        os.replace(temporary, path.name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        return path
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def manifest(path: Path, priority: list[str]) -> list[dict]:
    with catalogue.connection(path, seconds=2) as db:
        # Both extension tables are required for automatic publication, even when empty.
        originals = [
            dict(row)
            for row in db.execute(
                "SELECT work_id,sha256,width,height,media_type FROM work_cover LIMIT ?",
                (MAX_COVERS + 1,),
            )
        ]
        derivatives = [
            dict(row)
            for row in db.execute(
                "SELECT c.work_id,d.sha256,d.width,d.height,d.media_type FROM cover_derivative d JOIN work_cover c ON c.sha256=d.original_sha256 LIMIT ?",
                (MAX_COVERS + 1,),
            )
        ]
        if len(originals) + len(derivatives) > MAX_COVERS:
            raise ValueError("Cover manifest exceeds limit")
        for row in derivatives:
            row["upscaled"] = True
        # Added works can inherit their collection's artwork in the dashboard.
        if priority:
            placeholders = ",".join("?" for _ in priority)
            priority += [
                r[0]
                for r in db.execute(
                    f"SELECT parent_id FROM work_contains WHERE child_id IN ({placeholders})",
                    priority,
                ).fetchall()
            ]
    priority_set = set(priority)
    rows = sorted(
        originals + derivatives,
        key=lambda r: (
            0 if r["work_id"] in priority_set else 1 if r.get("upscaled") else 2,
            r["work_id"],
            r["sha256"],
        ),
    )
    unique: dict[tuple[bool, str], dict] = {}
    for row in rows:
        if (
            not isinstance(row["work_id"], str)
            or not WORK.fullmatch(row["work_id"])
            or not isinstance(row["sha256"], str)
            or not catalogue.DIGEST.fullmatch(row["sha256"])
            or type(row["width"]) is not int
            or type(row["height"]) is not int
            or not catalogue_covers.dimensions_allowed(row["width"], row["height"])
            or row["media_type"] not in catalogue_covers.MEDIA_TYPES
        ):
            raise ValueError("Invalid cover manifest")
        key = (bool(row.get("upscaled")), row["sha256"])
        if key in unique and any(
            unique[key][k] != row[k] for k in ("width", "height", "media_type")
        ):
            raise ValueError("Conflicting cover metadata")
        unique.setdefault(key, row)
    return list(unique.values())


def cover_signature(cover: dict) -> list | None:
    try:
        with catalogue_covers.blob(cover["sha256"], upscaled=cover.get("upscaled", False)) as (
            _,
            signature,
        ):
            return list(signature)
    except OSError, ValueError:
        return None


def fetch_cover(base: str, cover: dict, deadline: float):
    import io

    raw = io.BytesIO()
    variant = "upscaled" if cover.get("upscaled") else "original"
    download(
        base + f"/v1/work/{cover['work_id']}/cover/{variant}",
        raw,
        catalogue_covers.MAX_BODY,
        deadline,
        {cover["media_type"]},
    )
    data = raw.getvalue()
    if hashlib.sha256(data).hexdigest() != cover["sha256"] or catalogue_covers.raster_dimensions(
        data, cover["media_type"]
    ) != (cover["width"], cover["height"]):
        raise ValueError("Cover digest or dimensions differ from snapshot")
    directory = (
        settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR
        if cover.get("upscaled")
        else settings.LIBRARIUM_CATALOGUE_COVER_DIR
    )
    fd = os.open(directory, DIR_FLAGS)
    try:
        try:
            os.mkdir(cover["sha256"][:2], 0o755, dir_fd=fd)
        except FileExistsError:
            pass
        prefix = os.open(cover["sha256"][:2], DIR_FLAGS, dir_fd=fd)
        try:
            atomic(prefix, cover["sha256"], data)
        finally:
            os.close(prefix)
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_covers(path: Path, state: dict, base: str, deadline: float) -> bool:
    rows = manifest(path, list(state.get("priority", [])))
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    if state.get("manifest") != digest:
        state.update(manifest=digest, receipts={}, scan_cursor=0)
    receipts = state.setdefault("receipts", {})
    cursor = state.get("scan_cursor", 0)
    if type(cursor) is not int or not 0 <= cursor <= len(rows):
        raise ValueError("Invalid cover scan cursor")
    checked = 0
    try:
        while cursor < len(rows):
            if checked >= BATCH_SIZE or time.monotonic() >= deadline:
                break
            row = rows[cursor]
            key = ("u:" if row.get("upscaled") else "o:") + row["sha256"]
            signature = cover_signature(row)
            checked += 1
            if signature is None or receipts.get(key) != signature:
                if time.monotonic() >= deadline:
                    break
                try:
                    try:
                        catalogue_covers.read(row)
                    except catalogue.CatalogueError:
                        fetch_cover(base, row, deadline)
                except SliceExpired:
                    break
                except TimeoutError:
                    if time.monotonic() >= deadline:
                        break
                    raise
                except URLError as error:
                    if isinstance(error.reason, TimeoutError) and time.monotonic() >= deadline:
                        break
                    raise
                if time.monotonic() >= deadline:
                    break
                signature = cover_signature(row)
                if signature is None:
                    raise ValueError("Cover disappeared during verification")
                receipts[key] = signature
            cursor += 1
    finally:
        # Earlier slices already verified the prefix; resume without probing it again.
        state.update(scan_cursor=cursor, verified=cursor, total=len(rows))
        if state.get("phase") == "backfill":
            state.update(
                served_version=state["version"],
                served_verified=cursor,
                served_total=len(rows),
            )
    return cursor == len(rows)


def current(root: Path) -> str:
    pointer = root / "current"
    if not pointer.exists() and not pointer.is_symlink():
        return ""
    handle = os.open(pointer, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 80:
            raise ValueError("Invalid current pointer")
        version = stream.read(81).decode().strip()
    if not catalogue.valid_version(version):
        raise ValueError("Invalid current version")
    return version


def prune(root: Path, fd: int, served: str, previous: str):
    versions = sorted(
        (
            p.stem
            for p in root.glob("[0-9]*.sqlite")
            if catalogue.valid_version(p.stem) and not p.is_symlink()
        ),
        key=version_key,
        reverse=True,
    )
    keep = {v for v in (served, previous) if v}
    for version in versions:
        if len(keep) < RETAIN:
            keep.add(version)
        if version not in keep:
            os.unlink(version + ".sqlite", dir_fd=fd)
    os.fsync(fd)


def added_work_priority(root: Path, path: Path, target: str, priority: list[str]) -> list[str]:
    older = sorted(
        (
            p
            for p in root.glob("[0-9]*.sqlite")
            if catalogue.valid_version(p.stem)
            and version_key(p.stem) < version_key(target)
            and not p.is_symlink()
        ),
        key=lambda p: version_key(p.stem),
    )
    if not older:
        return priority
    try:
        previous = older[-1]
        catalogue.validate(previous, catalogue.identity(previous), previous.stem)
        with catalogue.connection(previous) as db:
            before = {r[0] for r in db.execute("SELECT id FROM work LIMIT ?", (MAX_COVERS + 1,))}
        with catalogue.connection(path) as db:
            added = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM work ORDER BY lower(title),id LIMIT ?", (MAX_COVERS + 1,)
                )
                if r[0] not in before
            ]
        return list(dict.fromkeys(priority + added[:300]))[:300]
    except catalogue.CatalogueError, OSError, sqlite3.Error:
        return priority


def step(root: Path, fd: int, state: dict, deadline: float):
    base = catalogue_status.base_url(settings.LIBRARIUM_CATALOGUE_STATUS_URL)
    # Accept the existing origin setting and an explicitly configured /v1/status URL.
    if base.endswith("/v1/status"):
        base = base.removesuffix("/v1/status")
    served = current(root)
    if time.time() >= state.get("poll_after", 0):
        remote = catalogue_status.STATUS(catalogue_status.fetch_json(base + "/v1/status", deadline))
        listing = catalogue_status.fetch_json(base + "/v1/snapshots", deadline)
        candidates = listing.get("snapshots", [])
        if not isinstance(candidates, list) or len(candidates) > 1000:
            raise ValueError("Invalid snapshot list")
        version = remote.get("published_version")
        if not isinstance(version, str) or not catalogue.valid_version(version):
            raise ValueError("Invalid published version")
        created = next(
            (
                s.get("created")
                for s in candidates
                if isinstance(s, dict) and s.get("version") == version
            ),
            None,
        )
        if created is not None:
            created = catalogue_status.stamp(created)
        added = (
            remote.get("snapshot", {}).get("changes", {}).get("added", [])
            if remote.get("snapshot")
            else []
        )
        priority = [
            w["id"]
            for w in added[:300]
            if isinstance(w, dict) and isinstance(w.get("id"), str) and WORK.fullmatch(w["id"])
        ]
        state.update(
            published_version=version,
            published_created_at=created,
            poll_after=time.time() + POLL_SECONDS,
            priority=priority,
        )
        if state.get("phase") == "idle":
            state["backfilled"] = False
        if state.get("published_version") != state.get("backfill_for"):
            state["backfill_attempted"] = False
            state["backfill_for"] = state["published_version"]
    version = state["published_version"]
    newer = not served or version_key(version) > version_key(served)
    if (
        served
        and not (newer and state.get("backfill_attempted"))
        and (
            state.get("served_version") != served
            or state.get("served_verified") != state.get("served_total")
            or not state.get("backfilled")
        )
    ):
        target, phase = served, "backfill"
    elif newer:
        target, phase = version, "staging"
    else:
        state.update(state="complete", phase="idle", next_after=time.time() + POLL_SECONDS)
        return
    if (state.get("version"), state.get("phase")) != (target, phase):
        state.update(receipts={}, manifest="", scan_cursor=0)
    state.update(version=target, phase=phase, state="syncing", failure="")
    if phase == "backfill":
        path = root / f"{served}.sqlite"
        catalogue.validate(path, catalogue.identity(path), served)
    else:
        path = pull_snapshot(base, root, fd, version, deadline)
    state["priority"] = added_work_priority(root, path, target, list(state.get("priority", [])))
    if not sync_covers(path, state, base, deadline):
        return
    if phase == "backfill":
        state["backfill_attempted"] = True
    if phase == "staging":
        if current(root) != served:
            raise ValueError("Current snapshot changed during sync")
        os.replace(path.name, target + ".sqlite", src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        atomic(fd, "current", (target + "\n").encode())
        prune(root, fd, target, served)
    state.update(
        served_version=target,
        served_verified=state["total"],
        served_total=state["total"],
        backfilled=True,
        completed_at=datetime.now(UTC).isoformat(),
    )
    if target == version or version_key(target) > version_key(version):
        state.update(state="complete", phase="idle", next_after=time.time() + POLL_SECONDS)


def tick() -> dict:
    if not settings.LIBRARIUM_CATALOGUE_SYNC_ENABLED:
        return {"state": "disabled"}
    if not settings.LIBRARIUM_CATALOGUE_DIR or not settings.LIBRARIUM_CATALOGUE_STATUS_URL:
        return {"state": "unavailable"}
    state: dict = {}
    try:
        with storage() as (root, fd):
            if fd is None:
                return {"state": "busy"}
            state = load(root)
            if time.time() < state.get("next_after", 0):
                return saved()
            state.update(key=configuration_key(), next_after=time.time() + SLICE_INTERVAL)
            # An interrupted download has no admitted bytes; restart that one bounded transfer.
            (root / ".snapshot-download").unlink(missing_ok=True)
            try:
                step(root, fd, state, time.monotonic() + BUDGET_SECONDS)
            except SliceExpired:
                state.update(state="syncing", failure="")
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                sqlite3.Error,
                catalogue.CatalogueError,
                http.client.HTTPException,
            ) as error:
                if isinstance(error, HTTPError):
                    error.close()
                if state.get("phase") == "backfill":
                    state["backfill_attempted"] = True
                state.update(
                    state="failed",
                    failure="Catalogue sync could not verify the snapshot and covers; retry pending.",
                    next_after=time.time() + RETRY_SECONDS,
                )
            state["updated_at"] = datetime.now(UTC).isoformat()
            atomic(fd, STATE, json.dumps(state, sort_keys=True).encode())
            return saved()
    except OSError, ValueError, TypeError:
        return {"state": "failed", "failure": "Catalogue sync storage is unavailable."}
