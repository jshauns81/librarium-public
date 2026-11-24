"""Exercise the actual decoder sandbox, clean environment and wall deadline."""

import json
import subprocess
import sys
from pathlib import Path

from librarium import cover_facts
from tests.test_cover_facts import jpeg


def test_decoder_child_cannot_read_files_open_sockets_or_spawn(tmp_path):
    secret = tmp_path / "private.txt"
    secret.write_text("not decoder input")
    source_root = Path(cover_facts.__file__).resolve().parent.parent
    script = tmp_path / "sandbox_probe.py"
    script.write_text("""
import json, os, socket, subprocess, sys
sys.path.insert(0, sys.argv[1])
from librarium.cover_process import sandbox
sandbox()
result = []
for probe in [lambda: open(sys.argv[2], "rb"), lambda: socket.socket(), lambda: subprocess.Popen([sys.executable, "-c", "pass"])]:
    try:
        probe()
        result.append("allowed")
    except OSError:
        result.append("denied")
print(json.dumps(result))
""")
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(script), str(source_root), str(secret)],
        check=False,
        capture_output=True,
        timeout=10,
        env={"LANG": "C.UTF-8"},
    )
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout) == ["denied", "denied", "denied"]


def test_decoder_does_not_inherit_runtime_credentials_or_descriptors(monkeypatch):
    captured = {}
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setenv("PGPASSWORD", "synthetic-secret-never-forwarded")
    monkeypatch.setenv("LIBRARIUM_SECRET_KEY", "synthetic-secret-never-forwarded")
    monkeypatch.setattr(subprocess, "Popen", spawn)
    assert cover_facts.inspect_cover(jpeg(art=True))["status"] == "known"
    assert captured["env"] == {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    assert captured["close_fds"] is True and captured["start_new_session"] is True


def test_expired_wall_deadline_reaps_the_child(monkeypatch):
    started = []
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        started.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(cover_facts, "WALL_SECONDS", 0.0)
    assert cover_facts.inspect_cover(jpeg())["error"] == "inspection_failed"
    assert started and started[0].poll() is not None
    assert not Path(f"/proc/{started[0].pid}").exists()


def test_census_interruption_kills_and_reaps_a_stalled_decoder(monkeypatch):
    started = []
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        if not any(str(arg).endswith("cover_process.py") for arg in args[0]):
            return original(*args, **kwargs)
        process = original([sys.executable, "-I", "-c", "import time; time.sleep(30)"], **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    checked = []

    def interrupted():
        checked.append(True)
        return True

    result = cover_facts.inspect_cover(jpeg(), interrupted=interrupted)
    assert checked and result["error"] == "inspection_failed"
    assert started and started[0].poll() is not None
    assert not Path(f"/proc/{started[0].pid}").exists()
