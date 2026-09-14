#!/usr/bin/env python3
"""Build the frozen local P5 propagation mart without estimating network edges."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.forecast.audit_p2_feasibility import load_scope_products
from src.procurement.common import load_flat_yaml, sha256, write_json
from src.propagation.audit_p5_feasibility import (
    SPLITS,
    add_propagation_residuals,
    build_binned_panel,
    build_candidate_edges,
    eligible_series,
    validate_config,
)


def _load_inputs(root: Path, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    products = load_scope_products(root / config["scope_config_path"])
    product_ids = {int(item["vegetable_id"]) for item in products}
    tiers = pd.read_parquet(root / config["coverage_tier_path"])
    tiers = tiers.loc[
        tiers["vegetable_id"].isin(product_ids)
        & tiers["coverage_tier"].isin(config["official_tiers"])
    ].copy()
    geo = pd.read_csv(root / config["city_geo_path"])
    fact = pd.read_parquet(
        root / config["city_fact_path"],
        columns=[
            "date",
            "vegetable_id",
            "vegetable_code",
            "vegetable_name_zh",
            "city_id",
            "analysis_price",
            "source_reliability_score",
            "data_quality_flag",
        ],
    )
    fact["date"] = pd.to_datetime(fact["date"])
    fact = fact.loc[
        fact["vegetable_id"].isin(product_ids)
        & fact["analysis_price"].gt(0)
        & ~fact["data_quality_flag"].isin(config["excluded_quality_flags"])
        & fact["date"].between(
            pd.Timestamp(config["train_start"]), pd.Timestamp(config["final_test_end"])
        )
    ].merge(
        tiers[["vegetable_id", "city_id"]],
        on=["vegetable_id", "city_id"],
        how="inner",
        validate="many_to_one",
    )
    return fact, tiers, geo


def _decorate_panel(
    panel: pd.DataFrame,
    eligible: pd.DataFrame,
    geo: pd.DataFrame,
    config: dict[str, Any],
    *,
    frequency: str,
    bin_days: int,
) -> pd.DataFrame:
    result = add_propagation_residuals(
        panel, eligible, config, bin_days=bin_days
    ).merge(
        geo[["city_id", "city_name_zh", "province_name_zh"]],
        on="city_id",
        how="left",
        validate="many_to_one",
    )
    result["frequency"] = frequency
    result["bin_days"] = int(bin_days)
    result["mart_version"] = str(config["mart_version"])
    result.sort_values(["vegetable_id", "city_id", "bin_start"], inplace=True)
    ordered = [
        "frequency",
        "bin_days",
        "bin_start",
        "split",
        "vegetable_id",
        "vegetable_code",
        "vegetable_name_zh",
        "city_id",
        "city_name_zh",
        "province_name_zh",
        "analysis_price",
        "observed_days",
        "mean_source_reliability",
        "log_return",
        "season_position",
        "seasonal_return",
        "seasonally_adjusted_return",
        "common_factor_loo",
        "common_factor_peer_count",
        "propagation_residual",
        "train_shock_threshold",
        "positive_shock",
        "mart_version",
    ]
    return result[ordered].reset_index(drop=True)


def build_mart(root: Path, config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    validate_config(config)
    fact, tiers, geo = _load_inputs(root, config)
    primary_raw = build_binned_panel(
        fact,
        anchor_date=str(config["primary_anchor_date"]),
        bin_days=int(config["primary_bin_days"]),
        minimum_observations=int(config["primary_minimum_observations_per_bin"]),
    )
    weekly_raw = build_binned_panel(
        fact,
        anchor_date=str(config["robustness_anchor_date"]),
        bin_days=int(config["robustness_bin_days"]),
        minimum_observations=int(config["robustness_minimum_observations_per_bin"]),
    )
    eligible = eligible_series(primary_raw, weekly_raw, config)
    primary = _decorate_panel(
        primary_raw,
        eligible,
        geo,
        config,
        frequency=str(config["primary_frequency"]),
        bin_days=int(config["primary_bin_days"]),
    )
    weekly = _decorate_panel(
        weekly_raw,
        eligible,
        geo,
        config,
        frequency=str(config["robustness_frequency"]),
        bin_days=int(config["robustness_bin_days"]),
    )
    edges = build_candidate_edges(eligible, tiers, geo, config)
    edges = edges.merge(
        geo[["city_id", "city_name_zh", "province_name_zh"]].rename(
            columns={
                "city_id": "source_city_id",
                "city_name_zh": "source_city_name_zh",
                "province_name_zh": "source_province_name_zh",
            }
        ),
        on="source_city_id",
        how="left",
        validate="many_to_one",
    ).merge(
        geo[["city_id", "city_name_zh", "province_name_zh"]].rename(
            columns={
                "city_id": "target_city_id",
                "city_name_zh": "target_city_name_zh",
                "province_name_zh": "target_province_name_zh",
            }
        ),
        on="target_city_id",
        how="left",
        validate="many_to_one",
    )
    edges["mart_version"] = str(config["mart_version"])
    edges.sort_values(
        ["vegetable_id", "target_city_id", "candidate_rank"], inplace=True
    )
    eligible = eligible.merge(
        tiers[
            ["vegetable_id", "vegetable_code", "vegetable_name_zh", "city_id"]
        ],
        on=["vegetable_id", "city_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        geo[["city_id", "city_name_zh", "province_name_zh"]],
        on="city_id",
        how="left",
        validate="many_to_one",
    )
    eligible["mart_version"] = str(config["mart_version"])
    return {
        "primary_panel": primary,
        "weekly_panel": weekly,
        "candidate_edges": edges.reset_index(drop=True),
        "eligible_series": eligible.sort_values(
            ["vegetable_id", "city_id"]
        ).reset_index(drop=True),
    }


def _file_summary(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "sha256": sha256(path),
    }
    if "bin_start" in frame:
        result["minimum_bin_start"] = str(pd.Timestamp(frame["bin_start"].min()).date())
        result["maximum_bin_start"] = str(pd.Timestamp(frame["bin_start"].max()).date())
    return result


def write_mart(root: Path, config: dict[str, Any], frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    output_dir = root / config["propagation_mart_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    for name, frame in frames.items():
        path = output_dir / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        files[name] = _file_summary(path.relative_to(root), frame)
        files[name]["sha256"] = sha256(path)
    manifest = {
        "mart_version": config["mart_version"],
        "experiment_version": config["experiment_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "frozen",
        "frequencies": {
            "primary": config["primary_frequency"],
            "robustness": config["robustness_frequency"],
        },
        "splits": {
            split: {
                "start": str(config[f"{split}_start"]),
                "end": str(config[f"{split}_end"]),
            }
            for split in SPLITS
        },
        "method_flags": {
            "seasonality_fit_on_train_only": True,
            "shock_threshold_fit_on_train_only": True,
            "common_factor_leave_one_out": True,
            "candidate_edges_selected_from_prices": False,
            "directional_models_fitted": False,
            "final_test_used_for_selection": False,
        },
        "files": files,
        "inputs": {
            key: {"path": str(config[key]), "sha256": sha256(root / config[key])}
            for key in ["city_fact_path", "coverage_tier_path", "city_geo_path"]
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p5_propagation_experiment.yaml")
    frames = build_mart(root, config)
    manifest = write_mart(root, config, frames)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "primary_rows": manifest["files"]["primary_panel"]["rows"],
                "weekly_rows": manifest["files"]["weekly_panel"]["rows"],
                "candidate_edges": manifest["files"]["candidate_edges"]["rows"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
