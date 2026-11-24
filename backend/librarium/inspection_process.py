"""Linux resource isolation for one EPUB inspection; no parser in the parent."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

ADDRESS_SPACE_BYTES = 512 * 1024 * 1024
CPU_SECONDS = 10
WALL_SECONDS = 15.0
REPORT_BYTES = 1024 * 1024
_CHILD_PATH = Path(__file__).absolute()


class InspectionProcessError(Exception):
    def __init__(self, code=None):
        self.code = code
        super().__init__("EPUB inspection process failed")


def _read_header(limit):
    # Buffered stdin can prefetch archive bytes before sandbox installation.
    header = bytearray()
    while len(header) < limit:
        byte = os.read(sys.stdin.fileno(), 1)
        if not byte:
            raise InspectionProcessError()
        if byte == b"\n":
            return json.loads(header)
        header.extend(byte)
    raise InspectionProcessError()


def _exchange(process, payload, deadline, output_limit, interrupted=None):
    output = bytearray()
    remaining = memoryview(payload)
    next_interruption_check = 0.0
    with selectors.DefaultSelector() as selector:
        for stream in (process.stdin, process.stdout):
            os.set_blocking(stream.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise InspectionProcessError()
            if interrupted is not None and time.monotonic() >= next_interruption_check:
                if interrupted():
                    raise InspectionProcessError()
                next_interruption_check = time.monotonic() + 0.05
            for key, _ in selector.select(min(timeout, 0.1)):
                if key.events & selectors.EVENT_WRITE:
                    try:
                        sent = os.write(process.stdin.fileno(), remaining[:65536])
                    except BrokenPipeError:
                        selector.unregister(process.stdin)
                        process.stdin.close()
                        continue
                    remaining = remaining[sent:]
                    if not remaining:
                        selector.unregister(process.stdin)
                        process.stdin.close()
                else:
                    chunk = os.read(
                        process.stdout.fileno(), min(65536, output_limit + 1 - len(output))
                    )
                    if not chunk:
                        selector.unregister(process.stdout)
                    else:
                        output.extend(chunk)
                        if len(output) > output_limit:
                            raise InspectionProcessError()
    while process.poll() is None:
        if time.monotonic() >= deadline or interrupted is not None and interrupted():
            raise InspectionProcessError()
        try:
            process.wait(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            pass
    if process.returncode != 0 or remaining:
        from librarium.python_sandbox import EXIT_CODES

        code = next(
            (code for code, status in EXIT_CODES.items() if status == process.returncode),
            None,
        )
        if process.returncode in {20, 21, 22}:
            # Parent preflight passed; this status cannot establish a host limitation.
            code = "sandbox_setup_failed"
        raise InspectionProcessError(code)
    return output


def sandbox_preflight():
    from librarium.python_sandbox import SandboxError, preflight

    try:
        return preflight()
    except SandboxError as error:
        raise InspectionProcessError(error.code) from None


def inspect_isolated(data: bytes, expected_sha256: str, policy, *, interrupted=None) -> dict:
    if sys.platform != "linux":
        raise InspectionProcessError("sandbox_platform_unavailable")
    if type(data) is not bytes or len(data) > policy.max_archive_bytes:
        raise InspectionProcessError()
    sandbox_preflight()
    header = {
        "digest": expected_sha256,
        "policy": asdict(policy),
        "size": len(data),
        "memory": ADDRESS_SPACE_BYTES,
        "cpu": CPU_SECONDS,
        "parent_pid": os.getpid(),
    }
    payload = json.dumps(header, separators=(",", ":")).encode() + b"\n" + data
    deadline = time.monotonic() + WALL_SECONDS
    environment = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if "LIBARCHIVE" in os.environ:
        environment["LIBARCHIVE"] = os.environ["LIBARCHIVE"]
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(_CHILD_PATH), "--child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            close_fds=True,
            start_new_session=True,
        )
        output = _exchange(
            process, payload, deadline, min(REPORT_BYTES, policy.max_output_bytes), interrupted
        )
        result = json.loads(output)
        if type(result) is not dict:
            raise InspectionProcessError()
        return result
    except OSError, ValueError, subprocess.TimeoutExpired:
        raise InspectionProcessError() from None
    finally:
        if process is not None:
            # Reap descendants even when the direct child has already exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


def parent_guard(expected_parent):
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != expected_parent:
        raise InspectionProcessError()


def process_group_guard():
    """An FD-free watcher kills the session if the parser dies with descendants."""
    parser_pid, group = os.getpid(), os.getpgrp()
    if os.fork() == 0:
        for descriptor in range(32):
            try:
                os.close(descriptor)
            except OSError:
                pass
        while os.getppid() == parser_pid:
            time.sleep(0.05)
        try:
            os.killpg(group, signal.SIGKILL)
        finally:
            os._exit(0)


def _child():
    import resource

    header = _read_header(8192)
    parent_guard(header["parent_pid"])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (header["memory"],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (header["cpu"],) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    process_group_guard()
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
    from librarium.epub_inspection import InspectionPolicy, inspect_bytes
    from librarium.python_sandbox import restrict

    restrict()
    policy = InspectionPolicy(**header["policy"])
    if not 0 <= header["size"] <= policy.max_archive_bytes:
        raise InspectionProcessError()
    data = sys.stdin.buffer.read(header["size"] + 1)
    if len(data) != header["size"]:
        raise InspectionProcessError()
    report = inspect_bytes(data, header["digest"], policy)
    encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > min(REPORT_BYTES, policy.max_output_bytes):
        raise InspectionProcessError()
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    if sys.argv[1:] != ["--child"] or sys.platform != "linux":
        sys.exit(2)
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
    from librarium.python_sandbox import EXIT_CODES, SandboxError

    try:
        _child()
    except SandboxError as error:
        sys.exit(EXIT_CODES[error.code])
    except Exception:  # noqa: BLE001 -- The child returns only a safe process exit status.
        sys.exit(3)
