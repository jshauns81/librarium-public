"""Observation fingerprints ignore their own access time, but retain write fences."""

import os
from types import SimpleNamespace

import pytest
from librarium.delivery_broker import BrokerError
from librarium.delivery_native import NativeOwner


@pytest.mark.parametrize("changed_field", ["access", "modified"])
def test_inventory_read_distinguishes_access_time_from_concurrent_writes(
    tmp_path, monkeypatch, changed_field
):
    (tmp_path / "metadata.db").write_bytes(b"synthetic database bytes")
    owner = object.__new__(NativeOwner)
    owner.cache = SimpleNamespace(backend=SimpleNamespace(library_path=str(tmp_path)))
    fstat = os.fstat
    calls = 0

    def observation(fd):
        nonlocal calls
        info = fstat(fd)
        fields = {
            name: getattr(info, name)
            for name in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_gid",
                "st_nlink",
                "st_size",
                "st_atime_ns",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        }
        calls += 1
        fields["st_atime_ns" if changed_field == "access" else "st_mtime_ns"] += calls
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", observation)
    if changed_field == "modified":
        with pytest.raises(BrokerError, match="inventory_changed"):
            owner.inventory()
    else:
        assert len(owner.inventory()) == 64


@pytest.mark.parametrize("stuck", [False, True])
def test_page_maintenance_is_drained_before_owner_admission(stuck):
    from librarium import delivery_native

    class Maintenance:
        stopped = False
        join_timeout = None
        queued = 0

        def shutdown(self):
            self.stopped = True

        def wait_for_worker_shutdown(self, timeout):
            self.join_timeout = timeout

        def is_alive(self):
            return stuck or not self.stopped

        def queue_scan(self, *args):
            self.queued += 1

    worker = Maintenance()
    cache = SimpleNamespace(maintain_page_counts=worker, backend=SimpleNamespace(fts_enabled=False))
    if stuck:
        with pytest.raises(BrokerError, match="native_maintenance_unconfirmed"):
            delivery_native.quiesce_maintenance(cache)
    else:
        assert delivery_native.quiesce_maintenance(cache) is worker
        worker.queue_scan(1)
        assert worker.queued == 0
    assert worker.stopped and worker.join_timeout == 5


def test_existing_fts_maintenance_is_not_admitted_or_reconfigured():
    from librarium import delivery_native

    cache = SimpleNamespace(backend=SimpleNamespace(fts_enabled=True))
    with pytest.raises(BrokerError, match="native_maintenance_unconfirmed"):
        delivery_native.quiesce_maintenance(cache)
    assert cache.backend.fts_enabled


def test_native_durability_syncs_epub_directory_and_database(tmp_path, monkeypatch):
    from threading import RLock

    from librarium import delivery_native

    book = tmp_path / "book"
    book.mkdir()
    epub = book / "fixture.epub"
    epub.write_bytes(b"synthetic EPUB")
    (tmp_path / "metadata.db").write_bytes(b"database")
    owner = object.__new__(NativeOwner)
    owner.lock = RLock()
    owner.cache = SimpleNamespace(
        backend=SimpleNamespace(library_path=str(tmp_path)), format_abspath=lambda *_: str(epub)
    )
    owner.book_id = lambda _: 1
    seen = []
    monkeypatch.setattr(delivery_native.os, "fsync", lambda fd: seen.append(os.fstat(fd).st_ino))
    owner.prepare_write({}, 100)
    owner.sync({})
    assert seen[:2] == [epub.stat().st_ino, book.stat().st_ino]
    assert (tmp_path / "metadata.db").stat().st_ino in seen
    assert tmp_path.stat().st_ino in seen
    os.link(epub, tmp_path / "hardlink")
    with pytest.raises(BrokerError, match="hardlinked_format"):
        owner.prepare_write({}, 100)


def test_native_full_library_holds_before_send(tmp_path, monkeypatch):
    from librarium import delivery_native

    owner = object.__new__(NativeOwner)
    owner.book_id = lambda _: 1
    epub = tmp_path / "fixture.epub"
    epub.write_bytes(b"synthetic")
    owner.cache = SimpleNamespace(
        backend=SimpleNamespace(library_path=str(tmp_path)), format_abspath=lambda *_: str(epub)
    )
    monkeypatch.setattr(
        delivery_native.os, "statvfs", lambda _: SimpleNamespace(f_bavail=0, f_frsize=4096)
    )
    with pytest.raises(BrokerError, match="library_storage_full"):
        owner.prepare_write({}, 100)


@pytest.fixture
def native_owner(tmp_path, monkeypatch):
    from threading import RLock

    from librarium import delivery_native

    cache = SimpleNamespace(
        library_id="library",
        write_lock=RLock(),
        fields={"title", "formats", "size", "last_modified"},
        has_id=lambda book: book == 1,
        field_for=lambda field, book: "book" if field == "uuid" else "Fixture",
        format=lambda book, fmt: b"epub" if fmt == "EPUB" else b"text",
        format_db_size=lambda *_: 4,
        formats=lambda *args, **kwargs: ["TXT", "EPUB"],
        cover=lambda _: b"cover",
        backend=SimpleNamespace(library_path=str(tmp_path)),
    )
    maintenance = SimpleNamespace(is_alive=lambda: False)
    cache.maintain_page_counts = maintenance
    monkeypatch.setattr(
        delivery_native, "import_module", lambda _: SimpleNamespace(numeric_version=(9, 17, 0))
    )
    monkeypatch.setattr(delivery_native, "quiesce_maintenance", lambda _: maintenance)
    return NativeOwner(cache, "library"), {
        "library_uuid": "library",
        "book_id": "1",
        "book_uuid": "book",
    }


def test_native_target_scoped_observation_and_hooks(native_owner):
    owner, target = native_owner
    observed = owner.observe(target)
    assert observed["size"] == 4 and observed["metadata"]["other_formats"]
    sent = []

    def add(book, fmt, stream, **kwargs):
        sent.append((book, fmt, stream.read(), kwargs))
        return True

    owner.cache.add_format = add
    owner.replace(target, b"replacement")
    assert sent == [(1, "EPUB", b"replacement", {"replace": True, "run_hooks": False})]
    owner.cache.add_format = lambda *args, **kwargs: False
    with pytest.raises(BrokerError, match="native_replace_failed"):
        owner.replace(target, b"replacement")


@pytest.mark.parametrize(
    "change,code",
    [
        ("uuid", "target_changed"),
        ("id", "target_invalid"),
        ("shape", "target_invalid"),
        ("maintenance", "native_maintenance_unconfirmed"),
        ("format", "format_unavailable"),
        ("size", "format_bookkeeping_changed"),
    ],
)
def test_native_observation_refusals(native_owner, change, code):
    owner, target = native_owner
    if change == "uuid":
        target["book_uuid"] = "other"
    elif change == "id":
        target["book_id"] = "01"
    elif change == "shape":
        target["path"] = "unexpected"
    elif change == "maintenance":
        owner.cache.maintain_page_counts = None
    elif change == "format":
        owner.cache.format = lambda *_: None
    elif change == "size":
        owner.cache.format_db_size = lambda *_: 9
    with pytest.raises(BrokerError, match=code):
        owner.observe(target)
