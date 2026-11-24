import uuid
from unittest.mock import patch

import pytest
from django.test import Client
from librarium import epub_validations
from librarium.models import Job
from test_epub_validations import complete
from test_epub_validations import source as source  # noqa: PLC0414 -- Shared pytest fixture.
from test_epub_validations import validation_store as validation_store  # noqa: PLC0414


def url(original):
    return f"/api/epub-inspections/{original.pk}/validations"


def submit(client, original, *, key=None, body=b"{}", content_type="application/json", **headers):
    headers.setdefault("CONTENT_TYPE", content_type)
    return client.post(
        url(original),
        body,
        content_type=content_type,
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
        **headers,
    )


def test_explicit_csrf_intent_captures_a_job_without_running_java(source):
    original = source()
    client = Client(enforce_csrf_checks=True)
    assert submit(client, original).status_code == 403
    session = client.get("/api/session").json()
    assert session["epub_validation"] is True
    assert session["epub_validator"] == {
        "name": "EPUBCheck",
        "version": "5.4.0",
        "policy_version": "librarium.epubcheck.v1",
    }
    with patch.object(
        epub_validations, "validate_isolated", side_effect=AssertionError("web ran Java")
    ):
        response = submit(client, original, HTTP_X_CSRFTOKEN=session["csrf"])
    assert response.status_code == 202 and response["Cache-Control"] == "no-store"
    body = response.json()
    assert body["kind"] == "epub_validation" and body["state"] == "queued"
    assert body["source_job_id"] == str(original.pk)
    assert body["source_report_sha256"] == original.result["report_sha256"]
    assert body["source_size"] == original.input["source_size"]
    assert body["validator"]["version"] == "5.4.0"
    assert client.get("/api/jobs?kind=epub_validation").json()["jobs"][0]["id"] == body["id"]
    assert client.get("/api/jobs/history?kind=epub_validation").json()["total"] == 1


@pytest.mark.parametrize(
    "body,content_type,status",
    [
        (b"", "application/json", 400),
        (b"[]", "application/json", 400),
        (b'{"path":"/private"}', "application/json", 400),
        (b"{", "application/json", 400),
        (b"{}", "text/plain", 415),
        (b"x" * 1025, "application/json", 413),
    ],
    ids=[
        "empty",
        "array",
        "private-path",
        "malformed-json",
        "wrong-media-type",
        "oversized-body",
    ],
)
def test_invalid_submission_cannot_enqueue(source, client, body, content_type, status):
    original = source()
    assert submit(client, original, body=body, content_type=content_type).status_code == status
    assert not Job.objects.filter(kind="epub_validation").exists()


def test_unknown_queries_keys_and_source_ids_are_rejected(source, client):
    original = source()
    assert submit(client, original, key="invalid").status_code == 400
    assert (
        client.post(
            url(original) + "?path=x",
            b"{}",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/epub-inspections/{uuid.uuid4()}/validations",
            b"{}",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).status_code
        == 404
    )
    for query in [
        "?page=0",
        "?page=10001",
        "?page=1&page=2",
        "?x=1",
        "?request_key=bad",
        f"?request_key={uuid.uuid4()}&page=1",
    ]:
        assert client.get(url(original) + query).status_code == 400
    assert client.put(url(original)).status_code == 405


def test_recovery_survives_configuration_changes_and_is_exact_to_the_source(
    source, client, settings
):
    original = source()
    other = source("Other.epub")
    first = submit(client, original).json()
    settings.LIBRARIUM_EPUBCHECK_DIR = ""
    settings.LIBRARIUM_ARTIFACT_DIR = ""
    with patch("librarium.artifacts.read", side_effect=AssertionError("recovery read bytes")):
        assert (
            client.get(url(original) + "?request_key=" + first["request_key"]).json()["id"]
            == first["id"]
        )
        assert submit(client, original, key=first["request_key"]).json()["id"] == first["id"]
    assert client.get(url(other) + "?request_key=" + first["request_key"]).status_code == 409
    assert submit(client, other, key=first["request_key"]).status_code == 409
    assert client.get(url(original) + f"?request_key={uuid.uuid4()}").status_code == 404
    assert submit(client, original).status_code == 503


def test_history_is_bounded_paginated_and_scoped_to_the_selected_source(source, client):
    original = source()
    other = source("Other.epub")
    for _ in range(21):
        job = epub_validations.enqueue(original.pk, uuid.uuid4())
        Job.objects.filter(pk=job.pk).update(state="failed")
    epub_validations.enqueue(other.pk, uuid.uuid4())
    first = client.get(url(original)).json()
    second = client.get(url(original) + "?page=2").json()
    assert first["total"] == second["total"] == 21
    assert first["page_size"] == 20 and len(first["jobs"]) == 20 and len(second["jobs"]) == 1
    assert all(job["source_job_id"] == str(original.pk) for job in first["jobs"] + second["jobs"])


def test_report_binds_original_source_and_has_read_only_strict_routes(source, client):
    original = source()
    job = complete(epub_validations.enqueue(original.pk, uuid.uuid4()))
    endpoint = f"/api/epub-validations/{job.pk}/report"
    response = client.get(endpoint)
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {
        "job_id",
        "source_job_id",
        "source_sha256",
        "source_report_sha256",
        "report_sha256",
        "report",
    }
    assert body["source_report_sha256"] == original.result["report_sha256"]
    assert body["report"]["ready"] is False
    assert client.get(endpoint + "?x=1").status_code == 400
    assert client.post(endpoint, b"{}", content_type="application/json").status_code == 405
    assert client.get(f"/api/epub-validations/{original.pk}/report").status_code == 404
    assert client.get(f"/api/epub-validations/{uuid.uuid4()}/report").status_code == 404
