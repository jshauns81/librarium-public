"""Sole-owner journal protocol. SQLite here stores broker evidence, never library data."""

import fcntl
import json
import os
import sqlite3
import stat
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock


class BrokerError(Exception):
    pass


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def fingerprint(value):
    return sha256(canonical(value)).hexdigest()


def target_evidence(observation):
    return (
        {key: observation[key] for key in ("sha256", "size", "metadata")} if observation else None
    )


def now():
    return datetime.now(UTC).isoformat()


class Broker:
    canonical = staticmethod(canonical)

    def __init__(self, root, owner, *, boundary=lambda name: None):
        self.started_at = datetime.now(UTC)
        self.root, self.owner, self.boundary = Path(root), owner, boundary
        self.lock = RLock()
        self.runtime_sha256 = None
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise BrokerError("journal_unavailable")
        self.lock_fd = os.open(self.root / ".owner", os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.lock_fd)
            raise BrokerError("owner_busy") from None
        path = self.root / "journal.sqlite3"
        try:
            identity = self.root / "journal.identity"
            if identity.exists() != path.exists():
                raise BrokerError("journal_missing")
            if not identity.exists():
                fd = os.open(identity, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(str(uuid.uuid4()).encode())
                    stream.flush()
                    os.fsync(stream.fileno())
            fd = os.open(identity, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077
                ):
                    raise BrokerError("journal_identity_invalid")
                self.journal_id = str(uuid.UUID(stream.read(37).decode("ascii")))
            self.boot_nonce = str(uuid.uuid4())
            fd = os.open(path, os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS pauses (operation_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, operation_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS targets (target_key TEXT PRIMARY KEY, operation_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS epochs (id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL REFERENCES operations(id),
                    epoch INTEGER NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS operations_no_update BEFORE UPDATE ON operations BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS operations_no_delete BEFORE DELETE ON operations BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'immutable'); END;
            """)
            if getattr(self.owner, "supervised", False):
                self.db.execute(
                    "INSERT OR IGNORE INTO pauses SELECT DISTINCT e.operation_id FROM events e "
                    "WHERE e.stage='send_started' AND NOT EXISTS (SELECT 1 FROM events r "
                    "WHERE r.operation_id=e.operation_id AND r.stage='receipt')"
                )
            self.epoch = self.db.execute(
                "INSERT INTO epochs(started) VALUES (?)", (now(),)
            ).lastrowid
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException:
            if getattr(self, "db", None) is not None:
                self.db.close()
            os.close(self.lock_fd)
            raise

    def close(self):
        self.db.close()
        os.close(self.lock_fd)

    def append(self, operation_id, stage, payload, *, request=None):
        data = canonical(payload)
        if len(data) > 1024 * 1024:
            raise BrokerError("receipt_budget_exceeded")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if request is not None:
                target_key = fingerprint(
                    {k: request["target"][k] for k in ("library_uuid", "book_id")}
                )
                if not (stage == "receipt" and payload["classification"] == "not_applied"):
                    reserved = self.db.execute(
                        "SELECT operation_id FROM targets WHERE target_key=?", (target_key,)
                    ).fetchone()
                    if reserved and reserved[0] != operation_id:
                        raise BrokerError("target_reserved")
                    self.db.execute(
                        "INSERT OR IGNORE INTO targets VALUES (?, ?)", (target_key, operation_id)
                    )
                self.db.execute(
                    "INSERT INTO operations VALUES (?, ?, ?)",
                    (operation_id, fingerprint(request), canonical(request).decode()),
                )
            self.db.execute(
                "INSERT INTO events(operation_id, epoch, stage, payload, created) VALUES (?, ?, ?, ?, ?)",
                (operation_id, self.epoch, stage, data.decode(), now()),
            )
            if stage == "receipt" and payload["classification"] in {"applied", "not_applied"}:
                self.db.execute("DELETE FROM targets WHERE operation_id=?", (operation_id,))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def existing(self, operation_id):
        with self.lock:
            return self._existing(operation_id)

    def _existing(self, operation_id):
        row = self.db.execute(
            "SELECT payload FROM operations WHERE id=?", (operation_id,)
        ).fetchone()
        if row is None:
            return None
        events = self.db.execute(
            "SELECT stage,payload FROM events WHERE operation_id=? ORDER BY sequence",
            (operation_id,),
        ).fetchall()
        if not events:
            raise BrokerError("journal_incomplete")
        return json.loads(row[0]), [(stage, json.loads(payload)) for stage, payload in events]

    def receipt(self, request, classification, observation, reason=None):
        return {
            "policy": "librarium.epub-delivery.v1",
            "runtime_sha256": self.runtime_sha256,
            "classification": classification,
            "reason": reason,
            "operation_id": request["operation_id"],
            "request_sha256": fingerprint(request),
            "target": request["target"],
            "before": request["before"],
            "observed": observation,
            "epoch": self.epoch,
            "verified_at": now() if classification == "applied" else None,
        }

    def output_already_present(self, request, observed):
        return (
            observed is not None
            and observed["sha256"] == request["output"]["sha256"]
            and observed["sha256"] != request["before"]["sha256"]
        )

    def claim_session(self, session_id, operation_id):
        with self.lock:
            row = self.db.execute(
                "SELECT operation_id FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if row and row[0] != operation_id:
                raise BrokerError("session_consumed")
            self.db.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?, ?)", (session_id, operation_id)
            )

    def paused(self):
        return bool(
            self.db.execute("SELECT 1 FROM pauses LIMIT 1").fetchone()
            or self.db.execute(
                "SELECT 1 FROM events e WHERE e.stage='send_started' AND NOT EXISTS "
                "(SELECT 1 FROM events r WHERE r.operation_id=e.operation_id AND r.stage='receipt') LIMIT 1"
            ).fetchone()
        )

    def pause(self, operation_id):
        if getattr(self.owner, "supervised", False):
            self.db.execute("INSERT OR IGNORE INTO pauses VALUES (?)", (operation_id,))

    def hold(self, operation_id):
        # Only an operation this writer started sending can pause every target.
        with self.lock:
            recorded = self.existing(operation_id)
            if recorded is None or not any(stage == "send_started" for stage, _ in recorded[1]):
                raise BrokerError("operation_unknown")
            self.pause(operation_id)

    def execute(self, request, output, *, send_authorized=lambda: True):
        try:
            return self._execute(request, output, send_authorized=send_authorized)
        except BaseException:
            with self.lock:
                # Before a send is recorded nothing was written, and the peer may not
                # be authenticated, so only a started send can pause every target.
                recorded = self.existing(request["operation_id"])
                if recorded and any(stage == "send_started" for stage, _ in recorded[1]):
                    self.pause(request["operation_id"])
            raise

    def seal_stale_grant(self, request, observed, send_authorized):
        if send_authorized():
            return None
        result = self.receipt(request, "not_applied", observed, "sealed_stale_grant")
        self.append(request["operation_id"], "receipt", result)
        return result

    def _execute(self, request, output, *, send_authorized=lambda: True):
        if (
            sha256(output).hexdigest() != request["output"]["sha256"]
            or len(output) != request["output"]["size"]
        ):
            raise BrokerError("artifact_changed")
        operation_id = request["operation_id"]
        with self.lock, self.owner.lock:
            recorded = self.existing(operation_id)
            if recorded:
                if recorded[0] != request:
                    raise BrokerError("operation_conflict")
                # Every operation is consumed before send. Recovery is always observation-only.
                return self.reconcile(operation_id)
            if getattr(self.owner, "supervised", False) and self.paused():
                raise BrokerError("recovery_required")
            space = os.statvfs(self.root)
            if (
                space.f_bavail * space.f_frsize < 16 * 1024 * 1024
                or (self.root / "journal.sqlite3").stat().st_size > 128 * 1024 * 1024
            ):
                raise BrokerError("storage_full")
            before = self.owner.observe(request["target"])
            if target_evidence(before) != target_evidence(request["before"]):
                if self.output_already_present(request, before):
                    return self.receipt(request, "unobservable", before, "output_already_present")
                result = self.receipt(request, "not_applied", before, "precondition_changed")
                self.append(operation_id, "receipt", result, request=request)
                return result
            self.owner.prepare_write(request["target"], len(output))
            self.append(operation_id, "prepared", before, request=request)
            self.boundary("prepared")
            refused = self.seal_stale_grant(request, before, send_authorized)
            if refused is not None:
                return refused
            self.append(operation_id, "send_started", {"epoch": self.epoch})
            self.boundary("send_started")
            # Recheck after durable send intent, immediately before the server write.
            current = before
            if getattr(self.owner, "supervised", False):
                current = self.owner.observe(request["target"])
                if target_evidence(current) != target_evidence(before):
                    self.pause(operation_id)
                    result = self.receipt(request, "diverged", current, "precondition_changed")
                    self.append(operation_id, "receipt", result)
                    return result
            refused = self.seal_stale_grant(request, current, send_authorized)
            if refused is not None:
                return refused
            self.owner.replace(request["target"], output)
            self.boundary("native_returned")
            after = self.owner.observe(request["target"])
            good = (
                after["sha256"] == request["output"]["sha256"]
                and after["size"] == request["output"]["size"]
                and after["metadata"] == before["metadata"]
            )
            result = self.receipt(
                request,
                "applied" if good else "diverged",
                after,
                None if good else "readback_mismatch",
            )
            if not good:
                self.pause(operation_id)
            if good:
                self.owner.sync(request["target"])
            self.boundary("readback")
            self.append(operation_id, "receipt", result)
            self.boundary("receipt")
            return result

    def reconcile(self, operation_id):
        with self.lock:
            result = self._reconcile(operation_id)
            if (
                result["classification"] in {"diverged", "unobservable"}
                and result.get("reason") != "journal_absent"
            ):
                self.pause(operation_id)
            return result

    def _reconcile(self, operation_id):
        with self.lock, self.owner.lock:
            recorded = self.existing(operation_id)
            if recorded is None:
                return {
                    "classification": "unobservable",
                    "operation_id": operation_id,
                    "reason": "journal_absent",
                }
            request, events = recorded
            historical = next((value for stage, value in events if stage == "receipt"), None)
            if historical and historical["classification"] == "not_applied":
                try:
                    present = self.owner.observe(request["target"])
                except BrokerError, OSError, ValueError:
                    present = None
                if target_evidence(present) == target_evidence(historical["observed"]):
                    return historical
                return {
                    **historical,
                    "present": present,
                    "present_drift": target_evidence(present) != target_evidence(request["before"]),
                }
            if events[-1][0] == "prepared":
                try:
                    present = self.owner.observe(request["target"])
                except BrokerError, OSError, ValueError:
                    present = None
                result = self.receipt(request, "not_applied", present, "sealed_before_send")
                self.append(operation_id, "receipt", result)
                return result
            try:
                observed = self.owner.observe(request["target"])
            except BrokerError as error:
                positive = str(error) in {"target_changed", "format_bookkeeping_changed"}
                result = self.receipt(
                    request,
                    "diverged" if positive else "unobservable",
                    None,
                    str(error) if positive else "target_unobservable",
                )
                if historical:
                    result["historical_receipt"] = historical
                return result
            except OSError, ValueError:
                return self.receipt(request, "unobservable", None, "target_unobservable")
            if historical:
                if target_evidence(observed) == target_evidence(historical["observed"]):
                    return historical
                return {
                    **self.receipt(request, "diverged", observed, "epub_changed_after_receipt"),
                    "historical_receipt": historical,
                }
            good = (
                observed["sha256"] == request["output"]["sha256"]
                and observed["size"] == request["output"]["size"]
                and observed["metadata"] == request["before"]["metadata"]
            )
            if good:
                self.owner.sync(request["target"])
                result = self.receipt(request, "applied", observed, "recovered_readback")
                self.append(operation_id, "receipt", result)
                return result
            # Original bytes after send_started do not disprove an ABA write/restoration.
            return self.receipt(
                request,
                "unobservable"
                if target_evidence(observed) == target_evidence(request["before"])
                else "diverged",
                observed,
                "send_outcome_unconfirmed",
            )

    def cancel(self, request, reason="cancelled_before_send"):
        operation_id = request["operation_id"]
        with self.lock, self.owner.lock:
            recorded = self.existing(operation_id)
            if recorded:
                if recorded[0] != request:
                    raise BrokerError("operation_conflict")
                return self.reconcile(operation_id)
            try:
                observed = self.owner.observe(request["target"])
            except BrokerError, OSError, ValueError:
                observed = None
            if self.output_already_present(request, observed):
                return self.receipt(request, "unobservable", observed, "output_already_present")
            result = self.receipt(request, "not_applied", observed, reason)
            self.append(operation_id, "receipt", result, request=request)
            return result
