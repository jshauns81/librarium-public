"""No ambient file or network access survives Python child startup."""

import ctypes
import errno
import hashlib
import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest
from librarium import inspection_process
from librarium.epub_inspection import InspectionPolicy
from test_epub_inspection import archive


def sandbox():
    from librarium import python_sandbox

    return python_sandbox


@pytest.mark.parametrize(
    "abi,fs,net",
    [
        (3, 15, 0),
        (4, 15, 3),
        (5, 16, 3),
        (6, 16, 3),
        (8, 16, 3),
        (9, 17, 3),
        (10, 17, 15),
        (11, 17, 15),
        (12, 17, 15),
    ],
)
def test_ruleset_handles_every_known_right_without_any_grants(monkeypatch, abi, fs, net):
    module = sandbox()
    library = Mock()
    library.syscall.side_effect = [abi, 91, 0]
    library.prctl.return_value = 0
    monkeypatch.setattr(module, "_library", lambda: library)
    close = Mock()
    monkeypatch.setattr(module.os, "close", close)
    module.restrict_filesystem()
    calls = library.syscall.call_args_list
    attributes = ctypes.cast(calls[1].args[1], ctypes.POINTER(module._Ruleset)).contents
    assert attributes.handled_access_fs == (1 << fs) - 1
    assert attributes.handled_access_net == net
    assert len(calls) == 3  # Query, create, restrict; no allow rules.
    library.prctl.assert_called_once_with(38, 1, 0, 0, 0)
    close.assert_called_once_with(91)


@pytest.mark.parametrize("abi", [-1, 0, 1, 2])
def test_unsupported_landlock_refuses(monkeypatch, abi):
    module = sandbox()
    library = Mock()
    library.syscall.return_value = abi
    monkeypatch.setattr(module, "_library", lambda: library)
    with pytest.raises(module.SandboxError) as error:
        module.restrict_filesystem()
    assert error.value.code == "sandbox_landlock_unavailable"


@pytest.mark.parametrize("system,machine", [("Darwin", "x86_64"), ("Linux", "aarch64")])
def test_unsupported_platform_refuses_before_syscall(monkeypatch, system, machine):
    module = sandbox()
    monkeypatch.setattr(module.platform, "system", lambda: system)
    monkeypatch.setattr(module.platform, "machine", lambda: machine)
    monkeypatch.setattr(module, "_library", lambda: pytest.fail("unsupported syscall"))
    with pytest.raises(module.SandboxError) as error:
        module.restrict_filesystem()
    assert error.value.code == "sandbox_platform_unavailable"


@pytest.mark.parametrize("stage", ["create", "privileges", "restrict"])
def test_ruleset_application_errors_fail_closed_and_close_fds(monkeypatch, stage):
    module = sandbox()
    library = Mock()
    library.syscall.side_effect = [
        6,
        -1 if stage == "create" else 91,
        -1 if stage == "restrict" else 0,
    ]
    library.prctl.return_value = -1 if stage == "privileges" else 0
    monkeypatch.setattr(module, "_library", lambda: library)
    close = Mock()
    monkeypatch.setattr(module.os, "close", close)
    with pytest.raises(module.SandboxError) as error:
        module.restrict_filesystem()
    assert error.value.code == "sandbox_setup_failed"
    assert close.call_count == (stage != "create")


@pytest.mark.parametrize("failure", [None, "missing", "dlopen", "init", "rule", "load", "resolve"])
def test_seccomp_filter_construction_and_refusal(monkeypatch, failure):
    from librarium import seccomp_sandbox as module

    library = Mock()
    library.seccomp_init.return_value = None if failure == "init" else 99
    library.seccomp_syscall_resolve_name.return_value = -1 if failure == "resolve" else 42
    library.seccomp_rule_add.return_value = -1 if failure == "rule" else 0
    library.seccomp_load.return_value = -1 if failure == "load" else 0
    monkeypatch.setattr(
        module.ctypes.util,
        "find_library",
        lambda name: None if failure == "missing" else "libseccomp.so.2",
    )

    def load(name):
        if failure == "dlopen":
            raise OSError("unavailable")
        return library

    monkeypatch.setattr(module.ctypes, "CDLL", load)
    if failure:
        with pytest.raises(module.SeccompUnavailable):
            module.deny_network()
    else:
        module.deny_network()
        names = [call.args[0] for call in library.seccomp_syscall_resolve_name.call_args_list]
        assert names == [b"socket", b"socketpair", b"socketcall", b"connect", b"io_uring_setup"]
        assert all(
            call.args == (99, 0x00050000 | errno.EPERM, 42, 0)
            for call in library.seccomp_rule_add.call_args_list
        )
        library.seccomp_load.assert_called_once_with(99)
    if failure not in {"missing", "dlopen", "init"}:
        library.seccomp_release.assert_called_once_with(99)


def test_real_kernel_denies_all_paths_sockets_and_io_uring(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("Synthetic sentinel")
    script = """import sys,os,socket,ctypes,errno,json
sys.path.insert(0,"backend")
from librarium.python_sandbox import restrict, SandboxError
libc=ctypes.CDLL(None,use_errno=True)
try: restrict()
except SandboxError as e:
    print(e.code);sys.exit(77)
assert libc.prctl(39,0,0,0,0)==1
for path,flags in [(sys.argv[1],os.O_RDONLY),(sys.argv[1],os.O_WRONLY),(sys.argv[2],os.O_CREAT|os.O_WRONLY),(sys.executable,os.O_RDONLY)]:
    try: os.close(os.open(path,flags,0o600))
    except PermissionError: pass
    else: raise AssertionError("filesystem access survived")
for family in (socket.AF_INET,socket.AF_INET6,socket.AF_UNIX):
    try: socket.socket(family)
    except PermissionError as e: assert e.errno==errno.EPERM
    else: raise AssertionError("socket creation survived")
assert libc.syscall(425,2,ctypes.c_void_p())==-1 and ctypes.get_errno()==errno.EPERM
print("restricted")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(unrelated), str(tmp_path / "created")],
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode == 77:
        reason = result.stdout.decode().strip()
        if os.environ.get("CI") or reason != "sandbox_landlock_unavailable":
            pytest.fail(f"Real kernel isolation required: {reason}")
        pytest.skip(f"Kernel isolation unavailable: {reason}")
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"restricted\n"
    assert unrelated.read_text() == "Synthetic sentinel"
    assert not (tmp_path / "created").exists()


def test_existing_fixture_inspects_under_restriction():
    source = archive()
    report = inspection_process.inspect_isolated(
        source, hashlib.sha256(source).hexdigest(), InspectionPolicy()
    )
    assert report["inspection_complete"]


@pytest.mark.parametrize(
    "code,status",
    [
        ("sandbox_platform_unavailable", 20),
        ("sandbox_landlock_unavailable", 21),
        ("sandbox_seccomp_unavailable", 22),
        ("sandbox_setup_failed", 23),
    ],
)
def test_parent_propagates_safe_sandbox_refusal(monkeypatch, tmp_path, code, status):
    child = tmp_path / "refusing.py"
    child.write_text(f"import sys;sys.stdin.buffer.read();sys.exit({status})")
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)
    with pytest.raises(inspection_process.InspectionProcessError) as error:
        inspection_process.inspect_isolated(b"synthetic", "a" * 64, InspectionPolicy())
    assert error.value.code == ("sandbox_setup_failed" if status in {20, 21, 22} else code)


def test_the_child_restricts_before_reading_untrusted_payload(monkeypatch):
    class StopBeforeBytes(Exception):
        pass

    header = {
        "parent_pid": os.getpid(),
        "memory": 512 * 1024 * 1024,
        "cpu": 10,
        "policy": {},
        "size": 0,
        "mode": "inspection",
    }

    class Input:
        def readline(self, maximum):
            return json.dumps(header).encode() + b"\n"

        def read(self, *args):
            pytest.fail("untrusted bytes were read before sandboxing")

    monkeypatch.setattr(sys, "stdin", Mock(buffer=Input()))
    monkeypatch.setattr(inspection_process, "_read_header", lambda limit: header)
    monkeypatch.setattr(inspection_process, "parent_guard", lambda pid: None)
    monkeypatch.setattr(inspection_process, "process_group_guard", lambda: None)
    import resource

    monkeypatch.setattr(resource, "setrlimit", lambda *args: None)
    module = sandbox()

    def stop():
        raise StopBeforeBytes()

    monkeypatch.setattr(module, "restrict", stop)
    with pytest.raises(StopBeforeBytes):
        inspection_process._child()


def test_large_payload_early_sandbox_refusal_is_not_hidden_by_broken_pipe(monkeypatch, tmp_path):
    child = tmp_path / "early-refusal.py"
    child.write_text("import sys;sys.exit(21)")
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)
    with pytest.raises(inspection_process.InspectionProcessError) as error:
        inspection_process.inspect_isolated(b"x" * (1024 * 1024), "a" * 64, InspectionPolicy())
    assert error.value.code == "sandbox_setup_failed"


def test_unsupported_platform_refuses_before_loading_native_dependencies(monkeypatch):
    module = sandbox()
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module, "_preload", lambda: pytest.fail("preloaded unsupported runtime"))
    with pytest.raises(module.SandboxError) as error:
        module.restrict()
    assert error.value.code == "sandbox_platform_unavailable"


def test_network_filter_failure_becomes_safe_python_refusal(monkeypatch):
    module = sandbox()
    from librarium.seccomp_sandbox import SeccompUnavailable

    monkeypatch.setattr(module, "_preload", lambda: None)
    monkeypatch.setattr(module, "deny_network", Mock(side_effect=SeccompUnavailable))
    with pytest.raises(module.SandboxError) as error:
        module.restrict()
    assert error.value.code == "sandbox_seccomp_unavailable"


def test_landlock_itself_denies_tcp_bind_and_connect():
    script = """import sys,ctypes,socket,errno
sys.path.insert(0,"backend")
from librarium.python_sandbox import _library,_CREATE,restrict_filesystem,SandboxError
abi=_library().syscall(_CREATE,ctypes.c_void_p(),ctypes.c_size_t(0),ctypes.c_uint(1))
if abi<4:
    print("Landlock ABI 4 TCP rights unavailable");sys.exit(77)
sockets=[socket.socket(socket.AF_INET,socket.SOCK_STREAM) for _ in range(2)]
restrict_filesystem()
for operation in (lambda:sockets[0].bind(("127.0.0.1",0)),lambda:sockets[1].connect(("127.0.0.1",1))):
    try: operation()
    except PermissionError as e: assert e.errno==errno.EACCES
    else: raise AssertionError("Landlock allowed TCP")
for s in sockets:s.close()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, timeout=5, check=False
    )
    if result.returncode == 77:
        pytest.skip(result.stdout.decode().strip())
    assert result.returncode == 0, result.stderr.decode()


def test_header_transport_cannot_prefetch_archive_before_restriction(monkeypatch):
    payload = bytearray(b'{"size":3}\nZIP')
    sizes = []

    def read(fd, size):
        sizes.append(size)
        chunk = bytes(payload[:size])
        del payload[:size]
        return chunk

    monkeypatch.setattr(inspection_process.os, "read", read)
    monkeypatch.setattr(sys, "stdin", Mock(fileno=lambda: 0))
    assert inspection_process._read_header(32) == {"size": 3}
    assert sizes == [1] * 11
    assert payload == b"ZIP"


@pytest.mark.parametrize("payload", [b"", b"{}", b"xxxxxxx\n"])
def test_header_transport_requires_bounded_complete_header(monkeypatch, payload):
    pending = bytearray(payload)

    def read(fd, size):
        chunk = bytes(pending[:size])
        del pending[:size]
        return chunk

    monkeypatch.setattr(inspection_process.os, "read", read)
    monkeypatch.setattr(sys, "stdin", Mock(fileno=lambda: 0))
    with pytest.raises(inspection_process.InspectionProcessError):
        inspection_process._read_header(4)


def test_launcher_platform_refusal_has_stable_code(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(inspection_process.InspectionProcessError) as error:
        inspection_process.inspect_isolated(b"x", "a" * 64, InspectionPolicy())
    assert error.value.code == "sandbox_platform_unavailable"


@pytest.mark.parametrize("abi", [3, 5, 6, 12])
def test_landlock_signal_and_abstract_socket_scopes(monkeypatch, abi):
    module = sandbox()
    library = Mock()
    library.syscall.side_effect = [abi, 91, 0]
    library.prctl.return_value = 0
    monkeypatch.setattr(module, "_library", lambda: library)
    monkeypatch.setattr(module.os, "close", lambda fd: None)
    module.restrict_filesystem()
    attributes = ctypes.cast(
        library.syscall.call_args_list[1].args[1], ctypes.POINTER(module._Ruleset)
    ).contents
    assert attributes.scoped == (3 if abi >= 6 else 0)


@pytest.mark.parametrize(
    "operation",
    [
        "signal_parent",
        "setsid",
        "setpgid",
        "fork",
        "clone",
        "clone3",
        "execve",
        "execveat",
        "unshare",
        "user_namespace",
        "setns",
        "pdeathsig",
        "memfd_exec",
    ],
)
def test_real_kernel_process_controls(operation):
    script = """import sys,os,ctypes,errno,threading
sys.path.insert(0,"backend")
from librarium.python_sandbox import restrict,_library,_CREATE
libc=ctypes.CDLL(None,use_errno=True)
abi=_library().syscall(_CREATE,ctypes.c_void_p(),ctypes.c_size_t(0),ctypes.c_uint(1))
operation=sys.argv[1]
if operation=="signal_parent" and abi<6: sys.exit(77)
image=open("/bin/true","rb").read()
fd=os.memfd_create("synthetic-image",0)
os.write(fd,image)
restrict()
operations={
 "signal_parent": lambda:libc.kill(os.getppid(),0),
 "setsid": lambda:libc.setsid(),
 "setpgid": lambda:libc.setpgid(0,0),
 "fork": lambda:libc.syscall(57),
 "clone": lambda:libc.syscall(56,17,0,0,0,0),
 "clone3": lambda:libc.syscall(435,0,0),
 "execve": lambda:libc.syscall(59,b"/missing",0,0),
 "execveat": lambda:libc.syscall(322,fd,b"",0,0,0x1000),
 "unshare": lambda:libc.syscall(272,0),
 "user_namespace": lambda:libc.syscall(272,0x10000000),
 "setns": lambda:libc.syscall(308,-1,0),
 "pdeathsig": lambda:libc.prctl(1,0,0,0,0),
 "memfd_exec": lambda:libc.fexecve(fd,(ctypes.c_char_p*2)(b"synthetic",None),(ctypes.c_char_p*1)(None)),
}
result=operations[operation]()
if result==0 and operation in {"fork","clone","vfork"}: os._exit(0)
if result>0 and operation in {"fork","clone","vfork"}: os.waitpid(result,0)
expected=errno.ENOSYS if operation=="clone3" else errno.EPERM
assert result==-1 and ctypes.get_errno()==expected,(operation,result,ctypes.get_errno())
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, operation],
        capture_output=True,
        timeout=8,
        check=False,
    )
    if result.returncode == 77:
        pytest.skip("Landlock signal scoping requires ABI 6")
    assert result.returncode == 0, result.stderr.decode()


def test_real_kernel_allows_threads_after_restriction():
    script = """import sys,threading
sys.path.insert(0,"backend")
from librarium.python_sandbox import restrict
restrict()
seen=[]
thread=threading.Thread(target=lambda:seen.append("thread"))
thread.start()
thread.join()
assert seen==["thread"]
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        capture_output=True,
        timeout=8,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_python_filter_resolves_process_rules_without_changing_java(monkeypatch):
    from librarium import seccomp_sandbox as module

    library = Mock()
    library.seccomp_init.return_value = 99
    library.seccomp_syscall_resolve_name.return_value = 42
    library.seccomp_rule_add.return_value = 0
    library.seccomp_load.return_value = 0
    monkeypatch.setattr(module.ctypes.util, "find_library", lambda name: "libseccomp.so.2")
    monkeypatch.setattr(module.ctypes, "CDLL", lambda name: library)
    module.deny_network(python_child=True)
    names = {call.args[0] for call in library.seccomp_syscall_resolve_name.call_args_list}
    assert {
        b"setsid",
        b"setpgid",
        b"fork",
        b"vfork",
        b"execve",
        b"execveat",
        b"unshare",
        b"setns",
        b"clone",
        b"clone3",
        b"prctl",
    } <= names


@pytest.mark.parametrize("probe", ["denial", "late_import", "importlib"])
def test_real_launcher_enforces_denials_and_late_import_guard(tmp_path, monkeypatch, probe):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("Synthetic sentinel")
    child = tmp_path / "probe_child.py"
    child.write_text(f"""import sys,os,socket,errno,importlib
sys.path.insert(0,{str(inspection_process._CHILD_PATH.parent.parent)!r})
from librarium import epub_inspection as domain
original=domain.inspect_bytes
def probe(*args,**kwargs):
    if {probe!r}=="denial":
        try: open({str(sentinel)!r},"rb")
        except PermissionError: pass
        else: raise AssertionError("file access survived real launcher")
        try: socket.socket()
        except PermissionError as e: assert e.errno==errno.EPERM
        else: raise AssertionError("socket creation survived real launcher")
    else:
        try:
            if {probe!r}=="importlib": importlib.import_module("sandbox_future_module")
            else: __import__("sandbox_future_module")
        except BaseException: pass
        # Catching ImportError or BaseException must never turn this into a verdict.
    return original(*args,**kwargs)
domain.inspect_bytes=probe
from librarium import inspection_process as process
process._child()
""")
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)
    source = archive()

    def run():
        return inspection_process.inspect_isolated(
            source, hashlib.sha256(source).hexdigest(), InspectionPolicy()
        )

    if probe == "denial":
        run()
    else:
        with pytest.raises(inspection_process.InspectionProcessError) as error:
            run()
        assert error.value.code == "sandbox_late_import"


@pytest.mark.parametrize("abi", [12, 13, 99])
def test_newer_abis_keep_audited_masks_and_return_observed_abi(monkeypatch, abi):
    module = sandbox()
    library = Mock()
    library.syscall.side_effect = [abi, 91, 0]
    library.prctl.return_value = 0
    monkeypatch.setattr(module, "_library", lambda: library)
    monkeypatch.setattr(module.os, "close", lambda fd: None)
    assert module.restrict_filesystem() == abi
    attributes = ctypes.cast(
        library.syscall.call_args_list[1].args[1], ctypes.POINTER(module._Ruleset)
    ).contents
    assert attributes.handled_access_fs == (1 << 17) - 1
    assert attributes.handled_access_net == 15
    assert attributes.scoped == 3
