import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from librarium_lab.snapshots import SnapshotError, capture, extract_archive, verify


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def upstream(tmp_path):
    root = tmp_path / "upstream"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "remote", "add", "origin", "https://github.com/jshauns81/library-finish.git")
    (root / "module.py").write_text('def hello():\n    return "committed"\n')
    git(root, "add", "module.py")
    git(root, "commit", "-qm", "Fixture baseline")
    return root


def test_capture_uses_committed_bytes_and_preserves_the_checkout(upstream, tmp_path):
    lab = tmp_path / "lab"
    before = git(upstream, "rev-parse", "HEAD")
    (upstream / "module.py").write_text("uncommitted work\n")
    (upstream / ".env").write_text("fixture-only-untracked-value\n")
    entry = capture(lab, "library-finish", upstream, "HEAD")
    assert entry["commit"] == before
    snapshot = lab / ".snapshots" / "library-finish" / before
    assert 'return "committed"' in (snapshot / "module.py").read_text()
    assert not (snapshot / ".env").exists()
    assert (upstream / "module.py").read_text() == "uncommitted work\n"
    assert git(upstream, "rev-parse", "HEAD") == before
    assert verify(lab, "library-finish")["commit"] == before


def test_repeated_capture_is_deterministic(upstream, tmp_path):
    lab = tmp_path / "lab"
    first = capture(lab, "library-finish", upstream, "HEAD")
    first_lock = (lab / "snapshots.lock.json").read_bytes()
    assert capture(lab, "library-finish", upstream, "HEAD") == first
    assert (lab / "snapshots.lock.json").read_bytes() == first_lock


def test_refresh_records_changed_added_and_removed_paths(upstream, tmp_path):
    lab = tmp_path / "lab"
    first = capture(lab, "library-finish", upstream, "HEAD")
    (upstream / "module.py").unlink()
    (upstream / "next.py").write_text("VALUE = 2\n")
    git(upstream, "add", "-A")
    git(upstream, "commit", "-qm", "Fixture update")
    second = capture(lab, "library-finish", upstream, "HEAD")
    report = json.loads((lab / "baselines" / "library-finish.json").read_text())
    assert second["commit"] != first["commit"]
    assert report["previous_commit"] == first["commit"]
    assert report["changes"] == {"added": ["next.py"], "removed": ["module.py"], "changed": []}
    assert (lab / ".snapshots" / "library-finish" / first["commit"]).is_dir()


def test_tampered_snapshot_is_refused(upstream, tmp_path):
    lab = tmp_path / "lab"
    entry = capture(lab, "library-finish", upstream, "HEAD")
    (lab / ".snapshots" / "library-finish" / entry["commit"] / "module.py").write_text("bad\n")
    with pytest.raises(SnapshotError, match="digest"):
        verify(lab, "library-finish")
    with pytest.raises(SnapshotError, match="digest"):
        capture(lab, "library-finish", upstream, "HEAD")


def test_wrong_repository_and_option_like_ref_are_refused(upstream, tmp_path):
    with pytest.raises(SnapshotError, match="revision"):
        capture(tmp_path / "lab", "library-finish", upstream, "--help")
    git(upstream, "remote", "set-url", "origin", "https://github.com/someone/other.git")
    with pytest.raises(SnapshotError, match="repository"):
        capture(tmp_path / "lab", "library-finish", upstream, "HEAD")


@pytest.mark.parametrize("name,kind", [("../escaped", "file"), ("/escaped", "file"), ("link", "hardlink")])
def test_unsafe_archive_members_are_refused(tmp_path, name, kind):
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as tar:
        member = tarfile.TarInfo(name)
        if kind == "hardlink":
            member.type = tarfile.LNKTYPE
            member.linkname = "../escaped"
            tar.addfile(member)
        else:
            member.size = 1
            tar.addfile(member, io.BytesIO(b"x"))
    target = tmp_path / "snapshot"
    target.mkdir()
    with pytest.raises(SnapshotError, match="archive"):
        extract_archive(archive, target)
    assert not (tmp_path / "escaped").exists()


def test_symlinks_are_recorded_without_following_or_creating_them(tmp_path):
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as tar:
        member = tarfile.TarInfo("artwork.png")
        member.type = tarfile.SYMTYPE
        member.linkname = "/outside/never-read"
        tar.addfile(member)
    target = tmp_path / "snapshot"
    target.mkdir()
    records = extract_archive(archive, target)
    assert records["artwork.png"]["kind"] == "symlink"
    assert records["artwork.png"]["target"] == "/outside/never-read"
    assert not (target / "artwork.png").exists()
