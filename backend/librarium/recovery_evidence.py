"""Closed projection of retained synthetic rehearsal evidence; grants no admission."""

import math
import os
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from librarium.delivery_broker import canonical
from librarium.delivery_recovery import RecoveryError, load, private_root, read_private, write_new

SCHEMA = "librarium.recovery-rehearsal.v1"
MAX_RECEIPT_BYTES = 16 * 1024
REHEARSAL_MAX_AGE_SECONDS = 30 * 24 * 3600
BACKUP_MAX_AGE_SECONDS = 24 * 3600
SCOPES = {
    "isolated_populated_upgrade": [
        "database_reopened",
        "historical_metadata",
        "historical_source_report_checker",
        "exact_request_keys",
        "obsolete_pending_refused",
        "current_work_retained",
        "retired_history_readable",
    ],
    "isolated_pre_upgrade_generation": [
        "database_reopened",
        "historical_metadata",
        "historical_source_report_checker",
        "exact_request_keys",
        "post_upgrade_work_excluded",
    ],
    "isolated_epub_database_artifacts": [
        "database_reopened",
        "original_bytes",
        "inspection_report",
        "validation_report",
    ],
    "isolated_coordinated_delivery": [
        "database_reopened",
        "original_bytes",
        "historical_receipt",
        "exact_request_key",
        "new_writer_epoch",
        "no_duplicate_operation",
        "no_resend",
    ],
}
BINDING_FIELDS = {"source_sha256", "build_identity_sha256", "compatibility_sha256"}
FIELDS = {
    "schema",
    "scope",
    "outcome",
    "backup_captured_at",
    "recovery_started_at",
    "recovery_completed_at",
    "recovery_seconds",
    "binding",
    "assertions",
}


def timestamp(value):
    if type(value) is not str or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", value
    ):
        raise ValueError
    return datetime.fromisoformat(value)


def utc_text(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def identity_binding(identity):
    if identity is None:
        return dict.fromkeys(BINDING_FIELDS)
    from librarium.build_identity import identity_sha256

    return {
        "source_sha256": identity["source_sha256"],
        "build_identity_sha256": identity_sha256(identity),
        "compatibility_sha256": sha256(canonical(identity["compatibility"])).hexdigest(),
    }


def validate_receipt(value):
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError
    if value["schema"] != SCHEMA:
        return "unsupported"
    scope = value["scope"]
    if type(scope) is not str or scope not in SCOPES or value["outcome"] != "passed":
        raise ValueError
    if value["assertions"] != SCOPES[scope]:
        raise ValueError
    binding = value["binding"]
    if type(binding) is not dict or set(binding) != BINDING_FIELDS:
        raise ValueError
    values = list(binding.values())
    if not all(item is None for item in values) and not all(
        type(item) is str and re.fullmatch(r"[0-9a-f]{64}", item) for item in values
    ):
        raise ValueError
    seconds = value["recovery_seconds"]
    if type(seconds) not in {float, int} or not math.isfinite(seconds) or not 0 < seconds <= 86400:
        raise ValueError
    capture, start, end = (
        timestamp(value[field])
        for field in ("backup_captured_at", "recovery_started_at", "recovery_completed_at")
    )
    wall_seconds = (end - start).total_seconds()
    if not capture <= start <= end or wall_seconds > 86400 or abs(seconds - wall_seconds) > 2:
        raise ValueError
    return "valid"


def make_receipt(scope, captured_at, started_at, completed_at, recovery_seconds, binding):
    value = {
        "schema": SCHEMA,
        "scope": scope,
        "outcome": "passed",
        "backup_captured_at": utc_text(captured_at),
        "recovery_started_at": utc_text(started_at),
        "recovery_completed_at": utc_text(completed_at),
        "recovery_seconds": round(recovery_seconds, 6),
        "binding": binding,
        "assertions": SCOPES[scope],
    }
    if validate_receipt(value) != "valid":
        raise ValueError("recovery_receipt_invalid")
    return value


def retain_receipt(path, value):
    if validate_receipt(value) != "valid" or len(canonical(value)) > MAX_RECEIPT_BYTES:
        raise ValueError("recovery_receipt_invalid")
    path = Path(path)
    root = private_root(path.parent)
    try:
        write_new(root, path.name, value)
    finally:
        os.close(root)


def report_recovery(path, identity, now=None):
    now = datetime.now(UTC) if now is None else now
    result = {
        "state": "missing",
        "authority": "reporting_only",
        "provenance": "retained_operator_evidence",
        "running_image_verified": False,
        "scope": None,
        "recovery_seconds": None,
        "backup_captured_at": None,
        "recovery_started_at": None,
        "recovery_completed_at": None,
        "backup_age_at_recovery_seconds": None,
        "backup_age_seconds": None,
        "rehearsal_current": None,
        "backup_current": None,
        "binding_matches": None,
        "limits": {
            "max_receipt_bytes": MAX_RECEIPT_BYTES,
            "rehearsal_max_age_seconds": REHEARSAL_MAX_AGE_SECONDS,
            "backup_max_age_seconds": BACKUP_MAX_AGE_SECONDS,
        },
    }
    if not path:
        return result
    descriptor = None
    try:
        location = Path(path)
        descriptor = private_root(location.parent)
        value = load(read_private(descriptor, location.name, MAX_RECEIPT_BYTES))
        validation = validate_receipt(value)
        if validation != "valid":
            result["state"] = validation
            return result
        capture, start, end = (
            timestamp(value[field])
            for field in ("backup_captured_at", "recovery_started_at", "recovery_completed_at")
        )
        if end > now:
            result["state"] = "future"
            return result
        bound = identity_binding(identity)
        complete = (
            all(item is not None for item in value["binding"].values()) and identity is not None
        )
        matches = value["binding"] == bound if complete else None
        rehearsal_current = (now - end).total_seconds() <= REHEARSAL_MAX_AGE_SECONDS
        result.update(
            state=(
                "incompatible"
                if matches is False
                else "stale"
                if not rehearsal_current
                else "incomplete"
                if matches is None
                else "recorded"
            ),
            scope=value["scope"],
            recovery_seconds=value["recovery_seconds"],
            backup_captured_at=value["backup_captured_at"],
            recovery_started_at=value["recovery_started_at"],
            recovery_completed_at=value["recovery_completed_at"],
            backup_age_at_recovery_seconds=(start - capture).total_seconds(),
            backup_age_seconds=(now - capture).total_seconds(),
            rehearsal_current=rehearsal_current,
            backup_current=(now - capture).total_seconds() <= BACKUP_MAX_AGE_SECONDS,
            binding_matches=matches,
        )
    except RecoveryError as error:
        result["state"] = "invalid" if error.code == "recovery_evidence_invalid" else "unavailable"
    except OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError:
        result["state"] = "invalid"
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return result
