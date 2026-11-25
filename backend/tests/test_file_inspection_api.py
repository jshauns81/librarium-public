import hashlib
import io
import threading
import uuid
from unittest.mock import patch
from urllib.parse import quote

import pytest
from django.test import Client, RequestFactory
from librarium import file_inspections, views
from librarium.models import Job
from librarium.services import advance, claim


@pytest.fixture
def store(tmp_path, settings, transactional_db):
    # The worker's heartbeat must see jobs created through the HTTP boundary.
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    return root


def post(client, data=b"not a zip", key=None, name=None, **headers):
    values = {
        "HTTP_IDEMPOTENCY_KEY": str(key or uuid.uuid4()),
        "HTTP_X_SOURCE_SHA256": hashlib.sha256(data).hexdigest(),
    }
    if name is not None:
        values["HTTP_X_SOURCE_NAME"] = name
    values.update(headers)
    return client.post("/api/epub-inspections", data, content_type="application/epub+zip", **values)


def test_csrf_session_and_no_direct_inspection(db, store):
    client = Client(enforce_csrf_checks=True)
    assert post(client).status_code == 403
    session = client.get("/api/session").json()
    assert (
        session["file_inspections"] is True
        and session["file_inspection_max_bytes"] == 32 * 1024 * 1024
    )
    with patch(
        "librarium.file_inspections.inspect_isolated", side_effect=AssertionError("web parsed EPUB")
    ):
        result = post(client, name=quote("A synthetic café.epub"), HTTP_X_CSRFTOKEN=session["csrf"])
    assert result.status_code == 202
    job = result.json()
    assert job["kind"] == "epub" and job["title"] == "A synthetic café.epub"
    assert job["work_id"] == job["source_sha256"]
    assert job["source_version"] == "librarium.epub-structure.v11"
    assert result["Cache-Control"] == "no-store"
    assert client.get("/api/jobs?kind=epub").json()["jobs"][0]["id"] == job["id"]
    assert client.get("/api/jobs/history?kind=epub").json()["total"] == 1


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"HTTP_IDEMPOTENCY_KEY": "bad"}, 400),
        ({"HTTP_X_SOURCE_SHA256": "A" * 64}, 400),
        ({"HTTP_X_SOURCE_NAME": "bad%Q1"}, 400),
        ({"HTTP_X_SOURCE_NAME": "bad%FF"}, 400),
        ({"HTTP_X_SOURCE_NAME": "a%2Fb"}, 400),
        ({"HTTP_X_SOURCE_NAME": "a%5Cb"}, 400),
        ({"HTTP_X_SOURCE_NAME": "a%00b"}, 400),
        ({"HTTP_X_SOURCE_NAME": "a" * 241}, 400),
        ({"CONTENT_LENGTH": str(32 * 1024 * 1024 + 1)}, 413),
        ({"CONTENT_LENGTH": "-1"}, 400),
    ],
)
def test_bad_headers_refused_before_storage(db, store, client, headers, status):
    with patch("librarium.artifacts.ingest", side_effect=AssertionError("storage touched")):
        result = post(client, **headers)
    assert result.status_code == status
    assert Job.objects.count() == 0


def test_type_digest_disabled_and_exact_replay(db, store, client, settings):
    assert (
        client.post("/api/epub-inspections", b"x", content_type="multipart/form-data").status_code
        == 415
    )
    assert post(client, HTTP_X_SOURCE_SHA256="a" * 64).status_code == 400
    first = post(client)
    key = first.json()["request_key"]
    settings.LIBRARIUM_ARTIFACT_DIR = ""
    assert client.get("/api/session").json()["file_inspections"] is False
    with patch("librarium.artifacts.ingest", side_effect=AssertionError("body reread")):
        assert post(client, key=key).json()["id"] == first.json()["id"]
    assert post(client, key=key, name="other.epub").status_code == 409
    assert post(client, key=uuid.uuid4()).status_code == 503


def test_raw_request_stream_enforces_bound_without_length(db, store):
    request = RequestFactory().post(
        "/api/epub-inspections",
        b"x",
        content_type="application/epub+zip",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        HTTP_X_SOURCE_SHA256="a" * 64,
    )
    request.META.pop("CONTENT_LENGTH", None)
    request._stream = io.BytesIO(b"12345")
    with patch("librarium.file_inspections.MAX_SOURCE_BYTES", 4):
        result = views.epub_inspections(request)
    assert result.status_code == 413


def test_report_contract_methods_parameters_storage_and_bindings(db, store, client, monkeypatch):
    renewed = threading.Event()
    renew_lease = file_inspections.renew
    inspect_source = file_inspections.inspect_isolated

    def renew(*args):
        result = renew_lease(*args)
        if result:
            renewed.set()
        return result

    def inspecting(*args):
        report = inspect_source(*args)
        assert renewed.wait(5), "The report worker must renew before publishing API evidence"
        return report

    monkeypatch.setattr(file_inspections, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(file_inspections, "renew", renew)
    monkeypatch.setattr(file_inspections, "inspect_isolated", inspecting)
    result = post(client).json()
    url = f"/api/epub-inspections/{result['id']}/report"
    assert client.get(url).status_code == 409
    assert client.get(url + "?x=1").status_code == 400
    assert client.post(url, b"", content_type="application/json").status_code == 405
    assert client.get(f"/api/epub-inspections/{uuid.uuid4()}/report").status_code == 404
    item = claim()
    assert advance(item.pk, item.lease_token)
    response = client.get(url)
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {"job_id", "source_sha256", "report_sha256", "report"}
    assert body["report"]["source_sha256"] == result["source_sha256"]
    assert body["report"]["ready"] is False
    source = next(p for p in store.iterdir() if p.name.startswith("source-"))
    source.write_bytes(b"corrupt")
    assert client.get(url).status_code in {409, 503}


def test_recovery_lookup_is_bounded_read_only_and_works_without_storage(
    db, store, client, settings
):
    created = post(client).json()
    settings.LIBRARIUM_ARTIFACT_DIR = ""
    url = "/api/epub-inspections?request_key=" + created["request_key"]
    with (
        patch("librarium.artifacts.ingest", side_effect=AssertionError("storage touched")),
        patch("librarium.artifacts.read", side_effect=AssertionError("storage touched")),
    ):
        recovered = client.get(url)
    assert recovered.status_code == 200 and recovered.json() == created
    assert recovered["Cache-Control"] == "no-store"
    assert client.get("/api/epub-inspections?request_key=" + str(uuid.uuid4())).status_code == 404
    assert Job.objects.count() == 1
    for suffix in [
        "",
        "?request_key=bad",
        "?request_key=" + created["request_key"] + "&extra=1",
        "?request_key=" + created["request_key"] + "&request_key=" + created["request_key"],
    ]:
        assert client.get("/api/epub-inspections" + suffix).status_code == 400
    Job.objects.filter(pk=created["id"]).update(kind="catalogue")
    assert client.get(url).status_code == 409
    assert client.put("/api/epub-inspections").status_code == 405


@pytest.mark.django_db(transaction=True)
def test_lookup_during_unrecorded_upload_is_not_a_failure_verdict(store, client):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections
    from librarium import artifacts

    key = uuid.uuid4()
    entered, release = threading.Event(), threading.Event()
    real_ingest = artifacts.ingest

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return real_ingest(*args, **kwargs)

    def upload():
        close_old_connections()
        try:
            return post(Client(), key=key)
        finally:
            close_old_connections()

    with patch("librarium.artifacts.ingest", side_effect=blocked), ThreadPoolExecutor(1) as pool:
        future = pool.submit(upload)
        assert entered.wait(timeout=3)
        assert client.get("/api/epub-inspections?request_key=" + str(key)).status_code == 404
        release.set()
        created = future.result(timeout=3)
    assert created.status_code == 202
    assert (
        client.get("/api/epub-inspections?request_key=" + str(key)).json()["id"]
        == created.json()["id"]
    )
    assert Job.objects.count() == 1


def test_large_raw_upload_does_not_access_request_body_or_multipart_spool(db, store, client):
    from unittest.mock import PropertyMock

    with patch(
        "django.http.request.HttpRequest.body",
        new_callable=PropertyMock,
        side_effect=AssertionError("unbounded request.body access"),
    ):
        result = post(client, data=b"synthetic bytes" * (16 * 1024))
    assert result.status_code == 202
    job = Job.objects.get(pk=result.json()["id"])
    assert job.input["source_size"] > 4096
    assert job.state == "queued"


def test_oversized_lookup_key_is_bounded(db, store, client):
    assert client.get("/api/epub-inspections?request_key=" + "a" * 1000).status_code == 400


def test_arbitrarily_large_numeric_length_is_413_before_storage(db, store, client):
    with patch("librarium.artifacts.ingest", side_effect=AssertionError("storage touched")):
        assert post(client, CONTENT_LENGTH="9" * 100).status_code == 413
