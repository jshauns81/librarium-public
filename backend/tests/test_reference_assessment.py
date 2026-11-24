"""Durable assessments bind an optional curated reference pin through the isolated worker."""

import json
import uuid
from copy import deepcopy

import pytest
import test_book_assessment as fixtures
import trust_store
from django.core.management import call_command
from librarium import book_assessment, content_trust, library_check_jobs, services
from librarium.models import Job
from librarium.services import fingerprint
from test_book_check_jobs import enqueue, payload

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
artifact_store = fixtures.artifact_store
selected = fixtures.selected
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def untrusted(settings):
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY = ""
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = ""
    return settings


@pytest.fixture
def curated(selected, untrusted, tmp_path):
    return trust_store.build(tmp_path / "trust", untrusted, selected.raw, selected.pin)


def run_check(client, selected, reference=None, key=None):
    value = payload(selected) | ({"reference": reference} if reference is not None else {})
    reply = enqueue(client, selected, key=key, value=value)
    assert reply.status_code == 202, reply.json()
    call_command("inspection_worker", once=True)
    return Job.objects.get(pk=reply.json()["id"])


def test_unpinned_check_never_reads_configured_trust(selected, curated, client, monkeypatch):
    monkeypatch.setattr(content_trust, "_open_root", lambda *_: pytest.fail("trust read"))
    job = run_check(client, selected)
    assert job.state == "succeeded"
    assert job.result["policy_version"] == "librarium.book-assessment.v6"
    auth = job.result["reference_authentication"]
    assert auth["status"] == "not_requested"
    assert auth["reason_codes"] == ["reference_not_pinned"]
    assert auth["source_sha256"] == selected.job.target_id
    assert auth["catalogue"] == {
        "version": selected.pin["version"],
        "sha256": selected.pin["sha256"],
        "work_id": "w_fixture",
    }
    assert "content_identity_unconfirmed" in job.result["blockers"]


def test_exact_reference_clears_only_content_identity(
    selected, curated, client, monkeypatch, settings
):
    key = uuid.uuid4()
    job = run_check(client, selected, curated.pin, key=key)
    assert job.state == "succeeded", job.result
    result = job.result
    auth = result["reference_authentication"]
    assert auth["status"] == "authenticated_reference_match"
    assert auth["claims"] == ["work_identity", "edition_identity", "language", "revision"]
    assert auth["reference_sha256"] == selected.job.target_id
    assert auth["registry_sha256"] == curated.registry_sha256
    assert auth["report_sha256"] == selected.job.result["report_sha256"]
    assert auth["checked_at"].endswith("+00:00")
    assert "content_identity_unconfirmed" not in result["blockers"]
    assert {"semantic_duplicates_unconfirmed", "writer_not_authorized"} <= set(result["blockers"])
    assert result["ready"] is False and result["correction_admission"] == "held"
    assert result["file_work_identity"]["content_authentication"] == "not_assessed"

    # Reading the saved assessment never re-authenticates.
    monkeypatch.setattr(content_trust, "authenticate", lambda *a, **k: pytest.fail("recheck"))
    monkeypatch.setattr(content_trust, "_open_root", lambda *_: pytest.fail("trust read"))
    read = library_check_jobs.assessment_report(job)
    assert read["reference_authentication"] == auth
    assert "content_identity_unconfirmed" not in read["blockers"]
    assert read["ready"] is False and read["correction_admission"] == "held"

    # Offline replay and recovery return the saved historical result unchanged.
    saved = deepcopy(job.result)
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY = ""
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = ""
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    value = payload(selected) | {"reference": curated.pin}
    assert enqueue(client, selected, key=key, value=value).json()["id"] == str(job.pk)
    recovered = client.get(
        f"/api/epub-inspections/{selected.job.pk}/checks", {"request_key": str(key)}
    )
    assert recovered.json()["result"] == saved
    assert recovered.json()["reference"] == curated.pin


def test_changed_candidate_bytes_are_different_not_excluded(selected, untrusted, tmp_path, client):
    store = trust_store.build(tmp_path / "trust", untrusted, selected.raw + b"x", selected.pin)
    job = run_check(client, selected, store.pin)
    auth = job.result["reference_authentication"]
    assert auth["status"] == "different_bytes"
    assert auth["claims"] == []
    assert "content_identity_unconfirmed" in job.result["blockers"]
    assert job.result["duplicates"]["exact_bytes"]["status"] == "none_found"


@pytest.mark.parametrize(
    "case, reason",
    [
        ("unconfigured", "trust_not_configured"),
        ("revoked", "reference_revoked"),
        ("other_registry", "registry_pin_mismatch"),
        ("other_work", "work_mismatch"),
    ],
)
def test_configured_but_unusable_reference_stays_bound_unconfirmed(
    selected, untrusted, tmp_path, client, case, reason
):
    def revoke(value):
        value["revocations"] = [
            {
                "reference_id": trust_store.REFERENCE,
                "revoked_at": "2026-02-01T00:00:00Z",
                "reason_code": "curation_withdrawn",
            }
        ]

    def other_work(value):
        value["publication"]["work_id"] = "w_other"
        value["coverage"]["expected_constituents"][0]["work_id"] = "w_other"

    store = trust_store.build(
        tmp_path / "trust",
        untrusted,
        selected.raw,
        selected.pin,
        configure=case != "unconfigured",
        edit_registry=revoke if case == "revoked" else None,
        edit_manifest=other_work if case == "other_work" else None,
    )
    pin = dict(store.pin)
    if case == "other_registry":
        pin["registry_sha256"] = "a" * 64
    job = run_check(client, selected, pin)
    assert job.state == "succeeded"
    auth = job.result["reference_authentication"]
    assert auth["status"] == "unconfirmed"
    assert reason in auth["reason_codes"]
    assert auth["reference_id"] == pin["reference_id"]
    assert auth["registry_sha256"] == pin["registry_sha256"]
    assert auth["manifest_sha256"] == pin["manifest_sha256"]
    assert "content_identity_unconfirmed" in job.result["blockers"]


def test_malformed_reference_request_is_refused_before_queueing(selected, untrusted, client):
    good = {
        "reference_id": "synthetic.reference-1",
        "registry_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
    }
    for bad in (
        good | {"url": "https://example.invalid/reference"},
        good | {"registry_sha256": "A" * 64},
        {k: v for k, v in good.items() if k != "manifest_sha256"},
        good | {"reference_id": "../escape"},
        None,
        "latest",
    ):
        reply = enqueue(client, selected, value=payload(selected) | {"reference": bad})
        assert reply.status_code == 400
    for extra in ({"kind": "book_assessment"}, {"request_key": str(uuid.uuid4())}):
        assert enqueue(client, selected, value=payload(selected) | extra).status_code == 400
    assert not Job.objects.filter(kind="book_assessment").exists()


def test_reference_selection_change_requires_new_request_key(selected, curated, client):
    key = uuid.uuid4()
    assert enqueue(client, selected, key=key).status_code == 202
    changed = payload(selected) | {"reference": curated.pin}
    assert enqueue(client, selected, key=key, value=changed).status_code == 409


def test_enqueue_and_recovery_never_read_trust_configuration(
    selected, curated, client, monkeypatch
):
    monkeypatch.setattr(content_trust, "_open_root", lambda *_: pytest.fail("trust read"))
    key = uuid.uuid4()
    value = payload(selected) | {"reference": curated.pin}
    reply = enqueue(client, selected, key=key, value=value)
    assert reply.status_code == 202
    data = reply.json()
    assert data["reference"] == curated.pin
    assert data["catalogue_version"] == selected.pin["version"]
    assert data["catalogue_sha256"] == selected.pin["sha256"]
    assert data["source_job_id"] == str(selected.job.pk)
    assert data["source_report_sha256"] == selected.job.result["report_sha256"]
    assert data["catalogue_work_id"] == "w_fixture"
    assert data["reconciliation_key"] == str(selected.saved.pk)
    job = Job.objects.get(pk=data["id"])
    assert job.input["authentication_policy"] == "librarium.content-reference-authentication.v1"
    assert job.input["intent"]["reference"] == curated.pin


def test_pending_v5_refuses_under_v6_and_saved_v5_stays_historical(selected, client):
    reply = enqueue(client, selected)
    job = Job.objects.get(pk=reply.json()["id"])
    job.input["engine_policy"] = "librarium.book-assessment.v5"
    job.input_fingerprint = fingerprint(job.input)
    job.save()
    call_command("inspection_worker", once=True)
    job.refresh_from_db()
    assert job.state == "failed" and job.result["error_code"] == "policy_unavailable"

    result = fixtures.run(selected)
    result.pop("reference_authentication")
    result.update(
        schema_version="librarium.book-assessment.v5", policy_version="librarium.book-assessment.v5"
    )
    result.update(input_fingerprint=job.input_fingerprint, read_only=True)
    result["result_fingerprint"] = fingerprint(result)
    job.state, job.result = "succeeded", result
    job.save()
    read = library_check_jobs.assessment_report(job)
    assert "reference_authentication" not in read


def test_tampered_reference_binding_is_refused_when_read(selected, curated, client):
    job = run_check(client, selected, curated.pin)
    result = deepcopy(job.result)
    result.pop("result_fingerprint")
    result["reference_authentication"]["reference_id"] = "synthetic.other"
    result["result_fingerprint"] = fingerprint(result)
    job.result = result
    job.save()
    with pytest.raises(library_check_jobs.CheckError):
        library_check_jobs.assessment_report(job)


def test_cancel_during_reference_authentication_cannot_publish(
    selected, curated, client, monkeypatch
):
    reply = enqueue(client, selected, value=payload(selected) | {"reference": curated.pin})
    job_id = reply.json()["id"]
    original = content_trust.authenticate

    def interrupted(*args, **kwargs):
        services.cancel(job_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(content_trust, "authenticate", interrupted)
    call_command("inspection_worker", once=True)
    job = Job.objects.get(pk=job_id)
    assert job.state == "cancelled" and job.result == {}


def test_budget_exhaustion_during_authentication_stays_unconfirmed(
    selected, curated, client, monkeypatch
):
    def exhausted(count):
        raise book_assessment._BudgetExceeded

    original = content_trust.authenticate

    def limited(*args, **kwargs):
        return original(*args, **{**kwargs, "checkpoint": exhausted})

    monkeypatch.setattr(content_trust, "authenticate", limited)
    job = run_check(client, selected, curated.pin)
    assert job.state == "succeeded"
    auth = job.result["reference_authentication"]
    assert auth["status"] == "unconfirmed"
    assert auth["reason_codes"] == ["authentication_budget_exhausted"]


# History and projections


def history(client, source_id, query):
    return client.get(f"/api/epub-inspections/{source_id}/checks", query)


def clone(job, count):
    for index in range(count):
        intent = {**job.input["intent"], "catalogue_work_id": f"w_clone_{index}"}
        captured = {**job.input, "intent": intent}
        Job.objects.create(
            kind="book_assessment",
            target_id=fingerprint(intent),
            request_key=uuid.uuid4(),
            input=captured,
            input_fingerprint=fingerprint(captured),
            state="succeeded",
            result={"policy_version": "librarium.book-assessment.v6", "large": "x" * 4096},
        )


def test_source_check_history_is_scoped_bounded_and_paged(selected, client):
    first = enqueue(client, selected)
    job = Job.objects.get(pk=first.json()["id"])
    clone(job, 24)
    foreign = {**job.input, "intent": {**job.input["intent"], "source_job_id": str(uuid.uuid4())}}
    Job.objects.create(
        kind="book_assessment",
        target_id=fingerprint(foreign["intent"]),
        request_key=uuid.uuid4(),
        input=foreign,
        input_fingerprint=fingerprint(foreign),
    )
    page = history(client, selected.job.pk, {"page": "1"}).json()
    assert page["total"] == 25 and page["pages"] == 2 and page["page_size"] == 24
    assert len(page["jobs"]) == 24
    second = history(client, selected.job.pk, {"page": "2"}).json()
    assert len(second["jobs"]) == 1 and second["page"] == 2
    rows = page["jobs"] + second["jobs"]
    assert {row["source_job_id"] for row in rows} == {str(selected.job.pk)}
    assert all("result" not in row for row in rows)
    assert str(job.pk) in {row["id"] for row in rows}
    assert history(client, selected.job.pk, {}).status_code == 400
    for bad in (
        {"page": "0"},
        {"page": "10001"},
        {"page": "x"},
        {"page": "1", "request_key": str(uuid.uuid4())},
        {"page": "1", "kind": "book_assessment"},
    ):
        assert history(client, selected.job.pk, bad).status_code == 400
    assert (
        client.get(f"/api/epub-inspections/{selected.job.pk}/checks?page=1&page=2").status_code
        == 400
    )
    assert history(client, uuid.uuid4(), {"page": "1"}).json()["total"] == 0


def test_history_summarises_saved_result_without_loading_it(selected, curated, client):
    job = run_check(client, selected, curated.pin)
    row = history(client, selected.job.pk, {"page": "1"}).json()["jobs"][0]
    assert row["id"] == str(job.pk)
    assert row["result_summary"] == {
        "policy_version": "librarium.book-assessment.v6",
        "assessed_at": job.result["assessed_at"],
        "error_code": None,
        "reference_authentication": "authenticated_reference_match",
        "exact_bytes": "none_found",
    }
    assert row["reference"] == curated.pin
    assert row["reconciliation_key"] == str(selected.saved.pk)


def test_sparse_historical_projection_stays_explicitly_unavailable(selected, client):
    reply = enqueue(client, selected)
    job = Job.objects.get(pk=reply.json()["id"])
    for name in ("source_report_sha256",):
        job.input.pop(name, None)
    job.input["intent"].pop("reconciliation")
    job.save()
    data = client.get(f"/api/jobs/{job.pk}").json()
    assert data["reconciliation_key"] is None
    assert data["reference"] is None
    assert data["source_job_id"] == str(selected.job.pk)


def test_check_request_body_bound_still_applies_with_reference(selected, curated, client):
    value = payload(selected) | {"reference": curated.pin}
    value["comparison_inspections"] = [
        {"job_id": str(uuid.uuid4()), "source_sha256": "a" * 64, "report_sha256": "b" * 64}
        for _ in range(8)
    ]
    assert len(json.dumps(value)) < 4096
    padded = json.dumps(value) + " " * 4096
    reply = client.post(
        f"/api/epub-inspections/{selected.job.pk}/checks",
        padded,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert reply.status_code == 413


def test_reference_curated_under_older_catalogue_authenticates_same_work(
    selected, untrusted, tmp_path, client
):
    def older(value):
        value["publication"].update(catalogue_version="2026.01.01.1", catalogue_sha256="e" * 64)

    store = trust_store.build(
        tmp_path / "trust", untrusted, selected.raw, selected.pin, edit_manifest=older
    )
    auth = run_check(client, selected, store.pin).result["reference_authentication"]
    assert auth["status"] == "authenticated_reference_match"
    assert auth["catalogue"]["sha256"] == selected.pin["sha256"]
    assert auth["reference_publication"]["catalogue_sha256"] == "e" * 64


def test_current_catalogue_resolver_uses_exact_ids_without_alias_remapping():
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    with closing(sqlite3.connect(":memory:")) as db:
        _resolver_checks(db, Path(__file__).parent / "fixtures/blc-schema.sql")


def _resolver_checks(db, schema):
    db.executescript(schema.read_text())
    db.executescript(
        "INSERT INTO work(id,title) VALUES('w_kept','Kept'),('w_merged','Merged'),"
        "('w_target','Target');"
        "INSERT INTO id_alias VALUES('w_merged','w_target'),('w_gone','w_target');"
        "INSERT INTO edition(id,work_id) VALUES('e_kept','w_kept'),('e_moved','w_target');"
        "INSERT INTO work_alias VALUES('w_target','Kept');"
    )
    resolver = book_assessment._CurrentCatalogue(db)
    assert resolver.work_current("w_kept")
    assert not resolver.work_current("w_merged")
    assert not resolver.work_current("w_gone")
    assert not resolver.work_current("w_unknown")
    assert resolver.edition_work("e_kept") == "w_kept"
    assert resolver.edition_work("e_moved") == "w_target"
    assert resolver.edition_work("e_unknown") is None
    db.execute("DROP TABLE id_alias")
    assert not resolver.work_current("w_kept")
