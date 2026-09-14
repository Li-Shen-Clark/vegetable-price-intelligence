from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.procurement.common import sha256


ROOT = Path(__file__).resolve().parents[1]


class P4SensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.detail_path = ROOT / "artifacts/p4/sensitivity_rows.parquet"
        cls.detail = pd.read_parquet(cls.detail_path)
        cls.summary = json.loads(
            (ROOT / "artifacts/p4/sensitivity_summary.json").read_text(encoding="utf-8")
        )

    def test_01_grid_and_detail_keys_are_complete(self) -> None:
        self.assertEqual(self.summary["scenario_count"], 10)
        self.assertEqual(self.summary["combination_count"], 36)
        self.assertEqual(len(self.detail), 1080)
        self.assertFalse(
            self.detail.duplicated(
                ["vegetable_id", "horizon_days", "combination_id", "rank"]
            ).any()
        )
        counts = self.detail.groupby(["vegetable_id", "combination_id"]).size()
        self.assertTrue(counts.eq(3).all())

    def test_02_frequency_denominators_reconcile(self) -> None:
        for scenario in self.summary["scenarios"]:
            candidates = scenario["candidate_stability"]
            self.assertAlmostEqual(sum(item["top3_share"] for item in candidates), 3.0)
            self.assertAlmostEqual(sum(item["first_share"] for item in candidates), 1.0)
            self.assertTrue(all(0 <= item["top3_share"] <= 1 for item in candidates))
            self.assertTrue(all(0 <= item["first_share"] <= 1 for item in candidates))

    def test_03_default_first_city_is_present_in_stability_table(self) -> None:
        for scenario in self.summary["scenarios"]:
            match = [
                item
                for item in scenario["candidate_stability"]
                if item["city_id"] == scenario["default_first_city_id"]
            ]
            self.assertEqual(len(match), 1)
            self.assertAlmostEqual(match[0]["first_share"], scenario["default_first_share"])

    def test_04_cost_ranges_and_hash_are_valid(self) -> None:
        self.assertTrue(self.detail["unit_landed_cost"].gt(0).all())
        self.assertTrue(self.detail["total_landed_cost"].gt(0).all())
        self.assertEqual(self.summary["detail_sha256"], sha256(self.detail_path))

    def test_05_report_names_stable_and_sensitive_cases(self) -> None:
        report = (ROOT / "docs/p4_sensitivity_report.md").read_text(encoding="utf-8")
        self.assertIn(self.summary["most_stable_case"]["vegetable_name_zh"], report)
        self.assertIn(self.summary["most_sensitive_case"]["vegetable_name_zh"], report)
        self.assertIn("历史参数化情景", report)


if __name__ == "__main__":
    unittest.main()
