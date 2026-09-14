from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.forecast.audit_p2_feasibility import (
    load_flat_yaml,
    load_scope_products,
    monthly_origins,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[1]


class P2ExperimentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p2_experiment.yaml")
        cls.audit = json.loads(
            (ROOT / "docs/p2_feasibility_audit.json").read_text(encoding="utf-8")
        )

    def test_01_config_and_scope_are_frozen(self) -> None:
        validate_config(self.config)
        products = load_scope_products(ROOT / self.config["scope_config_path"])
        self.assertEqual(len(products), 10)
        self.assertEqual(self.config["official_tiers"], ["A"])
        self.assertEqual(self.config["shadow_tiers"], ["B"])
        self.assertEqual(self.config["horizons_days"], [7, 14, 28])

    def test_02_rolling_origins_match_protocol(self) -> None:
        validation = monthly_origins(
            self.config["validation_origin_start"],
            self.config["validation_origin_end"],
            self.config["origin_frequency"],
        )
        final_test = monthly_origins(
            self.config["final_test_origin_start"],
            self.config["final_test_origin_end"],
            self.config["origin_frequency"],
        )
        self.assertEqual(len(validation), 12)
        self.assertEqual(len(final_test), 17)
        self.assertEqual(validation[0].date().isoformat(), "2020-01-01")
        self.assertEqual(final_test[-1].date().isoformat(), "2022-05-01")

    def test_03_feasibility_audit_passes_all_product_split_horizon_gates(self) -> None:
        self.assertEqual(self.audit["status"], "pass")
        self.assertEqual(len(self.audit["products"]), 10)
        self.assertEqual(self.audit["gate_summary"]["checks"], 60)
        self.assertEqual(self.audit["gate_summary"]["failed"], 0)
        for product in self.audit["products"]:
            self.assertGreaterEqual(product["official_series_count"], 5)
            for split in ["validation", "final_test"]:
                for result in product["evaluation"][split]:
                    self.assertTrue(result["passes_minimum_origins"])

    def test_04_protocol_preserves_test_and_product_boundaries(self) -> None:
        protocol = (ROOT / "docs/p2_experiment_protocol.md").read_text(encoding="utf-8")
        self.assertIn("上游决策情报层", protocol)
        self.assertIn("不生成最终报价", protocol)
        self.assertIn("目标日必须恰好存在", protocol)
        self.assertIn("不能用于选择算法", protocol)
        self.assertIn("paired rows", protocol)
        self.assertIn("回退到最佳简单基线", protocol)


if __name__ == "__main__":
    unittest.main()
