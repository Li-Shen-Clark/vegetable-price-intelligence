#!/usr/bin/env python3
"""Build leakage-safe P3 event labels and weekly alert features."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from .audit_p3_feasibility import (
        load_flat_yaml,
        load_scope_products,
        sha256,
        validate_config,
        weekly_origins,
    )
except ImportError:  # Support direct execution from the repository root.
    from audit_p3_feasibility import (
        load_flat_yaml,
        load_scope_products,
        sha256,
        validate_config,
        weekly_origins,
    )


KEY_COLUMNS = ["vegetable_id", "city_id", "origin_date"]
IDENTITY_COLUMNS = [
    "vegetable_id",
    "vegetable_code",
    "vegetable_name_zh",
    "city_id",
    "market_city",
    "market_province",
]


def validate_feature_config(config: dict[str, Any]) -> None:
    required = {
        "feature_contract_version",
        "experiment_config_path",
        "lag_days",
        "rolling_windows_days",
        "lag_asof_max_gap_days",
        "recent_direction_window_days",
        "event_rate_window_days",
        "parquet_compression",
        "output_directory",
        "manifest_path",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"P3 feature config misses keys: {sorted(missing)}")
    if list(config["lag_days"]) != [1, 7, 14, 28, 56]:
        raise ValueError("P3 v0.1 lag contract changed unexpectedly")
    if list(config["rolling_windows_days"]) != [7, 14, 28, 56, 90]:
        raise ValueError("P3 v0.1 rolling-window contract changed unexpectedly")
    if int(config["event_rate_window_days"]) != 364:
        raise ValueError("P3 v0.1 historical event-rate window must be 52 weeks")


def _last_asof(
    dates: np.ndarray,
    values: np.ndarray,
    desired: pd.Timestamp,
    max_gap_days: int,
) -> tuple[float, int | None]:
    index = int(np.searchsorted(dates, desired.to_datetime64(), side="right") - 1)
    if index < 0:
        return float("nan"), None
    gap = int((desired - pd.Timestamp(dates[index])).days)
    if gap > max_gap_days:
        return float("nan"), None
    return float(values[index]), gap


def _unchanged_share(dates: np.ndarray, prices: np.ndarray) -> float:
    if len(prices) < 2:
        return float("nan")
    consecutive = np.diff(dates).astype("timedelta64[D]").astype(int) == 1
    if not bool(consecutive.any()):
        return float("nan")
    unchanged = np.isclose(
        prices[1:][consecutive], prices[:-1][consecutive], rtol=0.0, atol=1e-12
    )
    return float(unchanged.mean())


def _series_rows(
    group: pd.DataFrame,
    origins_by_split: dict[str, list[pd.Timestamp]],
    experiment: dict[str, Any],
    features: dict[str, Any],
) -> list[dict[str, Any]]:
    valid = group[
        group["analysis_price"].gt(0)
        & ~group["data_quality_flag"].isin(experiment["excluded_quality_flags"])
    ].sort_values("date").reset_index(drop=True)
    if valid.empty:
        return []
    dates = valid["date"].to_numpy(dtype="datetime64[ns]")
    prices = valid["analysis_price"].to_numpy(dtype=float)
    stale = valid["stale_quote_share"].to_numpy(dtype=float)
    outlier = valid["outlier_share"].to_numpy(dtype=float)
    reliability = valid["source_reliability_score"].to_numpy(dtype=float)
    quality = valid["data_quality_flag"].astype(str).to_numpy()
    months = valid["date"].dt.month.to_numpy(dtype=int)
    consecutive = np.diff(dates).astype("timedelta64[D]").astype(int) == 1
    unchanged = consecutive & np.isclose(prices[1:], prices[:-1], rtol=0.0, atol=1e-12)
    consecutive_by_history_count = np.zeros(len(dates) + 1, dtype=int)
    unchanged_by_history_count = np.zeros(len(dates) + 1, dtype=int)
    if len(dates) > 1:
        consecutive_by_history_count[2:] = np.cumsum(consecutive)
        unchanged_by_history_count[2:] = np.cumsum(unchanged)
    minimum_history = int(experiment["minimum_history_observations"])
    minimum_future = int(experiment["minimum_future_observations"])
    max_fill = int(experiment["origin_max_forward_fill_days"])
    horizon = int(experiment["target_horizon_days"])
    lag_tolerance = int(features["lag_asof_max_gap_days"])
    rows: list[dict[str, Any]] = []
    identity = {column: group.iloc[0][column] for column in IDENTITY_COLUMNS}

    for split, origins in origins_by_split.items():
        for origin in origins:
            origin64 = origin.to_datetime64()
            history_end = int(np.searchsorted(dates, origin64, side="right"))
            history_count_before = int(np.searchsorted(dates, origin64, side="left"))
            if history_count_before < minimum_history:
                continue
            origin_index = None
            origin_lag = None
            for lag in range(max_fill + 1):
                candidate = (origin - pd.Timedelta(days=lag)).to_datetime64()
                position = int(np.searchsorted(dates, candidate, side="left"))
                if position < len(dates) and dates[position] == candidate:
                    origin_index = position
                    origin_lag = lag
                    break
            if origin_index is None:
                continue
            future_start = int(np.searchsorted(dates, origin64, side="right"))
            target_end = origin + pd.Timedelta(days=horizon)
            future_end = int(np.searchsorted(dates, target_end.to_datetime64(), side="right"))
            future_prices = prices[future_start:future_end]
            future_dates = dates[future_start:future_end]
            if len(future_prices) < minimum_future:
                continue

            origin_price = float(prices[origin_index])
            history_dates = dates[:history_end]
            history_prices = prices[:history_end]
            peak_position = int(np.argmax(future_prices))
            peak_price = float(future_prices[peak_position])
            peak_date = pd.Timestamp(future_dates[peak_position])
            future_returns = future_prices / origin_price - 1.0
            transition_count = int(consecutive_by_history_count[history_end])
            row: dict[str, Any] = {
                "split": split,
                **identity,
                "origin_date": origin,
                "origin_price_date": pd.Timestamp(dates[origin_index]),
                "origin_fill_days": int(origin_lag),
                "origin_price": origin_price,
                "log_origin_price": float(math.log(origin_price)),
                "origin_data_quality_flag": str(quality[origin_index]),
                "origin_stale_quote_share": float(stale[origin_index]),
                "origin_outlier_share": float(outlier[origin_index]),
                "origin_source_reliability_score": float(reliability[origin_index]),
                "history_observation_count": int(history_count_before),
                "historical_unchanged_share": (
                    float(unchanged_by_history_count[history_end] / transition_count)
                    if transition_count
                    else float("nan")
                ),
                "target_window_start": origin + pd.Timedelta(days=1),
                "target_window_end": target_end,
                "future_observation_count": int(len(future_prices)),
                "future_peak_price": peak_price,
                "future_peak_date": peak_date,
                "future_peak_return_14d": float(peak_price / origin_price - 1.0),
                "_future_dates": future_dates,
                "_future_returns": future_returns,
            }
            for lag in features["lag_days"]:
                lag = int(lag)
                value, gap = _last_asof(
                    history_dates,
                    history_prices,
                    origin - pd.Timedelta(days=lag),
                    lag_tolerance,
                )
                row[f"lag_price_{lag}d"] = value
                row[f"lag_gap_{lag}d"] = float(gap) if gap is not None else float("nan")
                row[f"lag_missing_{lag}d"] = bool(gap is None)
                row[f"return_{lag}d"] = (
                    float(math.log(origin_price / value))
                    if np.isfinite(value) and value > 0
                    else float("nan")
                )
            for window in features["rolling_windows_days"]:
                window = int(window)
                lower = (origin - pd.Timedelta(days=window - 1)).to_datetime64()
                start = int(np.searchsorted(history_dates, lower, side="left"))
                window_prices = history_prices[start:]
                window_stale = stale[start:history_end]
                window_outlier = outlier[start:history_end]
                row[f"rolling_count_{window}d"] = int(len(window_prices))
                row[f"rolling_mean_{window}d"] = float(window_prices.mean()) if len(window_prices) else float("nan")
                row[f"rolling_median_{window}d"] = float(np.median(window_prices)) if len(window_prices) else float("nan")
                row[f"rolling_std_{window}d"] = (
                    float(window_prices.std(ddof=1)) if len(window_prices) > 1 else 0.0
                )
                row[f"rolling_cv_{window}d"] = (
                    float(window_prices.std(ddof=1) / window_prices.mean())
                    if len(window_prices) > 1 and window_prices.mean() > 0
                    else 0.0
                )
                row[f"rolling_stale_share_{window}d"] = float(window_stale.mean()) if len(window_stale) else float("nan")
                row[f"rolling_outlier_share_{window}d"] = float(window_outlier.mean()) if len(window_outlier) else float("nan")

            direction_days = int(features["recent_direction_window_days"])
            direction_start = int(
                np.searchsorted(
                    history_dates,
                    (origin - pd.Timedelta(days=direction_days)).to_datetime64(),
                    side="left",
                )
            )
            recent_prices = history_prices[direction_start:]
            changes = np.diff(recent_prices)
            row["recent_up_day_share_14d"] = float((changes > 0).mean()) if len(changes) else float("nan")
            row["recent_down_day_share_14d"] = float((changes < 0).mean()) if len(changes) else float("nan")
            same_month_prices = history_prices[months[:history_end] == origin.month]
            seasonal_median = float(np.median(same_month_prices)) if len(same_month_prices) else float(np.median(history_prices))
            row["historical_same_month_count"] = int(len(same_month_prices))
            row["historical_same_month_median"] = seasonal_median
            row["origin_vs_seasonal_log_ratio"] = float(math.log(origin_price / seasonal_median))
            day_of_year = int(origin.dayofyear)
            row["origin_month"] = int(origin.month)
            row["origin_day_of_year_sin"] = float(math.sin(2 * math.pi * day_of_year / 365.25))
            row["origin_day_of_year_cos"] = float(math.cos(2 * math.pi * day_of_year / 365.25))
            rows.append(row)
    return rows


def _quantile(values: list[float], quantile: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), quantile))


def attach_seasonal_thresholds(frame: pd.DataFrame, experiment: dict[str, Any]) -> pd.DataFrame:
    ordered = frame.sort_values(["origin_date", "vegetable_id", "city_id"]).reset_index(drop=True)
    quantiles = [float(value) for value in experiment["sensitivity_seasonal_quantiles"]]
    pools: dict[str, defaultdict[Any, list[float]]] = {
        "series_month": defaultdict(list),
        "series_all": defaultdict(list),
        "product_month": defaultdict(list),
        "product_all": defaultdict(list),
        "global": defaultdict(list),
    }
    pending = ordered.sort_values("target_window_end").reset_index().to_dict("records")
    pending_index = 0
    threshold_columns = {quantile: np.full(len(ordered), np.nan) for quantile in quantiles}
    count_values = np.zeros(len(ordered), dtype=int)
    level_values = np.full(len(ordered), "unavailable", dtype=object)
    latest_values = np.full(len(ordered), np.datetime64("NaT"), dtype="datetime64[ns]")
    min_series_month = int(experiment["seasonal_min_city_product_month"])
    min_series_all = int(experiment["seasonal_min_city_product_all"])
    min_product_month = int(experiment["seasonal_min_product_month"])
    latest_completed_end = np.datetime64("NaT")

    for origin, indices in ordered.groupby("origin_date", sort=True).groups.items():
        origin = pd.Timestamp(origin)
        while pending_index < len(pending) and pd.Timestamp(pending[pending_index]["target_window_end"]) <= origin:
            record = pending[pending_index]
            value = float(record["future_peak_return_14d"])
            vegetable_id = int(record["vegetable_id"])
            city_id = str(record["city_id"])
            month = int(pd.Timestamp(record["origin_date"]).month)
            pools["series_month"][(vegetable_id, city_id, month)].append(value)
            pools["series_all"][(vegetable_id, city_id)].append(value)
            pools["product_month"][(vegetable_id, month)].append(value)
            pools["product_all"][vegetable_id].append(value)
            pools["global"]["all"].append(value)
            latest_completed_end = np.datetime64(record["target_window_end"])
            pending_index += 1

        cache: dict[tuple[str, Any], tuple[list[float], str]] = {}
        for index in indices:
            vegetable_id = int(ordered.at[index, "vegetable_id"])
            city_id = str(ordered.at[index, "city_id"])
            month = int(origin.month)
            candidates = [
                ("city_product_month", pools["series_month"][(vegetable_id, city_id, month)], min_series_month),
                ("city_product_all", pools["series_all"][(vegetable_id, city_id)], min_series_all),
                ("product_month", pools["product_month"][(vegetable_id, month)], min_product_month),
                ("product_all", pools["product_all"][vegetable_id], 1),
                ("global", pools["global"]["all"], 1),
            ]
            selected_level = "unavailable"
            selected: list[float] = []
            for level, values, minimum in candidates:
                if len(values) >= minimum:
                    selected_level = level
                    selected = values
                    break
            if not selected:
                continue
            cache_key: tuple[str, Any]
            if selected_level == "city_product_month":
                cache_key = (selected_level, (vegetable_id, city_id, month))
            elif selected_level == "city_product_all":
                cache_key = (selected_level, (vegetable_id, city_id))
            elif selected_level == "product_month":
                cache_key = (selected_level, (vegetable_id, month))
            elif selected_level == "product_all":
                cache_key = (selected_level, vegetable_id)
            else:
                cache_key = (selected_level, "all")
            if cache_key not in cache:
                cache[cache_key] = (selected, selected_level)
            values, level = cache[cache_key]
            for quantile in quantiles:
                threshold_columns[quantile][index] = _quantile(values, quantile)
            count_values[index] = len(values)
            level_values[index] = level
            latest_values[index] = latest_completed_end

    for quantile, values in threshold_columns.items():
        ordered[f"seasonal_threshold_q{int(round(quantile * 100))}"] = values
    ordered["seasonal_threshold_history_count"] = count_values
    ordered["seasonal_threshold_level"] = level_values
    ordered["seasonal_history_latest_window_end"] = latest_values
    return ordered


def attach_event_labels(frame: pd.DataFrame, experiment: dict[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    abs_thresholds = [float(value) for value in experiment["sensitivity_absolute_thresholds"]]
    seasonal_quantiles = [float(value) for value in experiment["sensitivity_seasonal_quantiles"]]
    dedup_days = int(experiment["event_deduplication_days"])
    result["primary_raw_event"] = False
    for absolute in abs_thresholds:
        abs_label = int(round(absolute * 100))
        for quantile in seasonal_quantiles:
            quantile_label = int(round(quantile * 100))
            raw_column = f"raw_event_abs{abs_label}_q{quantile_label}"
            event_column = f"event_label_abs{abs_label}_q{quantile_label}"
            threshold_column = f"seasonal_threshold_q{quantile_label}"
            result[raw_column] = (
                result["future_peak_return_14d"].ge(absolute)
                & result["future_peak_return_14d"].ge(result[threshold_column])
                & result[threshold_column].notna()
            )
            result[event_column] = False
            for _, indices in result.groupby(["vegetable_id", "city_id"], sort=False).groups.items():
                ordered_indices = sorted(indices, key=lambda idx: result.at[idx, "origin_date"])
                last_onset: pd.Timestamp | None = None
                for index in ordered_indices:
                    if not bool(result.at[index, raw_column]):
                        continue
                    origin = pd.Timestamp(result.at[index, "origin_date"])
                    if last_onset is None or (origin - last_onset).days > dedup_days:
                        result.at[index, event_column] = True
                        last_onset = origin
            if abs_label == 20 and quantile_label == 90:
                result["primary_raw_event"] = result[raw_column]
                result["event_label"] = result[event_column].astype(bool)

    effective = np.maximum(
        float(experiment["absolute_spike_threshold"]),
        result["seasonal_threshold_q90"].to_numpy(dtype=float),
    )
    lead_days = np.full(len(result), np.nan)
    crossing_dates = np.full(len(result), np.datetime64("NaT"), dtype="datetime64[ns]")
    for index in result.index[result["event_label"]]:
        returns = np.asarray(result.at[index, "_future_returns"], dtype=float)
        dates = np.asarray(result.at[index, "_future_dates"], dtype="datetime64[ns]")
        crossing = np.flatnonzero(returns >= effective[index])
        if len(crossing):
            crossing_date = pd.Timestamp(dates[int(crossing[0])])
            crossing_dates[index] = crossing_date.to_datetime64()
            lead_days[index] = float((crossing_date - pd.Timestamp(result.at[index, "origin_date"])).days)
    result["event_effective_return_threshold"] = effective
    result["event_crossing_date"] = crossing_dates
    result["event_lead_days"] = lead_days
    return result


def attach_historical_event_rates(frame: pd.DataFrame, feature_config: dict[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    window_days = int(feature_config["event_rate_window_days"])
    series_rate = np.full(len(result), np.nan)
    series_count = np.zeros(len(result), dtype=int)
    series_all_rate = np.full(len(result), np.nan)
    product_rate = np.full(len(result), np.nan)
    product_count = np.zeros(len(result), dtype=int)

    for _, indices in result.groupby(["vegetable_id", "city_id"], sort=False).groups.items():
        ordered_indices = np.asarray(
            sorted(indices, key=lambda idx: result.at[idx, "origin_date"]), dtype=int
        )
        origins = pd.to_datetime(result.loc[ordered_indices, "origin_date"]).to_numpy()
        target_ends = pd.to_datetime(result.loc[ordered_indices, "target_window_end"]).to_numpy()
        labels = result.loc[ordered_indices, "event_label"].to_numpy(dtype=float)
        available_pointer = 0
        recent_pointer = 0
        recent_event_sum = 0.0
        all_event_sum = 0.0
        available_count = 0
        for position, index in enumerate(ordered_indices):
            origin = origins[position]
            while available_pointer < len(ordered_indices) and target_ends[available_pointer] <= origin:
                available_label = labels[available_pointer]
                all_event_sum += available_label
                recent_event_sum += available_label
                available_count += 1
                available_pointer += 1
            lower = origin - np.timedelta64(window_days, "D")
            while recent_pointer < available_pointer and origins[recent_pointer] < lower:
                recent_event_sum -= labels[recent_pointer]
                recent_pointer += 1
            recent_count = available_pointer - recent_pointer
            if available_count:
                series_all_rate[index] = all_event_sum / available_count
            if recent_count:
                series_count[index] = recent_count
                series_rate[index] = recent_event_sum / recent_count

    for _, indices in result.groupby("vegetable_id", sort=False).groups.items():
        product_indices = np.asarray(list(indices), dtype=int)
        product_origin_values = pd.to_datetime(
            result.loc[product_indices, "origin_date"]
        ).to_numpy()
        product = result.loc[product_indices, ["origin_date", "target_window_end", "event_label"]].copy()
        weekly = (
            product.groupby(["origin_date", "target_window_end"], as_index=False)
            .agg(event_sum=("event_label", "sum"), row_count=("event_label", "size"))
            .sort_values("origin_date")
            .reset_index(drop=True)
        )
        origins = pd.to_datetime(weekly["origin_date"]).to_numpy()
        target_ends = pd.to_datetime(weekly["target_window_end"]).to_numpy()
        event_sums = weekly["event_sum"].to_numpy(dtype=float)
        row_counts = weekly["row_count"].to_numpy(dtype=int)
        available_pointer = 0
        recent_pointer = 0
        recent_event_sum = 0.0
        recent_row_count = 0
        for position, origin in enumerate(origins):
            while available_pointer < len(weekly) and target_ends[available_pointer] <= origin:
                recent_event_sum += event_sums[available_pointer]
                recent_row_count += int(row_counts[available_pointer])
                available_pointer += 1
            lower = origin - np.timedelta64(window_days, "D")
            while recent_pointer < available_pointer and origins[recent_pointer] < lower:
                recent_event_sum -= event_sums[recent_pointer]
                recent_row_count -= int(row_counts[recent_pointer])
                recent_pointer += 1
            current_indices = product_indices[product_origin_values == origin]
            if recent_row_count:
                product_count[current_indices] = recent_row_count
                product_rate[current_indices] = recent_event_sum / recent_row_count

    result["historical_event_count_series_52w"] = series_count
    result["historical_event_rate_series_52w"] = series_rate
    result["historical_event_rate_series_all"] = series_all_rate
    result["historical_event_count_product_52w"] = product_count
    result["historical_event_rate_product_52w"] = product_rate
    return result


def build_mart(root: Path, feature_config: dict[str, Any]) -> dict[str, Any]:
    validate_feature_config(feature_config)
    experiment_path = root / str(feature_config["experiment_config_path"])
    experiment = load_flat_yaml(experiment_path)
    validate_config(experiment)
    products = load_scope_products(root / str(experiment["scope_config_path"]))
    product_ids = [int(item["vegetable_id"]) for item in products]
    fact_path = root / str(experiment["city_fact_path"])
    tier_path = root / str(experiment["coverage_tier_path"])
    facts = pd.read_parquet(
        fact_path,
        columns=[
            "date",
            "vegetable_id",
            "vegetable_code",
            "vegetable_name_zh",
            "city_id",
            "market_city",
            "market_province",
            "analysis_price",
            "stale_quote_share",
            "outlier_share",
            "source_reliability_score",
            "data_quality_flag",
        ],
        filters=[("vegetable_id", "in", product_ids)],
    )
    facts["date"] = pd.to_datetime(facts["date"])
    tiers = pd.read_parquet(
        tier_path,
        columns=["vegetable_id", "city_id", "coverage_tier"],
        filters=[("vegetable_id", "in", product_ids)],
    )
    official = tiers[tiers["coverage_tier"].isin(experiment["official_tiers"])][
        ["vegetable_id", "city_id"]
    ].drop_duplicates()
    facts = facts.merge(official, on=["vegetable_id", "city_id"], how="inner")
    origins_by_split = {
        split: weekly_origins(
            str(experiment[f"{split}_origin_start"]),
            str(experiment[f"{split}_origin_end"]),
            str(experiment["origin_frequency"]),
        )
        for split in ["train", "validation", "final_test"]
    }

    rows: list[dict[str, Any]] = []
    for _, group in facts.groupby(IDENTITY_COLUMNS, observed=True, sort=True):
        rows.extend(_series_rows(group, origins_by_split, experiment, feature_config))
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("P3 alert mart is empty")
    frame = frame.sort_values(KEY_COLUMNS).reset_index(drop=True)
    if frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("P3 alert mart has duplicate keys")
    frame = attach_seasonal_thresholds(frame, experiment)
    frame = frame[frame["seasonal_threshold_level"].ne("unavailable")].reset_index(drop=True)
    frame = attach_event_labels(frame, experiment)
    frame = attach_historical_event_rates(frame, feature_config)
    frame = frame.drop(columns=["_future_dates", "_future_returns"])

    date_columns = [
        "origin_date",
        "origin_price_date",
        "target_window_start",
        "target_window_end",
        "future_peak_date",
        "seasonal_history_latest_window_end",
        "event_crossing_date",
    ]
    for column in date_columns:
        frame[column] = pd.to_datetime(frame[column]).dt.date

    output_dir = root / str(feature_config["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    split_manifest: dict[str, Any] = {}
    schema: list[dict[str, str]] | None = None
    for split in ["train", "validation", "final_test"]:
        subset = frame[frame["split"].eq(split)].sort_values(KEY_COLUMNS).reset_index(drop=True)
        output_path = output_dir / f"{split}.parquet"
        temporary = output_dir / f".{split}.parquet.tmp"
        subset.to_parquet(
            temporary,
            index=False,
            compression=str(feature_config["parquet_compression"]),
        )
        os.replace(temporary, output_path)
        if schema is None:
            schema = [{"name": column, "dtype": str(dtype)} for column, dtype in subset.dtypes.items()]
        split_manifest[split] = {
            "path": str(output_path.relative_to(root)),
            "rows": int(len(subset)),
            "eligible_series": int(subset[["vegetable_id", "city_id"]].drop_duplicates().shape[0]),
            "eligible_origins": int(subset["origin_date"].nunique()),
            "sha256": sha256(output_path),
        }

    manifest = {
        "feature_contract_version": feature_config["feature_contract_version"],
        "experiment_version": experiment["experiment_version"],
        "inputs": {
            str(experiment["city_fact_path"]): sha256(fact_path),
            str(experiment["coverage_tier_path"]): sha256(tier_path),
            str(feature_config["experiment_config_path"]): sha256(experiment_path),
        },
        "key_columns": KEY_COLUMNS,
        "schema": schema,
        "splits": split_manifest,
        "label_contract": {
            "primary": "event_label_abs20_q90",
            "target_horizon_days": int(experiment["target_horizon_days"]),
            "event_deduplication_days": int(experiment["event_deduplication_days"]),
            "sensitivity_absolute_thresholds": experiment["sensitivity_absolute_thresholds"],
            "sensitivity_seasonal_quantiles": experiment["sensitivity_seasonal_quantiles"],
        },
        "final_test_label_summary_withheld_until_t4": True,
    }
    manifest_path = root / str(feature_config["manifest_path"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def render_feature_dictionary(root: Path, manifest: dict[str, Any]) -> None:
    content = """# P3 预警 mart 字段字典

## 粒度与切分

每行是一个 `vegetable_id + city_id + origin_date` 周度预警任务。`split` 固定为 train、validation 或 final_test；三者目标窗口不交叉。final_test 标签已经独立物化，但在 P3-T4 前不得用于模型、特征或阈值选择。

## 身份与起点

- `vegetable_*`、`city_id`、`market_city`、`market_province`：产品和城市身份。
- `origin_date`、`origin_price_date`、`origin_fill_days`：计划预警日、实际起点价格日和最多 1 天的填充标记。
- `origin_price`、`log_origin_price`：起点价格及对数。
- `origin_*quality*`、`origin_stale_quote_share`、`origin_outlier_share`、`origin_source_reliability_score`：起点时可见的数据质量。

## 历史特征

- `lag_price_*`、`lag_gap_*`、`lag_missing_*`、`return_*`：1/7/14/28/56 日 as-of 价格、间隔、缺失和对数变化。
- `rolling_*`：7/14/28/56/90 日价格均值、中位数、标准差、变异系数、有效天数和质量均值。
- `recent_up_day_share_14d`、`recent_down_day_share_14d`：最近 14 日有效价格变动方向。
- `historical_same_month_*`、`origin_vs_seasonal_log_ratio`：只使用起点以前同月价格的季节参照。
- `historical_event_rate_*`：只使用目标窗口已在当前起点前结束的历史事件；52 周率和全历史率分别保留。

## 目标与事件标签

- `future_peak_*`：未来 14 日真实有效观测的峰值、日期和相对涨幅；只用于训练/评估。
- `seasonal_threshold_q90/q95`：由当前起点以前已经完成的历史 14 日窗口计算的分位阈值。
- `seasonal_threshold_level/count`：阈值回退层级与历史样本数。
- `raw_event_abs*_q*`：绝对涨幅与历史季节阈值同时满足的重叠窗口。
- `event_label_abs*_q*`：在 raw event 上再做同序列 21 天去重后的事件起点。
- `event_label`：正式 `abs20_q90` 标签；`primary_raw_event` 是其去重前窗口。
- `event_effective_return_threshold`、`event_crossing_date`、`event_lead_days`：正式事件的实际门槛、首次跨越日和 1–14 日提前量。

## 泄漏边界

模型输入不得包含任何 `future_*`、`target_*`、`seasonal_threshold_*`、`raw_event_*`、`event_label*`、`event_crossing_date`、`event_lead_days` 字段。所有模型特征列表必须在 `config/p3_models.yaml` 中显式白名单冻结。
"""
    (root / "docs/p3_feature_dictionary.md").write_text(content, encoding="utf-8")


def render_label_audit(root: Path, manifest: dict[str, Any]) -> None:
    output_dir = root / "data/modeling/p3_alert_mart"
    train = pd.read_parquet(output_dir / "train.parquet")
    validation = pd.read_parquet(output_dir / "validation.parquet")
    frames = {"train": train, "validation": validation}
    lines = [
        "# P3 事件标签审计",
        "",
        "> 只报告 train 与 validation；final_test 标签统计在 P3-T4 冻结模型后才打开。",
        "",
        "## 主标签",
        "",
        "| 切分 | 合格行 | 原始重叠窗口 | 去重事件 | 事件率 | 平均提前量 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for split, frame in frames.items():
        events = frame[frame["event_label"]]
        lines.append(
            f"| {split} | {len(frame):,} | {int(frame['primary_raw_event'].sum()):,} | "
            f"{len(events):,} | {frame['event_label'].mean():.2%} | "
            f"{events['event_lead_days'].mean():.2f} 天 |"
        )
    lines.extend([
        "",
        "## validation 产品分布",
        "",
        "| 产品 | 合格行 | 事件 | 事件率 |",
        "|---|---:|---:|---:|",
    ])
    for name, group in validation.groupby("vegetable_name_zh", sort=True):
        lines.append(f"| {name} | {len(group):,} | {int(group['event_label'].sum()):,} | {group['event_label'].mean():.2%} |")
    lines.extend([
        "",
        "## 防泄漏与去重检查",
        "",
        "- 所有季节阈值仅使用 `target_window_end <= origin_date` 的历史窗口。",
        "- 同一产品—城市的正式事件起点间隔严格大于 21 天。",
        "- 起点与未来目标过滤 poor 价格；未来目标不插值、不前向填充。",
        "- final_test 仅独立物化，未在本报告读取或汇总标签。",
    ])
    (root / "docs/p3_event_label_audit.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p3_features.yaml")
    args = parser.parse_args()
    root = args.root.resolve()
    feature_config = load_flat_yaml(root / args.config)
    manifest = build_mart(root, feature_config)
    render_feature_dictionary(root, manifest)
    render_label_audit(root, manifest)
    print(json.dumps({"splits": manifest["splits"], "final_test_labels": "withheld_until_t4"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
