import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release.py"
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
BROWSER_DIGEST = "sha256:" + "c" * 64
IMAGE_ID = "sha256:" + "d" * 64
BROWSER_ID = "sha256:" + "e" * 64


def run(*args):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            *args,
            *(
                [
                    "--browser-digest",
                    BROWSER_DIGEST,
                    "--image-id",
                    IMAGE_ID,
                    "--browser-image-id",
                    BROWSER_ID,
                ]
                if args[0] == "manifest"
                else []
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("version", ["v0.1.0-beta.1", "v12.3.40-beta.21"])
def test_valid_beta_identity(version):
    result = run("validate", "--version", version, "--commit", SHA)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "version",
    [
        "0.1.0-beta.1",
        "v0.1.0",
        "v0.1.0-beta.0",
        "v01.1.0-beta.1",
        "v0.1.0-beta.01",
        "v0.1.0-beta.1\n",
        "v0.1.0-beta.1;echo bad",
    ],
)
def test_invalid_beta_version_refused(version):
    result = run("validate", "--version", version, "--commit", SHA)
    assert result.returncode != 0
    assert "invalid beta version" in result.stderr


@pytest.mark.parametrize("commit", ["main", "a" * 39, "-" + "a" * 39, "A" * 40])
def test_requires_full_commit(commit):
    result = run("validate", "--version", "v0.1.0-beta.1", "--commit=" + commit)
    assert result.returncode != 0
    assert "full lowercase commit" in result.stderr


def test_manifest_records_derived_compatibility_and_actual_image(tmp_path):
    target = tmp_path / "manifest.json"
    result = run(
        "manifest",
        "--version",
        "v0.1.0-beta.1",
        "--commit",
        SHA,
        "--digest",
        DIGEST,
        "--run-url",
        "https://github.com/jshauns81/librarium/actions/runs/1",
        "--output",
        str(target),
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(target.read_text())
    assert manifest["commit"] == SHA
    assert manifest["image"] == "ghcr.io/jshauns81/librarium@" + DIGEST
    assert manifest["platform"] == "linux/amd64"
    assert manifest["compatibility"]["migration_leaves"] == ["0017_cover_source_timings"]
    assert manifest["compatibility"]["inspection_policy"] == "librarium.epub-structure.v11"
    assert manifest["compatibility"]["validation_policy"] == "librarium.epub-validation.v2"
    assert set(manifest["compatibility"]) == {
        "migration_leaves",
        "inspection_policy",
        "validation_policy",
        "required_configuration",
    }
    assert manifest["acceptance"]["result"] == "passed"
    assert manifest["activation"] == "separate approved operation required"


@pytest.mark.parametrize("digest", ["beta", "sha256:" + "b" * 63, "sha256:" + "B" * 64])
def test_manifest_refuses_mutable_or_invalid_digest(tmp_path, digest):
    result = run(
        "manifest",
        "--version",
        "v0.1.0-beta.1",
        "--commit",
        SHA,
        "--digest",
        digest,
        "--run-url",
        "https://github.com/jshauns81/librarium/actions/runs/1",
        "--output",
        str(tmp_path / "manifest.json"),
    )
    assert result.returncode != 0
    assert not (tmp_path / "manifest.json").exists()


def test_manifest_refuses_legacy_python_before_parsing_project_source(tmp_path):
    legacy_python = Path("/usr/bin/python3")
    if not legacy_python.exists():
        pytest.skip("No system Python available for the legacy-runtime proof")
    version = subprocess.run(
        [str(legacy_python), "-c", "import sys;print(sys.version_info.minor)"],
        text=True,
        capture_output=True,
        check=True,
    )
    if int(version.stdout) >= 14:
        pytest.skip("System Python already supports the project grammar")
    target = tmp_path / "manifest.json"
    result = subprocess.run(
        [
            str(legacy_python),
            str(SCRIPT),
            "manifest",
            "--version",
            "v0.1.0-beta.2",
            "--commit",
            SHA,
            "--digest",
            DIGEST,
            "--browser-digest",
            BROWSER_DIGEST,
            "--image-id",
            IMAGE_ID,
            "--browser-image-id",
            BROWSER_ID,
            "--run-url",
            "https://github.com/jshauns81/librarium/actions/runs/1",
            "--output",
            str(target),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "manifest requires Python 3.14 or newer" in result.stderr
    assert "SyntaxError" not in result.stderr
    assert not target.exists()


def test_manifest_binds_both_images_and_install_assets():
    import hashlib
    import io
    import zipfile

    from scripts import release

    data = release.manifest(
        "v0.1.0-beta.1",
        SHA,
        DIGEST,
        "https://github.com/jshauns81/librarium/actions/runs/1",
        browser_digest=BROWSER_DIGEST,
        image_id=IMAGE_ID,
        browser_image_id=BROWSER_ID,
    )
    assert data["schema"] == "librarium.release.v2"
    assert data["images"] == {
        "application": {
            "image": release.IMAGE + "@" + DIGEST,
            "config_digest": IMAGE_ID,
            "commit": SHA,
            "platform": "linux/amd64",
        },
        "source-browser": {
            "image": release.IMAGE + "-source-browser@" + BROWSER_DIGEST,
            "config_digest": BROWSER_ID,
            "commit": SHA,
            "platform": "linux/amd64",
        },
    }
    raw = release.stack_archive()
    assert raw == release.stack_archive()
    assert data["stack_assets"]["sha256"] == hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "compose.source-browser.yaml" in archive.namelist()
        assert "services/source-browser/seccomp.json" in archive.namelist()
        for name in archive.namelist():
            assert archive.read(name) == (ROOT / name).read_bytes()
            assert (
                data["stack_assets"]["files"][name]
                == hashlib.sha256(archive.read(name)).hexdigest()
            )
            assert archive.getinfo(name).date_time == (1980, 1, 1, 0, 0, 0)


@pytest.mark.parametrize("field", ["browser_digest", "image_id", "browser_image_id"])
@pytest.mark.parametrize("value", ["", "latest", "sha256:" + "F" * 64])
def test_manifest_refuses_incomplete_image_pair(field, value):
    from scripts import release

    fields = {
        "browser_digest": BROWSER_DIGEST,
        "image_id": IMAGE_ID,
        "browser_image_id": BROWSER_ID,
    }
    fields[field] = value
    with pytest.raises(ValueError):
        release.manifest(
            "v0.1.0-beta.1",
            SHA,
            DIGEST,
            "https://github.com/jshauns81/librarium/actions/runs/1",
            **fields,
        )


def test_stack_assets_carry_every_relative_compose_source():
    import yaml

    from scripts import release

    archived = set(release.STACK_FILES)
    needed = set()

    def local(path):
        # Absolute and ${VARIABLE} paths come from the operator, not the archive.
        if isinstance(path, str) and path and not path.startswith(("/", "$", "~")):
            needed.add(path.removeprefix("./"))

    for name in archived:
        if not name.endswith(".yaml"):
            continue
        data = yaml.safe_load((ROOT / name).read_text()) or {}
        for entry in data.get("include", []):
            paths = entry.get("path", []) if isinstance(entry, dict) else entry
            for path in [paths] if isinstance(paths, str) else paths:
                local(path)
        for kind in ("configs", "secrets"):
            for item in (data.get(kind) or {}).values():
                local((item or {}).get("file"))
        for service in (data.get("services") or {}).values():
            assert "build" not in service, name
            local((service.get("extends") or {}).get("file"))
            env_files = service.get("env_file", [])
            for entry in [env_files] if isinstance(env_files, str) else env_files:
                local(entry.get("path") if isinstance(entry, dict) else entry)
            for volume in service.get("volumes", []):
                if isinstance(volume, dict):
                    if volume.get("type", "bind") == "bind":
                        local(volume.get("source"))
                elif volume.split(":", 1)[0].startswith((".", "/", "$", "~")):
                    local(volume.split(":", 1)[0])
            for option in service.get("security_opt", []):
                if option.startswith("seccomp:") and option != "seccomp:unconfined":
                    local(option.removeprefix("seccomp:"))
    assert needed - archived == set()


def test_stack_assets_refuse_symlinks_and_missing_files(tmp_path):
    import shutil

    from scripts import release

    for name in release.STACK_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    target = tmp_path / "services/source-browser/seccomp.json"
    target.unlink()
    with pytest.raises(ValueError):
        release.stack_archive(tmp_path)
    target.symlink_to(ROOT / "services/source-browser/seccomp.json")
    with pytest.raises(ValueError):
        release.stack_archive(tmp_path)


def test_accepted_bundle_receipt_binds_source_and_both_configs(tmp_path):
    from scripts import release

    record = release.accepted_images(SHA, IMAGE_ID, BROWSER_ID)
    assert release.verify_images(record, SHA, IMAGE_ID) == BROWSER_ID
    for key, value in [
        ("commit", "f" * 40),
        ("application", BROWSER_ID),
        ("source-browser", "latest"),
    ]:
        changed = dict(record, **{key: value})
        with pytest.raises(ValueError):
            release.verify_images(changed, SHA, IMAGE_ID)
    with pytest.raises(ValueError):
        release.verify_images({"commit": SHA, "application": IMAGE_ID}, SHA, IMAGE_ID)


def test_uploaded_assets_must_match_the_local_release_payload():
    import hashlib

    from scripts import release

    payloads = {
        "release-manifest.json": b'{"schema":"fixture"}',
        "stack-assets.zip": b"fixture zip",
    }
    assets = [
        {
            "name": name,
            "size": len(raw),
            "state": "uploaded",
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
        for name, raw in payloads.items()
    ]
    release.verify_assets({"assets": assets}, payloads)
    for changed in [
        assets[:1],
        assets + assets[:1],
        [dict(assets[0], digest="sha256:" + "0" * 64), assets[1]],
        [dict(assets[0], state="new"), assets[1]],
    ]:
        with pytest.raises(ValueError):
            release.verify_assets({"assets": changed}, payloads)


def test_host_python_can_verify_the_export_receipt_and_generate_stack_assets(tmp_path):
    receipt = tmp_path / "accepted.json"
    target = tmp_path / "stack.zip"
    python = "/usr/bin/python3"

    def cli(*args):
        return subprocess.run(
            [python, str(SCRIPT), *args], capture_output=True, text=True, check=False
        )

    created = cli(
        "accepted-images",
        "--commit=" + SHA,
        "--image-id=" + IMAGE_ID,
        "--browser-image-id=" + BROWSER_ID,
        "--output=" + str(receipt),
    )
    assert created.returncode == 0, created.stderr
    verified = cli(
        "verify-images", "--commit=" + SHA, "--image-id=" + IMAGE_ID, "--receipt=" + str(receipt)
    )
    assert verified.returncode == 0 and verified.stdout.strip() == BROWSER_ID
    refused = cli(
        "verify-images",
        "--commit=" + "f" * 40,
        "--image-id=" + IMAGE_ID,
        "--receipt=" + str(receipt),
    )
    assert refused.returncode != 0 and not refused.stdout
    generated = cli("stack-assets", "--output=" + str(target))
    assert generated.returncode == 0, generated.stderr
    from scripts import release

    assert target.read_bytes() == release.stack_archive()


@pytest.mark.parametrize("role", ["application", "source-browser"])
def test_digest_cli_checks_each_accepted_config_before_printing(monkeypatch, capsys, role):
    from unittest.mock import patch

    from scripts import registry

    monkeypatch.setattr("sys.argv", ["registry.py", "digest", "v0.1.0-beta.1", "--role=" + role])
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_ACTOR", "owner")
    monkeypatch.setenv("EXPECTED_IMAGE_ID", BROWSER_ID)
    with patch(
        "scripts.registry.lookup", return_value=(BROWSER_DIGEST, {"config": {"digest": BROWSER_ID}})
    ) as lookup:
        registry.main()
    assert lookup.call_args.kwargs == {"role": role}
    assert capsys.readouterr().out.strip() == BROWSER_DIGEST
    with (
        patch(
            "scripts.registry.lookup",
            return_value=(BROWSER_DIGEST, {"config": {"digest": IMAGE_ID}}),
        ),
        pytest.raises(SystemExit),
    ):
        registry.main()
    assert not capsys.readouterr().out


def test_stack_archive_refuses_before_exceeding_promotion_download_budget(monkeypatch):
    from scripts import release

    monkeypatch.setattr(
        release, "stack_files", lambda root: {"compose.registry.yaml": b"x" * 65536}
    )
    with pytest.raises(ValueError, match="stack archive exceeds"):
        release.stack_archive()
