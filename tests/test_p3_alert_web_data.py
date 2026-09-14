from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web/public/data/alerts"


class P3AlertWebDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = json.loads((OUTPUT / "metadata.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((OUTPUT / "manifest.json").read_text(encoding="utf-8"))

    def test_01_metadata_preserves_historical_boundary(self) -> None:
        self.assertTrue(self.metadata["historical_replay"])
        self.assertIn("人工复核", self.metadata["boundary"])
        self.assertEqual(self.metadata["release_status"], "alert_release")
        self.assertEqual(len(self.metadata["products"]), 10)

    def test_02_product_files_follow_compact_contract(self) -> None:
        total = 0
        for product in self.metadata["products"]:
            path = ROOT / "web/public" / product["data_file"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["record_fields"]), 21)
            self.assertTrue(payload["records"])
            self.assertTrue(all(len(row) == len(payload["record_fields"]) for row in payload["records"]))
            total += len(payload["records"])
        self.assertEqual(total, 23530)
        self.assertEqual(total, self.manifest["total_rows"])

    def test_03_defaults_resolve_to_a_true_positive_replay(self) -> None:
        product = next(
            item
            for item in self.metadata["products"]
            if item["vegetable_id"] == self.metadata["defaults"]["vegetable_id"]
        )
        payload = json.loads(
            (ROOT / "web/public" / product["data_file"]).read_text(encoding="utf-8")
        )
        fields = {name: index for index, name in enumerate(payload["record_fields"])}
        record = next(
            row
            for row in payload["records"]
            if row[fields["city_id"]] == self.metadata["defaults"]["city_id"]
            and row[fields["origin_date"]] == self.metadata["defaults"]["origin_date"]
        )
        self.assertEqual(record[fields["outcome_type"]], "true_positive")

    def test_04_pr_curve_is_small_and_complete(self) -> None:
        self.assertGreater(len(self.metadata["pr_curve"]), 20)
        self.assertLessEqual(len(self.metadata["pr_curve"]), 160)
        for item in self.metadata["pr_curve"]:
            self.assertIn("precision", item)
            self.assertIn("recall", item)

    def test_05_alert_route_and_cross_navigation_are_present(self) -> None:
        alerts_page = (ROOT / "web/app/alerts/page.tsx").read_text(encoding="utf-8")
        monitor_page = (ROOT / "web/app/page.tsx").read_text(encoding="utf-8")
        forecast_page = (ROOT / "web/app/forecast/page.tsx").read_text(encoding="utf-8")
        self.assertIn("历史回放，不是今天的实时预警", alerts_page)
        self.assertIn("不要仅凭这条提醒自动调价", alerts_page)
        self.assertIn('href="/alerts"', monitor_page)
        self.assertIn('href="/alerts"', forecast_page)


if __name__ == "__main__":
    unittest.main()
