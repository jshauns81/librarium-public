"""Install the complete, hash-pinned official EPUBCheck software distribution."""

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 1024
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "backend/librarium/epubcheck_distribution.json"
)


def jar_manifest_sha256(jars: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(jars, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def safe_relative(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\\" not in value
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def validate_manifest(manifest: dict) -> None:
    if set(manifest) != {
        "version",
        "distribution_url",
        "distribution_sha256",
        "jars",
        "jar_manifest_sha256",
        "java_major",
    }:
        raise ValueError("Unexpected distribution manifest fields")
    if (
        manifest["version"] != "5.4.0"
        or type(manifest["java_major"]) is not int
        or manifest["java_major"] != 21
    ):
        raise ValueError("Unsupported EPUBCheck version or Java major")
    expected_url = "https://github.com/w3c/epubcheck/releases/download/v5.4.0/epubcheck-5.4.0.zip"
    if manifest["distribution_url"] != expected_url:
        raise ValueError("Distribution URL must name the pinned official release")
    for name in ("distribution_sha256", "jar_manifest_sha256"):
        if not isinstance(manifest[name], str) or not re.fullmatch(r"[a-f0-9]{64}", manifest[name]):
            raise ValueError(f"Invalid {name}")
    jars = manifest["jars"]
    if not isinstance(jars, dict) or not jars or "epubcheck.jar" not in jars:
        raise ValueError("Missing EPUBCheck JAR manifest")
    for name, digest in jars.items():
        if not safe_relative(name) or not name.endswith(".jar"):
            raise ValueError("Unsafe JAR manifest path")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid JAR SHA256")
    if jar_manifest_sha256(jars) != manifest["jar_manifest_sha256"]:
        raise ValueError("JAR manifest SHA256 mismatch")


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Distribution manifest must be an object")
    validate_manifest(manifest)
    return manifest


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_installation(prefix: Path, manifest: dict) -> None:
    if prefix.is_symlink() or not prefix.is_dir():
        raise ValueError("EPUBCheck installation must be a real directory")
    jars = {}
    for path in prefix.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("EPUBCheck installation contains a symlink or special file")
        if path.is_file() and path.suffix.lower() == ".jar":
            jars[path.relative_to(prefix).as_posix()] = file_sha256(path)
    if jars != manifest["jars"]:
        raise ValueError("EPUBCheck JAR set or SHA256 mismatch")


def extract_distribution(archive: Path, destination: Path, version: str) -> None:
    root = f"epubcheck-{version}"
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if (
            len(members) > MAX_MEMBERS
            or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES
        ):
            raise ValueError("EPUBCheck archive exceeds software distribution limits")
        seen = set()
        for item in members:
            name = item.filename.removesuffix("/")
            if not safe_relative(name) or name in seen:
                raise ValueError("Unsafe or duplicate EPUBCheck archive path")
            seen.add(name)
            parts = PurePosixPath(name).parts
            mode = stat.S_IFMT(item.external_attr >> 16)
            if parts[0] != root or mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError("Unsafe EPUBCheck archive root or file type")
            if mode == stat.S_IFDIR and not item.is_dir():
                raise ValueError("Inconsistent EPUBCheck archive directory")
            if len(parts) == 1:
                if not item.is_dir():
                    raise ValueError("Invalid EPUBCheck archive root")
                continue
            target = destination.joinpath(*parts[1:])
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with zipped.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                target.chmod(0o644)


def download_distribution(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as source, destination.open("xb") as output:
        total = 0
        while block := source.read(1024 * 1024):
            total += len(block)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("EPUBCheck archive exceeds download limit")
            output.write(block)


def install(manifest: dict, prefix: Path, archive: Path | None = None) -> None:
    validate_manifest(manifest)
    prefix = prefix.absolute()
    if any(path.is_symlink() for path in (prefix, *prefix.parents)):
        raise ValueError("EPUBCheck installation path contains a symlink")
    if prefix.exists():
        verify_installation(prefix, manifest)
        return
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".epubcheck-install-", dir=prefix.parent) as temporary:
        working = Path(temporary)
        if archive is None:
            archive = working / "distribution.zip"
            download_distribution(manifest["distribution_url"], archive)
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("EPUBCheck archive exceeds software distribution limit")
        if file_sha256(archive) != manifest["distribution_sha256"]:
            raise ValueError("EPUBCheck distribution SHA256 mismatch")
        payload = working / "payload"
        payload.mkdir(mode=0o755)
        extract_distribution(archive, payload, manifest["version"])
        verify_installation(payload, manifest)
        payload.rename(prefix)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument(
        "--archive", type=Path, help="Previously downloaded, hash-verified official ZIP"
    )
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    install(manifest, args.prefix, args.archive)
    print(
        f"Verified EPUBCheck {manifest['version']}: {len(manifest['jars'])} pinned JARs at {args.prefix}"
    )


if __name__ == "__main__":
    main()
