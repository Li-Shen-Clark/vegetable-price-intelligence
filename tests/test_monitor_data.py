from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "web/public/data"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MonitorDataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = load_json(DATA_DIR / "metadata.json")
        cls.manifest = load_json(DATA_DIR / "manifest.json")

    def test_01_manifest_and_source_contract(self) -> None:
        self.assertEqual(self.manifest["schema_version"], "monitor_mart_v0.1")
        self.assertEqual(self.manifest["product_count"], 30)
        self.assertEqual(self.manifest["city_count"], 117)
        self.assertEqual(self.manifest["city_day_source_row_count"], 7_358_606)
        self.assertEqual(
            sha256(DATA_DIR / "metadata.json"), self.manifest["metadata_sha256"]
        )
        self.assertEqual(
            self.metadata["source_artifacts"]["city_gold"]["sha256"],
            sha256(ROOT / "data/gold/fact_city_price.parquet"),
        )
        self.assertEqual(
            self.metadata["source_artifacts"]["coverage_tiers"]["sha256"],
            sha256(ROOT / "data/gold/coverage_tiers.parquet"),
        )

    def test_02_metadata_scope_and_defaults(self) -> None:
        self.assertTrue(self.metadata["historical_only"])
        self.assertEqual(self.metadata["data_period"]["end"], "2022-06-22")
        self.assertEqual(self.metadata["data_period"]["last_complete_month"], "2022-05")
        self.assertEqual(self.metadata["data_period"]["granularity"], "month")
        self.assertEqual(self.metadata["data_period"]["price_unit"], "CNY/kg")
        self.assertEqual(self.metadata["ranking_policy"]["eligible_tiers"], ["A", "B"])
        self.assertEqual(self.metadata["ranking_policy"]["minimum_valid_days_in_month"], 15)
        self.assertEqual(len(self.metadata["products"]), 30)
        self.assertEqual(len(self.metadata["cities"]), 117)
        self.assertEqual(len({row["vegetable_id"] for row in self.metadata["products"]}), 30)
        self.assertEqual(len({row["city_id"] for row in self.metadata["cities"]}), 117)

    def test_03_product_files_hashes_records_and_profiles(self) -> None:
        total_records = 0
        expected_city_ids = {row["city_id"] for row in self.metadata["cities"]}
        default_seen = False
        for entry in self.manifest["products"]:
            path = DATA_DIR / entry["file"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(sha256(path), entry["sha256"])
            self.assertEqual(path.stat().st_size, entry["bytes"])
            payload = load_json(path)
            self.assertEqual(payload["schema_version"], self.manifest["schema_version"])
            self.assertEqual(payload["record_fields"][0:2], ["city_id", "month"])
            self.assertEqual(len(payload["city_profiles"]), 117)
            self.assertEqual({row[0] for row in payload["city_profiles"]}, expected_city_ids)
            self.assertEqual(len(payload["records"]), entry["monthly_record_count"])
            keys = [(row[0], row[1]) for row in payload["records"]]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(len(keys), len(set(keys)))
            for record in payload["records"]:
                self.assertEqual(len(record), len(payload["record_fields"]))
                self.assertGreater(record[2], 0)
                self.assertLessEqual(record[3], record[2])
                self.assertLessEqual(record[2], record[4])
                self.assertEqual(record[5], record[9] + record[10] + record[11])
                self.assertGreaterEqual(record[8], 0)
                self.assertLessEqual(record[8], 1)
            if entry["vegetable_id"] == self.metadata["defaults"]["vegetable_id"]:
                default_city_id = self.metadata["defaults"]["city_id"]
                profiles = {row[0]: row for row in payload["city_profiles"]}
                profile = profiles[default_city_id]
                self.assertIn(profile[1], self.metadata["ranking_policy"]["eligible_tiers"])
                self.assertTrue(profile[2])
                default_seen = True
            total_records += len(payload["records"])
        self.assertTrue(default_seen)
        self.assertEqual(total_records, self.manifest["monthly_record_count"])

    def test_04_default_month_recomputes_from_gold(self) -> None:
        vegetable_id = int(self.metadata["defaults"]["vegetable_id"])
        city_id = self.metadata["defaults"]["city_id"]
        month = self.metadata["defaults"]["month"]
        product_payload = load_json(DATA_DIR / f"products/{vegetable_id}.json")
        fields = product_payload["record_fields"]
        record = next(
            row
            for row in product_payload["records"]
            if row[0] == city_id and row[1] == month
        )
        observed = dict(zip(fields, record))

        parquet = pq.ParquetFile(ROOT / "data/gold/fact_city_price.parquet")
        target = None
        for group_index in range(parquet.metadata.num_row_groups):
            ids = parquet.read_row_group(group_index, columns=["vegetable_id"])[
                "vegetable_id"
            ].unique().to_pylist()
            if ids == [vegetable_id]:
                target = parquet.read_row_group(
                    group_index,
                    columns=[
                        "date",
                        "city_id",
                        "analysis_price",
                        "number_of_reporting_markets",
                        "source_record_count",
                        "source_reliability_score",
                        "data_quality_flag",
                    ],
                ).to_pandas()
                break
        self.assertIsNotNone(target)
        target["month"] = pd.to_datetime(target["date"]).dt.to_period("M").astype(str)
        sample = target.loc[target["city_id"].eq(city_id) & target["month"].eq(month)]
        self.assertEqual(observed["valid_day_count"], len(sample))
        self.assertAlmostEqual(observed["median_price"], float(sample["analysis_price"].median()), 3)
        self.assertAlmostEqual(
            observed["p25_price"], float(sample["analysis_price"].quantile(0.25)), 3
        )
        self.assertAlmostEqual(
            observed["p75_price"], float(sample["analysis_price"].quantile(0.75)), 3
        )
        self.assertAlmostEqual(
            observed["mean_source_reliability_score"],
            float(sample["source_reliability_score"].mean()),
            4,
        )
        self.assertEqual(observed["source_record_count"], int(sample["source_record_count"].sum()))
        self.assertTrue(np.isfinite(sample["analysis_price"]).all())


if __name__ == "__main__":
    unittest.main()
