from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from src.procurement.audit_p4_feasibility import validate_config
from src.procurement.build_city_geo import validate_geo
from src.procurement.common import load_flat_yaml


ROOT = Path(__file__).resolve().parents[1]


class P4ExperimentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p4_procurement.yaml")
        cls.dim_city = pd.read_csv(ROOT / "reference/dim_city.csv")
        cls.geo = pd.read_csv(ROOT / "reference/dim_city_geo.csv")
        cls.audit = json.loads(
            (ROOT / "docs/p4_feasibility_audit.json").read_text(encoding="utf-8")
        )

    def test_01_config_freezes_scope_and_sensitivity(self) -> None:
        validate_config(self.config)
        self.assertEqual(self.config["horizons_days"], [7, 14, 28])
        self.assertEqual(self.config["default_horizon_days"], 28)
        self.assertEqual(
            len(self.config["sensitivity_transport_costs"])
            * len(self.config["sensitivity_loss_rates"])
            * len(self.config["sensitivity_risk_aversions"]),
            36,
        )

    def test_02_city_geo_is_one_to_one_and_complete(self) -> None:
        validate_geo(self.geo, self.dim_city)
        self.assertEqual(len(self.geo), 117)
        self.assertEqual(
            self.geo["coordinate_method"].value_counts().to_dict(),
            {"city_center_snapshot": 116, "verified_market_exception": 1},
        )

    def test_03_dali_exception_is_explicit(self) -> None:
        row = self.geo.loc[self.geo["city_name_zh"].eq("大理州弥渡县")].iloc[0]
        self.assertEqual(row["coordinate_method"], "verified_market_exception")
        self.assertIn("mk115", row["coordinate_source"])
        self.assertTrue(bool(row["alias_rule"]))

    def test_04_feasibility_audit_passes_without_rewriting_p2(self) -> None:
        self.assertEqual(self.audit["status"], "pass")
        self.assertTrue(all(self.audit["checks"].values()))
        self.assertEqual(
            self.audit["release_matrix"],
            {
                "model_target": 1,
                "model_minimum": 3,
                "point_only_model": 16,
                "baseline_fallback": 10,
            },
        )

    def test_05_protocol_preserves_product_boundary(self) -> None:
        text = (ROOT / "docs/p4_procurement_protocol.md").read_text(encoding="utf-8")
        self.assertIn("基线回退不得称为模型预测", text)
        self.assertIn("target_date < scenario_origin_date", text)
        self.assertIn("不生成采购订单或自动报价", text)


if __name__ == "__main__":
    unittest.main()
