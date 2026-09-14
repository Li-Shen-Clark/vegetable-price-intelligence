from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class P5PropagationMartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_flat_yaml(ROOT / "config/p5_propagation_experiment.yaml")
        cls.output_dir = ROOT / cls.config["propagation_mart_dir"]
        cls.manifest = json.loads(
            (cls.output_dir / "manifest.json").read_text(encoding="utf-8")
        )
        cls.primary = pd.read_parquet(cls.output_dir / "primary_panel.parquet")
        cls.weekly = pd.read_parquet(cls.output_dir / "weekly_panel.parquet")
        cls.edges = pd.read_parquet(cls.output_dir / "candidate_edges.parquet")
        cls.eligible = pd.read_parquet(cls.output_dir / "eligible_series.parquet")

    def test_01_manifest_hashes_and_method_flags(self) -> None:
        self.assertEqual(self.manifest["status"], "frozen")
        self.assertTrue(self.manifest["method_flags"]["seasonality_fit_on_train_only"])
        self.assertTrue(self.manifest["method_flags"]["shock_threshold_fit_on_train_only"])
        self.assertTrue(self.manifest["method_flags"]["common_factor_leave_one_out"])
        self.assertFalse(self.manifest["method_flags"]["directional_models_fitted"])
        for name, item in self.manifest["files"].items():
            path = self.output_dir / f"{name}.parquet"
            self.assertEqual(sha256(path), item["sha256"])

    def test_02_panel_keys_prices_and_frequency_contract(self) -> None:
        for frame, frequency, minimum_days in [
            (self.primary, "3D", 2),
            (self.weekly, "W-MON", 4),
        ]:
            self.assertFalse(
                frame.duplicated(["vegetable_id", "city_id", "bin_start"]).any()
            )
            self.assertTrue(frame["analysis_price"].gt(0).all())
            self.assertTrue(frame["observed_days"].ge(minimum_days).all())
            self.assertEqual(set(frame["frequency"]), {frequency})
            self.assertEqual(set(frame["split"]), {"train", "validation", "final_test"})

    def test_03_thresholds_are_frozen_from_train_only(self) -> None:
        quantile = float(self.config["shock_quantile"])
        for _, group in self.primary.groupby(["vegetable_id", "city_id"], observed=True):
            self.assertEqual(group["train_shock_threshold"].nunique(dropna=True), 1)
            train = group.loc[
                group["split"].eq("train") & group["propagation_residual"].notna(),
                "propagation_residual",
            ]
            expected = float(train.quantile(quantile))
            actual = float(group["train_shock_threshold"].dropna().iloc[0])
            self.assertAlmostEqual(actual, expected, places=12)

    def test_04_leave_one_out_common_factor_is_exact(self) -> None:
        groups = self.primary.loc[
            self.primary["seasonally_adjusted_return"].notna()
            & self.primary["common_factor_loo"].notna()
        ].groupby(["vegetable_id", "bin_start"], observed=True)
        _, sample = next((key, group) for key, group in groups if len(group) >= 11)
        values = sample["seasonally_adjusted_return"].to_numpy(float)
        actual = sample["common_factor_loo"].to_numpy(float)
        for index in range(min(5, len(sample))):
            expected = float(np.median(np.delete(values, index)))
            self.assertAlmostEqual(actual[index], expected, places=12)
            self.assertEqual(sample.iloc[index]["common_factor_peer_count"], len(sample) - 1)

    def test_05_candidate_edges_are_unique_sparse_and_non_self(self) -> None:
        self.assertFalse(
            self.edges.duplicated(
                ["vegetable_id", "source_city_id", "target_city_id"]
            ).any()
        )
        self.assertFalse(self.edges["source_city_id"].eq(self.edges["target_city_id"]).any())
        city_counts = self.eligible.groupby("vegetable_id")["city_id"].nunique()
        for vegetable_id, group in self.edges.groupby("vegetable_id"):
            n = int(city_counts.loc[vegetable_id])
            self.assertLessEqual(len(group) / (n * (n - 1)), 0.35)
            self.assertTrue(group.groupby("target_city_id").size().between(5, 8).all())

    def test_06_outputs_remain_local_only(self) -> None:
        self.assertTrue(str(self.output_dir.relative_to(ROOT)).startswith("data/"))
        self.assertTrue(self.manifest["method_flags"]["final_test_used_for_selection"] is False)


if __name__ == "__main__":
    unittest.main()
