"""SIGKILL acceptance against real Calibre, never inferred from a fake boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_native_kill_boundaries_preserve_consumed_operations(tmp_path):
    runtime = os.environ.get("LIBRARIUM_CALIBRE_RUNTIME")
    if runtime is None:
        if os.environ.get("LIBRARIUM_REQUIRE_NATIVE") == "1":
            pytest.fail("LIBRARIUM_CALIBRE_RUNTIME required")
        pytest.skip("dedicated native acceptance requires LIBRARIUM_CALIBRE_RUNTIME")
    root = Path(__file__).resolve().parents[1]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "QT_QPA_PLATFORM": "offscreen",
        "LIBRARIUM_CALIBRE_RUNTIME": runtime,
    }
    result = subprocess.run(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--net",
            sys.executable,
            str(root / ".github/scripts/delivery_native_kills.py"),
        ],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    for mode in ("delivery", "undo"):
        outcomes = report[mode]
        assert outcomes["prepared"] == "not_applied"
        assert outcomes["send_started"] == "unobservable"
        assert outcomes["native_copy"] in {"diverged", "unobservable"}
        assert all(
            outcomes[stage] == "applied"
            for stage in ("native_returned", "readback", "receipt")
        )
    assert report["resends"] == 0
    path = os.environ.get("LIBRARIUM_DELIVERY_KILL_REPORT")
    if path:
        Path(path).write_text(json.dumps(report, indent=2) + "\n")
