import base64
import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from django.test import RequestFactory
from librarium import direct_library, direct_library_views

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1cAAAAASUVORK5CYII="
)


@pytest.fixture
def library(tmp_path, settings):
    root = tmp_path / "library"
    root.mkdir()
    path = root / "metadata.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, sort TEXT, path TEXT,
                uuid TEXT, series_index REAL, pubdate TEXT, timestamp TEXT, last_modified TEXT,
                has_cover INTEGER);
            CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
            CREATE TABLE series(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE books_series_link(id INTEGER PRIMARY KEY, book INTEGER, series INTEGER);
            CREATE TABLE publishers(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE books_publishers_link(id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER);
            CREATE TABLE languages(id INTEGER PRIMARY KEY, lang_code TEXT);
            CREATE TABLE books_languages_link(id INTEGER PRIMARY KEY, book INTEGER,
                lang_code INTEGER, item_order INTEGER);
            CREATE TABLE identifiers(id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
            CREATE TABLE data(id INTEGER PRIMARY KEY, book INTEGER, format TEXT,
                uncompressed_size INTEGER, name TEXT);
            CREATE TABLE comments(id INTEGER PRIMARY KEY, book INTEGER, text TEXT);
            CREATE TABLE library_id(id INTEGER PRIMARY KEY, uuid TEXT);
            INSERT INTO library_id VALUES(1,'library-uuid');
            INSERT INTO books VALUES(1,'Actual Book','Actual Book','Writer/Actual Book (1)',
                'book-uuid',1.5,'2020-03-01','2026-10-20','2026-10-28',1);
            INSERT INTO authors VALUES(1,'Some Writer');
            INSERT INTO books_authors_link VALUES(1,1,1);
            INSERT INTO series VALUES(1,'Actual Series');
            INSERT INTO books_series_link VALUES(1,1,1);
            INSERT INTO publishers VALUES(1,'A Publisher');
            INSERT INTO books_publishers_link VALUES(1,1,1);
            INSERT INTO languages VALUES(1,'eng');
            INSERT INTO books_languages_link VALUES(1,1,1,0);
            INSERT INTO identifiers VALUES(1,1,'isbn','9780306406157');
            INSERT INTO data VALUES(1,1,'EPUB',12,'Actual Book - Some Writer');
            INSERT INTO comments VALUES(1,1,'<p>Original description</p>');
        """)
    folder = root / "Writer/Actual Book (1)"
    folder.mkdir(parents=True)
    (folder / "Actual Book - Some Writer.epub").write_bytes(b"original epub")
    (folder / "cover.jpg").write_bytes(PNG)
    settings.DIRECT_LIBRARY_ROOT = str(root)
    return root


def listing(**params):
    reply = direct_library_views.index(RequestFactory().get("/api/direct-library", params))
    return reply.status_code, json.loads(reply.content)


def detail(book_id="1", **params):
    reply = direct_library_views.book(
        RequestFactory().get(f"/api/direct-library/books/{book_id}", params), book_id
    )
    return reply.status_code, json.loads(reply.content)


def update(library, sql, values=()):
    with closing(sqlite3.connect(library / "metadata.db")) as db, db:
        db.execute(sql, values)


def test_direct_books_metadata_and_formats_without_network_or_library_writes(library, monkeypatch):
    import urllib.request

    def network_forbidden(*args, **kwargs):
        raise AssertionError("direct library must not contact Index")

    monkeypatch.setattr(urllib.request, "urlopen", network_forbidden)
    before = {
        str(p.relative_to(library)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in library.rglob("*")
        if p.is_file()
    }
    status, data = listing()
    assert status == 200
    assert data["source"] == "calibre" and data["read_only"] is True
    assert data["total"] == 1 and data["page_size"] == 24
    book = data["books"][0]
    assert book["id"] == "1" and book["title"] == "Actual Book"
    assert book["authors"] == ["Some Writer"]
    assert book["series"] == "Actual Series" and book["series_index"] == 1.5
    assert book["identifiers"] == [{"type": "isbn", "value": "9780306406157"}]
    assert book["languages"] == ["eng"]
    assert book["formats"] == [
        {
            "format": "EPUB",
            "name": "Actual Book - Some Writer.epub",
            "size_bytes": 13,
            "recorded_size_bytes": 12,
            "available": True,
        }
    ]
    assert str(library) not in json.dumps(data)
    assert detail(inventory=data["inventory"]["token"])[1]["book"]["description"] == (
        "<p>Original description</p>"
    )
    after = {
        str(p.relative_to(library)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in library.rglob("*")
        if p.is_file()
    }
    assert before == after


def test_inventory_changes_and_stale_requests_refuse(library):
    token = listing()[1]["inventory"]["token"]
    update(library, "UPDATE books SET title='New Title'")
    assert listing()[1]["inventory"]["token"] != token
    status, error = detail(inventory=token)
    assert status == 409 and error["code"] == "direct_library_changed"


@pytest.mark.parametrize(
    "recorded",
    [
        None,
        "",
        "0101-01-01",
        "0101-01-01 00:00:00.000000",
        "0101-01-01 00:00:00+00:00",
        "0101-01-01T00:00:00Z",
        "0101-01-01T05:30:00+05:30",
        "0100-12-31T19:00:00-05:00",
        "0001-01-01 00:00:00",
    ],
)
def test_undefined_calibre_publication_dates_are_absent_without_changing_source(library, recorded):
    update(library, "UPDATE books SET pubdate=?", (recorded,))
    before = hashlib.sha256((library / "metadata.db").read_bytes()).hexdigest()
    status, data = listing()
    assert status == 200
    assert data["books"][0]["published_at"] is None
    status, selected = detail(inventory=data["inventory"]["token"])
    assert status == 200
    assert selected["book"]["published_at"] is None
    assert hashlib.sha256((library / "metadata.db").read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "recorded",
    [
        "2020-03-01",
        "2016-11-15 00:00:00.000000",
        "2020-03-01T00:30:00+14:00",
        "0101-01-02",
        "not a date",
        "0101-01-01-not-a-date",
    ],
)
def test_other_recorded_publication_values_are_preserved(library, recorded):
    update(library, "UPDATE books SET pubdate=?", (recorded,))
    status, data = listing()
    assert status == 200
    assert data["books"][0]["published_at"] == recorded
    status, selected = detail(inventory=data["inventory"]["token"])
    assert status == 200
    assert selected["book"]["published_at"] == recorded


def test_literal_search_authors_and_paging(library):
    for number in range(2, 29):
        update(
            library,
            "INSERT INTO books(id,title,sort,path) VALUES(?,?,?,?)",
            (number, f"Book {number:02}", f"Book {number:02}", "absent"),
        )
    assert len(listing()[1]["books"]) == 24
    assert len(listing(page=2)[1]["books"]) == 4
    assert listing(q="Some Writer")[1]["total"] == 1
    assert listing(q="%_")[1]["total"] == 0
    assert listing(page=0)[0] == 400
    assert listing(q="x" * 201)[0] == 400


@pytest.mark.parametrize("params", [{"q": ["a", "b"]}, {"unexpected": "a"}, {"inventory": "x"}])
def test_invalid_parameters_refuse(library, params):
    assert listing(**params)[0] == 400


def test_missing_and_invalid_configuration_do_not_expose_paths(settings, tmp_path):
    settings.DIRECT_LIBRARY_ROOT = ""
    assert listing()[1]["code"] == "direct_library_unconfigured"
    settings.DIRECT_LIBRARY_ROOT = str(tmp_path / "private-name")
    status, value = listing()
    assert status == 503 and "private-name" not in json.dumps(value)


@pytest.mark.parametrize("kind", ["database", "book", "format", "root"])
def test_symlink_paths_never_follow(library, settings, tmp_path, kind):
    book = library / "Writer/Actual Book (1)"
    source = {
        "database": library / "metadata.db",
        "book": book,
        "format": book / "Actual Book - Some Writer.epub",
        "root": library,
    }[kind]
    moved = tmp_path / f"outside-{kind}"
    source.rename(moved)
    source.symlink_to(moved, target_is_directory=source == book or source == library)
    status, value = listing()
    if kind in {"database", "root"}:
        assert status == 503
    else:
        assert status == 200 and value["books"][0]["formats"][0]["available"] is False


@pytest.mark.parametrize("path", ["../outside", "/etc", "Writer/../Actual Book (1)", "Writer\\bad"])
def test_database_path_cannot_escape_library(library, path):
    update(library, "UPDATE books SET path=?", (path,))
    assert listing()[1]["books"][0]["formats"][0]["available"] is False


def test_pending_database_journal_refuses_instead_of_ignoring_it(library):
    (library / "metadata.db-journal").write_bytes(b"uncheckpointed changes")
    status, value = listing()
    assert status == 503 and value["code"] == "direct_library_busy"


def test_committed_wal_is_read_without_source_shm_or_database_writes(library):
    with closing(sqlite3.connect(library / "metadata.db")) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE books SET title='Committed WAL title'")
        writer.commit()
        before = {p.name: p.read_bytes() for p in library.glob("metadata.db*")}
        status, value = listing()
        assert status == 200 and value["books"][0]["title"] == "Committed WAL title"
        assert value["inventory"]["library_uuid"] == "library-uuid"
        assert {p.name: p.read_bytes() for p in library.glob("metadata.db*")} == before
        token = value["inventory"]["token"]
        writer.execute("UPDATE books SET title='Later WAL title'")
        writer.commit()
        assert detail(inventory=token)[0] == 409


def test_invalid_wal_refuses_instead_of_discarding_unknown_changes(library):
    (library / "metadata.db-wal").write_bytes(b"not a WAL")
    assert listing()[0] == 503


def test_missing_files_and_covers_do_not_hide_book(library):
    folder = library / "Writer/Actual Book (1)"
    (folder / "Actual Book - Some Writer.epub").unlink()
    (folder / "cover.jpg").unlink()
    value = listing()[1]["books"][0]
    assert value["formats"][0]["available"] is False
    assert value["formats"][0]["size_bytes"] is None
    assert value["cover"] is None


def test_cover_bytes_admission_and_no_stale_cache(library):
    data = listing()[1]
    selected = data["books"][0]["cover"]
    assert selected["width"] == selected["height"] == 1
    assert selected["media_type"] == "image/png"
    request = RequestFactory().get(selected["url"])
    reply = direct_library_views.cover(request, "1")
    assert reply.status_code == 200 and reply.content == PNG
    assert reply["Cache-Control"] == "private, max-age=86400"
    again = RequestFactory().get(selected["url"], HTTP_IF_NONE_MATCH=reply["ETag"])
    unchanged = direct_library_views.cover(again, "1")
    assert unchanged.status_code == 304 and unchanged.content == b""
    (library / "Writer/Actual Book (1)/cover.jpg").write_bytes(b"<svg>unsafe</svg>")
    assert direct_library_views.cover(request, "1").status_code == 404
    assert listing()[1]["books"][0]["cover"] is None


@pytest.mark.parametrize("cold_worker", [False, True])
def test_page_covers_do_not_recopy_metadata_for_each_book(library, monkeypatch, cold_worker):
    for number in range(2, 25):
        update(
            library,
            "INSERT INTO books(id,title,sort,path) VALUES(?,?,?,?)",
            (number, f"Book {number:02}", f"Book {number:02}", "Writer/Actual Book (1)"),
        )
    original = direct_library.tempfile.TemporaryDirectory
    copies = []

    def counted(*args, **kwargs):
        scratch = original(*args, **kwargs)
        copies.append(scratch.name)
        return scratch

    monkeypatch.setattr(direct_library.tempfile, "TemporaryDirectory", counted)
    page = direct_library.browse()
    assert len(copies) == 1
    if cold_worker:
        direct_library._discard_metadata()

    def cover(book):
        return direct_library.cover(book["id"], page["inventory"]["token"])[0]

    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(cover, page["books"])) == [PNG] * 24
    assert len(copies) == 1 + int(cold_worker)
    assert direct_library._METADATA[1].name == copies[-1]


def test_reused_metadata_still_refuses_source_change_during_cover_read(library, monkeypatch):
    token = listing()[1]["inventory"]["token"]
    read_cover = direct_library.read_cover

    def changed_while_reading(*args):
        value = read_cover(*args)
        update(library, "UPDATE books SET title='Changed during a cover request'")
        return value

    monkeypatch.setattr(direct_library, "read_cover", changed_while_reading)
    with pytest.raises(direct_library.DirectLibraryError) as error:
        direct_library.cover("1", token)
    assert error.value.code == "direct_library_changed"


def test_changed_metadata_replaces_private_copy_and_refuses_old_cover_pin(library):
    token = listing()[1]["inventory"]["token"]
    first_copy = Path(direct_library._METADATA[1].name)
    update(library, "UPDATE books SET title='Changed metadata'")
    with pytest.raises(direct_library.DirectLibraryError) as error:
        direct_library.cover("1", token)
    assert error.value.code == "direct_library_changed"
    status, latest = listing()
    assert status == 200 and latest["books"][0]["title"] == "Changed metadata"
    assert not first_copy.exists()
    assert direct_library.cover("1", latest["inventory"]["token"])[0] == PNG


def test_file_reader_selects_only_recorded_format_and_preserves_bytes(library):
    token = listing()[1]["inventory"]["token"]
    with direct_library.open_format("1", "EPUB", token) as (stream, info):
        assert stream.read() == b"original epub"
        assert info["book_id"] == "1" and info["size_bytes"] == 13
        assert info["library_uuid"] == "library-uuid"
    with (
        pytest.raises(direct_library.DirectLibraryError),
        direct_library.open_format("1", "../metadata.db", token),
    ):
        pytest.fail("unsafe format was opened")


def test_oversized_metadata_refuses_instead_of_truncating_evidence(library):
    update(library, "UPDATE books SET title=?", ("x" * 2001,))
    status, data = listing()
    assert status == 503 and data["code"] == "direct_library_invalid"


def test_unknown_book_and_non_get_requests(library):
    assert detail("999")[0] == 404
    assert detail("1 OR 1=1")[0] == 400
    assert (
        direct_library_views.index(RequestFactory().post("/api/direct-library")).status_code == 405
    )


def test_same_size_commit_changes_token_even_when_filesystem_timestamps_coincide(
    library, monkeypatch
):
    original_signature = direct_library.signature
    monkeypatch.setattr(
        direct_library, "signature", lambda info: (*original_signature(info)[:3], 0, 0)
    )
    token = listing()[1]["inventory"]["token"]
    update(library, "UPDATE books SET title='Changed metadata'")
    with pytest.raises(direct_library.DirectLibraryError) as error:
        direct_library.cover("1", token)
    assert error.value.code == "direct_library_changed"


@pytest.fixture
def recycled_wal(library, monkeypatch):
    with closing(sqlite3.connect(library / "metadata.db")) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        for number in range(12):
            writer.execute("UPDATE books SET title=?", (f"Padding commit {number}",))
            writer.commit()
        assert writer.execute("PRAGMA wal_checkpoint(RESTART)").fetchone()[0] == 0
        writer.execute("UPDATE books SET title='First recycled commit'")
        writer.commit()
        original_signature = direct_library.signature
        monkeypatch.setattr(
            direct_library, "signature", lambda info: (*original_signature(info)[:3], 0, 0)
        )
        yield writer


def test_recycled_wal_invalidates_token_and_private_cache_despite_unchanged_prefix(
    library, recycled_wal
):
    first = listing()[1]
    wal = library / "metadata.db-wal"
    before = wal.read_bytes()
    recycled_wal.execute("UPDATE books SET title='Second recycled commit'")
    recycled_wal.commit()
    after = wal.read_bytes()
    assert len(before) == len(after) and before[:100] == after[:100] and before != after
    with pytest.raises(direct_library.DirectLibraryError) as error:
        direct_library.cover("1", first["inventory"]["token"])
    assert error.value.code == "direct_library_changed"
    status, latest = listing()
    assert status == 200 and latest["books"][0]["title"] == "Second recycled commit"
    assert latest["inventory"]["token"] != first["inventory"]["token"]


@pytest.fixture
def checkpointed_wal(library, monkeypatch):
    with closing(sqlite3.connect(library / "metadata.db")) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE books SET title='First checkpointed commit'")
        writer.commit()
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        original_signature = direct_library.signature
        monkeypatch.setattr(
            direct_library, "signature", lambda info: (*original_signature(info)[:3], 0, 0)
        )
        yield writer


def test_checkpointed_pages_invalidate_token_and_cache_with_identical_header(
    library, checkpointed_wal
):
    first = listing()[1]
    database = library / "metadata.db"
    before = database.read_bytes()
    assert (library / "metadata.db-wal").read_bytes() == b""
    checkpointed_wal.execute("UPDATE books SET title='Second checkpointed commit'")
    checkpointed_wal.commit()
    assert checkpointed_wal.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    after = database.read_bytes()
    assert len(before) == len(after) and before[:100] == after[:100] and before != after
    assert (library / "metadata.db-wal").read_bytes() == b""
    with pytest.raises(direct_library.DirectLibraryError) as error:
        direct_library.cover("1", first["inventory"]["token"])
    assert error.value.code == "direct_library_changed"
    status, latest = listing()
    assert status == 200 and latest["books"][0]["title"] == "Second checkpointed commit"
    assert latest["inventory"]["token"] != first["inventory"]["token"]


def test_copied_bytes_must_match_observation_even_when_source_restores(library, monkeypatch):
    import builtins

    original = direct_library.source_file
    copy_active = [False]
    before = (library / "metadata.db").read_bytes()

    class ChangedDuringCopy:
        def __init__(self, stream):
            self.stream = stream

        def read(self, *args):
            value = self.stream.read(*args)
            return value.replace(b"Actual Book", b"Hidden Book") if copy_active[0] else value

        def __getattr__(self, name):
            return getattr(self.stream, name)

    @contextmanager
    def changing(root, name, limit=None):
        with original(root, name, limit) as (stream, info):
            yield (ChangedDuringCopy(stream) if name == "metadata.db" else stream), info

    @contextmanager
    def copying(path, mode):
        with builtins.open(path, mode) as target:
            copy_active[0] = True
            try:
                yield target
            finally:
                copy_active[0] = False

    monkeypatch.setattr(direct_library, "source_file", changing)
    monkeypatch.setattr(direct_library, "open", copying, raising=False)
    status, data = listing()
    assert status == 409 and data["code"] == "direct_library_changed"
    assert direct_library._METADATA is None
    assert (library / "metadata.db").read_bytes() == before


def book_file(book_id="1", **params):
    return direct_library_views.book_file(
        RequestFactory().get(f"/api/direct-library/books/{book_id}/file", params), book_id
    )


def test_book_file_serves_exact_recorded_bytes_as_a_private_attachment(library):
    token = listing()[1]["inventory"]["token"]
    reply = book_file(inventory=token, format="EPUB")
    assert reply.status_code == 200 and reply.content == b"original epub"
    assert reply["Content-Type"] == "application/epub+zip"
    assert reply["Content-Length"] == "13"
    assert reply["Content-Disposition"].startswith("attachment;")
    assert "Actual%20Book%20-%20Some%20Writer.epub" in reply["Content-Disposition"]
    assert reply["Cache-Control"] == "private, no-store"
    assert reply["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert (library / "Writer/Actual Book (1)/Actual Book - Some Writer.epub").read_bytes() == (
        b"original epub"
    )


@pytest.mark.parametrize(
    "params",
    [{}, {"format": "EPUB"}, {"inventory": "x" * 64, "format": "EPUB", "extra": "1"}],
)
def test_book_file_requires_a_pinned_inventory_and_format(library, params):
    assert book_file(**params).status_code == 400


def test_book_file_refuses_unrecorded_formats_and_stale_inventory(library):
    token = listing()[1]["inventory"]["token"]
    assert book_file(inventory=token, format="PDF").status_code == 404
    assert book_file(inventory=token, format="../metadata.db").status_code == 400
    update(library, "UPDATE books SET title='Changed'")
    assert book_file(inventory=token, format="EPUB").status_code == 409


def test_book_file_refuses_a_missing_file_like_other_library_reads(library):
    token = listing()[1]["inventory"]["token"]
    (library / "Writer/Actual Book (1)/Actual Book - Some Writer.epub").unlink()
    reply = book_file(inventory=token, format="EPUB")
    assert reply.status_code == 503
    assert json.loads(reply.content)["error"]


def series_listing(**params):
    reply = direct_library_views.series(RequestFactory().get("/api/direct-library/series", params))
    return reply.status_code, json.loads(reply.content)


def test_series_lists_every_owned_book_in_reading_order(library):
    for number, index in ((2, 3.0), (3, 2.0), (4, None)):
        update(
            library,
            "INSERT INTO books(id,title,sort,path,series_index) VALUES(?,?,?,?,?)",
            (number, f"Book {number}", f"Book {number}", "absent", index),
        )
        update(library, "INSERT INTO books_series_link(book,series) VALUES(?,1)", (number,))
    update(library, "INSERT INTO series VALUES(2,'Other Series')")
    update(
        library, "INSERT INTO books(id,title,sort,path) VALUES(5,'Elsewhere','Elsewhere','absent')"
    )
    update(library, "INSERT INTO books_series_link(book,series) VALUES(5,2)")
    status, body = series_listing(name="Actual Series")
    assert status == 200 and body["read_only"] is True
    assert [(book["id"], book["series_index"]) for book in body["books"]] == [
        ("1", 1.5),
        ("3", 2.0),
        ("2", 3.0),
        ("4", None),
    ]
    assert body["books"][0]["cover"]["url"].startswith("/api/direct-library/books/1/cover?")
    assert series_listing(name="actual series")[1]["books"] == []
    assert series_listing(name="Missing")[1]["books"] == []


@pytest.mark.parametrize(
    "params", [{}, {"name": ""}, {"name": "x" * 201}, {"name": "a", "q": "b"}, {"name": ["a", "b"]}]
)
def test_series_refuses_invalid_requests(library, params):
    assert series_listing(**params)[0] == 400


def test_recent_order_lists_the_latest_arrivals_first_with_their_dates(library):
    for number, added in ((2, "2026-11-02 10:00:00+00:00"), (3, "2026-10-29 09:00:00+00:00")):
        update(
            library,
            "INSERT INTO books(id,title,sort,path,timestamp) VALUES(?,?,?,?,?)",
            (number, f"Book {number}", f"Book {number}", "absent", added),
        )
    status, body = listing(order="recent")
    assert status == 200
    assert [book["id"] for book in body["books"]] == ["2", "3", "1"]
    assert body["books"][0]["added_at"] == "2026-11-02 10:00:00+00:00"
    assert [book["id"] for book in listing()[1]["books"]] == ["1", "2", "3"]
    assert listing(order="oldest")[0] == 400


def test_libraries_without_arrival_dates_still_list_and_open(library):
    update(library, "ALTER TABLE books DROP COLUMN timestamp")
    update(library, "INSERT INTO books(id,title,sort,path) VALUES(2,'Later','Later','absent')")
    status, body = listing(order="recent")
    assert status == 200 and [book["id"] for book in body["books"]] == ["2", "1"]
    assert body["books"][0]["added_at"] is None
    assert detail()[0] == 200


def test_listing_reads_only_cover_headers_but_the_cover_route_reads_it_all(library, monkeypatch):
    reads = []
    real = direct_library.file_in

    @contextmanager
    def counted(parent, name, limit=None):
        with real(parent, name, limit) as (stream, info):
            original = stream.read

            def read(size=-1):
                data = original(size)
                if name == "cover.jpg":
                    reads.append(size)
                return data

            stream.read = read
            yield stream, info

    monkeypatch.setattr(direct_library, "file_in", counted)
    token = listing()[1]["inventory"]["token"]
    assert reads == [direct_library.FIRST_HEADER]
    assert direct_library.cover("1", token)[0] == PNG
    assert reads[1:] == [direct_library.catalogue_covers.MAX_BODY + 1]


def jpeg(width, height, padding=0):
    app = b"\xff\xe1" + (padding + 2).to_bytes(2, "big") + b"\0" * padding
    app *= 2
    frame = b"\xff\xc0\x00\x11\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
    return b"\xff\xd8" + app + frame + b"\x03" + b"\x01\x11\x00" * 3 + b"\xff\xd9"


def test_cover_whose_frame_lies_past_the_first_chunk_still_has_its_size(library):
    cover = library / "Writer/Actual Book (1)/cover.jpg"
    cover.write_bytes(jpeg(600, 900, padding=direct_library.FIRST_HEADER // 2))
    value = listing()[1]["books"][0]["cover"]
    assert (value["media_type"], value["width"], value["height"]) == ("image/jpeg", 600, 900)


def test_listing_opens_each_book_folder_once_and_never_opens_its_files(library, monkeypatch):
    update(library, "INSERT INTO data VALUES(2,1,'PDF',3,'Actual Book - Some Writer')")
    (library / "Writer/Actual Book (1)/Actual Book - Some Writer.pdf").write_bytes(b"pdf")
    opened = []
    real = direct_library.os.open

    def counted(path, *args, **kwargs):
        opened.append(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(direct_library.os, "open", counted)
    book = listing()[1]["books"][0]
    assert [(f["format"], f["available"], f["size_bytes"]) for f in book["formats"]] == [
        ("EPUB", True, 13),
        ("PDF", True, 3),
    ]
    assert book["cover"]["width"] == 1
    assert opened.count("Writer") == opened.count("Actual Book (1)") == 1
    assert opened.count("cover.jpg") == 1
    assert not [name for name in opened if name.startswith("Actual Book - ")]


def test_a_page_checks_its_books_files_side_by_side_in_page_order(library, monkeypatch):
    for number in range(2, 9):
        update(
            library,
            "INSERT INTO books(id,title,sort,path) VALUES(?,?,?,?)",
            (number, f"Book {number:02}", f"Book {number:02}", "Writer/Actual Book (1)"),
        )
    together = threading.Barrier(2, timeout=5)
    real = direct_library.book_files

    def paired(*args):
        together.wait()
        return real(*args)

    monkeypatch.setattr(direct_library, "book_files", paired)
    books = listing()[1]["books"]
    assert [book["title"] for book in books] == ["Actual Book"] + [
        f"Book {n:02}" for n in range(2, 9)
    ]
    assert all(book["cover"]["width"] == 1 for book in books)
