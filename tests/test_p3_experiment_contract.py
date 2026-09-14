from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.alerts.audit_p3_feasibility import (
    load_flat_yaml,
    load_scope_products,
    validate_config,
    weekly_origins,
)


ROOT = Path(__file__).resolve().parents[1]


class P3ExperimentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p3_alert_experiment.yaml")
        cls.audit = json.loads(
            (ROOT / "docs/p3_feasibility_audit.json").read_text(encoding="utf-8")
        )

    def test_01_primary_event_contract_is_frozen(self) -> None:
        validate_config(self.config)
        products = load_scope_products(ROOT / self.config["scope_config_path"])
        self.assertEqual(len(products), 10)
        self.assertEqual(self.config["absolute_spike_threshold"], 0.20)
        self.assertEqual(self.config["seasonal_quantile"], 0.90)
        self.assertEqual(self.config["event_deduplication_days"], 21)

    def test_02_weekly_origins_are_mondays_and_leave_target_room(self) -> None:
        for split in ["train", "validation", "final_test"]:
            origins = weekly_origins(
                self.config[f"{split}_origin_start"],
                self.config[f"{split}_origin_end"],
                self.config["origin_frequency"],
            )
            self.assertTrue(origins)
            self.assertTrue(all(item.dayofweek == 0 for item in origins))
            self.assertLessEqual(
                origins[-1] + __import__("pandas").Timedelta(days=14),
                __import__("pandas").Timestamp(self.config[f"{split}_end"]),
            )

    def test_03_feasibility_gate_has_all_products(self) -> None:
        self.assertEqual(self.audit["status"], "pass")
        self.assertEqual(len(self.audit["products"]), 10)
        self.assertEqual(self.audit["gate_summary"]["official_product_split_checks"], 20)
        self.assertEqual(self.audit["gate_summary"]["failed_eligibility_checks"], 0)

    def test_04_protocol_separates_audit_from_model_claims(self) -> None:
        protocol = (ROOT / "docs/p3_alert_experiment_protocol.md").read_text(encoding="utf-8")
        self.assertIn("上游决策情报层", protocol)
        self.assertIn("不生成最终报价", protocol)
        self.assertIn("FPR 不超过 10%", protocol)
        self.assertIn("不是正式事件率", protocol)


if __name__ == "__main__":
    unittest.main()
