from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MART_DIR = ROOT / "data/modeling/p2_forecast_mart"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class P2ForecastMartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((MART_DIR / "manifest.json").read_text(encoding="utf-8"))
        cls.frames = {
            split: pd.read_parquet(MART_DIR / f"{split}.parquet")
            for split in ["train", "validation", "final_test"]
        }

    def test_01_split_hashes_counts_and_primary_keys(self) -> None:
        expected_counts = {"validation": 11882, "final_test": 16217}
        keys = self.manifest["key_columns"]
        for split, frame in self.frames.items():
            metadata = self.manifest["splits"][split]
            self.assertEqual(len(frame), metadata["row_count"])
            self.assertEqual(sha256(MART_DIR / f"{split}.parquet"), metadata["sha256"])
            self.assertFalse(frame.duplicated(keys).any())
            self.assertEqual(set(frame["split"]), {split})
            if split in expected_counts:
                self.assertEqual(len(frame), expected_counts[split])

    def test_02_dates_targets_and_origin_fill_obey_contract(self) -> None:
        boundaries = {
            "train": ("2016-01-01", "2019-12-01"),
            "validation": ("2020-01-01", "2020-12-01"),
            "final_test": ("2021-01-01", "2022-05-01"),
        }
        for split, frame in self.frames.items():
            origin = pd.to_datetime(frame["origin_date"])
            target = pd.to_datetime(frame["target_date"])
            price_date = pd.to_datetime(frame["origin_price_date"])
            expected_start, expected_end = boundaries[split]
            self.assertEqual(origin.min().date().isoformat(), expected_start)
            self.assertEqual(origin.max().date().isoformat(), expected_end)
            np.testing.assert_array_equal((target - origin).dt.days, frame["horizon_days"])
            np.testing.assert_array_equal((origin - price_date).dt.days, frame["origin_fill_days"])
            self.assertTrue(frame["origin_fill_days"].isin([0, 1]).all())
            self.assertTrue(frame["origin_price"].gt(0).all())
            self.assertTrue(frame["target_price"].gt(0).all())
            self.assertTrue(frame["history_observation_count"].ge(365).all())

    def test_03_feature_list_excludes_targets_and_future_values(self) -> None:
        features = set(self.manifest["feature_columns"])
        self.assertTrue(features)
        self.assertTrue(features.isdisjoint(self.manifest["target_columns"]))
        forbidden = {
            "target_price",
            "log_target_price",
            "target_price_change",
            "target_log_return",
            "target_direction",
        }
        self.assertTrue(features.isdisjoint(forbidden))
        self.assertIn("origin_price", features)
        self.assertIn("historical_seasonal_median", features)
        self.assertIn("weekly_pattern_median", features)

    def test_04_sample_rolling_feature_recomputes_from_gold_cutoff(self) -> None:
        row = self.frames["validation"].iloc[0]
        gold = pd.read_parquet(
            ROOT / "data/gold/fact_city_price.parquet",
            columns=["date", "vegetable_id", "city_id", "analysis_price", "data_quality_flag"],
            filters=[
                ("vegetable_id", "=", int(row["vegetable_id"])),
                ("city_id", "=", str(row["city_id"])),
            ],
        )
        gold["date"] = pd.to_datetime(gold["date"])
        origin = pd.Timestamp(row["origin_date"])
        eligible = gold[
            gold["analysis_price"].gt(0)
            & gold["data_quality_flag"].ne("poor")
            & gold["date"].between(origin - pd.Timedelta(days=27), origin)
        ]
        self.assertEqual(int(row["rolling_count_28d"]), len(eligible))
        self.assertAlmostEqual(float(row["rolling_mean_28d"]), float(eligible["analysis_price"].mean()), 12)


if __name__ == "__main__":
    unittest.main()
