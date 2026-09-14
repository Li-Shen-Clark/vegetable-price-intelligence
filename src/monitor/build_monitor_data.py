#!/usr/bin/env python3
"""Build deterministic, browser-sized monthly data for the P1 price monitor."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


CITY_COLUMNS = [
    "date",
    "vegetable_id",
    "vegetable_code",
    "vegetable_name_zh",
    "city_id",
    "analysis_price",
    "number_of_reporting_markets",
    "source_record_count",
    "source_reliability_score",
    "data_quality_flag",
]

RECORD_FIELDS = [
    "city_id",
    "month",
    "median_price",
    "p25_price",
    "p75_price",
    "valid_day_count",
    "first_observed_date",
    "last_observed_date",
    "mean_source_reliability_score",
    "good_day_count",
    "caution_day_count",
    "poor_day_count",
    "median_reporting_markets",
    "max_reporting_markets",
    "source_record_count",
]

PROFILE_FIELDS = [
    "city_id",
    "coverage_tier",
    "monitor_eligible_flag",
    "coverage_rate",
    "valid_day_count",
    "mean_source_reliability_score",
    "tier_reason",
]


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def load_flat_yaml(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(" ") or ":" not in raw_line:
            raise ValueError(f"Unsupported flat YAML line {line_number}: {raw_line}")
        key, value = raw_line.split(":", 1)
        result[key.strip()] = parse_scalar(value)
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_text(content, encoding="utf-8")


def round_float(value: Any, digits: int) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), digits)


def validate_config(config: dict[str, Any]) -> None:
    required = {
        "monitor_schema_version",
        "price_unit",
        "display_granularity",
        "ranking_min_valid_days",
        "ranking_eligible_tiers",
        "default_vegetable_id",
        "default_city_id",
        "price_decimals",
        "score_decimals",
        "market_count_decimals",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"monitor config misses keys: {sorted(missing)}")
    if config["display_granularity"] != "month":
        raise ValueError("P1 v0.1 supports monthly display granularity only")
    if int(config["ranking_min_valid_days"]) < 1:
        raise ValueError("ranking_min_valid_days must be positive")
    if list(config["ranking_eligible_tiers"]) != ["A", "B"]:
        raise ValueError("P1 default ranking tiers must be A and B")


def parquet_date_range(parquet: pq.ParquetFile) -> tuple[str, str]:
    date_index = parquet.schema_arrow.get_field_index("date")
    minima = []
    maxima = []
    for index in range(parquet.metadata.num_row_groups):
        stats = parquet.metadata.row_group(index).column(date_index).statistics
        if stats is None or not stats.has_min_max:
            dates = parquet.read_row_group(index, columns=["date"])["date"].to_pylist()
            minima.append(min(dates))
            maxima.append(max(dates))
        else:
            minima.append(stats.min)
            maxima.append(stats.max)
    return min(minima).isoformat(), max(maxima).isoformat()


def build_monthly_records(
    frame: pd.DataFrame,
    *,
    price_decimals: int,
    score_decimals: int,
    market_count_decimals: int,
) -> list[list[Any]]:
    if frame.duplicated(["date", "vegetable_id", "city_id"]).any():
        raise ValueError("Gold city-day primary key is not unique")
    frame = frame.copy()
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    keys = ["city_id", "month"]
    grouped = frame.groupby(keys, sort=True, observed=True)

    base = grouped.agg(
        valid_day_count=("date", "size"),
        first_observed_date=("date", "min"),
        last_observed_date=("date", "max"),
        mean_source_reliability_score=("source_reliability_score", "mean"),
        median_reporting_markets=("number_of_reporting_markets", "median"),
        max_reporting_markets=("number_of_reporting_markets", "max"),
        source_record_count=("source_record_count", "sum"),
    )
    quantiles = (
        grouped["analysis_price"]
        .quantile([0.25, 0.5, 0.75])
        .unstack(level=-1)
        .rename(columns={0.25: "p25_price", 0.5: "median_price", 0.75: "p75_price"})
    )
    quality = (
        frame.assign(
            good_day_count=frame["data_quality_flag"].eq("good").astype(int),
            caution_day_count=frame["data_quality_flag"].eq("caution").astype(int),
            poor_day_count=frame["data_quality_flag"].eq("poor").astype(int),
        )
        .groupby(keys, sort=True, observed=True)[
            ["good_day_count", "caution_day_count", "poor_day_count"]
        ]
        .sum()
    )
    monthly = base.join(quantiles, validate="one_to_one").join(quality, validate="one_to_one")
    monthly.reset_index(inplace=True)
    monthly.sort_values(keys, kind="mergesort", inplace=True)

    if monthly.duplicated(keys).any():
        raise ValueError("monthly monitor primary key is not unique")
    if not (
        monthly["valid_day_count"]
        == monthly[["good_day_count", "caution_day_count", "poor_day_count"]].sum(axis=1)
    ).all():
        raise ValueError("monthly quality-day counts do not conserve valid days")
    if not (
        (monthly["p25_price"] <= monthly["median_price"])
        & (monthly["median_price"] <= monthly["p75_price"])
    ).all():
        raise ValueError("monthly price quantiles are not monotonic")

    records: list[list[Any]] = []
    for row in monthly.itertuples(index=False):
        records.append(
            [
                row.city_id,
                row.month,
                round_float(row.median_price, price_decimals),
                round_float(row.p25_price, price_decimals),
                round_float(row.p75_price, price_decimals),
                int(row.valid_day_count),
                row.first_observed_date.isoformat(),
                row.last_observed_date.isoformat(),
                round_float(row.mean_source_reliability_score, score_decimals),
                int(row.good_day_count),
                int(row.caution_day_count),
                int(row.poor_day_count),
                round_float(row.median_reporting_markets, market_count_decimals),
                int(row.max_reporting_markets),
                int(row.source_record_count),
            ]
        )
    return records


def build_city_profiles(
    tier_frame: pd.DataFrame, *, score_decimals: int
) -> list[list[Any]]:
    tier_frame = tier_frame.sort_values("city_id", kind="mergesort")
    profiles: list[list[Any]] = []
    for row in tier_frame.itertuples(index=False):
        profiles.append(
            [
                row.city_id,
                row.coverage_tier,
                bool(row.monitor_eligible_flag),
                round_float(row.coverage_rate, score_decimals),
                int(row.valid_day_count),
                round_float(row.mean_source_reliability_score, score_decimals),
                row.tier_reason,
            ]
        )
    return profiles


def publish_directory(temp_dir: Path, output_dir: Path) -> None:
    backup_dir = output_dir.with_name(output_dir.name + ".previous")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if output_dir.exists():
        output_dir.rename(backup_dir)
    try:
        temp_dir.rename(output_dir)
    except Exception:
        if backup_dir.exists() and not output_dir.exists():
            backup_dir.rename(output_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)


def build(root: Path, paths: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    city_path = root / str(paths["gold_fact_city_price"])
    tier_path = root / str(paths["gold_coverage_tiers"])
    dim_city_path = root / str(paths["dim_city"])
    dim_vegetable_path = root / str(paths["dim_vegetable"])
    output_dir = root / str(paths["monitor_data_dir"])
    temp_dir = output_dir.with_name(output_dir.name + ".tmp")

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    (temp_dir / "products").mkdir(parents=True, exist_ok=True)

    vegetables = read_csv(dim_vegetable_path)
    cities = read_csv(dim_city_path)
    if len(vegetables) != 30 or len({row["vegetable_id"] for row in vegetables}) != 30:
        raise ValueError("dim_vegetable must have 30 unique products")
    if len(cities) != 117 or len({row["city_id"] for row in cities}) != 117:
        raise ValueError("dim_city must have 117 unique cities")

    tier_table = pq.read_table(tier_path).to_pandas()
    if len(tier_table) != 3510:
        raise ValueError("coverage tiers must have 3,510 rows")
    tier_table["vegetable_id"] = tier_table["vegetable_id"].astype(int)

    parquet = pq.ParquetFile(city_path)
    data_start, data_end = parquet_date_range(parquet)
    end_period = pd.Period(data_end, freq="M")
    last_complete_month = str(end_period - 1)
    row_group_by_product: dict[int, int] = {}
    for group_index in range(parquet.metadata.num_row_groups):
        product_ids = parquet.read_row_group(group_index, columns=["vegetable_id"])[
            "vegetable_id"
        ].unique().to_pylist()
        if len(product_ids) != 1:
            raise ValueError(f"row group {group_index} contains multiple products")
        product_id = int(product_ids[0])
        if product_id in row_group_by_product:
            raise ValueError(f"product {product_id} spans multiple row groups")
        row_group_by_product[product_id] = group_index

    product_summaries: list[dict[str, Any]] = []
    product_manifest_entries: list[dict[str, Any]] = []
    total_monthly_records = 0
    total_city_day_rows = 0
    vegetable_ids = {int(row["vegetable_id"]) for row in vegetables}
    if set(row_group_by_product) != vegetable_ids:
        raise ValueError("Gold row-group products do not match dim_vegetable")

    for vegetable in vegetables:
        vegetable_id = int(vegetable["vegetable_id"])
        frame = parquet.read_row_group(
            row_group_by_product[vegetable_id], columns=CITY_COLUMNS
        ).to_pandas()
        if set(frame["vegetable_id"].astype(int).unique()) != {vegetable_id}:
            raise ValueError(f"Gold product mismatch for {vegetable_id}")
        tier_product = tier_table.loc[tier_table["vegetable_id"].eq(vegetable_id)].copy()
        if len(tier_product) != 117 or set(tier_product["city_id"]) != {
            row["city_id"] for row in cities
        }:
            raise ValueError(f"tier city coverage is incomplete for {vegetable_id}")

        records = build_monthly_records(
            frame,
            price_decimals=int(config["price_decimals"]),
            score_decimals=int(config["score_decimals"]),
            market_count_decimals=int(config["market_count_decimals"]),
        )
        profiles = build_city_profiles(
            tier_product, score_decimals=int(config["score_decimals"])
        )
        product_months = [record[1] for record in records]
        product_payload = {
            "schema_version": config["monitor_schema_version"],
            "product": {
                "vegetable_id": vegetable_id,
                "vegetable_code": vegetable["vegetable_code"],
                "vegetable_name_zh": vegetable["vegetable_name_zh"],
                "edible_part_group": vegetable["edible_part_group"],
                "perishability_group": vegetable["perishability_group"],
                "storability_group": vegetable["storability_group"],
                "typical_price_level": vegetable["typical_price_level"],
            },
            "data_period": {
                "start": data_start,
                "end": data_end,
                "last_complete_month": last_complete_month,
                "granularity": config["display_granularity"],
                "price_unit": config["price_unit"],
            },
            "city_profile_fields": PROFILE_FIELDS,
            "city_profiles": profiles,
            "record_fields": RECORD_FIELDS,
            "records": records,
        }
        relative_file = f"products/{vegetable_id}.json"
        product_path = temp_dir / relative_file
        write_json(product_path, product_payload)
        file_hash = sha256(product_path)
        file_size = product_path.stat().st_size
        total_monthly_records += len(records)
        total_city_day_rows += len(frame)
        tier_counts = tier_product["coverage_tier"].value_counts().to_dict()
        monitor_eligible_count = int(tier_product["monitor_eligible_flag"].sum())
        product_summaries.append(
            {
                "vegetable_id": vegetable_id,
                "vegetable_code": vegetable["vegetable_code"],
                "vegetable_name_zh": vegetable["vegetable_name_zh"],
                "edible_part_group": vegetable["edible_part_group"],
                "perishability_group": vegetable["perishability_group"],
                "storability_group": vegetable["storability_group"],
                "typical_price_level": vegetable["typical_price_level"],
                "data_file": f"data/{relative_file}",
                "monthly_record_count": len(records),
                "observed_city_count": len({record[0] for record in records}),
                "first_month": min(product_months),
                "last_month": max(product_months),
                "monitor_eligible_city_count": monitor_eligible_count,
                "tier_counts": {tier: int(tier_counts.get(tier, 0)) for tier in ["A", "B", "C"]},
            }
        )
        product_manifest_entries.append(
            {
                "vegetable_id": vegetable_id,
                "file": relative_file,
                "sha256": file_hash,
                "bytes": file_size,
                "monthly_record_count": len(records),
                "city_day_source_rows": len(frame),
            }
        )

    if total_city_day_rows != parquet.metadata.num_rows:
        raise ValueError("Gold city-day rows were not conserved across products")

    default_vegetable_id = int(config["default_vegetable_id"])
    default_city_id = str(config["default_city_id"])
    default_profile = tier_table.loc[
        tier_table["vegetable_id"].eq(default_vegetable_id)
        & tier_table["city_id"].eq(default_city_id)
    ]
    if len(default_profile) != 1 or not bool(default_profile.iloc[0]["monitor_eligible_flag"]):
        raise ValueError("default product/city must be a monitor-eligible Tier A/B combination")

    metadata = {
        "schema_version": config["monitor_schema_version"],
        "title": "Historical Price Monitor",
        "historical_only": True,
        "data_period": {
            "start": data_start,
            "end": data_end,
            "last_complete_month": last_complete_month,
            "granularity": config["display_granularity"],
            "price_unit": config["price_unit"],
        },
        "ranking_policy": {
            "eligible_tiers": list(config["ranking_eligible_tiers"]),
            "minimum_valid_days_in_month": int(config["ranking_min_valid_days"]),
        },
        "defaults": {
            "vegetable_id": default_vegetable_id,
            "city_id": default_city_id,
            "month": last_complete_month,
        },
        "methodology": {
            "display_price": "median of valid city-day analysis_price values within the calendar month",
            "price_band": "25th and 75th percentiles of valid city-day analysis_price values within the calendar month",
            "quality_counts": "counts of good, caution, and poor city-day quality flags within the month",
            "comparison_scope": "Tier A/B cities with at least the configured minimum valid days in the selected month",
        },
        "source_artifacts": {
            "city_gold": {
                "path": str(paths["gold_fact_city_price"]),
                "sha256": sha256(city_path),
                "row_count": parquet.metadata.num_rows,
            },
            "coverage_tiers": {
                "path": str(paths["gold_coverage_tiers"]),
                "sha256": sha256(tier_path),
                "row_count": len(tier_table),
            },
            "dim_city": {"path": str(paths["dim_city"]), "sha256": sha256(dim_city_path)},
            "dim_vegetable": {
                "path": str(paths["dim_vegetable"]),
                "sha256": sha256(dim_vegetable_path),
            },
        },
        "cities": [
            {
                "city_id": row["city_id"],
                "city_name_zh": row["city_name_zh"],
                "province_name_zh": row["province_name_zh"],
                "included_market_count": int(row["included_market_count"]),
            }
            for row in cities
        ],
        "products": product_summaries,
    }
    metadata_path = temp_dir / "metadata.json"
    write_json(metadata_path, metadata, pretty=True)

    manifest = {
        "schema_version": config["monitor_schema_version"],
        "dataset": "historical_price_monitor_web_mart",
        "data_start": data_start,
        "data_end": data_end,
        "last_complete_month": last_complete_month,
        "product_count": len(product_summaries),
        "city_count": len(cities),
        "monthly_record_count": total_monthly_records,
        "city_day_source_row_count": total_city_day_rows,
        "metadata_sha256": sha256(metadata_path),
        "products": product_manifest_entries,
    }
    write_json(temp_dir / "manifest.json", manifest, pretty=True)
    publish_directory(temp_dir, output_dir)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", default="config/paths.yaml")
    parser.add_argument("--monitor-config", default="config/monitor.yaml")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    paths = load_flat_yaml(root / args.paths)
    config = load_flat_yaml(root / args.monitor_config)
    manifest = build(root, paths, config)
    print(
        "Built Historical Price Monitor mart: "
        f"{manifest['product_count']} products, "
        f"{manifest['city_count']} cities, "
        f"{manifest['monthly_record_count']:,} monthly records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
