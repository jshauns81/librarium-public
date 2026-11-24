"""Deny ambient filesystem and network access before Python parses owned pipes."""

import codecs
import ctypes
import encodings
import importlib
import logging
import os
import pkgutil
import platform
import sys

from librarium.seccomp_sandbox import (
    SeccompUnavailable,
    deny_network,
)
from librarium.seccomp_sandbox import (
    check_available as check_seccomp,
)

# x86-64 Landlock UAPI, using the ABI-12 policy on newer kernels.
_CREATE, _RESTRICT = 444, 446
EXIT_CODES = {
    "sandbox_platform_unavailable": 20,
    "sandbox_landlock_unavailable": 21,
    "sandbox_seccomp_unavailable": 22,
    "sandbox_setup_failed": 23,
    "sandbox_late_import": 24,
}


class SandboxError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Ruleset(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


def _library():
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    library.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    library.prctl.restype = ctypes.c_int
    return library


def _platform():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SandboxError("sandbox_platform_unavailable")


def _abi(library):
    abi = library.syscall(_CREATE, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    if abi < 3:
        raise SandboxError("sandbox_landlock_unavailable")
    return abi


def preflight():
    _platform()
    abi = _abi(_library())
    try:
        check_seccomp()
    except SeccompUnavailable:
        raise SandboxError("sandbox_seccomp_unavailable") from None
    logging.getLogger(__name__).info(
        "Python sandbox: Landlock ABI %s; policy ABI %s", abi, min(abi, 12)
    )
    return {"landlock_abi": abi, "policy_abi": min(abi, 12)}


def restrict_filesystem():
    _platform()
    library = _library()
    abi = _abi(library)
    observed_abi = abi
    abi = min(abi, 12)
    # ABI 5 adds device ioctl; ABI 9 adds pathname UNIX socket resolution.
    fs_bits = 17 if abi >= 9 else 16 if abi >= 5 else 15
    attributes = _Ruleset(
        (1 << fs_bits) - 1, 15 if abi >= 10 else 3 if abi >= 4 else 0, 3 if abi >= 6 else 0
    )
    descriptor = library.syscall(
        _CREATE,
        ctypes.byref(attributes),
        ctypes.c_size_t(ctypes.sizeof(attributes)),
        ctypes.c_uint(0),
    )
    if descriptor < 0:
        raise SandboxError("sandbox_setup_failed")
    try:
        if library.prctl(38, 1, 0, 0, 0) or library.syscall(
            _RESTRICT, descriptor, ctypes.c_uint(0)
        ):
            raise SandboxError("sandbox_setup_failed")
    finally:
        os.close(descriptor)
    return observed_abi


def _preload():
    # Lazy imports/native dlopen must finish before even reading archive bytes.
    for name in (
        "librarium.xml_policy",
        "librarium.epub_inspection",
        "librarium.epub_archive",
        "librarium.identifier_evidence",
        "librarium.content_evidence",
        "librarium.source_attribution",
        "librarium.contents_rules",
        "librarium.contents_observations",
        "librarium.contents_planning",
    ):
        importlib.import_module(name)
    # Expat's unknown-encoding handler uses Python codecs, including CJK extensions.
    codec_entries = {}
    for module in pkgutil.iter_modules(encodings.__path__):
        if module.name not in {"mbcs", "oem"}:
            loaded = importlib.import_module("encodings." + module.name)
            if hasattr(loaded, "getregentry"):
                codec_entries[module.name] = loaded.getregentry()
    aliases = encodings.aliases.aliases.copy()

    def codec_search(name):
        normalized = encodings.normalize_encoding(name)
        canonical = aliases.get(normalized) or aliases.get(normalized.replace(".", "_"))
        return codec_entries.get(canonical or normalized)

    # Unknown input encoding names must remain LookupError, without speculative imports.
    codecs.unregister(encodings.search_function)
    codecs.register(codec_search)


class _NoLateImports:
    def find_spec(self, fullname, path=None, target=None):
        os._exit(EXIT_CODES["sandbox_late_import"])


def _import_audit(event, arguments):
    if event == "import":
        # A codec/optional-import handler must not swallow this into a changed verdict.
        os._exit(EXIT_CODES["sandbox_late_import"])


def restrict():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SandboxError("sandbox_platform_unavailable")
    _preload()
    # Load seccomp while runtime libraries remain accessible; Landlock grants nothing.
    try:
        deny_network(python_child=True)
    except SeccompUnavailable:
        raise SandboxError("sandbox_seccomp_unavailable") from None
    restrict_filesystem()
    sys.meta_path.insert(0, _NoLateImports())
    sys.addaudithook(_import_audit)
