"""Shared deny-network filter for single-threaded native child launchers."""

import ctypes
import ctypes.util
import errno
import sys


class SeccompUnavailable(Exception):
    pass


class _Comparison(ctypes.Structure):
    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_uint),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


def deny_network(*, python_child=False):
    """Install the shared filter, with process controls only for Python."""
    _filter(python_child=python_child, load=True)


def check_available():
    """Construct the Python policy and query kernel support without attaching it."""
    _filter(python_child=True, load=False)


def _filter(*, python_child, load):
    if sys.platform != "linux":
        raise SeccompUnavailable()
    name = ctypes.util.find_library("seccomp")
    if not name:
        raise SeccompUnavailable()
    try:
        library = ctypes.CDLL(name)
    except OSError:
        raise SeccompUnavailable() from None
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_release.restype = None
    context = library.seccomp_init(0x7FFF0000)
    if not context:
        raise SeccompUnavailable()
    try:
        for syscall in (b"socket", b"socketpair", b"socketcall", b"connect", b"io_uring_setup"):
            number = library.seccomp_syscall_resolve_name(syscall)
            if number < 0:
                if syscall == b"socketcall":
                    continue  # Absent on x86-64; mandatory calls must resolve.
                raise SeccompUnavailable()
            if library.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0):
                raise SeccompUnavailable()
        if python_child:
            for syscall in (
                b"setsid",
                b"setpgid",
                b"fork",
                b"vfork",
                b"execve",
                b"execveat",
                b"unshare",
                b"setns",
                b"setuid",
                b"setgid",
                b"setreuid",
                b"setregid",
                b"setresuid",
                b"setresgid",
                b"setfsuid",
                b"setfsgid",
            ):
                number = library.seccomp_syscall_resolve_name(syscall)
                if number < 0 or library.seccomp_rule_add(
                    context, 0x00050000 | errno.EPERM, number, 0
                ):
                    raise SeccompUnavailable()
            # MASKED_EQ(flags & CLONE_THREAD, 0) blocks new processes, not threads.
            for syscall, action, comparison in (
                (b"clone", errno.EPERM, _Comparison(0, 7, 0x10000, 0)),
                (b"prctl", errno.EPERM, _Comparison(0, 7, 0xFFFFFFFF, 1)),
                # clone3 flags are behind a pointer; ENOSYS makes pthread use clone.
                (b"clone3", errno.ENOSYS, None),
            ):
                number = library.seccomp_syscall_resolve_name(syscall)
                arguments = (comparison,) if comparison is not None else ()
                if number < 0 or library.seccomp_rule_add(
                    context, 0x00050000 | action, number, len(arguments), *arguments
                ):
                    raise SeccompUnavailable()
        if load:
            if library.seccomp_load(context):
                raise SeccompUnavailable()
        else:
            # SECCOMP_GET_ACTION_AVAIL is read-only and does not change no_new_privs.
            required_action = ctypes.c_uint32(0x00050000)
            kernel = ctypes.CDLL(None, use_errno=True)
            kernel.syscall.restype = ctypes.c_long
            if kernel.syscall(317, 2, 0, ctypes.byref(required_action)) != 0:
                raise SeccompUnavailable()
    finally:
        library.seccomp_release(context)
