"""Sandboxed canonical JPEG and LF layout fingerprint, never ambient image decoding."""

import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from librarium.cover_facts import MAX_BYTES
from librarium.inspection_process import InspectionProcessError, _exchange, sandbox_preflight


def prepare(raw):
    if type(raw) is not bytes or not 6000 <= len(raw) <= MAX_BYTES:
        raise ValueError("Image byte size refused.")
    sandbox_preflight()
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("cover_source_image_child.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        close_fds=True,
        start_new_session=True,
    )
    try:
        header = json.dumps({"size": len(raw), "parent_pid": os.getpid()}).encode() + b"\n"
        value = json.loads(
            _exchange(child, header + raw, time.monotonic() + 12, 24 * 1024 * 1024, None)
        )
        value["data"] = base64.b64decode(value["data"], validate=True)
        return value
    except InspectionProcessError, ValueError, KeyError:
        raise ValueError("This image could not be admitted.") from None
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        for stream in (child.stdin, child.stdout):
            if stream:
                stream.close()
