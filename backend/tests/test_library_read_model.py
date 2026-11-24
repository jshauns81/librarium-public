import base64
import hashlib
import json
import logging
import sqlite3
from contextlib import closing

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory
from librarium import direct_library, direct_library_views, library_read_model
from librarium.models import CalibreBook, CalibreFormat, LibraryReadModel

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1cAAAAASUVORK5CYII="
)
GIF = b"GIF89a\x02\x00\x03\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x02\x00\x03\x00\x00\x02\x02D\x01\x00;"

pytestmark = pytest.mark.django_db


@pytest.fixture
def library(tmp_path, settings):
    """A Calibre-shaped library whose books exercise every ordering and search edge."""
    root = tmp_path / "library"
    root.mkdir()
    with closing(sqlite3.connect(root / "metadata.db")) as db, db:
        db.executescript("""
            -- Calibre declares these name and sort columns NOCASE: ASCII case is ignored.
            CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, sort TEXT COLLATE NOCASE,
                path TEXT, uuid TEXT, series_index REAL, pubdate TEXT, timestamp TEXT,
                last_modified TEXT, has_cover INTEGER);
            CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT COLLATE NOCASE);
            CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
            CREATE TABLE series(id INTEGER PRIMARY KEY, name TEXT COLLATE NOCASE);
            CREATE TABLE books_series_link(id INTEGER PRIMARY KEY, book INTEGER, series INTEGER);
            CREATE TABLE publishers(id INTEGER PRIMARY KEY, name TEXT COLLATE NOCASE);
            CREATE TABLE books_publishers_link(id INTEGER PRIMARY KEY, book INTEGER,
                publisher INTEGER);
            CREATE TABLE languages(id INTEGER PRIMARY KEY, lang_code TEXT);
            CREATE TABLE books_languages_link(id INTEGER PRIMARY KEY, book INTEGER,
                lang_code INTEGER, item_order INTEGER);
            CREATE TABLE identifiers(id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
            CREATE TABLE data(id INTEGER PRIMARY KEY, book INTEGER, format TEXT,
                uncompressed_size INTEGER, name TEXT);
            CREATE TABLE comments(id INTEGER PRIMARY KEY, book INTEGER, text TEXT);
            CREATE TABLE library_id(id INTEGER PRIMARY KEY, uuid TEXT);
            INSERT INTO library_id VALUES(1,'library-uuid');
            INSERT INTO books VALUES
                (1,'Actual Book','actual Book','Writer/Actual Book (1)','uuid-1',1.5,
                 '2020-03-01','2026-10-20','2026-10-28',1),
                (2,'Émile Story','Emile Story','Zola/Emile Story (2)','uuid-2',NULL,
                 '0101-01-01T00:00:00+00:00','2026-10-22','2026-10-28',0),
                (3,'beta',NULL,'Other/beta (3)','uuid-3',2.0,NULL,NULL,'2026-10-28',1),
                (4,'Zeta 100% _odd','zeta','Gone/Zeta (4)','uuid-4',0.5,
                 '2019-01-01','2026-10-21','2026-10-28',1),
                (5,'Ünïcode','Ünïcode','Writer/Unicode (5)','uuid-5',1.0,
                 'not a date','2026-10-20','2026-10-28',1);
            INSERT INTO authors VALUES(1,'Some Writer'),(2,'Émile Author'),(3,'Another');
            INSERT INTO books_authors_link VALUES(1,1,1),(2,2,2),(3,3,3),(4,4,3),(5,4,1),(6,5,1);
            INSERT INTO series VALUES(1,'Actual Series'),(2,'Second');
            INSERT INTO books_series_link VALUES(1,1,1),(2,2,1),(3,3,2),(4,4,1);
            INSERT INTO publishers VALUES(1,'A Publisher');
            INSERT INTO books_publishers_link VALUES(1,1,1),(2,4,1);
            INSERT INTO languages VALUES(1,'eng'),(2,'fra');
            INSERT INTO books_languages_link VALUES(1,1,1,0),(2,2,1,1),(3,2,2,0);
            INSERT INTO identifiers VALUES(1,1,'isbn','9780306406157'),(2,2,'uri','x'),
                (3,2,'isbn','9780306406157');
            INSERT INTO data VALUES(1,1,'EPUB',12,'Actual Book - Some Writer'),
                (2,2,'EPUB',99,'Emile Story'),(3,3,'PDF',NULL,'beta'),(4,3,'EPUB',-1,'beta'),
                (5,4,'EPUB',5,'Zeta'),(6,5,'EPUB',7,'Unicode');
            INSERT INTO comments VALUES(1,1,'<p>Original description</p>');
        """)
    for path, files in {
        "Writer/Actual Book (1)": {
            "Actual Book - Some Writer.epub": b"original epub",
            "cover.jpg": PNG,
        },
        "Zola/Emile Story (2)": {},
        "Other/beta (3)": {"beta.epub": b"beta epub bytes", "cover.jpg": GIF},
        "Writer/Unicode (5)": {"Unicode.epub": b"unicode", "cover.jpg": b"not an image"},
    }.items():
        folder = root / path
        folder.mkdir(parents=True)
        for name, raw in files.items():
            (folder / name).write_bytes(raw)
    settings.DIRECT_LIBRARY_ROOT = str(root)
    settings.LIBRARY_READ_MODEL = "serve"
    return root


def update(library, sql, values=()):
    with closing(sqlite3.connect(library / "metadata.db")) as db, db:
        db.execute(sql, values)


def call(view, path, params, *args):
    reply = view(RequestFactory().get(path, params), *args)
    return reply.status_code, json.loads(reply.content)


def listing(**params):
    return call(direct_library_views.index, "/api/direct-library", params)


def series(name):
    return call(direct_library_views.series, "/api/direct-library/series", {"name": name})


def detail(book_id, **params):
    return call(direct_library_views.book, f"/api/direct-library/books/{book_id}", params, book_id)


def without_observation(body):
    body = json.loads(json.dumps(body))
    if "inventory" in body:
        body["inventory"].pop("observed_at")
    return body


def share_forbidden(monkeypatch):
    def refuse():
        raise AssertionError("a served listing must not touch the library share")

    monkeypatch.setattr(direct_library, "directory", refuse)


REQUESTS = [
    (listing, {}),
    (listing, {"page": "2"}),
    (listing, {"page": "3"}),
    (listing, {"page": "9"}),
    (listing, {"order": "recent"}),
    (listing, {"order": "recent", "page": "2"}),
    (listing, {"q": "writer"}),
    (listing, {"q": "ACTUAL"}),
    (listing, {"q": "É"}),
    (listing, {"q": "é"}),
    (listing, {"q": "Ü"}),
    (listing, {"q": "%"}),
    (listing, {"q": "_"}),
    (listing, {"q": "another", "order": "recent"}),
    (listing, {"q": "nothing matches"}),
    (series, "Actual Series"),
    (series, "Second"),
    (series, "actual series"),
    (series, "Missing"),
]


@pytest.mark.parametrize(("request_kind", "selected"), REQUESTS)
def test_served_listing_is_identical_to_the_direct_reader(
    library, settings, monkeypatch, request_kind, selected
):
    monkeypatch.setattr(direct_library, "PAGE_SIZE", 2)
    library_read_model.refresh()

    def ask():
        return request_kind(selected) if request_kind is series else request_kind(**selected)

    settings.LIBRARY_READ_MODEL = "off"
    direct_status, direct = ask()
    settings.LIBRARY_READ_MODEL = "serve"
    with monkeypatch.context() as patch:
        share_forbidden(patch)
        served_status, served = ask()
    assert direct_status == served_status == 200
    assert json.dumps(without_observation(served)) == json.dumps(without_observation(direct))
    assert served["inventory"]["token"] == direct["inventory"]["token"]


def test_served_pages_cover_every_shape_the_fixture_needs(library, monkeypatch):
    """Guards the parity test against a fixture that stops exercising its edges."""
    monkeypatch.setattr(direct_library, "PAGE_SIZE", 2)
    library_read_model.refresh()
    share_forbidden(monkeypatch)
    titles = [book["title"] for page in (1, 2, 3) for book in listing(page=str(page))[1]["books"]]
    assert titles == ["beta", "Actual Book", "Émile Story", "Zeta 100% _odd", "Ünïcode"]
    recent = [
        book["id"]
        for page in (1, 2, 3)
        for book in listing(order="recent", page=str(page))[1]["books"]
    ]
    assert recent == ["2", "4", "5", "1", "3"]
    books = {book["id"]: book for page in (1, 2, 3) for book in listing(page=str(page))[1]["books"]}
    assert books["1"]["cover"]["media_type"] == "image/png"
    assert books["3"]["cover"]["media_type"] == "image/gif"
    assert books["5"]["cover"] is None
    assert books["2"]["formats"][0] == {
        "format": "EPUB",
        "name": "Emile Story.epub",
        "size_bytes": None,
        "recorded_size_bytes": 99,
        "available": False,
    }
    assert [entry["format"] for entry in books["3"]["formats"]] == ["EPUB", "PDF"]
    assert books["2"]["languages"] == ["fra", "eng"]
    assert books["2"]["published_at"] is None
    assert [book["id"] for book in listing(q="É")[1]["books"]] == ["2"]
    assert listing(q="é")[1]["books"] == []


def test_no_import_stale_model_and_other_root_fall_back_to_the_direct_reader(
    library, settings, tmp_path
):
    assert listing()[0] == 200 and not LibraryReadModel.objects.exists()
    library_read_model.refresh()
    assert library_read_model.current() is not None
    LibraryReadModel.objects.update(stale=True)
    assert library_read_model.current() is None
    LibraryReadModel.objects.update(stale=False, root=str(tmp_path / "elsewhere"))
    assert library_read_model.current() is None
    settings.LIBRARY_READ_MODEL = "refresh"
    LibraryReadModel.objects.update(root=str(library))
    assert library_read_model.current() is None


def test_a_pinned_token_from_another_observation_is_refused(library, monkeypatch):
    library_read_model.refresh()
    share_forbidden(monkeypatch)
    status, body = listing(inventory="0" * 64)
    assert status == 409 and body["code"] == "direct_library_changed"
    status, body = call(
        direct_library_views.series,
        "/api/direct-library/series",
        {"name": "Second", "inventory": "0" * 64},
    )
    assert status == 409 and body["code"] == "direct_library_changed"
    token = LibraryReadModel.objects.get().token
    assert listing(inventory=token)[0] == 200


def test_refresh_imports_once_per_calibre_change_and_keeps_known_hashes(library, monkeypatch):
    first = library_read_model.refresh()
    assert first["imported"] is True and first["books"] == 5
    imported = LibraryReadModel.objects.get()
    assert imported.library_uuid == "library-uuid" and imported.has_added
    assert library_read_model.refresh()["imported"] is False
    assert LibraryReadModel.objects.get().imported_at == imported.imported_at
    assert LibraryReadModel.objects.get().observed_at > imported.observed_at

    library_read_model.hash_pending(60)
    hashed = dict(CalibreFormat.objects.values_list("calibre_id", "sha256"))
    assert hashed[1] == hashlib.sha256(b"original epub").hexdigest()
    assert hashed[4] == hashlib.sha256(b"beta epub bytes").hexdigest()
    assert hashed[2] is None and hashed[3] is None  # recorded, not on the share

    calls = []
    original = library_read_model.digest

    def counted(parent, name, expected, deadline):
        calls.append(name)
        return original(parent, name, expected, deadline)

    monkeypatch.setattr(library_read_model, "digest", counted)
    update(library, "UPDATE books SET title='Actual Book, Revised' WHERE id=1")
    (library / "Other/beta (3)/beta.epub").write_bytes(b"changed beta epub")
    second = library_read_model.refresh()
    assert second["imported"] is True
    assert LibraryReadModel.objects.get().token != imported.token
    assert CalibreBook.objects.get(pk=1).title == "Actual Book, Revised"
    after = dict(CalibreFormat.objects.values_list("calibre_id", "sha256"))
    assert after[1] == hashed[1] and after[4] is None
    library_read_model.hash_pending(60)
    assert calls == ["beta.epub"]
    assert (
        CalibreFormat.objects.get(pk=4).sha256 == hashlib.sha256(b"changed beta epub").hexdigest()
    )


def test_refresh_reports_its_duration_and_the_work_sent_to_the_share(library, caplog):
    with caplog.at_level(logging.INFO, logger="librarium.library_read_model"):
        first = library_read_model.refresh()
        assert library_read_model.hash_pending(60) == 3
    # Four book folders exist: five format stats, four cover stats, three cover header reads.
    # The fifth book's folder is gone, so nothing is probed for it.
    assert first["stats"] == 9 and first["covers_read"] == 3
    assert isinstance(first["seconds"], float) and first["seconds"] >= 0
    imported, hashed = [record.getMessage() for record in caplog.records]
    assert imported.startswith("library_read_model_imported books=5 seconds=")
    assert imported.endswith(" stats=9 covers_read=3")
    assert hashed == "library_read_model_hashed files=3"

    update(library, "UPDATE books SET title='Actual Book, Revised' WHERE id=1")
    second = library_read_model.refresh()
    # Every file is stat-checked again; unchanged covers keep what the first import learned.
    assert second["imported"] and second["stats"] == 9 and second["covers_read"] == 0


def test_hashing_stops_inside_a_file_when_its_slice_runs_out(library, monkeypatch):
    library_read_model.refresh()
    (library / "Writer/Actual Book (1)/Actual Book - Some Writer.epub").write_bytes(
        b"x" * (3 * 1024 * 1024)
    )
    library_read_model.refresh(force=True)
    big = CalibreFormat.objects.get(pk=1)
    assert big.size == 3 * 1024 * 1024 and big.sha256 is None
    clock = [0.0]

    def ticking():
        clock[0] += 1
        return clock[0]

    monkeypatch.setattr(library_read_model.time, "monotonic", ticking)
    # Smallest first: the two small files fit, then the large one is cut off mid-read.
    assert library_read_model.hash_pending(6.5) == 2
    assert CalibreFormat.objects.get(pk=1).sha256 is None
    monkeypatch.undo()
    assert library_read_model.hash_pending(60) == 1
    assert (
        CalibreFormat.objects.get(pk=1).sha256 == hashlib.sha256(b"x" * 3 * 1024 * 1024).hexdigest()
    )


def test_a_refused_model_token_marks_the_model_stale_until_the_worker_catches_up(library):
    library_read_model.refresh()
    token = LibraryReadModel.objects.get().token
    update(library, "UPDATE books SET title='Renamed' WHERE id=1")
    status, body = detail("1", inventory=token)
    assert status == 409 and body["code"] == "direct_library_changed"
    assert LibraryReadModel.objects.get().stale is True
    status, body = listing()
    assert status == 200 and body["inventory"]["token"] != token
    assert body["books"][1]["title"] == "Renamed"
    library_read_model.refresh()
    refreshed = LibraryReadModel.objects.get()
    assert refreshed.stale is False and refreshed.token == body["inventory"]["token"]


def test_a_library_the_model_cannot_represent_is_never_served(library):
    library_read_model.refresh()
    for index in range(65):
        update(library, "INSERT INTO identifiers(book,type,val) VALUES(5,'x',?)", (str(index),))
    with pytest.raises(library_read_model.ReadModelError, match="book 5"):
        library_read_model.refresh()
    state = LibraryReadModel.objects.get()
    assert state.stale is True and "book 5" in state.error
    assert library_read_model.current() is None


def test_conflicting_single_values_and_missing_library_identity_refuse_import(library):
    update(library, "INSERT INTO books_series_link(book,series) VALUES(1,2)")
    with pytest.raises(library_read_model.ReadModelError, match="book 1"):
        library_read_model.refresh()
    update(library, "DELETE FROM books_series_link WHERE book=1 AND series=2")
    update(library, "UPDATE library_id SET uuid=NULL")
    with pytest.raises(library_read_model.ReadModelError, match="library UUID"):
        library_read_model.refresh()
    assert not CalibreBook.objects.exists()


def test_parity_compares_every_book_and_both_orders_with_the_direct_reader(library):
    library_read_model.refresh()
    report = library_read_model.parity()
    assert report["parity"] is True and report["books"] == 5 and report["current"] is True
    assert report["changes"] == {
        "added": [],
        "removed": [],
        "replaced": [],
        "identity_unknown": [],
        "changed": [],
    }
    assert report["order"] == {"title": True, "recent": True}

    CalibreBook.objects.filter(pk=3).update(cover_width=9, sort="z")
    CalibreBook.objects.filter(pk=4).update(uuid="other")
    report = library_read_model.parity()
    assert report["parity"] is False
    assert report["changes"]["changed"] == ["3"] and report["changes"]["replaced"] == ["4"]
    assert report["differences"]["3"] == ["cover"]
    assert report["order"]["title"] is False

    update(library, "UPDATE books SET title='Later' WHERE id=2")
    report = library_read_model.parity()
    assert report["current"] is False and report["parity"] is False


def test_parity_command_prints_the_report_and_fails_without_parity(library, capsys):
    with pytest.raises(CommandError, match="No complete read model"):
        call_command("library_read_model", "parity")
    call_command("library_read_model", "refresh")
    assert json.loads(capsys.readouterr().out)["imported"] is True
    call_command("library_read_model", "parity")
    assert json.loads(capsys.readouterr().out)["parity"] is True
    CalibreBook.objects.filter(pk=1).update(title="Other")
    with pytest.raises(CommandError, match="differs"):
        call_command("library_read_model", "parity")
    assert json.loads(capsys.readouterr().out)["changes"]["changed"] == ["1"]


def test_worker_tick_follows_the_setting_and_interval(library, settings, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(library_read_model.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(library_read_model, "_next_tick", 0.0)
    settings.LIBRARY_READ_MODEL = "off"
    assert library_read_model.tick() is False
    settings.LIBRARY_READ_MODEL = "refresh"
    assert library_read_model.tick() is True
    assert CalibreBook.objects.count() == 5
    clock[0] += settings.LIBRARY_READ_MODEL_SECONDS - 1
    assert library_read_model.tick() is False
    clock[0] += 1
    update(library, "UPDATE library_id SET uuid=NULL")
    assert library_read_model.tick() is True  # failures are recorded, never raised to the worker
    assert "library UUID" in LibraryReadModel.objects.get().error


def test_worker_tick_without_a_library_does_nothing(settings):
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARY_READ_MODEL = "serve"
    assert library_read_model.tick() is False


@pytest.mark.django_db(transaction=True)
def test_migration_reverses_and_reapplies(library):
    library_read_model.refresh()
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0010_evidence_guards")])
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    assert "librarium_calibrebook" not in tables
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    library_read_model.refresh()
    assert CalibreBook.objects.count() == 5
