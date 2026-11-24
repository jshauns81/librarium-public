import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts/dev.py"


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "experiments/migration-baseline"
        self.archive.mkdir(parents=True)
        self.source = self.archive / "original.txt"
        self.source.write_bytes(b"saved bytes")
        self.entry = {
            "preserved_path": "original.txt",
            "size": 11,
            "sha256": hashlib.sha256(b"saved bytes").hexdigest(),
        }
        self.manifest = self.archive / "preservation-manifest.json"
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps({
            "schema": "librarium.preserved-experiment.v1",
            "files": [self.entry],
        }))

    def verify(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "verify-archive"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )

    def test_valid_archive_passes_without_modifying_source(self):
        before = self.source.read_bytes()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verified 1 preserved file", result.stdout)
        self.assertEqual(self.source.read_bytes(), before)

    def test_same_size_tampering_fails_with_digest_error(self):
        self.source.write_bytes(b"other bytes")
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("digest mismatch", result.stderr)

    def test_manifest_cannot_escape_archive(self):
        self.entry["preserved_path"] = "../outside.txt"
        self.write_manifest()
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsafe manifest path", result.stderr)

    def test_symlinked_source_is_refused(self):
        outside = self.root / "outside.txt"
        outside.write_bytes(b"saved bytes")
        self.source.unlink()
        self.source.symlink_to(outside)
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink", result.stderr)

    def test_missing_source_reports_the_file(self):
        self.source.unlink()
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing preserved file: original.txt", result.stderr)

    def test_doctor_uses_project_directory_from_any_cwd(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "doctor", "--json"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(Path(report["workspace"]), PROJECT)
        self.assertEqual(len(report["commit"]), 40)


class StatusDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = self.root / "docs"
        self.status_dir = self.docs / "status"
        self.status_dir.mkdir(parents=True)
        self.status_page = self.docs / "status.md"
        self.status_page.write_text(
            "# Current status\n\nEntries live in `docs/status/`.\n\n## Product implementation\n\nStable.\n",
            encoding="utf-8",
        )
        self.entry = self.status_dir / "2026-11-06-example-entry.md"
        self.entry.write_text("# Example entry, 2026-11-06\n\nVerified.\n", encoding="utf-8")

    def verify(self, root=None):
        target = self.root if root is None else root
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(target), "verify-status"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )

    def test_valid_status_layout_passes(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verified 1 status entry", result.stdout)

    def test_missing_status_page_fails(self):
        self.status_page.unlink()
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/status.md", result.stderr)

    def test_dated_section_in_status_page_fails(self):
        self.status_page.write_text(
            "# Current status\n\n## New work, 2026-11-07\n\nWrong place.\n",
            encoding="utf-8",
        )
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("dated section", result.stderr)

    def test_invalid_entry_filename_or_date_fails(self):
        for bad_name in ("notes.md", "2026-11-06-Upper.md", "2026-02-30-impossible.md"):
            with self.subTest(name=bad_name):
                bad = self.status_dir / bad_name
                bad.write_text("# Heading\n\nBody.\n", encoding="utf-8")
                try:
                    result = self.verify()
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(bad_name, result.stderr)
                finally:
                    bad.unlink()

    def test_entry_requires_level_one_heading_and_body(self):
        for bad_text in ("## Demoted wrong\n\nBody.\n", "Plain paragraph.\n", "# Only heading\n"):
            with self.subTest(text=bad_text):
                self.entry.write_text(bad_text, encoding="utf-8")
                result = self.verify()
                self.assertEqual(result.returncode, 1)

    def test_symlinked_status_entry_is_refused(self):
        outside = self.root / "outside.md"
        outside.write_text("# Outside\n\nBody.\n", encoding="utf-8")
        link = self.status_dir / "2026-11-05-linked.md"
        link.symlink_to(outside)
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink", result.stderr)

    def test_repository_status_layout_passes(self):
        result = self.verify(PROJECT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
