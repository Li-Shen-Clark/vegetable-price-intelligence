#!/usr/bin/env python3
"""Publish the market fact and build deterministic city-day prices."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


INPUT_COLUMNS = [
    "date",
    "vegetable_id",
    "vegetable_code",
    "vegetable_name_zh",
    "market_id",
    "market_city",
    "market_province",
    "mapping_status",
    "mapping_confidence",
    "observed_price",
    "price_valid_flag",
    "stale_quote_flag",
    "outlier_flag",
]

CITY_SCHEMA = pa.schema(
    [
        pa.field("date", pa.date32(), nullable=False),
        pa.field("vegetable_id", pa.int32(), nullable=False),
        pa.field("vegetable_code", pa.string(), nullable=False),
        pa.field("vegetable_name_zh", pa.string(), nullable=False),
        pa.field("city_id", pa.string(), nullable=False),
        pa.field("market_city", pa.string(), nullable=False),
        pa.field("market_province", pa.string(), nullable=False),
        pa.field("analysis_price", pa.float64(), nullable=False),
        pa.field("median_price", pa.float64(), nullable=False),
        pa.field("trimmed_mean_price", pa.float64(), nullable=False),
        pa.field("number_of_reporting_markets", pa.int32(), nullable=False),
        pa.field("source_record_count", pa.int64(), nullable=False),
        pa.field("stale_quote_share", pa.float64(), nullable=False),
        pa.field("outlier_share", pa.float64(), nullable=False),
        pa.field("duplicate_market_share", pa.float64(), nullable=False),
        pa.field("mean_mapping_confidence_score", pa.float64(), nullable=False),
        pa.field("source_reliability_score", pa.float64(), nullable=False),
        pa.field("data_quality_flag", pa.string(), nullable=False),
        pa.field("aggregation_version", pa.string(), nullable=False),
    ]
)


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return {}
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def load_flat_yaml(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(" ") or ":" not in raw_line:
            raise ValueError(f"Unsupported flat YAML line {line_number}: {raw_line}")
        key, value = raw_line.split(":", 1)
        result[key.strip()] = parse_scalar(value)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_product_order(path: Path) -> List[Tuple[str, int]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = [(row["vegetable_code"], int(row["vegetable_id"])) for row in rows]
    if len(result) != 30 or len(set(result)) != 30:
        raise ValueError("dim_vegetable must contain 30 unique code/id pairs")
    return result


def read_city_dimension(path: Path) -> Tuple[Dict[str, str], Dict[str, str], str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "city_id",
        "city_name_zh",
        "province_name_zh",
        "included_market_count",
        "dimension_version",
    }
    if len(rows) != 117 or not rows or not required.issubset(rows[0]):
        raise ValueError("dim_city must contain 117 rows and the required columns")
    if len({row["city_id"] for row in rows}) != 117:
        raise ValueError("dim_city city_id must be unique")
    if len({row["city_name_zh"] for row in rows}) != 117:
        raise ValueError("dim_city city_name_zh must be unique")
    versions = {row["dimension_version"] for row in rows}
    if len(versions) != 1:
        raise ValueError(f"dim_city must have one version, found {versions}")
    city_to_id = {row["city_name_zh"]: row["city_id"] for row in rows}
    city_to_province = {row["city_name_zh"]: row["province_name_zh"] for row in rows}
    return city_to_id, city_to_province, versions.pop()


def validate_aggregation_config(config: Dict[str, Any]) -> None:
    trim_fraction = float(config["city_trim_fraction"])
    if not 0 <= trim_fraction < 0.5:
        raise ValueError("city_trim_fraction must be in [0, 0.5)")
    weight_keys = [
        "reliability_weight_freshness",
        "reliability_weight_outlier",
        "reliability_weight_duplicate",
        "reliability_weight_mapping_confidence",
        "reliability_weight_market_support",
    ]
    weights = [float(config[key]) for key in weight_keys]
    if any(weight < 0 for weight in weights) or not np.isclose(sum(weights), 1.0):
        raise ValueError(f"reliability weights must be non-negative and sum to 1, found {weights}")
    if int(config["reliability_market_support_target"]) < 1:
        raise ValueError("reliability_market_support_target must be positive")
    good = float(config["data_quality_good_min_score"])
    caution = float(config["data_quality_caution_min_score"])
    if not 0 <= caution < good <= 1:
        raise ValueError("quality score thresholds must satisfy 0 <= caution < good <= 1")


def aggregate_product(
    frame: pd.DataFrame,
    aggregation: Dict[str, Any],
    city_to_id: Dict[str, str],
    city_to_province: Dict[str, str],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    total_source_rows = len(frame)
    mapped = frame["mapping_status"].eq("mapped_existing_city")
    valid = frame["price_valid_flag"].astype(bool)
    eligible = frame.loc[mapped & valid].copy()
    if eligible.empty:
        raise ValueError("product has no eligible city aggregation rows")
    if eligible["market_city"].isna().any() or eligible["market_province"].isna().any():
        raise ValueError("eligible rows have a blank canonical city or province")
    eligible["city_id"] = eligible["market_city"].map(city_to_id)
    if eligible["city_id"].isna().any():
        unknown = sorted(eligible.loc[eligible["city_id"].isna(), "market_city"].unique())
        raise ValueError(f"city dimension misses mapped cities: {unknown}")
    expected_province = eligible["market_city"].map(city_to_province)
    if not expected_province.eq(eligible["market_province"]).all():
        raise ValueError("eligible row province conflicts with dim_city")

    confidence_scores = {
        "high": float(aggregation["mapping_confidence_high_score"]),
        "medium": float(aggregation["mapping_confidence_medium_score"]),
        "low": float(aggregation["mapping_confidence_low_score"]),
    }
    eligible["mapping_confidence_score"] = eligible["mapping_confidence"].map(
        confidence_scores
    ).fillna(float(aggregation["mapping_confidence_other_score"]))

    market_keys = [
        "date",
        "vegetable_id",
        "vegetable_code",
        "vegetable_name_zh",
        "city_id",
        "market_city",
        "market_province",
        "market_id",
    ]
    market_day = (
        eligible.groupby(market_keys, sort=False, observed=True, dropna=False)
        .agg(
            market_day_price=("observed_price", "median"),
            source_row_count=("observed_price", "size"),
            stale_quote_flag=("stale_quote_flag", "max"),
            outlier_flag=("outlier_flag", "max"),
            mapping_confidence_score=("mapping_confidence_score", "first"),
        )
        .reset_index()
    )
    market_day["duplicate_market_day_flag"] = market_day["source_row_count"] > 1

    city_keys = [
        "date",
        "vegetable_id",
        "vegetable_code",
        "vegetable_name_zh",
        "city_id",
        "market_city",
        "market_province",
    ]
    market_day.sort_values(
        city_keys + ["market_day_price", "market_id"], kind="mergesort", inplace=True
    )
    grouped = market_day.groupby(city_keys, sort=False, observed=True, dropna=False)
    group_size = grouped["market_day_price"].transform("size").astype(np.int32)
    price_rank = grouped.cumcount().astype(np.int32)
    trim_count = np.floor(group_size * float(aggregation["city_trim_fraction"])).astype(np.int32)
    retained_for_trim = (price_rank >= trim_count) & (price_rank < group_size - trim_count)
    trimmed_mean = (
        market_day.loc[retained_for_trim]
        .groupby(city_keys, sort=False, observed=True, dropna=False)["market_day_price"]
        .mean()
        .rename("trimmed_mean_price")
        .reset_index()
    )

    city_day = (
        grouped.agg(
            median_price=("market_day_price", "median"),
            number_of_reporting_markets=("market_day_price", "size"),
            source_record_count=("source_row_count", "sum"),
            stale_quote_share=("stale_quote_flag", "mean"),
            outlier_share=("outlier_flag", "mean"),
            duplicate_market_share=("duplicate_market_day_flag", "mean"),
            mean_mapping_confidence_score=("mapping_confidence_score", "mean"),
        )
        .reset_index()
        .merge(trimmed_mean, on=city_keys, how="left", validate="one_to_one")
    )
    city_day["analysis_price"] = city_day["median_price"]
    support = np.minimum(
        city_day["number_of_reporting_markets"].astype(float)
        / int(aggregation["reliability_market_support_target"]),
        1.0,
    )
    city_day["source_reliability_score"] = (
        float(aggregation["reliability_weight_freshness"])
        * (1 - city_day["stale_quote_share"])
        + float(aggregation["reliability_weight_outlier"])
        * (1 - city_day["outlier_share"])
        + float(aggregation["reliability_weight_duplicate"])
        * (1 - city_day["duplicate_market_share"])
        + float(aggregation["reliability_weight_mapping_confidence"])
        * city_day["mean_mapping_confidence_score"]
        + float(aggregation["reliability_weight_market_support"]) * support
    )
    city_day["data_quality_flag"] = np.select(
        [
            city_day["source_reliability_score"]
            >= float(aggregation["data_quality_good_min_score"]),
            city_day["source_reliability_score"]
            >= float(aggregation["data_quality_caution_min_score"]),
        ],
        ["good", "caution"],
        default="poor",
    )
    city_day["aggregation_version"] = str(aggregation["city_aggregation_version"])
    city_day["number_of_reporting_markets"] = city_day[
        "number_of_reporting_markets"
    ].astype(np.int32)
    city_day["source_record_count"] = city_day["source_record_count"].astype(np.int64)
    city_day.sort_values(["city_id", "date"], kind="mergesort", inplace=True)
    city_day.reset_index(drop=True, inplace=True)
    city_day = city_day[[field.name for field in CITY_SCHEMA]]

    if city_day.duplicated(["date", "vegetable_id", "city_id"]).any():
        raise ValueError("city-day primary key is not unique")
    price_columns = ["analysis_price", "median_price", "trimmed_mean_price"]
    if not np.isfinite(city_day[price_columns].to_numpy(dtype=float)).all():
        raise ValueError("city prices must be finite")
    if (city_day[price_columns] <= 0).any().any():
        raise ValueError("city prices must be positive")
    bounded_columns = [
        "stale_quote_share",
        "outlier_share",
        "duplicate_market_share",
        "mean_mapping_confidence_score",
        "source_reliability_score",
    ]
    if not city_day[bounded_columns].apply(lambda series: series.between(0, 1).all()).all():
        raise ValueError("city quality shares and scores must be in [0, 1]")
    if (city_day["number_of_reporting_markets"] < 1).any():
        raise ValueError("city-day reporting market count must be positive")
    if int(city_day["source_record_count"].sum()) != len(eligible):
        raise ValueError("eligible source rows were not conserved in aggregation")

    stats: Dict[str, Any] = {
        "vegetable_id": int(city_day["vegetable_id"].iat[0]),
        "vegetable_code": str(city_day["vegetable_code"].iat[0]),
        "source_rows": total_source_rows,
        "eligible_source_rows": len(eligible),
        "excluded_unmapped_rows": int((~mapped).sum()),
        "excluded_invalid_mapped_rows": int((mapped & ~valid).sum()),
        "market_day_rows": len(market_day),
        "duplicate_market_day_rows": int(market_day["duplicate_market_day_flag"].sum()),
        "city_day_rows": len(city_day),
        "cities": int(city_day["city_id"].nunique()),
        "single_market_city_day_rows": int(
            city_day["number_of_reporting_markets"].eq(1).sum()
        ),
        "quality_flag_counts": {
            str(key): int(value)
            for key, value in city_day["data_quality_flag"].value_counts().sort_index().items()
        },
        "min_analysis_price": float(city_day["analysis_price"].min()),
        "max_analysis_price": float(city_day["analysis_price"].max()),
        "min_reliability_score": float(city_day["source_reliability_score"].min()),
        "max_reliability_score": float(city_day["source_reliability_score"].max()),
    }
    return city_day, stats


def build(paths_path: Path, aggregation_path: Path) -> Dict[str, Any]:
    paths = load_flat_yaml(paths_path)
    aggregation = load_flat_yaml(aggregation_path)
    validate_aggregation_config(aggregation)
    project_root = paths_path.resolve().parent.parent
    input_path = project_root / str(paths["silver_fact_market_price_quality"])
    dim_vegetable_path = project_root / str(paths["dim_vegetable"])
    dim_city_path = project_root / str(paths["dim_city"])
    market_output_path = project_root / str(paths["gold_fact_market_price"])
    market_manifest_path = project_root / str(paths["gold_market_manifest"])
    city_output_path = project_root / str(paths["gold_fact_city_price"])
    city_manifest_path = project_root / str(paths["gold_city_manifest"])
    expected_rows = int(paths["expected_raw_rows"])

    source = pq.ParquetFile(input_path)
    if source.metadata.num_rows != expected_rows:
        raise ValueError(f"expected {expected_rows} quality rows, found {source.metadata.num_rows}")
    missing_columns = sorted(set(INPUT_COLUMNS) - set(source.schema_arrow.names))
    if missing_columns:
        raise ValueError(f"quality input misses columns: {missing_columns}")
    product_order = read_product_order(dim_vegetable_path)
    city_to_id, city_to_province, city_dimension_version = read_city_dimension(dim_city_path)

    for output_path in [market_output_path, market_manifest_path, city_output_path, city_manifest_path]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    market_temp = market_output_path.with_suffix(market_output_path.suffix + ".tmp")
    market_manifest_temp = market_manifest_path.with_suffix(market_manifest_path.suffix + ".tmp")
    city_temp = city_output_path.with_suffix(city_output_path.suffix + ".tmp")
    city_manifest_temp = city_manifest_path.with_suffix(city_manifest_path.suffix + ".tmp")
    for temp in [market_temp, market_manifest_temp, city_temp, city_manifest_temp]:
        temp.unlink(missing_ok=True)

    writer = None
    try:
        shutil.copyfile(input_path, market_temp)
        if sha256(market_temp) != sha256(input_path):
            raise ValueError("published market fact is not byte-identical to quality Silver")

        writer = pq.ParquetWriter(
            city_temp,
            CITY_SCHEMA,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        products: List[Dict[str, Any]] = []
        total_city_rows = 0
        total_eligible_rows = 0
        total_market_day_rows = 0
        observed_city_ids: set[str] = set()
        quality_counts: Counter[str] = Counter()
        for vegetable_code, vegetable_id in product_order:
            frame = pq.read_table(
                input_path,
                columns=INPUT_COLUMNS,
                filters=[("vegetable_id", "=", vegetable_id)],
            ).to_pandas()
            if set(frame["vegetable_id"].unique()) != {vegetable_id}:
                raise ValueError(f"filter leakage for vegetable {vegetable_code}")
            city_day, stats = aggregate_product(
                frame,
                aggregation,
                city_to_id,
                city_to_province,
            )
            if stats["vegetable_code"] != vegetable_code:
                raise ValueError(f"vegetable dimension mismatch for {vegetable_code}")
            output_table = pa.Table.from_pandas(
                city_day,
                schema=CITY_SCHEMA,
                preserve_index=False,
                safe=True,
            )
            writer.write_table(output_table, row_group_size=len(output_table))
            products.append(stats)
            total_city_rows += len(city_day)
            total_eligible_rows += stats["eligible_source_rows"]
            total_market_day_rows += stats["market_day_rows"]
            observed_city_ids.update(city_day["city_id"].unique())
            quality_counts.update(stats["quality_flag_counts"])
        writer.close()
        writer = None

        city_file = pq.ParquetFile(city_temp)
        if city_file.metadata.num_rows != total_city_rows:
            raise ValueError("city output row count does not match aggregation total")
        if city_file.schema_arrow != CITY_SCHEMA:
            raise ValueError("city output schema mismatch")
        if city_file.metadata.num_row_groups != len(product_order):
            raise ValueError("city output must have one row group per product")
        if observed_city_ids != set(city_to_id.values()):
            missing = sorted(set(city_to_id.values()) - observed_city_ids)
            raise ValueError(f"city output does not cover all dimension cities: {missing}")

        input_hash = sha256(input_path)
        market_hash = sha256(market_temp)
        city_hash = sha256(city_temp)
        market_manifest: Dict[str, Any] = {
            "dataset": "fact_market_price",
            "layer": "gold",
            "schema_version": "gold_market_v0.1",
            "row_count": expected_rows,
            "column_count": len(source.schema_arrow),
            "parquet_row_group_count": source.metadata.num_row_groups,
            "parquet_compression": "zstd",
            "parquet_sha256": market_hash,
            "input_quality_silver_sha256": input_hash,
            "byte_identical_to_quality_silver": market_hash == input_hash,
            "quality_rule_version": "quality_v0.1",
            "mapping_version": str(paths["market_mapping_version"]),
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in source.schema_arrow
            ],
        }
        city_manifest: Dict[str, Any] = {
            "dataset": "fact_city_price",
            "layer": "gold",
            "schema_version": "gold_city_v0.1",
            "aggregation_version": str(aggregation["city_aggregation_version"]),
            "city_dimension_version": city_dimension_version,
            "row_count": total_city_rows,
            "column_count": len(CITY_SCHEMA),
            "source_product_count": len(product_order),
            "observed_city_count": len(observed_city_ids),
            "eligible_source_rows": total_eligible_rows,
            "market_day_rows": total_market_day_rows,
            "quality_flag_counts": dict(sorted(quality_counts.items())),
            "parquet_row_group_count": city_file.metadata.num_row_groups,
            "parquet_compression": "zstd",
            "parquet_sha256": city_hash,
            "input_quality_silver_sha256": input_hash,
            "dim_city_sha256": sha256(dim_city_path),
            "dim_vegetable_sha256": sha256(dim_vegetable_path),
            "aggregation_config_sha256": sha256(aggregation_path),
            "implementation_sha256": sha256(Path(__file__).resolve()),
            "products": products,
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in CITY_SCHEMA
            ],
        }
        market_manifest_temp.write_text(
            json.dumps(market_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        city_manifest_temp.write_text(
            json.dumps(city_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        market_temp.replace(market_output_path)
        city_temp.replace(city_output_path)
        market_manifest_temp.replace(market_manifest_path)
        city_manifest_temp.replace(city_manifest_path)
        return {"market": market_manifest, "city": city_manifest}
    except Exception:
        if writer is not None:
            writer.close()
        for temp in [market_temp, market_manifest_temp, city_temp, city_manifest_temp]:
            temp.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default="config/paths.yaml")
    parser.add_argument("--aggregation", default="config/aggregation.yaml")
    args = parser.parse_args()
    manifests = build(Path(args.paths).resolve(), Path(args.aggregation).resolve())
    print(
        json.dumps(
            {
                "market": {
                    "rows": manifests["market"]["row_count"],
                    "columns": manifests["market"]["column_count"],
                    "sha256": manifests["market"]["parquet_sha256"],
                },
                "city": {
                    "rows": manifests["city"]["row_count"],
                    "columns": manifests["city"]["column_count"],
                    "cities": manifests["city"]["observed_city_count"],
                    "quality_flag_counts": manifests["city"]["quality_flag_counts"],
                    "sha256": manifests["city"]["parquet_sha256"],
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
