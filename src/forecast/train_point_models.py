#!/usr/bin/env python3
"""Train and freeze P2 point-model candidates using train and validation only."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.forecast.audit_p2_feasibility import load_flat_yaml, sha256
from src.forecast.metrics import point_metric_record, wape


KEY_COLUMNS = ["vegetable_id", "city_id", "origin_date", "horizon_days"]
OUTPUT_COLUMNS = [
    "vegetable_id",
    "vegetable_code",
    "vegetable_name_zh",
    "city_id",
    "origin_date",
    "horizon_days",
    "target_date",
    "target_price",
]


def validate_model_config(config: dict[str, Any]) -> None:
    required = {
        "model_contract_version",
        "train_mart_path",
        "validation_mart_path",
        "baseline_predictions_path",
        "baseline_scorecard_path",
        "output_directory",
        "ridge_alphas",
        "ridge_shrink_factors",
        "hurdle_alpha",
        "hurdle_change_threshold",
        "hurdle_shrink_factors",
        "damped_trend_factors",
        "weekly_blend_weights",
        "seasonal_blend_weights",
        "maximum_absolute_log_return",
        "minimum_validation_improvement",
        "minimum_improved_series_share",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"P2 model config misses keys: {sorted(missing)}")
    if any(float(value) <= 0 for value in config["ridge_alphas"]):
        raise ValueError("ridge alphas must be positive")
    if not 0 < float(config["hurdle_change_threshold"]) < 1:
        raise ValueError("hurdle change threshold must be between zero and one")


def engineered_numeric_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    direct = [
        "log_origin_price",
        "origin_fill_days",
        "history_observation_count",
        "historical_unchanged_share",
        "origin_day_of_year_sin",
        "origin_day_of_year_cos",
        "target_day_of_year_sin",
        "target_day_of_year_cos",
        "return_1d",
        "return_7d",
        "return_14d",
        "return_28d",
        "return_56d",
    ]
    for column in direct:
        result[column] = pd.to_numeric(frame[column], errors="coerce")
    origin_price = frame["origin_price"].astype(float)
    for window in [7, 14, 28, 56, 90]:
        mean_value = frame[f"rolling_mean_{window}d"].astype(float)
        median_value = frame[f"rolling_median_{window}d"].astype(float)
        std_value = frame[f"rolling_std_{window}d"].astype(float)
        result[f"rolling_mean_ratio_{window}d"] = np.log(mean_value / origin_price)
        result[f"rolling_median_ratio_{window}d"] = np.log(median_value / origin_price)
        result[f"rolling_cv_{window}d"] = std_value / mean_value
    for lag in [1, 7, 14, 28, 56]:
        result[f"lag_missing_{lag}d"] = frame[f"lag_missing_{lag}d"].astype(float)
        result[f"lag_gap_{lag}d"] = pd.to_numeric(frame[f"lag_gap_{lag}d"], errors="coerce")
    result["weekly_pattern_log_ratio"] = np.log(
        frame["weekly_pattern_median"].astype(float) / origin_price
    )
    result["seasonal_log_ratio"] = np.log(
        frame["historical_seasonal_median"].astype(float) / origin_price
    )
    return result.replace([np.inf, -np.inf], np.nan)


def category_values(frame: pd.DataFrame) -> pd.Series:
    return frame["vegetable_id"].astype(str) + ":h" + frame["horizon_days"].astype(str)


def fit_transformer(train: pd.DataFrame) -> dict[str, Any]:
    numeric = engineered_numeric_features(train)
    medians = numeric.median(axis=0, skipna=True).fillna(0.0)
    imputed = numeric.fillna(medians)
    means = imputed.mean(axis=0)
    scales = imputed.std(axis=0, ddof=0).replace(0.0, 1.0)
    categories = sorted(category_values(train).unique().tolist())
    return {
        "numeric_feature_names": numeric.columns.tolist(),
        "numeric_medians": {key: float(value) for key, value in medians.items()},
        "numeric_means": {key: float(value) for key, value in means.items()},
        "numeric_scales": {key: float(value) for key, value in scales.items()},
        "category_levels": categories,
        "fit_split": "train",
    }


def transform(frame: pd.DataFrame, transformer: dict[str, Any]) -> np.ndarray:
    numeric = engineered_numeric_features(frame)[transformer["numeric_feature_names"]]
    medians = pd.Series(transformer["numeric_medians"])
    means = pd.Series(transformer["numeric_means"])
    scales = pd.Series(transformer["numeric_scales"])
    standardized = (numeric.fillna(medians) - means) / scales
    categories = category_values(frame)
    one_hot = np.column_stack(
        [(categories == level).to_numpy(dtype=float) for level in transformer["category_levels"]]
    )
    return np.column_stack(
        [
            np.ones(len(frame), dtype=float),
            standardized.to_numpy(dtype=float),
            one_hot,
        ]
    )


def design_column_names(transformer: dict[str, Any]) -> list[str]:
    return [
        "intercept",
        *transformer["numeric_feature_names"],
        *[f"category={value}" for value in transformer["category_levels"]],
    ]


def finite_matmul(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    # NumPy 2.0 on the bundled macOS Accelerate runtime can emit false floating-point
    # warnings for finite BLAS results. Validate the result explicitly instead.
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        result = np.matmul(left, right)
    if not np.isfinite(result).all():
        raise ValueError("model matrix multiplication produced non-finite values")
    return result


def fit_ridge(design: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    gram = finite_matmul(design.T, design)
    cross_product = finite_matmul(design.T, target)
    coefficients = np.linalg.solve(gram + penalty, cross_product)
    if not np.isfinite(coefficients).all():
        raise ValueError("ridge fit produced non-finite coefficients")
    return coefficients


def price_from_log_return(
    frame: pd.DataFrame,
    predicted_return: np.ndarray,
    max_absolute_return: float,
) -> np.ndarray:
    clipped = np.clip(predicted_return, -max_absolute_return, max_absolute_return)
    return frame["origin_price"].to_numpy(dtype=float) * np.exp(clipped)


def heuristic_prediction(
    frame: pd.DataFrame,
    kind: str,
    value: float,
    maximum_absolute_log_return: float,
) -> np.ndarray:
    origin = frame["origin_price"].to_numpy(dtype=float)
    if kind == "damped_trend":
        recent = frame["return_7d"].fillna(0.0).to_numpy(dtype=float)
        horizon_scale = frame["horizon_days"].to_numpy(dtype=float) / 7.0
        returns = value * horizon_scale * recent
    elif kind == "weekly_blend":
        destination = frame["weekly_pattern_median"].to_numpy(dtype=float)
        returns = value * np.log(destination / origin)
    elif kind == "seasonal_blend":
        destination = frame["historical_seasonal_median"].to_numpy(dtype=float)
        returns = value * np.log(destination / origin)
    else:
        raise ValueError(f"unknown heuristic model kind: {kind}")
    return price_from_log_return(frame, returns, maximum_absolute_log_return)


def candidate_name(prefix: str, **values: float) -> str:
    suffix = "_".join(f"{key}{value:g}".replace(".", "p") for key, value in values.items())
    return f"{prefix}_{suffix}"


def parse_candidate(name: str) -> dict[str, Any]:
    parts = name.split("_")
    if name.startswith("ridge_"):
        return {
            "kind": "ridge",
            "alpha": float(parts[1][1:].replace("p", ".")),
            "shrink": float(parts[2][1:].replace("p", ".")),
        }
    if name.startswith("hurdle_"):
        return {
            "kind": "hurdle",
            "alpha": float(parts[1][1:].replace("p", ".")),
            "shrink": float(parts[2][1:].replace("p", ".")),
        }
    for kind in ["damped_trend", "weekly_blend", "seasonal_blend"]:
        if name.startswith(kind + "_"):
            return {"kind": kind, "value": float(parts[-1][1:].replace("p", "."))}
    raise ValueError(f"cannot parse candidate: {name}")


def predict_from_frozen(frame: pd.DataFrame, frozen: dict[str, Any]) -> np.ndarray:
    selected = frozen["selected_model"]
    kind = selected["kind"]
    maximum = float(frozen["maximum_absolute_log_return"])
    if kind in {"damped_trend", "weekly_blend", "seasonal_blend"}:
        return heuristic_prediction(frame, kind, float(selected["value"]), maximum)
    design = transform(frame, frozen["transformer"])
    if kind == "ridge":
        coefficients = np.asarray(selected["coefficients"], dtype=float)
        predicted_return = finite_matmul(design, coefficients) * float(selected["shrink"])
    elif kind == "hurdle":
        change_probability = np.clip(
            finite_matmul(
                design, np.asarray(selected["change_coefficients"], dtype=float)
            ),
            0.0,
            1.0,
        )
        changed_return = finite_matmul(
            design, np.asarray(selected["return_coefficients"], dtype=float)
        )
        predicted_return = change_probability * changed_return * float(selected["shrink"])
    else:
        raise ValueError(f"unsupported frozen model kind: {kind}")
    return price_from_log_return(frame, predicted_return, maximum)


def series_improvement_share(
    frame: pd.DataFrame,
    model_column: str,
    baseline_column: str,
) -> float:
    comparisons = []
    for _, group in frame.groupby("city_id", sort=True, observed=True):
        comparisons.append(
            wape(group["target_price"], group[model_column])
            < wape(group["target_price"], group[baseline_column])
        )
    return float(np.mean(comparisons)) if comparisons else float("nan")


def build_models(root: Path, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_model_config(config)
    train_path = root / str(config["train_mart_path"])
    validation_path = root / str(config["validation_mart_path"])
    baseline_path = root / str(config["baseline_predictions_path"])
    baseline_scorecard_path = root / str(config["baseline_scorecard_path"])
    train = pd.read_parquet(train_path)
    validation = pd.read_parquet(validation_path)
    if set(train["split"]) != {"train"} or set(validation["split"]) != {"validation"}:
        raise ValueError("point-model training accepts train and validation splits only")
    baseline_predictions = pd.read_parquet(baseline_path)
    baseline_scorecard = json.loads(baseline_scorecard_path.read_text(encoding="utf-8"))
    if baseline_scorecard["final_test_opened"]:
        raise ValueError("validation baseline artifact unexpectedly opened final test")
    baseline_map = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): row["baseline"]
        for row in baseline_scorecard["best_baselines"]
    }
    aligned = validation.merge(
        baseline_predictions[
            KEY_COLUMNS
            + ["last_valid_price", "weekly_pattern", "historical_seasonal"]
        ],
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
    )
    if aligned[["last_valid_price", "weekly_pattern", "historical_seasonal"]].isna().any().any():
        raise ValueError("baseline rows do not align with validation mart")
    aligned["best_baseline_name"] = [
        baseline_map[(int(vegetable_id), int(horizon))]
        for vegetable_id, horizon in zip(aligned["vegetable_id"], aligned["horizon_days"])
    ]
    aligned["best_baseline_prediction"] = [
        aligned.iloc[index][name]
        for index, name in enumerate(aligned["best_baseline_name"])
    ]

    transformer = fit_transformer(train)
    train_design = transform(train, transformer)
    validation_design = transform(aligned, transformer)
    target_return = train["target_log_return"].to_numpy(dtype=float)
    max_return = float(config["maximum_absolute_log_return"])
    ridge_coefficients: dict[float, np.ndarray] = {}
    candidate_predictions: dict[str, np.ndarray] = {}
    candidate_parameters: dict[str, dict[str, Any]] = {}

    for alpha_value in config["ridge_alphas"]:
        alpha = float(alpha_value)
        coefficients = fit_ridge(train_design, target_return, alpha)
        ridge_coefficients[alpha] = coefficients
        base_return = finite_matmul(validation_design, coefficients)
        for shrink_value in config["ridge_shrink_factors"]:
            shrink = float(shrink_value)
            name = candidate_name("ridge", a=alpha, s=shrink)
            candidate_predictions[name] = price_from_log_return(
                aligned,
                base_return * shrink,
                max_return,
            )
            candidate_parameters[name] = {
                "kind": "ridge",
                "alpha": alpha,
                "shrink": shrink,
                "coefficients": coefficients.tolist(),
            }

    hurdle_alpha = float(config["hurdle_alpha"])
    changed = np.abs(target_return) > float(config["hurdle_change_threshold"])
    change_coefficients = fit_ridge(train_design, changed.astype(float), hurdle_alpha)
    return_coefficients = fit_ridge(
        train_design[changed],
        target_return[changed],
        hurdle_alpha,
    )
    probability = np.clip(finite_matmul(validation_design, change_coefficients), 0.0, 1.0)
    changed_return = finite_matmul(validation_design, return_coefficients)
    for shrink_value in config["hurdle_shrink_factors"]:
        shrink = float(shrink_value)
        name = candidate_name("hurdle", a=hurdle_alpha, s=shrink)
        candidate_predictions[name] = price_from_log_return(
            aligned,
            probability * changed_return * shrink,
            max_return,
        )
        candidate_parameters[name] = {
            "kind": "hurdle",
            "alpha": hurdle_alpha,
            "change_threshold": float(config["hurdle_change_threshold"]),
            "shrink": shrink,
            "change_coefficients": change_coefficients.tolist(),
            "return_coefficients": return_coefficients.tolist(),
        }

    heuristic_grids = {
        "damped_trend": config["damped_trend_factors"],
        "weekly_blend": config["weekly_blend_weights"],
        "seasonal_blend": config["seasonal_blend_weights"],
    }
    for kind, values in heuristic_grids.items():
        for raw_value in values:
            value = float(raw_value)
            name = candidate_name(kind, w=value)
            candidate_predictions[name] = heuristic_prediction(
                aligned,
                kind,
                value,
                max_return,
            )
            candidate_parameters[name] = {"kind": kind, "value": value}

    candidate_scores = []
    for name, prediction in candidate_predictions.items():
        candidate_scores.append(
            {
                "candidate": name,
                **point_metric_record(aligned["target_price"], prediction),
            }
        )
    selected_score = min(candidate_scores, key=lambda item: (item["wape"], item["candidate"]))
    selected_name = str(selected_score["candidate"])
    selected_prediction = candidate_predictions[selected_name]
    aligned["selected_model_prediction"] = selected_prediction

    group_decisions: list[dict[str, Any]] = []
    for (vegetable_id, vegetable_name, horizon), group in aligned.groupby(
        ["vegetable_id", "vegetable_name_zh", "horizon_days"],
        sort=True,
        observed=True,
    ):
        model_metrics = point_metric_record(group["target_price"], group["selected_model_prediction"])
        baseline_metrics = point_metric_record(group["target_price"], group["best_baseline_prediction"])
        relative_improvement = 1.0 - model_metrics["wape"] / baseline_metrics["wape"]
        improvement_share = series_improvement_share(
            group,
            "selected_model_prediction",
            "best_baseline_prediction",
        )
        use_model = (
            relative_improvement > float(config["minimum_validation_improvement"])
            and improvement_share > float(config["minimum_improved_series_share"])
        )
        group_decisions.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_name_zh": str(vegetable_name),
                "horizon_days": int(horizon),
                "row_count": int(len(group)),
                "model_wape": model_metrics["wape"],
                "best_baseline": str(group["best_baseline_name"].iloc[0]),
                "baseline_wape": baseline_metrics["wape"],
                "relative_wape_improvement": round(float(relative_improvement), 8),
                "improved_series_share": round(float(improvement_share), 8),
                "validation_route": "model_candidate" if use_model else "baseline_fallback",
            }
        )

    frozen = {
        "model_version": "p2_point_model_v0.1",
        "status": "frozen_after_validation",
        "selection_split": "validation",
        "final_test_opened": False,
        "training_target": "target_log_return",
        "maximum_absolute_log_return": max_return,
        "transformer": transformer,
        "design_columns": design_column_names(transformer),
        "selected_model_name": selected_name,
        "selected_model": candidate_parameters[selected_name],
        "selected_validation_metrics": selected_score,
        "best_baseline_validation_metrics": point_metric_record(
            aligned["target_price"], aligned["best_baseline_prediction"]
        ),
        "group_decisions": group_decisions,
        "inputs": {
            str(train_path.relative_to(root)): sha256(train_path),
            str(validation_path.relative_to(root)): sha256(validation_path),
            str(baseline_path.relative_to(root)): sha256(baseline_path),
            str(baseline_scorecard_path.relative_to(root)): sha256(baseline_scorecard_path),
        },
    }
    replay = predict_from_frozen(aligned, frozen)
    if not np.allclose(replay, selected_prediction, rtol=0.0, atol=1e-12):
        raise ValueError("frozen model does not reproduce selected validation predictions")

    prediction_output = aligned[OUTPUT_COLUMNS + [
        "best_baseline_name",
        "best_baseline_prediction",
    ]].copy()
    for name in sorted(candidate_predictions):
        prediction_output[name] = candidate_predictions[name]
    prediction_output["selected_model_name"] = selected_name
    prediction_output["selected_model_prediction"] = selected_prediction

    output_dir = root / str(config["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / "validation_candidate_predictions.parquet"
    temporary_prediction = output_dir / ".validation_candidate_predictions.parquet.tmp"
    prediction_output.to_parquet(temporary_prediction, index=False, compression="zstd")
    os.replace(temporary_prediction, prediction_path)

    scorecard = {
        "scorecard_version": "p2_point_candidates_v0.1",
        "status": "frozen_after_validation",
        "final_test_opened": False,
        "selected_model_name": selected_name,
        "candidate_count": len(candidate_scores),
        "candidate_scores": sorted(candidate_scores, key=lambda item: (item["wape"], item["candidate"])),
        "best_baseline_metrics": frozen["best_baseline_validation_metrics"],
        "group_decisions": group_decisions,
        "predictions": {
            "path": str(prediction_path.relative_to(root)),
            "sha256": sha256(prediction_path),
            "row_count": int(len(prediction_output)),
        },
    }
    frozen_path = output_dir / "frozen_point_model.json"
    scorecard_path = output_dir / "candidate_scorecard.json"
    frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scorecard_path.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return frozen, scorecard


def render_report(frozen: dict[str, Any], scorecard: dict[str, Any]) -> str:
    selected = scorecard["candidate_scores"][0]
    baseline = scorecard["best_baseline_metrics"]
    overall_improvement = 1.0 - selected["wape"] / baseline["wape"]
    model_routes = sum(
        row["validation_route"] == "model_candidate" for row in scorecard["group_decisions"]
    )
    lines = [
        "# P2 确定性点预测模型报告",
        "",
        "> 状态：主模型规格已在 validation 上冻结；最终测试未打开。  ",
        f"> 主模型：`{frozen['selected_model_name']}`",
        "",
        "## 1. 选择结果",
        "",
        f"共比较 {scorecard['candidate_count']} 个候选规格。全验证集最低 WAPE 的候选为 `{frozen['selected_model_name']}`：WAPE {selected['wape']:.2%}，最佳分组基线组合为 {baseline['wape']:.2%}，相对改善 {overall_improvement:.2%}。",
        "",
        f"按照“WAPE 正改善且超过 50% 城市序列改善”的验证门槛，{model_routes}/30 个产品×跨度暂列为模型候选，其余先标为基线回退。最终发布由 P2-T5 的冻结测试决定。",
        "",
        "## 2. 候选模型总体排名",
        "",
        "| 排名 | 候选 | WAPE | MAE | sMAPE |",
        "|---:|---|---:|---:|---:|",
    ]
    for rank, row in enumerate(scorecard["candidate_scores"][:12], 1):
        lines.append(
            f"| {rank} | `{row['candidate']}` | {row['wape']:.2%} | {row['mae']:.3f} | {row['smape']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 3. 产品×跨度验证路由",
            "",
            "| 产品 | 跨度 | 模型 WAPE | 基线 WAPE | 相对改善 | 改善城市占比 | 验证路由 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in scorecard["group_decisions"]:
        route = "模型候选" if row["validation_route"] == "model_candidate" else "基线回退"
        lines.append(
            f"| {row['vegetable_name_zh']} | {row['horizon_days']}日 | {row['model_wape']:.2%} | "
            f"{row['baseline_wape']:.2%} | {row['relative_wape_improvement']:.2%} | "
            f"{row['improved_series_share']:.1%} | {route} |"
        )
    lines.extend(
        [
            "",
            "## 4. 解释与限制",
            "",
            "- 岭模型的缺失中位数、均值、标准差和系数只从 train 拟合；validation 只用于候选选择。",
            "- Hurdle 候选先估计超过 1% 的变价概率，再估计变化样本的对数收益；它是可解释的两阶段线性近似，不是最终业务变价分类器。",
            "- 当前环境没有 LightGBM、CatBoost 或 scikit-learn。本轮使用 NumPy 闭式岭回归，避免临时安装重量级依赖并保持模型 JSON 可复算。",
            "- 复杂模型不自动获得发布资格。每个未通过切片会在最终产品中回退到已经冻结的简单基线。",
            "- 本报告不是最终测试成绩；`final_test.parquet` 未被本任务读取。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p2_models.yaml")
    parser.add_argument("--report", default="docs/p2_point_model_report.md")
    args = parser.parse_args()
    root = args.root.resolve()
    frozen, scorecard = build_models(root, load_flat_yaml(root / args.config))
    (root / args.report).write_text(render_report(frozen, scorecard), encoding="utf-8")
    print(
        json.dumps(
            {
                "selected_model": frozen["selected_model_name"],
                "candidate_count": scorecard["candidate_count"],
                "validation_wape": frozen["selected_validation_metrics"]["wape"],
                "baseline_wape": frozen["best_baseline_validation_metrics"]["wape"],
                "model_candidate_groups": sum(
                    row["validation_route"] == "model_candidate"
                    for row in frozen["group_decisions"]
                ),
                "final_test_opened": frozen["final_test_opened"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
