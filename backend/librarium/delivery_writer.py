"""Narrow synthetic writer service; independent approval and persisted broker state."""

import fcntl
import hmac
import json
import os
import re
import stat
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic

from librarium.delivery_authorization import AuthorizationError, verify
from librarium.delivery_broker import BrokerError
from librarium.delivery_contract import POLICY

DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class WriterError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.status = 503 if code.endswith("unavailable") else 409


def transport_authenticated(header, token):
    return type(header) is str and hmac.compare_digest(
        header.encode("utf-8"), b"Bearer " + token.hex().encode("ascii")
    )


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise WriterError("invalid_json")
        value[key] = item
    return value


def parse(data):
    try:
        return json.loads(
            data,
            object_pairs_hook=unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except ValueError, TypeError, UnicodeError:
        raise WriterError("invalid_json") from None


def root_descriptor(root):
    path = Path(root)
    if not path.is_absolute() or ".." in path.parts:
        raise WriterError("storage_unavailable")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise WriterError("storage_unavailable")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_secret(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or not 32 <= info.st_size <= 4096
            ):
                raise WriterError("secret_unavailable")
            return stream.read(4097)
    except OSError:
        raise WriterError("secret_unavailable") from None


def read_artifact(root, descriptor):
    from hashlib import sha256

    if (
        type(descriptor) is not dict
        or set(descriptor) != {"kind", "sha256", "size"}
        or descriptor["kind"] not in {"source", "corrected", "report"}
        or type(descriptor["sha256"]) is not str
        or not DIGEST.fullmatch(descriptor["sha256"])
        or type(descriptor["size"]) is not int
        or not 0
        <= descriptor["size"]
        <= (1024 * 1024 if descriptor["kind"] == "report" else 32 * 1024 * 1024)
    ):
        raise WriterError("artifact_invalid")
    root_fd = None
    try:
        root_fd = root_descriptor(root)
        fd = os.open(
            descriptor["kind"] + "-" + descriptor["sha256"],
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_mode & 0o077
                or before.st_size != descriptor["size"]
            ):
                raise WriterError("artifact_changed")
            data = stream.read(descriptor["size"] + 1)
            after = os.fstat(stream.fileno())
            if (
                len(data) != descriptor["size"]
                or sha256(data).hexdigest() != descriptor["sha256"]
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise WriterError("artifact_changed")
            return data
    except OSError:
        raise WriterError("artifact_unavailable") from None
    finally:
        if root_fd is not None:
            os.close(root_fd)


class SyntheticLibraryLock:
    def __init__(self, root, library_uuid):
        self.path = Path(root) / "librarium-synthetic-owner.json"
        self.library_uuid = library_uuid
        self.fd = None

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(self.fd)
            data = os.read(self.fd, 4096)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
                or parse(data)
                != {
                    "schema": "librarium.synthetic-owner.v1",
                    "library_uuid": self.library_uuid,
                    "sole_owner": True,
                }
            ):
                raise WriterError("synthetic_owner_unconfirmed")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not self.verified(self.library_uuid):
                raise WriterError("synthetic_owner_unconfirmed")
            return self
        except (OSError, WriterError) as error:
            self.__exit__(None, None, None)
            if isinstance(error, WriterError):
                raise
            raise WriterError("independent_writer_not_excluded") from None

    def verified(self, library_uuid):
        if self.fd is None:
            return False
        try:
            opened, current = os.fstat(self.fd), self.path.lstat()
            return (
                self.library_uuid == library_uuid
                and opened.st_nlink == 1
                and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
            )
        except OSError, TypeError:
            return False

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class WriterService:
    def __init__(self, broker, artifact_root, signing_key, runtime_sha256, *, recovery=None):
        from librarium.delivery_recovery import RecoveryGate

        broker.runtime_sha256 = runtime_sha256
        self.broker, self.artifacts, self.key, self.runtime = (
            broker,
            artifact_root,
            signing_key,
            runtime_sha256,
        )
        self.recovery = recovery or RecoveryGate(os.environ.get("LIBRARIUM_DELIVERY_RECOVERY_DIR"))

    def authorized(self, grant):
        try:
            payload = verify(grant, self.key)
        except AuthorizationError:
            raise WriterError("approval_invalid") from None
        if (
            type(payload) is not dict
            or set(payload) - {"supervised_session"}
            != {
                "policy",
                "runtime_sha256",
                "request",
                "original",
                "replacement",
                "validation",
                "evidence",
                "intent_sha256",
                "review_expires_at",
                "writer_instance",
            }
            or payload["policy"] != POLICY
            or payload["runtime_sha256"] != self.runtime
            or not isinstance(payload["evidence"], list)
            or len(payload["evidence"]) > 8
        ):
            raise WriterError("approval_scope_invalid")
        request = payload["request"]
        if (
            type(request) is not dict
            or set(request) != {"operation_id", "target", "before", "output", "mode"}
            or request["mode"] not in {"delivery", "undo"}
        ):
            raise WriterError("approval_scope_invalid")
        return payload

    def execute(self, grant):
        payload = self.authorized(grant)
        request = payload["request"]
        with self.broker.lock:
            if self.broker.existing(request["operation_id"]) is not None:
                return self.broker.cancel(request)
            if not self.grant_current(payload):
                return self.broker.cancel(request, "sealed_stale_grant")
            if getattr(self.broker.owner, "supervised", False):
                from librarium.delivery_session import validate_session

                session = validate_session(payload.get("supervised_session"), request["target"])
                self.broker.claim_session(session["session_id"], request["operation_id"])
            return self._execute(payload)

    def grant_current(self, payload):
        checked_at = datetime.now(UTC)
        try:
            expiry = datetime.fromisoformat(payload["review_expires_at"])
            expired = expiry.tzinfo is None or expiry <= checked_at
        except ValueError, TypeError:
            expired = True
        instance = payload["writer_instance"]
        try:
            issued = datetime.fromisoformat(instance.get("approved_at", ""))
            fresh = issued.tzinfo is not None and self.broker.started_at <= issued <= checked_at
        except ValueError, TypeError, AttributeError:
            fresh = False
        journal_undo = (
            payload["request"]["mode"] == "undo"
            and fresh
            and instance
            == {
                "journal_id": self.broker.journal_id,
                "boot_nonce": None,
                "approved_at": instance["approved_at"],
            }
        )
        return not expired and (
            journal_undo
            or instance
            == {"journal_id": self.broker.journal_id, "boot_nonce": self.broker.boot_nonce}
        )

    def send_authorized(self, payload):
        if not self.grant_current(payload):
            return False
        if getattr(self.broker.owner, "supervised", False):
            from librarium.delivery_session import validate_session

            try:
                validate_session(payload.get("supervised_session"), payload["request"]["target"])
            except WriterError:
                return False
        return True

    def _execute(self, payload):
        request = payload["request"]
        original_binding = request["before"] if request["mode"] == "delivery" else request["output"]
        if any(
            payload["original"].get(field) != original_binding[field]
            for field in ("sha256", "size")
        ):
            raise WriterError("original_binding_changed")
        read_artifact(self.artifacts, payload["original"])
        output = read_artifact(self.artifacts, payload["replacement"])
        for descriptor in payload["evidence"]:
            read_artifact(self.artifacts, descriptor)
        report = parse(read_artifact(self.artifacts, payload["validation"]))
        expected = request["output"] if request["mode"] == "delivery" else request["before"]
        if (
            report.get("policy") != "librarium.output-validation.v1"
            or report.get("verdict") != "passed"
            or any(
                report.get("checks", {}).get(name, {}).get("status") != "passed"
                for name in ("structure", "epubcheck", "preservation")
            )
            or any(
                report.get("output", {}).get(field) != expected[field]
                for field in ("sha256", "size")
            )
        ):
            raise WriterError("validation_not_passed")
        if payload["original"]["kind"] != "source" or payload["replacement"]["kind"] != (
            "corrected" if request["mode"] == "delivery" else "source"
        ):
            raise WriterError("approval_scope_invalid")
        baseline = None
        if getattr(self.broker.owner, "recovery_required", False):
            baseline = self.recovery.prepare(payload, self.broker, self.artifacts)

        def authorized():
            if not self.send_authorized(payload):
                return False
            if baseline is not None:
                self.recovery.check_operation(payload, self.broker, self.artifacts, baseline)
            return self.send_authorized(payload)

        return self.broker.execute(request, output, send_authorized=authorized)

    def cancel(self, grant):
        reason = "cancelled_before_send"
        if type(grant) is dict and "seal_reason" in grant:
            grant = dict(grant)
            reason = grant.pop("seal_reason")
            if reason not in {
                "cancelled_before_send",
                "sealed_before_send",
                "sealed_after_refusal",
            }:
                raise WriterError("invalid_request")
        payload = self.authorized(grant)
        request = payload["request"]
        return self.broker.cancel(request, reason)


def make_server(service, token, port=8133):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    recent: deque[float] = deque()
    rate_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 60

        def log_message(self, *args):
            return

        def reply(self, value, status=200):
            data = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authenticated(self):
            return len(self.headers.get_all("Authorization", [])) == 1 and transport_authenticated(
                self.headers.get("Authorization"), token
            )

        def admitted(self):
            if not self.authenticated():
                self.reply({"error": "unauthorized"}, 401)
                return False
            with rate_lock:
                cutoff = monotonic() - 60
                while recent and recent[0] < cutoff:
                    recent.popleft()
                if len(recent) >= 120:
                    self.reply({"error": "rate_limited"}, 429)
                    return False
                recent.append(monotonic())
            return True

        def do_GET(self):
            if not self.admitted():
                return
            if self.path != "/v1/capability":
                return self.reply({"error": "not_found"}, 404)
            return self.reply(
                {
                    "policy": POLICY,
                    "runtime_sha256": service.runtime,
                    "library_uuid": service.broker.owner.library_uuid,
                    "synthetic_only": True,
                    "exclusion": "sole_owner"
                    if service.broker.owner.exclusion.verified(service.broker.owner.library_uuid)
                    else "unconfirmed",
                    "epoch": service.broker.epoch,
                    "writer_instance": {
                        "journal_id": service.broker.journal_id,
                        "boot_nonce": service.broker.boot_nonce,
                    },
                }
            )

        def do_POST(self):
            if not self.admitted():
                return
            try:
                length = self.headers.get("Content-Length", "")
                if (
                    len(self.headers.get_all("Content-Length", [])) != 1
                    or len(self.headers.get_all("Content-Type", [])) != 1
                    or self.headers.get("Transfer-Encoding") is not None
                    or self.headers.get("Content-Type") != "application/json"
                    or not length.isascii()
                    or not length.isdecimal()
                    or not 0 < int(length) <= 1024 * 1024
                ):
                    raise WriterError("invalid_request")
                self.connection.settimeout(60)
                value = parse(self.rfile.read(int(length)))
                if self.path == "/v1/observe" and type(value) is dict and set(value) == {"target"}:
                    result = service.broker.owner.observe(value["target"])
                elif (
                    self.path == "/v1/hold"
                    and type(value) is dict
                    and set(value) == {"operation_id"}
                ):
                    import uuid

                    operation_id = str(uuid.UUID(value["operation_id"]))
                    service.broker.hold(operation_id)
                    result = {"held": True}
                elif self.path == "/v1/execute":
                    result = service.execute(value)
                elif self.path == "/v1/cancel":
                    result = service.cancel(value)
                elif (
                    self.path == "/v1/reconcile"
                    and type(value) is dict
                    and set(value) == {"operation_id"}
                ):
                    result = service.broker.reconcile(value["operation_id"])
                else:
                    raise WriterError("invalid_request")
                return self.reply(result)
            except (WriterError, BrokerError, ValueError, TypeError, KeyError) as error:
                code = str(error)
                if not re.fullmatch(r"[a-z_]{1,64}", code):
                    code = "writer_unavailable"
                return self.reply({"error": code}, 409)
            except Exception:  # noqa: BLE001 - do not expose signed malformed payload details
                return self.reply({"error": "writer_unavailable"}, 503)

    class BoundedServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8

        def __init__(self, *args):
            self.slots = BoundedSemaphore(8)
            super().__init__(*args)

        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.slots.release()

    return BoundedServer(("127.0.0.1", port), Handler)


def serve(service, token):
    server = make_server(service, token, int(os.environ.get("LIBRARIUM_WRITER_PORT", "8133")))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def writer_state(environment):
    """Refuse before Calibre starts unless its state and config folders are usable.

    Calibre writes its configuration at process start, so this runs before the
    runtime is executed and never creates or writes anything itself.
    """
    state = environment.get("LIBRARIUM_WRITER_STATE_DIR")
    if not state:
        raise WriterError("writer_configuration_incomplete")
    if environment.get("CALIBRE_CONFIG_DIRECTORY") != str(Path(state) / "config"):
        raise WriterError("isolated_calibre_configuration_required")

    def usable(fd):
        info = os.fstat(fd)
        if (
            info.st_mode & 0o300 != 0o300
            or info.st_mode & 0o077
            or os.fstatvfs(fd).f_flag & os.ST_RDONLY
        ):
            raise WriterError("writer_state_unavailable")

    try:
        fd = root_descriptor(state)
    except WriterError, OSError:
        raise WriterError("writer_state_unavailable") from None
    try:
        usable(fd)
        config = os.open("config", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            if os.fstat(config).st_uid != os.geteuid():
                raise WriterError("writer_state_unavailable")
            usable(config)
        finally:
            os.close(config)
    except OSError:
        raise WriterError("writer_state_unavailable") from None
    finally:
        os.close(fd)


def configuration(environment):
    if environment.get("LIBRARIUM_DELIVERY_ENABLED") != "1":
        raise WriterError("writer_disabled")
    if environment.get("LIBRARIUM_WRITER_SYNTHETIC_ONLY") != "1":
        raise WriterError("synthetic_only_required")
    names = (
        "LIBRARIUM_WRITER_LIBRARY_ROOT",
        "LIBRARIUM_WRITER_STATE_DIR",
        "LIBRARIUM_ARTIFACT_DIR",
        "LIBRARIUM_WRITER_TOKEN_FILE",
        "LIBRARIUM_DELIVERY_SIGNING_KEY_FILE",
        "LIBRARIUM_WRITER_LIBRARY_UUID",
        "LIBRARIUM_WRITER_RUNTIME_SHA256",
        "LIBRARIUM_WRITER_ARCHIVE",
    )
    if any(not environment.get(name) for name in names):
        raise WriterError("writer_configuration_incomplete")
    writer_state(environment)
    values = {name: environment[name] for name in names}
    roots = [Path(values[name]) for name in names[:3]]
    for root in roots:
        fd = root_descriptor(root)
        os.close(fd)
    if any(
        a == b or a in b.parents or b in a.parents
        for i, a in enumerate(roots)
        for b in roots[i + 1 :]
    ):
        raise WriterError("writer_storage_overlap")
    marker = roots[0] / "librarium-synthetic-owner.json"
    try:
        marker_data = parse(read_secret(marker))
    except WriterError:
        raise WriterError("synthetic_owner_unconfirmed") from None
    if marker_data != {
        "schema": "librarium.synthetic-owner.v1",
        "library_uuid": values["LIBRARIUM_WRITER_LIBRARY_UUID"],
        "sole_owner": True,
    }:
        raise WriterError("synthetic_owner_unconfirmed")
    if not DIGEST.fullmatch(values["LIBRARIUM_WRITER_RUNTIME_SHA256"]):
        raise WriterError("runtime_pin_invalid")
    if read_secret(values["LIBRARIUM_WRITER_TOKEN_FILE"]) == read_secret(
        values["LIBRARIUM_DELIVERY_SIGNING_KEY_FILE"]
    ):
        raise WriterError("separate_signing_key_required")
    plugins = roots[1] / "config" / "plugins"
    if plugins.exists() and any(plugins.iterdir()):
        raise WriterError("isolated_calibre_configuration_required")
    return values
