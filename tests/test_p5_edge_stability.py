import json
import unittest
from pathlib import Path

import pandas as pd

from src.procurement.common import load_flat_yaml


ROOT = Path(__file__).resolve().parents[1]


class P5EdgeStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_flat_yaml(ROOT / "config/p5_propagation_experiment.yaml")
        model_dir = ROOT / cls.config["model_artifact_dir"]
        stability_dir = ROOT / cls.config["stability_artifact_dir"]
        cls.validation = pd.read_parquet(
            model_dir / "validation_candidate_scorecard.parquet"
        )
        cls.scorecard = pd.read_parquet(stability_dir / "stability_scorecard.parquet")
        cls.summary = json.loads((stability_dir / "summary.json").read_text())
        cls.frozen = json.loads((stability_dir / "frozen_edges.json").read_text())

    def test_01_only_validation_selected_edges_are_audited(self):
        selected = set(
            self.validation.loc[self.validation["validation_pass"]]
            .apply(
                lambda row: (
                    int(row["vegetable_id"]),
                    row["source_city_id"],
                    row["target_city_id"],
                ),
                axis=1,
            )
            .tolist()
        )
        audited = set(
            self.scorecard.apply(
                lambda row: (
                    int(row["vegetable_id"]),
                    row["source_city_id"],
                    row["target_city_id"],
                ),
                axis=1,
            ).tolist()
        )
        self.assertEqual(audited, selected)

    def test_02_stability_gate_is_mechanical(self):
        expected = (
            self.scorecard["train_halves_direction_consistent"]
            & self.scorecard["bootstrap_positive_direction_rate"].ge(
                float(self.config["minimum_stability_rate"])
            )
        )
        self.assertTrue(expected.equals(self.scorecard["stability_pass"]))
        self.assertEqual(
            int(expected.sum()), int(self.summary["stability_pass_edges"])
        )

    def test_03_bootstrap_contract_is_frozen(self):
        self.assertTrue(
            self.scorecard["bootstrap_resamples"]
            .eq(int(self.config["bootstrap_resamples"]))
            .all()
        )
        self.assertTrue(
            self.scorecard["bootstrap_block_bins"]
            .eq(int(self.config["bootstrap_block_bins"]))
            .all()
        )
        self.assertTrue(
            self.scorecard["bootstrap_positive_direction_rate"].between(0, 1).all()
        )

    def test_04_weekly_sensitivity_is_complete_but_not_posthoc_gate(self):
        available = self.scorecard["weekly_available"]
        self.assertTrue(
            self.scorecard.loc[available, "weekly_source_coefficient_sum"]
            .notna()
            .all()
        )
        self.assertTrue(
            self.scorecard.loc[~available, "weekly_source_coefficient_sum"]
            .isna()
            .all()
        )
        self.assertTrue(self.scorecard.loc[~available, "frequency_sensitive"].all())
        self.assertTrue(
            self.scorecard.loc[available, "weekly_direction_consistent"]
            .eq(self.scorecard.loc[available, "weekly_source_coefficient_sum"].gt(0))
            .all()
        )
        expected_gate = (
            self.scorecard["train_halves_direction_consistent"]
            & self.scorecard["bootstrap_positive_direction_rate"].ge(
                float(self.config["minimum_stability_rate"])
            )
        )
        self.assertTrue(expected_gate.equals(self.scorecard["stability_pass"]))

    def test_05_final_test_remains_sealed(self):
        self.assertFalse(self.summary["final_test_evaluated"])
        self.assertFalse(self.summary["candidate_edges_reselected"])
        self.assertFalse(self.frozen["final_test_evaluated"])
        self.assertFalse(self.frozen["thresholds_reselected"])
        self.assertEqual(
            self.frozen["edge_count"], int(self.scorecard["stability_pass"].sum())
        )


if __name__ == "__main__":
    unittest.main()
