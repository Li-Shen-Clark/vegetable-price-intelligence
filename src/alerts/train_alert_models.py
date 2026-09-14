#!/usr/bin/env python3
"""Train and freeze the P3 logistic alert model using train/validation only."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from .audit_p3_feasibility import load_flat_yaml
    from .metrics import confusion_metrics, score_alerts
except ImportError:
    from audit_p3_feasibility import load_flat_yaml
    from metrics import confusion_metrics, score_alerts


KEY_COLUMNS = ["vegetable_id", "city_id", "origin_date"]


def validate_model_config(config: dict[str, Any]) -> None:
    required = {
        "model_contract_version",
        "experiment_config_path",
        "mart_directory",
        "baseline_scorecard_path",
        "output_directory",
        "numeric_features",
        "derived_features",
        "categorical_features",
        "ridge_strengths",
        "positive_class_weights",
        "optimizer_learning_rate",
        "optimizer_max_iterations",
        "optimizer_tolerance",
        "optimizer_patience",
        "standardized_feature_clip",
        "probability_floor",
        "probability_ceiling",
        "selection_metric",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"P3 model config misses keys: {sorted(missing)}")
    if config["selection_metric"] != "average_precision":
        raise ValueError("P3 v0.1 must select the alert model by validation Average Precision")
    if config["categorical_features"] != ["vegetable_id", "origin_month"]:
        raise ValueError("P3 v0.1 categorical contract changed unexpectedly")


def add_derived_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for window in [7, 14, 28, 56, 90]:
        rolling = pd.to_numeric(result[f"rolling_mean_{window}d"], errors="coerce")
        origin = pd.to_numeric(result["origin_price"], errors="coerce")
        result[f"origin_to_rolling_mean_{window}d_log"] = np.log(origin / rolling.where(rolling.gt(0)))
    group = result.groupby(["vegetable_id", "origin_date"], observed=True, sort=False)
    for lag in [7, 14, 28]:
        result[f"regional_median_return_{lag}d"] = group[f"return_{lag}d"].transform("median")
    result["regional_median_cv_28d"] = group["rolling_cv_28d"].transform("median")
    result["regional_up_share_14d"] = group["return_14d"].transform(
        lambda values: float(pd.to_numeric(values, errors="coerce").gt(0).mean())
    )
    result["city_minus_regional_return_14d"] = (
        result["return_14d"] - result["regional_median_return_14d"]
    )
    return result


def fit_preprocessor(
    train: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
    clip: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    columns = []
    medians: dict[str, float] = {}
    scales: dict[str, float] = {}
    feature_names = ["intercept"]
    columns.append(np.ones((len(train), 1), dtype=float))
    for feature in numeric_features:
        values = pd.to_numeric(train[feature], errors="coerce")
        median = float(values.median())
        filled = values.fillna(median).to_numpy(dtype=float)
        scale = float(filled.std(ddof=0))
        if not np.isfinite(scale) or scale < 1e-12:
            scale = 1.0
        standardized = np.clip((filled - median) / scale, -clip, clip)
        columns.append(standardized.reshape(-1, 1))
        medians[feature] = median
        scales[feature] = scale
        feature_names.append(feature)
    categories: dict[str, list[str]] = {}
    for feature in categorical_features:
        values = train[feature].astype(str)
        levels = sorted(values.dropna().unique().tolist())
        categories[feature] = levels
        for level in levels[1:]:
            columns.append(values.eq(level).to_numpy(dtype=float).reshape(-1, 1))
            feature_names.append(f"{feature}={level}")
    matrix = np.hstack(columns)
    artifact = {
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
        "numeric_medians": medians,
        "numeric_scales": scales,
        "standardized_feature_clip": clip,
        "categories": categories,
        "feature_names": feature_names,
    }
    return matrix, artifact


def transform_preprocessor(frame: pd.DataFrame, artifact: dict[str, Any]) -> np.ndarray:
    columns = [np.ones((len(frame), 1), dtype=float)]
    clip = float(artifact["standardized_feature_clip"])
    for feature in artifact["numeric_features"]:
        median = float(artifact["numeric_medians"][feature])
        scale = float(artifact["numeric_scales"][feature])
        values = pd.to_numeric(frame[feature], errors="coerce").fillna(median).to_numpy(dtype=float)
        columns.append(np.clip((values - median) / scale, -clip, clip).reshape(-1, 1))
    for feature in artifact["categorical_features"]:
        values = frame[feature].astype(str)
        for level in artifact["categories"][feature][1:]:
            columns.append(values.eq(level).to_numpy(dtype=float).reshape(-1, 1))
    return np.hstack(columns)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -30.0, 30.0)))


def fit_logistic_adam(
    matrix: np.ndarray,
    labels: np.ndarray,
    ridge_strength: float,
    positive_weight: float,
    learning_rate: float,
    max_iterations: int,
    tolerance: float,
    patience: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    coefficients = np.zeros(matrix.shape[1], dtype=float)
    prevalence = float(labels.mean())
    coefficients[0] = math.log(np.clip(prevalence, 1e-6, 1 - 1e-6) / np.clip(1 - prevalence, 1e-6, 1))
    first_moment = np.zeros_like(coefficients)
    second_moment = np.zeros_like(coefficients)
    sample_weights = np.where(labels == 1, positive_weight, 1.0).astype(float)
    weight_sum = float(sample_weights.sum())
    best_loss = float("inf")
    best_coefficients = coefficients.copy()
    stale_iterations = 0
    completed_iterations = 0

    for iteration in range(1, max_iterations + 1):
        with np.errstate(all="ignore"):
            logits = matrix @ coefficients
        if not np.isfinite(logits).all():
            raise FloatingPointError(f"non-finite training logits at iteration {iteration}")
        probabilities = _sigmoid(logits)
        residual = (probabilities - labels) * sample_weights
        with np.errstate(all="ignore"):
            gradient = matrix.T @ residual / weight_sum
        if not np.isfinite(gradient).all():
            raise FloatingPointError(f"non-finite gradient at iteration {iteration}")
        regularization = ridge_strength * coefficients
        regularization[0] = 0.0
        gradient += regularization
        first_moment = 0.9 * first_moment + 0.1 * gradient
        second_moment = 0.999 * second_moment + 0.001 * (gradient * gradient)
        corrected_first = first_moment / (1 - 0.9**iteration)
        corrected_second = second_moment / (1 - 0.999**iteration)
        coefficients -= learning_rate * corrected_first / (np.sqrt(corrected_second) + 1e-8)
        np.clip(coefficients, -20.0, 20.0, out=coefficients)

        with np.errstate(all="ignore"):
            logits = matrix @ coefficients
        if not np.isfinite(logits).all():
            raise FloatingPointError(f"non-finite updated logits at iteration {iteration}")
        probabilities = _sigmoid(logits)
        loss = float(
            -np.sum(
                sample_weights
                * (
                    labels * np.log(np.clip(probabilities, 1e-12, 1))
                    + (1 - labels) * np.log(np.clip(1 - probabilities, 1e-12, 1))
                )
            )
            / weight_sum
            + 0.5 * ridge_strength * np.sum(coefficients[1:] ** 2)
        )
        completed_iterations = iteration
        if best_loss - loss > tolerance:
            best_loss = loss
            best_coefficients = coefficients.copy()
            stale_iterations = 0
        else:
            stale_iterations += 1
            if stale_iterations >= patience:
                break
    return best_coefficients, {
        "iterations": completed_iterations,
        "converged_by_patience": completed_iterations < max_iterations,
        "best_weighted_log_loss": best_loss,
    }


def predict_from_artifact(frame: pd.DataFrame, artifact: dict[str, Any]) -> np.ndarray:
    derived = add_derived_features(frame)
    matrix = transform_preprocessor(derived, artifact["preprocessor"])
    coefficients = np.asarray(artifact["coefficients"], dtype=float)
    with np.errstate(all="ignore"):
        logits = matrix @ coefficients
    if not np.isfinite(logits).all():
        raise FloatingPointError("frozen alert model produced non-finite logits")
    probabilities = _sigmoid(logits)
    return np.clip(
        probabilities,
        float(artifact["probability_floor"]),
        float(artifact["probability_ceiling"]),
    )


def run(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    validate_model_config(config)
    experiment = load_flat_yaml(root / str(config["experiment_config_path"]))
    mart = root / str(config["mart_directory"])
    train = add_derived_features(pd.read_parquet(mart / "train.parquet"))
    validation = add_derived_features(pd.read_parquet(mart / "validation.parquet"))
    numeric = [str(item) for item in config["numeric_features"]] + [
        str(item) for item in config["derived_features"]
    ]
    categorical = [str(item) for item in config["categorical_features"]]
    train_matrix, preprocessor = fit_preprocessor(
        train,
        numeric,
        categorical,
        float(config["standardized_feature_clip"]),
    )
    validation_matrix = transform_preprocessor(validation, preprocessor)
    labels = train["event_label"].to_numpy(dtype=float)
    validation_labels = validation["event_label"].to_numpy(dtype=int)
    experiment_fpr = float(experiment["fixed_false_positive_rate"])
    floor = float(config["probability_floor"])
    ceiling = float(config["probability_ceiling"])
    candidates: list[dict[str, Any]] = []
    prediction_frames = []

    for ridge in config["ridge_strengths"]:
        for positive_weight in config["positive_class_weights"]:
            candidate_id = f"logistic_r{float(ridge):g}_pw{float(positive_weight):g}"
            coefficients, optimization = fit_logistic_adam(
                train_matrix,
                labels,
                float(ridge),
                float(positive_weight),
                float(config["optimizer_learning_rate"]),
                int(config["optimizer_max_iterations"]),
                float(config["optimizer_tolerance"]),
                int(config["optimizer_patience"]),
            )
            with np.errstate(all="ignore"):
                validation_logits = validation_matrix @ coefficients
            if not np.isfinite(validation_logits).all():
                raise FloatingPointError(f"{candidate_id} produced non-finite validation logits")
            probabilities = np.clip(_sigmoid(validation_logits), floor, ceiling)
            metrics, _ = score_alerts(
                validation_labels,
                probabilities,
                experiment_fpr,
                validation["future_peak_return_14d"],
                validation["event_lead_days"],
            )
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "ridge_strength": float(ridge),
                    "positive_class_weight": float(positive_weight),
                    "optimization": optimization,
                    "metrics": metrics,
                    "coefficients": coefficients.tolist(),
                }
            )
            item = validation[KEY_COLUMNS + ["vegetable_name_zh", "market_city", "event_label"]].copy()
            item["candidate_id"] = candidate_id
            item["risk_probability"] = probabilities
            prediction_frames.append(item)

    candidates.sort(
        key=lambda item: (
            -item["metrics"]["average_precision"],
            -item["metrics"]["threshold_at_fixed_fpr"]["recall"],
            item["metrics"]["brier_score"],
            -item["ridge_strength"],
            item["positive_class_weight"],
        )
    )
    best = candidates[0]
    baseline = json.loads(
        (root / str(config["baseline_scorecard_path"])).read_text(encoding="utf-8")
    )
    best_baseline_name = baseline["best_baseline"]
    best_baseline_ap = float(
        baseline["baselines"][best_baseline_name]["overall"]["average_precision"]
    )
    model_ap = float(best["metrics"]["average_precision"])
    ap_lift = (model_ap / best_baseline_ap - 1.0) if best_baseline_ap > 0 else None
    with np.errstate(all="ignore"):
        best_logits = validation_matrix @ np.asarray(best["coefficients"], dtype=float)
    if not np.isfinite(best_logits).all():
        raise FloatingPointError("selected candidate produced non-finite validation logits")
    best_probabilities = np.clip(_sigmoid(best_logits), floor, ceiling)
    global_threshold = float(best["metrics"]["threshold_at_fixed_fpr"]["threshold"])
    best_by_product: dict[str, Any] = {}
    for product, group in validation.groupby("vegetable_name_zh", sort=True):
        positions = group.index.to_numpy(dtype=int)
        product_metrics, _ = score_alerts(
            group["event_label"],
            best_probabilities[positions],
            experiment_fpr,
            group["future_peak_return_14d"],
            group["event_lead_days"],
        )
        product_metrics["at_global_threshold"] = confusion_metrics(
            group["event_label"], best_probabilities[positions], global_threshold
        )
        best_by_product[str(product)] = product_metrics
    frozen = {
        "model_contract_version": config["model_contract_version"],
        "model_type": "l2_logistic_regression_adam",
        "candidate_id": best["candidate_id"],
        "ridge_strength": best["ridge_strength"],
        "positive_class_weight": best["positive_class_weight"],
        "preprocessor": preprocessor,
        "coefficients": best["coefficients"],
        "probability_floor": floor,
        "probability_ceiling": ceiling,
        "validation_action_threshold": best["metrics"]["threshold_at_fixed_fpr"]["threshold"],
        "validation_fixed_fpr": experiment_fpr,
        "validation_metrics": best["metrics"],
        "best_baseline": best_baseline_name,
        "best_baseline_average_precision": best_baseline_ap,
        "validation_average_precision_lift_vs_baseline": ap_lift,
        "best_candidate_by_product": best_by_product,
        "selection_data": ["train", "validation"],
        "final_test_read": False,
    }
    scorecard = {
        "model_contract_version": config["model_contract_version"],
        "train_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "feature_count_including_intercept": int(train_matrix.shape[1]),
        "selection_rule": "highest validation Average Precision; then fixed-FPR recall, Brier, stronger ridge, lower positive weight",
        "best_candidate": best["candidate_id"],
        "best_baseline": best_baseline_name,
        "best_baseline_average_precision": best_baseline_ap,
        "validation_average_precision_lift_vs_baseline": ap_lift,
        "best_candidate_by_product": best_by_product,
        "candidates": [
            {key: value for key, value in item.items() if key != "coefficients"}
            for item in candidates
        ],
        "final_test_read": False,
    }
    output = root / str(config["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    pd.concat(prediction_frames, ignore_index=True).to_parquet(
        output / "validation_candidate_predictions.parquet", index=False, compression="zstd"
    )
    (output / "candidate_scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "frozen_alert_model.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"scorecard": scorecard, "frozen": frozen, "validation": validation}


def render_report(root: Path, result: dict[str, Any]) -> None:
    scorecard = result["scorecard"]
    frozen = result["frozen"]
    lines = [
        "# P3 概率预警模型验证报告",
        "",
        "> 候选模型只使用 train 拟合，在 validation 选择；final_test 尚未读取。",
        "",
        "## 候选比较",
        "",
        "| 候选 | L2 | 正例权重 | PR-AUC | Brier | Precision@FPR | Recall@FPR | FPR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in scorecard["candidates"]:
        metrics = item["metrics"]
        fixed = metrics["threshold_at_fixed_fpr"]
        lines.append(
            f"| {item['candidate_id']} | {item['ridge_strength']:g} | {item['positive_class_weight']:g} | "
            f"{metrics['average_precision']:.4f} | {metrics['brier_score']:.4f} | "
            f"{fixed['precision']:.2%} | {fixed['recall']:.2%} | {fixed['false_positive_rate']:.2%} |"
        )
    fixed = frozen["validation_metrics"]["threshold_at_fixed_fpr"]
    lift = frozen["validation_average_precision_lift_vs_baseline"]
    lines.extend([
        "",
        "## 冻结规格",
        "",
        f"- 候选：`{frozen['candidate_id']}`；特征（含截距）{scorecard['feature_count_including_intercept']} 个。",
        f"- validation PR-AUC：{frozen['validation_metrics']['average_precision']:.4f}；最佳简单基线：{frozen['best_baseline_average_precision']:.4f}；相对提升：{lift:.2%}。",
        f"- 冻结行动阈值：{frozen['validation_action_threshold']:.4f}；validation precision {fixed['precision']:.2%}、recall {fixed['recall']:.2%}、FPR {fixed['false_positive_rate']:.2%}。",
        "- 最终测试不得重新拟合系数、预处理、阈值或事件标签。正式发布状态只由 P3-T4 决定。",
        "",
        "## 产品级 validation 切片",
        "",
        "| 产品 | 事件率 | PR-AUC | Precision@全局阈值 | Recall@全局阈值 | FPR@全局阈值 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for product, item in scorecard["best_candidate_by_product"].items():
        fixed_product = item["at_global_threshold"]
        lines.append(
            f"| {product} | {item['prevalence']:.2%} | {item['average_precision']:.4f} | "
            f"{fixed_product['precision']:.2%} | {fixed_product['recall']:.2%} | "
            f"{fixed_product['false_positive_rate']:.2%} |"
        )
    lines.append("")
    (root / "docs/p3_alert_model_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p3_models.yaml")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / args.config)
    result = run(root, config)
    render_report(root, result)
    frozen = result["frozen"]
    print(json.dumps({
        "best_candidate": frozen["candidate_id"],
        "validation_average_precision": frozen["validation_metrics"]["average_precision"],
        "validation_average_precision_lift_vs_baseline": frozen["validation_average_precision_lift_vs_baseline"],
        "validation_action_threshold": frozen["validation_action_threshold"],
        "final_test": "not_read",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
