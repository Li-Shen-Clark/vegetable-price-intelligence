from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.procurement.build_procurement_web_data import RECORD_FIELDS
from src.procurement.common import sha256


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web/public/data/procurement"


class P4ProcurementWebDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = json.loads((WEB / "metadata.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((WEB / "manifest.json").read_text(encoding="utf-8"))
        cls.snapshot = pd.read_parquet(
            ROOT / "data/modeling/p4_procurement_mart/scenario_snapshot.parquet"
        )

    def test_01_metadata_freezes_city_product_and_parameter_scope(self) -> None:
        self.assertTrue(self.metadata["historical_scenario"])
        self.assertEqual(self.metadata["scenario_origin_date"], "2022-05-01")
        self.assertEqual(len(self.metadata["cities"]), 117)
        self.assertEqual(len(self.metadata["products"]), 10)
        self.assertEqual(self.metadata["horizons_days"], [7, 14, 28])
        grid = self.metadata["sensitivity_grid"]
        self.assertEqual(
            len(grid["transport_cost_per_kg_km"])
            * len(grid["loss_rate"])
            * len(grid["risk_aversion"]),
            36,
        )

    def test_02_product_files_cover_all_843_snapshot_rows(self) -> None:
        total = 0
        for product in self.metadata["products"]:
            payload = json.loads(
                (ROOT / "web/public" / product["data_file"]).read_text(encoding="utf-8")
            )
            self.assertEqual(payload["record_fields"], RECORD_FIELDS)
            self.assertEqual(len(payload["records"]), product["record_count"])
            total += len(payload["records"])
        self.assertEqual(total, 843)
        self.assertEqual(self.manifest["total_records"], 843)

    def test_03_sample_web_record_matches_procurement_mart(self) -> None:
        product = next(item for item in self.metadata["products"] if item["vegetable_id"] == 170060)
        payload = json.loads(
            (ROOT / "web/public" / product["data_file"]).read_text(encoding="utf-8")
        )
        record = dict(zip(payload["record_fields"], payload["records"][0]))
        source = self.snapshot.loc[
            self.snapshot["vegetable_id"].eq(170060)
            & self.snapshot["city_id"].eq(record["city_id"])
            & self.snapshot["horizon_days"].eq(record["horizon_days"])
        ].iloc[0]
        self.assertAlmostEqual(record["released_point_prediction"], source["released_point_prediction"])
        self.assertAlmostEqual(record["base_uncertainty_per_kg"], source["base_uncertainty_per_kg"])
        self.assertEqual(record["release_point_source"], source["release_point_source"])

    def test_04_baseline_labels_and_interval_nulls_are_preserved(self) -> None:
        for product in self.metadata["products"]:
            payload = json.loads(
                (ROOT / "web/public" / product["data_file"]).read_text(encoding="utf-8")
            )
            for values in payload["records"]:
                record = dict(zip(payload["record_fields"], values))
                if record["release_status"] == "baseline_fallback":
                    self.assertIn("不是模型预测", record["price_input_label"])
                    self.assertIsNone(record["released_p10"])
                    self.assertIsNone(record["released_p90"])

    def test_05_manifest_hashes_match_public_files(self) -> None:
        self.assertEqual(
            self.manifest["metadata"]["sha256"], sha256(WEB / "metadata.json")
        )
        for item in self.manifest["products"]:
            self.assertEqual(item["sha256"], sha256(ROOT / "web/public" / item["path"]))

    def test_06_procurement_route_keeps_required_disclosures(self) -> None:
        page = (ROOT / "web/app/procurement/page.tsx").read_text(encoding="utf-8")
        for phrase in [
            "Historical scenario",
            "当前价格延续（基线），不是模型预测",
            "历史季节中位数（基线），不是模型预测",
            "城市中心直线距离",
            "不执行采购",
        ]:
            self.assertIn(phrase, page)


if __name__ == "__main__":
    unittest.main()
