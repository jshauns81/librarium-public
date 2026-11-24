"""The image probe uses an isolated WAL fixture and detects changed originals."""

import hashlib
import json
import runpy
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/native_library_acceptance.py"


@pytest.fixture
def acceptance():
    return runpy.run_path(str(SCRIPT))


def test_prepare_keeps_committed_title_in_wal_and_hashes_all_originals(acceptance, tmp_path):
    root = tmp_path / "library"
    source = b"synthetic epub source"
    acceptance["prepare"](root, source)
    assert (root / "metadata.db-wal").stat().st_size > 32
    copy = tmp_path / "private-reader"
    copy.mkdir()
    for name in ("metadata.db", "metadata.db-wal"):
        shutil.copyfile(root / name, copy / name)
    with closing(sqlite3.connect((copy / "metadata.db").as_uri() + "?mode=ro", uri=True)) as db:
        assert (
            db.execute("SELECT title FROM books WHERE id=1").fetchone()[0]
            == "Native container fixture"
        )
    manifest = acceptance["original_hashes"](root)
    assert (
        manifest["Synthetic Author/Native container fixture (1)/Native container fixture.epub"]
        == hashlib.sha256(source).hexdigest()
    )
    assert set(manifest) == {
        "metadata.db",
        "metadata.db-wal",
        "Synthetic Author/Native container fixture (1)/Native container fixture.epub",
        "Synthetic Author/Native container fixture (1)/cover.jpg",
    }


def test_prepare_refuses_existing_directory_and_preservation_check_fails_on_change(
    acceptance, tmp_path
):
    root = tmp_path / "library"
    acceptance["prepare"](root, b"source")
    with pytest.raises(FileExistsError):
        acceptance["prepare"](root, b"different")
    book = root / "Synthetic Author/Native container fixture (1)/Native container fixture.epub"
    book.chmod(0o644)
    book.write_bytes(b"changed")
    with pytest.raises(AssertionError):
        acceptance["original_hashes"](root)


def test_prepared_wal_fixture_works_with_native_reader_without_changing_sources(
    acceptance, tmp_path, settings
):
    from librarium import direct_library

    root = tmp_path / "library"
    acceptance["prepare"](root, b"preserved synthetic source")
    before = acceptance["original_hashes"](root)
    settings.DIRECT_LIBRARY_ROOT = str(root)
    listing = direct_library.browse()
    assert listing["books"][0]["title"] == "Native container fixture"
    assert listing["inventory"]["library_uuid"] == acceptance["LIBRARY_UUID"]
    assert listing["books"][0]["formats"][0]["available"] is True
    data, info = direct_library.cover("1", listing["inventory"]["token"])
    assert data == acceptance["PNG"] and info["media_type"] == "image/png"
    assert acceptance["original_hashes"](root) == before


def test_json_request_uses_csrf_and_native_key_without_upload_headers(acceptance, monkeypatch):
    import io

    observed = []

    def respond(request, timeout):
        observed.append(request)
        response = io.BytesIO(b'{"id":"native-job"}')
        response.status = 202
        return response

    monkeypatch.setattr(acceptance["urllib"].request, "urlopen", respond)
    result = acceptance["request"](
        "/api/direct-library/books/1/inspect", {"inventory": "a" * 64}, "csrf", expected=202
    )
    assert result == {"id": "native-job"}
    request = observed[0]
    assert json.loads(request.data) == {"inventory": "a" * 64}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("X-csrftoken") == "csrf"
    assert request.get_header("Idempotency-key") == acceptance["KEY"]
    assert request.get_header("X-source-sha256") is None
