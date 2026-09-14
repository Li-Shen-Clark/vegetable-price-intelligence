from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.forecast.evaluate_final_test import release_status
from src.forecast.metrics import point_metric_record, probability_metric_record
from src.forecast.train_point_models import predict_from_frozen


ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = ROOT / "artifacts/p2/final"


class P2FinalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.predictions = pd.read_parquet(FINAL_DIR / "final_test_predictions.parquet")
        cls.scorecard = json.loads((FINAL_DIR / "final_scorecard.json").read_text(encoding="utf-8"))
        cls.release = json.loads((FINAL_DIR / "release_matrix.json").read_text(encoding="utf-8"))
        cls.frozen = json.loads(
            (ROOT / "artifacts/p2/models/frozen_point_model.json").read_text(encoding="utf-8")
        )
        cls.mart = pd.read_parquet(ROOT / "data/modeling/p2_forecast_mart/final_test.parquet")

    def test_01_final_predictions_cover_every_frozen_test_row(self) -> None:
        self.assertTrue(self.scorecard["final_test_opened"])
        self.assertFalse(self.scorecard["specifications_refit_after_test"])
        self.assertEqual(len(self.predictions), 16217)
        columns = [
            "best_baseline_prediction",
            "model_prediction",
            "validation_routed_point",
            "p10",
            "p50",
            "p90",
            "released_point_prediction",
        ]
        self.assertTrue(np.isfinite(self.predictions[columns].to_numpy()).all())

    def test_02_frozen_model_replays_final_prediction(self) -> None:
        replay = predict_from_frozen(self.mart, self.frozen)
        np.testing.assert_allclose(
            replay,
            self.predictions["model_prediction"].to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-12,
        )

    def test_03_overall_metrics_recompute_from_detail(self) -> None:
        model = point_metric_record(
            self.predictions["target_price"], self.predictions["model_prediction"]
        )
        baseline = point_metric_record(
            self.predictions["target_price"], self.predictions["best_baseline_prediction"]
        )
        probability = probability_metric_record(
            self.predictions["target_price"],
            self.predictions["p10"],
            self.predictions["p50"],
            self.predictions["p90"],
        )
        self.assertEqual(model, self.scorecard["model_overall_metrics"])
        self.assertEqual(baseline, self.scorecard["best_baseline_overall_metrics"])
        self.assertEqual(
            probability, self.scorecard["overall_probability_metrics_on_validation_route"]
        )

    def test_04_release_matrix_applies_frozen_rule_without_promotion(self) -> None:
        self.assertEqual(len(self.release["group_results"]), 30)
        for row in self.release["group_results"]:
            expected = release_status(
                row["validation_route"],
                row["relative_wape_improvement"],
                row["improved_series_share"],
                row["probability_metrics"]["interval_coverage_80"],
            )
            self.assertEqual(row["release_status"], expected)
            if row["validation_route"] == "baseline_fallback":
                self.assertEqual(row["release_status"], "baseline_fallback")


if __name__ == "__main__":
    unittest.main()
