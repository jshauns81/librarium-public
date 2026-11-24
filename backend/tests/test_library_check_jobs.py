import json
import uuid
from datetime import timedelta

import pytest
import test_library_reconciliation as fixtures
from django.core.management import call_command
from django.db import connections
from django.utils import timezone
from librarium import direct_library, library_reconciliation, services
from librarium.models import Job, LibraryReconciliation

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
pytestmark = pytest.mark.django_db(transaction=True)
PATH = "/api/library/reconciliation-jobs"


def payload(catalogue_fixture):
    version, sha256 = fixtures.pins(catalogue_fixture)
    with direct_library.snapshot() as (_, _, info):
        inventory = {key: info[key] for key in ("token", "library_uuid")}
    return {"version": version, "sha256": sha256, "inventory": inventory}


def post(client, value, key=None, path=PATH):
    return client.post(
        path,
        json.dumps(value),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
    )


def test_queue_returns_before_inventory_work_and_survives_new_connection(
    library, catalogue_fixture, client, monkeypatch
):
    value = payload(catalogue_fixture)
    original = library_reconciliation.inventory
    monkeypatch.setattr(library_reconciliation, "inventory", lambda: pytest.fail("request scan"))
    reply = post(client, value)
    assert reply.status_code == 202
    job_id = reply.json()["id"]
    assert reply.json()["state"] == "queued"
    assert not LibraryReconciliation.objects.exists()
    monkeypatch.setattr(library_reconciliation, "inventory", original)
    connections.close_all()
    call_command("inspection_worker", once=True, step_seconds=0)
    job = Job.objects.get(pk=job_id)
    assert job.state == "succeeded"
    saved = LibraryReconciliation.objects.get(pk=job.request_key)
    assert saved.report["total"] == 1
    assert job.result["reconciliation"] == str(saved.pk)
    assert job.result["ready"] is False
    assert client.get("/api/jobs/history", {"kind": "library_reconcile"}).json()["total"] == 1


def test_exact_replay_and_recovery_survive_removed_sources(
    library, catalogue_fixture, client, settings
):
    value, key = payload(catalogue_fixture), uuid.uuid4()
    first = post(client, value, key)
    assert first.status_code == 202
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    assert post(client, value, key).json()["id"] == first.json()["id"]
    recovered = client.get(PATH, {"request_key": str(key)})
    assert recovered.status_code == 200
    assert recovered.json()["id"] == first.json()["id"]
    value["sha256"] = "a" * 64
    assert post(client, value, key).status_code == 409
    assert Job.objects.count() == 1


def test_metadata_change_before_worker_fails_without_partial_report(
    library, catalogue_fixture, client
):
    value = payload(catalogue_fixture)
    reply = post(client, value)
    assert reply.status_code == 202
    fixtures.update(library, "UPDATE books SET title='Later version'")
    call_command("inspection_worker", once=True)
    job = Job.objects.get(pk=reply.json()["id"])
    assert job.state == "failed"
    assert job.result["error_code"] == "library_changed"
    assert "Later version" not in json.dumps(job.result)
    assert not LibraryReconciliation.objects.exists()


@pytest.mark.parametrize("invalidate", ["cancel", "replace", "expire"])
def test_lost_worker_cannot_publish_reconciliation(
    library, catalogue_fixture, client, monkeypatch, invalidate
):
    reply = post(client, payload(catalogue_fixture))
    assert reply.status_code == 202
    job_id = reply.json()["id"]
    original = library_reconciliation.build_report

    def interrupted(*args, **kwargs):
        report = original(*args, **kwargs)
        if invalidate == "cancel":
            services.cancel(job_id)
        elif invalidate == "replace":
            Job.objects.filter(pk=job_id).update(lease_token=uuid.uuid4())
        else:
            Job.objects.filter(pk=job_id).update(lease_until=timezone.now() - timedelta(seconds=1))
        return report

    monkeypatch.setattr(library_reconciliation, "build_report", interrupted)
    call_command("inspection_worker", once=True)
    assert not LibraryReconciliation.objects.exists()
    assert Job.objects.get(pk=job_id).state != "succeeded"


def test_expired_job_resumes_with_new_fence_and_completes(library, catalogue_fixture, client):
    reply = post(client, payload(catalogue_fixture))
    assert reply.status_code == 202
    first = services.claim()
    Job.objects.filter(pk=first.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    second = services.claim()
    assert second.pk == first.pk and second.lease_token != first.lease_token
    assert services.advance(first.pk, first.lease_token) is False
    assert services.advance(second.pk, second.lease_token) is True
    assert Job.objects.get(pk=first.pk).state == "succeeded"
    assert LibraryReconciliation.objects.count() == 1


def test_same_intent_has_one_active_job_and_recovery_has_no_implicit_latest(
    library, catalogue_fixture, client
):
    value = payload(catalogue_fixture)
    assert post(client, value).status_code == 202
    assert post(client, value).status_code == 409
    assert client.get(PATH).status_code == 400
    assert client.get(PATH, {"request_key": str(uuid.uuid4())}).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"version": "latest"},
        {"sha256": "x"},
        {"inventory": {"token": "a" * 64, "library_uuid": ""}},
        {"inventory": {"token": "x", "library_uuid": "library"}},
        {"previous": "latest"},
    ],
)
def test_rejects_unbound_or_ambiguous_queue_inputs(library, catalogue_fixture, client, change):
    value = payload(catalogue_fixture) | change
    assert post(client, value).status_code == 400
    assert not Job.objects.exists()


def test_queue_json_budget_duplicate_fields_and_csrf(client):
    for text, status in [("x" * 4097, 413), ('{"version":"a","version":"b"}', 400)]:
        assert client.post(PATH, text, content_type="application/json").status_code == status
    assert client.post(PATH, "{}", content_type="text/plain").status_code == 415
    from django.test import Client

    assert (
        Client(enforce_csrf_checks=True)
        .post(PATH, "{}", content_type="application/json")
        .status_code
        == 403
    )


def test_live_heartbeat_prevents_reclaim_during_observation(
    library, catalogue_fixture, client, monkeypatch
):
    import time

    from librarium import file_inspections, library_check_jobs

    reply = post(client, payload(catalogue_fixture))
    assert reply.status_code == 202
    original = library_reconciliation.build_report
    renewals = []
    renew = library_check_jobs.renew

    def renewed(*args):
        renewals.append(1)
        return renew(*args)

    def delayed(*args, **kwargs):
        time.sleep(0.3)
        assert services.claim() is None
        return original(*args, **kwargs)

    monkeypatch.setattr(file_inspections, "HEARTBEAT_SECONDS", 0.02)
    monkeypatch.setattr(library_check_jobs, "renew", renewed)
    monkeypatch.setattr(library_reconciliation, "build_report", delayed)
    job = services.claim()
    Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() + timedelta(seconds=0.2))
    assert services.advance(job.pk, job.lease_token)
    assert len(renewals) > 2
    assert Job.objects.get(pk=job.pk).state == "succeeded"


def test_concurrent_same_key_queue_creates_one_intent(library, catalogue_fixture):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from librarium import library_check_jobs

    value, key = payload(catalogue_fixture), str(uuid.uuid4())
    gate = Barrier(2)

    def submit():
        try:
            gate.wait(timeout=5)
            return library_check_jobs.enqueue("library_reconcile", value, key).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    assert Job.objects.count() == 1


def test_reconciliation_engine_policy_and_reverse_migration_are_fenced(
    library, catalogue_fixture, client, monkeypatch
):
    import importlib

    from django.apps import apps

    reply = post(client, payload(catalogue_fixture))
    assert reply.status_code == 202
    monkeypatch.setattr(library_reconciliation, "POLICY", "later_policy")
    call_command("inspection_worker", once=True)
    assert Job.objects.get(pk=reply.json()["id"]).state == "failed"
    assert not LibraryReconciliation.objects.exists()
    migration = importlib.import_module("librarium.migrations.0007_library_check_jobs")
    with pytest.raises(RuntimeError, match="preserve evidence"):
        migration.refuse_to_drop_check_jobs(apps, None)
