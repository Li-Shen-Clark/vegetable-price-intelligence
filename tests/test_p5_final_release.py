import json
import unittest
from pathlib import Path

import pandas as pd

from src.procurement.common import load_flat_yaml


ROOT = Path(__file__).resolve().parents[1]


class P5FinalReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_flat_yaml(ROOT / "config/p5_propagation_experiment.yaml")
        final_dir = ROOT / cls.config["final_artifact_dir"]
        cls.payload = json.loads((final_dir / "release_decision.json").read_text())
        cls.scorecard = pd.read_parquet(final_dir / "final_scorecard.parquet")
        cls.decision = cls.payload["release_decision"]

    def test_01_final_is_a_single_sealed_evaluation(self):
        self.assertTrue(self.config["final_test_consumed"])
        self.assertTrue(self.payload["final_test_first_and_only_evaluation"])
        self.assertTrue(self.payload["final_test_evaluated"])
        self.assertFalse(self.payload["threshold_reselected_on_final_test"])
        self.assertFalse(self.payload["candidate_edges_reselected_on_final_test"])
        self.assertFalse(self.payload["model_refit_on_final_test"])
        self.assertTrue(self.payload["model_refit_before_final_test"])

    def test_02_edge_labels_follow_frozen_thresholds(self):
        confirmed = self.scorecard["final_rmse_improvement"].gt(
            float(self.config["final_minimum_positive_rmse_improvement"])
        )
        strong = self.scorecard["final_rmse_improvement"].ge(
            float(self.config["strong_edge_minimum_rmse_improvement"])
        )
        self.assertTrue(confirmed.equals(self.scorecard["final_confirmed"]))
        self.assertTrue(strong.equals(self.scorecard["final_strong_edge"]))

    def test_03_release_decision_is_mechanically_reproducible(self):
        gate_results = [gate["pass"] for gate in self.decision["gates"].values()]
        expected = "network_release" if all(gate_results) else "common_shock_only"
        self.assertEqual(self.decision["release_status"], expected)
        self.assertEqual(
            self.decision["final_confirmed_edges"],
            int(self.scorecard["final_confirmed"].sum()),
        )
        self.assertAlmostEqual(
            self.decision["positive_final_edge_share"],
            float(self.scorecard["final_confirmed"].mean()),
        )
        self.assertAlmostEqual(
            self.decision["median_final_rmse_improvement"],
            float(self.scorecard["final_rmse_improvement"].median()),
        )

    def test_04_all_scored_edges_were_fdr_and_stability_frozen(self):
        self.assertTrue(self.scorecard["fdr_reject"].all())
        self.assertTrue(self.scorecard["validation_pass"].all())
        self.assertTrue(self.scorecard["stability_pass"].all())
        self.assertTrue(self.scorecard["final_test_eligible"].all())

    def test_05_model_card_enforces_noncausal_product_boundary(self):
        text = (ROOT / "docs/p5_model_card.md").read_text(encoding="utf-8")
        self.assertIn("不能证明城市间贸易流", text)
        self.assertIn("不能自动调价", text)
        self.assertIn(self.decision["release_status"], text)


if __name__ == "__main__":
    unittest.main()
