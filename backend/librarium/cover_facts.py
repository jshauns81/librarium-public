"""Bounded, isolated cover observations; no image decoder runs in the worker.

Ported from Library Finish services/bookindex/app/cover_facts.py (measure) and
services/coverart/app/server.py (problem), commit
72bdf39eb986f7e4dc52eb9e0fb528afe767e01d. Related regression cases are retained
in tests/test_cover_facts.py. Calibre's comment and 1200x1600 flatness rule remain
separate from the grayscale blank detector; none certifies artistic quality.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from librarium.inspection_process import InspectionProcessError, _exchange, sandbox_preflight

POLICY = "librarium.cover-facts.v1"
MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 25_000_000
WALL_SECONDS = 5.0
REASONS = ("missing", "generated", "blank", "width_below_1000", "height_below_1200")


def unknown(error, digest=""):
    return {
        "status": "unresolved",
        "error": error,
        "width": None,
        "height": None,
        "placeholder": None,
        "blank": None,
        "reasons": [],
        "sha256": digest,
        "detector": POLICY,
        "media_type": None,
    }


def inspect_cover(raw: bytes, *, interrupted=None) -> dict:
    if type(raw) is not bytes:
        raise TypeError("Cover input must be bytes")
    if len(raw) > MAX_BYTES:
        return unknown("oversize")
    digest = hashlib.sha256(raw).hexdigest()
    process = None
    try:
        sandbox_preflight()
        header = json.dumps({"size": len(raw), "parent_pid": os.getpid()}).encode() + b"\n"
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).absolute().with_name("cover_process.py")),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            close_fds=True,
            start_new_session=True,
        )
        output = _exchange(
            process, header + raw, time.monotonic() + WALL_SECONDS, 8192, interrupted
        )
        result = json.loads(output)
        if (
            type(result) is not dict
            or result.get("sha256") != digest
            or result.get("detector") != POLICY
            or result.get("status") not in {"known", "unresolved"}
            or type(result.get("reasons")) is not list
            or any(reason not in REASONS for reason in result["reasons"])
        ):
            raise ValueError
        return result
    except InspectionProcessError, OSError, ValueError, TypeError:
        return unknown("inspection_failed", digest)
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
