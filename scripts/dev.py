"""Read-only local workspace checks; no installs, services, or library access."""

import argparse
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]
STATUS_ENTRY_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
DATED_HEADING = re.compile(r"^##\s+.+,\s*\d{4}-\d{2}-\d{2}\s*$", re.MULTILINE)
WORKSPACE_JSON = (
    "Librarium.code-workspace",
    ".vscode/settings.json",
    ".vscode/extensions.json",
    ".vscode/tasks.json",
)


class WorkspaceError(Exception):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise WorkspaceError(result.stderr.strip() or result.stdout.strip() or "Git check failed")
    return result.stdout.strip()


def verify_archive(root: Path) -> int:
    archive = root / "experiments/migration-baseline"
    manifest = archive / "preservation-manifest.json"
    if (root / "experiments").is_symlink() or archive.is_symlink() or manifest.is_symlink():
        raise WorkspaceError("symlink in archive or preservation manifest")
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict) or data.get("schema") != "librarium.preserved-experiment.v1":
        raise WorkspaceError("unsupported preservation manifest schema")
    entries = data.get("files")
    if not isinstance(entries, list) or not entries:
        raise WorkspaceError("preservation manifest must contain files")
    seen = set()
    for entry in entries:
        name = entry.get("preserved_path") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name or "\\" in name:
            raise WorkspaceError("unsafe manifest path")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise WorkspaceError(f"unsafe manifest path: {name}")
        if name in seen:
            raise WorkspaceError(f"duplicate preserved path: {name}")
        seen.add(name)
        path = archive
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise WorkspaceError(f"symlink in preserved path: {name}")
        if not path.is_file():
            raise WorkspaceError(f"missing preserved file: {name}")
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise WorkspaceError(f"invalid digest in preservation manifest: {name}")
        if path.stat().st_size != entry.get("size"):
            raise WorkspaceError(f"size mismatch: {name}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise WorkspaceError(f"digest mismatch: {name}")
    return len(entries)


def verify_status_docs(root: Path) -> int:
    docs = root / "docs"
    status_page = docs / "status.md"
    status_dir = docs / "status"
    if docs.is_symlink() or status_page.is_symlink() or status_dir.is_symlink():
        raise WorkspaceError("symlink in docs/status layout")
    if not status_page.is_file():
        raise WorkspaceError("missing docs/status.md")
    page_text = status_page.read_text(encoding="utf-8")
    if not page_text.startswith("# ") or not page_text.splitlines()[0][2:].strip():
        raise WorkspaceError("docs/status.md must start with a level-one heading")
    if DATED_HEADING.search(page_text):
        raise WorkspaceError("dated section in docs/status.md belongs under docs/status/")
    if not status_dir.is_dir():
        raise WorkspaceError("missing docs/status directory")
    entries = sorted(status_dir.iterdir(), key=lambda item: item.name)
    if not entries:
        raise WorkspaceError("docs/status must contain status entries")
    for entry in entries:
        if entry.is_symlink():
            raise WorkspaceError(f"symlink in docs/status: {entry.name}")
        if not entry.is_file():
            raise WorkspaceError(f"non-regular entry in docs/status: {entry.name}")
        match = STATUS_ENTRY_NAME.fullmatch(entry.name)
        if not match:
            raise WorkspaceError(f"invalid status entry filename: {entry.name}")
        try:
            date.fromisoformat(match.group(1))
        except ValueError as error:
            raise WorkspaceError(f"invalid status entry date: {entry.name}") from error
        lines = entry.read_text(encoding="utf-8").splitlines()
        if not lines or not lines[0].startswith("# ") or not lines[0][2:].strip():
            raise WorkspaceError(f"status entry must start with '# ': {entry.name}")
        if not any(line.strip() for line in lines[1:]):
            raise WorkspaceError(f"status entry has no body: {entry.name}")
    return len(entries)


def doctor(root: Path) -> dict:
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise WorkspaceError("selected directory is not the repository root")
    return {
        "host": socket.gethostname(),
        "workspace": str(root),
        "branch": git(root, "branch", "--show-current") or "detached HEAD",
        "commit": git(root, "rev-parse", "HEAD"),
        "python_tooling": sys.version.split()[0],
        "docker_cli_available": shutil.which("docker") is not None,
        "vscode_cli_available": shutil.which("code") is not None,
        "vscode_server_installed": (Path.home() / ".vscode-server").is_dir(),
        "remote_names": git(root, "remote").splitlines(),
    }


def check(root: Path) -> tuple[int, int]:
    count = verify_archive(root)
    status_count = verify_status_docs(root)
    for name in WORKSPACE_JSON:
        json.loads((root / name).read_text())
    git(root, "diff", "--check")
    git(root, "diff", "--cached", "--check")
    return count, status_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT)
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("doctor", help="Report this checkout and optional local tools")
    report.add_argument("--json", action="store_true")
    commands.add_parser("verify-archive", help="Verify the paused experiment without executing it")
    commands.add_parser("verify-status", help="Verify docs/status.md and per-PR docs/status/ entries")
    commands.add_parser("check", help="Check workspace JSON, preserved files, status docs, and Git whitespace")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "doctor":
            data = doctor(root)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                for key, value in data.items():
                    print(f"{key}: {value}")
        elif args.command == "verify-status":
            status_count = verify_status_docs(root)
            noun = "entry" if status_count == 1 else "entries"
            print(f"Verified {status_count} status {noun}.")
        elif args.command == "check":
            count, status_count = check(root)
            noun = "entry" if status_count == 1 else "entries"
            print(f"Verified {count} preserved file(s) and {status_count} status {noun}.")
            print("Workspace JSON and Git whitespace checks passed.")
        else:
            count = verify_archive(root)
            print(f"Verified {count} preserved file(s).")
        return 0
    except (OSError, ValueError, WorkspaceError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
