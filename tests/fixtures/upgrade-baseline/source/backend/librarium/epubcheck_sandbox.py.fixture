"""Landlock filesystem restrictions for the single-threaded checker launcher."""

import ctypes
import errno
import os
import platform
import stat
import struct
from pathlib import Path

# Linux x86-64 UAPI numbers; this release's Java runtime is pinned to amd64.
_CREATE, _ADD, _RESTRICT = 444, 445, 446
_EXECUTE, _WRITE, _READ, _READ_DIR = 1, 2, 4, 8
_HANDLED = (1 << 15) - 1
_SCRATCH = (
    _READ | _READ_DIR | _WRITE | (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 13) | (1 << 14)
)


class _Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


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


def available():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        return False
    return _library().syscall(_CREATE, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1)) >= 3


def restrict_filesystem(java: Path, jars: list[Path], directory: Path):
    """Deny file reads/writes beyond the runtime inputs and private scratch area."""
    if not available():
        raise OSError(errno.ENOSYS, "The filesystem sandbox is unavailable")
    library = _library()
    attributes = _Ruleset(_HANDLED)
    ruleset = library.syscall(
        _CREATE,
        ctypes.byref(attributes),
        ctypes.c_size_t(ctypes.sizeof(attributes)),
        ctypes.c_uint(0),
    )
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), "The filesystem sandbox is unavailable")
    try:
        runtime = java.resolve().parent.parent
        read_directories = [
            runtime,
            runtime / "conf",
            Path("/lib"),
            Path("/lib64"),
            Path("/usr/lib"),
            Path("/usr/lib64"),
            Path("/usr/share/fonts"),
            Path("/usr/share/zoneinfo"),
            Path("/etc/fonts"),
            Path("/etc/java-21-openjdk"),
            Path("/var/cache/fontconfig"),
            Path("/proc/self"),
            Path("/proc/thread-self"),
            Path("/sys/devices/system/cpu"),
            Path("/sys/fs/cgroup"),
        ]
        read_files = [
            Path("/etc/ld.so.cache"),
            Path("/etc/localtime"),
            Path("/etc/timezone"),
            Path("/etc/nsswitch.conf"),
            Path("/etc/passwd"),
            Path("/etc/group"),
            Path("/etc/hosts"),
            Path("/etc/resolv.conf"),
            Path("/proc/meminfo"),
            Path("/proc/cpuinfo"),
            Path("/proc/stat"),
            Path("/proc/sys/kernel/threads-max"),
            Path("/proc/sys/kernel/pid_max"),
            Path("/proc/sys/vm/max_map_count"),
            *jars,
        ]
        rules = [(path, _READ | _READ_DIR | _EXECUTE) for path in read_directories]
        rules += [(path, _READ) for path in read_files]
        rules += [(directory, _SCRATCH)]
        rules += [
            (Path(path), _READ | _WRITE)
            for path in ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom")
        ]
        for path, access in rules:
            try:
                descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except FileNotFoundError:
                continue
            try:
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    access &= _READ | _WRITE | _EXECUTE | (1 << 14)
                rule = ctypes.create_string_buffer(struct.pack("=Qi", access, descriptor), 12)
                if library.syscall(
                    _ADD, ruleset, ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0)
                ):
                    raise OSError(
                        ctypes.get_errno(), "The filesystem sandbox could not be configured"
                    )
            finally:
                os.close(descriptor)
        if library.prctl(38, 1, 0, 0, 0) or library.syscall(_RESTRICT, ruleset, ctypes.c_uint(0)):
            raise OSError(ctypes.get_errno(), "The filesystem sandbox could not be applied")
    finally:
        os.close(ruleset)
