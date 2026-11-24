import io
import json
import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.db import OperationalError, connection
from django.utils import timezone
from librarium import operational_status as support
from librarium.models import Job
from librarium.retired_jobs import RETIRED_KINDS

CANARY = "private-canary-never-disclose.example"


def test_database_unavailable_is_sanitized(monkeypatch):
    monkeypatch.setattr(support.connection, "copy", Mock(side_effect=OperationalError(CANARY)))
    report = support.database_observations(timezone.now())
    assert report["database"]["state"] == "unavailable"
    assert report["jobs"]["state"] == "unavailable"
    assert report["schema"]["state"] == "unavailable"
    assert CANARY not in json.dumps(report)


@pytest.mark.parametrize("configured", ["", "/missing/" + CANARY, "\x00" + CANARY])
def test_storage_missing_and_unavailable_are_safe(configured):
    result = support.storage_capacity(configured)
    assert result["state"] == ("unknown" if not configured else "unavailable")
    assert CANARY not in json.dumps(result)


def test_storage_is_read_only_capacity_not_inventory(tmp_path):
    path = tmp_path / CANARY
    path.mkdir()
    result = support.storage_capacity(str(path))
    assert result["state"] == "observed"
    assert result["available_bytes"] >= 0
    assert result["total_bytes"] > 0
    assert list(path.iterdir()) == []
    assert CANARY not in json.dumps(result)
    link = tmp_path / "link"
    link.symlink_to(path, target_is_directory=True)
    assert support.storage_capacity(str(link))["state"] == "unavailable"


@pytest.mark.django_db(transaction=True)
def test_job_sample_is_bounded_and_expiry_never_proves_worker_death():
    now = timezone.now()
    Job.objects.bulk_create(
        [
            Job(
                id=uuid.UUID(int=i + 1),
                kind="epub",
                target_id=f"{i:064x}",
                request_key=uuid.uuid4(),
                input_fingerprint="a" * 64,
                input={"secret": CANARY},
                message=CANARY,
                result={"private": CANARY},
                state="running" if i == 0 else ("private-canary" if i == 1 else "queued"),
                lease_until=now - timedelta(seconds=20),
            )
            for i in range(support.JOB_LIMIT + 3)
        ]
    )
    before = list(Job.objects.values_list("id", "state", "updated_at", "attempts"))
    report = support.database_observations(now)
    jobs = report["jobs"]
    assert jobs["state"] == "observed"
    assert jobs["sampled"] == support.JOB_LIMIT
    assert jobs["incomplete"] is True
    assert jobs["selection"] == "active_jobs"
    assert jobs["window_seconds"] is None
    assert jobs["expired_running_leases"] == jobs["states"]["running"]
    assert jobs["worker_liveness"] == "unknown"
    assert set(jobs["states"]) == {"queued", "running"}
    assert CANARY not in json.dumps(report)
    assert "private-canary" not in json.dumps(report)
    assert report["database"]["state"] == "available"
    assert report["schema"]["state"] == "compatible"
    assert before == list(Job.objects.values_list("id", "state", "updated_at", "attempts"))


@pytest.mark.django_db(transaction=True)
def test_database_connection_really_forbids_writes(monkeypatch):
    def forbidden(cursor, now):
        cursor.execute("DELETE FROM librarium_job")
        return {}

    monkeypatch.setattr(support, "_job_sample", forbidden)
    report = support.database_observations(timezone.now())
    assert report["database"]["state"] == "available"
    assert report["jobs"]["state"] == "unavailable"
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        assert cursor.fetchone()[0] == "off"


def test_command_sanitizes_unexpected_failure(monkeypatch):
    from librarium.management.commands import support_report

    monkeypatch.setattr(support_report, "collect_report", Mock(side_effect=RuntimeError(CANARY)))
    output, errors = io.StringIO(), io.StringIO()
    call_command("support_report", stdout=output, stderr=errors)
    assert json.loads(output.getvalue()) == {
        "schema": support.REPORT_SCHEMA,
        "state": "unavailable",
    }
    assert CANARY not in output.getvalue() + errors.getvalue()


@pytest.mark.django_db(transaction=True)
def test_full_command_has_fixed_projection_and_no_upstream_probes(settings, tmp_path):
    settings.LIBRARIUM_ARTIFACT_DIR = str(tmp_path)
    settings.LIBRARIUM_REFERENCE_STATE_DIR = ""
    settings.LIBRARIUM_LIBRARY_URL = "https://" + CANARY
    output = io.StringIO()
    call_command("support_report", stdout=output)
    report = json.loads(output.getvalue())
    assert set(report) == {
        "schema",
        "observed_at",
        "database",
        "jobs",
        "schema_compatibility",
        "storage",
        "build",
        "recovery",
        "limits",
    }
    assert report["build"]["state"] == "unknown"
    assert report["build"]["running_image_digest"] is None
    assert report["storage"]["artifacts"]["state"] == "observed"
    assert CANARY not in output.getvalue()


@pytest.mark.django_db(transaction=True)
def test_schema_drift_disclosed_without_raw_migration_names():
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO django_migrations (app, name, applied) VALUES (%s,%s,%s)",
            ["librarium", CANARY, timezone.now()],
        )
    try:
        report = support.database_observations(timezone.now())
        assert report["schema"]["state"] == "incompatible"
        assert report["schema"]["unexpected_count"] == 1
        assert CANARY not in json.dumps(report)
        assert report["jobs"]["incomplete"] is False
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_migrations WHERE name = %s", [CANARY])


@pytest.mark.django_db(transaction=True)
def test_failed_schema_observation_does_not_hide_jobs(monkeypatch):
    def unavailable(cursor, now):
        cursor.execute("SELECT missing_canary_column FROM django_migrations")

    monkeypatch.setattr(support, "_schema_observation", unavailable)
    report = support.database_observations(timezone.now())
    assert report["schema"]["state"] == "unavailable"
    assert report["jobs"]["state"] == "observed"


def test_storage_error_does_not_disclose_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(support.os, "fstatvfs", Mock(side_effect=OSError(CANARY)))
    result = support.storage_capacity(str(tmp_path))
    assert result == {"state": "unavailable", "reason": "capacity_read_failed"}
    assert CANARY not in json.dumps(result)


@pytest.mark.django_db(transaction=True)
def test_migration_observation_limit_never_claims_compatibility():
    names = [f"support_canary_{i}" for i in range(support.MIGRATION_LIMIT + 1)]
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO django_migrations (app, name, applied) VALUES (%s,%s,%s)",
            [("librarium", name, timezone.now()) for name in names],
        )
    try:
        report = support.database_observations(timezone.now())
        assert report["schema"] == {"state": "incomplete", "limit": support.MIGRATION_LIMIT}
        assert report["jobs"]["state"] == "observed"
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_migrations WHERE name = ANY(%s)", [names])


@pytest.mark.django_db(transaction=True)
def test_sample_exposes_queued_age_retry_and_unknown_running_lease():
    now = timezone.now()
    queued, running = [
        Job.objects.create(
            kind="epub",
            target_id=char * 64,
            request_key=uuid.uuid4(),
            input_fingerprint="a" * 64,
            input={},
            state=state,
            attempts=attempts,
        )
        for char, state, attempts in [("a", "queued", 2), ("b", "running", 1)]
    ]
    Job.objects.filter(pk=queued.pk).update(created_at=now - timedelta(hours=2))
    Job.objects.filter(pk=running.pk).update(created_at=now + timedelta(hours=1))
    jobs = support.database_observations(now)["jobs"]
    assert jobs["oldest_sampled_queued_age_seconds"] == 7200
    assert jobs["retried_jobs"] == 1
    assert jobs["future_created_timestamps"] == 1
    assert jobs["running_without_lease"] == 1
    assert jobs["worker_liveness"] == "unknown"
    assert jobs["expired_running_leases"] == 0


@pytest.mark.django_db(transaction=True)
def test_finished_history_cannot_hide_an_expired_active_job():
    now = timezone.now()
    Job.objects.bulk_create(
        [
            Job(
                id=uuid.UUID(int=i + 1),
                kind="epub",
                target_id=f"{i:064x}",
                request_key=uuid.uuid4(),
                input_fingerprint="a" * 64,
                input={},
                state="succeeded",
            )
            for i in range(support.JOB_LIMIT + 50)
        ]
    )
    Job.objects.create(
        id=uuid.UUID(int=2**128 - 1),
        kind="epub",
        target_id="f" * 64,
        request_key=uuid.uuid4(),
        input_fingerprint="a" * 64,
        input={},
        state="running",
        attempts=3,
        lease_until=now - timedelta(hours=6),
    )
    jobs = support.database_observations(now)["jobs"]
    assert jobs["sampled"] == 1
    assert jobs["incomplete"] is False
    assert jobs["states"]["running"] == 1
    assert jobs["expired_running_leases"] == 1
    assert jobs["retried_jobs"] == 1
    assert jobs["worker_liveness"] == "unknown"


@pytest.mark.django_db(transaction=True)
def test_connection_time_does_not_make_a_new_job_look_future_created():
    Job.objects.create(
        kind="epub",
        target_id="f" * 64,
        request_key=uuid.uuid4(),
        input_fingerprint="a" * 64,
        input={},
        state="queued",
    )
    before_connection = timezone.now() - timedelta(seconds=3)
    jobs = support.database_observations(before_connection)["jobs"]
    assert jobs["future_created_timestamps"] == 0


@pytest.mark.django_db(transaction=True)
def test_unfinished_retired_work_is_not_sampled_as_active():
    now = timezone.now()
    for index, kind in enumerate(sorted(RETIRED_KINDS)):
        Job.objects.create(
            kind=kind,
            target_id=f"{index:064x}",
            request_key=uuid.uuid4(),
            input_fingerprint="a" * 64,
            input={},
            state="queued",
        )
    Job.objects.create(
        kind="epub",
        target_id="f" * 64,
        request_key=uuid.uuid4(),
        input_fingerprint="a" * 64,
        input={},
        state="queued",
    )
    jobs = support.database_observations(now)["jobs"]
    assert jobs["sampled"] == 1
    assert jobs["states"] == {"queued": 1, "running": 0}
