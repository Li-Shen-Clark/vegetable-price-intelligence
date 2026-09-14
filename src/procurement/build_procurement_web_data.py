#!/usr/bin/env python3
"""Export compact P4 procurement scenario data for the local web app."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml, sha256, write_json


RECORD_FIELDS = [
    "city_id",
    "horizon_days",
    "target_date",
    "released_point_prediction",
    "released_p10",
    "released_p90",
    "later_actual_price",
    "release_status",
    "release_point_source",
    "price_input_label",
    "interval_status",
    "risk_basis",
    "origin_source_reliability_score",
    "base_uncertainty_per_kg",
    "coverage_rate",
    "poor_day_share",
]


def json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.date().isoformat()
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return str(value)


def write_compact_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p4_procurement.yaml")
    snapshot = pd.read_parquet(
        root / config["procurement_mart_dir"] / "scenario_snapshot.parquet"
    )
    city_geo = pd.read_csv(root / config["city_geo_path"])
    sensitivity = json.loads(
        (root / "artifacts/p4/sensitivity_summary.json").read_text(encoding="utf-8")
    )
    out_dir = root / "web/public/data/procurement"
    products_dir = out_dir / "products"
    products_dir.mkdir(parents=True, exist_ok=True)

    product_metadata = []
    product_files = []
    for vegetable_id, group in snapshot.groupby("vegetable_id", sort=True, observed=True):
        group = group.sort_values(["horizon_days", "city_id"]).reset_index(drop=True)
        vegetable_name = str(group["vegetable_name_zh"].iloc[0])
        vegetable_code = str(group["vegetable_code"].iloc[0])
        records = [
            [json_value(row[field]) for field in RECORD_FIELDS]
            for _, row in group.iterrows()
        ]
        payload = {
            "schema_version": "p4_procurement_product_v0.1",
            "historical_scenario": True,
            "scenario_origin_date": str(config["scenario_origin_date"]),
            "product": {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": vegetable_code,
                "vegetable_name_zh": vegetable_name,
            },
            "record_fields": RECORD_FIELDS,
            "records": records,
        }
        relative = Path("data/procurement/products") / f"{int(vegetable_id)}.json"
        path = root / "web/public" / relative
        write_compact_json(path, payload)
        counts = {
            str(int(key)): int(value)
            for key, value in group.groupby("horizon_days")["city_id"].nunique().items()
        }
        product_metadata.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": vegetable_code,
                "vegetable_name_zh": vegetable_name,
                "data_file": str(relative),
                "record_count": int(len(group)),
                "city_count_by_horizon": counts,
            }
        )
        product_files.append(
            {
                "path": str(relative),
                "rows": int(len(group)),
                "sha256": sha256(path),
            }
        )

    city_records = [
        {
            "city_id": str(row.city_id),
            "city_name_zh": str(row.city_name_zh),
            "province_name_zh": str(row.province_name_zh),
            "longitude": float(row.longitude),
            "latitude": float(row.latitude),
            "coordinate_method": str(row.coordinate_method),
        }
        for row in city_geo.itertuples(index=False)
    ]
    metadata = {
        "schema_version": "p4_procurement_metadata_v0.1",
        "title": "Procurement Scenario Engine",
        "historical_scenario": True,
        "data_as_of": "2022-06-22",
        "scenario_origin_date": str(config["scenario_origin_date"]),
        "price_unit": "元/公斤",
        "distance_unit": "公里",
        "quantity_unit": "公斤（到货可用量）",
        "defaults": {
            "vegetable_id": 170060,
            "target_city_id": str(config["default_target_city_id"]),
            "horizon_days": int(config["default_horizon_days"]),
            "quantity_kg": float(config["default_quantity_kg"]),
            "transport_cost_per_kg_km": float(config["default_transport_cost_per_kg_km"]),
            "loss_rate": float(config["default_loss_rate"]),
            "max_distance_km": float(config["default_max_distance_km"]),
            "road_factor": float(config["default_road_factor"]),
            "risk_aversion": float(config["default_risk_aversion"]),
            "minimum_reliability": float(config["default_minimum_reliability"]),
            "reliability_gamma": float(config["reliability_gamma"]),
            "maximum_reliability_multiplier": float(config["maximum_reliability_multiplier"]),
        },
        "horizons_days": [7, 14, 28],
        "cities": city_records,
        "products": product_metadata,
        "sensitivity_grid": sensitivity["parameter_grid"],
        "release_status_counts": {
            "model_target": 1,
            "model_minimum": 3,
            "point_only_model": 16,
            "baseline_fallback": 10,
        },
        "formula": {
            "estimated_transport_distance": "haversine_distance × road_factor",
            "unit_transport_cost": "estimated_transport_distance × transport_cost_per_kg_km",
            "risk_penalty": "risk_aversion × base_uncertainty × reliability_multiplier",
            "unit_landed_cost": "(released_point + unit_transport_cost + risk_penalty) / (1 - loss_rate)",
            "total": "城市距离与所有成本均为历史参数化情景。",
        },
        "boundary": "P4  historical scenario using P2 release routes; no live quote, road route, supply capacity or procurement execution.",
    }
    write_compact_json(out_dir / "metadata.json", metadata)
    manifest = {
        "manifest_version": "p4_procurement_web_manifest_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_scenario": True,
        "metadata": {
            "path": "data/procurement/metadata.json",
            "sha256": sha256(out_dir / "metadata.json"),
        },
        "products": product_files,
        "total_records": int(sum(item["rows"] for item in product_files)),
    }
    write_json(out_dir / "manifest.json", manifest)
    print(f"built P4 web data: {len(product_files)} products, {manifest['total_records']} rows")


if __name__ == "__main__":
    main()
