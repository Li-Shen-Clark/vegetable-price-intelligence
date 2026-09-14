from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.alerts.train_alert_models import predict_from_artifact


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/p3/models"


class P3AlertModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = json.loads((OUTPUT / "frozen_alert_model.json").read_text(encoding="utf-8"))
        cls.scorecard = json.loads((OUTPUT / "candidate_scorecard.json").read_text(encoding="utf-8"))
        cls.validation = pd.read_parquet(ROOT / "data/modeling/p3_alert_mart/validation.parquet")
        cls.predictions = pd.read_parquet(OUTPUT / "validation_candidate_predictions.parquet")

    def test_01_candidate_selection_does_not_read_final_test(self) -> None:
        self.assertFalse(self.frozen["final_test_read"])
        self.assertFalse(self.scorecard["final_test_read"])
        self.assertEqual(self.scorecard["train_rows"], 70589)
        self.assertEqual(self.scorecard["validation_rows"], 16388)

    def test_02_every_candidate_covers_same_validation_rows(self) -> None:
        counts = self.predictions.groupby("candidate_id").size()
        self.assertEqual(len(counts), 6)
        self.assertTrue(counts.eq(16388).all())
        self.assertTrue(self.predictions["risk_probability"].between(0, 1).all())

    def test_03_frozen_artifact_reproduces_validation_probabilities(self) -> None:
        expected = self.predictions[
            self.predictions["candidate_id"].eq(self.frozen["candidate_id"])
        ].sort_values(["vegetable_id", "city_id", "origin_date"])
        actual_frame = self.validation.sort_values(["vegetable_id", "city_id", "origin_date"])
        actual = predict_from_artifact(actual_frame, self.frozen)
        np.testing.assert_allclose(actual, expected["risk_probability"].to_numpy(), rtol=0, atol=1e-12)

    def test_04_threshold_satisfies_validation_fpr_contract(self) -> None:
        metrics = self.frozen["validation_metrics"]["threshold_at_fixed_fpr"]
        self.assertLessEqual(metrics["false_positive_rate"], 0.10 + 1e-12)
        self.assertEqual(self.frozen["selection_data"], ["train", "validation"])
        self.assertEqual(len(self.frozen["coefficients"]), len(self.frozen["preprocessor"]["feature_names"]))
        self.assertTrue(np.isfinite(np.asarray(self.frozen["coefficients"], dtype=float)).all())
        self.assertEqual(len(self.scorecard["best_candidate_by_product"]), 10)


if __name__ == "__main__":
    unittest.main()
