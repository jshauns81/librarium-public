"""All artifact bytes are synthetic and storage is temporary."""

import fcntl
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest
from librarium import artifacts


@pytest.fixture
def store(tmp_path, settings):
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    return root


def put(data=b"synthetic bytes", **kwargs):
    return artifacts.ingest(io.BytesIO(data), hashlib.sha256(data).hexdigest(), **kwargs)


def test_streamed_atomic_reuse_and_private_files(store):
    first = put()
    before = {p.name: p.stat().st_ino for p in store.iterdir()}
    assert put() == first
    assert before == {p.name: p.stat().st_ino for p in store.iterdir()}
    assert artifacts.read("source", first["sha256"], first["size"]) == b"synthetic bytes"
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in store.iterdir())


@pytest.mark.parametrize("relationship", ["same", "contains", "inside"])
def test_artifact_writes_cannot_overlap_native_reference_state(store, settings, relationship):
    root = (
        store
        if relationship == "same"
        else store / "reference"
        if relationship == "contains"
        else store.parent
    )
    settings.LIBRARIUM_REFERENCE_STATE_DIR = str(root)
    with pytest.raises(artifacts.ArtifactError):
        put()
    assert list(store.iterdir()) == []


def test_concurrent_equal_uploads_never_overwrite(store):
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: put(), range(12)))
    assert all(item == results[0] for item in results)
    assert len(list(store.iterdir())) == 1


def test_duplicate_read_waits_for_winning_temporary_link_cleanup(store, monkeypatch):
    published, reader_waiting, shared_waiting, cleaned = Event(), Event(), Event(), Event()
    real_link, real_unlink = os.link, os.unlink
    real_fstat, real_flock = os.fstat, fcntl.flock
    winner = {}
    captured = []
    exclusive_threads = set()

    def link(source, target, **kwargs):
        real_link(source, target, **kwargs)
        winner.update(temporary=source, thread=get_ident())
        winner["inode"] = os.stat(target, dir_fd=kwargs["dst_dir_fd"]).st_ino
        published.set()
        assert reader_waiting.wait(5), "duplicate did not reach the published inode"

    def unlink(name, **kwargs):
        real_unlink(name, **kwargs)
        if name == winner.get("temporary"):
            cleaned.set()

    def duplicate(info):
        return info.st_ino == winner.get("inode") and get_ident() != winner.get("thread")

    def fstat(fd):
        info = real_fstat(fd)
        if duplicate(info):
            info = LinkSnapshot(info)
        if duplicate(info) and not captured:
            if winner.get("thread") in exclusive_threads and not cleaned.is_set():
                return info
            captured.append(info)
            reader_waiting.set()
            assert cleaned.wait(5), "winner did not remove its temporary link"
        return info

    class LinkSnapshot:
        def __init__(self, info):
            self.info = info
            # Model a distinct unlink ctime even when the host coalesces clock ticks.
            self.st_ctime_ns = info.st_ctime_ns + (info.st_nlink == 1)

        def __getattr__(self, name):
            return getattr(self.info, name)

    def flock(fd, operation):
        if operation == fcntl.LOCK_EX:
            exclusive_threads.add(get_ident())
        shared = operation == fcntl.LOCK_SH and duplicate(real_fstat(fd))
        if shared:
            shared_waiting.set()
            reader_waiting.set()
        result = real_flock(fd, operation)
        if shared:
            assert cleaned.is_set(), "reader acquired SH while publication EX was held"
        return result

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(fcntl, "flock", flock)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(put)
        assert published.wait(5)
        second = pool.submit(put)
        results = [future.result(timeout=10) for future in (first, second)]
    assert results[0] == results[1]
    assert cleaned.is_set() and reader_waiting.is_set()
    assert shared_waiting.is_set() and captured[0].st_nlink == 1
    assert len(list(store.iterdir())) == 1
    assert artifacts.read("source", results[0]["sha256"], results[0]["size"]) == b"synthetic bytes"


def test_publication_error_cleans_temporary_link_before_releasing_lock(store, monkeypatch):
    real_link, real_unlink = os.link, os.unlink
    published = []
    cleanup = []

    def link(source, target, **kwargs):
        real_link(source, target, **kwargs)
        published.append(target)
        raise OSError("synthetic publication interruption")

    def unlink(name, **kwargs):
        if published:
            descriptor = os.open(published[0], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=kwargs["dir_fd"])
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                cleanup.append(name)
            finally:
                os.close(descriptor)
        return real_unlink(name, **kwargs)

    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(artifacts.ArtifactError):
        put()
    assert len(cleanup) == 1
    assert [path.name for path in store.iterdir()] == published
    assert (
        artifacts.read("source", hashlib.sha256(b"synthetic bytes").hexdigest(), 15)
        == b"synthetic bytes"
    )


def test_read_still_refuses_noncooperative_ctime_change(store, monkeypatch):
    item = put()
    path = next(store.iterdir())
    original = path.stat()
    real_fdopen, real_fstat = os.fdopen, os.fstat
    changed = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            data = self.stream.read(size)
            path.chmod(0o400)
            path.chmod(0o600)
            changed.append(True)
            return data

    class ChangedStat:
        def __init__(self, info):
            self.info = info
            self.st_ctime_ns = info.st_ctime_ns + 1

        def __getattr__(self, name):
            return getattr(self.info, name)

    def fstat(fd):
        info = real_fstat(fd)
        # Keep the metadata-only mutation observable on coalesced host clock ticks.
        return ChangedStat(info) if changed and info.st_ino == original.st_ino else info

    monkeypatch.setattr(os, "fdopen", lambda fd, mode: Reader(real_fdopen(fd, mode)))
    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.read("source", item["sha256"], item["size"])
    assert path.read_bytes() == b"synthetic bytes"
    assert path.stat().st_mtime_ns == original.st_mtime_ns


@pytest.mark.parametrize(
    "data,sha,limit,status", [(b"wrong", "a" * 64, 20, 400), (b"12345", None, 4, 413)]
)
def test_hash_and_stream_limit_leave_no_published_artifact(store, data, sha, limit, status):
    with pytest.raises(artifacts.ArtifactError) as caught:
        artifacts.ingest(io.BytesIO(data), sha or hashlib.sha256(data).hexdigest(), max_bytes=limit)
    assert caught.value.status == status
    assert list(store.iterdir()) == []


def test_stream_reads_at_most_limit_plus_one(store):
    class Bound(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 5
            return super().read(size)

    stream = Bound(b"x" * 100)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.ingest(stream, "a" * 64, max_bytes=4)
    assert stream.tell() == 5


@pytest.mark.parametrize(
    "mutation", ["bytes", "length", "symlink", "fifo", "directory", "permissions"]
)
def test_reuse_and_reads_refuse_corruption_or_nonregular_files(store, mutation):
    item = put()
    path = next(store.iterdir())
    if mutation in {"bytes", "length"}:
        path.write_bytes(b"X" * item["size"] if mutation == "bytes" else b"x")
    elif mutation == "permissions":
        path.chmod(0o644)
    else:
        path.unlink()
        if mutation == "symlink":
            other = store.parent / "original"
            other.write_bytes(b"synthetic bytes")
            path.symlink_to(other)
        elif mutation == "fifo":
            os.mkfifo(path)
        else:
            path.mkdir()
    for action in (put, lambda: artifacts.read("source", item["sha256"], item["size"])):
        with pytest.raises(artifacts.ArtifactError):
            action()


@pytest.mark.parametrize("root", ["", "relative", "/tmp/../tmp", "/does-not-exist-librarium"])
def test_disabled_missing_or_unsafe_root_is_safe(settings, root):
    settings.LIBRARIUM_ARTIFACT_DIR = root
    with pytest.raises(artifacts.ArtifactError) as caught:
        put()
    assert caught.value.status == 503
    assert root not in str(caught.value) or not root


def test_root_or_ancestor_symlink_and_public_root_are_refused(store, settings):
    store.chmod(0o755)
    with pytest.raises(artifacts.ArtifactError):
        put()
    store.chmod(0o700)
    link = store.parent / "link"
    link.symlink_to(store, target_is_directory=True)
    settings.LIBRARIUM_ARTIFACT_DIR = str(link)
    with pytest.raises(artifacts.ArtifactError):
        put()


def test_report_is_separate_bounded_digest_addressed_json(store):
    body = {"source_sha256": "a" * 64, "facts": ["synthetic"]}
    item = artifacts.write_report(body)
    assert artifacts.read_report(item["sha256"], item["size"]) == body
    assert next(store.iterdir()).name.startswith("report-")
    with pytest.raises(artifacts.ArtifactError):
        artifacts.write_report({"huge": "x" * (1024 * 1024)})
    with pytest.raises(artifacts.ArtifactError):
        artifacts.read("source", "../escape", 3)


def test_misleading_length_and_overlapping_input_mount_are_refused(store, settings):
    with pytest.raises(artifacts.ArtifactError) as caught:
        put(expected_size=1)
    assert caught.value.status == 400
    assert list(store.iterdir()) == []
    settings.LIBRARIUM_CATALOGUE_DIR = str(store)
    with pytest.raises(artifacts.ArtifactError):
        put()
    assert list(store.iterdir()) == []


def test_io_failure_leaves_no_published_or_staged_artifact(store):
    class Interrupted:
        def read(self, size):
            raise OSError("/private/source.epub")

    with pytest.raises(artifacts.ArtifactError) as caught:
        artifacts.ingest(Interrupted(), "a" * 64)
    assert "/private/" not in str(caught.value)
    assert list(store.iterdir()) == []


@pytest.mark.parametrize(
    "setting", ["LIBRARIUM_CATALOGUE_COVER_DIR", "LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR"]
)
@pytest.mark.parametrize("relationship", ["same", "contains", "inside"])
def test_artifacts_cannot_overlap_cover_storage(store, settings, setting, relationship):
    cover = (
        store
        if relationship == "same"
        else store / "covers"
        if relationship == "contains"
        else store.parent
    )
    setattr(settings, setting, str(cover))
    with pytest.raises(artifacts.ArtifactError):
        put()
    assert not list(store.iterdir())
