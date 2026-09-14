from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src.procurement.common import haversine_km, load_flat_yaml
from src.procurement.engine import (
    ScenarioParameters,
    calculate_cost_rows,
    default_parameters,
    rank_sources,
)


ROOT = Path(__file__).resolve().parents[1]


class P4ProcurementEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p4_procurement.yaml")
        cls.snapshot = pd.read_parquet(
            ROOT / cls.config["procurement_mart_dir"] / "scenario_snapshot.parquet"
        )
        cls.geo = pd.read_csv(ROOT / cls.config["city_geo_path"])
        cls.parameters = default_parameters(cls.config)
        cls.artifact = json.loads(
            (ROOT / "artifacts/p4/default_scenarios.json").read_text(encoding="utf-8")
        )

    def test_01_haversine_matches_known_geometry(self) -> None:
        self.assertAlmostEqual(haversine_km(0, 0, 0, 0), 0.0, places=9)
        self.assertAlmostEqual(haversine_km(0, 0, 0, 1), 111.195, places=3)

    def test_02_cost_formula_matches_hand_calculation(self) -> None:
        row = pd.DataFrame(
            {
                "latitude": [0.0],
                "longitude": [0.0],
                "origin_source_reliability_score": [0.8],
                "base_uncertainty_per_kg": [1.0],
                "released_point_prediction": [4.0],
            }
        )
        params = ScenarioParameters(100, 0.01, 0.10, 500, 1.0, 0.5, 0.0)
        result = calculate_cost_rows(row, 0.0, 0.0, params).iloc[0]
        self.assertAlmostEqual(result["unit_transport_cost"], 0.0)
        self.assertAlmostEqual(result["reliability_multiplier"], 1.2)
        self.assertAlmostEqual(result["risk_penalty_per_kg"], 0.6)
        self.assertAlmostEqual(result["unit_landed_cost"], 4.6 / 0.9)
        self.assertAlmostEqual(result["total_landed_cost"], 100 * 4.6 / 0.9)

    def test_03_default_scenarios_have_local_and_three_external_options(self) -> None:
        self.assertEqual(self.artifact["scenario_count"], 10)
        for scenario in self.artifact["scenarios"]:
            self.assertEqual(scenario["status"], "ok")
            self.assertIsNotNone(scenario["local_benchmark"])
            self.assertEqual(len(scenario["candidates"]), 3)
            costs = [item["unit_landed_cost"] for item in scenario["candidates"]]
            self.assertEqual(costs, sorted(costs))
            self.assertTrue(
                all(item["city_id"] != scenario["target_city"]["city_id"] for item in scenario["candidates"])
            )

    def test_04_quantity_changes_total_not_unit_ranking(self) -> None:
        base = rank_sources(self.snapshot, self.geo, "city_008", 170060, 28, self.parameters)
        larger = rank_sources(
            self.snapshot,
            self.geo,
            "city_008",
            170060,
            28,
            replace(self.parameters, quantity_kg=self.parameters.quantity_kg * 2),
        )
        self.assertEqual(
            [item["city_id"] for item in base["candidates"]],
            [item["city_id"] for item in larger["candidates"]],
        )
        for left, right in zip(base["candidates"], larger["candidates"]):
            self.assertAlmostEqual(left["unit_landed_cost"], right["unit_landed_cost"])
            self.assertAlmostEqual(left["total_landed_cost"] * 2, right["total_landed_cost"])

    def test_05_filters_and_no_candidate_state_are_explicit(self) -> None:
        result = rank_sources(
            self.snapshot,
            self.geo,
            "city_008",
            170060,
            28,
            replace(self.parameters, max_distance_km=1.0, minimum_reliability=1.0),
        )
        self.assertEqual(result["status"], "no_candidates")
        self.assertEqual(result["candidates"], [])

    def test_06_invalid_parameters_fail_instead_of_returning_zero_cost(self) -> None:
        with self.assertRaises(ValueError):
            replace(self.parameters, loss_rate=1.0).validate()
        with self.assertRaises(ValueError):
            replace(self.parameters, quantity_kg=0).validate()

    def test_07_baseline_route_copy_remains_visible(self) -> None:
        result = rank_sources(self.snapshot, self.geo, "city_008", 170130, 28, self.parameters)
        labels = [result["local_benchmark"]["price_input_label"]] + [
            item["price_input_label"] for item in result["candidates"]
        ]
        self.assertTrue(all("不是模型预测" in label for label in labels))
        self.assertTrue(all("历史季节" in label for label in labels))


if __name__ == "__main__":
    unittest.main()
