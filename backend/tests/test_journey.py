import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import close_old_connections, connection
from django.test import Client
from django.utils import timezone
from librarium.models import Job, Work
from librarium.seed import seed
from librarium.services import advance, cancel, claim, enqueue


@pytest.fixture
def collection(db):
    seed(120)
    return Work.objects.get(pk="demo-00001")


def test_browse_detail_and_postgres_persistence(client, collection):
    assert connection.vendor == "postgresql"
    response = client.get("/api/works?q=glass&page=1").json()
    assert response["total"] > 0
    detail = client.get("/api/works/demo-00001").json()
    assert detail["synthetic"] is True
    assert detail["editions"][0]["id"] != detail["id"]
    assert detail["evidence"][0]["source"] == "synthetic-catalogue"
    key = str(uuid.uuid4())
    first = client.post(
        "/api/jobs",
        {"work_id": collection.pk},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert first.status_code == 202
    duplicate = client.post(
        "/api/jobs",
        {"work_id": collection.pk},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert duplicate.json()["id"] == first.json()["id"]
    reconnected = Client().get("/api/jobs").json()["jobs"][0]
    assert reconnected["state"] == "queued"
    assert reconnected["id"] == first.json()["id"]
    assert Job.objects.count() == 1


def test_duplicate_key_conflict_and_active_job_deduplication(collection):
    key = str(uuid.uuid4())
    job = enqueue(collection.pk, key)
    assert enqueue(collection.pk, key).pk == job.pk
    with pytest.raises(ValueError, match="active"):
        enqueue(collection.pk, str(uuid.uuid4()))
    with pytest.raises(ValueError, match="different"):
        enqueue("demo-00002", key)


def test_cancel_is_durable_terminal_and_old_worker_cannot_publish(collection):
    job = enqueue(collection.pk, str(uuid.uuid4()))
    claimed = claim()
    cancel(job.pk)
    assert not advance(claimed.pk, claimed.lease_token)
    job.refresh_from_db()
    assert job.state == "cancelled"
    assert job.result == {}
    assert claim() is None


def test_worker_crash_reclaims_checkpoint_and_fences_old_lease(collection):
    job = enqueue(collection.pk, str(uuid.uuid4()))
    old = claim()
    assert advance(old.pk, old.lease_token)
    Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    recovered = claim()
    assert recovered.pk == old.pk
    assert recovered.checkpoint == 1
    assert recovered.lease_token != old.lease_token
    assert not advance(old.pk, old.lease_token)
    for _ in range(3):
        advance(recovered.pk, recovered.lease_token)
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert job.result["read_only"] is True
    assert job.result["input_fingerprint"] == job.input_fingerprint
    assert job.attempts == 2


def test_fixture_failure_is_explicit_and_new_intent_can_retry(collection):
    failed = enqueue("demo-00003", str(uuid.uuid4()))
    item = claim()
    advance(item.pk, item.lease_token)
    failed.refresh_from_db()
    assert failed.state == "failed"
    assert "fixture" in failed.message.lower()
    retry = enqueue("demo-00003", str(uuid.uuid4()))
    item = claim()
    for _ in range(4):
        advance(item.pk, item.lease_token)
    retry.refresh_from_db()
    assert retry.state == "succeeded"
    assert Job.objects.filter(work_id="demo-00003").count() == 2


def test_findings_disclose_the_values_they_checked(collection):
    job = enqueue("demo-00002", str(uuid.uuid4()))
    worker = claim()
    for _ in range(4):
        advance(worker.pk, worker.lease_token)
    job.refresh_from_db()
    details = " ".join(finding["detail"] for finding in job.result["findings"])
    assert "9780306406158" in details
    assert "A Different Map" in details
    assert "A Map of Quiet Stars" in details


def test_api_boundaries_csrf_validation_and_bounded_reads(client, collection):
    strict = Client(enforce_csrf_checks=True)
    assert strict.post("/api/jobs", "{}", content_type="application/json").status_code == 403
    assert client.post("/api/jobs", "[]", content_type="application/json").status_code == 400
    assert client.get("/api/works?page=0").status_code == 400
    assert client.get("/api/works?q=" + "x" * 201).status_code == 400
    assert client.get("/api/works/missing").status_code == 404
    assert len(client.get("/api/works").json()["works"]) <= 24
    assert client.get("/api/jobs").headers["Cache-Control"] == "no-store"


def test_invalid_cancel_body_cannot_mutate_a_job(client, collection):
    job = enqueue(collection.pk, str(uuid.uuid4()))
    result = client.post(f"/api/jobs/{job.pk}", '{"unknown":true}', content_type="application/json")
    assert result.status_code == 400
    job.refresh_from_db()
    assert job.state == "queued"


def test_cancel_api_and_session_are_recoverable(client, collection):
    assert client.get("/api/session").json()["csrf"]
    job = enqueue(collection.pk, str(uuid.uuid4()))
    url = f"/api/jobs/{job.pk}"
    assert client.get(url).json()["state"] == "queued"
    first = client.post(url, "{}", content_type="application/json").json()
    second = client.post(url, "{}", content_type="application/json").json()
    assert first["state"] == "cancelled"
    assert second["revision"] == first["revision"]
    assert client.get(f"/api/jobs/{uuid.uuid4()}").status_code == 404


def test_local_frontend_proxy_can_send_csrf_verified_intent(collection):
    browser = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1:8123")
    token = browser.get("/api/session").json()["csrf"]
    result = browser.post(
        "/api/jobs",
        {"work_id": collection.pk},
        content_type="application/json",
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_X_CSRFTOKEN=token,
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert result.status_code == 202


def test_old_active_job_is_visible_after_thirty_newer_terminal_jobs(client, collection):
    oldest = enqueue(collection.pk, str(uuid.uuid4()))
    for number in range(2, 34):
        newer = enqueue(f"demo-{number:05}", str(uuid.uuid4()))
        cancel(newer.pk)
    jobs = client.get("/api/jobs").json()["jobs"]
    assert str(oldest.pk) in {job["id"] for job in jobs}
    assert sum(job["state"] == "cancelled" for job in jobs) <= 30


def test_selected_work_retains_its_result_beyond_recent_history(client, collection):
    oldest = enqueue(collection.pk, str(uuid.uuid4()))
    cancel(oldest.pk)
    for number in range(2, 34):
        cancel(enqueue(f"demo-{number:05}", str(uuid.uuid4())).pk)
    jobs = client.get(f"/api/jobs?work_id={collection.pk}").json()["jobs"]
    assert str(oldest.pk) in {job["id"] for job in jobs}


@pytest.mark.django_db(transaction=True)
def test_worker_commands_and_recovery_limit(collection):
    from django.core.management import call_command

    call_command("seed_demo", count=2)
    job = enqueue(collection.pk, str(uuid.uuid4()))
    call_command("inspection_worker", once=True, step_seconds=0)
    job.refresh_from_db()
    assert job.state == "succeeded"
    second = enqueue(collection.pk, str(uuid.uuid4()))
    Job.objects.filter(pk=second.pk).update(attempts=3)
    assert claim() is None
    second.refresh_from_db()
    assert second.state == "failed"
    with pytest.raises(ValueError):
        seed(0)


@pytest.mark.django_db(transaction=True)
def test_two_workers_cannot_claim_the_same_job():
    seed(2)
    enqueue("demo-00001", str(uuid.uuid4()))

    def worker():
        close_old_connections()
        try:
            item = claim()
            return str(item.pk) if item else None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert len([r for r in results if r]) == 1
