"""Real, short-lived Python children prove resource and transport isolation."""

import hashlib
import os
import signal
import time
from dataclasses import replace
from pathlib import Path

import pytest
from librarium.epub_inspection import InspectionPolicy
from test_epub_inspection import archive, inspect


def isolated(data, policy=None):
    from librarium.inspection_process import inspect_isolated

    return inspect_isolated(data, hashlib.sha256(data).hexdigest(), policy or InspectionPolicy())


def parser_stub(tmp_path, monkeypatch, body, *, setup=""):
    from librarium import inspection_process

    package = tmp_path / "backend" / "librarium"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "__path__.append(" + repr(str(Path(inspection_process.__file__).parent)) + ")\n"
    )
    child = package / "inspection_process.py"
    child.write_bytes(Path(inspection_process.__file__).read_bytes())
    (package / "epub_inspection.py").write_text(
        "import os, resource, sys, time\n"
        "assert resource.getrlimit(resource.RLIMIT_AS) == (512 * 1024 * 1024,) * 2\n"
        "assert 0 < resource.getrlimit(resource.RLIMIT_CPU)[0] <= 10\n"
        "assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)\n" + setup + "\n"
        "class InspectionPolicy:\n"
        "    def __init__(self, **kwargs): self.__dict__.update(kwargs)\n"
        "def inspect_bytes(data, expected_sha256, policy):\n"
        + "\n".join("    " + line for line in body.splitlines())
        + "\n"
    )
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)
    return inspection_process


def test_clean_report_matches_direct_parser():
    data = archive()
    assert isolated(data) == inspect(data)


def test_child_pid_and_limits_are_set_before_parser_import(tmp_path, monkeypatch):
    module = parser_stub(
        tmp_path,
        monkeypatch,
        "return {'pid': os.getpid(), 'as': resource.getrlimit(resource.RLIMIT_AS), "
        "'cpu': resource.getrlimit(resource.RLIMIT_CPU), "
        "'core': resource.getrlimit(resource.RLIMIT_CORE)}",
    )
    report = isolated(b"synthetic")
    assert report["pid"] != os.getpid()
    assert report["as"] == [module.ADDRESS_SPACE_BYTES] * 2
    assert report["cpu"] == [module.CPU_SECONDS] * 2
    assert report["core"] == [0, 0]
    with pytest.raises(ProcessLookupError):
        os.kill(report["pid"], 0)


def test_oversize_input_is_rejected_before_process_start(monkeypatch):
    from librarium import inspection_process

    monkeypatch.setattr(
        inspection_process.subprocess,
        "Popen",
        lambda *a, **kw: pytest.fail("oversize input started a child"),
    )
    with pytest.raises(inspection_process.InspectionProcessError):
        isolated(b"123", replace(InspectionPolicy(), max_archive_bytes=2))


@pytest.mark.parametrize("startup_delay", [0, 1])
def test_wall_timeout_kills_and_reaps_child(tmp_path, monkeypatch, startup_delay):
    module = parser_stub(
        tmp_path,
        monkeypatch,
        "time.sleep(20)\nreturn {}",
        setup=f"time.sleep({startup_delay})",
    )
    processes = []
    popen = module.subprocess.Popen

    def start_child(*args, **kwargs):
        process = popen(*args, **kwargs)
        if args[0][-1] == "--child":
            processes.append(process)
        return process

    # The parent knows the PID even when the child cannot finish parser startup.
    monkeypatch.setattr(module.subprocess, "Popen", start_child)
    monkeypatch.setattr(module, "WALL_SECONDS", 0.5)
    with pytest.raises(module.InspectionProcessError):
        isolated(b"synthetic")
    assert len(processes) == 1
    process = processes[0]
    assert process.returncode == -signal.SIGKILL
    with pytest.raises(ChildProcessError):
        os.waitpid(process.pid, os.WNOHANG)
    with pytest.raises(ProcessLookupError):
        os.kill(process.pid, 0)


@pytest.mark.parametrize(
    "body",
    [
        "data = bytes(2 * 512 * 1024 * 1024)\nreturn {}",
        "while True: pass",
        "return {'blob': 'x' * (1024 * 1024 + 1)}",
        "sys.stdout.write('x' * (1024 * 1024 + 1))\nsys.stdout.flush()\ntime.sleep(20)",
        "os.abort()",
    ],
)
def test_resource_native_and_transport_failures_are_safe(tmp_path, monkeypatch, body):
    module = parser_stub(tmp_path, monkeypatch, body)
    monkeypatch.setattr(module, "CPU_SECONDS", 1)
    with pytest.raises(module.InspectionProcessError) as error:
        isolated(b"synthetic")
    assert str(error.value) == "EPUB inspection process failed"


def test_interruption_callback_stops_and_reaps_waiting_parser(tmp_path, monkeypatch):
    import time

    from librarium.inspection_process import inspect_isolated

    pid_file = tmp_path / "interrupted-pid"
    module = parser_stub(
        tmp_path,
        monkeypatch,
        "os.write(probe_fd, str(os.getpid()).encode())\ntime.sleep(20)\nreturn {}",
        setup=f"probe_fd = os.open({str(pid_file)!r}, os.O_CREAT | os.O_WRONLY, 0o600)",
    )
    started = time.monotonic()
    with pytest.raises(module.InspectionProcessError):
        inspect_isolated(
            b"synthetic",
            "a" * 64,
            InspectionPolicy(),
            interrupted=lambda: pid_file.exists() and bool(pid_file.read_text()),
        )
    assert time.monotonic() - started < 2
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def active_process(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError, ProcessLookupError:
        return False


def test_successful_child_exit_terminates_surviving_descendant(tmp_path, monkeypatch):
    module = parser_stub(
        tmp_path,
        monkeypatch,
        "return {'descendant': pid}",
        setup="pid = os.fork()\nif pid == 0:\n    time.sleep(20)\n    os._exit(0)",
    )
    monkeypatch.setattr(module, "WALL_SECONDS", 2)
    result = isolated(b"synthetic")
    # SIGKILL is sent before return; an orphan is not ours to wait for, so allow delivery.
    deadline = time.monotonic() + 2
    while active_process(result["descendant"]) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not active_process(result["descendant"])


def test_parent_death_terminates_parser_and_its_descendant(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    marker = tmp_path / "owned-processes"
    module = parser_stub(
        tmp_path,
        monkeypatch,
        "os.write(probe_fd, (str(os.getpid()) + ' ' + str(pid)).encode())\n"
        + "time.sleep(20)\nreturn {}",
        setup=(
            f"probe_fd = os.open({str(marker)!r}, os.O_CREAT | os.O_WRONLY, 0o600)\n"
            "pid = os.fork()\nif pid == 0:\n    time.sleep(20)\n    os._exit(0)"
        ),
    )
    code = (
        "from pathlib import Path\nfrom librarium import inspection_process as p\n"
        "from librarium.epub_inspection import InspectionPolicy\n"
        f"p._CHILD_PATH = Path({str(module._CHILD_PATH)!r})\n"
        "p.inspect_isolated(b'synthetic', 'a'*64, InspectionPolicy())\n"
    )
    runner = subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    owned = []
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if marker.exists() and len(marker.read_text().split()) == 2:
                break
            time.sleep(0.02)
        assert marker.exists()
        owned = [int(value) for value in marker.read_text().split()]
        assert len(owned) == 2
        runner.kill()
        runner.wait(timeout=2)
        while time.monotonic() < deadline:
            active = []
            for pid in owned:
                if active_process(pid):
                    active.append(pid)
            if not active:
                break
            time.sleep(0.02)
        assert not active
    finally:
        if runner.poll() is None:
            runner.kill()
            runner.wait(timeout=2)
        if owned:
            import signal

            try:
                os.killpg(owned[0], signal.SIGKILL)
            except ProcessLookupError:
                pass
