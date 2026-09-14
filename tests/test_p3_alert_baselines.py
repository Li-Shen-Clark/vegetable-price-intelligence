from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.alerts.metrics import (
    average_precision,
    confusion_metrics,
    precision_recall_curve,
    select_threshold_at_fpr,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/p3/baselines"


class P3AlertMetricTests(unittest.TestCase):
    def test_01_average_precision_known_example(self) -> None:
        labels = [1, 0, 1, 0]
        scores = [0.9, 0.8, 0.7, 0.1]
        self.assertAlmostEqual(average_precision(labels, scores), (1.0 + 2 / 3) / 2)

    def test_02_curve_and_fixed_fpr_selection(self) -> None:
        labels = [1, 0, 1, 0, 0]
        scores = [0.9, 0.8, 0.7, 0.2, 0.1]
        curve = precision_recall_curve(labels, scores)
        selected = select_threshold_at_fpr(curve, 1 / 3)
        self.assertAlmostEqual(selected["recall"], 1.0)
        self.assertLessEqual(selected["false_positive_rate"], 1 / 3 + 1e-12)
        metrics = confusion_metrics(labels, scores, selected["threshold"])
        self.assertEqual(metrics["true_positives"], 2)
        self.assertEqual(metrics["false_positives"], 1)


class P3AlertBaselineArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scorecard = json.loads((OUTPUT / "validation_scorecard.json").read_text(encoding="utf-8"))
        cls.predictions = pd.read_parquet(OUTPUT / "validation_predictions.parquet")
        cls.curve = pd.read_parquet(OUTPUT / "validation_pr_curve.parquet")

    def test_03_all_baselines_cover_identical_validation_rows(self) -> None:
        self.assertEqual(self.scorecard["validation_rows"], 16388)
        self.assertEqual(set(self.predictions["baseline"]), set(self.scorecard["baselines"]))
        counts = self.predictions.groupby("baseline").size()
        self.assertTrue(counts.eq(16388).all())
        self.assertTrue(np.isfinite(self.predictions["risk_score"]).all())

    def test_04_scorecard_has_fixed_fpr_and_no_final_test(self) -> None:
        self.assertFalse(self.scorecard["final_test_read"])
        self.assertEqual(self.scorecard["fixed_false_positive_rate"], 0.10)
        for item in self.scorecard["baselines"].values():
            fixed = item["overall"]["threshold_at_fixed_fpr"]
            self.assertLessEqual(fixed["false_positive_rate"], 0.10 + 1e-12)
            self.assertIn("top_decile_spike_recall", item["overall"])
        self.assertFalse(self.curve.empty)


if __name__ == "__main__":
    unittest.main()
