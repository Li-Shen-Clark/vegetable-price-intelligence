from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml
from src.propagation.modeling import benjamini_hochberg


ROOT = Path(__file__).resolve().parents[1]


class P5DirectionalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p5_propagation_experiment.yaml")
        cls.output_dir = ROOT / cls.config["model_artifact_dir"]
        cls.summary = json.loads(
            (cls.output_dir / "validation_summary.json").read_text(encoding="utf-8")
        )
        cls.frozen = json.loads(
            (cls.output_dir / "validation_frozen_edges.json").read_text(encoding="utf-8")
        )
        cls.scorecard = pd.read_parquet(
            cls.output_dir / "validation_candidate_scorecard.parquet"
        )

    def test_01_only_geographic_candidates_are_modeled(self) -> None:
        candidates = pd.read_parquet(
            ROOT / self.config["propagation_mart_dir"] / "candidate_edges.parquet"
        )
        candidate_keys = set(
            map(
                tuple,
                candidates[["vegetable_id", "source_city_id", "target_city_id"]].to_numpy(),
            )
        )
        model_keys = set(
            map(
                tuple,
                self.scorecard[["vegetable_id", "source_city_id", "target_city_id"]].to_numpy(),
            )
        )
        self.assertTrue(model_keys.issubset(candidate_keys))
        self.assertFalse(
            self.scorecard.duplicated(
                ["vegetable_id", "source_city_id", "target_city_id"]
            ).any()
        )

    def test_02_bh_fdr_is_reproducible_per_product(self) -> None:
        for _, group in self.scorecard.groupby("vegetable_id", observed=True):
            expected = benjamini_hochberg(
                group["train_joint_p_value"], float(self.config["fdr_q"])
            )
            np.testing.assert_allclose(
                group["fdr_q_value"].to_numpy(float),
                expected["fdr_q_value"].to_numpy(float),
                rtol=0,
                atol=1e-14,
            )
            np.testing.assert_array_equal(
                group["fdr_reject"].to_numpy(bool),
                expected["fdr_reject"].to_numpy(bool),
            )

    def test_03_validation_selection_is_mechanical(self) -> None:
        expected = (
            self.scorecard["fdr_reject"]
            & self.scorecard["source_coefficient_sum"].gt(0)
            & self.scorecard["validation_rmse_improvement"].ge(0.01)
            & self.scorecard["validation_mae_improvement"].ge(-0.005)
        )
        np.testing.assert_array_equal(expected, self.scorecard["validation_pass"])
        self.assertEqual(int(expected.sum()), self.frozen["edge_count"])

    def test_04_final_test_is_not_evaluated_or_used(self) -> None:
        self.assertFalse(self.summary["final_test_evaluated"])
        self.assertFalse(self.frozen["final_test_evaluated"])
        self.assertFalse(self.summary["candidate_edges_reselected_from_prices"])

    def test_05_report_forbids_causal_interpretation(self) -> None:
        report = (ROOT / "docs/p5_directional_model_report.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不证明贸易联系或因果传播", report)
        self.assertIn("final test 未读取", report)


if __name__ == "__main__":
    unittest.main()
