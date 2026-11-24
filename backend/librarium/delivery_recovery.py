"""Verified backup admission and immutable references to already retained evidence."""

import os
import sqlite3
import stat
import uuid
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from librarium.delivery_broker import canonical, fingerprint
from librarium.delivery_writer import WriterError, parse, read_artifact, root_descriptor

MANIFEST = "librarium.recovery-baseline.v1"
VERIFICATION = "librarium.recovery-verification.v1"
OPERATION = "librarium.operation-recovery.v1"
COMPONENTS = ("library", "artifacts", "broker")
MAX_MANIFEST = 16 * 1024 * 1024
MAX_FILES = 100_000


class RecoveryError(WriterError):
    pass


def identifier(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError, TypeError, AttributeError:
        raise RecoveryError("recovery_binding_invalid") from None
    return value


def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def private_root(path):
    try:
        return root_descriptor(path)
    except OSError, WriterError, TypeError:
        raise RecoveryError("recovery_baseline_required") from None


def read_private(root, name, limit=MAX_MANIFEST, *, sync=False):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_mode & 0o077
                or before.st_nlink != 1
                or not 0 < before.st_size <= limit
            ):
                raise RecoveryError("recovery_evidence_invalid")
            data = stream.read(limit + 1)
            current = os.stat(name, dir_fd=root, follow_symlinks=False)
            if len(data) != before.st_size or identity(before) != identity(current):
                raise RecoveryError("recovery_evidence_changed")
            if sync:
                os.fsync(stream.fileno())
                os.fsync(root)
            return data
    except OSError:
        raise RecoveryError("recovery_evidence_unavailable") from None


def load(data):
    try:
        value = parse(data)
        if type(value) is not dict:
            raise ValueError
        return value
    except WriterError, ValueError, TypeError:
        raise RecoveryError("recovery_evidence_invalid") from None


def write_new(root, name, value):
    data = canonical(value)
    if len(data) > MAX_MANIFEST:
        raise RecoveryError("recovery_budget_exceeded")
    try:
        try:
            fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root
            )
        except FileExistsError:
            if read_private(root, name, sync=True) != data:
                raise RecoveryError("recovery_evidence_conflict") from None
            return
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(root)
    except OSError:
        raise RecoveryError("recovery_evidence_unavailable") from None


def regular_file(root, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
        ):
            raise RecoveryError("recovery_entry_invalid")
        digest, size = sha256(), 0
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
        after = os.stat(name, dir_fd=root, follow_symlinks=False)
        if identity(before) != identity(after) or size != before.st_size:
            raise RecoveryError("recovery_evidence_changed")
        return {"sha256": digest.hexdigest(), "size": size}


def inventory(root, counter=None, prefix="", depth=0):
    if depth > 64:
        raise RecoveryError("recovery_budget_exceeded")
    counter = [0] if counter is None else counter
    before = identity(os.fstat(root))
    found = []
    for name in sorted(os.listdir(root)):
        counter[0] += 1
        if counter[0] > MAX_FILES:
            raise RecoveryError("recovery_budget_exceeded")
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        path = prefix + name
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid():
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                found.append({"path": path, "directory": True})
                found.extend(inventory(child, counter, path + "/", depth + 1))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            found.append({"path": path, **regular_file(root, name)})
        else:
            raise RecoveryError("recovery_entry_invalid")
    if identity(os.fstat(root)) != before:
        raise RecoveryError("recovery_evidence_changed")
    return found


def components(root):
    result = {"database": regular_file(root, "database.dump")}
    if result["database"]["size"] == 0:
        raise RecoveryError("recovery_evidence_invalid")
    for name in COMPONENTS:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            result[name] = inventory(fd)
        finally:
            os.close(fd)
    return result


def stat_tree(root, prefix="", counter=None, depth=0):
    if depth > 64:
        raise RecoveryError("recovery_budget_exceeded")
    counter = [0] if counter is None else counter
    before = identity(os.fstat(root))
    result = {prefix: before}
    for name in sorted(os.listdir(root)):
        counter[0] += 1
        if counter[0] > MAX_FILES:
            raise RecoveryError("recovery_budget_exceeded")
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        path = prefix + name
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid():
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                result.update(stat_tree(child, path + "/", counter, depth + 1))
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1:
            result[path] = identity(info)
        else:
            raise RecoveryError("recovery_entry_invalid")
    if identity(os.fstat(root)) != before:
        raise RecoveryError("recovery_evidence_changed")
    return result


def component_identities(root):
    values = {
        "database.dump": identity(os.stat("database.dump", dir_fd=root, follow_symlinks=False))
    }
    counter = [0]
    for name in COMPONENTS:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            values.update(stat_tree(fd, name + "/", counter))
        finally:
            os.close(fd)
    return values


def journal_cursor(db, operation_id=""):
    digest, size = sha256(), 0
    for table, query in (
        ("operations", "SELECT id,request_sha256,payload FROM operations WHERE id<>? ORDER BY id"),
        (
            "events",
            "SELECT sequence,operation_id,epoch,stage,payload,created FROM events WHERE operation_id<>? ORDER BY sequence",
        ),
    ):
        digest.update(table.encode() + b"\n")
        for row in db.execute(query, (operation_id,)):
            data = canonical(row) + b"\n"
            size += len(data)
            if size > 128 * 1024 * 1024:
                raise RecoveryError("recovery_budget_exceeded")
            digest.update(data)
    return {
        "sha256": digest.hexdigest(),
        "operations": db.execute(
            "SELECT COUNT(*) FROM operations WHERE id<>?", (operation_id,)
        ).fetchone()[0],
        "events": db.execute(
            "SELECT COUNT(*) FROM events WHERE operation_id<>?", (operation_id,)
        ).fetchone()[0],
        "sequence": db.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM events WHERE operation_id<>?", (operation_id,)
        ).fetchone()[0],
    }


def baseline_facts(root):
    # Offline captures must be checkpointed; immutable SQLite reads never write SHM.
    for relative in ("library/metadata.db-wal", "broker/journal.sqlite3-wal"):
        path = Path(root) / relative
        if path.exists() and path.stat().st_size:
            raise RecoveryError("recovery_checkpoint_required")
    with closing(
        sqlite3.connect(
            (Path(root) / "library/metadata.db").as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as db:
        row = db.execute("SELECT uuid FROM library_id").fetchall()
        if len(row) != 1 or type(row[0][0]) is not str or not 0 < len(row[0][0]) <= 128:
            raise RecoveryError("recovery_binding_invalid")
        library = row[0][0]
    broker = private_root(Path(root) / "broker")
    try:
        journal = identifier(read_private(broker, "journal.identity", 64).decode("ascii"))
    finally:
        os.close(broker)
    with closing(
        sqlite3.connect(
            (Path(root) / "broker/journal.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as db:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RecoveryError("recovery_evidence_invalid")
        cursor = journal_cursor(db)
        if db.execute(
            "SELECT 1 FROM events e WHERE e.stage='send_started' AND NOT EXISTS (SELECT 1 FROM events r WHERE r.operation_id=e.operation_id AND r.stage='receipt') LIMIT 1"
        ).fetchone():
            raise RecoveryError("recovery_unreconciled")
    return {"library_uuid": library, "journal_id": journal, "journal_cursor": cursor}


def capture_baseline(root, session_id):
    """Inventory an already captured, stopped backup; never copy or restore state."""
    session_id = identifier(session_id)
    root = Path(root)
    fd = private_root(root)
    try:
        measured = components(fd)
        facts = baseline_facts(root)
        if measured != components(fd):
            raise RecoveryError("recovery_evidence_changed")
        value = {
            "schema": MANIFEST,
            "generation_id": str(uuid.uuid4()),
            "captured_at": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            **facts,
            "components": measured,
        }
        if os.path.lexists(root / "manifest.json"):
            existing = checked_manifest(read_private(fd, "manifest.json"))
            value["generation_id"] = existing["generation_id"]
            value["captured_at"] = existing["captured_at"]
            if value != existing:
                raise RecoveryError("recovery_evidence_conflict")
        write_new(fd, "manifest.json", value)
        return value
    except OSError, sqlite3.Error, UnicodeError:
        raise RecoveryError("recovery_evidence_unavailable") from None
    finally:
        os.close(fd)


def checked_manifest(data):
    value = load(data)
    if (
        set(value)
        != {
            "schema",
            "generation_id",
            "captured_at",
            "session_id",
            "library_uuid",
            "journal_id",
            "journal_cursor",
            "components",
        }
        or value["schema"] != MANIFEST
    ):
        raise RecoveryError("recovery_evidence_invalid")
    for field in ("generation_id", "session_id", "journal_id"):
        identifier(value[field])
    if type(value["components"]) is not dict or set(value["components"]) != {
        "database",
        *COMPONENTS,
    }:
        raise RecoveryError("recovery_evidence_invalid")
    return value


def verify_baseline(root, session_id):
    session_id = identifier(session_id)
    root = Path(root)
    fd = private_root(root)
    try:
        raw = read_private(fd, "manifest.json")
        manifest = checked_manifest(raw)
        if manifest["session_id"] != session_id:
            raise RecoveryError("recovery_session_changed")
        identities = component_identities(fd)
        if manifest["components"] != components(fd) or any(
            manifest[key] != value for key, value in baseline_facts(root).items()
        ):
            raise RecoveryError("recovery_evidence_changed")
        if identities != component_identities(fd):
            raise RecoveryError("recovery_evidence_changed")
        receipt = {
            "schema": VERIFICATION,
            "generation_id": manifest["generation_id"],
            "manifest_sha256": sha256(raw).hexdigest(),
            "session_id": session_id,
            "library_uuid": manifest["library_uuid"],
            "journal_id": manifest["journal_id"],
            "verified_at": datetime.now(UTC).isoformat(),
            "components": identities,
            "checks": {
                "component_hashes": "passed",
                "library_identity": "passed",
                "journal_identity": "passed",
            },
        }
        try:
            os.mkdir("verifications", 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        os.fsync(fd)
        receipts = private_root(root / "verifications")
        try:
            if os.path.lexists(root / "verifications" / (session_id + ".json")):
                existing = load(read_private(receipts, session_id + ".json"))
                receipt["verified_at"] = existing.get("verified_at")
                try:
                    verified = datetime.fromisoformat(receipt["verified_at"])
                    captured = datetime.fromisoformat(manifest["captured_at"])
                    if not (
                        captured.tzinfo
                        and verified.tzinfo
                        and captured <= verified <= datetime.now(UTC)
                    ):
                        raise ValueError
                except ValueError, TypeError:
                    raise RecoveryError("recovery_evidence_invalid") from None
                if receipt != existing:
                    raise RecoveryError("recovery_evidence_conflict")
            write_new(receipts, session_id + ".json", receipt)
        finally:
            os.close(receipts)
        return receipt
    except OSError, sqlite3.Error, UnicodeError, KeyError, TypeError:
        raise RecoveryError("recovery_evidence_invalid") from None
    finally:
        os.close(fd)


class RecoveryGate:
    def __init__(self, root):
        self.root = Path(root) if root else None

    def check(self, payload, broker, artifacts):
        if self.root is None:
            raise RecoveryError("recovery_baseline_required")
        root = self.root
        if any(
            root == Path(path) or root in Path(path).parents or Path(path) in root.parents
            for path in (broker.root, artifacts)
        ):
            raise RecoveryError("recovery_storage_overlap")
        fd = private_root(root)
        try:
            raw = read_private(fd, "manifest.json")
            manifest = checked_manifest(raw)
            session = payload["supervised_session"]
            sid = identifier(session["session_id"])
            receipts = private_root(root / "verifications")
            try:
                verification_data = read_private(receipts, sid + ".json")
            finally:
                os.close(receipts)
            receipt = load(verification_data)
            expected = {
                "schema": VERIFICATION,
                "generation_id": manifest["generation_id"],
                "manifest_sha256": sha256(raw).hexdigest(),
                "session_id": sid,
                "library_uuid": payload["request"]["target"]["library_uuid"],
                "journal_id": broker.journal_id,
                "verified_at": receipt.get("verified_at"),
                "components": component_identities(fd),
                "checks": {
                    "component_hashes": "passed",
                    "library_identity": "passed",
                    "journal_identity": "passed",
                },
            }
            if (
                receipt != expected
                or manifest["session_id"] != sid
                or manifest["library_uuid"] != expected["library_uuid"]
                or manifest["journal_id"] != broker.journal_id
            ):
                raise RecoveryError("recovery_binding_changed")
            verified = datetime.fromisoformat(receipt["verified_at"])
            captured = datetime.fromisoformat(manifest["captured_at"])
            confirmed = datetime.fromisoformat(session["confirmed_at"])
            if not (
                captured.tzinfo
                and verified.tzinfo
                and captured <= verified <= confirmed <= datetime.now(UTC)
            ):
                raise RecoveryError("recovery_session_changed")
            if manifest["journal_cursor"] != journal_cursor(
                broker.db, payload["request"]["operation_id"]
            ):
                raise RecoveryError("recovery_journal_changed")
            files = {
                entry["path"]: entry
                for entry in manifest["components"]["artifacts"]
                if not entry.get("directory")
            }
            for descriptor in [
                payload["original"],
                payload["replacement"],
                payload["validation"],
                *payload["evidence"],
            ]:
                name = descriptor["kind"] + "-" + descriptor["sha256"]
                if files.get(name) != {
                    "path": name,
                    "sha256": descriptor["sha256"],
                    "size": descriptor["size"],
                }:
                    raise RecoveryError("recovery_artifact_missing")
                try:
                    read_artifact(root / "artifacts", descriptor)
                except WriterError:
                    raise RecoveryError("recovery_artifact_changed") from None
            return {
                "generation_id": manifest["generation_id"],
                "manifest_sha256": sha256(raw).hexdigest(),
                "verification_sha256": sha256(verification_data).hexdigest(),
            }
        except OSError, ValueError, TypeError, KeyError, sqlite3.Error:
            raise RecoveryError("recovery_evidence_invalid") from None
        finally:
            os.close(fd)

    def operation(self, payload, broker, baseline):
        request = payload["request"]
        operation = identifier(request["operation_id"])
        return {
            "schema": OPERATION,
            "operation_id": operation,
            "request_sha256": fingerprint(request),
            "approval_sha256": fingerprint(payload),
            "intent_sha256": payload["intent_sha256"],
            "journal_id": broker.journal_id,
            "target": request["target"],
            "baseline": baseline,
            "session": payload["supervised_session"],
            **{key: payload[key] for key in ("original", "replacement", "validation", "evidence")},
        }

    def check_operation(self, payload, broker, artifacts, baseline):
        if self.check(payload, broker, artifacts) != baseline:
            raise RecoveryError("recovery_baseline_changed")
        expected = self.operation(payload, broker, baseline)
        folder = private_root(broker.root / "recovery")
        try:
            if read_private(folder, expected["operation_id"] + ".json") != canonical(expected):
                raise RecoveryError("recovery_package_changed")
        finally:
            os.close(folder)

    def prepare(self, payload, broker, artifacts):
        baseline = self.check(payload, broker, artifacts)
        value = self.operation(payload, broker, baseline)
        operation = value["operation_id"]
        root = private_root(broker.root)
        try:
            try:
                os.mkdir("recovery", 0o700, dir_fd=root)
            except FileExistsError:
                pass
            os.fsync(root)
            folder = private_root(broker.root / "recovery")
            try:
                write_new(folder, operation + ".json", value)
            finally:
                os.close(folder)
        except OSError:
            raise RecoveryError("recovery_evidence_unavailable") from None
        finally:
            os.close(root)
        return baseline
