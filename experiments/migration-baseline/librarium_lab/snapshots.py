"""Capture committed source without checking out or importing upstream applications."""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

REPOSITORIES = {
    "library-finish": "jshauns81/library-finish",
    "bl-catalog": "jshauns81/bl-catalog",
}
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024


class SnapshotError(ValueError):
    """Source provenance or snapshot integrity could not be established."""


def canonical(data):
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise SnapshotError(f"Cannot read {path.name}") from error


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(canonical(data))
        name = temporary.name
    os.replace(name, path)


def git(checkout, *args):
    try:
        return subprocess.check_output(
            ["git", "-C", str(checkout), *args], stderr=subprocess.PIPE, timeout=120
        ).decode().strip()
    except (subprocess.SubprocessError, OSError) as error:
        raise SnapshotError("Git could not read the requested committed source") from error


def repository_name(origin):
    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if origin.startswith(prefix):
            return origin.removeprefix(prefix).removesuffix(".git").rstrip("/")
    return None


def checked_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in {"..", ".git"} for p in path.parts):
        raise SnapshotError("Unsafe archive path")
    return path


def extract_archive(archive, target):
    records = {}
    total = 0
    with tarfile.open(archive) as tar:
        for member in tar:
            path = checked_path(member.name)
            if member.isdir():
                continue
            if member.name in records:
                raise SnapshotError("Duplicate archive path")
            if member.issym():
                records[member.name] = {"kind": "symlink", "target": member.linkname}
                continue
            if not member.isfile():
                raise SnapshotError("Unsupported archive member")
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise SnapshotError("Source archive exceeds the experiment's size limit")
            destination = target.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            stream = tar.extractfile(member)
            if stream is None:
                raise SnapshotError("Unreadable archive member")
            with stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output)
            records[member.name] = {
                "kind": "file", "bytes": member.size,
                "sha256": digest(destination.read_bytes()), "executable": bool(member.mode & 0o111),
            }
    return dict(sorted(records.items()))


def load_lock(root):
    path = root / "snapshots.lock.json"
    data = read_json(path) if path.exists() else {"schema": 1, "sources": {}}
    if data.get("schema") != 1 or not isinstance(data.get("sources"), dict):
        raise SnapshotError("Invalid snapshot lock")
    return data


def snapshot_path(root, name, commit):
    if name not in REPOSITORIES or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SnapshotError("Invalid snapshot identity")
    return root / ".snapshots" / name / commit


def verify_entry(root, name, entry):
    if entry.get("repository") != REPOSITORIES.get(name):
        raise SnapshotError("Unexpected snapshot repository")
    directory = snapshot_path(root, name, entry["commit"])
    manifest_path = directory / ".librarium-manifest.json"
    if not manifest_path.is_file() or digest(manifest_path.read_bytes()) != entry["manifest_sha256"]:
        raise SnapshotError("Snapshot manifest digest mismatch or source not materialized")
    manifest = read_json(manifest_path)
    if manifest.get("commit") != entry["commit"] or manifest.get("tree") != entry["tree"]:
        raise SnapshotError("Snapshot manifest provenance mismatch")
    for relative, record in manifest["files"].items():
        path = directory.joinpath(*checked_path(relative).parts)
        if record["kind"] == "symlink":
            if path.exists() or path.is_symlink():
                raise SnapshotError("Snapshot symlinks must stay unmaterialized")
            continue
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != record["sha256"]:
            raise SnapshotError("Snapshot file digest mismatch")
    expected = {p for p, r in manifest["files"].items() if r["kind"] == "file"}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != expected | {".librarium-manifest.json"}:
        raise SnapshotError("Snapshot contains unexpected files")
    return manifest


def verify(root, name):
    lock = load_lock(root)
    try:
        entry = lock["sources"][name]
    except KeyError as error:
        raise SnapshotError("Source has not been captured") from error
    verify_entry(root, name, entry)
    return entry


def inventory(directory, manifest, previous):
    python_files = functions = 0
    parse_errors, routes, imports = [], [], set()
    for relative, record in manifest["files"].items():
        if not relative.endswith(".py") or record["kind"] != "file":
            continue
        python_files += 1
        try:
            tree = ast.parse((directory / relative).read_bytes(), filename=relative)
        except (SyntaxError, UnicodeError) as error:
            parse_errors.append({"file": relative, "line": getattr(error, "lineno", None)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
                for decorator in node.decorator_list:
                    if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                            and decorator.func.attr in {"get", "post", "put", "patch", "delete"}
                            and decorator.args and isinstance(decorator.args[0], ast.Constant)
                            and isinstance(decorator.args[0].value, str)):
                        routes.append({"file": relative, "line": node.lineno,
                                       "method": decorator.func.attr.upper(),
                                       "path": decorator.args[0].value})
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
    changes = None
    if previous:
        before, after = previous["files"], manifest["files"]
        changes = {"added": sorted(after.keys() - before.keys()),
                   "removed": sorted(before.keys() - after.keys()),
                   "changed": sorted(p for p in before.keys() & after.keys()
                                     if before[p] != after[p])}
    return {"schema": 1, "repository": manifest["repository"], "commit": manifest["commit"],
            "tree": manifest["tree"], "previous_commit": previous["commit"] if previous else None,
            "changes": changes, "files": len(manifest["files"]), "python_files": python_files,
            "python_functions": functions, "parse_errors": parse_errors,
            "imports": sorted(imports), "decorated_routes": routes,
            "limits": "Static inventory only; literal decorated routes are not a complete API map.",
            "migration_ready": False}


def capture(root, name, checkout, revision):
    root, checkout = Path(root).resolve(), Path(checkout).resolve()
    if not revision or revision.startswith("-") or len(revision) > 200:
        raise SnapshotError("Invalid source revision")
    if name not in REPOSITORIES or repository_name(git(checkout, "remote", "get-url", "origin")) != REPOSITORIES[name]:
        raise SnapshotError("Unexpected source repository")
    commit = git(checkout, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SnapshotError("Invalid source revision")
    tree = git(checkout, "rev-parse", commit + "^{tree}")
    lock = load_lock(root)
    previous_entry = lock["sources"].get(name)
    directory = snapshot_path(root, name, commit)
    if previous_entry and previous_entry["commit"] == commit and directory.exists():
        verify_entry(root, name, previous_entry)
        return previous_entry
    previous = None
    if previous_entry:
        prior = snapshot_path(root, name, previous_entry["commit"])
        if prior.exists():
            previous = verify_entry(root, name, previous_entry)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent, prefix=".capture-") as temporary:
        staging = Path(temporary)
        archive, files = staging / "source.tar", staging / "files"
        files.mkdir()
        try:
            with archive.open("wb") as output:
                subprocess.run(["git", "-C", str(checkout), "archive", "--format=tar", commit],
                               stdout=output, stderr=subprocess.PIPE, check=True, timeout=120)
            records = extract_archive(archive, files)
        except (subprocess.SubprocessError, OSError, tarfile.TarError) as error:
            raise SnapshotError("Could not export committed source") from error
        manifest = {"schema": 1, "repository": REPOSITORIES[name], "commit": commit,
                    "tree": tree, "files": records}
        write_json(files / ".librarium-manifest.json", manifest)
        entry = {"repository": REPOSITORIES[name], "commit": commit, "tree": tree,
                 "manifest_sha256": digest(canonical(manifest)), "files": len(records)}
        if previous_entry and previous_entry["commit"] == commit and entry != previous_entry:
            raise SnapshotError("Restored source differs from the locked archive digest")
        report = inventory(files, manifest, previous)
        if directory.exists():
            verify_entry(root, name, entry)
        else:
            files.rename(directory)
    verify_entry(root, name, entry)
    lock["sources"][name] = entry
    write_json(root / "baselines" / (name + ".json"), report)
    write_json(root / "snapshots.lock.json", lock)
    return entry
