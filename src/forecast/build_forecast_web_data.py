#!/usr/bin/env python3
"""Build browser-sized P2 historical forecast-backtest data files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from src.forecast.audit_p2_feasibility import sha256


RECORD_FIELDS = [
    "city_id",
    "horizon_days",
    "target_date",
    "origin_price",
    "actual_price",
    "best_baseline_name",
    "best_baseline_prediction",
    "model_prediction",
    "release_status",
    "release_point_source",
    "released_point_prediction",
    "released_p10",
    "released_p90",
    "absolute_percentage_error",
]


def read_cities(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["city_id"]: {
            "city_id": row["city_id"],
            "city_name_zh": row["city_name_zh"],
            "province_name_zh": row["province_name_zh"],
        }
        for row in rows
    }


def round_or_none(value: Any, digits: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_web_data(root: Path) -> dict[str, Any]:
    predictions_path = root / "artifacts/p2/final/final_test_predictions.parquet"
    release_path = root / "artifacts/p2/final/release_matrix.json"
    scorecard_path = root / "artifacts/p2/final/final_scorecard.json"
    city_path = root / "reference/dim_city.csv"
    predictions = pd.read_parquet(predictions_path)
    release = json.loads(release_path.read_text(encoding="utf-8"))
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    cities = read_cities(city_path)
    snapshot_origin = max(pd.to_datetime(predictions["origin_date"]))
    snapshot = predictions[pd.to_datetime(predictions["origin_date"]).eq(snapshot_origin)].copy()
    release_lookup = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): row
        for row in release["group_results"]
    }
    if len(release_lookup) != 30:
        raise ValueError("P2 release matrix must contain 30 product-horizon groups")
    output_dir = root / "web/public/data/forecast"
    product_dir = output_dir / "products"
    product_dir.mkdir(parents=True, exist_ok=True)
    product_metadata = []
    product_hashes: dict[str, str] = {}

    for vegetable_id, frame in snapshot.groupby("vegetable_id", sort=True, observed=True):
        vegetable_id = int(vegetable_id)
        frame = frame.sort_values(["city_id", "horizon_days"])
        product_code = str(frame["vegetable_code"].iloc[0])
        product_name = str(frame["vegetable_name_zh"].iloc[0])
        observed_cities = sorted(frame["city_id"].astype(str).unique())
        city_records = [cities[city_id] for city_id in observed_cities]
        evidence = [release_lookup[(vegetable_id, horizon)] for horizon in [7, 14, 28]]
        records = []
        for row in frame.itertuples(index=False):
            group = release_lookup[(vegetable_id, int(row.horizon_days))]
            released_point = float(row.released_point_prediction)
            actual = float(row.target_price)
            records.append(
                [
                    str(row.city_id),
                    int(row.horizon_days),
                    row.target_date.isoformat(),
                    round(float(row.origin_price), 4),
                    round(actual, 4),
                    str(row.best_baseline_name),
                    round(float(row.best_baseline_prediction), 4),
                    round(float(row.model_prediction), 4),
                    str(row.release_status),
                    str(group["release_point_source"]),
                    round(released_point, 4),
                    round_or_none(row.released_p10),
                    round_or_none(row.released_p90),
                    round(abs(actual - released_point) / actual, 6),
                ]
            )
        payload = {
            "schema_version": "p2_forecast_web_product_v0.1",
            "historical_backtest": True,
            "snapshot_origin_date": snapshot_origin.date().isoformat(),
            "product": {
                "vegetable_id": vegetable_id,
                "vegetable_code": product_code,
                "vegetable_name_zh": product_name,
            },
            "cities": city_records,
            "evidence_by_horizon": evidence,
            "record_fields": RECORD_FIELDS,
            "records": records,
        }
        relative_path = f"data/forecast/products/{vegetable_id}.json"
        output_path = root / "web/public" / relative_path
        write_json_atomic(output_path, payload)
        product_hashes[relative_path] = sha256(output_path)
        product_metadata.append(
            {
                "vegetable_id": vegetable_id,
                "vegetable_code": product_code,
                "vegetable_name_zh": product_name,
                "data_file": relative_path,
                "snapshot_city_count": len(observed_cities),
                "snapshot_record_count": len(records),
                "release_status_by_horizon": {
                    str(row["horizon_days"]): row["release_status"] for row in evidence
                },
            }
        )

    default_product_id = 170140
    default_frame = snapshot[snapshot["vegetable_id"].eq(default_product_id)]
    city_horizon_counts = default_frame.groupby("city_id")["horizon_days"].nunique()
    default_city_id = str(city_horizon_counts[city_horizon_counts.eq(3)].index.sort_values()[0])
    metadata = {
        "schema_version": "p2_forecast_web_metadata_v0.1",
        "title": "Forecast Decision Lab",
        "historical_backtest": True,
        "data_as_of": "2022-06-22",
        "snapshot_origin_date": snapshot_origin.date().isoformat(),
        "target_dates": {
            str(horizon): (snapshot_origin + pd.Timedelta(days=horizon)).date().isoformat()
            for horizon in [7, 14, 28]
        },
        "price_unit": "CNY/kg",
        "model_name": release["model_name"],
        "release_status": release["status"],
        "release_status_counts": release["status_counts"],
        "overall_final_test": {
            "row_count": scorecard["row_count"],
            "model_wape": scorecard["model_overall_metrics"]["wape"],
            "baseline_wape": scorecard["best_baseline_overall_metrics"]["wape"],
            "relative_wape_improvement": scorecard["raw_model_relative_wape_improvement"],
            "interval_coverage_80": scorecard[
                "overall_probability_metrics_on_validation_route"
            ]["interval_coverage_80"],
            "meets_overall_target_improvement": scorecard[
                "meets_overall_target_improvement"
            ],
            "meets_minimum_7d_14d_product_gate": scorecard[
                "meets_minimum_7d_14d_product_gate"
            ],
        },
        "defaults": {
            "vegetable_id": default_product_id,
            "city_id": default_city_id,
            "horizon_days": 28,
        },
        "products": product_metadata,
        "status_definitions": {
            "model_target": "模型点预测和区间均通过，且 WAPE 改善至少 8%",
            "model_minimum": "模型点预测和区间通过最低门槛，但改善不足 8%",
            "point_only_model": "模型点预测通过，区间覆盖未通过；不发布区间",
            "baseline_fallback": "模型未通过冻结门槛；发布最佳简单基线",
        },
        "boundary": "Historical backtest only. This is not a current quote or automatic pricing recommendation.",
    }
    metadata_path = output_dir / "metadata.json"
    write_json_atomic(metadata_path, metadata)
    manifest = {
        "manifest_version": "p2_forecast_web_manifest_v0.1",
        "inputs": {
            str(predictions_path.relative_to(root)): sha256(predictions_path),
            str(release_path.relative_to(root)): sha256(release_path),
            str(scorecard_path.relative_to(root)): sha256(scorecard_path),
            str(city_path.relative_to(root)): sha256(city_path),
        },
        "metadata_sha256": sha256(metadata_path),
        "product_files": product_hashes,
        "product_count": len(product_metadata),
        "snapshot_record_count": int(len(snapshot)),
        "snapshot_series_count": int(
            snapshot[["vegetable_id", "city_id"]].drop_duplicates().shape[0]
        ),
    }
    write_json_atomic(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    manifest = build_web_data(args.root.resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

