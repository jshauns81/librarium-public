import importlib
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

import pytest
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.utils import timezone
from librarium.models import Job, Work
from librarium.seed import seed
from librarium.services import advance, claim, enqueue


@pytest.fixture
def records(db):
    seed(12)


@pytest.mark.parametrize(
    "url", ["/api/works?q=%00", "/api/works?series=%00", "/api/works/%00", "/api/jobs?work_id=%00"]
)
def test_controls_are_json_bad_requests(client, records, url):
    result = client.get(url)
    assert result.status_code == 400
    assert result.json()["error"]


def test_bad_post_identifier_and_conflict_are_bounded(client, records):
    for value in ["\x00", "x" * 41]:
        result = client.post(
            "/api/jobs",
            {"work_id": value},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert result.status_code == 400
    result = client.post(
        "/api/jobs",
        {"work_id": "missing"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert result.status_code == 404
    with patch("librarium.views.enqueue", side_effect=IntegrityError):
        result = client.post(
            "/api/jobs",
            {"work_id": "demo-00001"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert result.status_code == 409


def test_collection_versions_and_series_come_from_records(client, records):
    item = Work.objects.get(pk="demo-00001")
    item.payload["source_version"] = "synthetic-test-v2"
    item.save()
    result = client.get("/api/works?q=Glass&series=The%20Meridian%20Papers").json()
    assert result["total"] == 1
    assert result["works"][0]["source_version"] == "synthetic-test-v2"


def test_request_reference_is_returned_for_recovery(client, records):
    key = str(uuid.uuid4())
    item = enqueue("demo-00001", key)
    assert client.get(f"/api/jobs/{item.pk}").json()["request_key"] == key


def test_fixture_controls_do_not_change_metadata_fingerprint(records):
    first = enqueue("demo-00003", str(uuid.uuid4()))
    worker = claim()
    advance(worker.pk, worker.lease_token)
    second = enqueue("demo-00003", str(uuid.uuid4()))
    assert first.input_fingerprint == second.input_fingerprint
    assert "inject_failure" not in first.input
    assert "fault" not in first.input


def test_title_finding_is_durable_and_not_recomputed_on_recovery(records):
    item = enqueue("demo-00002", str(uuid.uuid4()))
    old = claim()
    advance(old.pk, old.lease_token)
    advance(old.pk, old.lease_token)
    item.refresh_from_db()
    title = item.result["findings"][0]
    assert title["ok"] is False
    Job.objects.filter(pk=item.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    recovered = claim()
    with patch("librarium.services.title_finding", side_effect=AssertionError("recomputed")):
        advance(recovered.pk, recovered.lease_token)
        advance(recovered.pk, recovered.lease_token)
    item.refresh_from_db()
    assert item.state == "succeeded"
    assert item.result["findings"][0] == title
    assert len(item.result["findings"]) == 2


@pytest.mark.django_db(transaction=True)
def test_locked_job_is_skipped_deterministically():
    seed(2)
    item = enqueue("demo-00001", str(uuid.uuid4()))

    def other_connection():
        close_old_connections()
        try:
            return claim()
        finally:
            close_old_connections()

    with transaction.atomic():
        Job.objects.select_for_update().get(pk=item.pk)
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(other_connection).result(timeout=3) is None


def test_exhaustion_clears_lease_and_claims_next_ready_work(records):
    first = enqueue("demo-00001", str(uuid.uuid4()))
    Job.objects.filter(pk=first.pk).update(
        attempts=3, lease_token=uuid.uuid4(), lease_until=timezone.now()
    )
    second = enqueue("demo-00002", str(uuid.uuid4()))
    assert claim().pk == second.pk
    first.refresh_from_db()
    assert first.state == "failed"
    assert first.lease_token is None
    assert first.lease_until is None


def test_wsgi_headers_cover_static_and_api(tmp_path, settings, records):
    settings.BASE_DIR = tmp_path
    root = tmp_path / "frontend/dist"
    root.mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Fixture</title>")
    from librarium import wsgi

    application = importlib.reload(wsgi).application
    for path, host, expected in [
        ("/", "localhost", "200"),
        ("/api/session", "localhost", "200"),
        ("/", "untrusted.invalid", "400"),
        ("/api/session", "untrusted.invalid", "400"),
    ]:
        environ = {}
        setup_testing_defaults(environ)
        environ.update(PATH_INFO=path, HTTP_HOST=host)
        statuses = []
        headers = {}

        def started(status, values, exc_info=None, statuses=statuses, headers=headers):
            statuses.append(status)
            headers.update(dict(values))

        result = application(environ, started)
        try:
            assert b"".join(result)
        finally:
            if hasattr(result, "close"):
                result.close()
        assert statuses[0].startswith(expected)
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["Referrer-Policy"] == "no-referrer"


def test_non_test_settings_require_explicit_secret():
    environment = {**os.environ, "PYTHONPATH": "backend"}
    environment.pop("LIBRARIUM_SECRET_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "import librarium.settings"],
        env=environment,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"LIBRARIUM_SECRET_KEY" in result.stderr


def test_continuous_worker_retries_a_database_interruption(records):
    from django.core.management import call_command

    with (
        patch(
            "librarium.management.commands.inspection_worker.claim",
            side_effect=[OperationalError("fixture disconnect"), KeyboardInterrupt],
        ),
        patch("librarium.management.commands.inspection_worker.time.sleep") as pause,
    ):
        with pytest.raises(KeyboardInterrupt):
            call_command("inspection_worker")
        pause.assert_called_once_with(1)
