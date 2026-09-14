from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.forecast.metrics import mae, point_metric_record, smape, wape


ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = ROOT / "artifacts/p2/baselines"


class P2BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.predictions = pd.read_parquet(BASELINE_DIR / "validation_predictions.parquet")
        cls.scorecard = json.loads(
            (BASELINE_DIR / "validation_scorecard.json").read_text(encoding="utf-8")
        )

    def test_01_point_metric_formulas_on_hand_sample(self) -> None:
        actual = np.array([1.0, 2.0, 3.0])
        predicted = np.array([1.0, 1.0, 5.0])
        self.assertAlmostEqual(wape(actual, predicted), 0.5)
        self.assertAlmostEqual(mae(actual, predicted), 1.0)
        self.assertAlmostEqual(
            smape(actual, predicted),
            np.mean([0.0, 2.0 / 3.0, 4.0 / 8.0]),
        )

    def test_02_predictions_are_complete_positive_paired_rows(self) -> None:
        columns = ["last_valid_price", "weekly_pattern", "historical_seasonal"]
        self.assertEqual(len(self.predictions), 11882)
        self.assertEqual(self.scorecard["predictions"]["paired_row_count"], 11882)
        self.assertTrue(np.isfinite(self.predictions[columns].to_numpy()).all())
        self.assertTrue(self.predictions[columns].gt(0).all().all())
        self.assertFalse(
            self.predictions.duplicated(
                ["vegetable_id", "city_id", "origin_date", "horizon_days"]
            ).any()
        )

    def test_03_product_score_recomputes_from_prediction_detail(self) -> None:
        expected = self.scorecard["product_horizon_scores"][0]
        frame = self.predictions[
            self.predictions["vegetable_id"].eq(expected["vegetable_id"])
            & self.predictions["horizon_days"].eq(expected["horizon_days"])
        ]
        actual = point_metric_record(frame["actual_price"], frame[expected["baseline"]])
        self.assertEqual(actual, {key: expected[key] for key in actual})

    def test_04_best_baselines_are_frozen_without_final_test(self) -> None:
        self.assertFalse(self.scorecard["final_test_opened"])
        self.assertEqual(len(self.scorecard["best_baselines"]), 30)
        self.assertEqual(self.scorecard["input"]["path"], "data/modeling/p2_forecast_mart/validation.parquet")
        self.assertNotIn("final_test", json.dumps(self.scorecard["input"]))


if __name__ == "__main__":
    unittest.main()
