"""Validate immutable beta identity and generate source-derived release metadata."""

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "jshauns81/librarium-public"
IMAGE = "ghcr.io/" + REPOSITORY
IMAGES = {"application": IMAGE, "source-browser": IMAGE + "-source-browser"}
STACK_FILES: tuple[str, ...] = (
    "compose.registry.yaml",
    "compose.registry-workspace.yaml",
    "compose.files.yaml",
    "compose.library.yaml",
    "compose.assessments.yaml",
    "compose.content-trust.yaml",
    "compose.cover-sources.yaml",
    "compose.source-browser.yaml",
    "compose.runtime.yaml",
    "compose.registry-library.yaml",
    "compose.catalogue-sync.yaml",
    "scripts/runtime_login.sql",
    "scripts/runtime_identity.py",
    "services/source-browser/seccomp.json",
    "services/source-browser/provenance.json",
    "services/source-browser/LICENSE.moby",
)
NUMBER = r"(?:0|[1-9][0-9]*)"
BETA = rf"v{NUMBER}\.{NUMBER}\.{NUMBER}-beta\.[1-9][0-9]*"


def validate(version: str, commit: str) -> None:
    if not re.fullmatch(BETA, version):
        raise ValueError("invalid beta version")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("expected full lowercase commit SHA")


def _build_module():
    # Build tooling and runtime share one compatibility extraction implementation.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "librarium_build_identity", ROOT / "backend/librarium/build_identity.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compatibility(root: Path = ROOT) -> dict:
    if sys.version_info < (3, 14):
        raise ValueError("manifest requires Python 3.14 or newer")
    return _build_module().compatibility(root)


def build_identity(root: Path = ROOT) -> dict:
    module = _build_module()
    hasher = hashlib.sha256()
    fixed = [
        "Dockerfile",
        "requirements.txt",
        "scripts/release.py",
        "scripts/build_libarchive.py",
        "scripts/install_epubcheck.py",
    ]
    try:
        paths = [root / name for name in fixed]
        for directory in ("backend", "frontend/dist"):
            base = root / directory
            if not base.is_dir() or base.is_symlink():
                raise ValueError
            for path in base.rglob("*"):
                parts = path.relative_to(base).parts
                if any(part in {"__pycache__", "tests"} for part in parts):
                    continue
                if path.name == "build-identity.json":
                    continue
                if path.is_symlink():
                    raise ValueError
                if path.is_file():
                    paths.append(path)
                    if len(paths) > 10_000:
                        raise ValueError
                elif not path.is_dir():
                    raise ValueError
        if len(paths) > 10_000 or not any(p.is_relative_to(root / "frontend/dist") for p in paths):
            raise ValueError
        for path in sorted(paths):
            if (
                path.is_symlink()
                or not path.is_file()
                or any(parent.is_symlink() for parent in path.parents if parent != root)
            ):
                raise ValueError
            with path.open("rb") as stream:
                data = stream.read(100 * 1024 * 1024 + 1)
            if len(data) > 100 * 1024 * 1024:
                raise ValueError
            name = path.relative_to(root).as_posix().encode()
            hasher.update(len(name).to_bytes(4, "big") + name)
            hasher.update(len(data).to_bytes(8, "big") + data)
        record = {
            "schema": module.SCHEMA,
            "source_scope": module.SOURCE_SCOPE,
            "source_sha256": hasher.hexdigest(),
            "compatibility": compatibility(root),
        }
        if not module.valid_identity(record):
            raise ValueError
        return record
    except (OSError, ValueError, StopIteration, SyntaxError):
        raise ValueError("build identity inputs unavailable") from None


def accepted_images(commit: str, image_id: str, browser_image_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in (image_id, browser_image_id)
    ):
        raise ValueError("invalid accepted image identity")
    return {"commit": commit, "application": image_id, "source-browser": browser_image_id}


def verify_images(record: dict, commit: str, image_id: str) -> str:
    try:
        expected = accepted_images(commit, image_id, record["source-browser"])
        if record != expected:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("accepted image bundle differs from source or config identity") from None
    return expected["source-browser"]


def verify_assets(record: dict, payloads: dict[str, bytes]) -> None:
    try:
        assets = record["assets"]
        if len(assets) != len(payloads):
            raise ValueError
        for name, raw in payloads.items():
            found = [item for item in assets if item["name"] == name]
            if len(found) != 1 or any(
                (
                    found[0]["state"] != "uploaded",
                    found[0]["size"] != len(raw),
                    found[0]["digest"] != "sha256:" + hashlib.sha256(raw).hexdigest(),
                )
            ):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("uploaded release assets differ from reviewed payload") from None


def stack_files(root: Path = ROOT) -> dict[str, bytes]:
    result = {}
    try:
        for name in STACK_FILES:
            path = root / name
            if (
                not path.is_file()
                or path.is_symlink()
                or any(p.is_symlink() for p in path.parents if p != root)
            ):
                raise ValueError
            with path.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if not path.is_file() or len(raw) > 1024 * 1024:
                raise ValueError
            result[name] = raw
    except (OSError, ValueError):
        raise ValueError("release stack inputs unavailable") from None
    return result


def stack_archive(root: Path = ROOT) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in stack_files(root).items():
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, raw)
    raw_archive = output.getvalue()
    if len(raw_archive) > 65536:
        raise ValueError("stack archive exceeds promotion download budget")
    return raw_archive


def stack_metadata(root: Path = ROOT) -> dict:
    return {
        "archive": "stack-assets.zip",
        "sha256": hashlib.sha256(stack_archive(root)).hexdigest(),
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in stack_files(root).items()},
    }


def manifest(
    version: str,
    commit: str,
    digest: str,
    run_url: str,
    *,
    browser_digest: str = "",
    image_id: str = "",
    browser_image_id: str = "",
    root: Path = ROOT,
) -> dict:
    validate(version, commit)
    if not all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value)
        for value in (digest, browser_digest, image_id, browser_image_id)
    ):
        raise ValueError("expected immutable sha256 image digest")
    if not re.fullmatch(
        re.escape("https://github.com/" + REPOSITORY) + r"/actions/runs/[1-9][0-9]*", run_url
    ):
        raise ValueError("invalid acceptance run URL")
    return {
        "schema": "librarium.release.v2",
        "version": version,
        "channel": "beta",
        "repository": "https://github.com/" + REPOSITORY,
        "commit": commit,
        "image": IMAGE + "@" + digest,
        "images": {
            role: {
                "image": IMAGES[role] + "@" + registry_digest,
                "config_digest": config_digest,
                "commit": commit,
                "platform": "linux/amd64",
            }
            for role, registry_digest, config_digest in (
                ("application", digest, image_id),
                ("source-browser", browser_digest, browser_image_id),
            )
        },
        "stack_assets": stack_metadata(root),
        "platform": "linux/amd64",
        "acceptance": {
            "run": run_url,
            "result": "passed",
            "checks": [
                "source-quality",
                "container",
                "epub",
                "replacement",
                "restore",
                "populated-upgrade",
                "source-browser",
            ],
        },
        "compatibility": compatibility(root),
        "previous_supported_release": None,
        "activation": "separate approved operation required",
        "upgrade_recovery": "docs/releases.md#environment-isolation-and-activation",
        "known_limits": [
            "No library write is reachable; the retained writer core is disabled and uncalled",
            "File role requires target kernel acceptance",
            "Stable promotion requires beta observation and user acceptance",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "validate",
            "manifest",
            "build-identity",
            "stack-assets",
            "accepted-images",
            "verify-images",
            "verify-assets",
        ],
    )
    parser.add_argument("--version")
    parser.add_argument("--commit")
    parser.add_argument("--digest")
    parser.add_argument("--browser-digest")
    parser.add_argument("--image-id")
    parser.add_argument("--browser-image-id")
    parser.add_argument("--run-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--manifest-file", type=Path)
    parser.add_argument("--stack-file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "verify-assets":
            verify_assets(
                json.loads(args.receipt.read_bytes()),
                {
                    "release-manifest.json": args.manifest_file.read_bytes(),
                    "stack-assets.zip": args.stack_file.read_bytes(),
                },
            )
            return
        if args.command == "verify-images":
            print(
                verify_images(
                    json.loads(args.receipt.read_bytes()), args.commit or "", args.image_id or ""
                )
            )
            return
        if args.command == "accepted-images":
            data = accepted_images(
                args.commit or "", args.image_id or "", args.browser_image_id or ""
            )
            if not args.output:
                raise ValueError("accepted bundle output is required")
            with args.output.open("x") as target:
                target.write(json.dumps(data, indent=2) + "\n")
            return
        if args.command == "stack-assets":
            if not args.output:
                raise ValueError("stack output is required")
            with args.output.open("xb") as target:
                target.write(stack_archive())
            return
        if args.command == "build-identity":
            if not args.output:
                raise ValueError("build identity output is required")
            data = build_identity()
            with args.output.open("x") as target:
                target.write(json.dumps(data, indent=2) + "\n")
            args.output.chmod(0o444)
            return
        validate(args.version or "", args.commit or "")
        if args.command == "manifest":
            if not args.output:
                raise ValueError("manifest output is required")
            data = manifest(
                args.version,
                args.commit,
                args.digest or "",
                args.run_url or "",
                browser_digest=args.browser_digest or "",
                image_id=args.image_id or "",
                browser_image_id=args.browser_image_id or "",
            )
            with args.output.open("x") as target:
                target.write(json.dumps(data, indent=2) + "\n")
    except (ValueError, OSError, AttributeError, TypeError) as exc:
        parser.error(str(exc) if isinstance(exc, ValueError) else "release inputs unavailable")


if __name__ == "__main__":
    main()
