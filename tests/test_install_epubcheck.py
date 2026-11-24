"""The software installer rejects incomplete or altered validator distributions."""

import hashlib
import importlib.util
import io
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_epubcheck.py"


@pytest.fixture
def installer():
    spec = importlib.util.spec_from_file_location("install_epubcheck", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def distribution(tmp_path, extras=None):
    files = {
        "epubcheck-5.4.0/epubcheck.jar": b"main software",
        "epubcheck-5.4.0/lib/dependency.jar": b"dependency software",
        "epubcheck-5.4.0/LICENSE.txt": b"validator license",
        "epubcheck-5.4.0/THIRD-PARTY.txt": b"dependency notices",
        "epubcheck-5.4.0/licenses/dependency.txt": b"dependency license",
    }
    files.update(extras or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    path = tmp_path / "distribution.zip"
    path.write_bytes(output.getvalue())
    jars = {
        name.removeprefix("epubcheck-5.4.0/"): hashlib.sha256(content).hexdigest()
        for name, content in files.items()
        if name.endswith(".jar") and name.startswith("epubcheck-5.4.0/")
    }
    manifest = {
        "version": "5.4.0",
        "distribution_url": "https://github.com/w3c/epubcheck/releases/download/v5.4.0/epubcheck-5.4.0.zip",
        "distribution_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "jars": jars,
        "jar_manifest_sha256": hashlib.sha256(
            json.dumps(jars, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "java_major": 21,
    }
    return path, manifest


def test_install_preserves_full_distribution_and_is_idempotent(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    target = tmp_path / "installed"
    installer.install(manifest, target, archive)
    assert (target / "epubcheck.jar").read_bytes() == b"main software"
    assert (target / "lib/dependency.jar").read_bytes() == b"dependency software"
    assert (target / "LICENSE.txt").read_bytes() == b"validator license"
    assert (target / "THIRD-PARTY.txt").read_bytes() == b"dependency notices"
    assert (target / "licenses/dependency.txt").read_bytes() == b"dependency license"
    installer.install(manifest, target, archive)
    assert {p.name for p in tmp_path.iterdir()} == {"distribution.zip", "installed"}


def test_bad_archive_hash_is_rejected_before_zip_parsing(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    archive.write_bytes(b"not even a ZIP")
    target = tmp_path / "installed"
    with pytest.raises(ValueError, match="distribution SHA256"):
        installer.install(manifest, target, archive)
    assert not target.exists()


@pytest.mark.parametrize("change", ["missing", "changed", "extra", "uppercase", "symlink"])
def test_existing_installation_must_match_exact_jar_set(installer, tmp_path, change):
    archive, manifest = distribution(tmp_path)
    target = tmp_path / "installed"
    installer.install(manifest, target, archive)
    jar = target / "lib/dependency.jar"
    if change == "missing":
        jar.unlink()
    elif change == "changed":
        jar.write_bytes(b"tampered")
    elif change == "extra":
        (target / "lib/extra.jar").write_bytes(b"unlisted")
    elif change == "uppercase":
        (target / "lib/extra.JAR").write_bytes(b"unlisted")
    else:
        jar.unlink()
        jar.symlink_to(archive)
    with pytest.raises(ValueError):
        installer.install(manifest, target, archive)


@pytest.mark.parametrize(
    "path",
    [
        "../escaped",
        "/absolute",
        "other-root/file",
        "epubcheck-5.4.0/../escaped",
        "epubcheck-5.4.0/a\\b",
    ],
)
def test_unsafe_archive_paths_never_publish_installation(installer, tmp_path, path):
    archive, manifest = distribution(tmp_path, {path: b"unsafe"})
    with pytest.raises(ValueError, match="archive"):
        installer.install(manifest, tmp_path / "installed", archive)
    assert not (tmp_path / "installed").exists()
    assert not (tmp_path / "escaped").exists()


def test_symlink_archive_member_is_rejected(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    with zipfile.ZipFile(archive, "a") as zipped:
        entry = zipfile.ZipInfo("epubcheck-5.4.0/link")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(entry, "../../outside")
    manifest["distribution_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="archive"):
        installer.install(manifest, tmp_path / "installed", archive)
    assert not (tmp_path / "installed").exists()


def test_duplicate_archive_member_is_rejected(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    with zipfile.ZipFile(archive, "a") as zipped, pytest.warns(UserWarning, match="Duplicate"):
        zipped.writestr("epubcheck-5.4.0/LICENSE.txt", b"replacement license")
    manifest["distribution_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="duplicate"):
        installer.install(manifest, tmp_path / "installed", archive)
    assert not (tmp_path / "installed").exists()


def test_unlisted_distribution_jar_is_rejected(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    with zipfile.ZipFile(archive, "a") as zipped:
        zipped.writestr("epubcheck-5.4.0/lib/unlisted.jar", b"unapproved dependency")
    manifest["distribution_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="JAR"):
        installer.install(manifest, tmp_path / "installed", archive)
    assert not (tmp_path / "installed").exists()


def test_expanded_size_limit_precedes_extraction(installer, tmp_path, monkeypatch):
    archive, manifest = distribution(tmp_path)
    monkeypatch.setattr(installer, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(ValueError, match="limits"):
        installer.install(manifest, tmp_path / "installed", archive)
    assert not (tmp_path / "installed").exists()


def test_missing_distribution_jar_cannot_publish_partial_install(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    manifest["jars"]["lib/missing.jar"] = "a" * 64
    manifest["jar_manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest["jars"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="JAR"):
        installer.install(manifest, tmp_path / "installed", archive)
    assert not (tmp_path / "installed").exists()


def test_symlink_destination_does_not_write_through(installer, tmp_path):
    archive, manifest = distribution(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        installer.install(manifest, link / "installed", archive)
    assert list(outside.iterdir()) == []


def test_manifest_hash_cannot_drift_from_jar_map(installer, tmp_path):
    _, manifest = distribution(tmp_path)
    manifest["jars"]["epubcheck.jar"] = "b" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest SHA256"):
        installer.load_manifest(path)


def test_checked_in_manifest_pins_official_complete_distribution(installer):
    manifest = installer.load_manifest(
        SCRIPT.parents[1] / "backend/librarium/epubcheck_distribution.json"
    )
    assert manifest["version"] == "5.4.0"
    assert manifest["java_major"] == 21
    assert len(manifest["jars"]) == 40
    assert "epubcheck.jar" in manifest["jars"]
    assert (
        manifest["distribution_sha256"]
        == "33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c"
    )


def test_cli_installs_offline_and_preserves_existing_tampered_tree(tmp_path):
    archive, manifest = distribution(tmp_path)
    pin = tmp_path / "manifest.json"
    pin.write_text(json.dumps(manifest))
    target = tmp_path / "installed"
    command = [
        sys.executable,
        str(SCRIPT),
        "--manifest",
        str(pin),
        "--prefix",
        str(target),
        "--archive",
        str(archive),
    ]
    installed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    assert installed.returncode == 0, installed.stderr
    jar = target / "epubcheck.jar"
    jar.write_bytes(b"changed by another process")
    rejected = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    assert rejected.returncode != 0
    assert "JAR set or SHA256 mismatch" in rejected.stderr
    assert jar.read_bytes() == b"changed by another process"
