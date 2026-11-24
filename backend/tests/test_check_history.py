"""Paged reconciliation-job history and catalogue-filtered saved coverage discovery."""

import uuid

import pytest
import test_library_reconciliation as fixtures
from librarium.models import Job, LibraryReconciliation
from librarium.services import fingerprint
from test_library_check_jobs import PATH, payload, post

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
pytestmark = pytest.mark.django_db(transaction=True)


def test_reconciliation_job_history_pages_without_reading_sources(
    library, catalogue_fixture, client, settings
):
    value = payload(catalogue_fixture)
    first = post(client, value)
    assert first.status_code == 202
    data = first.json()
    assert data["catalogue_version"] == value["version"]
    assert data["catalogue_sha256"] == value["sha256"]
    job = Job.objects.get(pk=data["id"])
    for index in range(24):
        intent = {**job.input["intent"], "previous": str(uuid.uuid4())}
        captured = {**job.input, "intent": intent}
        Job.objects.create(
            kind="library_reconcile",
            target_id=fingerprint(intent),
            request_key=uuid.uuid4(),
            input=captured,
            input_fingerprint=fingerprint(captured),
            state="failed",
            result={"error_code": "library_changed"},
        )
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    page = client.get(PATH, {"page": "1"}).json()
    assert page["total"] == 25 and page["pages"] == 2 and page["page_size"] == 24
    assert len(page["jobs"]) == 24
    assert all(row["kind"] == "library_reconcile" for row in page["jobs"])
    assert all("result" not in row for row in page["jobs"])
    off_page = client.get(PATH, {"page": "2"}).json()["jobs"]
    assert len(off_page) == 1
    failed = next(row for row in page["jobs"] if row["state"] == "failed")
    assert failed["result_summary"]["error_code"] == "library_changed"
    assert client.get(PATH).status_code == 400
    key = job.request_key
    assert client.get(PATH, {"request_key": str(key)}).json()["id"] == str(job.pk)
    for bad in (
        {"page": "1", "request_key": str(key)},
        {"page": "0"},
        {"page": "1", "version": value["version"]},
    ):
        assert client.get(PATH, bad).status_code == 400
    assert client.get(PATH + "?page=1&page=1").status_code == 400


def test_saved_reconciliations_filter_by_paired_catalogue_pin(
    library, catalogue_fixture, client, settings
):
    first = fixtures.run(catalogue_fixture)
    other = LibraryReconciliation.objects.create(
        request_key=uuid.uuid4(),
        catalogue_version="2026.01.01.1",
        catalogue_sha256="e" * 64,
        report={
            **first.report,
            "catalogue": {"version": "2026.01.01.1", "sha256": "e" * 64},
        },
    )
    settings.DIRECT_LIBRARY_ROOT = ""
    path = "/api/library/reconciliations"
    assert client.get(path).json()["total"] == 2
    version, sha256 = fixtures.pins(catalogue_fixture)
    data = client.get(path, {"version": version, "sha256": sha256}).json()
    assert data["total"] == 1 and data["pages"] == 1 and data["page"] == 1
    assert [row["request_key"] for row in data["reports"]] == [str(first.pk)]
    assert all("books" not in row for row in data["reports"])
    data = client.get(path, {"version": "2026.01.01.1", "sha256": "e" * 64, "page": "1"}).json()
    assert [row["request_key"] for row in data["reports"]] == [str(other.pk)]
    for bad in (
        {"version": version},
        {"sha256": sha256},
        {"version": "latest", "sha256": sha256},
        {"version": version, "sha256": "E" * 64},
        {"version": version, "sha256": sha256, "work": "w_fixture"},
    ):
        assert client.get(path, bad).status_code == 400
