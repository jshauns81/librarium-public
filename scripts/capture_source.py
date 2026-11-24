"""Capture selected committed source without checkout, imports, or extraction."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".md", ".toml", ".sql"}


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Unsafe source selection")
    return value


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def capture(repo: Path, ref: str, includes: list[str], destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(destination)
    if not includes or ref.startswith("-"):
        raise ValueError("Select source paths and a ref explicitly")
    includes = sorted(safe_path(path) for path in includes)
    commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    archive_bytes = io.BytesIO()
    files = {}
    excluded = []
    selected = set()
    with tarfile.open(fileobj=archive_bytes, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
            if not entry:
                continue
            meta, raw_path = entry.split(b"\t", 1)
            path = safe_path(raw_path.decode())
            matches = [p for p in includes if path == p or path.startswith(p + "/")]
            if not matches:
                continue
            selected.update(matches)
            mode, kind, blob = meta.decode().split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError(f"Refusing link or unsupported mode: {path}")
            parts = PurePosixPath(path).parts
            if PurePosixPath(path).suffix not in SUFFIXES or any(
                part.startswith(".")
                or any(
                    word in part.lower()
                    for word in ("credential", "secret", "local_settings", "private")
                )
                for part in parts
            ):
                excluded.append(path)
                continue
            data = git(repo, "cat-file", "blob", blob)
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
            files[path] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "git_blob": blob,
                "git_mode": mode,
            }
    if selected != set(includes) or not files:
        raise ValueError("Source selection contains missing or empty paths")
    data = archive_bytes.getvalue()
    remotes = git(repo, "remote").decode().splitlines()
    repository = (
        git(repo, "remote", "get-url", "origin").decode().strip()
        if "origin" in remotes
        else str(repo.resolve())
    )
    if "://" in repository and "@" in repository.split("://", 1)[1].split("/", 1)[0]:
        raise ValueError("Refusing credential-bearing repository locator")
    manifest = {
        "schema": "librarium.source-capture.v1",
        "repository": repository,
        "ref": ref,
        "commit": commit,
        "includes": includes,
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "files": files,
        "excluded": excluded,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / "capture"
        stage.mkdir()
        (stage / "source.tar").write_bytes(data)
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        verify(stage)
        # A second existence check avoids replacing a capture created during construction.
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(stage, destination)
    return manifest


def verify(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    data = (directory / "source.tar").read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Archive integrity mismatch")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        seen = set()
        for item in archive:
            path = safe_path(item.name)
            if not item.isfile() or path in seen or path not in manifest["files"]:
                raise ValueError("Archive member integrity mismatch")
            seen.add(path)
            stream = archive.extractfile(item)
            if stream is None:
                raise ValueError("Archive member integrity mismatch")
            body = stream.read()
            expected = manifest["files"][path]
            if (
                len(body) != expected["size"]
                or hashlib.sha256(body).hexdigest() != expected["sha256"]
            ):
                raise ValueError("File integrity mismatch")
        if seen != set(manifest["files"]):
            raise ValueError("Archive file inventory integrity mismatch")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("ref")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--include", action="append", required=True)
    args = parser.parse_args()
    result = capture(args.repository, args.ref, args.include, args.destination)
    print(f"Captured {result['commit']}: {len(result['files'])} files; {result['archive_sha256']}")


if __name__ == "__main__":
    main()
