#!/usr/bin/env python3
"""Build the leakage-safe P2 forecasting mart from P0 Gold city-day prices."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.forecast.audit_p2_feasibility import (
    load_flat_yaml,
    load_scope_products,
    monthly_origins,
    sha256,
    validate_config,
)


KEY_COLUMNS = ["vegetable_id", "city_id", "origin_date", "horizon_days"]
TARGET_COLUMNS = [
    "target_date",
    "target_price",
    "log_target_price",
    "target_price_change",
    "target_log_return",
    "target_direction",
]


def validate_feature_config(config: dict[str, Any]) -> None:
    required = {
        "feature_contract_version",
        "experiment_config_path",
        "training_origin_start",
        "training_origin_end",
        "origin_frequency",
        "lag_days",
        "rolling_windows_days",
        "lag_asof_max_gap_days",
        "weekly_pattern_lookback_weeks",
        "minimum_seasonal_observations",
        "parquet_compression",
        "output_directory",
        "manifest_path",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"P2 feature config misses keys: {sorted(missing)}")
    if config["origin_frequency"] != "MS":
        raise ValueError("P2 v0.1 training origins must be month starts")
    if list(config["lag_days"]) != [1, 7, 14, 28, 56]:
        raise ValueError("P2 v0.1 lag contract changed unexpectedly")
    if list(config["rolling_windows_days"]) != [7, 14, 28, 56, 90]:
        raise ValueError("P2 v0.1 rolling window contract changed unexpectedly")
    if int(config["lag_asof_max_gap_days"]) < 0:
        raise ValueError("lag as-of tolerance cannot be negative")


def float_or_nan(value: Any) -> float:
    return float(value) if value is not None and not pd.isna(value) else float("nan")


def last_value_asof(
    dates: np.ndarray,
    prices: np.ndarray,
    desired_date: pd.Timestamp,
    max_gap_days: int,
) -> tuple[float, int | None]:
    index = int(np.searchsorted(dates, desired_date.to_datetime64(), side="right") - 1)
    if index < 0:
        return float("nan"), None
    observed_date = pd.Timestamp(dates[index])
    gap = int((desired_date - observed_date).days)
    if gap > max_gap_days:
        return float("nan"), None
    return float(prices[index]), gap


def historical_unchanged_share(dates: np.ndarray, prices: np.ndarray) -> float:
    if len(prices) < 2:
        return float("nan")
    gaps = np.diff(dates).astype("timedelta64[D]").astype(int)
    consecutive = gaps == 1
    if not bool(consecutive.any()):
        return float("nan")
    unchanged = np.isclose(prices[1:][consecutive], prices[:-1][consecutive], rtol=0.0, atol=1e-12)
    return float(unchanged.mean())


def base_features_for_origin(
    series: pd.DataFrame,
    origin: pd.Timestamp,
    origin_price: float,
    origin_price_date: pd.Timestamp,
    feature_config: dict[str, Any],
) -> dict[str, Any]:
    history = series[series["date"].le(origin)]
    dates = history["date"].to_numpy(dtype="datetime64[ns]")
    prices = history["analysis_price"].to_numpy(dtype=float)
    result: dict[str, Any] = {
        "origin_price": float(origin_price),
        "log_origin_price": float(math.log(origin_price)),
        "origin_price_date": origin_price_date.date().isoformat(),
        "origin_fill_days": int((origin - origin_price_date).days),
        "history_observation_count": int(len(history)),
        "historical_unchanged_share": historical_unchanged_share(dates, prices),
    }
    lag_tolerance = int(feature_config["lag_asof_max_gap_days"])
    for lag in feature_config["lag_days"]:
        lag = int(lag)
        value, gap = last_value_asof(
            dates,
            prices,
            origin - pd.Timedelta(days=lag),
            lag_tolerance,
        )
        result[f"lag_price_{lag}d"] = value
        result[f"lag_gap_{lag}d"] = float(gap) if gap is not None else float("nan")
        result[f"lag_missing_{lag}d"] = bool(gap is None)
        result[f"return_{lag}d"] = (
            float(math.log(origin_price / value))
            if np.isfinite(value) and value > 0
            else float("nan")
        )
    for window in feature_config["rolling_windows_days"]:
        window = int(window)
        lower = origin - pd.Timedelta(days=window - 1)
        values = history.loc[history["date"].ge(lower), "analysis_price"].to_numpy(dtype=float)
        result[f"rolling_count_{window}d"] = int(len(values))
        result[f"rolling_mean_{window}d"] = float(values.mean()) if len(values) else float("nan")
        result[f"rolling_median_{window}d"] = float(np.median(values)) if len(values) else float("nan")
        result[f"rolling_std_{window}d"] = (
            float(values.std(ddof=1)) if len(values) > 1 else 0.0 if len(values) == 1 else float("nan")
        )
    day_of_year = int(origin.dayofyear)
    result.update(
        {
            "origin_month": int(origin.month),
            "origin_day_of_year_sin": float(math.sin(2 * math.pi * day_of_year / 365.25)),
            "origin_day_of_year_cos": float(math.cos(2 * math.pi * day_of_year / 365.25)),
        }
    )
    return result


def target_seasonal_features(
    series: pd.DataFrame,
    origin: pd.Timestamp,
    target_date: pd.Timestamp,
    feature_config: dict[str, Any],
) -> dict[str, Any]:
    history = series[series["date"].le(origin)]
    target_month_history = history[history["date"].dt.month.eq(target_date.month)]["analysis_price"]
    minimum_seasonal = int(feature_config["minimum_seasonal_observations"])
    seasonal_median = (
        float(target_month_history.median())
        if len(target_month_history) >= minimum_seasonal
        else float(history["analysis_price"].median())
    )
    weekly_candidates = history[history["date"].dt.weekday.eq(target_date.weekday())].tail(
        int(feature_config["weekly_pattern_lookback_weeks"])
    )["analysis_price"]
    weekly_pattern = (
        float(weekly_candidates.median())
        if len(weekly_candidates)
        else float(history["analysis_price"].iloc[-1])
    )
    target_day_of_year = int(target_date.dayofyear)
    return {
        "target_month": int(target_date.month),
        "target_day_of_year_sin": float(
            math.sin(2 * math.pi * target_day_of_year / 365.25)
        ),
        "target_day_of_year_cos": float(
            math.cos(2 * math.pi * target_day_of_year / 365.25)
        ),
        "historical_seasonal_median": seasonal_median,
        "historical_seasonal_observation_count": int(len(target_month_history)),
        "weekly_pattern_median": weekly_pattern,
        "weekly_pattern_observation_count": int(len(weekly_candidates)),
    }


def build_split_rows(
    facts: pd.DataFrame,
    tiers: pd.DataFrame,
    products: list[dict[str, Any]],
    split_name: str,
    origins: list[pd.Timestamp],
    experiment_config: dict[str, Any],
    feature_config: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    excluded_quality = set(experiment_config["excluded_quality_flags"])
    minimum_history = int(experiment_config["minimum_history_observations"])
    max_origin_fill = int(experiment_config["origin_max_forward_fill_days"])
    official_tiers = set(experiment_config["official_tiers"])

    for product in products:
        vegetable_id = int(product["vegetable_id"])
        official_cities = sorted(
            tiers.loc[
                tiers["vegetable_id"].eq(vegetable_id)
                & tiers["coverage_tier"].isin(official_tiers),
                "city_id",
            ].astype(str)
        )
        product_facts = facts[facts["vegetable_id"].eq(vegetable_id)]
        for city_id in official_cities:
            series = product_facts[
                product_facts["city_id"].astype(str).eq(city_id)
                & product_facts["analysis_price"].gt(0)
                & ~product_facts["data_quality_flag"].isin(excluded_quality)
            ].sort_values("date")
            if series.empty:
                continue
            price_by_date = dict(zip(series["date"], series["analysis_price"].astype(float)))
            dates = series["date"].to_numpy(dtype="datetime64[ns]")
            for origin in origins:
                history_count_before_origin = int(
                    np.searchsorted(dates, origin.to_datetime64(), side="left")
                )
                if history_count_before_origin < minimum_history:
                    continue
                origin_lag = next(
                    (
                        lag
                        for lag in range(max_origin_fill + 1)
                        if origin - pd.Timedelta(days=lag) in price_by_date
                    ),
                    None,
                )
                if origin_lag is None:
                    continue
                origin_price_date = origin - pd.Timedelta(days=origin_lag)
                origin_price = float(price_by_date[origin_price_date])
                base = base_features_for_origin(
                    series,
                    origin,
                    origin_price,
                    origin_price_date,
                    feature_config,
                )
                for horizon in experiment_config["horizons_days"]:
                    horizon = int(horizon)
                    target_date = origin + pd.Timedelta(days=horizon)
                    target_price = price_by_date.get(target_date)
                    if target_price is None:
                        continue
                    seasonal = target_seasonal_features(
                        series,
                        origin,
                        target_date,
                        feature_config,
                    )
                    target_price = float(target_price)
                    price_change = target_price - origin_price
                    rows.append(
                        {
                            "split": split_name,
                            **product,
                            "city_id": city_id,
                            "origin_date": origin.date().isoformat(),
                            "horizon_days": horizon,
                            "target_date": target_date.date().isoformat(),
                            **base,
                            **seasonal,
                            "target_price": target_price,
                            "log_target_price": float(math.log(target_price)),
                            "target_price_change": float(price_change),
                            "target_log_return": float(math.log(target_price / origin_price)),
                            "target_direction": int(np.sign(price_change)),
                        }
                    )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"P2 mart split {split_name} is empty")
    frame = frame.sort_values(KEY_COLUMNS).reset_index(drop=True)
    if frame.duplicated(KEY_COLUMNS).any():
        raise ValueError(f"P2 mart split {split_name} has duplicate keys")
    for column in ["origin_date", "origin_price_date", "target_date"]:
        frame[column] = pd.to_datetime(frame[column]).dt.date
    return frame


def file_sha256(path: Path) -> str:
    return sha256(path)


def build_mart(root: Path, feature_config: dict[str, Any]) -> dict[str, Any]:
    validate_feature_config(feature_config)
    experiment_path = root / str(feature_config["experiment_config_path"])
    experiment = load_flat_yaml(experiment_path)
    validate_config(experiment)
    products = load_scope_products(root / str(experiment["scope_config_path"]))
    product_ids = [int(item["vegetable_id"]) for item in products]
    facts_path = root / str(experiment["city_fact_path"])
    tiers_path = root / str(experiment["coverage_tier_path"])
    facts = pd.read_parquet(
        facts_path,
        columns=[
            "date",
            "vegetable_id",
            "city_id",
            "analysis_price",
            "data_quality_flag",
        ],
        filters=[("vegetable_id", "in", product_ids)],
    )
    facts["date"] = pd.to_datetime(facts["date"])
    tiers = pd.read_parquet(
        tiers_path,
        columns=["vegetable_id", "city_id", "coverage_tier"],
        filters=[("vegetable_id", "in", product_ids)],
    )
    split_origins = {
        "train": monthly_origins(
            str(feature_config["training_origin_start"]),
            str(feature_config["training_origin_end"]),
            str(feature_config["origin_frequency"]),
        ),
        "validation": monthly_origins(
            str(experiment["validation_origin_start"]),
            str(experiment["validation_origin_end"]),
            str(experiment["origin_frequency"]),
        ),
        "final_test": monthly_origins(
            str(experiment["final_test_origin_start"]),
            str(experiment["final_test_origin_end"]),
            str(experiment["origin_frequency"]),
        ),
    }
    output_dir = root / str(feature_config["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    split_manifest: dict[str, Any] = {}
    feature_columns: list[str] | None = None
    schema: list[dict[str, str]] | None = None
    for split_name, origins in split_origins.items():
        frame = build_split_rows(
            facts,
            tiers,
            products,
            split_name,
            origins,
            experiment,
            feature_config,
        )
        output_path = output_dir / f"{split_name}.parquet"
        temporary_path = output_dir / f".{split_name}.parquet.tmp"
        frame.to_parquet(
            temporary_path,
            index=False,
            compression=str(feature_config["parquet_compression"]),
        )
        os.replace(temporary_path, output_path)
        if feature_columns is None:
            feature_columns = [
                column
                for column in frame.columns
                if column
                not in {
                    "split",
                    "vegetable_code",
                    "vegetable_name_zh",
                    *KEY_COLUMNS,
                    *TARGET_COLUMNS,
                }
            ]
            schema = [
                {"name": column, "dtype": str(dtype)}
                for column, dtype in frame.dtypes.items()
            ]
        split_manifest[split_name] = {
            "path": str(output_path.relative_to(root)),
            "sha256": file_sha256(output_path),
            "row_count": int(len(frame)),
            "origin_count": int(frame["origin_date"].nunique()),
            "origin_start": frame["origin_date"].min().isoformat(),
            "origin_end": frame["origin_date"].max().isoformat(),
            "target_start": frame["target_date"].min().isoformat(),
            "target_end": frame["target_date"].max().isoformat(),
            "product_count": int(frame["vegetable_id"].nunique()),
            "series_count": int(frame[["vegetable_id", "city_id"]].drop_duplicates().shape[0]),
            "horizon_row_counts": {
                str(int(key)): int(value)
                for key, value in frame["horizon_days"].value_counts().sort_index().items()
            },
        }
    manifest = {
        "mart_version": "p2_forecast_mart_v0.1",
        "feature_contract_version": feature_config["feature_contract_version"],
        "experiment_version": experiment["experiment_version"],
        "inputs": {
            str(experiment_path.relative_to(root)): sha256(experiment_path),
            str((root / "config/p2_features.yaml").relative_to(root)): sha256(
                root / "config/p2_features.yaml"
            ),
            str(facts_path.relative_to(root)): sha256(facts_path),
            str(tiers_path.relative_to(root)): sha256(tiers_path),
        },
        "key_columns": KEY_COLUMNS,
        "target_columns": TARGET_COLUMNS,
        "feature_columns": feature_columns,
        "schema": schema,
        "splits": split_manifest,
        "leakage_contract": {
            "feature_cutoff": "origin_date inclusive",
            "minimum_history_cutoff": "strictly before origin_date",
            "target_rule": "exact observed non-poor positive price at target_date",
            "origin_rule": "observed at origin_date or at most one day earlier",
            "final_test_usage": "evaluation only after model specification freeze",
        },
    }
    manifest_path = root / str(feature_config["manifest_path"])
    temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p2_features.yaml")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = build_mart(root, load_flat_yaml(root / args.config))
    print(
        json.dumps(
            {
                "mart_version": manifest["mart_version"],
                "splits": {
                    key: value["row_count"] for key, value in manifest["splits"].items()
                },
                "feature_count": len(manifest["feature_columns"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

