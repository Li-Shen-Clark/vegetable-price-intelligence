from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.alerts.train_alert_models import predict_from_artifact


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/p3/final"


class P3FinalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = json.loads(
            (ROOT / "artifacts/p3/models/frozen_alert_model.json").read_text(encoding="utf-8")
        )
        cls.scorecard = json.loads((OUTPUT / "final_scorecard.json").read_text(encoding="utf-8"))
        cls.release = json.loads((OUTPUT / "release_decision.json").read_text(encoding="utf-8"))
        cls.predictions = pd.read_parquet(OUTPUT / "final_test_predictions.parquet")

    def test_01_frozen_model_and_threshold_are_unchanged(self) -> None:
        self.assertFalse(self.scorecard["model_refit_on_final_test"])
        self.assertFalse(self.scorecard["threshold_reselected_on_final_test"])
        self.assertEqual(
            self.scorecard["frozen_validation_threshold"],
            self.frozen["validation_action_threshold"],
        )
        recomputed = predict_from_artifact(self.predictions, self.frozen)
        np.testing.assert_allclose(
            recomputed,
            self.predictions["risk_probability"].to_numpy(dtype=float),
            rtol=0,
            atol=1e-12,
        )

    def test_02_final_predictions_cover_the_frozen_mart(self) -> None:
        manifest = json.loads(
            (ROOT / "data/modeling/p3_alert_mart/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(self.predictions), manifest["splits"]["final_test"]["rows"])
        self.assertFalse(
            self.predictions.duplicated(["vegetable_id", "city_id", "origin_date"]).any()
        )
        self.assertTrue(
            self.predictions["predicted_alert"].eq(
                self.predictions["risk_probability"].ge(
                    self.frozen["validation_action_threshold"]
                )
            ).all()
        )

    def test_03_release_decision_matches_all_gates(self) -> None:
        all_pass = all(item["pass"] for item in self.release["gates"].values())
        if all_pass:
            self.assertEqual(self.release["release_status"], "alert_release")
        else:
            self.assertIn(self.release["release_status"], {"research_only", "no_signal"})
        self.assertEqual(len(self.scorecard["by_product"]), 10)
        self.assertEqual(len(self.scorecard["sensitivity"]), 6)

    def test_04_final_pr_curve_and_cases_are_present(self) -> None:
        curve = pd.read_parquet(OUTPUT / "final_pr_curve.parquet")
        self.assertIn("frozen_model", set(curve["score_source"]))
        self.assertIn(self.scorecard["best_baseline"], set(curve["score_source"]))
        for outcome in ["true_positive", "false_positive", "false_negative"]:
            self.assertGreater(len(self.scorecard["cases"][outcome]), 0)
            self.assertLessEqual(len(self.scorecard["cases"][outcome]), 10)


if __name__ == "__main__":
    unittest.main()
