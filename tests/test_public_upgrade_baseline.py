"""The published schema-0005 fixture is independent of the original Git repository."""

import json
import os
import shutil
from pathlib import Path

import pytest

from scripts import populated_upgrade as upgrade

FIXTURE = Path("tests/fixtures/upgrade-baseline")


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "committed-source"
    shutil.copytree(upgrade.ROOT / FIXTURE, root / FIXTURE)
    return root


def repin_for_test(manifest, value, monkeypatch):
    data = upgrade.encoded(value)
    manifest.write_bytes(data)
    monkeypatch.setattr(upgrade, "BASELINE_MANIFEST_SHA256", upgrade.digest(data))


def test_materializes_manifest_files_without_git(candidate, tmp_path):
    target = tmp_path / "old"
    receipt = upgrade.export_baseline(candidate, target)
    assert receipt["kind"] == "public_compatibility_fixture"
    assert receipt["manifest_sha256"] == upgrade.digest(
        (candidate / FIXTURE / "manifest.json").read_bytes()
    )
    assert "commit" not in receipt and "tree" not in receipt
    assert receipt["policy"]["migration_leaves"] == ["0005_epub_validation_jobs"]
    actual = {
        path.relative_to(target).as_posix(): {
            "sha256": upgrade.digest(path.read_bytes()),
            "mode": oct(path.stat().st_mode)[2:],
        }
        for path in target.rglob("*")
        if path.is_file()
    }
    assert actual == receipt["files"]


def test_fixture_image_user_can_traverse_materialized_directories(candidate, tmp_path):
    target = tmp_path / "old"
    previous = os.umask(0o077)
    try:
        upgrade.export_baseline(candidate, target)
    finally:
        os.umask(previous)
    assert target.stat().st_mode & 0o777 == 0o700
    assert all(
        directory.stat().st_mode & 0o777 == 0o755
        for directory in target.rglob("*")
        if directory.is_dir()
    )


@pytest.mark.parametrize(
    "change",
    ["manifest", "content", "missing", "extra", "file_link", "directory_link", "manifest_link"],
)
def test_fixture_integrity_is_checked_before_use(candidate, tmp_path, change):
    fixture = candidate / FIXTURE
    source = fixture / "source"
    selected = source / "Dockerfile.fixture"
    if change == "manifest":
        with (fixture / "manifest.json").open("ab") as stream:
            stream.write(b" ")
    elif change == "content":
        selected.write_bytes(b"changed")
    elif change == "missing":
        selected.unlink()
    elif change == "extra":
        (source / "undeclared.fixture").write_bytes(b"")
    else:
        selected = {
            "file_link": selected,
            "directory_link": source / "backend",
            "manifest_link": fixture / "manifest.json",
        }[change]
        other = tmp_path / "outside"
        selected.rename(other)
        selected.symlink_to(other, target_is_directory=other.is_dir())
    target = tmp_path / "old"
    with pytest.raises(ValueError):
        upgrade.export_baseline(candidate, target)
    assert not target.exists()


@pytest.mark.parametrize(
    "change", ["traversal", "absolute", "bad_mode", "wrong_policy", "source_policy"]
)
def test_repinned_fixture_still_requires_safe_paths_modes_and_schema(
    candidate, tmp_path, monkeypatch, change
):
    fixture = candidate / FIXTURE
    manifest = fixture / "manifest.json"
    value = json.loads(manifest.read_bytes())
    if change in {"traversal", "absolute"}:
        name = "../escaped" if change == "traversal" else "/escaped"
        value["files"][name] = value["files"].pop("Dockerfile")
    elif change == "bad_mode":
        value["files"]["Dockerfile"]["mode"] = "120000"
    elif change == "wrong_policy":
        value["policy"]["inspection_policy"] = "wrong"
    else:
        name = "backend/librarium/epub_inspection.py"
        source = fixture / "source" / (name + ".fixture")
        data = source.read_bytes().replace(
            b"librarium.epub-structure.v5", b"librarium.epub-structure.v0"
        )
        source.write_bytes(data)
        value["files"][name]["sha256"] = upgrade.digest(data)
    repin_for_test(manifest, value, monkeypatch)
    target = tmp_path / "old"
    with pytest.raises(ValueError):
        upgrade.export_baseline(candidate, target)
    assert not target.exists()
    assert not (tmp_path / "escaped").exists()
