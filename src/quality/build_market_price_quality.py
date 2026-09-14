#!/usr/bin/env python3
"""Add row-level, non-destructive quality flags to mapped Silver prices."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


QUALITY_FIELDS = [
    pa.field("price_valid_flag", pa.bool_(), nullable=False),
    pa.field("invalid_price_reason", pa.string(), nullable=True),
    pa.field("reported_change_consistent_flag", pa.bool_(), nullable=True),
    pa.field("duplicate_market_date_flag", pa.bool_(), nullable=False),
    pa.field("zero_change_flag", pa.bool_(), nullable=False),
    pa.field("zero_change_run_length", pa.int32(), nullable=False),
    pa.field("stale_quote_flag", pa.bool_(), nullable=False),
    pa.field("days_since_last_valid_quote", pa.int32(), nullable=True),
    pa.field("outlier_flag", pa.bool_(), nullable=False),
    pa.field("quality_rule_version", pa.string(), nullable=False),
]


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
    return [(row["vegetable_code"], int(row["vegetable_id"])) for row in rows]


def add_quality_fields(frame: pd.DataFrame, quality: Dict[str, Any]) -> pd.DataFrame:
    input_columns = list(frame.columns)
    frame = frame.copy()
    frame["_source_order"] = np.arange(len(frame), dtype=np.int64)
    frame["_date_ts"] = pd.to_datetime(frame["date"])
    frame.sort_values(
        ["market_id", "_date_ts", "source_file_row_number"],
        kind="mergesort",
        inplace=True,
    )
    frame.reset_index(drop=True, inplace=True)

    price = frame["observed_price"].astype(float)
    previous = frame["previous_price"].astype(float)
    valid = np.isfinite(price) & (price > float(quality["positive_price_min_exclusive"]))
    previous_valid = np.isfinite(previous) & (previous > 0)
    frame["price_valid_flag"] = valid
    frame["invalid_price_reason"] = np.where(valid, None, "non_positive")

    evaluable_change = valid & previous_valid & np.isfinite(frame["reported_change_pct"].astype(float))
    calculated_change = np.full(len(frame), np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        calculated_change[evaluable_change] = np.round(
            (price[evaluable_change] - previous[evaluable_change])
            / previous[evaluable_change]
            * 100,
            2,
        )
    change_consistent = np.full(len(frame), None, dtype=object)
    change_consistent[evaluable_change] = (
        np.abs(calculated_change[evaluable_change] - frame.loc[evaluable_change, "reported_change_pct"].astype(float))
        <= float(quality["reported_change_tolerance_pp"])
    )
    frame["reported_change_consistent_flag"] = pd.array(change_consistent, dtype="boolean")

    frame["duplicate_market_date_flag"] = frame.duplicated(
        subset=["market_id", "vegetable_id", "_date_ts"], keep=False
    )

    grouped = frame.groupby("market_id", sort=False, observed=True)
    previous_observation_date = grouped["_date_ts"].shift(1)
    calendar_gap_days = (frame["_date_ts"] - previous_observation_date).dt.days
    exact_zero_change = valid & previous_valid & np.isclose(price, previous, rtol=0, atol=1e-12)
    zero_change = exact_zero_change & calendar_gap_days.eq(1)
    frame["zero_change_flag"] = zero_change
    run_segment = (~zero_change).groupby(frame["market_id"], sort=False).cumsum()
    frame["zero_change_run_length"] = (
        zero_change.astype(np.int32)
        .groupby([frame["market_id"], run_segment], sort=False)
        .cumsum()
        .astype(np.int32)
    )
    frame["stale_quote_flag"] = frame["zero_change_run_length"] >= int(
        quality["stale_quote_min_run_days"]
    )

    current_valid_date = frame["_date_ts"].where(valid)
    last_valid_date = current_valid_date.groupby(frame["market_id"], sort=False).ffill()
    days_since = (frame["_date_ts"] - last_valid_date).dt.days
    frame["days_since_last_valid_quote"] = pd.array(days_since, dtype="Int32")

    log_values = np.full(len(frame), np.nan, dtype=float)
    log_values[valid] = np.log(price.to_numpy()[valid])
    log_price = pd.Series(log_values, index=frame.index)
    prior_log_price = log_price.groupby(frame["market_id"], sort=False).shift(1)
    rolling = prior_log_price.groupby(frame["market_id"], sort=False).rolling(
        window=int(quality["outlier_history_window_rows"]),
        min_periods=int(quality["outlier_min_valid_history"]),
    )
    history_count = rolling.count().reset_index(level=0, drop=True).sort_index()
    rolling_median = rolling.median().reset_index(level=0, drop=True).sort_index()
    rolling_q25 = rolling.quantile(0.25).reset_index(level=0, drop=True).sort_index()
    rolling_q75 = rolling.quantile(0.75).reset_index(level=0, drop=True).sort_index()
    robust_scale = (rolling_q75 - rolling_q25) / 1.349
    absolute_deviation = (log_price - rolling_median).abs()
    enough_history = history_count >= int(quality["outlier_min_valid_history"])
    positive_scale_outlier = (robust_scale > 0) & (
        absolute_deviation > float(quality["outlier_robust_scale_multiplier"]) * robust_scale
    )
    zero_scale_outlier = robust_scale.eq(0) & (
        absolute_deviation > np.log(float(quality["outlier_zero_iqr_min_ratio"]))
    )
    frame["outlier_flag"] = (
        valid & enough_history & (positive_scale_outlier | zero_scale_outlier)
    ).fillna(False)
    frame["quality_rule_version"] = str(quality["quality_rule_version"])

    frame.sort_values("_source_order", kind="mergesort", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame[input_columns + [field.name for field in QUALITY_FIELDS]]


def build(paths_path: Path, quality_path: Path) -> Dict[str, Any]:
    paths = load_flat_yaml(paths_path)
    quality = load_flat_yaml(quality_path)
    project_root = paths_path.resolve().parent.parent
    input_path = project_root / str(paths["silver_fact_market_price"])
    output_path = project_root / str(paths["silver_fact_market_price_quality"])
    manifest_path = project_root / str(paths["silver_quality_manifest"])
    dim_path = project_root / str(paths["dim_vegetable"])
    expected_rows = int(paths["expected_raw_rows"])

    source = pq.ParquetFile(input_path)
    if source.metadata.num_rows != expected_rows:
        raise ValueError(f"expected {expected_rows} input rows, found {source.metadata.num_rows}")
    output_schema = pa.schema(list(source.schema_arrow) + QUALITY_FIELDS)
    product_order = read_product_order(dim_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_output.unlink(missing_ok=True)
    temp_manifest.unlink(missing_ok=True)

    writer = None
    total_rows = 0
    total_stats = {
        "invalid_price_rows": 0,
        "change_consistency_evaluable_rows": 0,
        "change_inconsistent_rows": 0,
        "duplicate_rows": 0,
        "zero_change_rows": 0,
        "stale_quote_rows": 0,
        "outlier_rows": 0,
        "days_since_last_valid_quote_null_rows": 0,
    }
    products: List[Dict[str, Any]] = []
    try:
        writer = pq.ParquetWriter(
            temp_output,
            output_schema,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        for vegetable_code, vegetable_id in product_order:
            table = pq.read_table(
                input_path,
                filters=[("vegetable_id", "=", vegetable_id)],
            )
            if table.num_rows == 0:
                raise ValueError(f"no input rows for vegetable {vegetable_code}")
            frame = table.to_pandas()
            if set(frame["vegetable_id"].unique()) != {vegetable_id}:
                raise ValueError(f"filter leakage for vegetable {vegetable_code}")
            enriched = add_quality_fields(frame, quality)
            output_table = pa.Table.from_pandas(
                enriched,
                schema=output_schema,
                preserve_index=False,
                safe=True,
            )
            writer.write_table(output_table, row_group_size=len(output_table))

            evaluable = int(enriched["reported_change_consistent_flag"].notna().sum())
            product_stats = {
                "vegetable_id": vegetable_id,
                "vegetable_code": vegetable_code,
                "row_count": len(enriched),
                "invalid_price_rows": int((~enriched["price_valid_flag"]).sum()),
                "change_consistency_evaluable_rows": evaluable,
                "change_inconsistent_rows": int(
                    (enriched["reported_change_consistent_flag"] == False).sum()
                ),
                "duplicate_rows": int(enriched["duplicate_market_date_flag"].sum()),
                "zero_change_rows": int(enriched["zero_change_flag"].sum()),
                "stale_quote_rows": int(enriched["stale_quote_flag"].sum()),
                "outlier_rows": int(enriched["outlier_flag"].sum()),
                "days_since_last_valid_quote_null_rows": int(
                    enriched["days_since_last_valid_quote"].isna().sum()
                ),
            }
            for key in total_stats:
                total_stats[key] += product_stats[key]
            products.append(product_stats)
            total_rows += len(enriched)

        writer.close()
        writer = None
        if total_rows != expected_rows:
            raise ValueError(f"expected {expected_rows} output rows, wrote {total_rows}")
        output = pq.ParquetFile(temp_output)
        if output.metadata.num_rows != total_rows or output.schema_arrow != output_schema:
            raise ValueError("quality Parquet contract mismatch")

        manifest: Dict[str, Any] = {
            "dataset": "fact_market_price_quality",
            "layer": "silver",
            "schema_version": "silver_quality_v0.1",
            "mapping_version": str(paths["market_mapping_version"]),
            "quality_rule_version": str(quality["quality_rule_version"]),
            "row_count": total_rows,
            "column_count": len(output_schema),
            "source_product_count": len(products),
            "parquet_row_group_count": output.metadata.num_row_groups,
            "parquet_compression": "zstd",
            "parquet_sha256": sha256(temp_output),
            "input_silver_sha256": sha256(input_path),
            "paths_config_sha256": sha256(paths_path),
            "quality_config_sha256": sha256(quality_path),
            "implementation_sha256": sha256(Path(__file__).resolve()),
            "input_columns_preserved_by_construction": True,
            "summary": total_stats,
            "products": products,
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in output_schema
            ],
        }
        temp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_output.replace(output_path)
        temp_manifest.replace(manifest_path)
        return manifest
    except Exception:
        if writer is not None:
            writer.close()
        temp_output.unlink(missing_ok=True)
        temp_manifest.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default="config/paths.yaml")
    parser.add_argument("--quality", default="config/quality.yaml")
    args = parser.parse_args()
    manifest = build(Path(args.paths).resolve(), Path(args.quality).resolve())
    print(
        json.dumps(
            {
                "dataset": manifest["dataset"],
                "rows": manifest["row_count"],
                "columns": manifest["column_count"],
                "summary": manifest["summary"],
                "row_groups": manifest["parquet_row_group_count"],
                "parquet_sha256": manifest["parquet_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
