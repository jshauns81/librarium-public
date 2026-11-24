"""Explicit native reference imports with immutable generations and one cutover."""

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import uuid
from contextlib import ExitStack, closing, contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from librarium import catalogue

MAX_PACKET_BYTES = 4 * 1024 * 1024
MAX_DATABASE_BYTES = 512 * 1024 * 1024
MAX_RECEIPT_BYTES = 16384
MAX_VERSIONS = 10000
SCHEMA = "librarium.reference-receipt.v1"
PRODUCER = "librarium.reference-producer.v1"


class ProductionError(Exception):
    def __init__(self, message, code="reference_unavailable", status=503):
        super().__init__(message)
        self.code, self.status = code, status


def _engine():
    from bl_catalog import native

    return native


def _now():
    return datetime.now(UTC).isoformat()


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _private(info, *, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ProductionError(
            "Reference state is unavailable or has unsafe ownership or permissions"
        )


@contextmanager
def _root():
    raw = getattr(settings, "LIBRARIUM_REFERENCE_STATE_DIR", "")
    path = Path(raw)
    if not raw:
        raise ProductionError(
            "Native reference state is not configured", "reference_not_configured"
        )
    if (
        not path.is_absolute()
        or "\x00" in raw
        or any(part in {"", ".", ".."} for part in raw.split("/")[1:])
    ):
        raise ProductionError("Use an absolute private reference-state directory")
    for name in (
        "DIRECT_LIBRARY_ROOT",
        "LIBRARIUM_ARTIFACT_DIR",
        "LIBRARIUM_CATALOGUE_COVER_DIR",
        "LIBRARIUM_CATALOGUE_DIR",
    ):
        value = getattr(settings, name, "")
        if value:
            other = Path(value).resolve()
            if name == "LIBRARIUM_CATALOGUE_DIR" and other == path / "published":
                continue
            if other == path or other in path.parents or path in other.parents:
                raise ProductionError(
                    "Reference state must not overlap library, artifact or incumbent inputs"
                )
    with ExitStack() as stack:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, fd)
        for part in path.parts[1:]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        _private(os.fstat(fd), directory=True)
        entries = os.listdir(fd)
        if len(entries) > 1000:
            raise ProductionError("Use a dedicated private reference-state directory")
        for name in entries:
            if name in {"requests", "generations", "published"}:
                _private(os.stat(name, dir_fd=fd, follow_symlinks=False), directory=True)
            elif name in {"producer.lock", "pending", "last"}:
                _private(os.stat(name, dir_fd=fd, follow_symlinks=False))
            elif name.startswith(".pending-"):
                _request_key(name.removeprefix(".pending-"))
                _private(os.stat(name, dir_fd=fd, follow_symlinks=False))
            else:
                raise ProductionError("Use a dedicated private reference-state directory")
        yield fd


@contextmanager
def _directory(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        _private(os.fstat(fd), directory=True)
        if create:
            os.fsync(parent)
        yield fd
    finally:
        os.close(fd)


def _path(fd, name=""):
    return Path(f"/proc/self/fd/{fd}") / name


def _read(fd, name, limit, *, private=True):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if private:
            _private(before)
        elif (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o222
        ):
            raise ProductionError("Published reference data is not an immutable owned file")
        if not 0 <= before.st_size <= limit:
            raise ProductionError("Reference state exceeds its safety limit")
        body = stream.read(limit + 1)
        if len(body) != before.st_size or _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ProductionError("Reference state changed during reading")
        return body


def _digest(fd, name, limit, *, private=True):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if private:
            _private(before)
        elif (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o222
        ):
            raise ProductionError("Published reference data is not an immutable owned file")
        if not 0 <= before.st_size <= limit:
            raise ProductionError("Reference state exceeds its safety limit")
        size, digest = 0, hashlib.sha256()
        while chunk := stream.read(min(1024 * 1024, limit + 1 - size)):
            size += len(chunk)
            if size > before.st_size:
                raise ProductionError("Reference state changed during reading")
            digest.update(chunk)
        if size != before.st_size or _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ProductionError("Reference state changed during reading")
        return digest.hexdigest()


def _optional(fd, name, limit):
    try:
        return _read(fd, name, limit)
    except FileNotFoundError:
        return None


def _atomic(fd, name, raw):
    temporary = f".pending-{uuid.uuid4()}"
    existing = _optional(fd, name, MAX_RECEIPT_BYTES)
    del existing
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def _json(fd, name, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ProductionError("Reference outcome exceeds its safety limit")
    _atomic(fd, name, raw)


def _preserve_packet(requests, key, raw):
    name = f"{key}.packet"
    existing = _optional(requests, name, MAX_PACKET_BYTES)
    if existing is not None:
        if existing != raw:
            raise ProductionError(
                "This request key belongs to another preserved packet",
                "reference_request_conflict",
                409,
            )
        return
    temporary = f".packet-{uuid.uuid4()}"
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=requests
    )
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(raw)
            target.flush()
            os.fchmod(target.fileno(), 0o400)
            os.fsync(target.fileno())
        os.link(temporary, name, src_dir_fd=requests, dst_dir_fd=requests, follow_symlinks=False)
        os.fsync(requests)
    finally:
        try:
            os.unlink(temporary, dir_fd=requests)
        except FileNotFoundError:
            pass
        os.fsync(requests)


@contextmanager
def _lock(root):
    fd = os.open(
        "producer.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root
    )
    try:
        _private(os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProductionError(
                "A reference import is already running; retry after it finishes",
                "reference_busy",
                409,
            ) from None
        yield
    finally:
        os.close(fd)


def _request_key(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str) or not 1 <= len(value) <= 45:
        raise ValueError
    return str(uuid.UUID(value))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate packet field")
        result[key] = value
    return result


def _valid_digest(value):
    return isinstance(value, str) and bool(catalogue.DIGEST.fullmatch(value))


def _valid_version(value):
    return isinstance(value, str) and catalogue.valid_version(value)


def _valid_pin(value):
    return (
        isinstance(value, dict)
        and _valid_version(value.get("version"))
        and _valid_digest(value.get("sha256"))
        and type(value.get("fixture")) is bool
    )


def _packet(raw):
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(value, dict):
            raise TypeError
        return _engine().validate_packet(value)
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise ProductionError(
            "Use a valid bounded source-evidence packet", "reference_packet_invalid", 400
        ) from error


def _receipt(requests, key):
    raw = _optional(requests, f"{key}.json", MAX_RECEIPT_BYTES)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProductionError("The recorded reference outcome is invalid") from error
    if (
        not isinstance(value, dict)
        or value.get("schema") != SCHEMA
        or value.get("request_key") != key
        or value.get("state") not in {"preparing", "prepared", "succeeded", "failed"}
        or not _valid_digest(value.get("packet_sha256"))
        or not _valid_version(value.get("version"))
        or type(value.get("fixture")) is not bool
        or type(value.get("records")) is not int
        or not 0 <= value["records"] <= 1000
        or not isinstance(value.get("source"), str)
        or not value["source"].isascii()
        or not 1 <= len(value["source"]) <= 80
        or not _valid_pin(value.get("base_snapshot"))
        or "base_current" not in value
        or (value["base_current"] is not None and not _valid_version(value["base_current"]))
        or (value.get("bootstrap") is not None and not _valid_pin(value["bootstrap"]))
        or (value.get("sha256") is not None and not _valid_digest(value["sha256"]))
        or (
            value["state"] in {"prepared", "succeeded"}
            and (
                not _valid_digest(value.get("sha256"))
                or not _valid_digest(value.get("evidence_sha256"))
            )
        )
        or any(
            value.get(field) is not None
            and (not isinstance(value[field], str) or len(value[field]) > 80)
            for field in ("started_at", "prepared_at", "completed_at")
        )
    ):
        raise ProductionError("The recorded reference outcome is invalid")
    packet_name = f"{key}.packet"
    before = os.stat(packet_name, dir_fd=requests, follow_symlinks=False)
    _private(before)
    if _packet_digest(requests, packet_name, _identity(before)) != value["packet_sha256"]:
        raise ProductionError("The preserved reference packet failed its integrity check")
    if _identity(os.stat(packet_name, dir_fd=requests, follow_symlinks=False)) != _identity(before):
        raise ProductionError("The preserved reference packet changed during reading")
    return value


@lru_cache(maxsize=16)
def _packet_digest(requests, name, identity):
    return _digest(requests, name, MAX_PACKET_BYTES)


def _current_version(published):
    raw = _optional(published, "current", 80)
    if raw is None:
        return None
    value = raw.decode("ascii").strip()
    if not catalogue.valid_version(value):
        raise ProductionError("The native catalogue selection is invalid")
    return value


@lru_cache(maxsize=8)
def _pin_evidence(path, identity, version):
    digest = catalogue.validate(path, identity, version)
    with catalogue.connection(path) as db:
        rows = dict(
            db.execute(
                "SELECT key,substr(value,1,257) FROM meta WHERE key IN ('librarium_reference_producer','librarium_reference_fixture','librarium_reference_request','librarium_reference_packet')"
            )
        )
    if rows.get("librarium_reference_producer") != PRODUCER or rows.get(
        "librarium_reference_fixture"
    ) not in {"true", "false"}:
        raise ProductionError("The native catalogue provenance is invalid")
    key = _request_key(rows.get("librarium_reference_request"))
    packet_sha = rows.get("librarium_reference_packet", "")
    if not catalogue.DIGEST.fullmatch(packet_sha):
        raise ProductionError("The native catalogue packet binding is invalid")
    return {
        "version": version,
        "sha256": digest,
        "fixture": rows["librarium_reference_fixture"] == "true",
        "request_key": key,
        "packet_sha256": packet_sha,
    }


def _pin(published, version, expected=""):
    name = f"{version}.sqlite"
    before = os.stat(name, dir_fd=published, follow_symlinks=False)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_mode & 0o222
        or before.st_size > MAX_DATABASE_BYTES
    ):
        raise ProductionError("Published reference data is not an immutable owned file")
    pin = dict(_pin_evidence(_path(published, name), _identity(before), version))
    if expected and pin["sha256"] != expected:
        raise ProductionError("Published reference data failed its integrity check")
    if _identity(os.stat(name, dir_fd=published, follow_symlinks=False)) != _identity(before):
        raise ProductionError("Published reference data changed during reading")
    return pin


def _verified_receipt_pin(published, receipt):
    pin = _pin(published, receipt["version"], receipt["sha256"])
    if any(
        pin[key] != receipt[key]
        for key in ("version", "sha256", "fixture", "request_key", "packet_sha256")
    ):
        raise ProductionError("The reference outcome does not match its published snapshot")
    return pin


def _bound_pin(requests, published, version):
    pin = _pin(published, version)
    receipt = _receipt(requests, pin["request_key"])
    if receipt is None or receipt["state"] not in {"prepared", "succeeded"}:
        raise ProductionError("The native publication has no verifiable prepared outcome")
    return _verified_receipt_pin(published, receipt)


def _next_version(generations, base_version):
    names = os.listdir(generations)
    if len(names) >= MAX_VERSIONS:
        raise ProductionError("Reference generation retention has reached its safety limit")
    prefix = max(datetime.now(UTC).strftime("%Y.%m.%d"), base_version[:10]) + "."
    numbers = [
        int(name[len(prefix) :])
        for name in names
        if name.startswith(prefix) and catalogue.valid_version(name)
    ]
    if base_version.startswith(prefix):
        numbers.append(int(base_version[len(prefix) :]))
    value = prefix + str(max(numbers, default=0) + 1)
    if not catalogue.valid_version(value):
        raise ProductionError("No reference version is available")
    return value


def _copy_database(source, generation):
    descriptor = os.open(
        "evidence.sqlite",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=generation,
    )
    os.close(descriptor)
    with closing(sqlite3.connect(_path(generation, "evidence.sqlite"))) as target:
        source.backup(target, pages=256)
    if (
        os.stat("evidence.sqlite", dir_fd=generation, follow_symlinks=False).st_size
        > MAX_DATABASE_BYTES
    ):
        raise ProductionError("Reference evidence exceeds its safety limit")


def _stamp(generation, receipt):
    path = _path(generation, "evidence.sqlite")
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        values = {
            "catalog_version": receipt["version"],
            "librarium_reference_producer": PRODUCER,
            "librarium_reference_request": receipt["request_key"],
            "librarium_reference_packet": receipt["packet_sha256"],
            "librarium_reference_fixture": "true" if receipt["fixture"] else "false",
        }
        db.executemany("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", values.items())
        db.commit()
    descriptor = os.open("evidence.sqlite", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=generation)
    try:
        _private(os.fstat(descriptor))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _activate(published, version):
    _atomic(published, "current", version.encode("ascii"))


def _finish(root, requests, receipt):
    receipt = {
        **receipt,
        "state": "succeeded",
        "completed_at": receipt.get("completed_at") or _now(),
    }
    _json(requests, f"{receipt['request_key']}.json", receipt)
    _atomic(root, "last", receipt["request_key"].encode())
    try:
        os.unlink("pending", dir_fd=root)
    except FileNotFoundError:
        pass
    os.fsync(root)
    return receipt


def _recover(root, requests, published, key):
    receipt = _receipt(requests, key)
    if receipt is None:
        raise ProductionError(
            "An interrupted import requires operator review", "reference_recovery_required", 409
        )
    current = _current_version(published)
    if receipt["state"] == "prepared":
        _verified_receipt_pin(published, receipt)
        if current not in {receipt["base_current"], receipt["version"]}:
            raise ProductionError(
                "The interrupted import no longer matches the active generation",
                "reference_recovery_required",
                409,
            )
        if current != receipt["version"]:
            _activate(published, receipt["version"])
        return _finish(root, requests, receipt)
    if current != receipt["base_current"]:
        raise ProductionError(
            "The selected generation changed during the interrupted import",
            "reference_recovery_required",
            409,
        )
    receipt = {
        **receipt,
        "state": "failed",
        "completed_at": _now(),
        "error_code": "reference_interrupted",
        "message": "Import stopped before preparation completed; review and retry with a new request key",
    }
    _json(requests, f"{key}.json", receipt)
    _atomic(root, "last", key.encode())
    try:
        os.unlink("pending", dir_fd=root)
    except FileNotFoundError:
        pass
    os.fsync(root)
    return receipt


def _run(root, requests, generations, published, raw, key, packet, bootstrap):
    current = _current_version(published)
    if current and bootstrap:
        raise ProductionError(
            "Bootstrap is only available before the first native publication",
            "reference_bootstrap_conflict",
            409,
        )
    if not current and not bootstrap:
        raise ProductionError(
            "Choose an admitted bootstrap catalogue version and SHA-256",
            "reference_bootstrap_required",
            400,
        )
    base = _bound_pin(requests, published, current) if current else dict(bootstrap)
    version = _next_version(generations, base["version"])
    receipt = {
        "schema": SCHEMA,
        "request_key": key,
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "source": packet["source"],
        "records": len(packet["records"]),
        "base_snapshot": {k: base[k] for k in ("version", "sha256", "fixture")},
        "base_current": current,
        "bootstrap": bootstrap,
        "version": version,
        "sha256": None,
        "fixture": base["fixture"],
        "state": "preparing",
        "prepared_at": None,
        "completed_at": None,
        "started_at": _now(),
    }
    _preserve_packet(requests, key, raw)
    _json(requests, f"{key}.json", receipt)
    _atomic(root, "pending", key.encode())
    phase = "import"
    try:
        os.mkdir(version, 0o700, dir_fd=generations)
        os.fsync(generations)
        with _directory(generations, version) as generation:
            if current:
                with _directory(generations, current) as prior:
                    if (
                        _digest(prior, "evidence.sqlite", MAX_DATABASE_BYTES)
                        != _receipt(requests, base["request_key"])["evidence_sha256"]
                    ):
                        raise ProductionError("Active native evidence failed its integrity check")
                    with catalogue.connection(_path(prior, "evidence.sqlite")) as source:
                        _copy_database(source, generation)
            else:
                with catalogue.snapshot(
                    settings.LIBRARIUM_CATALOGUE_DIR,
                    base["version"],
                    base["sha256"],
                    base["fixture"],
                ) as (source, _):
                    _copy_database(source, generation)
            engine = _engine()
            receipt["import_summary"] = engine.apply_packet(
                _path(generation, "evidence.sqlite"), packet
            )
            receipt["resolution_summary"] = engine.rebuild_database(
                _path(generation, "evidence.sqlite")
            )
            _stamp(generation, receipt)
            receipt["evidence_sha256"] = _digest(generation, "evidence.sqlite", MAX_DATABASE_BYTES)
            os.chmod("evidence.sqlite", 0o400, dir_fd=generation, follow_symlinks=False)
            with _directory(generation, "snapshots", create=True) as staging:
                engine.stage_snapshot(_path(generation, "evidence.sqlite"), staging, version)
                candidate = _path(staging, f"{version}.sqlite")
                digest = catalogue.validate(candidate, catalogue.identity(candidate), version)
                receipt.update(sha256=digest, state="prepared", prepared_at=_now())
                phase = "publication"
                os.link(
                    f"{version}.sqlite",
                    f"{version}.sqlite",
                    src_dir_fd=staging,
                    dst_dir_fd=published,
                    follow_symlinks=False,
                )
                os.fsync(published)
            _pin(published, version, receipt["sha256"])
            _json(requests, f"{key}.json", receipt)
            if _current_version(published) != current:
                raise ProductionError(
                    "The active reference generation changed before publication",
                    "reference_changed",
                    409,
                )
            _activate(published, version)
            return _finish(root, requests, receipt)
    except Exception as error:
        if _current_version(published) == version:
            raise ProductionError(
                "The snapshot is selected; replay this exact request to recover its outcome",
                "reference_recovery_required",
                409,
            ) from error
        receipt.update(
            state="failed",
            completed_at=_now(),
            error_code=f"reference_{phase}_failed",
            message="Reference import did not change the active catalogue; inspect the selected inputs and retry with a new request key",
        )
        _json(requests, f"{key}.json", receipt)
        _atomic(root, "last", key.encode())
        os.unlink("pending", dir_fd=root)
        os.fsync(root)
        raise ProductionError(receipt["message"], receipt["error_code"]) from error


def import_packet(raw, request_key, *, bootstrap_version="", bootstrap_sha256=""):
    try:
        key = _request_key(request_key)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_PACKET_BYTES:
            raise ValueError
        if bool(bootstrap_version) != bool(bootstrap_sha256) or (
            bootstrap_version
            and (
                not catalogue.valid_version(bootstrap_version)
                or not catalogue.DIGEST.fullmatch(bootstrap_sha256)
            )
        ):
            raise ValueError
    except (ValueError, TypeError) as error:
        raise ProductionError(
            "Use a bounded packet, UUID request key and complete bootstrap pin",
            "reference_request_invalid",
            400,
        ) from error
    digest = hashlib.sha256(raw).hexdigest()
    try:
        previous = None
        with _root() as probe:
            try:
                with _directory(probe, "requests") as requests:
                    previous = _receipt(requests, key)
            except FileNotFoundError:
                pass
        # Recorded requests retain their original interpretation after an engine upgrade.
        # New invalid input is refused before creating lock, receipt or generation files.
        packet = _packet(raw) if previous is None else None
        with (
            _root() as root,
            _lock(root),
            _directory(root, "requests", create=True) as requests,
            _directory(root, "generations", create=True) as generations,
            _directory(root, "published", create=True) as published,
        ):
            previous = _receipt(requests, key)
            if previous is not None:
                if (
                    previous["packet_sha256"] != digest
                    or (
                        bootstrap_version
                        and (previous.get("bootstrap") or {}).get("version") != bootstrap_version
                    )
                    or (
                        bootstrap_sha256
                        and (previous.get("bootstrap") or {}).get("sha256") != bootstrap_sha256
                    )
                ):
                    raise ProductionError(
                        "This request key belongs to another reference import",
                        "reference_request_conflict",
                        409,
                    )
                if previous["state"] == "succeeded":
                    _verified_receipt_pin(published, previous)
                    if _optional(root, "pending", 80) == key.encode():
                        if _current_version(published) != previous["version"]:
                            raise ProductionError(
                                "The selected generation differs from the interrupted outcome",
                                "reference_recovery_required",
                                409,
                            )
                        return _finish(root, requests, previous)
                    return previous
                if previous["state"] == "failed":
                    if _optional(root, "pending", 80) == key.encode():
                        if _current_version(published) != previous["base_current"]:
                            raise ProductionError(
                                "The failed outcome conflicts with the selected generation",
                                "reference_recovery_required",
                                409,
                            )
                        _atomic(root, "last", key.encode())
                        os.unlink("pending", dir_fd=root)
                        os.fsync(root)
                    return previous
            pending = _optional(root, "pending", 80)
            if pending is not None:
                pending_key = _request_key(pending.decode("ascii"))
                if pending_key != key:
                    raise ProductionError(
                        "An interrupted import must be recovered with its original request key first",
                        "reference_recovery_required",
                        409,
                    )
                return _recover(root, requests, published, key)
            if packet is None:
                return _recover(root, requests, published, key)
            bootstrap = (
                {
                    "version": bootstrap_version,
                    "sha256": bootstrap_sha256,
                    "fixture": settings.LIBRARIUM_CATALOGUE_FIXTURE,
                }
                if bootstrap_version
                else None
            )
            return _run(root, requests, generations, published, raw, key, packet, bootstrap)
    except ProductionError:
        raise
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        raise ProductionError(
            "Reference state is unavailable or invalid; check its private configuration"
        ) from error


def status():
    if not getattr(settings, "LIBRARIUM_REFERENCE_STATE_DIR", ""):
        return {
            "status": "not_configured",
            "message": "Reference updates are not running inside Librarium yet. These queues describe the selected saved snapshot.",
            "current": None,
            "last_outcome": None,
        }
    try:
        with _root() as root:
            current = None
            try:
                with _directory(root, "published") as published:
                    version = _current_version(published)
                    if version:
                        with _directory(root, "requests") as requests:
                            pin = _bound_pin(requests, published, version)
                        current = {k: pin[k] for k in ("version", "sha256", "fixture")}
            except FileNotFoundError:
                pass
            last = _optional(root, "pending", 80) or _optional(root, "last", 80)
            outcome = None
            if last:
                key = _request_key(last.decode("ascii"))
                with _directory(root, "requests") as requests:
                    receipt = _receipt(requests, key)
                if receipt:
                    outcome = {
                        k: receipt.get(k)
                        for k in (
                            "request_key",
                            "completed_at",
                            "state",
                            "source",
                            "records",
                            "version",
                            "sha256",
                            "error_code",
                            "message",
                        )
                    }
            return {
                "status": "manual",
                "message": "Native reference import is configured for explicit source-evidence packets. Automatic provider fetching is not enabled.",
                "current": current,
                "last_outcome": outcome,
            }
    except ProductionError, catalogue.CatalogueError, OSError, ValueError, TypeError, sqlite3.Error:
        return {
            "status": "unavailable",
            "message": "Native reference state could not be verified. Existing catalogue browsing remains available.",
            "current": None,
            "last_outcome": None,
        }
