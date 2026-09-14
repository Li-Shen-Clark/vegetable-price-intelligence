#!/usr/bin/env python3
"""Calibrate and freeze P2 multiplicative P10/P50/P90 intervals."""

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
from src.forecast.metrics import probability_metric_record


KEY_COLUMNS = ["vegetable_id", "city_id", "origin_date", "horizon_days"]


def validate_probability_config(config: dict[str, Any]) -> None:
    required = {
        "probability_contract_version",
        "validation_mart_path",
        "point_predictions_path",
        "frozen_point_model_path",
        "output_directory",
        "calibration_start",
        "calibration_end",
        "evaluation_start",
        "evaluation_end",
        "central_interval_alpha",
        "minimum_group_calibration_rows",
        "width_scale_candidates",
        "target_coverage_lower",
        "target_coverage_upper",
        "target_coverage_midpoint",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"P2 probability config misses keys: {sorted(missing)}")
    if not (
        pd.Timestamp(config["calibration_start"])
        <= pd.Timestamp(config["calibration_end"])
        < pd.Timestamp(config["evaluation_start"])
        <= pd.Timestamp(config["evaluation_end"])
    ):
        raise ValueError("calibration and evaluation periods must be ordered and disjoint")
    if not 0 < float(config["central_interval_alpha"]) < 1:
        raise ValueError("central interval alpha must be between zero and one")


def conformal_quantile(values: Any, alpha: float) -> tuple[float, float]:
    residuals = np.asarray(values, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    if residuals.size == 0:
        raise ValueError("conformal residual pool is empty")
    order = min(residuals.size, math.ceil((residuals.size + 1) * (1.0 - alpha)))
    level = order / residuals.size
    return float(np.sort(residuals)[order - 1]), float(level)


def route_point_predictions(
    mart: pd.DataFrame,
    predictions: pd.DataFrame,
    frozen_point: dict[str, Any],
) -> pd.DataFrame:
    columns = KEY_COLUMNS + [
        "best_baseline_name",
        "best_baseline_prediction",
        "selected_model_name",
        "selected_model_prediction",
    ]
    frame = mart.merge(
        predictions[columns],
        on=KEY_COLUMNS,
        how="left",
        validate="one_to_one",
    )
    if frame[["best_baseline_prediction", "selected_model_prediction"]].isna().any().any():
        raise ValueError("point prediction rows do not align with validation mart")
    route_map = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): row["validation_route"]
        for row in frozen_point["group_decisions"]
    }
    use_model = np.array(
        [
            route_map[(int(vegetable_id), int(horizon))] == "model_candidate"
            for vegetable_id, horizon in zip(frame["vegetable_id"], frame["horizon_days"])
        ],
        dtype=bool,
    )
    frame["point_source"] = np.where(
        use_model,
        frozen_point["selected_model_name"],
        "baseline:" + frame["best_baseline_name"].astype(str),
    )
    frame["point_prediction"] = np.where(
        use_model,
        frame["selected_model_prediction"],
        frame["best_baseline_prediction"],
    )
    frame["absolute_log_residual"] = np.abs(
        np.log(frame["target_price"].to_numpy(dtype=float))
        - np.log(frame["point_prediction"].to_numpy(dtype=float))
    )
    return frame


def fit_group_quantiles(
    frame: pd.DataFrame,
    alpha: float,
    minimum_group_rows: int,
) -> list[dict[str, Any]]:
    horizon_pools = {
        int(horizon): group["absolute_log_residual"].to_numpy(dtype=float)
        for horizon, group in frame.groupby("horizon_days", sort=True, observed=True)
    }
    global_pool = frame["absolute_log_residual"].to_numpy(dtype=float)
    records = []
    for (vegetable_id, vegetable_name, horizon), group in frame.groupby(
        ["vegetable_id", "vegetable_name_zh", "horizon_days"],
        sort=True,
        observed=True,
    ):
        group_values = group["absolute_log_residual"].to_numpy(dtype=float)
        if len(group_values) >= minimum_group_rows:
            values = group_values
            level_name = "product_horizon"
        elif len(horizon_pools[int(horizon)]) >= minimum_group_rows:
            values = horizon_pools[int(horizon)]
            level_name = "horizon"
        else:
            values = global_pool
            level_name = "global"
        quantile, quantile_level = conformal_quantile(values, alpha)
        records.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_name_zh": str(vegetable_name),
                "horizon_days": int(horizon),
                "calibration_level": level_name,
                "group_row_count": int(len(group_values)),
                "calibration_row_count": int(len(values)),
                "conformal_quantile_level": round(quantile_level, 8),
                "absolute_log_residual_quantile": round(quantile, 12),
            }
        )
    return records


def apply_intervals(
    frame: pd.DataFrame,
    quantiles: list[dict[str, Any]],
    width_scale: float,
) -> pd.DataFrame:
    quantile_map = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): float(
            row["absolute_log_residual_quantile"]
        )
        for row in quantiles
    }
    widths = np.array(
        [
            quantile_map[(int(vegetable_id), int(horizon))] * float(width_scale)
            for vegetable_id, horizon in zip(frame["vegetable_id"], frame["horizon_days"])
        ],
        dtype=float,
    )
    result = frame.copy()
    median = result["point_prediction"].to_numpy(dtype=float)
    result["p10"] = median * np.exp(-widths)
    result["p50"] = median
    result["p90"] = median * np.exp(widths)
    result["interval_log_half_width"] = widths
    result["interval_width_scale"] = float(width_scale)
    if not (
        result["p10"].gt(0).all()
        and result["p10"].le(result["p50"]).all()
        and result["p50"].le(result["p90"]).all()
    ):
        raise ValueError("probability interval ordering or positivity failed")
    return result


def score_probability(frame: pd.DataFrame) -> dict[str, Any]:
    return probability_metric_record(
        frame["target_price"], frame["p10"], frame["p50"], frame["p90"]
    )


def select_scale(candidate_scores: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    lower = float(config["target_coverage_lower"])
    upper = float(config["target_coverage_upper"])
    midpoint = float(config["target_coverage_midpoint"])
    in_band = [
        row for row in candidate_scores if lower <= row["interval_coverage_80"] <= upper
    ]
    if in_band:
        return min(in_band, key=lambda row: (row["wis_80"], row["width_scale"]))
    return min(
        candidate_scores,
        key=lambda row: (
            abs(row["interval_coverage_80"] - midpoint),
            row["wis_80"],
            row["width_scale"],
        ),
    )


def build_calibrator(root: Path, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_probability_config(config)
    mart_path = root / str(config["validation_mart_path"])
    prediction_path = root / str(config["point_predictions_path"])
    frozen_point_path = root / str(config["frozen_point_model_path"])
    mart = pd.read_parquet(mart_path)
    predictions = pd.read_parquet(prediction_path)
    frozen_point = json.loads(frozen_point_path.read_text(encoding="utf-8"))
    if set(mart["split"]) != {"validation"} or frozen_point["final_test_opened"]:
        raise ValueError("probability calibration accepts validation artifacts only")
    routed = route_point_predictions(mart, predictions, frozen_point)
    origin = pd.to_datetime(routed["origin_date"])
    calibration_mask = origin.between(
        pd.Timestamp(config["calibration_start"]),
        pd.Timestamp(config["calibration_end"]),
    )
    evaluation_mask = origin.between(
        pd.Timestamp(config["evaluation_start"]),
        pd.Timestamp(config["evaluation_end"]),
    )
    calibration = routed[calibration_mask].copy()
    evaluation = routed[evaluation_mask].copy()
    if calibration.empty or evaluation.empty or bool((calibration_mask & evaluation_mask).any()):
        raise ValueError("probability calibration/evaluation split is invalid")
    alpha = float(config["central_interval_alpha"])
    minimum_rows = int(config["minimum_group_calibration_rows"])
    initial_quantiles = fit_group_quantiles(calibration, alpha, minimum_rows)
    candidate_scores = []
    for raw_scale in config["width_scale_candidates"]:
        scale = float(raw_scale)
        candidate = apply_intervals(evaluation, initial_quantiles, scale)
        candidate_scores.append({"width_scale": scale, **score_probability(candidate)})
    selected_scale_record = select_scale(candidate_scores, config)
    selected_scale = float(selected_scale_record["width_scale"])
    validation_intervals = apply_intervals(routed, initial_quantiles, selected_scale)
    validation_intervals["interval_phase"] = np.where(
        calibration_mask, "calibration_fit", "temporal_evaluation"
    )
    evaluation_intervals = validation_intervals[evaluation_mask]

    group_evaluation = []
    for (vegetable_id, vegetable_name, horizon), group in evaluation_intervals.groupby(
        ["vegetable_id", "vegetable_name_zh", "horizon_days"],
        sort=True,
        observed=True,
    ):
        group_evaluation.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_name_zh": str(vegetable_name),
                "horizon_days": int(horizon),
                **score_probability(group),
            }
        )
    final_quantiles = fit_group_quantiles(routed, alpha, minimum_rows)
    frozen_calibrator = {
        "calibrator_version": "p2_interval_calibrator_v0.1",
        "status": "frozen_after_validation",
        "selection_split": "validation_temporal_holdout",
        "final_test_opened": False,
        "interval": {"p10": 0.1, "p50": 0.5, "p90": 0.9, "alpha": alpha},
        "method": "symmetric_multiplicative_split_conformal_on_absolute_log_residual",
        "selected_width_scale": selected_scale,
        "scale_selection_metrics": selected_scale_record,
        "final_group_quantiles": final_quantiles,
        "inputs": {
            str(mart_path.relative_to(root)): sha256(mart_path),
            str(prediction_path.relative_to(root)): sha256(prediction_path),
            str(frozen_point_path.relative_to(root)): sha256(frozen_point_path),
        },
    }
    output_dir = root / str(config["output_directory"])
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_columns = [
        "vegetable_id",
        "vegetable_code",
        "vegetable_name_zh",
        "city_id",
        "origin_date",
        "horizon_days",
        "target_date",
        "target_price",
        "point_source",
        "point_prediction",
        "p10",
        "p50",
        "p90",
        "interval_log_half_width",
        "interval_width_scale",
        "interval_phase",
    ]
    output_path = output_dir / "validation_probability_predictions.parquet"
    temporary_path = output_dir / ".validation_probability_predictions.parquet.tmp"
    validation_intervals[detail_columns].to_parquet(
        temporary_path, index=False, compression="zstd"
    )
    os.replace(temporary_path, output_path)
    scorecard = {
        "scorecard_version": "p2_probability_validation_v0.1",
        "status": "frozen_after_validation",
        "final_test_opened": False,
        "calibration_row_count": int(len(calibration)),
        "temporal_evaluation_row_count": int(len(evaluation)),
        "initial_group_quantiles": initial_quantiles,
        "width_scale_candidates": candidate_scores,
        "selected_width_scale": selected_scale,
        "temporal_evaluation_metrics": score_probability(evaluation_intervals),
        "group_temporal_evaluation": group_evaluation,
        "final_group_quantiles": final_quantiles,
        "predictions": {
            "path": str(output_path.relative_to(root)),
            "sha256": sha256(output_path),
            "row_count": int(len(validation_intervals)),
        },
    }
    frozen_path = output_dir / "frozen_interval_calibrator.json"
    scorecard_path = output_dir / "calibration_scorecard.json"
    frozen_path.write_text(
        json.dumps(frozen_calibrator, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    scorecard_path.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return frozen_calibrator, scorecard


def render_report(calibrator: dict[str, Any], scorecard: dict[str, Any]) -> str:
    metrics = scorecard["temporal_evaluation_metrics"]
    in_band = 0.75 <= metrics["interval_coverage_80"] <= 0.85
    lines = [
        "# P2 概率预测与区间校准报告",
        "",
        "> 状态：validation 校准器已冻结；最终测试未打开。  ",
        f"> 选定宽度系数：{scorecard['selected_width_scale']:.2f}",
        "",
        "## 1. 时间顺序设计",
        "",
        f"2020-01 至 2020-08 的 {scorecard['calibration_row_count']:,} 行用于估计 absolute log residual 分位数；2020-09 至 2020-12 的 {scorecard['temporal_evaluation_row_count']:,} 行只用于比较宽度系数和报告校准表现。选定后，最终校准器用 2020 全年 residual 重算，并冻结供 P2-T5 使用。",
        "",
        "## 2. 宽度系数比较",
        "",
        "| 宽度系数 | 80% 覆盖率 | 平均宽度 | WIS | P10 loss | P50 loss | P90 loss |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in scorecard["width_scale_candidates"]:
        marker = " **← 选定**" if row["width_scale"] == scorecard["selected_width_scale"] else ""
        lines.append(
            f"| {row['width_scale']:.2f}{marker} | {row['interval_coverage_80']:.1%} | "
            f"{row['mean_interval_width']:.3f} | {row['wis_80']:.3f} | "
            f"{row['pinball_loss_p10']:.3f} | {row['pinball_loss_p50']:.3f} | "
            f"{row['pinball_loss_p90']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## 3. 时间后段评估结论",
            "",
            f"选定区间的 80% 覆盖率为 {metrics['interval_coverage_80']:.1%}，平均宽度 {metrics['mean_interval_width']:.3f} 元/kg，WIS {metrics['wis_80']:.3f}。覆盖率{'落在' if in_band else '未落在'} 75%–85% 目标带内。",
            "",
            "## 4. 产品×跨度校准",
            "",
            "| 产品 | 跨度 | 覆盖率 | 平均宽度 | WIS | 行数 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in scorecard["group_temporal_evaluation"]:
        lines.append(
            f"| {row['vegetable_name_zh']} | {row['horizon_days']}日 | "
            f"{row['interval_coverage_80']:.1%} | {row['mean_interval_width']:.3f} | "
            f"{row['wis_80']:.3f} | {row['row_count']} |"
        )
    fallback_counts: dict[str, int] = {}
    for row in calibrator["final_group_quantiles"]:
        level = row["calibration_level"]
        fallback_counts[level] = fallback_counts.get(level, 0) + 1
    lines.extend(
        [
            "",
            "## 5. 边界与回退",
            "",
            f"最终 30 个产品×跨度校准组的层级分布为：{', '.join(f'{key}={value}' for key, value in sorted(fallback_counts.items()))}。",
            "",
            "- 区间在 log-price 空间对称，因此价格下界始终为正且 P10 ≤ P50 ≤ P90。",
            "- P50 与 T3 路由完全一致；基线回退切片不会被概率模块重新包装成复杂模型预测。",
            "- 时间后段评估仍属于 validation，不是最终测试。真正发布资格只由 P2-T5 冻结测试决定。",
            "- 区间覆盖率必须结合宽度和 WIS；宽区间本身不代表更好的决策信息。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p2_probability.yaml")
    parser.add_argument("--report", default="docs/p2_probability_report.md")
    args = parser.parse_args()
    root = args.root.resolve()
    calibrator, scorecard = build_calibrator(root, load_flat_yaml(root / args.config))
    (root / args.report).write_text(render_report(calibrator, scorecard), encoding="utf-8")
    metrics = scorecard["temporal_evaluation_metrics"]
    print(
        json.dumps(
            {
                "selected_width_scale": scorecard["selected_width_scale"],
                "coverage_80": metrics["interval_coverage_80"],
                "mean_interval_width": metrics["mean_interval_width"],
                "wis_80": metrics["wis_80"],
                "final_test_opened": scorecard["final_test_opened"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
