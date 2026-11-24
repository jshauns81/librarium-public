"""Check tracked public text without echoing matching private data.

This is a regression guard, not a complete privacy audit. It does not inspect
Git history, hosted discussions, binary metadata, or identify arbitrary people.
Keep an optional newline-separated private denylist outside the checkout and
pass --denylist when reviewing publication. Never commit that list or its values.
Diagnostics identify files by the SHA-256 of their repository-relative UTF-8
path; line zero denotes a path finding. In-process findings retain exact paths
for private inspection without writing those paths into captured CLI output.
"""

import argparse
import hashlib
import ipaddress
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[1]
PERSONAL_PATH = re.compile(
    r"(?:/(?:home|Users)/|(?i:[A-Za-z]:[\\/]+Users[\\/]+))([^/\\\s\"'`<>]+)"
)
GENERIC_USERS = frozenset({"developer", "runner", "user", "example"})
SYNTHETIC_HOME_COMPONENTS = {
    "backend/tests/test_epub_inspection.py": frozenset({"private", "private.xhtml"}),
}
SYNTHETIC_URL_USERINFO = {
    "backend/tests/test_deployment.py": ("user", "pass", "lib.example.org"),
    "backend/tests/test_library.py": ("user", "secret", "localhost"),
    "tests/test_promotion.py": ("user", None, "release-assets.githubusercontent.com"),
}
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in (
    (10 << 24, 8), ((172 << 24) | (16 << 16), 12), ((192 << 24) | (168 << 16), 16),
))
URL = re.compile(r"https?://[^\s<>`\]\)\"']+", re.IGNORECASE)
PRIVATE_ROOTS = frozenset({".local", "graphify-out"})
PRIVATE_COMPONENTS = frozenset({".private", ".agent-private", ".agent-context"})

# Adding a documentation hostname requires reviewing that it is a public source,
# not an installation address. Reserved examples need no individual entry.
PUBLIC_SOURCE_HOSTS = frozenset({
    "adoptium.net", "antigravity.google", "api.github.com", "claude.ai",
    "code.claude.com", "code.visualstudio.com", "devblogs.microsoft.com",
    "devguide.python.org", "distribution.github.io", "dockhand.pro",
    "docs.astral.sh", "docs.djangoproject.com", "docs.docker.com", "docs.github.com",
    "docs.python.org", "ecc.tools", "github.com", "idpf.org",
    "ismn-international.org", "nodejs.org", "ns.editeur.org", "pypi.org",
    "react.dev", "semver.org", "snapshot.debian.org", "sqlite.org",
    "stream-unzip.docs.trade.gov.uk", "tanstack.com", "vite.dev",
    "www.antigravity.google", "www.djangoproject.com", "www.editeur.org",
    "www.iana.org", "www.isbn-international.org", "www.loc.gov",
    "www.postgresql.org", "www.python.org", "www.qemu.org", "www.sqlite.org", "www.w3.org",
    "librarium-web", "librarium-edge-bridge",
})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    category: str


def file_location(path: str) -> str:
    return "file-sha256:" + hashlib.sha256(path.encode("utf-8")).hexdigest()


def documentation(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in {".md", ".rst"}


def public_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in PUBLIC_SOURCE_HOSTS or host == "localhost":
        return True
    if host in {"example.com", "example.net", "example.org"}:
        return True
    if host.endswith((".example.com", ".example.net", ".example.org", ".test", ".invalid")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or any(address in network for network in (
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
    ))


def scan_text(path: str, text: str, denied: tuple[str, ...] = ()) -> list[Finding]:
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        categories = set()
        permitted = GENERIC_USERS | SYNTHETIC_HOME_COMPONENTS.get(path, frozenset())
        if any(match.group(1) not in permitted for match in PERSONAL_PATH.finditer(line)):
            categories.add("personal-path")
        for match in IPV4.finditer(line):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if any(address in network for network in PRIVATE_NETWORKS):
                categories.add("private-address")
        if any(term.casefold() in line.casefold() for term in denied):
            categories.add("private-term")
        for match in URL.finditer(line):
            try:
                parsed = urlsplit(match.group().rstrip("*.,;:"))
                host = parsed.hostname
                if parsed.username is not None or parsed.password is not None:
                    synthetic = SYNTHETIC_URL_USERINFO.get(path)
                    if synthetic != (parsed.username, parsed.password, host):
                        categories.add("url-userinfo")
                if documentation(path) and (not host or not public_host(host)):
                    categories.add("unreviewed-documentation-host")
            except ValueError:
                if documentation(path):
                    categories.add("unreviewed-documentation-host")
        findings.extend(Finding(path, number, category) for category in sorted(categories))
    return findings


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("Git content enumeration failed")
    return result.stdout


def scan_repository(root: Path, staged: bool, denied: tuple[str, ...]) -> tuple[list[Finding], int]:
    findings = []
    scanned = 0
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        mode, object_id, stage = metadata.split()
        path = path_bytes.decode("utf-8")
        relative = PurePosixPath(path)
        if stage != b"0":
            raise ValueError("Resolve index conflicts before checking public content")
        findings.extend(
            Finding(path, 0, "path-" + finding.category)
            for finding in scan_text("tracked-path.md", path, denied)
        )
        if (
            relative.parts[0] in PRIVATE_ROOTS
            or any(part in PRIVATE_COMPONENTS for part in relative.parts)
            or any(pair == ("docs", "private") for pair in zip(relative.parts, relative.parts[1:]))
            or relative.name.endswith(".private.md")
            or (relative.name != ".env.example"
                and (relative.name == ".env" or relative.name.startswith(".env.")))
        ):
            findings.append(Finding(path, 1, "private-context-path"))
        if mode == b"120000":
            findings.append(Finding(path, 1, "tracked-symlink"))
            continue
        if mode != b"100644" and mode != b"100755":
            findings.append(Finding(path, 1, "unsupported-tracked-entry"))
            continue
        if staged:
            data = git(root, "cat-file", "blob", object_id.decode("ascii"))
        else:
            target = root / path
            if not target.exists() and not target.is_symlink():
                continue
            if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != root):
                findings.append(Finding(path, 1, "tracked-symlink"))
                continue
            data = target.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        findings.extend(scan_text(path, text, denied))
    return findings, scanned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT)
    parser.add_argument("--staged", action="store_true", help="Check index bytes instead of working files")
    parser.add_argument(
        "--denylist", type=Path,
        default=os.environ.get("LIBRARIUM_PRIVATE_TERMS_FILE") or None,
        help="Private terms outside this checkout; defaults to LIBRARIUM_PRIVATE_TERMS_FILE",
    )
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
            raise ValueError("Select a repository root")
        denied = ()
        if args.denylist:
            denylist = args.denylist.resolve()
            if denylist.is_relative_to(root):
                raise ValueError("The private denylist must be outside the checkout")
            denied = tuple(line.strip() for line in denylist.read_text(encoding="utf-8").splitlines()
                           if line.strip() and not line.lstrip().startswith("#"))
            if not denied:
                raise ValueError("The private denylist must contain at least one term")
        findings, count = scan_repository(root, args.staged, denied)
    except (OSError, UnicodeError, ValueError):
        print("Public-content check could not complete; inspect repository or denylist configuration privately.", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{file_location(finding.path)}:{finding.line}: {finding.category}")
    if findings:
        print(f"Public-content check failed: {len(findings)} finding(s) in {count} tracked text files.")
        return 1
    print(f"Public-content check passed: {count} tracked text files; binary files and history require separate review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
