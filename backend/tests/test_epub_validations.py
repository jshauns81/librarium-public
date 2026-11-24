"""Durable validation binds a preserved inspection without changing its assurance."""

import hashlib
import io
import uuid
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from librarium import artifacts, epub_validations, file_inspections
from librarium.epub_inspection import inspect_bytes
from librarium.models import Job
from librarium.services import advance, cancel, claim, fingerprint
from test_epub_inspection import archive
from test_file_inspections import historical

POLICY = {"version": "librarium.epubcheck.v1", "limits": {"max_report_bytes": 1024 * 1024}}
VALIDATOR = {"name": "EPUBCheck", "version": "5.4.0", "distribution_sha256": "c" * 64}


def fake_report(data, digest, policy, validator, **kwargs):
    return {
        "schema_version": "librarium.epub-validation.v1",
        "source_sha256": digest,
        "source_size": len(data),
        "policy": deepcopy(policy),
        "validator": deepcopy(validator),
        "outcome": "passed",
        "counts": {"fatal": 0, "error": 0, "warning": 0, "info": None, "usage": 0},
        "messages": [],
        "messages_truncated": False,
        "message_repetition_limit": 25,
        "process_exit_code": 0,
        "ready": False,
        "content_acceptance": "not_checked",
        "limitations": ["Conformance only; no content or identity claim."],
    }


@pytest.fixture
def validation_store(tmp_path, settings, monkeypatch, transactional_db):
    # Validation and correction heartbeats must see jobs on independent connections.
    MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    settings.LIBRARIUM_EPUBCHECK_DIR = "/test/epubcheck"
    settings.LIBRARIUM_JAVA = "/test/java"
    monkeypatch.setattr(
        epub_validations, "profile", lambda: (deepcopy(POLICY), deepcopy(VALIDATOR))
    )
    monkeypatch.setattr(epub_validations, "validate_isolated", fake_report)
    return root


@pytest.fixture
def source(validation_store):
    def make(name="Synthetic source.epub"):
        data = archive()
        digest = hashlib.sha256(data).hexdigest()
        job = file_inspections.enqueue(io.BytesIO(data), uuid.uuid4(), digest, name)
        value = inspect_bytes(data, digest)
        stored = artifacts.write_report(value)
        job.result = file_inspections._summary(
            job.pk, job.input, job.input_fingerprint, value, stored
        )
        job.state = "succeeded"
        job.checkpoint = 4
        job.save()
        return job

    return make


def complete(job):
    claimed = claim()
    assert claimed.pk == job.pk
    assert advance(claimed.pk, claimed.lease_token)
    job.refresh_from_db()
    return job


def test_capture_and_finished_report_retain_source_and_validator_pins(source):
    original = source()
    before = deepcopy(original.result)
    job = epub_validations.enqueue(original.pk, uuid.uuid4())
    assert job.kind == "epub_validation" and job.target_id == original.target_id
    assert job.input["source_job_id"] == str(original.pk)
    assert job.input["source_report_sha256"] == original.result["report_sha256"]
    assert job.input["source_input_fingerprint"] == original.input_fingerprint
    assert job.input["source_inspection_policy"] == original.input["policy"]
    assert job.input["policy"] == POLICY and job.input["validator"] == VALIDATOR
    done = complete(job)
    assert done.state == "succeeded" and done.checkpoint == 4
    assert done.result["outcome"] == "passed" and done.result["ready"] is False
    envelope = epub_validations.report(done)
    assert envelope["source_job_id"] == str(original.pk)
    assert envelope["source_report_sha256"] == original.result["report_sha256"]
    assert envelope["report"]["source_size"] == original.input["source_size"]
    original.refresh_from_db()
    assert original.result == before and original.result["epubcheck"] == "not_run"


def test_completed_nonconformance_is_not_a_worker_execution_failure(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())

    def findings(*args, **kwargs):
        value = fake_report(*args, **kwargs)
        value.update(outcome="failed", process_exit_code=1)
        value["counts"]["error"] = 1
        value["messages"] = [
            {
                "id": "RSC-005",
                "severity": "ERROR",
                "message": "Invalid markup",
                "locations": [{"path": "chapter.xhtml", "line": 2, "column": None}],
            }
        ]
        return value

    with patch.object(epub_validations, "validate_isolated", side_effect=findings):
        assert complete(job).state == "succeeded"
    assert job.result["outcome"] == "failed"
    assert epub_validations.report(job)["report"]["counts"]["error"] == 1


def test_warning_only_result_preserves_counts_and_is_passed(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())

    def warnings(*args, **kwargs):
        value = fake_report(*args, **kwargs)
        value["counts"]["warning"] = 40
        value["messages_truncated"] = True
        return value

    with patch.object(epub_validations, "validate_isolated", side_effect=warnings):
        complete(job)
    assert job.result["counts"]["warning"] == 40
    assert job.result["messages_truncated"] is True
    assert job.result["outcome"] == "passed"


def test_runtime_exception_is_safe_and_a_new_intent_can_retry(source):
    original = source()
    job = epub_validations.enqueue(original.pk, uuid.uuid4())
    with patch.object(
        epub_validations, "validate_isolated", side_effect=RuntimeError("/private/path secret")
    ):
        assert complete(job).state == "failed"
    assert "/private" not in str(job.result) + job.message and "secret" not in job.message
    assert "outcome" not in job.result
    retry = complete(epub_validations.enqueue(original.pk, uuid.uuid4()))
    assert retry.state == "succeeded"


def test_same_key_is_recovered_across_disabled_or_changed_current_profile(source, settings):
    original = source()
    key = uuid.uuid4()
    first = epub_validations.enqueue(original.pk, key)
    settings.LIBRARIUM_EPUBCHECK_DIR = ""
    with patch.object(epub_validations, "profile", side_effect=AssertionError("profile read")):
        assert epub_validations.enqueue(original.pk, key).pk == first.pk
    with pytest.raises(epub_validations.ValidationError):
        epub_validations.enqueue(original.pk, uuid.uuid4())
    other = source("Other source.epub")
    with pytest.raises(epub_validations.ValidationError):
        epub_validations.enqueue(other.pk, key)


def test_one_active_validation_per_source(source):
    original = source()
    first = epub_validations.enqueue(original.pk, uuid.uuid4())
    with pytest.raises(epub_validations.ValidationError):
        epub_validations.enqueue(original.pk, uuid.uuid4())
    cancel(first.pk)
    assert epub_validations.enqueue(original.pk, uuid.uuid4()).pk != first.pk


@pytest.mark.parametrize("change", ["capture", "fingerprint", "policy", "validator"])
def test_changed_pending_capture_cannot_run_under_a_new_profile(source, change):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    if change == "fingerprint":
        job.input_fingerprint = "b" * 64
    else:
        field = {"capture": "source_sha256", "policy": "policy", "validator": "validator"}[change]
        job.input[field] = "b" * 64 if change == "capture" else {"version": "other"}
        job.input_fingerprint = fingerprint(job.input)
    job.save()
    with patch.object(
        epub_validations, "validate_isolated", side_effect=AssertionError("runtime reached")
    ):
        assert complete(job).state == "failed"


@pytest.mark.parametrize("change", ["source", "source_report", "summary", "source_capture"])
def test_mutated_source_or_summary_refuses_a_saved_validation(source, validation_store, change):
    original = source()
    job = complete(epub_validations.enqueue(original.pk, uuid.uuid4()))
    if change == "source":
        (validation_store / f"source-{original.target_id}").write_bytes(b"changed")
    elif change == "source_report":
        original.result["report_sha256"] = "b" * 64
        original.save()
    elif change == "source_capture":
        original.input["source_name"] = "Changed.epub"
        original.save()
    else:
        job.result["counts"]["warning"] = 7
        job.save()
    with pytest.raises(
        (
            epub_validations.ValidationError,
            artifacts.ArtifactError,
            file_inspections.InspectionError,
        )
    ):
        epub_validations.report(job)


def test_source_changed_during_execution_never_publishes_success(source):
    original = source()
    job = epub_validations.enqueue(original.pk, uuid.uuid4())

    def changed(*args, **kwargs):
        Job.objects.filter(pk=original.pk).update(input_fingerprint="b" * 64)
        return fake_report(*args, **kwargs)

    with patch.object(epub_validations, "validate_isolated", side_effect=changed):
        assert complete(job).state == "failed"


@pytest.mark.parametrize(
    "change", ["digest", "size", "policy", "validator", "ready", "counts", "outcome", "exit"]
)
def test_inconsistent_process_reports_cannot_publish(source, change):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())

    def malformed(*args, **kwargs):
        value = fake_report(*args, **kwargs)
        field, replacement = {
            "digest": ("source_sha256", "b" * 64),
            "size": ("source_size", 1),
            "policy": ("policy", {}),
            "validator": ("validator", {}),
            "ready": ("ready", True),
            "counts": ("counts", {"fatal": False, "error": 0, "warning": 0, "info": 0, "usage": 0}),
            "outcome": ("outcome", "failed"),
            "exit": ("process_exit_code", 1),
        }[change]
        value[field] = replacement
        return value

    with patch.object(epub_validations, "validate_isolated", side_effect=malformed):
        assert complete(job).state == "failed"


def test_completed_captured_profile_stays_readable_after_current_identity_changes(source):
    job = complete(epub_validations.enqueue(source().pk, uuid.uuid4()))
    with patch.object(
        epub_validations, "profile", return_value=({"version": "future"}, {"version": "future"})
    ):
        assert epub_validations.report(job)["report"]["validator"] == VALIDATOR


def test_reported_error_messages_cannot_contradict_zero_aggregate_errors(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())

    def inconsistent(*args, **kwargs):
        value = fake_report(*args, **kwargs)
        value["messages"] = [
            {"id": "RSC-005", "severity": "ERROR", "message": "An error", "locations": []}
        ]
        return value

    with patch.object(epub_validations, "validate_isolated", side_effect=inconsistent):
        assert complete(job).state == "failed"


@pytest.mark.parametrize("field", ["outcome", "severity"])
def test_invalid_report_value_types_are_controlled_validation_errors(source, field):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    value = fake_report(archive(), job.target_id, POLICY, VALIDATOR)
    if field == "outcome":
        value["outcome"] = []
    else:
        value["messages"] = [
            {"id": "RSC-005", "severity": [], "message": "Invalid", "locations": []}
        ]
    with pytest.raises(epub_validations.ValidationError):
        epub_validations._validate_report(value, job.input)


def test_pending_old_current_profile_fails_without_launching_runtime(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    with (
        patch.object(epub_validations, "profile", return_value=({"version": "future"}, VALIDATOR)),
        patch.object(
            epub_validations, "validate_isolated", side_effect=AssertionError("runtime reached")
        ),
    ):
        assert complete(job).state == "failed"


@pytest.mark.parametrize("version", ["librarium.epub-structure.v3", "librarium.epub-structure.v4"])
def test_validation_can_bind_a_preserved_historical_structural_report(source, version):
    original = source()
    value = file_inspections.report(original)["report"]
    original.input["source_version"] = version
    original.input["policy"]["version"] = original.input["source_version"]
    original.input_fingerprint = fingerprint(original.input)
    value["policy"] = deepcopy(original.input["policy"])
    value.pop("content_evidence", None)
    value.pop("source_attribution", None)
    value.pop("document_text_evidence", None)
    value.pop("identifier_evidence", None)
    value["package"].pop("byte_sha256", None)
    if version.endswith(".v4"):
        historical(original, value, version)
    else:
        value.pop("contents_plan", None)
    stored = artifacts.write_report(value)
    original.result = file_inspections._summary(
        original.pk, original.input, original.input_fingerprint, value, stored
    )
    original.save()
    assert file_inspections.report(original)["report"] == value
    job = complete(epub_validations.enqueue(original.pk, uuid.uuid4()))
    assert job.input["source_inspection_policy"]["version"] == version
    assert epub_validations.report(job)["report"]["outcome"] == "passed"


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_enqueues_one_validation_job(source):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections

    original = source()
    key = uuid.uuid4()

    def submit():
        close_old_connections()
        try:
            return epub_validations.enqueue(original.pk, key).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert len(set(results)) == 1
    assert Job.objects.filter(kind="epub_validation").count() == 1


@pytest.mark.django_db(transaction=True)
def test_lease_expiration_fences_publication_and_recovery(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    item = claim()

    def expired(*args, **kwargs):
        Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        return fake_report(*args, **kwargs)

    with patch.object(epub_validations, "validate_isolated", side_effect=expired):
        assert not advance(item.pk, item.lease_token)
    job.refresh_from_db()
    assert job.state == "running" and not job.result
    assert complete(job).state == "succeeded" and job.attempts == 2


@pytest.mark.django_db(transaction=True)
def test_cancellation_is_visible_to_the_running_process_and_cannot_publish(source):
    import time

    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    item = claim()

    def cancelled(*args, interrupted, **kwargs):
        cancel(job.pk)
        deadline = time.monotonic() + 2
        while not interrupted() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert interrupted()
        return fake_report(*args, **kwargs)

    with (
        patch.object(epub_validations, "HEARTBEAT_SECONDS", 0.01),
        patch.object(epub_validations, "validate_isolated", side_effect=cancelled),
    ):
        assert not advance(item.pk, item.lease_token)
    job.refresh_from_db()
    assert job.state == "cancelled" and not job.result


@pytest.mark.django_db(transaction=True)
def test_runtime_and_artifact_work_do_not_hold_a_database_transaction(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())

    def checked(*args, **kwargs):
        assert not connection.in_atomic_block
        return fake_report(*args, **kwargs)

    with patch.object(epub_validations, "validate_isolated", side_effect=checked):
        assert complete(job).state == "succeeded"


@pytest.mark.django_db(transaction=True)
def test_worker_once_dispatches_one_validation_operation(source):
    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    call_command("inspection_worker", once=True, step_seconds=0)
    job.refresh_from_db()
    assert job.state == "succeeded" and job.checkpoint == 4


@pytest.mark.django_db(transaction=True)
def test_migration_reverse_refuses_to_discard_validation_jobs(source):
    original = source()
    job = epub_validations.enqueue(original.pk, uuid.uuid4())
    with pytest.raises(RuntimeError, match="validation"):
        MigrationExecutor(connection).migrate([("librarium", "0004_epub_inspection_jobs")])
    assert Job.objects.filter(pk=job.pk).exists()
    historical = (
        MigrationExecutor(connection)
        .loader.project_state(("librarium", "0005_epub_validation_jobs"))
        .apps.get_model("librarium", "Job")
    )
    historical.objects.filter(kind="epub_validation").delete()
    MigrationExecutor(connection).migrate([("librarium", "0004_epub_inspection_jobs")])
    MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


def test_database_rejects_invalid_validation_targets(source):
    original = source()
    job = epub_validations.enqueue(original.pk, uuid.uuid4())
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.create(
            kind="epub_validation",
            target_id="invalid",
            request_key=uuid.uuid4(),
            input=job.input,
            input_fingerprint=job.input_fingerprint,
        )


@pytest.mark.parametrize(
    "code,reason",
    [("timeout", "deadline"), ("unavailable", "isolation"), ("output_limit", "limit")],
)
def test_runtime_failures_explain_the_reason_without_recording_a_conformance_verdict(
    source, code, reason
):
    from librarium.epubcheck_process import ValidationProcessError

    job = epub_validations.enqueue(source().pk, uuid.uuid4())
    with patch.object(
        epub_validations, "validate_isolated", side_effect=ValidationProcessError(code)
    ):
        job = complete(job)
    assert job.state == "failed"
    assert reason in job.message
    assert "No conformance result" in job.message
    assert "outcome" not in job.result and job.result["ready"] is False
