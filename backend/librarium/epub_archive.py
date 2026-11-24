"""Bounded ZIP evidence from pinned libarchive, without extracting files.

Names are libarchive's exposed names. Its normalization and local/central name
ambiguity prevent this adapter from asserting raw-name or EPUB conformance.
"""

import ctypes
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

if not os.path.isabs(os.environ.get("LIBARCHIVE", "")):
    raise RuntimeError("LIBARCHIVE must name the pinned native library by absolute path")

from libarchive import ffi  # type: ignore[import-untyped]
from libarchive.entry import ArchiveEntry  # type: ignore[import-untyped]

if ffi.version_number() != 3008010:
    raise RuntimeError("Librarium requires libarchive 3.8.10")


def _function(name, result, *arguments):
    # Separate public C bindings preserve raw warning statuses without logging names.
    return ctypes.CFUNCTYPE(result, *arguments)(("archive_" + name, ffi.libarchive))


_pointer = ctypes.c_void_p
_status = ctypes.c_int
_support_zip = _function("read_support_format_zip_seekable", _status, _pointer)
_support_none = _function("read_support_filter_none", _status, _pointer)
_open = _function("read_open_memory", _status, _pointer, _pointer, ctypes.c_size_t)
_header = _function("read_next_header2", _status, _pointer, _pointer)
_position = _function("read_header_position", ctypes.c_int64, _pointer)
_block = _function(
    "read_data_block",
    _status,
    _pointer,
    ctypes.POINTER(_pointer),
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(ctypes.c_int64),
)
_close = _function("read_close", _status, _pointer)
_free = _function("read_free", _status, _pointer)
_encrypted = _function("entry_is_encrypted", _status, _pointer)
_FORMAT = re.compile(rb"ZIP [0-9]+\.[0-9]+ \((uncompressed|deflation)\)")


class ArchiveRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Member:
    name: str
    size: int
    directory: bool

    def is_dir(self) -> bool:
        return self.directory


@dataclass(frozen=True)
class Archive:
    members: Mapping[str, Member]
    _content: Mapping[str, bytes]

    def read(self, name: str) -> bytes:
        return self._content[name]


def _check(code, pointer):
    if code != ffi.ARCHIVE_OK:
        message = ffi.error_string(pointer) or b""
        finding = "zip_crc_failure" if b"CRC" in message else "invalid_zip"
        raise ArchiveRefused(finding)


def _name(value, policy):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > policy.max_name_chars
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in "\\:%?#")
        or value.endswith("//")
        or any(part in {"", ".", ".."} for part in value.rstrip("/").split("/"))
    ):
        raise ArchiveRefused("unsafe_zip_member")
    return value


def read_archive(data: bytes, policy) -> Archive:
    if type(data) is not bytes:
        raise TypeError("Archive input must be bytes")
    if len(data) > policy.max_archive_bytes:
        raise ArchiveRefused("invalid_zip")
    members: dict[str, Member] = {}
    content: dict[str, bytes] = {}
    expanded = 0
    pointer = ffi.read_new()
    try:
        _check(_support_none(pointer), pointer)
        _check(_support_zip(pointer), pointer)
        _check(_open(pointer, ctypes.c_char_p(data), len(data)), pointer)
        while True:
            entry = ArchiveEntry(pointer, "utf-8")
            status = _header(pointer, entry._entry_p)
            if status == ffi.ARCHIVE_EOF:
                break
            _check(status, pointer)
            if len(members) >= policy.max_members:
                raise ArchiveRefused("archive_members_limit")
            name = _name(entry.pathname, policy)
            if name in members:
                raise ArchiveRefused("duplicate_zip_member")
            if (
                not (entry.isreg or entry.isdir)
                or entry.islnk
                or _encrypted(entry._entry_p)
                or (entry.isdir and entry.size != 0)
            ):
                raise ArchiveRefused("unsupported_zip_member")
            format_name = ffi.format_name(pointer) or b""
            compression = _FORMAT.fullmatch(format_name)
            if not members and (
                name != "mimetype"
                or entry.isdir
                or _position(pointer) != 0
                or not compression
                or compression[1] != b"uncompressed"
            ):
                raise ArchiveRefused("invalid_mimetype")
            if not compression:
                raise ArchiveRefused("unsupported_zip_member")
            start = ffi.filter_bytes(pointer, 0)
            output = bytearray()
            size = 0
            while True:
                address = _pointer()
                length = ctypes.c_size_t()
                offset = ctypes.c_int64()
                status = _block(
                    pointer, ctypes.byref(address), ctypes.byref(length), ctypes.byref(offset)
                )
                if status == ffi.ARCHIVE_EOF:
                    break
                _check(status, pointer)
                if offset.value != size:
                    raise ArchiveRefused("invalid_zip")
                size += length.value
                expanded += length.value
                if size > policy.max_member_bytes:
                    raise ArchiveRefused("member_bytes_limit")
                if expanded > policy.max_expanded_bytes:
                    raise ArchiveRefused("expansion_limit")
                if expanded > policy.max_read_bytes:
                    raise ArchiveRefused("read_bytes_limit")
                output.extend(ctypes.string_at(address, length.value))
            consumed = ffi.filter_bytes(pointer, 0) - start
            if consumed < 0:
                raise ArchiveRefused("invalid_zip")
            if size > max(1, consumed) * policy.max_expansion_ratio:
                raise ArchiveRefused("expansion_ratio_limit")
            if entry.size != size or (entry.isdir and size):
                raise ArchiveRefused("invalid_zip")
            if name == "mimetype" and output != b"application/epub+zip":
                raise ArchiveRefused("invalid_mimetype")
            members[name] = Member(name, size, entry.isdir)
            content[name] = bytes(output)
        if not members:
            raise ArchiveRefused("invalid_mimetype")
        _check(_close(pointer), pointer)
    except UnicodeError, ValueError, ffi.ArchiveError:
        raise ArchiveRefused("invalid_zip") from None
    finally:
        status = _free(pointer)
        if status != ffi.ARCHIVE_OK and sys.exc_info()[0] is None:
            raise ArchiveRefused("invalid_zip")
    return Archive(MappingProxyType(members), MappingProxyType(content))
