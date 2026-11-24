import hashlib
import json
import subprocess
import tarfile

import pytest

from scripts.capture_source import capture, verify


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("raise RuntimeError('must never execute')\n")
    (repo / "src/.env").write_text("PRIVATE=test-only\n")
    (repo / "src/book.epub").write_bytes(b"test-only")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "source",
        ],
        check=True,
    )
    return repo


def test_capture_is_repeatable_committed_source_only(repository, tmp_path):
    first = capture(repository, "HEAD", ["src"], tmp_path / "first")
    (repository / "src/app.py").write_text("dirty local change\n")
    (repository / "src/untracked.py").write_text("untracked\n")
    second = capture(repository, "HEAD", ["src"], tmp_path / "second")
    assert first == second
    assert list(first["files"]) == ["src/app.py"]
    with tarfile.open(tmp_path / "first/source.tar") as archive:
        assert archive.getnames() == ["src/app.py"]
        assert archive.extractfile("src/app.py").read().startswith(b"raise RuntimeError")
    assert verify(tmp_path / "first") == first
    assert (
        hashlib.sha256((tmp_path / "first/source.tar").read_bytes()).hexdigest()
        == first["archive_sha256"]
    )


def test_symlinks_are_refused_without_following(repository, tmp_path):
    (repository / "src/link.py").symlink_to("/etc/passwd")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "link",
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="link|mode"):
        capture(repository, "HEAD", ["src"], tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_capture_refuses_overwrite_and_integrity_tampering(repository, tmp_path):
    capture(repository, "HEAD", ["src"], tmp_path / "snapshot")
    with pytest.raises(FileExistsError):
        capture(repository, "HEAD", ["src"], tmp_path / "snapshot")
    manifest = tmp_path / "snapshot/manifest.json"
    value = json.loads(manifest.read_text())
    value["files"]["src/app.py"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="integrity"):
        verify(manifest.parent)


@pytest.mark.parametrize("path", ["../src", "/tmp", ".", "src/../src", "src\\app.py"])
def test_capture_rejects_unsafe_selection(repository, tmp_path, path):
    with pytest.raises(ValueError):
        capture(repository, "HEAD", [path], tmp_path / "bad")
