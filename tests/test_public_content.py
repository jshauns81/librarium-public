"""Behavior checks for the public-content boundary; all findings are synthetic."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_public_content import scan_text

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_public_content.py"


class PublicContentTests(unittest.TestCase):
    def test_private_paths_and_addresses_are_findings(self):
        cases = [
            ("/home/" + "fictional-owner/work", "personal-path"),
            ("/Users/" + "fictional-owner/work", "personal-path"),
            ("C:\\Users\\" + "fictional-owner\\work", "personal-path"),
            ("c:\\users\\" + "fictional-owner\\work", "personal-path"),
            ("10." + "42.13.7", "private-address"),
            ("172." + "20.5.2", "private-address"),
            ("192." + "168.5.2", "private-address"),
        ]
        for text, category in cases:
            with self.subTest(category=category, text=text):
                self.assertEqual([f.category for f in scan_text("notes.md", text)], [category])

    def test_safe_examples_loopback_and_public_sources_pass(self):
        text = (
            "/home/developer/project /home/runner/work /Users/developer/project\n"
            "http://127.0.0.1:8123/ https://docs.python.org/ https://api.github.com/\n"
            "https://library.example.org/ https://example.com/ https://thing.invalid/\n"
            "192.0.2.1 198.51.100.2 203.0.113.3 172.32.0.1\n"
        )
        self.assertEqual(scan_text("docs/setup.md", text), [])

    def test_unknown_documentation_endpoint_is_rejected_without_private_literal(self):
        text = "A service: https://control." + "fictional-deployment.net/"
        findings = scan_text("docs/setup.md", text)
        self.assertEqual([f.category for f in findings], ["unreviewed-documentation-host"])
        self.assertNotIn("fictional", str(findings))

    def test_private_terms_apply_to_source_and_dotfiles_case_insensitively(self):
        findings = scan_text(".config", "value = PRIVATE-TERM", ("private-term",))
        self.assertEqual([f.category for f in findings], ["private-term"])
        self.assertNotIn("PRIVATE-TERM", str(findings))

    def test_synthetic_attack_fixture_exception_is_scoped_to_existing_test(self):
        text = "/home/" + "private.xhtml"
        self.assertEqual(scan_text("backend/tests/test_epub_inspection.py", text), [])
        self.assertEqual([f.category for f in scan_text("notes.md", text)], ["personal-path"])

    def test_allowlisted_public_host_does_not_hide_userinfo(self):
        findings = scan_text("config.py", "https://" + "account:password@github.com/project")
        self.assertEqual([f.category for f in findings], ["url-userinfo"])

    def test_existing_userinfo_fixture_exception_requires_exact_synthetic_values(self):
        path = "backend/tests/test_library.py"
        text = "http://" + "user:secret@localhost"
        self.assertEqual(scan_text(path, text), [])
        changed = text.replace("secret", "different")
        self.assertEqual([f.category for f in scan_text(path, changed)], ["url-userinfo"])
        self.assertEqual([f.category for f in scan_text("config.py", text)], ["url-userinfo"])

    def test_cli_scans_index_separately_from_worktree_and_ignores_untracked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            source = root / "README.md"
            source.write_text("Safe text\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            source.write_text("/home/" + "fictional-owner/work\n", encoding="utf-8")
            (root / "untracked.md").write_text("/home/" + "someone/work", encoding="utf-8")
            result = self.run_cli(root)
            self.assertEqual(result.returncode, 1)
            self.assertRegex(result.stdout, r"file-sha256:[0-9a-f]{64}:1: personal-path")
            self.assertNotIn("fictional-owner", result.stdout + result.stderr)
            self.assertNotIn("untracked.md", result.stdout)
            staged = self.run_cli(root, "--staged")
            self.assertEqual(staged.returncode, 0, staged.stdout + staged.stderr)

    def test_cli_rejects_private_directory_and_symlink_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".private").mkdir()
            (root / ".private/note.md").write_text("Private", encoding="utf-8")
            (root / "external").symlink_to("/missing-external-file")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            result = self.run_cli(root)
            self.assertEqual(result.returncode, 1)
            self.assertIn("private-context-path", result.stdout)
            self.assertIn("tracked-symlink", result.stdout)

    def test_cli_denylist_must_be_external_and_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Safe", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            inside = self.run_cli(root, "--denylist", str(root / "private.txt"))
            self.assertEqual(inside.returncode, 2)
            self.assertNotIn(str(root), inside.stderr)
            missing = self.run_cli(root, "--denylist", str(root.parent / "missing-list"))
            self.assertEqual(missing.returncode, 2)

    def test_force_added_private_context_is_rejected_in_worktree_and_index(self):
        paths = [
            ".agent-context/handoff.md",
            "nested/.agent-context/handoff.md",
            "docs/private/context.md",
            "nested/docs/private/context.md",
            "nested/setup.private.md",
            ".env",
            ".env.production",
            "nested/.env.local",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text(
                ".agent-context/\ndocs/private/\n*.private.md\n", encoding="utf-8",
            )
            (root / ".env.example").write_text("PUBLIC_ORIGIN=\n", encoding="utf-8")
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("Private context", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "--force", "."], check=True)
            for options in [(), ("--staged",)]:
                with self.subTest(options=options):
                    result = self.run_cli(root, *options)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout.count(":1: private-context-path"), len(paths))
                    self.assertNotIn(".env.example:1:", result.stdout)

    def test_external_denylist_reports_only_category(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Sensitive owner alias\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            denylist = base / "private-terms.txt"
            denylist.write_text("# private local configuration\nowner alias\n", encoding="utf-8")
            result = self.run_cli(root, "--denylist", str(denylist))
            self.assertEqual(result.returncode, 1)
            self.assertRegex(result.stdout, r"file-sha256:[0-9a-f]{64}:1: private-term")
            self.assertNotIn("owner alias", result.stdout + result.stderr)

    def test_environment_key_loads_private_terms_without_printing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("private-owner-alias\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            denylist = base / "terms.txt"
            denylist.write_text("private-owner-alias\n", encoding="utf-8")
            with patch.dict(os.environ, {"LIBRARIUM_PRIVATE_TERMS_FILE": str(denylist)}):
                result = self.run_cli(root)
            self.assertEqual(result.returncode, 1)
            self.assertIn("private-term", result.stdout)
            self.assertNotIn("private-owner-alias", result.stdout + result.stderr)

    def test_private_filename_is_not_repeated_in_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            alias = "fictional-owner"
            (root / (alias + ".md")).write_text(alias + "\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            denylist = base / "terms.txt"
            denylist.write_text(alias + "\n", encoding="utf-8")
            result = self.run_cli(root, "--denylist", str(denylist))
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(alias, result.stdout + result.stderr)
            self.assertRegex(result.stdout, r"file-sha256:[0-9a-f]{64}:1: private-term")
            self.assertEqual(result.stdout, self.run_cli(root, "--denylist", str(denylist)).stdout)

    def test_filename_only_private_terms_are_checked_before_binary_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            alias = "fictional-owner"
            (root / (alias + ".bin")).write_bytes(b"\0")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            denylist = base / "terms.txt"
            denylist.write_text(alias + "\n", encoding="utf-8")
            for options in [(), ("--staged",)]:
                with self.subTest(options=options):
                    result = self.run_cli(root, *options, "--denylist", str(denylist))
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(":0: path-private-term", result.stdout)
                    self.assertNotIn(alias, result.stdout + result.stderr)

    def test_generic_private_values_in_paths_are_not_echoed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            names = [
                "C:\\Users\\" + "fictional-owner\\notes.md",
                "10." + "42.13.7-notes.md",
                "line\nfictional-owner.md",
            ]
            for name in names:
                (root / name).write_text("/home/" + "another-owner\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            result = self.run_cli(root)
            self.assertEqual(result.returncode, 1)
            for value in ["fictional-owner", "another-owner", "10." + "42.13.7", "C:", "line\\n"]:
                self.assertNotIn(value, result.stdout + result.stderr)
            self.assertIn(":0: path-private-address", result.stdout)
            self.assertIn(":0: path-personal-path", result.stdout)
            ids = {line.split(":")[1] for line in result.stdout.splitlines()
                   if line.startswith("file-sha256:")}
            self.assertEqual(len(ids), len(names))

    @staticmethod
    def run_cli(root, *options):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *options],
            capture_output=True,
            text=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
