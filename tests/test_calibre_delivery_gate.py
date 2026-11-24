"""Required native proof; invoke explicitly with the isolated pinned runtime."""

import json
import os
import subprocess
from hashlib import file_digest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_pinned_owner_conditional_replacement(tmp_path):
    runtime = os.environ.get("LIBRARIUM_CALIBRE_RUNTIME")
    if runtime is None:
        if os.environ.get("LIBRARIUM_REQUIRE_NATIVE") == "1":
            pytest.fail("LIBRARIUM_CALIBRE_RUNTIME required")
        pytest.skip("dedicated native acceptance requires LIBRARIUM_CALIBRE_RUNTIME")
    pin = json.loads((ROOT / "scripts/calibre_delivery_runtime.json").read_text())
    archive = Path(runtime).parent / "calibre-9.17.0-x86_64.txz"
    with archive.open("rb") as stream:
        assert file_digest(stream, "sha256").hexdigest() == pin["sha256"]
    (tmp_path / "scratch").mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CALIBRE_CONFIG_DIRECTORY": str(tmp_path / "config"),
        "CALIBRE_TEMP_DIR": str(tmp_path / "scratch"),
        "QT_QPA_PLATFORM": "offscreen",
        "LANG": "C.UTF-8",
    }
    result = subprocess.run(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--net",
            str(Path(runtime) / "calibre-debug"),
            "-e",
            str(ROOT / "scripts/calibre_delivery_gate.py"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["runtime"] == "9.17.0"
    assert report["gate"] == "passed"
    assert set(report["proved"]) == {
        "conditional_replace",
        "identity_fences",
        "hooks_disabled",
        "byte_identical_readback",
        "same_cache_serialization",
        "changed_source_refused",
        "untouched_fields",
        "oracle_readback",
    }

    assert report["missing_format_held"]
    assert report["maintenance_quiesced"]
    assert report["broker_proved"] == ["apply", "replay", "undo", "drift"]
    report["archive_sha256"] = pin["sha256"]
    receipt = os.environ.get("LIBRARIUM_DELIVERY_GATE_REPORT")
    if receipt:
        Path(receipt).write_text(json.dumps(report, indent=2) + "\n")
