from __future__ import annotations

import re
import unittest

from scripts.verify_portfolio_bundle import (
    PRIVATE_HISTORY_PATHS,
    ROOT,
    assert_ignore_contract,
    assert_private_paths_absent,
    assert_public_text_is_portable,
    assert_required_paths,
    assert_git_candidate_contract,
    git_candidate_paths,
    git_publishable_history_paths,
)


class PortfolioBundleTests(unittest.TestCase):
    def test_01_required_portfolio_files_exist(self) -> None:
        assert_required_paths()

    def test_02_large_local_data_and_secrets_are_ignored(self) -> None:
        assert_ignore_contract()

    def test_03_public_facing_text_has_no_absolute_local_paths(self) -> None:
        assert_public_text_is_portable()

    def test_04_git_candidates_contain_no_data(self) -> None:
        paths = git_candidate_paths()
        self.assertTrue(paths)
        assert_private_paths_absent(paths)
        count, _ = assert_git_candidate_contract(paths)
        self.assertEqual(count, len(paths))
        history_paths = git_publishable_history_paths()
        self.assertTrue(history_paths)
        assert_private_paths_absent(history_paths, PRIVATE_HISTORY_PATHS)
        assert_git_candidate_contract(history_paths)

    def test_05_curated_roadmap_replaces_internal_stage_plans(self) -> None:
        roadmap = (ROOT / "PROJECT_ROADMAP.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for stage in range(8):
            self.assertIn(f"P{stage} ·", roadmap)
        for phrase in (
            "Pricing Intelligence",
            "partial_release",
            "alert_release",
            "scenario_release",
            "common_shock_only",
            "evidence quality determines the release state",
        ):
            self.assertIn(phrase, roadmap)
        self.assertIn("[Project Roadmap](PROJECT_ROADMAP.md)", readme)
        for stage in range(8):
            self.assertNotIn(f"P{stage}_执行计划.md", readme)
        for target in re.findall(r"\]\(([^)]+)\)", roadmap):
            if target.startswith(("http://", "https://", "#")):
                continue
            self.assertTrue((ROOT / target).is_file(), target)


if __name__ == "__main__":
    unittest.main()
