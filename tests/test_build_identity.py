import copy
import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import release

ROOT = Path(__file__).resolve().parents[1]


def identity_module():
    from librarium import build_identity

    return build_identity


@pytest.fixture
def source_tree(tmp_path):
    for name in ("backend", "scripts"):
        (tmp_path / name).mkdir()
    shutil.copytree(
        ROOT / "backend/librarium",
        tmp_path / "backend/librarium",
        ignore=shutil.ignore_patterns("__pycache__", "build-identity.json"),
    )
    shutil.copytree(
        ROOT / "backend/bl_catalog",
        tmp_path / "backend/bl_catalog",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(ROOT / "backend/manage.py", tmp_path / "backend/manage.py")
    for name in ("release.py", "build_libarchive.py", "install_epubcheck.py"):
        shutil.copy(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    for name in ("Dockerfile", "requirements.txt"):
        shutil.copy(ROOT / name, tmp_path / name)
    assets = tmp_path / "frontend/dist/assets"
    assets.mkdir(parents=True)
    (assets / "app.js").write_text("console.log('synthetic');\n")
    (tmp_path / "frontend/dist/index.html").write_text("<html></html>\n")
    return tmp_path


def built(source_tree):
    return release.build_identity(source_tree)


def test_build_record_uses_existing_release_compatibility_and_actual_inputs(source_tree):
    record = built(source_tree)
    assert record["schema"] == "librarium.build-identity.v1"
    assert record["source_scope"] == "application-source-and-assets.v1"
    assert record["compatibility"] == release.compatibility(source_tree)
    assert len(record["source_sha256"]) == 64
    assert record == built(source_tree)
    (source_tree / "frontend/dist/assets/app.js").write_text("changed")
    assert built(source_tree)["source_sha256"] != record["source_sha256"]


def test_policy_change_changes_build_binding_and_compatibility(source_tree):
    record = built(source_tree)
    source = source_tree / "backend/librarium/epub_inspection.py"
    source.write_text(
        source.read_text().replace("librarium.epub-structure.v10", "librarium.epub-structure.v11")
    )
    changed = built(source_tree)
    assert changed["source_sha256"] != record["source_sha256"]
    assert changed["compatibility"]["inspection_policy"] == "librarium.epub-structure.v11"


def test_generated_record_caches_and_test_inputs_are_excluded(source_tree):
    record = built(source_tree)
    (source_tree / "backend/librarium/build-identity.json").write_text("ignored")
    (source_tree / "backend/tests").mkdir()
    (source_tree / "backend/tests/private-test.py").write_text("ignored")
    cache = source_tree / "backend/librarium/__pycache__"
    cache.mkdir()
    (cache / "private.pyc").write_text("ignored")
    assert built(source_tree) == record


@pytest.mark.parametrize(
    "name", ["requirements.txt", "frontend/dist", "backend/librarium/epub_inspection.py"]
)
def test_missing_build_input_is_unbuilt_instead_of_synthesizing_identity(source_tree, name):
    path = source_tree / name
    shutil.rmtree(path) if path.is_dir() else path.unlink()
    with pytest.raises(ValueError, match="build identity inputs unavailable"):
        built(source_tree)


def test_build_fingerprint_refuses_symlinked_inputs(source_tree, tmp_path):
    target = source_tree / "frontend/dist/assets/app.js"
    target.unlink()
    target.symlink_to(source_tree / "requirements.txt")
    with pytest.raises(ValueError, match="build identity inputs unavailable"):
        built(source_tree)


def test_packaged_identity_is_strict_and_runtime_does_not_need_git(source_tree, monkeypatch):
    record = built(source_tree)
    target = source_tree / "identity.json"
    target.write_text(json.dumps(record))
    target.chmod(0o644)
    module = identity_module()
    with patch("subprocess.run", side_effect=AssertionError("no Git at runtime")):
        assert module.load_build_identity(target) == record
        assert module.identity_sha256(record) == module.identity_sha256(copy.deepcopy(record))
        assert module.current_compatibility() == release.compatibility()
    monkeypatch.setenv("LIBRARIUM_DECLARED_IMAGE_DIGEST", "sha256:" + "d" * 64)
    report = module.build_status(record, declared_digest="sha256:" + "d" * 64)
    assert report["state"] == "known"
    assert report["declared_image_digest"] == "sha256:" + "d" * 64
    assert report["running_image_digest"] is None
    assert report["running_image_state"] == "unknown"


def test_unknown_or_untrusted_identity_never_claims_running_image(tmp_path):
    module = identity_module()
    assert module.load_build_identity(tmp_path / "missing") is None
    report = module.build_status(None, declared_digest="sha256:" + "d" * 64)
    assert report["state"] == "unknown"
    assert report["source_sha256"] is None
    assert report["compatibility"] is None
    assert report["running_image_digest"] is None
    assert report["running_image_state"] == "unknown"
    assert (
        module.build_status(None, declared_digest="private-canary.invalid")["declared_image_digest"]
        is None
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(schema="unsupported"),
        lambda v: v.update(source_sha256="private-canary.invalid"),
        lambda v: v.update(private="private-canary.invalid"),
        lambda v: v.update(source_scope="private-canary.invalid"),
        lambda v: v["compatibility"].update(inspection_policy="private-canary.invalid"),
        lambda v: v["compatibility"].update(migration_leaves=["private-canary.invalid"]),
        lambda v: v["compatibility"].update(migration_leaves=[]),
        lambda v: v["compatibility"].update(required_configuration=["private-canary.invalid"]),
        lambda v: v["compatibility"].update(private="private-canary.invalid"),
    ],
)
def test_malformed_or_untrusted_identity_is_unknown_without_leaking(source_tree, change):
    record = built(source_tree)
    change(record)
    path = source_tree / "identity.json"
    path.write_text(json.dumps(record))
    module = identity_module()
    assert module.load_build_identity(path) is None
    report = module.build_status(record)
    assert report["state"] == "unknown"
    assert "private-canary.invalid" not in json.dumps(report)


@pytest.mark.parametrize(
    "raw",
    ["{}", '{"schema":1,"schema":2}', '{"schema":NaN}', "[" * 20000, "x" * 20000],
    ids=["empty", "duplicate", "nonfinite", "deep", "oversized"],
)
def test_malformed_oversized_duplicate_and_nonfinite_json_is_unknown(tmp_path, raw):
    path = tmp_path / "identity.json"
    path.write_text(raw)
    assert identity_module().load_build_identity(path) is None


def test_unavailable_nonregular_symlink_and_mutable_files_are_unknown(source_tree):
    module = identity_module()
    target = source_tree / "identity.json"
    target.write_text(json.dumps(built(source_tree)))
    target.chmod(0o644)
    assert module.load_build_identity(target) is not None
    target.chmod(0o666)
    assert module.load_build_identity(target) is None
    target.chmod(0o644)
    link = source_tree / "link.json"
    link.symlink_to(target)
    assert module.load_build_identity(link) is None
    target.unlink()
    os.mkfifo(target)
    assert module.load_build_identity(target) is None


def test_docker_packages_generated_identity_from_actual_application_and_assets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "AS identity-build" in dockerfile
    assert "COPY --from=frontend /ui/dist/ /identity/frontend/dist/" in dockerfile
    assert "build-identity --output" in dockerfile
    assert (
        "COPY --from=identity-build /identity/build-identity.json /app/backend/librarium/build-identity.json"
        in dockerfile
    )


def test_build_status_distinguishes_built_and_current_policy_compatibility(source_tree):
    module = identity_module()
    record = built(source_tree)
    assert module.build_status(record)["runtime_compatibility_state"] == "compatible"
    changed = copy.deepcopy(record["compatibility"])
    changed["inspection_policy"] = "librarium.epub-structure.v11"
    with patch.object(module, "current_compatibility", return_value=changed):
        assert module.build_status(record)["runtime_compatibility_state"] == "incompatible"
    with patch.object(
        module, "current_compatibility", side_effect=OSError("private-canary.invalid")
    ):
        result = module.build_status(record)
        assert result["runtime_compatibility_state"] == "unknown"
        assert "private-canary.invalid" not in json.dumps(result)
    assert module.build_status(None)["runtime_compatibility_state"] == "unknown"


def test_build_identity_cli_packages_readable_record_without_git_or_release_claim(source_tree):
    import subprocess
    import sys

    destination = source_tree / "packaged-identity.json"
    result = subprocess.run(
        [
            sys.executable,
            str(source_tree / "scripts/release.py"),
            "build-identity",
            "--output",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    loaded = identity_module().load_build_identity(destination)
    assert loaded == built(source_tree)
    assert "commit" not in loaded
    assert "acceptance" not in loaded


def test_nonregular_source_input_is_refused_without_blocking(source_tree):
    os.mkfifo(source_tree / "backend/unsupported-pipe")
    with pytest.raises(ValueError, match="build identity inputs unavailable"):
        built(source_tree)
