from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FORECAST_DIR = ROOT / "web/public/data/forecast"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class P2ForecastWebDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = json.loads((FORECAST_DIR / "metadata.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((FORECAST_DIR / "manifest.json").read_text(encoding="utf-8"))
        cls.release = json.loads(
            (ROOT / "artifacts/p2/final/release_matrix.json").read_text(encoding="utf-8")
        )

    def test_01_metadata_preserves_historical_and_release_boundaries(self) -> None:
        self.assertTrue(self.metadata["historical_backtest"])
        self.assertEqual(self.metadata["data_as_of"], "2022-06-22")
        self.assertEqual(self.metadata["snapshot_origin_date"], "2022-05-01")
        self.assertEqual(self.metadata["release_status_counts"], self.release["status_counts"])
        self.assertIn("not a current quote", self.metadata["boundary"])

    def test_02_all_product_files_match_manifest(self) -> None:
        self.assertEqual(self.manifest["product_count"], 10)
        self.assertEqual(len(self.metadata["products"]), 10)
        for product in self.metadata["products"]:
            path = ROOT / "web/public" / product["data_file"]
            self.assertTrue(path.is_file())
            self.assertEqual(sha256(path), self.manifest["product_files"][product["data_file"]])

    def test_03_snapshot_values_recompute_from_final_detail(self) -> None:
        product = next(
            row
            for row in self.metadata["products"]
            if row["vegetable_id"] == self.metadata["defaults"]["vegetable_id"]
        )
        payload = json.loads(
            (ROOT / "web/public" / product["data_file"]).read_text(encoding="utf-8")
        )
        fields = payload["record_fields"]
        record = dict(zip(fields, payload["records"][0]))
        final = pd.read_parquet(ROOT / "artifacts/p2/final/final_test_predictions.parquet")
        expected = final[
            final["vegetable_id"].eq(product["vegetable_id"])
            & final["city_id"].eq(record["city_id"])
            & final["horizon_days"].eq(record["horizon_days"])
            & pd.to_datetime(final["origin_date"]).eq(pd.Timestamp("2022-05-01"))
        ].iloc[0]
        self.assertAlmostEqual(record["released_point_prediction"], expected["released_point_prediction"], 4)
        self.assertAlmostEqual(record["actual_price"], expected["target_price"], 4)
        self.assertEqual(record["release_status"], expected["release_status"])

    def test_04_interval_visibility_exactly_matches_release_matrix(self) -> None:
        for product in self.metadata["products"]:
            payload = json.loads(
                (ROOT / "web/public" / product["data_file"]).read_text(encoding="utf-8")
            )
            fields = payload["record_fields"]
            for raw in payload["records"]:
                record = dict(zip(fields, raw))
                should_have_interval = record["release_status"] in {
                    "model_target",
                    "model_minimum",
                }
                self.assertEqual(record["released_p10"] is not None, should_have_interval)
                self.assertEqual(record["released_p90"] is not None, should_have_interval)

    def test_05_forecast_page_has_boundaries_states_and_navigation(self) -> None:
        page = (ROOT / "web/app/forecast/page.tsx").read_text(encoding="utf-8")
        historical_page = (ROOT / "web/app/page.tsx").read_text(encoding="utf-8")
        self.assertIn("Historical backtest", page)
        self.assertIn("不是当前报价", page)
        self.assertIn("baseline_fallback", page)
        self.assertIn("point_only_model", page)
        self.assertIn("<LoadingSurface />", page)
        self.assertIn("预测数据暂时不可用", page)
        self.assertIn("这个城市缺少所选跨度", page)
        self.assertIn('href="/"', page)
        self.assertIn('href="/forecast"', historical_page)


if __name__ == "__main__":
    unittest.main()
