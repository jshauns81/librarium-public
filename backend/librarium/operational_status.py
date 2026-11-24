"""Read-only operator observations; deliberately contains no book or network projection."""

import os
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, connection
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from librarium.retired_jobs import RETIRED_KINDS

REPORT_SCHEMA = "librarium.support-report.v1"
JOB_LIMIT = 200
MIGRATION_LIMIT = 256
STATEMENT_TIMEOUT_MS = 2000
JOB_STATES = ("queued", "running")


def storage_capacity(configured):
    if not configured:
        return {"state": "unknown", "reason": "not_configured"}
    descriptor = None
    try:
        path = Path(configured)
        if not path.is_absolute() or any(p in {"", ".", ".."} for p in configured.split("/")[1:]):
            raise ValueError()
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        space = os.fstatvfs(descriptor)
        return {
            "state": "observed",
            "total_bytes": space.f_blocks * space.f_frsize,
            "available_bytes": max(0, space.f_bavail) * space.f_frsize,
            "available_inodes": max(0, space.f_favail),
            "scope": "configured_filesystem_capacity",
        }
    except OSError, ValueError, TypeError:
        return {"state": "unavailable", "reason": "capacity_read_failed"}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _job_sample(cursor, now):
    # Filter active work using the existing state index; do not sort or count history.
    cursor.execute(
        "SELECT state, lease_until, created_at, attempts FROM librarium_job "
        "WHERE state IN ('queued', 'running') AND NOT (kind = ANY(%s)) LIMIT %s",
        # Retired work is never claimed again, so it is history, not active work.
        [sorted(RETIRED_KINDS), JOB_LIMIT + 1],
    )
    rows = cursor.fetchall()
    sample = rows[:JOB_LIMIT]
    states = dict.fromkeys(JOB_STATES, 0)
    expired = missing = retried = future = 0
    queued_ages = []
    for state, lease, created, attempts in sample:
        retried += attempts > 1
        future += created > now
        if state == "queued":
            queued_ages.append(max(0, int((now - created).total_seconds())))
        states[state] += 1
        if state == "running":
            expired += lease is not None and lease <= now
            missing += lease is None
    return {
        "state": "observed",
        "selection": "active_jobs",
        "window_seconds": None,
        "limit": JOB_LIMIT,
        "sampled": len(sample),
        "incomplete": len(rows) > JOB_LIMIT,
        "states": states,
        "expired_running_leases": expired,
        "running_without_lease": missing,
        "worker_liveness": "unknown",
        "retried_jobs": retried,
        "future_created_timestamps": future,
        "oldest_sampled_queued_age_seconds": max(queued_ages, default=None),
    }


def _schema_observation(cursor, now):
    loader = MigrationLoader(None, ignore_no_migrations=True)
    expected = {name for app, name in loader.disk_migrations if app == "librarium"}
    cursor.execute(
        "SELECT name FROM django_migrations WHERE app = %s ORDER BY id LIMIT %s",
        ["librarium", MIGRATION_LIMIT + 1],
    )
    rows = cursor.fetchall()
    if len(rows) > MIGRATION_LIMIT:
        return {"state": "incomplete", "limit": MIGRATION_LIMIT}
    applied = {row[0] for row in rows}
    return {
        "state": "compatible" if expected == applied else "incompatible",
        "scope": "application_migration_names",
        "limit": MIGRATION_LIMIT,
        "missing_count": len(expected - applied),
        "unexpected_count": len(applied - expected),
    }


def database_observations(now):
    report = {name: {"state": "unavailable"} for name in ("database", "jobs", "schema")}
    diagnostic = None
    try:
        diagnostic = connection.copy(alias="support_report")
        diagnostic.settings_dict = {
            **diagnostic.settings_dict,
            "OPTIONS": {**diagnostic.settings_dict.get("OPTIONS", {}), "connect_timeout": 3},
        }
        with diagnostic.cursor() as cursor:
            cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = %s", [STATEMENT_TIMEOUT_MS])
            cursor.execute("SET LOCAL lock_timeout = %s", [STATEMENT_TIMEOUT_MS])
            cursor.execute("SELECT 1, statement_timestamp()")
            snapshot_time = cursor.fetchone()[1]
            report["database"] = {"state": "available", "scope": "select_1"}
            for name, observe in (("schema", _schema_observation), ("jobs", _job_sample)):
                cursor.execute("SAVEPOINT support_observation")
                try:
                    report[name] = observe(cursor, snapshot_time)
                except DatabaseError, OSError, ValueError:
                    # Database errors can contain connection details or attacker-controlled values.
                    cursor.execute("ROLLBACK TO SAVEPOINT support_observation")
                cursor.execute("RELEASE SAVEPOINT support_observation")
    except DatabaseError, OSError, ValueError:
        return report
    finally:
        if diagnostic is not None:
            diagnostic.close()
    return report


def collect_report(*, now: datetime | None = None):
    from librarium.build_identity import build_status, load_build_identity
    from librarium.recovery_evidence import report_recovery

    now = now or timezone.now()
    identity = load_build_identity()
    database = database_observations(now)
    return {
        "schema": REPORT_SCHEMA,
        "observed_at": now.isoformat(),
        "database": database["database"],
        "jobs": database["jobs"],
        "schema_compatibility": database["schema"],
        "storage": {
            "artifacts": storage_capacity(settings.LIBRARIUM_ARTIFACT_DIR),
            "reference_state": storage_capacity(settings.LIBRARIUM_REFERENCE_STATE_DIR),
        },
        "build": build_status(identity, os.environ.get("LIBRARIUM_DECLARED_IMAGE_DIGEST", "")),
        "recovery": report_recovery(
            os.environ.get("LIBRARIUM_RECOVERY_RECEIPT", ""), identity, now
        ),
        "limits": {
            "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            "connect_timeout_seconds": 3,
            "job_rows_read_max": JOB_LIMIT + 1,
            "job_clock": "database_snapshot_statement",
            "migration_rows_read_max": MIGRATION_LIMIT + 1,
            "database_capacity": "unknown",
            "filesystem_deadline": "not_guaranteed",
            "upstream_or_writer_probes": False,
            "authority": "reporting_only",
        },
    }
