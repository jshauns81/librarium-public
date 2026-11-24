import hashlib
import io
import uuid
from contextlib import contextmanager

import pytest
from librarium import file_inspections
from librarium.services import fingerprint

pytest_plugins = ["test_direct_library"]


@pytest.fixture
def store(tmp_path, settings, db):
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    return root


def test_library_origin_is_captured_and_request_replay_cannot_change_it(store):
    data = b"preserved source"
    digest = hashlib.sha256(data).hexdigest()
    key = uuid.uuid4()
    origin = {
        "library_uuid": str(uuid.uuid4()),
        "book_id": "23",
        "inventory": "a" * 64,
        "format": "EPUB",
    }
    job = file_inspections.enqueue(io.BytesIO(data), key, digest, "Book.epub", origin=origin)
    assert job.input["library_origin"] == origin
    assert job.input_fingerprint == fingerprint(job.input)
    assert file_inspections.enqueue(None, key, digest, "Book.epub", origin=origin).pk == job.pk
    with pytest.raises(file_inspections.InspectionError):
        file_inspections.enqueue(None, key, digest, "Book.epub", origin={**origin, "book_id": "24"})
    with pytest.raises(file_inspections.InspectionError):
        file_inspections.enqueue(None, key, digest, "Book.epub")


def test_artifact_store_cannot_overlap_authoritative_library(store, settings):
    from librarium import artifacts

    settings.DIRECT_LIBRARY_ROOT = str(store)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.ingest(io.BytesIO(b"x"), hashlib.sha256(b"x").hexdigest())


def test_native_book_inspection_preserves_file_and_replays_after_source_disappears(
    store, library, client
):
    from librarium import direct_library
    from librarium.models import Job

    token = direct_library.browse()["inventory"]["token"]
    source = next(library.rglob("*.epub"))
    original = source.read_bytes()
    key = str(uuid.uuid4())
    path = "/api/direct-library/books/1/inspect"
    first = client.post(
        path, {"inventory": token}, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
    )
    assert first.status_code == 202, first.content
    job = Job.objects.get(pk=first.json()["id"])
    assert job.input["library_origin"] == {
        "library_uuid": "library-uuid",
        "book_id": "1",
        "inventory": token,
        "format": "EPUB",
    }
    with direct_library.snapshot() as (db, _, _):
        assert job.input["library_book_uuid"] == direct_library.record(db, "1")["uuid"]
    assert job.input["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert source.read_bytes() == original
    source.unlink()
    repeated = client.post(
        path, {"inventory": token}, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
    )
    assert repeated.status_code == 200 and repeated.json()["id"] == str(job.pk)
    assert (
        client.post(
            path, {"inventory": "b" * 64}, content_type="application/json", HTTP_IDEMPOTENCY_KEY=key
        ).status_code
        == 409
    )


def test_native_inspection_refuses_changed_inventory_and_requires_csrf(store, library, client):
    from django.test import Client

    path = "/api/direct-library/books/1/inspect"
    assert (
        client.post(
            path,
            {"inventory": "0" * 64},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).status_code
        == 409
    )
    assert list(store.iterdir()) == []
    assert (
        Client(enforce_csrf_checks=True)
        .post(
            path,
            {"inventory": "0" * 64},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        .status_code
        == 403
    )


def test_source_change_at_capture_exit_publishes_no_artifact_or_job(store, client, monkeypatch):
    from librarium import direct_library
    from librarium.models import Job

    @contextmanager
    def changed_source(*args):
        yield io.BytesIO(b"source"), {"size_bytes": 6}
        raise direct_library.changed()

    monkeypatch.setattr(direct_library, "open_format", changed_source)
    result = client.post(
        "/api/direct-library/books/1/inspect",
        {"inventory": "a" * 64},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert result.status_code == 409
    assert Job.objects.count() == 0
    assert list(store.iterdir()) == []
