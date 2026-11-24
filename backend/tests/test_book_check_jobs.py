import json
import uuid
from copy import deepcopy

import pytest
import test_book_assessment as fixtures
from django.core.management import call_command
from librarium import book_assessment, library_check_jobs, services
from librarium.models import Job

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
artifact_store = fixtures.artifact_store
selected = fixtures.selected
pytestmark = pytest.mark.django_db(transaction=True)


def payload(selected):
    return {
        "version": selected.pin["version"],
        "sha256": selected.pin["sha256"],
        "catalogue_work_id": "w_fixture",
        "source_sha256": selected.job.target_id,
        "report_sha256": selected.job.result["report_sha256"],
        "reconciliation": str(selected.saved.pk),
    }


def enqueue(client, selected, *, key=None, value=None):
    return client.post(
        f"/api/epub-inspections/{selected.job.pk}/checks",
        json.dumps(payload(selected) if value is None else value),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
    )


def test_durable_assessment_and_offline_recovery(selected, client, settings):
    key = uuid.uuid4()
    reply = enqueue(client, selected, key=key)
    assert reply.status_code == 202
    job_id = reply.json()["id"]
    call_command("inspection_worker", once=True)
    job = Job.objects.get(pk=job_id)
    assert job.state == "succeeded"
    assert job.result["file_work_identity"]["status"] == "supported"
    assert job.result["duplicates"]["exact_bytes"]["status"] == "none_found"
    assert job.result["ready"] is False
    saved = deepcopy(job.result)
    report = {k: v for k, v in saved.items() if k != "result_fingerprint"}
    assert library_check_jobs.assessment_report(job) == report
    assert "content_identity_unconfirmed" in saved["blockers"]
    # A later change to the library file never rewrites the saved, historical result.
    selected.path.write_bytes(selected.raw[:-1] + bytes([selected.raw[-1] ^ 1]))
    assert library_check_jobs.assessment_report(job) == report
    assert saved["observation"] == "historical"
    assert saved["current_library_bytes"]["status"] == "same_bytes"
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    assert enqueue(client, selected, key=key).json()["id"] == job_id
    recovered = client.get(
        f"/api/epub-inspections/{selected.job.pk}/checks", {"request_key": str(key)}
    )
    assert recovered.json()["result"] == saved


def test_assessment_cancel_during_observation_cannot_publish(selected, client, monkeypatch):
    reply = enqueue(client, selected)
    assert reply.status_code == 202
    job_id = reply.json()["id"]
    original = book_assessment.assess

    def interrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        services.cancel(job_id)
        return result

    monkeypatch.setattr(book_assessment, "assess", interrupted)
    call_command("inspection_worker", once=True)
    job = Job.objects.get(pk=job_id)
    assert job.state == "cancelled" and job.result == {}
    with pytest.raises(library_check_jobs.CheckError):
        library_check_jobs.assessment_report(job)


@pytest.mark.parametrize("tamper", ["source", "work", "result"])
def test_a_foreign_or_changed_assessment_is_refused_when_read(selected, client, tamper):
    reply = enqueue(client, selected)
    assert reply.status_code == 202
    call_command("inspection_worker", once=True)
    job = Job.objects.get(pk=reply.json()["id"])
    if tamper == "result":
        job.result["duplicates"]["exact_bytes"]["status"] = "forged"
    else:
        job.input["intent"]["source_job_id" if tamper == "source" else "catalogue_work_id"] = str(
            uuid.uuid4()
        )
    job.save()
    with pytest.raises(library_check_jobs.CheckError):
        library_check_jobs.assessment_report(job)


def test_queued_policy_change_fails_without_reinterpreting_input(selected, client, monkeypatch):
    reply = enqueue(client, selected)
    assert reply.status_code == 202
    monkeypatch.setattr(book_assessment, "POLICY", "a_later_policy")
    call_command("inspection_worker", once=True)
    job = Job.objects.get(pk=reply.json()["id"])
    assert job.state == "failed" and job.result["error_code"] == "policy_unavailable"


def test_reused_keys_and_inspection_bindings_are_strict(selected, client):
    key = uuid.uuid4()
    first = enqueue(client, selected, key=key)
    assert first.status_code == 202
    assert (
        enqueue(
            client, selected, key=key, value=payload(selected) | {"sha256": "a" * 64}
        ).status_code
        == 409
    )
    assert (
        enqueue(client, selected, value=payload(selected) | {"source_sha256": "a" * 64}).status_code
        == 409
    )
    assert (
        enqueue(
            client, selected, value=payload(selected) | {"reconciliation": str(uuid.uuid4())}
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/epub-inspections/{uuid.uuid4()}/checks", {"request_key": str(key)}
        ).status_code
        == 409
    )
    assert library_check_jobs.recover("library_reconcile", key) is None


@pytest.mark.parametrize("legacy_version", [2, 3, 4])
def test_pending_old_assessment_refuses_upgrade_and_historical_stays_readable(
    selected, client, legacy_version
):
    from librarium.services import fingerprint

    reply = enqueue(client, selected)
    job = Job.objects.get(pk=reply.json()["id"])
    old_policy = f"librarium.book-assessment.v{legacy_version}"
    job.input["engine_policy"] = old_policy
    job.input_fingerprint = fingerprint(job.input)
    job.save()
    call_command("inspection_worker", once=True)
    job.refresh_from_db()
    assert job.state == "failed"
    assert job.result["error_code"] == "policy_unavailable"

    result = fixtures.run(selected)
    result.pop("reference_authentication")
    result.update(
        schema_version=job.input["engine_policy"], policy_version=job.input["engine_policy"]
    )
    if legacy_version < 4:
        result.pop("source_attribution")
        result["blockers"].remove("source_attribution_unconfirmed")
    for comparison in result["duplicates"]["content"]["comparisons"]:
        comparison.pop("document_text_overlap", None)
    if legacy_version == 2:
        result["duplicates"]["scope"] = "recorded_epub_formats"
        result["duplicates"].pop("recorded_files")
        result["duplicates"].pop("resolved_files")
        result["duplicates"]["other_formats"].pop("byte_comparison")
    result.update(input_fingerprint=job.input_fingerprint, read_only=True)
    result["result_fingerprint"] = fingerprint(result)
    job.state = "succeeded"
    job.result = result
    job.save()
    original = deepcopy(job.result)
    read = library_check_jobs.assessment_report(job)
    assert read["policy_version"] == old_policy
    assert ("source_attribution" in read) is (legacy_version >= 4)
    if legacy_version == 2:
        assert read["duplicates"]["scope"] == "recorded_epub_formats"
        assert "recorded_files" not in read["duplicates"]
    else:
        assert read["duplicates"]["scope"] == "all_recorded_formats"
        assert "recorded_files" in read["duplicates"]
    job.refresh_from_db()
    assert job.result == original
