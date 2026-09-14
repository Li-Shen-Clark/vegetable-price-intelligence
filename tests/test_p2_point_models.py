from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.forecast.metrics import point_metric_record
from src.forecast.train_point_models import predict_from_frozen


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "artifacts/p2/models"


class P2PointModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = json.loads((MODEL_DIR / "frozen_point_model.json").read_text(encoding="utf-8"))
        cls.scorecard = json.loads((MODEL_DIR / "candidate_scorecard.json").read_text(encoding="utf-8"))
        cls.predictions = pd.read_parquet(MODEL_DIR / "validation_candidate_predictions.parquet")
        cls.validation = pd.read_parquet(
            ROOT / "data/modeling/p2_forecast_mart/validation.parquet"
        )

    def test_01_training_contract_does_not_open_final_test(self) -> None:
        self.assertFalse(self.frozen["final_test_opened"])
        self.assertEqual(self.frozen["selection_split"], "validation")
        self.assertEqual(self.frozen["transformer"]["fit_split"], "train")
        self.assertTrue(all("final_test" not in path for path in self.frozen["inputs"]))

    def test_02_candidates_cover_all_paired_rows(self) -> None:
        self.assertEqual(len(self.predictions), 11882)
        self.assertEqual(self.scorecard["candidate_count"], 28)
        candidate_columns = [row["candidate"] for row in self.scorecard["candidate_scores"]]
        self.assertTrue(np.isfinite(self.predictions[candidate_columns].to_numpy()).all())
        self.assertTrue(self.predictions[candidate_columns].gt(0).all().all())

    def test_03_frozen_model_replays_validation_predictions(self) -> None:
        replay = predict_from_frozen(self.validation, self.frozen)
        stored = self.predictions["selected_model_prediction"].to_numpy(dtype=float)
        np.testing.assert_allclose(replay, stored, rtol=0.0, atol=1e-12)
        metrics = point_metric_record(self.predictions["target_price"], stored)
        expected = self.frozen["selected_validation_metrics"]
        self.assertEqual(metrics, {key: expected[key] for key in metrics})

    def test_04_group_routes_follow_frozen_validation_rule(self) -> None:
        self.assertEqual(len(self.frozen["group_decisions"]), 30)
        for row in self.frozen["group_decisions"]:
            expected = (
                row["relative_wape_improvement"] > 0
                and row["improved_series_share"] > 0.5
            )
            self.assertEqual(row["validation_route"] == "model_candidate", expected)


if __name__ == "__main__":
    unittest.main()
