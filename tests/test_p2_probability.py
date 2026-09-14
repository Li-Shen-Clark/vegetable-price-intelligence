from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.forecast.calibrate_intervals import conformal_quantile
from src.forecast.metrics import probability_metric_record


ROOT = Path(__file__).resolve().parents[1]
PROBABILITY_DIR = ROOT / "artifacts/p2/probability"


class P2ProbabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calibrator = json.loads(
            (PROBABILITY_DIR / "frozen_interval_calibrator.json").read_text(encoding="utf-8")
        )
        cls.scorecard = json.loads(
            (PROBABILITY_DIR / "calibration_scorecard.json").read_text(encoding="utf-8")
        )
        cls.predictions = pd.read_parquet(
            PROBABILITY_DIR / "validation_probability_predictions.parquet"
        )

    def test_01_conformal_quantile_uses_finite_sample_higher_rule(self) -> None:
        value, level = conformal_quantile(np.arange(1.0, 11.0), alpha=0.2)
        self.assertEqual(level, 0.9)
        self.assertEqual(value, 9.0)

    def test_02_probability_rows_are_ordered_positive_and_complete(self) -> None:
        frame = self.predictions
        self.assertEqual(len(frame), 11882)
        self.assertTrue(frame["p10"].gt(0).all())
        self.assertTrue(frame["p10"].le(frame["p50"]).all())
        self.assertTrue(frame["p50"].le(frame["p90"]).all())
        np.testing.assert_allclose(frame["p50"], frame["point_prediction"], rtol=0, atol=0)

    def test_03_temporal_evaluation_metrics_recompute(self) -> None:
        evaluation = self.predictions[
            self.predictions["interval_phase"].eq("temporal_evaluation")
        ]
        self.assertEqual(len(evaluation), self.scorecard["temporal_evaluation_row_count"])
        self.assertEqual(pd.to_datetime(evaluation["origin_date"]).min().date().isoformat(), "2020-09-01")
        actual = probability_metric_record(
            evaluation["target_price"], evaluation["p10"], evaluation["p50"], evaluation["p90"]
        )
        self.assertEqual(actual, self.scorecard["temporal_evaluation_metrics"])

    def test_04_calibrator_is_frozen_without_final_test(self) -> None:
        self.assertFalse(self.calibrator["final_test_opened"])
        self.assertEqual(len(self.calibrator["final_group_quantiles"]), 30)
        self.assertTrue(all("final_test" not in path for path in self.calibrator["inputs"]))
        self.assertIn(
            self.calibrator["selected_width_scale"],
            [row["width_scale"] for row in self.scorecard["width_scale_candidates"]],
        )


if __name__ == "__main__":
    unittest.main()
