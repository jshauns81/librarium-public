"""Synthetic direct-library acceptance in the exact image, without Index or BLC."""

import base64
import hashlib
import json
import os
import runpy
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-container-native-library-v1"))
LIBRARY_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-synthetic-calibre-library"))
BOOK = "Synthetic Author/Native container fixture (1)"
SOURCE = BOOK + "/Native container fixture.epub"
MANIFEST = "native-acceptance.json"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1cAAAAASUVORK5CYII="
)


def prepare(root, source):
    """Create new disposable originals, including an unapplied committed WAL frame."""
    root = Path(root)
    root.mkdir(mode=0o755)
    book = root / BOOK
    book.mkdir(parents=True, mode=0o755)
    (root / SOURCE).write_bytes(source)
    (book / "cover.jpg").write_bytes(PNG)
    with tempfile.TemporaryDirectory(prefix="librarium-ci-calibre-") as temporary:
        database = Path(temporary) / "metadata.db"
        db = sqlite3.connect(database)
        try:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.executescript("""
                CREATE TABLE books(id INTEGER PRIMARY KEY,title TEXT,sort TEXT,path TEXT,
                    uuid TEXT,series_index REAL,pubdate TEXT);
                CREATE TABLE library_id(id INTEGER PRIMARY KEY,uuid TEXT);
                CREATE TABLE authors(id INTEGER PRIMARY KEY,name TEXT);
                CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY,book INTEGER,author INTEGER);
                CREATE TABLE data(id INTEGER PRIMARY KEY,book INTEGER,format TEXT,
                    uncompressed_size INTEGER,name TEXT);
                INSERT INTO books VALUES(1,'Title before WAL','Native container fixture',
                    'Synthetic Author/Native container fixture (1)','synthetic-book-uuid',1,NULL);
                INSERT INTO authors VALUES(1,'Synthetic Author');
                INSERT INTO books_authors_link VALUES(1,1,1);
            """)
            db.execute("INSERT INTO library_id VALUES(1,?)", (LIBRARY_UUID,))
            db.execute(
                "INSERT INTO data VALUES(1,1,'EPUB',?,'Native container fixture')", (len(source),)
            )
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("UPDATE books SET title='Native container fixture' WHERE id=1")
            db.commit()
            for name in ("metadata.db", "metadata.db-wal"):
                shutil.copyfile(Path(temporary) / name, root / name)
        finally:
            db.close()
    paths = [path for path in root.rglob("*") if path.is_file()]
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }
    (root / MANIFEST).write_text(json.dumps(hashes, sort_keys=True), encoding="utf-8")
    for path in [*paths, root / MANIFEST]:
        path.chmod(0o444)


def original_hashes(root):
    root = Path(root)
    expected = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    observed = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    assert observed == {*expected, MANIFEST}, "The reader created or removed library files"
    for name, digest in expected.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    return expected


def request(path, data=None, csrf=None, *, expected=200, raw=False):
    headers = {
        "Host": "lib.example.org",
        "X-Forwarded-Proto": "https",
        "Origin": "https://lib.example.org",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers.update(
            {
                "Content-Type": "application/json",
                "X-CSRFToken": csrf,
                "Cookie": f"librarium_csrftoken={csrf}",
                "Idempotency-Key": KEY,
            }
        )
    req = urllib.request.Request("http://127.0.0.1:8123" + path, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as reply:
        assert reply.status == expected, reply.status
        return reply.read() if raw else json.load(reply)


def check_saved(job, token, source_digest):
    assert job["state"] == "succeeded", job
    assert job["kind"] == "epub" and job["source_sha256"] == source_digest
    envelope = request(f"/api/epub-inspections/{job['id']}/report")
    assert envelope["source_sha256"] == envelope["report"]["source_sha256"] == source_digest
    assert envelope["report_sha256"] == job["result"]["report_sha256"]
    assert envelope["report"]["inspection_complete"] is True
    assert envelope["report"]["structural_check"] == "passed"
    assert envelope["report"]["ready"] is False
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "librarium.settings")
    import django

    django.setup()
    from librarium.models import Job

    captured = Job.objects.get(pk=job["id"])
    assert captured.input["library_origin"] == {
        "library_uuid": LIBRARY_UUID,
        "book_id": "1",
        "inventory": token,
        "format": "EPUB",
    }
    assert captured.input["source_sha256"] == source_digest


def check(*, existing=False):
    root = Path(os.environ["LIBRARIUM_DIRECT_LIBRARY_ROOT"])
    assert os.statvfs(root).f_flag & os.ST_RDONLY, (
        "The authoritative library mount must be read-only"
    )
    assert not os.environ.get("LIBRARIUM_LIBRARY_URL"), "An old service origin is configured"
    originals = original_hashes(root)
    session = request("/api/session")
    assert session["direct_library"] is True and session["file_inspections"] is True
    listing = request("/api/direct-library")
    assert listing["total"] == 1 and listing["read_only"] is True
    token = listing["inventory"]["token"]
    book = listing["books"][0]
    assert book["id"] == "1" and book["title"] == "Native container fixture", (
        "Committed WAL title was lost"
    )
    assert book["authors"] == ["Synthetic Author"]
    assert book["formats"][0]["available"] is True
    selected = request(
        "/api/direct-library/books/1?" + urllib.parse.urlencode({"inventory": token})
    )
    assert selected["inventory"]["token"] == token and selected["book"]["id"] == "1"
    cover = request(book["cover"]["url"], raw=True)
    assert hashlib.sha256(cover).hexdigest() == originals[BOOK + "/cover.jpg"]
    if existing:
        job = request("/api/epub-inspections?request_key=" + KEY)
    else:
        path = "/api/direct-library/books/1/inspect"
        job = request(path, {"inventory": token}, session["csrf"], expected=202)
        replay = request(path, {"inventory": token}, session["csrf"])
        assert replay["id"] == job["id"]
        for _ in range(80):
            job = request("/api/jobs/" + job["id"])
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.25)
        else:
            raise AssertionError("The independent worker did not complete the native inspection")
    check_saved(job, token, originals[SOURCE])
    check_cover_census(originals[BOOK + "/cover.jpg"])
    assert original_hashes(root) == originals
    print(
        "PASS: native WAL inventory, metadata, cover, origin-bound worker report and preserved originals"
        + (" survived replacement" if existing else " without Index")
    )


def check_cover_census(digest):
    from django.conf import settings
    from librarium import cover_reviews, library_read_model
    from librarium.models import CoverReviewEntry

    settings.LIBRARY_READ_MODEL = "serve"
    library_read_model.refresh()
    census = cover_reviews.start(str(uuid.uuid4()))
    for _ in range(6):
        if not cover_reviews.tick():
            break
    census.refresh_from_db()
    assert census.state == "complete" and census.scanned == 1
    assert census.remaining == census.unresolved == 0
    entry = CoverReviewEntry.objects.get(library_uuid=LIBRARY_UUID, book_uuid="synthetic-book-uuid")
    assert entry.calibre_id == 1 and entry.facts["sha256"] == digest
    assert (entry.facts["width"], entry.facts["height"]) == (1, 1)
    print("PASS: sandboxed cover census, UUID/digest binding and read-only mount")


def worker():
    assert not os.environ.get("LIBRARIUM_DIRECT_LIBRARY_ROOT")
    assert not Path("/library").exists(), "The worker must receive artifacts, not the library mount"
    assert os.environ["LIBRARIUM_ARTIFACT_DIR"] == "/artifacts"
    print("PASS: worker has preserved artifacts and no library mount")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "prepare":
        source = runpy.run_path(str(Path(__file__).with_name("epub_container_acceptance.py")))[
            "source_bytes"
        ]()
        prepare(Path(os.environ["LIBRARIUM_LIBRARY_HOST_PATH"]), source)
    elif mode == "check":
        check()
    elif mode == "verify":
        check(existing=True)
    elif mode == "worker":
        worker()
    else:
        raise ValueError("Choose prepare, check, verify or worker")
