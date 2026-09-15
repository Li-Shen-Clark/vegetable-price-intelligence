from __future__ import annotations

import unittest

from scripts.verify_portfolio_bundle import (
    assert_ignore_contract,
    assert_private_paths_untracked,
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
        assert_private_paths_untracked(paths)
        count, _ = assert_git_candidate_contract(paths)
        self.assertEqual(count, len(paths))
        history_paths = git_publishable_history_paths()
        self.assertTrue(history_paths)
        assert_git_candidate_contract(history_paths)


if __name__ == "__main__":
    unittest.main()
