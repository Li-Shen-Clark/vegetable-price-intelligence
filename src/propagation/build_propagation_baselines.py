#!/usr/bin/env python3
"""Build public-factor diagnostics and the frozen target-only P5 baseline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml, sha256, write_json
from src.propagation.modeling import (
    add_exact_lags,
    fit_ols,
    predict_ols,
    regression_metrics,
)


def _mean_absolute_pairwise_correlation(frame: pd.DataFrame, value: str) -> tuple[float, float, int]:
    pivot = frame.pivot(index="bin_start", columns="city_id", values=value)
    correlation = pivot.corr(min_periods=30).to_numpy(dtype=float)
    if correlation.size == 0:
        return float("nan"), float("nan"), 0
    upper = np.abs(correlation[np.triu_indices_from(correlation, k=1)])
    upper = upper[np.isfinite(upper)]
    return float(upper.mean()), float(np.median(upper)), int(len(upper))


def common_factor_diagnostics(panel: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (vegetable_id, vegetable_code, vegetable_name, split), group in panel.loc[
        panel["split"].isin(["train", "validation"])
    ].groupby(
        ["vegetable_id", "vegetable_code", "vegetable_name_zh", "split"],
        observed=True,
    ):
        raw_mean, raw_median, raw_pairs = _mean_absolute_pairwise_correlation(
            group, "log_return"
        )
        residual_mean, residual_median, residual_pairs = _mean_absolute_pairwise_correlation(
            group, "propagation_residual"
        )
        rows.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": vegetable_code,
                "vegetable_name_zh": vegetable_name,
                "split": split,
                "raw_mean_absolute_correlation": raw_mean,
                "raw_median_absolute_correlation": raw_median,
                "residual_mean_absolute_correlation": residual_mean,
                "residual_median_absolute_correlation": residual_median,
                "raw_pair_count": raw_pairs,
                "residual_pair_count": residual_pairs,
                "mean_absolute_correlation_reduction": (
                    (raw_mean - residual_mean) / raw_mean if raw_mean > 0 else float("nan")
                ),
            }
        )
    return rows


def build_baseline(
    panel: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    lags = [int(value) for value in config["primary_lags_bins"]]
    lagged = add_exact_lags(
        panel,
        value_columns=["propagation_residual", "common_factor_loo"],
        lags=lags,
        bin_days=int(config["primary_bin_days"]),
    )
    features = [f"propagation_residual_lag{lag}" for lag in lags] + [
        f"common_factor_loo_lag{lag}" for lag in lags
    ]
    required = ["propagation_residual", *features]
    usable = lagged.loc[
        lagged[required].notna().all(axis=1) & lagged["split"].isin(["train", "validation"])
    ].copy()
    predictions: list[pd.DataFrame] = []
    scores: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for keys, group in usable.groupby(
        ["vegetable_id", "vegetable_code", "vegetable_name_zh", "city_id", "city_name_zh"],
        observed=True,
    ):
        train = group.loc[group["split"].eq("train")]
        validation = group.loc[group["split"].eq("validation")]
        if len(train) < int(config["minimum_model_train_rows"]) or len(validation) < int(
            config["minimum_model_validation_rows"]
        ):
            continue
        coefficients = fit_ols(train, "propagation_residual", features)
        model_row = {
            "vegetable_id": int(keys[0]),
            "city_id": keys[3],
            "feature_names": ["intercept", *features],
            "coefficients": [float(value) for value in coefficients],
            "fit_end": str(config["train_end"]),
        }
        models.append(model_row)
        for split, sample in [("train", train), ("validation", validation)]:
            actual = sample["propagation_residual"].to_numpy(float)
            predicted = predict_ols(sample, features, coefficients)
            zero = np.zeros(len(sample), dtype=float)
            metrics = regression_metrics(actual, predicted)
            zero_metrics = regression_metrics(actual, zero)
            scores.append(
                {
                    "vegetable_id": int(keys[0]),
                    "vegetable_code": keys[1],
                    "vegetable_name_zh": keys[2],
                    "city_id": keys[3],
                    "city_name_zh": keys[4],
                    "split": split,
                    "rows": metrics["rows"],
                    "baseline_rmse": metrics["rmse"],
                    "baseline_mae": metrics["mae"],
                    "zero_rmse": zero_metrics["rmse"],
                    "zero_mae": zero_metrics["mae"],
                }
            )
            if split == "validation":
                output = sample[
                    [
                        "bin_start",
                        "vegetable_id",
                        "vegetable_code",
                        "vegetable_name_zh",
                        "city_id",
                        "city_name_zh",
                        "propagation_residual",
                    ]
                ].copy()
                output["baseline_prediction"] = predicted
                output["zero_prediction"] = 0.0
                output["model_fit_end"] = str(config["train_end"])
                predictions.append(output)
    prediction_frame = pd.concat(predictions, ignore_index=True)
    score_frame = pd.DataFrame(scores)
    return prediction_frame, score_frame, models


def aggregate_scores(scores: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for keys, group in scores.groupby(
        ["vegetable_id", "vegetable_code", "vegetable_name_zh", "split"], observed=True
    ):
        weights = group["rows"].to_numpy(float)
        rows.append(
            {
                "vegetable_id": int(keys[0]),
                "vegetable_code": keys[1],
                "vegetable_name_zh": keys[2],
                "split": keys[3],
                "series": int(len(group)),
                "rows": int(group["rows"].sum()),
                "baseline_rmse_weighted": float(np.average(group["baseline_rmse"], weights=weights)),
                "baseline_mae_weighted": float(np.average(group["baseline_mae"], weights=weights)),
                "zero_rmse_weighted": float(np.average(group["zero_rmse"], weights=weights)),
                "zero_mae_weighted": float(np.average(group["zero_mae"], weights=weights)),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p5_propagation_experiment.yaml")
    panel_path = root / config["propagation_mart_dir"] / "primary_panel.parquet"
    panel = pd.read_parquet(panel_path)
    diagnostics = common_factor_diagnostics(panel)
    predictions, scores, models = build_baseline(panel, config)

    output_dir = root / config["baseline_artifact_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "validation_predictions.parquet"
    scores_path = output_dir / "series_scorecard.parquet"
    predictions.to_parquet(predictions_path, index=False)
    scores.to_parquet(scores_path, index=False)
    payload = {
        "baseline_version": "p5_target_common_ar_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "frozen",
        "target": "propagation_residual",
        "features": {
            "target_lags": config["primary_lags_bins"],
            "common_factor_lags": config["primary_lags_bins"],
        },
        "splits_evaluated": ["train", "validation"],
        "final_test_evaluated": False,
        "common_factor_diagnostics": diagnostics,
        "aggregate_scores": aggregate_scores(scores),
        "models": models,
        "files": {
            "validation_predictions": {
                "path": str(predictions_path.relative_to(root)),
                "rows": int(len(predictions)),
                "sha256": sha256(predictions_path),
            },
            "series_scorecard": {
                "path": str(scores_path.relative_to(root)),
                "rows": int(len(scores)),
                "sha256": sha256(scores_path),
            },
        },
        "input": {"path": str(panel_path.relative_to(root)), "sha256": sha256(panel_path)},
    }
    write_json(output_dir / "baseline_scorecard.json", payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "validation_prediction_rows": len(predictions),
                "modeled_series": len(models),
                "final_test_evaluated": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
