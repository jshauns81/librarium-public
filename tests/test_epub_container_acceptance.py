"""Image acceptance must distinguish checker findings from unfinished jobs."""

import copy
import io
import json
import os
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/epub_container_acceptance.py"


@pytest.fixture
def acceptance():
    return runpy.run_path(str(SCRIPT))


@pytest.fixture
def saved_reports():
    digest, inspection_hash, validation_hash = "a" * 64, "b" * 64, "c" * 64
    source = {"id": "inspection-id", "result": {"report_sha256": inspection_hash}}
    policy = {"version": "librarium.epubcheck.v1"}
    validator = {"name": "EPUBCheck", "version": "5.4.0", "java_major": 21}
    report = {
        "schema_version": "librarium.epub-validation.v1",
        "source_sha256": digest,
        "source_size": 1234,
        "policy": policy,
        "validator": validator,
        "outcome": "failed",
        "counts": {"fatal": 0, "error": 1, "warning": 0, "usage": 0, "info": None},
        "messages": [
            {
                "id": "RSC-005",
                "severity": "ERROR",
                "message": "missing modified",
                "locations": [{"path": "book.opf", "line": 1, "column": 140}],
            }
        ],
        "messages_truncated": False,
        "message_repetition_limit": 25,
        "process_exit_code": 1,
        "ready": False,
        "content_acceptance": "not_checked",
    }
    result = {
        name: report[name]
        for name in (
            "source_sha256",
            "source_size",
            "policy",
            "validator",
            "outcome",
            "counts",
            "messages_truncated",
            "message_repetition_limit",
            "process_exit_code",
            "ready",
            "content_acceptance",
        )
    }
    result.update(
        source_job_id=source["id"],
        source_report_sha256=inspection_hash,
        source_version=policy["version"],
        report_sha256=validation_hash,
    )
    validation = {
        "id": "validation-id",
        "kind": "epub_validation",
        "state": "succeeded",
        "result": result,
    }
    envelope = {
        "job_id": validation["id"],
        "source_job_id": source["id"],
        "source_sha256": digest,
        "source_report_sha256": inspection_hash,
        "report_sha256": validation_hash,
        "report": report,
    }
    return source, validation, envelope, digest


def test_completed_conformance_failure_is_accepted(acceptance, saved_reports):
    source, validation, envelope, digest = saved_reports
    acceptance["check_validation"](envelope, source, validation, digest, 1234)


def test_validation_post_uses_empty_json_and_own_replay_key(acceptance, monkeypatch):
    requests = []

    def respond(request, timeout):
        requests.append(request)
        response = io.BytesIO(b'{"id":"validation-id"}')
        response.status = 202
        return response

    monkeypatch.setattr(acceptance["urllib"].request, "urlopen", respond)
    actual = acceptance["request"](
        "/api/epub-inspections/source-id/validations", b"{}", "csrf", validation=True
    )
    assert actual == {"id": "validation-id"}
    request = requests[0]
    assert request.get_method() == "POST"
    assert request.data == b"{}"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Idempotency-key") == acceptance["VALIDATION_KEY"]
    assert request.get_header("Idempotency-key") != acceptance["KEY"]
    assert request.get_header("X-csrftoken") == "csrf"
    assert request.get_header("Cookie") == "librarium_csrftoken=csrf"
    assert request.get_header("X-source-sha256") is None
    assert request.get_header("X-source-name") is None


def test_validation_post_requires_202(acceptance, monkeypatch):
    def respond(request, timeout):
        response = io.BytesIO(b'{"id":"validation-id"}')
        response.status = 200
        return response

    monkeypatch.setattr(acceptance["urllib"].request, "urlopen", respond)
    with pytest.raises(AssertionError):
        acceptance["request"](
            "/api/epub-inspections/source-id/validations", b"{}", "csrf", validation=True
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "source_job",
        "source_report",
        "digest",
        "policy",
        "validator",
        "summary",
        "unfinished",
        "ready",
        "exit",
        "empty_findings",
    ],
)
def test_validation_acceptance_rejects_broken_binding(acceptance, saved_reports, mutation):
    source, validation, envelope, digest = copy.deepcopy(saved_reports)
    if mutation == "source_job":
        envelope["source_job_id"] = "different-job"
    elif mutation == "source_report":
        envelope["source_report_sha256"] = "d" * 64
    elif mutation == "digest":
        envelope["report"]["source_sha256"] = "d" * 64
    elif mutation in {"policy", "validator"}:
        envelope["report"][mutation] = {"version": "different"}
    elif mutation == "summary":
        validation["result"]["counts"] = {"error": 0}
    elif mutation == "unfinished":
        validation["state"] = "failed"
    elif mutation == "ready":
        envelope["report"]["ready"] = True
    elif mutation == "exit":
        envelope["report"]["process_exit_code"] = 0
    else:
        envelope["report"]["messages"] = []
    with pytest.raises(AssertionError):
        acceptance["check_validation"](envelope, source, validation, digest, 1234)


def test_recovery_receipt_requires_actual_capture_and_start_markers(
    acceptance, tmp_path, monkeypatch
):
    from librarium import recovery_evidence
    from librarium.delivery_recovery import RecoveryError

    root = tmp_path / "recovery"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("LIBRARIUM_ARTIFACT_DIR", str(root))
    monkeypatch.setenv("LIBRARIUM_ACCEPTANCE_RECOVERY_DIR", str(root))
    with pytest.raises(RecoveryError):
        acceptance["retained_recovery"]()
    assert not (root / "recovery-rehearsal.json").exists()
    with pytest.raises(RecoveryError):
        acceptance["recovery_start"]()
    acceptance["recovery_capture"]()
    acceptance["recovery_start"]()
    marker = acceptance["read_recovery_marker"]("recovery-clock.json")
    assert marker["capture"]["schema"] == "librarium.recovery-capture.v1"
    assert marker["monotonic"] > 0
    assert (
        recovery_evidence.report_recovery(root / "recovery-rehearsal.json", None)["state"]
        == "unavailable"
    )


@pytest.mark.skipif(
    not os.environ.get("LIBRARIUM_POSTGRES_BIN"),
    reason="requires explicit matching PostgreSQL clients for isolated recovery acceptance",
)
@pytest.mark.django_db(transaction=True)
def test_actual_database_and_artifact_restore_retains_measured_receipt(
    acceptance, tmp_path, settings, monkeypatch
):
    """Real PostgreSQL dump/restore plus preserved bytes and native checker reopens."""
    import hashlib
    import subprocess
    import sys
    import tarfile
    import uuid

    import psycopg
    from django.db import connection
    from librarium import epub_validations, file_inspections, recovery_evidence
    from librarium.services import advance, claim
    from psycopg import sql

    root = tmp_path / "source-artifacts"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    monkeypatch.setenv("LIBRARIUM_ARTIFACT_DIR", str(root))
    monkeypatch.setenv("LIBRARIUM_ACCEPTANCE_RECOVERY_DIR", str(root))
    source = acceptance["source_bytes"]()
    original = file_inspections.enqueue(
        io.BytesIO(source),
        acceptance["KEY"],
        hashlib.sha256(source).hexdigest(),
        acceptance["NAME"],
    )
    first = claim()
    assert first.pk == original.pk and advance(first.pk, first.lease_token)
    original.refresh_from_db()
    assert original.state == "succeeded"
    validation = epub_validations.enqueue(original.pk, acceptance["VALIDATION_KEY"])
    claimed = claim()
    assert claimed.pk == validation.pk and advance(claimed.pk, claimed.lease_token)
    validation.refresh_from_db()
    assert validation.state == "succeeded"
    acceptance["recovery_capture"]()
    project = SCRIPT.parents[2]
    binaries = Path(os.environ["LIBRARIUM_POSTGRES_BIN"])
    assert binaries.is_absolute(), "explicit_postgresql_client_directory_required"
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "librarium.settings",
        "PGDATABASE": connection.settings_dict["NAME"],
        "PGHOST": connection.settings_dict["HOST"],
        "PGPORT": str(connection.settings_dict["PORT"]),
        "PGUSER": connection.settings_dict["USER"],
        "PGPASSWORD": connection.settings_dict["PASSWORD"],
        "LIBRARIUM_SECRET_KEY": "isolated-recovery-test-" + "x" * 60,
        "PYTHONPATH": str(project / "backend"),
    }
    dump, archive = tmp_path / "database.dump", tmp_path / "artifacts.tar"
    result = subprocess.run(
        [
            str(binaries / "pg_dump"),
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--lock-wait-timeout=10000",
            "--file",
            str(dump),
        ],
        env=env,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, "isolated_dump_failed"
    with tarfile.open(archive, "w") as stream:
        for path in root.iterdir():
            if path.name.startswith(("source-", "report-", "corrected-")):
                stream.add(path, arcname=path.name, recursive=False)
    restored = "librarium_rehearsal_restore_" + uuid.uuid4().hex[:12]
    acceptance["recovery_start"]()
    with psycopg.connect(**connection.get_connection_params(), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored)))
    try:
        restore_env = {
            **env,
            "PGDATABASE": restored,
            "LIBRARIUM_ACCEPTANCE_RESTORE_ARCHIVE": str(archive),
        }
        result = subprocess.run(
            [
                str(binaries / "pg_restore"),
                "--no-owner",
                "--no-acl",
                "--dbname",
                restored,
                str(dump),
            ],
            env=env,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, "isolated_restore_failed"
        checked = subprocess.run(
            [sys.executable, str(SCRIPT), "restore"],
            env=restore_env,
            capture_output=True,
            timeout=180,
            check=False,
        )
        assert checked.returncode == 0, "isolated_restored_evidence_failed"
        receipt = json.loads((root / "recovery-rehearsal.json").read_text())
        assert receipt["scope"] == "isolated_epub_database_artifacts"
        assert 0 < receipt["recovery_seconds"] < 180
        print(json.dumps(receipt, sort_keys=True))
        assert (
            recovery_evidence.report_recovery(root / "recovery-rehearsal.json", None)["state"]
            == "incomplete"
        )
    finally:
        with psycopg.connect(**connection.get_connection_params(), autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restored))
            )


def test_restored_support_schema_read_must_succeed(acceptance, tmp_path, monkeypatch):
    from django.core import management

    root = tmp_path / "markers"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("LIBRARIUM_ARTIFACT_DIR", str(root))
    monkeypatch.setenv("LIBRARIUM_ACCEPTANCE_RECOVERY_DIR", str(root))
    acceptance["recovery_capture"]()
    acceptance["recovery_start"]()

    def failed_schema(*args, stdout, **kwargs):
        stdout.write(
            json.dumps(
                {
                    "database": {"state": "available"},
                    "jobs": {"state": "observed"},
                    "storage": {"artifacts": {"state": "observed"}},
                    "schema_compatibility": {"state": "unavailable"},
                    "build": {
                        "state": "unknown",
                        "running_image_digest": None,
                        "running_image_state": "unknown",
                    },
                    "recovery": {"state": "incomplete"},
                }
            )
        )

    monkeypatch.setattr(management, "call_command", failed_schema)
    with pytest.raises(AssertionError):
        acceptance["retained_recovery"]()
