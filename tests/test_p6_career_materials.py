"""Publication checks that never require the owner's private preparation notes."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_portfolio_bundle as verifier


class P6CareerMaterialsTests(unittest.TestCase):
    def test_01_private_documents_are_ignored_and_not_required(self):
        for path in verifier.PRIVATE_LOCAL_PATHS:
            if path == ".private-deliverables":
                continue
            with self.subTest(path=path):
                self.assertNotIn(path, verifier.REQUIRED_PATHS)
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "-q", path],
                    cwd=verifier.ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 0)

    def test_02_forced_adds_and_private_backup_subdirectories_are_rejected(self):
        paths = [
            *verifier.PRIVATE_LOCAL_PATHS,
            ".private-backups/history.bundle",
            ".private-deliverables/notes/example.md",
            "archive/GUIDEBOOK.md",
            "docs/p8_interview_guide.md",
            "nested/P8_执行计划.md",
        ]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(AssertionError):
                verifier.assert_private_paths_absent([path])

    def test_03_public_methods_and_site_files_remain_allowed(self):
        verifier.assert_private_paths_absent([
            "docs/p2_final_model_card.md",
            "docs/p6_evidence_matrix.md",
            "PROJECT_ROADMAP.md",
            "portfolio-site/index.html",
        ])

    def test_04_ci_requires_full_history_in_both_workflows(self):
        for name in ("portfolio-ci.yml", "pages.yml"):
            workflow = (verifier.ROOT / ".github/workflows" / name).read_text()
            self.assertIn(
                "uses: actions/checkout@v7\n        with:\n          fetch-depth: 0",
                workflow,
            )


class PrivateHistoryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="publication-history-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Publication Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", "/dev/null")
        (self.root / "README.md").write_text("synthetic test fixture\n")
        self.commit("Initial public content")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def history(self, root=None):
        with patch.object(verifier, "ROOT", root or self.root):
            return verifier.git_publishable_history_paths()

    def test_deleted_plan_with_identical_public_blob_is_still_detected(self):
        path = "P7_执行计划.md"
        (self.root / path).write_bytes((self.root / "README.md").read_bytes())
        self.commit("Accidental private document")
        (self.root / path).unlink()
        self.commit("Remove private document from current tree")
        self.assertNotIn(path, self.git("ls-tree", "-r", "--name-only", "HEAD"))
        self.assertIn(path, self.history())
        with self.assertRaises(AssertionError):
            verifier.assert_private_paths_absent(self.history())

    def test_private_file_on_another_branch_is_detected(self):
        self.git("checkout", "-qb", "other")
        (self.root / "GUIDEBOOK.md").write_text("synthetic private fixture\n")
        self.commit("Private file on another branch")
        self.git("checkout", "-q", "main")
        with self.assertRaises(AssertionError):
            verifier.assert_private_paths_absent(self.history())

    def test_private_file_reachable_only_from_tag_is_detected(self):
        self.git("checkout", "-qb", "other")
        (self.root / "P7_状态评审.md").write_text("synthetic private fixture\n")
        self.commit("Private file in a tagged version")
        self.git("tag", "old-version")
        self.git("checkout", "-q", "main")
        self.git("branch", "-D", "other")
        with self.assertRaises(AssertionError):
            verifier.assert_private_paths_absent(self.history())

    def test_clean_history_passes(self):
        verifier.assert_private_paths_absent(self.history())

    def test_force_added_ignored_career_file_is_rejected(self):
        path = "docs/p6_career_pack.md"
        (self.root / ".gitignore").write_text("/docs/*_career_pack.md\n")
        (self.root / "docs").mkdir()
        (self.root / path).write_text("synthetic private fixture\n")
        with patch.object(verifier, "ROOT", self.root):
            self.assertNotIn(path, verifier.git_candidate_paths())
            self.git("add", "-f", path)
            self.assertIn(path, verifier.git_candidate_paths())
            with self.assertRaises(AssertionError):
                verifier.assert_private_paths_absent(verifier.git_candidate_paths())

    def test_shallow_clone_cannot_report_a_successful_history_audit(self):
        (self.root / "README.md").write_text("second public revision\n")
        self.commit("Second public commit")
        destination = self.root / "shallow-copy"
        self.git("clone", "-q", "--depth=1", self.root.as_uri(), str(destination))
        with self.assertRaisesRegex(AssertionError, "full Git history"):
            self.history(destination)


if __name__ == "__main__":
    unittest.main()
