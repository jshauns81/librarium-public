"""Print which CI areas a change touches, as GitHub step outputs.

With no base commit (push to main, release and manual runs) every area runs.
"""

import subprocess
import sys
from pathlib import PurePosixPath

DOCS = ("docs/", "design-system/", ".claude/", ".codex/")
OUTPUTS = ("python", "frontend", "docs", "candidate_container", "populated_upgrade")
PACKAGING = {
    "Dockerfile", "Dockerfile.writer", ".dockerignore", ".python-version",
    "pyproject.toml", "uv.lock", "requirements.txt",
    "scripts/build_libarchive.py", "scripts/install_epubcheck.py", "scripts/release.py",
    "scripts/run_delivery_writer.py", "scripts/calibre_delivery_runtime.json",
    "scripts/runtime_identity.py", "scripts/runtime_login.sql", "scripts/registry_config.py",
    "backend/librarium/settings.py", "backend/librarium/epubcheck_distribution.json",
    "backend/librarium/source_browser.py", "backend/librarium/cover_source_protocol.py",
    "backend/librarium/cover_source_fetch.py",
}
UPGRADE = {
    "scripts/populated_upgrade.py", "scripts/upgrade_fixture.py", "scripts/capture_source.py",
    "tests/test_populated_upgrade.py", "tests/test_upgrade_fixture.py",
    "backend/librarium/build_identity.py", "backend/librarium/recovery_evidence.py",
    "backend/librarium/delivery_recovery.py",
    "backend/librarium/epub_inspection.py", "backend/librarium/epubcheck_process.py",
    "backend/librarium/management/commands/provision_runtime_role.py",
    ".github/scripts/epub_container_acceptance.py", ".github/workflows/container.yml",
    ".github/scripts/changed_areas.py", ".github/scripts/container_tiers.py",
}


def areas(paths):
    found = dict.fromkeys(OUTPUTS, False)
    for path in paths:
        upgrade = path in UPGRADE or path.startswith("backend/librarium/migrations/")
        helper = path.startswith(".github/scripts/") and any(
            word in PurePosixPath(path).name for word in ("container", "acceptance")
        )
        compose = "/" not in path and path.startswith("compose.") and path.endswith((".yaml", ".yml"))
        found["populated_upgrade"] |= upgrade
        # The rehearsal consumes the exact candidate image, so it also selects its producer.
        found["candidate_container"] |= upgrade or path in PACKAGING or helper or compose or path.startswith("services/source-browser/")
        if path.startswith(".github/"):
            found.update(python=True, frontend=True)
        elif path.startswith("frontend/"):
            found["frontend"] = True
        elif path.endswith(".md") or path.startswith(DOCS):
            found["docs"] = True
        else:
            found["python"] = True
    return found


def classify(base):
    if base:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return areas(diff.stdout.rstrip("\0").split("\0") if diff.stdout else [])
    return dict.fromkeys(OUTPUTS, True)


def main(base):
    for name, value in classify(base).items():
        print(f"{name}={str(value).lower()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
