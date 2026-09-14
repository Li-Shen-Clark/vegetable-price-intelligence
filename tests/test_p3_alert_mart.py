from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MART = ROOT / "data/modeling/p3_alert_mart"


class P3AlertMartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((MART / "manifest.json").read_text(encoding="utf-8"))
        cls.train = pd.read_parquet(MART / "train.parquet")
        cls.validation = pd.read_parquet(MART / "validation.parquet")

    def test_01_keys_splits_and_manifest_match(self) -> None:
        keys = ["vegetable_id", "city_id", "origin_date"]
        self.assertFalse(self.train.duplicated(keys).any())
        self.assertFalse(self.validation.duplicated(keys).any())
        self.assertEqual(len(self.train), self.manifest["splits"]["train"]["rows"])
        self.assertEqual(len(self.validation), self.manifest["splits"]["validation"]["rows"])
        self.assertEqual(set(self.train["split"]), {"train"})
        self.assertEqual(set(self.validation["split"]), {"validation"})

    def test_02_threshold_history_is_available_at_origin(self) -> None:
        for frame in [self.train, self.validation]:
            self.assertTrue(frame["seasonal_threshold_q90"].notna().all())
            self.assertTrue(frame["seasonal_threshold_history_count"].gt(0).all())
            latest = pd.to_datetime(frame["seasonal_history_latest_window_end"])
            origin = pd.to_datetime(frame["origin_date"])
            self.assertTrue(latest.le(origin).all())

    def test_03_primary_label_matches_rule_and_deduplication(self) -> None:
        combined = pd.concat([self.train, self.validation], ignore_index=True)
        expected_raw = (
            combined["future_peak_return_14d"].ge(0.20)
            & combined["future_peak_return_14d"].ge(combined["seasonal_threshold_q90"])
        )
        self.assertTrue(expected_raw.eq(combined["primary_raw_event"]).all())
        self.assertTrue(combined.loc[combined["event_label"], "primary_raw_event"].all())
        events = combined[combined["event_label"]].sort_values(["vegetable_id", "city_id", "origin_date"])
        events = events.assign(origin_date=pd.to_datetime(events["origin_date"]))
        gaps = events.groupby(["vegetable_id", "city_id"])["origin_date"].diff().dt.days.dropna()
        self.assertTrue(gaps.gt(21).all())

    def test_04_lead_time_and_target_quality_contract(self) -> None:
        for frame in [self.train, self.validation]:
            events = frame[frame["event_label"]]
            self.assertTrue(events["event_lead_days"].between(1, 14).all())
            self.assertTrue(frame["future_observation_count"].ge(10).all())
            self.assertTrue(frame["origin_fill_days"].between(0, 1).all())
            self.assertTrue(
                (pd.to_datetime(frame["target_window_end"]) - pd.to_datetime(frame["origin_date"]))
                .dt.days.eq(14).all()
            )

    def test_05_model_inputs_are_explicitly_separable_from_targets(self) -> None:
        forbidden_prefixes = ("future_", "target_", "seasonal_threshold_", "raw_event_", "event_label")
        feature_candidates = [
            column
            for column in self.train.columns
            if column.startswith(("return_", "rolling_", "historical_event_rate_", "origin_"))
            and not column.startswith(forbidden_prefixes)
        ]
        self.assertGreater(len(feature_candidates), 20)
        self.assertTrue(self.manifest["final_test_label_summary_withheld_until_t4"])


if __name__ == "__main__":
    unittest.main()
