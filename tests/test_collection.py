"""Keep test identifiers safe for runner logs and JUnit reports."""

import subprocess
import sys
from pathlib import Path


def test_collected_node_ids_fit_runner_logs():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-n", "0"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    node_ids = [
        line
        for line in result.stdout.splitlines()
        if line.startswith(("backend/tests/", "tests/")) and "::" in line
    ]
    assert node_ids, "Suite collection returned no node IDs"
    oversized = [
        f"{node_id.split('[', 1)[0]}: {len(node_id)} characters"
        for node_id in node_ids
        if len(node_id) > 400
    ]
    assert not oversized, "Oversized collected node IDs:\n" + "\n".join(oversized)
