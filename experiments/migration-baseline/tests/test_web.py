import pytest
from django.test import Client, override_settings


def test_baseline_api_reads_the_lock_without_connecting_to_upstream(tmp_path):
    (tmp_path / "snapshots.lock.json").write_text('{"schema": 1, "sources": {}}')
    with override_settings(LAB_ROOT=tmp_path):
        response = Client().get("/api/lab/v1/baseline/")
    assert response.status_code == 200
    assert response.json()["sources"] == {}
    assert response.json()["migration_ready"] is False
    assert response["Cache-Control"] == "no-store"


def test_missing_baseline_is_explicitly_unavailable(tmp_path):
    with override_settings(LAB_ROOT=tmp_path):
        response = Client().get("/api/lab/v1/baseline/")
    assert response.status_code == 503
    assert response.json()["error"] == "baseline_unavailable"


@pytest.mark.parametrize("path", ["/", "/healthz/", "/api/lab/v1/baseline/", "/api/lab/v1/identity/"])
def test_the_experiment_has_no_http_mutation_routes(path):
    response = Client(enforce_csrf_checks=True).post(path)
    assert response.status_code in {403, 405}


def test_identity_slice_combines_two_pure_helpers_without_library_access():
    response = Client().get("/api/lab/v1/identity/", {
        "title": "The Test Book: An Edition", "authors": "Fixture Writer", "isbn": "0-306-40615-2",
    })
    assert response.status_code == 200
    assert response.json() == {
        "work_key": "test book|writer", "isbn13": "9780306406157", "scope": "experiment",
    }


def test_identity_input_is_bounded_and_invalid_isbn_is_not_invented():
    assert Client().get("/api/lab/v1/identity/", {"title": "x" * 1001}).status_code == 400
    assert Client().get("/api/lab/v1/identity/", {"isbn": "not-an-isbn"}).json()["isbn13"] is None


def test_unknown_hosts_and_frame_embedding_are_refused():
    assert Client().get("/healthz/", HTTP_HOST="untrusted.invalid").status_code == 400
    response = Client().get("/healthz/")
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response["Content-Security-Policy"]
