"""Calibre runtime adapter. Only the dedicated synthetic owner imports Calibre."""

import os
import stat
from hashlib import sha256
from importlib import import_module
from io import BytesIO
from pathlib import Path

from librarium.delivery_broker import BrokerError, canonical, fingerprint

MAX_BYTES = 32 * 1024 * 1024


def quiesce_maintenance(cache):
    if cache.backend.fts_enabled:
        raise BrokerError("native_maintenance_unconfirmed")
    worker = cache.maintain_page_counts
    worker.shutdown()
    worker.wait_for_worker_shutdown(5)
    if worker.is_alive():
        raise BrokerError("native_maintenance_unconfirmed")
    # The pinned API queues a page scan even with import hooks disabled. Keep its
    # bookkeeping call, but prevent this EPUB-only role from scheduling more writes.
    worker.queue_scan = lambda *args, **kwargs: None
    return worker


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain(v) for v in value), key=canonical)
    if value is None or type(value) in {str, int, bool, float}:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise BrokerError("metadata_unsupported")


class NativeOwner:
    def __init__(self, cache, library_uuid, *, boundary=None):
        numeric_version = import_module("calibre.constants").numeric_version

        if numeric_version != (9, 17, 0) or cache.library_id != library_uuid:
            raise BrokerError("runtime_or_library_changed")
        self.cache, self.library_uuid = cache, library_uuid
        self.lock = cache.write_lock
        self.boundary = boundary
        self.maintenance = quiesce_maintenance(cache)

    def book_id(self, target):
        exclusion = getattr(self, "exclusion", None)
        if exclusion is not None and not exclusion.verified(self.library_uuid):
            raise BrokerError("independent_writer_not_excluded")
        if self.cache.maintain_page_counts is not self.maintenance or self.maintenance.is_alive():
            raise BrokerError("native_maintenance_unconfirmed")
        if type(target) is not dict or set(target) != {"library_uuid", "book_id", "book_uuid"}:
            raise BrokerError("target_invalid")
        text = target["book_id"]
        if (
            type(text) is not str
            or not text.isascii()
            or not text.isdecimal()
            or not 1 <= len(text) <= 12
            or str(int(text)) != text
            or int(text) < 1
        ):
            raise BrokerError("target_invalid")
        book_id = int(text)
        if (
            self.cache.library_id != self.library_uuid
            or target["library_uuid"] != self.library_uuid
            or not self.cache.has_id(book_id)
            or self.cache.field_for("uuid", book_id) != target["book_uuid"]
        ):
            raise BrokerError("target_changed")
        return book_id

    def format(self, book_id, fmt):
        data = self.cache.format(book_id, fmt)
        if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
            raise BrokerError("format_unavailable")
        return data

    def inventory(self):
        root = Path(self.cache.backend.library_path)
        values: dict[str, dict[str, object] | None] = {}
        for leaf in ("metadata.db", "metadata.db-wal", "metadata.db-journal"):
            try:
                fd = os.open(root / leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                values[leaf] = None
                continue
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if before.st_size > 64 * 1024 * 1024:
                    raise BrokerError("inventory_budget_exceeded")
                data = stream.read(64 * 1024 * 1024 + 1)
                after = os.fstat(stream.fileno())
                stable_fields = (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_gid",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
                if (
                    any(getattr(before, name) != getattr(after, name) for name in stable_fields)
                    or len(data) != before.st_size
                ):
                    raise BrokerError("inventory_changed")
                values[leaf] = {
                    "sha256": sha256(data).hexdigest(),
                    "size": len(data),
                    "inode": before.st_ino,
                    "mtime_ns": before.st_mtime_ns,
                }
        return fingerprint(values)

    def observe(self, target):
        with self.lock:
            book_id = self.book_id(target)
            data = self.format(book_id, "EPUB")
            if self.cache.format_db_size(book_id, "EPUB") != len(data):
                raise BrokerError("format_bookkeeping_changed")
            fields = {
                name: plain(self.cache.field_for(name, book_id))
                for name in self.cache.fields
                if name not in {"size", "last_modified", "formats"}
            }
            formats = sorted(self.cache.formats(book_id, verify_formats=False))
            fields["formats"] = formats
            if len(canonical(fields)) > 512 * 1024:
                raise BrokerError("metadata_budget_exceeded")
            cover = self.cache.cover(book_id)
            metadata = {
                "fields_sha256": fingerprint(fields),
                "cover_sha256": sha256(cover).hexdigest() if cover else None,
                "other_formats": {
                    fmt: sha256(self.format(book_id, fmt)).hexdigest()
                    for fmt in formats
                    if fmt != "EPUB"
                },
            }
            return {
                "sha256": sha256(data).hexdigest(),
                "size": len(data),
                "metadata": metadata,
                "inventory": self.inventory(),
            }

    def replace(self, target, output):
        with self.lock:
            book_id = self.book_id(target)
            stream = BytesIO(output)
            if self.boundary is not None:
                callback = self.boundary

                class CopyProbe(BytesIO):
                    def read(self, size=-1):
                        if self.tell() >= 64:
                            callback("native_copy")
                        return super().read(min(size, 64) if size > 0 else 64)

                stream = CopyProbe(output)
            if not self.cache.add_format(book_id, "EPUB", stream, replace=True, run_hooks=False):
                raise BrokerError("native_replace_failed")

    def prepare_write(self, target, size):
        book_id = self.book_id(target)
        path = Path(self.cache.format_abspath(book_id, "EPUB"))
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BrokerError("hardlinked_format")
        space = os.statvfs(path.parent)
        if space.f_bavail * space.f_frsize < size + 16 * 1024 * 1024:
            raise BrokerError("library_storage_full")

    def sync(self, target):
        book_id = self.book_id(target)
        path = Path(self.cache.format_abspath(book_id, "EPUB"))
        root = Path(self.cache.backend.library_path)
        for item in (path, path.parent, root / "metadata.db", root / "metadata.db-wal", root):
            try:
                fd = os.open(item, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                if item.name == "metadata.db-wal":
                    continue
                raise
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
