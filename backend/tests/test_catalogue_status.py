import copy
import io
import json
from datetime import timedelta
from typing import ClassVar
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from django.utils import timezone
from librarium import catalogue_status
from librarium.models import CatalogueStatus

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def poll_clock(monkeypatch):
    monkeypatch.setattr(catalogue_status, "_next_check", 0, raising=False)
    monkeypatch.setattr(catalogue_status, "_check_url", "", raising=False)


@pytest.fixture
def feed(settings):
    settings.LIBRARIUM_CATALOGUE_STATUS_URL = "https://catalogue.example.com"
    status = {
        "now": "2026-11-10T12:00:00+00:00",
        "published_version": "2026.11.10.1",
        "live": {
            "state": "idle",
            "paused": False,
            "stalled": False,
            "updated_at": "2026-11-10T11:00:00+00:00",
            "next_cycle_at": "2026-11-10T13:00:00+00:00",
            "phase": None,
            "sources": {},
        },
        "snapshot": {"version": "2026.11.10.1", "catalogue": {}, "changes": {}},
        "cycles": [
            {
                "started_at": "2026-11-10T11:00:00+00:00",
                "duration_s": 15.5,
                "stages": {"harvest": {"status": "ok", "error": None}},
                "tripped": [],
                "tripped_reasons": {},
                "per_source": {},
                "inbox_new_records": 0,
                "harvest_new_records": 2,
            }
        ],
    }
    covers = {
        "checked_at": status["now"],
        "downloaded_images": 4,
        "queued_images": 1,
        "failed_uploads": 0,
        "upscale": {
            "enabled": True,
            "paused": False,
            "state": "idle",
            "queued": 1,
            "completed": 3,
            "failed": 0,
        },
    }
    return status, covers


def poll(feed, monkeypatch, now=None):
    if now:
        monkeypatch.setattr(catalogue_status.time, "monotonic", lambda: now.timestamp())
    monkeypatch.setattr(
        catalogue_status,
        "fetch_json",
        lambda url, deadline: copy.deepcopy(feed[1] if url.endswith("/covers/status") else feed[0]),
    )
    return catalogue_status.tick(now=now)


def test_poll_scrubs_queries_error_samples_and_raw_reasons(feed, monkeypatch):
    feed[0]["live"]["last_query"] = "PRIVATE SEARCH"
    feed[0]["live"]["sources"]["publisher"] = {
        "asked": 1,
        "new": 0,
        "errors": 1,
        "nested_query_text": "PRIVATE SEARCH",
        "error_samples": ["PRIVATE PATH"],
    }
    cycle = feed[0]["cycles"][0]
    cycle["tripped"] = ["publisher"]
    cycle["tripped_reasons"] = {"publisher": "401 from GET /private/book: secret payload"}
    cycle["stages"]["harvest"]["error"] = "GET /private/request"
    assert poll(feed, monkeypatch)
    row = CatalogueStatus.objects.get()
    text = json.dumps(row.payload)
    assert "query" not in text.lower()
    assert "PRIVATE" not in text and "/private" not in text and "secret payload" not in text
    assert (
        row.payload["status"]["cycles"][0]["tripped_reasons"]["publisher"]
        == "API key rejected (401)"
    )
    assert row.fetched_at and not row.failure


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"live": [], "cycles": []},
        {"live": {"state": "idle", "paused": "no"}, "cycles": []},
    ],
)
def test_invalid_shapes_keep_last_good(feed, monkeypatch, bad):
    now = timezone.now()
    poll(feed, monkeypatch, now)
    good = CatalogueStatus.objects.get().payload
    feed = (bad, feed[1])
    poll(feed, monkeypatch, now + timedelta(seconds=61))
    row = CatalogueStatus.objects.get()
    assert row.payload == good
    assert row.fetched_at == now
    assert row.failure == "Invalid status response"


@pytest.mark.parametrize(
    "error,reason",
    [
        (TimeoutError("private"), "Status request timed out"),
        (URLError("private"), "Status service unreachable"),
        (ValueError("private"), "Invalid status response"),
    ],
)
def test_failure_retains_last_good_and_age(feed, monkeypatch, error, reason):
    now = timezone.now()
    poll(feed, monkeypatch, now)

    def fail(*args):
        raise error

    monkeypatch.setattr(catalogue_status, "fetch_json", fail)
    monkeypatch.setattr(catalogue_status.time, "monotonic", lambda: now.timestamp() + 61)
    catalogue_status.tick(now=now + timedelta(seconds=61))
    view = catalogue_status.saved(now + timedelta(seconds=301))
    assert view["state"] == "stale"
    assert view["age_seconds"] == 301
    assert view["failure"] == reason and view["status"]["live"]["state"] == "idle"
    assert catalogue_status.saved(now + timedelta(seconds=300))["state"] == "observed"


def test_disabled_is_unavailable_even_with_previously_saved_copy(feed, monkeypatch, settings):
    poll(feed, monkeypatch)
    settings.LIBRARIUM_CATALOGUE_STATUS_URL = ""
    assert not catalogue_status.tick()
    assert catalogue_status.saved()["state"] == "unavailable"


def test_source_change_does_not_serve_old_source(feed, monkeypatch, settings):
    poll(feed, monkeypatch)
    settings.LIBRARIUM_CATALOGUE_STATUS_URL = "https://other.example.com"
    assert catalogue_status.saved()["state"] == "unavailable"


def test_poll_is_due_once_a_minute_and_survives_worker_restart(feed, monkeypatch):
    now = timezone.now()
    assert poll(feed, monkeypatch, now)
    monkeypatch.setattr(catalogue_status, "_next_check", 0)
    monkeypatch.setattr(catalogue_status.time, "monotonic", lambda: now.timestamp() + 59)
    assert not catalogue_status.tick(now=now + timedelta(seconds=59))
    assert poll(feed, monkeypatch, now + timedelta(seconds=60))


def test_health_requests_never_fetch(feed, monkeypatch, client):
    poll(feed, monkeypatch)

    def fail(*args):
        pytest.fail("Request path attempted a BLC fetch")

    monkeypatch.setattr(catalogue_status, "fetch_json", fail)
    assert client.get("/api/catalogue/health").json()["telemetry"]["state"] == "observed"


class Reply(io.BytesIO):
    status = 200
    headers: ClassVar[dict] = {}

    def read1(self, size):
        return self.read(size)


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"live":NaN}', b'{"x":1,"x":2}'])
def test_transport_refuses_invalid_json(body):
    with (
        patch.object(catalogue_status, "open_url", return_value=Reply(body)),
        pytest.raises((ValueError, TypeError)),
    ):
        catalogue_status.fetch_json(
            "https://catalogue.example.com/v1/status", catalogue_status.time.monotonic() + 5
        )


def test_transport_caps_size_and_uses_get_without_credentials():
    with patch.object(
        catalogue_status, "open_url", return_value=Reply(b"x" * (catalogue_status.MAX_BYTES + 1))
    ) as request:
        with pytest.raises(catalogue_status.ResponseTooLarge):
            catalogue_status.fetch_json(
                "https://catalogue.example.com/v1/status", catalogue_status.time.monotonic() + 5
            )
        args, kwargs = request.call_args
        assert args[0].get_method() == "GET"
        assert not args[0].has_header("Authorization")
        assert 0 < kwargs["timeout"] <= 5


def test_malicious_or_credentialed_base_urls_are_refused():
    for base in [
        "file:///tmp/status",
        "https://" + "fixture:fixture@example.com",
        "https://example.com/?token=secret",
        "https://example.com/#fragment",
    ]:
        with pytest.raises(ValueError):
            catalogue_status.base_url(base)


def test_historical_cycles_accept_per_source_record_totals(feed):
    feed[0]["cycles"][0]["per_source"] = {"publisher": 3}
    assert catalogue_status.validate(*feed)["status"]["cycles"][0]["per_source"] == {"publisher": 3}


@pytest.mark.parametrize("code", [301, 302])
def test_redirects_are_rejected_without_following(feed, monkeypatch, code):
    from email.message import Message
    from urllib.request import HTTPErrorProcessor, build_opener

    headers = Message()
    headers["Location"] = "https://other.example.com/status"
    request = Request("https://catalogue.example.com/v1/status")
    opener = build_opener(catalogue_status.NoRedirect())
    with patch.object(opener, "open") as follow:
        response = Reply(b"")
        response.code, response.msg, response.info = code, "Redirect", lambda: headers
        response.headers = headers
        processor = HTTPErrorProcessor()
        processor.add_parent(opener)
        with pytest.raises(HTTPError) as error:
            processor.http_response(request, response)
        assert error.value.code == code
        error.value.close()
        follow.assert_not_called()


def test_cover_failure_keeps_both_parts_of_last_good_copy(feed, monkeypatch):
    now = timezone.now()
    poll(feed, monkeypatch, now)
    good = CatalogueStatus.objects.get().payload
    feed[0]["live"]["state"] = "harvest"

    def fetch(url, deadline):
        if url.endswith("/covers/status"):
            raise HTTPError(url, 503, "private error", {}, None)
        return feed[0]

    monkeypatch.setattr(catalogue_status.time, "monotonic", lambda: now.timestamp() + 61)
    monkeypatch.setattr(catalogue_status, "fetch_json", fetch)
    assert catalogue_status.tick(now + timedelta(seconds=61))
    row = CatalogueStatus.objects.get()
    assert row.payload == good and row.fetched_at == now
    assert row.failure == "Status service returned HTTP 503"


def test_worker_loop_does_not_touch_database_between_poll_checks(
    feed, monkeypatch, django_assert_num_queries
):
    poll(feed, monkeypatch)
    with django_assert_num_queries(0):
        for _ in range(10):
            assert not catalogue_status.tick()


def test_http_fetch_runs_outside_transaction(feed, monkeypatch):
    from django.db import connection

    def fetch(url, deadline):
        assert not connection.in_atomic_block
        return feed[1] if url.endswith("/covers/status") else feed[0]

    monkeypatch.setattr(catalogue_status, "fetch_json", fetch)
    assert catalogue_status.tick()


def test_slow_poll_cannot_overwrite_a_newer_worker_result(feed, monkeypatch):
    now = timezone.now()
    poll(feed, monkeypatch, now)
    good = CatalogueStatus.objects.get().payload
    newer = now + timedelta(seconds=62)

    def fetch(url, deadline):
        CatalogueStatus.objects.update(attempted_at=newer, fetched_at=newer, failure="")
        return feed[1] if url.endswith("/covers/status") else feed[0]

    monkeypatch.setattr(catalogue_status.time, "monotonic", lambda: now.timestamp() + 61)
    monkeypatch.setattr(catalogue_status, "fetch_json", fetch)
    assert not catalogue_status.tick(now + timedelta(seconds=61))
    row = CatalogueStatus.objects.get()
    assert row.fetched_at == newer and row.payload == good


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3 consecutive failures (HTTPStatusError: 503)", "Source request failed (503)"),
        ("HTTPStatusError: 401 for private request", "API key rejected (401)"),
        ("ISBN 9781234567503", "Source unavailable"),
    ],
)
def test_reason_recognizes_embedded_status_without_retaining_raw_text(raw, expected):
    assert catalogue_status.reason(raw) == expected
