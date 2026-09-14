from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.procurement.common import sha256


ROOT = Path(__file__).resolve().parents[1]
MART = ROOT / "data/modeling/p4_procurement_mart"


class P4ProcurementMartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = pd.read_parquet(MART / "scenario_snapshot.parquet")
        cls.calibration = pd.read_parquet(MART / "residual_calibration.parquet")
        cls.manifest = json.loads((MART / "manifest.json").read_text(encoding="utf-8"))

    def test_01_snapshot_key_and_scope(self) -> None:
        keys = ["vegetable_id", "city_id", "origin_date", "horizon_days", "target_date"]
        self.assertEqual(len(self.snapshot), 843)
        self.assertFalse(self.snapshot.duplicated(keys).any())
        self.assertEqual(self.snapshot["vegetable_id"].nunique(), 10)
        self.assertEqual(sorted(self.snapshot["horizon_days"].unique().tolist()), [7, 14, 28])
        self.assertTrue(self.snapshot["coverage_tier"].eq("A").all())

    def test_02_release_route_and_interval_gate_are_preserved(self) -> None:
        groups = self.snapshot[
            ["vegetable_id", "horizon_days", "release_status", "release_point_source"]
        ].drop_duplicates()
        self.assertEqual(len(groups), 30)
        self.assertEqual(
            groups["release_status"].value_counts().to_dict(),
            {
                "point_only_model": 16,
                "baseline_fallback": 10,
                "model_minimum": 3,
                "model_target": 1,
            },
        )
        released = self.snapshot["interval_status"].eq("calibrated_released")
        self.assertEqual(
            len(self.snapshot.loc[released, ["vegetable_id", "horizon_days"]].drop_duplicates()),
            4,
        )
        self.assertTrue(self.snapshot.loc[~released, "released_p10"].isna().all())
        self.assertTrue(self.snapshot.loc[~released, "released_p90"].isna().all())

    def test_03_residual_calibration_has_no_lookahead(self) -> None:
        self.assertEqual(len(self.calibration), 30)
        self.assertTrue(self.calibration["no_lookahead_pass"].all())
        self.assertTrue(self.calibration["sample_count"].ge(30).all())
        self.assertTrue(
            pd.to_datetime(self.calibration["calibration_target_end"])
            .lt(pd.Timestamp("2022-05-01"))
            .all()
        )
        self.assertTrue(self.calibration["q80_absolute_log_error"].gt(0).all())

    def test_04_reliability_and_risk_values_are_finite(self) -> None:
        columns = [
            "released_point_prediction",
            "origin_source_reliability_score",
            "base_uncertainty_per_kg",
            "default_risk_penalty_per_kg",
        ]
        self.assertTrue(np.isfinite(self.snapshot[columns].to_numpy(dtype=float)).all())
        self.assertTrue(self.snapshot["origin_source_reliability_score"].between(0, 1).all())
        self.assertTrue(self.snapshot["base_uncertainty_per_kg"].ge(0).all())
        self.assertTrue(self.snapshot["default_reliability_multiplier"].between(1, 1.5).all())

    def test_05_baseline_copy_is_explicit(self) -> None:
        baseline = self.snapshot["release_status"].eq("baseline_fallback")
        self.assertTrue(
            self.snapshot.loc[baseline, "price_input_label"]
            .str.contains("不是模型预测")
            .all()
        )
        self.assertTrue(
            self.snapshot.loc[baseline, "interval_status"].eq("not_applicable_baseline").all()
        )

    def test_06_manifest_hashes_match_outputs(self) -> None:
        self.assertEqual(
            self.manifest["snapshot"]["sha256"], sha256(MART / "scenario_snapshot.parquet")
        )
        self.assertEqual(
            self.manifest["residual_calibration"]["sha256"],
            sha256(MART / "residual_calibration.parquet"),
        )
        self.assertEqual(self.manifest["residual_calibration"]["rows"], 30)


if __name__ == "__main__":
    unittest.main()
