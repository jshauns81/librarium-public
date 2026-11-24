"""Retired corrected-copy and delivery work stays readable history and is never run again."""

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from librarium import retired_jobs, services
from librarium.models import CorrectedEpub, DeliveryIntent, Job
from retired_history import make_delivery, make_job, make_output

OPERATOR = {"REMOTE_USER": "synthetic-operator"}
GENERATION = sorted(retired_jobs.GENERATION_KINDS)
DELIVERY = sorted(retired_jobs.DELIVERY_KINDS)
RETIRED = GENERATION + DELIVERY
OLD_CAPABILITY = {
    "librarium.worker_capability": "corrected-output-v1",
    "librarium.delivery_capability": "delivery-v1",
}


def retired(kind, state="queued", *, lease=None, result=None, **input_fields):
    """A stored row exactly as the retired code left it; only the model creates it."""
    value = {"title": "Synthetic title", "source_version": "retired", **input_fields}
    job = Job.objects.create(
        kind=kind,
        target_id=uuid.uuid4().hex + uuid.uuid4().hex,
        request_key=uuid.uuid4(),
        input=value,
        input_fingerprint="a" * 64,
        message="Held for review",
        result=result or {},
        state="queued",
    )
    if state != "queued":
        # The database refuses a running row unless the retired worker's capability is set.
        # Set it only to write the fixture, then drop it so the guards apply to what follows.
        with connection.cursor() as cursor:
            for setting, value in OLD_CAPABILITY.items():
                cursor.execute("SELECT set_config(%s, %s, true)", [setting, value])
        Job.objects.filter(pk=job.pk).update(
            state=state,
            lease_token=lease and uuid.uuid4(),
            lease_until=lease,
            attempts=1,
        )
        with connection.cursor() as cursor:
            for setting in OLD_CAPABILITY:
                cursor.execute("SELECT set_config(%s, '', true)", [setting])
        job.refresh_from_db()
    return job


def unchanged(job):
    before = Job.objects.filter(pk=job.pk).values().get()
    return lambda: Job.objects.filter(pk=job.pk).values().get() == before


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RETIRED)
@pytest.mark.parametrize("state", ["queued", "running"])
def test_the_worker_never_claims_or_advances_a_retired_kind(kind, state):
    expired = timezone.now() - timedelta(minutes=5)
    job = retired(kind, state, lease=expired if state == "running" else None)
    same = unchanged(job)
    assert services.claim() is None
    assert same()
    live = timezone.now() + timedelta(minutes=5)
    if state == "running":
        token = uuid.uuid4()
        with connection.cursor() as cursor:
            for setting, value in OLD_CAPABILITY.items():
                cursor.execute("SELECT set_config(%s, %s, true)", [setting, value])
        Job.objects.filter(pk=job.pk).update(lease_token=token, lease_until=live)
        with connection.cursor() as cursor:
            for setting in OLD_CAPABILITY:
                cursor.execute("SELECT set_config(%s, '', true)", [setting])
        same = unchanged(job)
        assert services.advance(job.pk, token) is False
        assert same()


@pytest.mark.django_db
def test_retired_rows_do_not_hide_work_the_worker_still_runs():
    retired("epub_delivery")
    retired("epub_correction")
    kept = Job.objects.create(
        kind="catalogue",
        target_id="w" * 8,
        request_key=uuid.uuid4(),
        input={"title": "Kept", "source_version": "v1"},
        input_fingerprint="b" * 64,
    )
    claimed = services.claim()
    assert claimed is not None and claimed.pk == kept.pk


def record_for(client, job, **extra):
    reply = client.get(f"/api/jobs/{job.pk}", **extra)
    assert reply.status_code == 200, reply.content
    return reply.json()


SENSITIVE = {
    "report": {"sha256": "c" * 64, "size": 10},
    "output": {"id": "00000000-0000-4000-8000-000000000001"},
    "delivery_id": "00000000-0000-4000-8000-000000000002",
    "receipt_id": "00000000-0000-4000-8000-000000000003",
    "actor": "synthetic-operator",
    "target": {"library_uuid": "synthetic-library", "book_id": "7"},
}


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RETIRED)
@pytest.mark.parametrize("session", [{}, OPERATOR], ids=["ordinary", "operator"])
def test_job_detail_returns_a_plain_historical_record(client, kind, session):
    job = retired(
        kind,
        "failed",
        result=dict(SENSITIVE),
        source_job_id="00000000-0000-4000-8000-000000000004",
        output=dict(SENSITIVE["output"]),
        actor="synthetic-operator",
        target=dict(SENSITIVE["target"]),
    )
    value = record_for(client, job, **session)
    assert value["id"] == str(job.pk)
    assert value["kind"] == kind and value["state"] == "failed"
    assert value["stored_state"] == "failed"
    assert value["message"] == "Held for review"
    assert value["retired"] is True
    assert value["title"] == "Synthetic title"
    assert value["created_at"] and value["updated_at"]
    assert value["result"] == {}
    assert {"source_job_id", "output", "generation_job_id", "report_sha256"}.isdisjoint(value)
    text = str(value)
    for secret in ("synthetic-operator", "synthetic-library", "report", "delivery_id", "receipt"):
        assert secret not in text


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RETIRED)
@pytest.mark.parametrize("state", ["queued", "running"])
def test_unfinished_retired_work_reads_as_finished_history(client, kind, state):
    job = retired(kind, state, lease=timezone.now() + timedelta(minutes=5))
    value = record_for(client, job)
    assert value["state"] == "cancelled" and value["stored_state"] == state
    assert value["message"] == retired_jobs.UNFINISHED_MESSAGE
    job.refresh_from_db()
    assert job.state == state


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RETIRED)
def test_an_old_row_with_a_bare_input_is_still_readable(client, kind):
    job = retired(kind)
    Job.objects.filter(pk=job.pk).update(input={})
    value = record_for(client, job)
    assert value["title"] == "" and value["kind"] == kind


@pytest.mark.django_db
@pytest.mark.parametrize("session", [{}, OPERATOR], ids=["ordinary", "operator"])
def test_the_retired_filter_returns_all_six_kinds_to_any_session(client, session):
    rows = {kind: retired(kind, result=dict(SENSITIVE)) for kind in RETIRED}
    kept = Job.objects.create(
        kind="catalogue",
        target_id="w" * 8,
        request_key=uuid.uuid4(),
        input={"title": "Kept", "source_version": "v1"},
        input_fingerprint="b" * 64,
    )
    reply = client.get("/api/jobs/history", {"kind": "retired"}, **session)
    assert reply.status_code == 200, reply.content
    value = reply.json()
    assert value["total"] == 6
    assert {row["kind"] for row in value["jobs"]} == set(RETIRED)
    assert {row["id"] for row in value["jobs"]} == {str(row.pk) for row in rows.values()}
    assert "synthetic-operator" not in str(value) and "receipt" not in str(value)
    everything = client.get("/api/jobs/history", **session).json()
    assert everything["total"] == 7 and str(kept.pk) in str(everything)
    for kind in RETIRED:
        single = client.get("/api/jobs/history", {"kind": kind}, **session)
        assert single.status_code == 200 and single.json()["total"] == 1
    listing = client.get("/api/jobs", {"kind": "retired"}, **session)
    assert listing.status_code == 200 and len(listing.json()["jobs"]) == 6


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RETIRED)
@pytest.mark.parametrize("state", ["queued", "running", "failed", "succeeded", "cancelled"])
def test_job_history_and_list_return_retired_kinds_with_the_shown_state(client, kind, state):
    job = retired(kind, state, lease=timezone.now() + timedelta(minutes=5))
    shown = "cancelled" if state in {"queued", "running"} else state
    reply = client.get("/api/jobs/history", {"kind": kind, "state": shown})
    assert reply.status_code == 200, reply.content
    assert reply.json()["total"] == 1
    row = reply.json()["jobs"][0]
    assert (row["id"], row["kind"], row["state"]) == (str(job.pk), kind, shown)
    assert client.get("/api/jobs/history", {"q": "synthetic"}).json()["total"] == 1
    listing = client.get("/api/jobs", {"kind": kind})
    assert listing.status_code == 200, listing.content
    assert [row["id"] for row in listing.json()["jobs"]] == [str(job.pk)]
    assert client.get("/api/jobs/history", {"kind": "not_a_kind"}).status_code == 400


@pytest.mark.django_db
def test_unfinished_retired_work_is_never_counted_as_active(client):
    for kind in RETIRED:
        retired(kind, "running", lease=timezone.now() + timedelta(minutes=5))
        retired(kind, "queued")
    live = Job.objects.create(
        kind="catalogue",
        target_id="w" * 8,
        request_key=uuid.uuid4(),
        input={"title": "Kept", "source_version": "v1"},
        input_fingerprint="b" * 64,
    )
    for state in ("active", "queued", "running"):
        reply = client.get("/api/jobs/history", {"state": state})
        assert [row["id"] for row in reply.json()["jobs"]] == (
            [str(live.pk)] if state in {"active", "queued"} else []
        )
    assert client.get("/api/jobs/history", {"state": "cancelled"}).json()["total"] == 12
    assert (
        client.get("/api/jobs/history", {"kind": "retired", "state": "active"}).json()["total"] == 0
    )
    listing = client.get("/api/jobs").json()["jobs"]
    assert len(listing) == 13
    assert [row["id"] for row in listing if row["state"] in {"queued", "running"}] == [str(live.pk)]
    assert all(row["state"] == "cancelled" for row in listing if row.get("retired"))


@pytest.mark.django_db
@pytest.mark.parametrize("kind", RETIRED)
@pytest.mark.parametrize("state", ["queued", "running"])
def test_the_cancel_route_cancels_stored_retired_work_through_the_database_guards(
    client, kind, state
):
    job = retired(kind, state, lease=timezone.now() + timedelta(minutes=5))
    path = f"/api/jobs/{job.pk}/cancel"
    assert client.post(path, "{}", content_type="application/json").status_code == 401
    assert client.post(path, "[]", content_type="application/json", **OPERATOR).status_code == 400
    assert client.post(path, "{}", content_type="text/plain", **OPERATOR).status_code == 400
    job.refresh_from_db()
    assert job.state == state
    reply = client.post(path, "{}", content_type="application/json", **OPERATOR)
    assert reply.status_code == 200, reply.content
    assert reply.json()["job"]["state"] == "cancelled"
    assert reply.json()["job"]["stored_state"] == "cancelled"
    job.refresh_from_db()
    assert job.state == "cancelled" and job.lease_token is None and job.lease_until is None
    assert job.message == retired_jobs.CANCELLED_MESSAGE
    assert "no library changes" not in job.message
    again = client.post(path, "{}", content_type="application/json", **OPERATOR)
    assert again.status_code == 200 and again.json()["job"]["state"] == "cancelled"


@pytest.mark.django_db
def test_the_ordinary_job_route_cancels_retired_work_too(client):
    job = retired("epub_correction", "running", lease=timezone.now() + timedelta(minutes=5))
    reply = client.post(f"/api/jobs/{job.pk}", "{}", content_type="application/json")
    assert reply.status_code == 200, reply.content
    assert reply.json()["stored_state"] == "cancelled" and reply.json()["retired"] is True
    job.refresh_from_db()
    assert job.state == "cancelled" and job.lease_until is None
    delivery = retired("epub_delivery")
    reply = client.post(f"/api/jobs/{delivery.pk}", "{}", content_type="application/json")
    assert reply.status_code == 200 and reply.json()["stored_state"] == "cancelled"


@pytest.mark.django_db
def test_the_cancel_route_leaves_every_other_job_alone(client):
    kept = Job.objects.create(
        kind="catalogue",
        target_id="w" * 8,
        request_key=uuid.uuid4(),
        input={"title": "Kept", "source_version": "v1"},
        input_fingerprint="b" * 64,
    )
    reply = client.post(
        f"/api/jobs/{kept.pk}/cancel", "{}", content_type="application/json", **OPERATOR
    )
    assert reply.status_code == 404
    assert (
        client.post(
            f"/api/jobs/{uuid.uuid4()}/cancel", "{}", content_type="application/json", **OPERATOR
        ).status_code
        == 404
    )
    kept.refresh_from_db()
    assert kept.state == "queued"


@pytest.mark.django_db
def test_stored_corrected_copies_and_delivery_evidence_remain_in_the_database():
    output, parts = make_output()
    job, intent, _ = make_delivery(output, parts, reserved=False)
    reconcile = make_job("delivery_reconcile", intent.pk)
    assert CorrectedEpub.objects.filter(pk=output.pk).exists()
    assert DeliveryIntent.objects.filter(pk=intent.pk, job=job).exists()
    assert reconcile.kind in retired_jobs.DELIVERY_KINDS


REMOVED_ROUTES = [
    ("post", "api/epub-inspections/{}/corrections"),
    ("get", "api/epub-inspections/{}/corrections"),
    ("get", "api/epub-corrections/{}/report"),
    ("get", "api/corrected-epubs/{}/validations"),
    ("post", "api/corrected-epubs/{}/validations"),
    ("get", "api/corrected-epubs/{}/download"),
    ("get", "api/output-validations/{}/report"),
    ("get", "api/delivery-preparations/{}"),
    ("get", "api/corrected-epubs/{}/delivery-preparations"),
    ("post", "api/corrected-epubs/{}/delivery-preparations"),
    ("get", "api/corrected-epubs/{}/deliveries"),
    ("post", "api/corrected-epubs/{}/deliveries"),
    ("get", "api/deliveries/{}"),
    ("get", "api/deliveries/{}/receipts/00000000-0000-4000-8000-000000000009"),
    ("post", "api/deliveries/{}/reconciliations"),
    ("post", "api/deliveries/{}/undos"),
    ("get", "api/epub-inspections/{}/preparation"),
    ("post", "api/epub-inspections/{}/source-check"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("method,route", REMOVED_ROUTES)
def test_removed_routes_return_the_ordinary_404(client, method, route):
    reply = getattr(client, method)("/" + route.format(uuid.uuid4()), **OPERATOR)
    assert reply.status_code == 404
