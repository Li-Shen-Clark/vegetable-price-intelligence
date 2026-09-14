from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.procurement.common import load_flat_yaml
from src.propagation.audit_p5_feasibility import validate_config


ROOT = Path(__file__).resolve().parents[1]


class P5ExperimentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p5_propagation_experiment.yaml")
        cls.audit = json.loads(
            (ROOT / cls.config["audit_json_path"]).read_text(encoding="utf-8")
        )

    def test_01_config_freezes_scope_frequency_and_splits(self) -> None:
        validate_config(self.config)
        self.assertEqual(self.config["official_tiers"], ["A"])
        self.assertEqual(self.config["primary_frequency"], "3D")
        self.assertEqual(self.config["robustness_frequency"], "W-MON")
        self.assertEqual(self.config["primary_lags_bins"], [1, 2, 3, 4])
        self.assertEqual(self.config["weekly_lags_bins"], [1, 2])

    def test_02_candidate_set_is_sparse_and_geography_only(self) -> None:
        self.assertTrue(self.audit["checks"]["candidate_density_capped"])
        self.assertTrue(self.audit["checks"]["candidate_sources_bounded"])
        self.assertFalse(
            self.audit["method_flags"]["candidate_edges_selected_from_prices"]
        )
        for row in self.audit["products"]:
            self.assertLessEqual(row["candidate_pair_share"], 0.35)
            self.assertGreaterEqual(row["minimum_sources_per_target"], 5)
            self.assertLessEqual(row["maximum_sources_per_target"], 8)

    def test_03_all_products_have_city_and_shock_support(self) -> None:
        self.assertEqual(len(self.audit["products"]), 10)
        self.assertTrue(self.audit["checks"]["minimum_eligible_cities"])
        self.assertTrue(self.audit["checks"]["train_shock_support"])
        self.assertTrue(self.audit["checks"]["validation_shock_support"])
        self.assertTrue(self.audit["checks"]["final_test_support_only"])

    def test_04_t0_does_not_fit_edges_or_consume_final_test(self) -> None:
        self.assertFalse(self.audit["method_flags"]["directional_models_fitted"])
        self.assertFalse(self.audit["method_flags"]["fdr_tests_run"])
        self.assertFalse(self.audit["method_flags"]["final_test_used_for_selection"])
        self.assertFalse(self.config["final_test_consumed"])

    def test_05_protocol_preserves_economic_and_causal_boundary(self) -> None:
        protocol = (ROOT / self.config["protocol_markdown_path"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("leave-one-out 全国共同因子", protocol)
        self.assertIn("不能声称因果贸易流", protocol)
        self.assertIn("不生成零售价或执行调价", protocol)


if __name__ == "__main__":
    unittest.main()
