from __future__ import annotations

import ast
import csv
import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROWS = 8_682_381


def load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def sha256(relative_path: str) -> str:
    digest = hashlib.sha256()
    with (ROOT / relative_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(relative_path: str) -> list[dict[str, str]]:
    with (ROOT / relative_path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_flat_config(relative_path: str) -> dict:
    result = {}
    for raw_line in (ROOT / relative_path).read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        key, value = raw_line.split(":", 1)
        value = value.strip()
        try:
            result[key.strip()] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            result[key.strip()] = value
    return result


class DataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifests = {
            "bronze": load_json("data/bronze/fact_market_price_raw.manifest.json"),
            "mapped": load_json("data/silver/fact_market_price_mapped.manifest.json"),
            "quality": load_json("data/silver/fact_market_price_quality.manifest.json"),
            "market": load_json("data/gold/fact_market_price.manifest.json"),
            "city": load_json("data/gold/fact_city_price.manifest.json"),
            "tiers": load_json("data/gold/coverage_tiers.manifest.json"),
        }
        cls.parquet_paths = {
            "bronze": "data/bronze/fact_market_price_raw.parquet",
            "mapped": "data/silver/fact_market_price_mapped.parquet",
            "quality": "data/silver/fact_market_price_quality.parquet",
            "market": "data/gold/fact_market_price.parquet",
            "city": "data/gold/fact_city_price.parquet",
            "tiers": "data/gold/coverage_tiers.parquet",
        }

    def test_01_artifact_hashes_match_manifests(self) -> None:
        for name, relative_path in self.parquet_paths.items():
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)
            self.assertEqual(sha256(relative_path), self.manifests[name]["parquet_sha256"])
        self.assertEqual(
            self.manifests["quality"]["parquet_sha256"],
            self.manifests["market"]["parquet_sha256"],
        )
        self.assertTrue(self.manifests["market"]["byte_identical_to_quality_silver"])
        self.assertEqual(
            sha256("docs/coverage_tier_summary.md"),
            self.manifests["tiers"]["summary_sha256"],
        )

    def test_02_bronze_rows_dates_products_and_trace_keys(self) -> None:
        parquet = pq.ParquetFile(ROOT / self.parquet_paths["bronze"])
        manifest = self.manifests["bronze"]
        self.assertEqual(parquet.metadata.num_rows, EXPECTED_ROWS)
        self.assertEqual(parquet.metadata.num_rows, manifest["row_count"])
        self.assertEqual(parquet.metadata.num_columns, manifest["column_count"])
        self.assertEqual(parquet.metadata.num_row_groups, manifest["parquet_row_group_count"])
        source_files = set()
        product_ids = set()
        source_to_product = {}
        last_row_number = {}
        minimum_date = None
        maximum_date = None
        observed_rows = 0
        for batch in parquet.iter_batches(
            columns=["source_file", "source_file_row_number", "vegetable_id", "date"],
            batch_size=250_000,
        ):
            frame = batch.to_pandas()
            for source_file, source_rows in frame.groupby("source_file", sort=False):
                source_file = str(source_file)
                product_values = {int(value) for value in source_rows["vegetable_id"].unique()}
                self.assertEqual(len(product_values), 1)
                product_id = product_values.pop()
                if source_file in source_to_product:
                    self.assertEqual(source_to_product[source_file], product_id)
                else:
                    source_to_product[source_file] = product_id
                row_numbers = source_rows["source_file_row_number"].to_numpy(dtype=np.int64)
                self.assertTrue((np.diff(row_numbers) > 0).all())
                if source_file in last_row_number:
                    self.assertGreater(int(row_numbers[0]), last_row_number[source_file])
                last_row_number[source_file] = int(row_numbers[-1])
                source_files.add(source_file)
                product_ids.add(product_id)
            local_min = frame["date"].min()
            local_max = frame["date"].max()
            minimum_date = local_min if minimum_date is None or local_min < minimum_date else minimum_date
            maximum_date = local_max if maximum_date is None or local_max > maximum_date else maximum_date
            observed_rows += len(frame)
        self.assertEqual(observed_rows, EXPECTED_ROWS)
        self.assertEqual(len(source_files), 30)
        self.assertEqual(len(product_ids), 30)
        self.assertEqual(str(minimum_date), manifest["minimum_date"])
        self.assertEqual(str(maximum_date), manifest["maximum_date"])

    def test_03_silver_row_and_schema_preservation(self) -> None:
        bronze = pq.ParquetFile(ROOT / self.parquet_paths["bronze"])
        mapped = pq.ParquetFile(ROOT / self.parquet_paths["mapped"])
        quality = pq.ParquetFile(ROOT / self.parquet_paths["quality"])
        market = pq.ParquetFile(ROOT / self.parquet_paths["market"])
        for name, parquet in [("mapped", mapped), ("quality", quality), ("market", market)]:
            self.assertEqual(parquet.metadata.num_rows, EXPECTED_ROWS)
            self.assertEqual(
                parquet.metadata.num_row_groups,
                self.manifests[name]["parquet_row_group_count"],
            )
        self.assertEqual(mapped.schema_arrow.names[: len(bronze.schema_arrow)], bronze.schema_arrow.names)
        self.assertEqual(quality.schema_arrow.names[: len(mapped.schema_arrow)], mapped.schema_arrow.names)
        self.assertEqual(market.schema_arrow, quality.schema_arrow)

    def test_04_mapping_and_quality_logic(self) -> None:
        parquet = pq.ParquetFile(ROOT / self.parquet_paths["quality"])
        manifest = self.manifests["quality"]
        status_counts: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        for batch in parquet.iter_batches(
            columns=[
                "observed_price",
                "mapping_status",
                "price_valid_flag",
                "invalid_price_reason",
                "reported_change_consistent_flag",
                "duplicate_market_date_flag",
                "zero_change_flag",
                "zero_change_run_length",
                "stale_quote_flag",
                "outlier_flag",
                "days_since_last_valid_quote",
            ],
            batch_size=250_000,
        ):
            frame = batch.to_pandas()
            price = frame["observed_price"].to_numpy(dtype=float)
            expected_valid = np.isfinite(price) & (price > 0)
            np.testing.assert_array_equal(frame["price_valid_flag"].to_numpy(), expected_valid)
            self.assertTrue(frame.loc[~frame["price_valid_flag"], "invalid_price_reason"].notna().all())
            self.assertTrue(frame.loc[frame["price_valid_flag"], "invalid_price_reason"].isna().all())
            evaluated_change = frame["reported_change_consistent_flag"].dropna()
            self.assertTrue(evaluated_change.astype(bool).all())
            self.assertTrue(
                frame.loc[frame["stale_quote_flag"], "zero_change_flag"].astype(bool).all()
            )
            self.assertTrue(
                frame.loc[frame["stale_quote_flag"], "zero_change_run_length"].ge(7).all()
            )
            self.assertTrue(
                frame.loc[~frame["zero_change_flag"], "zero_change_run_length"].eq(0).all()
            )
            self.assertTrue(
                frame.loc[frame["price_valid_flag"], "days_since_last_valid_quote"].eq(0).all()
            )
            status_counts.update(frame["mapping_status"].value_counts().to_dict())
            totals.update(
                {
                    "invalid_price_rows": int((~frame["price_valid_flag"]).sum()),
                    "change_consistency_evaluable_rows": int(
                        frame["reported_change_consistent_flag"].notna().sum()
                    ),
                    "change_inconsistent_rows": int(
                        frame["reported_change_consistent_flag"].eq(False).sum()
                    ),
                    "duplicate_rows": int(frame["duplicate_market_date_flag"].sum()),
                    "zero_change_rows": int(frame["zero_change_flag"].sum()),
                    "stale_quote_rows": int(frame["stale_quote_flag"].sum()),
                    "outlier_rows": int(frame["outlier_flag"].sum()),
                    "days_since_last_valid_quote_null_rows": int(
                        frame["days_since_last_valid_quote"].isna().sum()
                    ),
                }
            )
        self.assertEqual(set(status_counts), {"mapped_existing_city", "unmapped_new_city"})
        self.assertEqual(sum(status_counts.values()), EXPECTED_ROWS)
        self.assertGreaterEqual(status_counts["mapped_existing_city"] / EXPECTED_ROWS, 0.995)
        self.assertEqual(dict(status_counts), self.manifests["mapped"]["mapping_status_row_counts"])
        self.assertEqual(dict(totals), manifest["summary"])
        eligible = status_counts["mapped_existing_city"] - sum(
            item["excluded_invalid_mapped_rows"] for item in self.manifests["city"]["products"]
        )
        self.assertEqual(eligible, self.manifests["city"]["eligible_source_rows"])

    def test_05_city_fact_primary_key_prices_and_quality(self) -> None:
        parquet = pq.ParquetFile(ROOT / self.parquet_paths["city"])
        manifest = self.manifests["city"]
        config = load_flat_config("config/aggregation.yaml")
        dim_city_ids = {row["city_id"] for row in read_csv("reference/dim_city.csv")}
        self.assertEqual(parquet.metadata.num_rows, manifest["row_count"])
        self.assertEqual(parquet.metadata.num_row_groups, 30)
        observed_city_ids = set()
        source_record_count = 0
        quality_counts: Counter[str] = Counter()
        for group_index in range(parquet.metadata.num_row_groups):
            frame = parquet.read_row_group(group_index).to_pandas()
            self.assertFalse(frame.duplicated(["date", "vegetable_id", "city_id"]).any())
            np.testing.assert_array_equal(
                frame["analysis_price"].to_numpy(), frame["median_price"].to_numpy()
            )
            prices = frame[["analysis_price", "median_price", "trimmed_mean_price"]].to_numpy()
            self.assertTrue(np.isfinite(prices).all())
            self.assertTrue((prices > 0).all())
            self.assertTrue(frame["number_of_reporting_markets"].ge(1).all())
            for column in [
                "stale_quote_share",
                "outlier_share",
                "duplicate_market_share",
                "mean_mapping_confidence_score",
                "source_reliability_score",
            ]:
                self.assertTrue(frame[column].between(0, 1).all(), column)
            expected_quality = np.select(
                [
                    frame["source_reliability_score"]
                    >= float(config["data_quality_good_min_score"]),
                    frame["source_reliability_score"]
                    >= float(config["data_quality_caution_min_score"]),
                ],
                ["good", "caution"],
                default="poor",
            )
            np.testing.assert_array_equal(expected_quality, frame["data_quality_flag"].to_numpy())
            observed_city_ids.update(frame["city_id"].unique())
            source_record_count += int(frame["source_record_count"].sum())
            quality_counts.update(frame["data_quality_flag"].value_counts().to_dict())
        self.assertEqual(observed_city_ids, dim_city_ids)
        self.assertEqual(source_record_count, manifest["eligible_source_rows"])
        self.assertEqual(dict(quality_counts), manifest["quality_flag_counts"])

    def test_06_coverage_tier_cartesian_contract(self) -> None:
        tiers = pq.read_table(ROOT / self.parquet_paths["tiers"]).to_pandas()
        manifest = self.manifests["tiers"]
        vegetable_ids = {int(row["vegetable_id"]) for row in read_csv("reference/dim_vegetable.csv")}
        city_ids = {row["city_id"] for row in read_csv("reference/dim_city.csv")}
        expected_keys = {(vegetable_id, city_id) for vegetable_id in vegetable_ids for city_id in city_ids}
        actual_keys = set(zip(tiers["vegetable_id"], tiers["city_id"]))
        self.assertEqual(len(tiers), 3_510)
        self.assertEqual(actual_keys, expected_keys)
        self.assertEqual(set(tiers["coverage_tier"]), {"A", "B", "C"})
        self.assertTrue(tiers["coverage_score"].between(0, 1).all())
        self.assertTrue(
            tiers["forecast_eligible_flag"].eq(tiers["coverage_tier"].eq("A")).all()
        )
        self.assertTrue(
            tiers["monitor_eligible_flag"].eq(tiers["coverage_tier"].isin(["A", "B"])).all()
        )
        no_data = tiers["valid_day_count"].eq(0)
        self.assertTrue(tiers.loc[no_data, "coverage_tier"].eq("C").all())
        self.assertEqual(int(no_data.sum()), manifest["no_data_combinations"])
        self.assertEqual(
            tiers["coverage_tier"].value_counts().to_dict(), manifest["tier_counts"]
        )
        self.assertTrue(tiers.groupby("vegetable_id").size().eq(117).all())
        self.assertTrue(tiers.groupby("city_id").size().eq(30).all())
        self.assertEqual(int(tiers["valid_day_count"].sum()), self.manifests["city"]["row_count"])

    def test_07_tier_valid_days_reconcile_to_city_fact(self) -> None:
        tiers = pq.read_table(
            ROOT / self.parquet_paths["tiers"],
            columns=["vegetable_id", "city_id", "valid_day_count"],
        ).to_pandas()
        tier_lookup = tiers.set_index(["vegetable_id", "city_id"])["valid_day_count"]
        city_file = pq.ParquetFile(ROOT / self.parquet_paths["city"])
        observed = {}
        for group_index in range(city_file.metadata.num_row_groups):
            frame = city_file.read_row_group(
                group_index, columns=["vegetable_id", "city_id"]
            ).to_pandas()
            product_id = int(frame["vegetable_id"].iat[0])
            for city_id, count in frame["city_id"].value_counts().items():
                observed[(product_id, str(city_id))] = int(count)
        for key, expected_count in tier_lookup.items():
            self.assertEqual(observed.get((int(key[0]), str(key[1])), 0), int(expected_count))

    def test_08_manifest_dimensions_and_product_totals(self) -> None:
        tier_manifest = self.manifests["tiers"]
        self.assertEqual(tier_manifest["row_count"], 3_510)
        self.assertEqual(tier_manifest["product_count"], 30)
        self.assertEqual(tier_manifest["city_count"], 117)
        self.assertEqual(tier_manifest["calendar_day_count"], 3_063)
        self.assertEqual(tier_manifest["calendar_start_date"], "2014-02-02")
        self.assertEqual(tier_manifest["calendar_end_date"], "2022-06-22")
        self.assertEqual(len(tier_manifest["products"]), 30)
        for product in tier_manifest["products"]:
            self.assertEqual(sum(product["tier_counts"].values()), 117)


if __name__ == "__main__":
    unittest.main()
