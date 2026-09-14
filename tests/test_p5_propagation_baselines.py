from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml
from src.propagation.modeling import add_exact_lags, benjamini_hochberg


ROOT = Path(__file__).resolve().parents[1]


class P5PropagationBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p5_propagation_experiment.yaml")
        cls.output_dir = ROOT / cls.config["baseline_artifact_dir"]
        cls.payload = json.loads(
            (cls.output_dir / "baseline_scorecard.json").read_text(encoding="utf-8")
        )
        cls.predictions = pd.read_parquet(
            cls.output_dir / "validation_predictions.parquet"
        )
        cls.scores = pd.read_parquet(cls.output_dir / "series_scorecard.parquet")

    def test_01_final_test_remains_unread(self) -> None:
        self.assertFalse(self.payload["final_test_evaluated"])
        self.assertEqual(self.payload["splits_evaluated"], ["train", "validation"])
        self.assertEqual(set(self.scores["split"]), {"train", "validation"})
        self.assertEqual(self.predictions["model_fit_end"].nunique(), 1)
        self.assertEqual(self.predictions["model_fit_end"].iloc[0], "2019-12-31")

    def test_02_validation_prediction_key_is_unique(self) -> None:
        self.assertFalse(
            self.predictions.duplicated(
                ["vegetable_id", "city_id", "bin_start"]
            ).any()
        )
        self.assertEqual(self.predictions["vegetable_id"].nunique(), 10)
        self.assertGreaterEqual(self.predictions["city_id"].nunique(), 20)

    def test_03_common_factor_reduces_average_raw_synchrony(self) -> None:
        diagnostics = pd.DataFrame(self.payload["common_factor_diagnostics"])
        validation = diagnostics.loc[diagnostics["split"].eq("validation")]
        self.assertEqual(len(validation), 10)
        self.assertGreater(
            validation["mean_absolute_correlation_reduction"].median(), 0.0
        )

    def test_04_baseline_features_are_target_and_common_lags_only(self) -> None:
        features = self.payload["features"]
        self.assertEqual(features["target_lags"], [1, 2, 3, 4])
        self.assertEqual(features["common_factor_lags"], [1, 2, 3, 4])
        self.assertNotIn("source", json.dumps(features))

    def test_05_exact_lag_does_not_bridge_missing_bins(self) -> None:
        frame = pd.DataFrame(
            {
                "vegetable_id": [1, 1],
                "city_id": ["a", "a"],
                "bin_start": pd.to_datetime(["2020-01-01", "2020-01-07"]),
                "value": [1.0, 2.0],
            }
        )
        lagged = add_exact_lags(
            frame, value_columns=["value"], lags=[1], bin_days=3
        )
        self.assertTrue(lagged["value_lag1"].isna().all())

    def test_06_bh_adjustment_is_monotone_and_index_safe(self) -> None:
        p_values = pd.Series([0.04, 0.001, 0.02], index=[8, 3, 5])
        result = benjamini_hochberg(p_values, 0.05)
        self.assertEqual(list(result.index), [8, 3, 5])
        ordered = result.loc[p_values.sort_values().index, "fdr_q_value"].to_numpy()
        self.assertTrue(np.all(np.diff(ordered) >= -1e-12))


if __name__ == "__main__":
    unittest.main()
