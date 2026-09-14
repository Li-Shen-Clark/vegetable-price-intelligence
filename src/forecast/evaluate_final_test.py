#!/usr/bin/env python3
"""Apply frozen P2 point and interval models to the one-time final test split."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.forecast.audit_p2_feasibility import load_flat_yaml, sha256
from src.forecast.calibrate_intervals import apply_intervals
from src.forecast.metrics import point_metric_record, probability_metric_record, wape
from src.forecast.train_point_models import predict_from_frozen


KEY_COLUMNS = ["vegetable_id", "city_id", "origin_date", "horizon_days"]


def series_improvement_share(frame: pd.DataFrame) -> float:
    results = []
    for _, group in frame.groupby("city_id", sort=True, observed=True):
        results.append(
            wape(group["target_price"], group["model_prediction"])
            < wape(group["target_price"], group["best_baseline_prediction"])
        )
    return float(np.mean(results)) if results else float("nan")


def baseline_predictions(
    frame: pd.DataFrame,
    baseline_scorecard: dict[str, Any],
) -> pd.DataFrame:
    source_columns = {
        "last_valid_price": "origin_price",
        "weekly_pattern": "weekly_pattern_median",
        "historical_seasonal": "historical_seasonal_median",
    }
    best_map = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): row["baseline"]
        for row in baseline_scorecard["best_baselines"]
    }
    result = frame.copy()
    result["best_baseline_name"] = [
        best_map[(int(vegetable_id), int(horizon))]
        for vegetable_id, horizon in zip(result["vegetable_id"], result["horizon_days"])
    ]
    result["best_baseline_prediction"] = [
        result.iloc[index][source_columns[name]]
        for index, name in enumerate(result["best_baseline_name"])
    ]
    return result


def release_status(
    validation_route: str,
    relative_improvement: float,
    improvement_share: float,
    coverage: float,
) -> str:
    if validation_route != "model_candidate":
        return "baseline_fallback"
    point_passes = relative_improvement > 0 and improvement_share > 0.5
    if not point_passes:
        return "baseline_fallback"
    interval_passes = 0.75 <= coverage <= 0.85
    if not interval_passes:
        return "point_only_model"
    if relative_improvement >= 0.08:
        return "model_target"
    return "model_minimum"


def build_final_evaluation(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    experiment = load_flat_yaml(root / "config/p2_experiment.yaml")
    final_path = root / "data/modeling/p2_forecast_mart/final_test.parquet"
    baseline_scorecard_path = root / "artifacts/p2/baselines/validation_scorecard.json"
    frozen_point_path = root / "artifacts/p2/models/frozen_point_model.json"
    frozen_calibrator_path = root / "artifacts/p2/probability/frozen_interval_calibrator.json"
    final_frame = pd.read_parquet(final_path)
    if set(final_frame["split"]) != {"final_test"}:
        raise ValueError("P2-T5 requires the isolated final_test mart")
    baseline_scorecard = json.loads(baseline_scorecard_path.read_text(encoding="utf-8"))
    frozen_point = json.loads(frozen_point_path.read_text(encoding="utf-8"))
    frozen_calibrator = json.loads(frozen_calibrator_path.read_text(encoding="utf-8"))
    if frozen_point["status"] != "frozen_after_validation" or frozen_calibrator["status"] != "frozen_after_validation":
        raise ValueError("point model and interval calibrator must be frozen before final test")

    evaluated = baseline_predictions(final_frame, baseline_scorecard)
    evaluated["model_prediction"] = predict_from_frozen(evaluated, frozen_point)
    validation_route_map = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): row["validation_route"]
        for row in frozen_point["group_decisions"]
    }
    evaluated["validation_route"] = [
        validation_route_map[(int(vegetable_id), int(horizon))]
        for vegetable_id, horizon in zip(evaluated["vegetable_id"], evaluated["horizon_days"])
    ]
    evaluated["validation_routed_point"] = np.where(
        evaluated["validation_route"].eq("model_candidate"),
        evaluated["model_prediction"],
        evaluated["best_baseline_prediction"],
    )
    interval_frame = evaluated.rename(
        columns={"validation_routed_point": "point_prediction"}
    )
    interval_frame = apply_intervals(
        interval_frame,
        frozen_calibrator["final_group_quantiles"],
        float(frozen_calibrator["selected_width_scale"]),
    )
    evaluated["p10"] = interval_frame["p10"]
    evaluated["p50"] = interval_frame["p50"]
    evaluated["p90"] = interval_frame["p90"]

    group_results: list[dict[str, Any]] = []
    for (vegetable_id, vegetable_name, horizon), group in evaluated.groupby(
        ["vegetable_id", "vegetable_name_zh", "horizon_days"],
        sort=True,
        observed=True,
    ):
        model_metrics = point_metric_record(group["target_price"], group["model_prediction"])
        baseline_metrics = point_metric_record(
            group["target_price"], group["best_baseline_prediction"]
        )
        relative_improvement = 1.0 - model_metrics["wape"] / baseline_metrics["wape"]
        improvement_share = series_improvement_share(group)
        probability_metrics = probability_metric_record(
            group["target_price"], group["p10"], group["p50"], group["p90"]
        )
        validation_route = str(group["validation_route"].iloc[0])
        status = release_status(
            validation_route,
            relative_improvement,
            improvement_share,
            probability_metrics["interval_coverage_80"],
        )
        group_results.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_name_zh": str(vegetable_name),
                "horizon_days": int(horizon),
                "row_count": int(len(group)),
                "validation_route": validation_route,
                "best_baseline": str(group["best_baseline_name"].iloc[0]),
                "model_metrics": model_metrics,
                "baseline_metrics": baseline_metrics,
                "relative_wape_improvement": round(float(relative_improvement), 8),
                "improved_series_share": round(float(improvement_share), 8),
                "probability_metrics": probability_metrics,
                "release_status": status,
                "release_point_source": (
                    frozen_point["selected_model_name"]
                    if status != "baseline_fallback"
                    else f"baseline:{group['best_baseline_name'].iloc[0]}"
                ),
                "release_interval": status in {"model_target", "model_minimum"},
            }
        )

    release_map = {
        (row["vegetable_id"], row["horizon_days"]): row for row in group_results
    }
    evaluated["release_status"] = [
        release_map[(int(vegetable_id), int(horizon))]["release_status"]
        for vegetable_id, horizon in zip(evaluated["vegetable_id"], evaluated["horizon_days"])
    ]
    use_model = evaluated["release_status"].isin(
        ["model_target", "model_minimum", "point_only_model"]
    )
    use_interval = evaluated["release_status"].isin(["model_target", "model_minimum"])
    evaluated["released_point_prediction"] = np.where(
        use_model, evaluated["model_prediction"], evaluated["best_baseline_prediction"]
    )
    evaluated["released_p10"] = np.where(use_interval, evaluated["p10"], np.nan)
    evaluated["released_p90"] = np.where(use_interval, evaluated["p90"], np.nan)

    model_overall = point_metric_record(evaluated["target_price"], evaluated["model_prediction"])
    baseline_overall = point_metric_record(
        evaluated["target_price"], evaluated["best_baseline_prediction"]
    )
    routed_overall = point_metric_record(
        evaluated["target_price"], evaluated["validation_routed_point"]
    )
    raw_model_improvement = 1.0 - model_overall["wape"] / baseline_overall["wape"]

    horizon_gate = {}
    for horizon in [7, 14]:
        rows = [row for row in group_results if row["horizon_days"] == horizon]
        passing = sum(
            row["validation_route"] == "model_candidate"
            and row["relative_wape_improvement"] > 0
            and row["improved_series_share"] > 0.5
            for row in rows
        )
        horizon_gate[str(horizon)] = {
            "passing_product_count": int(passing),
            "required_product_count": int(experiment["minimum_positive_products_7d_14d"]),
            "passes": bool(passing >= int(experiment["minimum_positive_products_7d_14d"])),
        }

    validation_lookup = {
        (int(row["vegetable_id"]), int(row["horizon_days"])): row
        for row in frozen_point["group_decisions"]
    }
    stability = []
    for row in group_results:
        validation_row = validation_lookup[(row["vegetable_id"], row["horizon_days"])]
        stability.append(
            {
                "vegetable_id": row["vegetable_id"],
                "vegetable_name_zh": row["vegetable_name_zh"],
                "horizon_days": row["horizon_days"],
                "validation_relative_wape_improvement": validation_row["relative_wape_improvement"],
                "test_relative_wape_improvement": row["relative_wape_improvement"],
                "improvement_sign_stable": bool(
                    (validation_row["relative_wape_improvement"] > 0)
                    == (row["relative_wape_improvement"] > 0)
                ),
            }
        )

    origin_results = []
    for origin, group in evaluated.groupby("origin_date", sort=True, observed=True):
        model_metric = point_metric_record(group["target_price"], group["model_prediction"])
        baseline_metric = point_metric_record(
            group["target_price"], group["best_baseline_prediction"]
        )
        origin_results.append(
            {
                "origin_date": origin.isoformat() if hasattr(origin, "isoformat") else str(origin),
                "row_count": int(len(group)),
                "model_wape": model_metric["wape"],
                "baseline_wape": baseline_metric["wape"],
                "relative_wape_improvement": round(
                    1.0 - model_metric["wape"] / baseline_metric["wape"], 8
                ),
            }
        )

    release_matrix = {
        "release_matrix_version": "p2_release_matrix_v0.1",
        "status": "partial_release" if any(row["release_status"] != "baseline_fallback" for row in group_results) else "no_model_release",
        "final_test_opened": True,
        "model_name": frozen_point["selected_model_name"],
        "interval_calibrator": frozen_calibrator["calibrator_version"],
        "group_results": group_results,
        "status_counts": {
            status: int(sum(row["release_status"] == status for row in group_results))
            for status in ["model_target", "model_minimum", "point_only_model", "baseline_fallback"]
        },
    }
    output_dir = root / "artifacts/p2/final"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_columns = [
        "vegetable_id",
        "vegetable_code",
        "vegetable_name_zh",
        "city_id",
        "origin_date",
        "horizon_days",
        "target_date",
        "origin_price",
        "target_price",
        "best_baseline_name",
        "best_baseline_prediction",
        "model_prediction",
        "validation_route",
        "validation_routed_point",
        "p10",
        "p50",
        "p90",
        "release_status",
        "released_point_prediction",
        "released_p10",
        "released_p90",
    ]
    predictions_path = output_dir / "final_test_predictions.parquet"
    temporary_path = output_dir / ".final_test_predictions.parquet.tmp"
    evaluated[output_columns].to_parquet(temporary_path, index=False, compression="zstd")
    os.replace(temporary_path, predictions_path)
    release_path = output_dir / "release_matrix.json"
    release_path.write_text(
        json.dumps(release_matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    scorecard = {
        "scorecard_version": "p2_final_test_v0.1",
        "status": "completed_one_time_final_test",
        "final_test_opened": True,
        "specifications_refit_after_test": False,
        "row_count": int(len(evaluated)),
        "model_overall_metrics": model_overall,
        "best_baseline_overall_metrics": baseline_overall,
        "validation_routed_overall_metrics": routed_overall,
        "raw_model_relative_wape_improvement": round(float(raw_model_improvement), 8),
        "target_relative_wape_improvement": float(experiment["target_relative_wape_improvement"]),
        "meets_overall_target_improvement": bool(
            raw_model_improvement >= float(experiment["target_relative_wape_improvement"])
        ),
        "horizon_product_gate": horizon_gate,
        "meets_minimum_7d_14d_product_gate": bool(
            horizon_gate["7"]["passes"] and horizon_gate["14"]["passes"]
        ),
        "overall_probability_metrics_on_validation_route": probability_metric_record(
            evaluated["target_price"], evaluated["p10"], evaluated["p50"], evaluated["p90"]
        ),
        "group_results": group_results,
        "stability": stability,
        "origin_results": origin_results,
        "release_status_counts": release_matrix["status_counts"],
        "inputs": {
            str(final_path.relative_to(root)): sha256(final_path),
            str(baseline_scorecard_path.relative_to(root)): sha256(baseline_scorecard_path),
            str(frozen_point_path.relative_to(root)): sha256(frozen_point_path),
            str(frozen_calibrator_path.relative_to(root)): sha256(frozen_calibrator_path),
        },
        "predictions": {
            "path": str(predictions_path.relative_to(root)),
            "sha256": sha256(predictions_path),
        },
        "release_matrix": {
            "path": str(release_path.relative_to(root)),
            "sha256": sha256(release_path),
        },
    }
    scorecard_path = output_dir / "final_scorecard.json"
    scorecard_path.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return scorecard, release_matrix


def render_report(scorecard: dict[str, Any], release_matrix: dict[str, Any]) -> str:
    model = scorecard["model_overall_metrics"]
    baseline = scorecard["best_baseline_overall_metrics"]
    probability = scorecard["overall_probability_metrics_on_validation_route"]
    status_labels = {
        "model_target": "模型+区间（达目标）",
        "model_minimum": "模型+区间（最低可用）",
        "point_only_model": "仅模型点预测",
        "baseline_fallback": "基线回退",
    }
    lines = [
        "# P2 最终测试模型卡",
        "",
        "> 状态：冻结规格已完成一次性 final test；测试后没有重新拟合或调参。  ",
        f"> 发布结论：`{release_matrix['status']}`",
        "",
        "## 1. 总体结论",
        "",
        f"冻结 hurdle 主模型在 16,217 条最终测试任务上的 WAPE 为 {model['wape']:.2%}，冻结最佳基线组合为 {baseline['wape']:.2%}，相对改善 {scorecard['raw_model_relative_wape_improvement']:.2%}。8% 总体目标线{'达到' if scorecard['meets_overall_target_improvement'] else '未达到'}。",
        "",
        f"7 日有 {scorecard['horizon_product_gate']['7']['passing_product_count']}/10 个产品通过点预测门槛，14 日有 {scorecard['horizon_product_gate']['14']['passing_product_count']}/10；最低 6/10 的双跨度门槛{'通过' if scorecard['meets_minimum_7d_14d_product_gate'] else '未通过'}。因此本项目采用产品×跨度的部分发布和基线回退，而不宣称一个模型全面胜出。",
        "",
        f"按 validation 预先路由的概率区间在最终测试上的总体覆盖率为 {probability['interval_coverage_80']:.1%}，平均宽度 {probability['mean_interval_width']:.3f} 元/kg，WIS {probability['wis_80']:.3f}。",
        "",
        "## 2. 发布矩阵",
        "",
        "| 产品 | 跨度 | 模型 WAPE | 基线 WAPE | 相对改善 | 改善城市 | 区间覆盖 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in release_matrix["group_results"]:
        lines.append(
            f"| {row['vegetable_name_zh']} | {row['horizon_days']}日 | "
            f"{row['model_metrics']['wape']:.2%} | {row['baseline_metrics']['wape']:.2%} | "
            f"{row['relative_wape_improvement']:.2%} | {row['improved_series_share']:.1%} | "
            f"{row['probability_metrics']['interval_coverage_80']:.1%} | "
            f"{status_labels[row['release_status']]} |"
        )
    lines.extend(
        [
            "",
            "发布状态计数："
            + "；".join(
                f"{status_labels[key]} {value}"
                for key, value in release_matrix["status_counts"].items()
            )
            + "。",
            "",
            "## 3. Validation→Test 稳定性",
            "",
            "| 产品 | 跨度 | Validation 改善 | Test 改善 | 符号稳定 |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in scorecard["stability"]:
        lines.append(
            f"| {row['vegetable_name_zh']} | {row['horizon_days']}日 | "
            f"{row['validation_relative_wape_improvement']:.2%} | "
            f"{row['test_relative_wape_improvement']:.2%} | "
            f"{'是' if row['improvement_sign_stable'] else '否'} |"
        )
    worst_origins = sorted(
        scorecard["origin_results"], key=lambda row: row["relative_wape_improvement"]
    )[:5]
    lines.extend(
        [
            "",
            "## 4. 最弱月份起点",
            "",
            "| 起点 | 模型 WAPE | 基线 WAPE | 相对改善 | 行数 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in worst_origins:
        lines.append(
            f"| {row['origin_date']} | {row['model_wape']:.2%} | {row['baseline_wape']:.2%} | "
            f"{row['relative_wape_improvement']:.2%} | {row['row_count']:,} |"
        )
    lines.extend(
        [
            "",
            "## 5. 模型限制与正确使用",
            "",
            "- 数据止于 2022-06-22，所有结果是历史回测，不是当前报价或实时预测。",
            "- 测试结果只用于接受、降级或拒绝冻结规格；没有反向修改模型、特征、阈值或区间。",
            "- `point_only_model` 只允许显示 P50，不显示未校准的 P10/P90；`baseline_fallback` 明确展示基线来源。",
            "- 这是 pricing engine 的上游风险情报，不包含成本、利润、库存、竞品约束或最终定价决策。",
            "- 部分发布比总体平均更可信：使用者必须查看当前产品×跨度状态，不应把一个切片的成功推广到全部城市和产品。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report", default="docs/p2_final_model_card.md")
    args = parser.parse_args()
    root = args.root.resolve()
    scorecard, release_matrix = build_final_evaluation(root)
    (root / args.report).write_text(
        render_report(scorecard, release_matrix), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": scorecard["status"],
                "row_count": scorecard["row_count"],
                "model_wape": scorecard["model_overall_metrics"]["wape"],
                "baseline_wape": scorecard["best_baseline_overall_metrics"]["wape"],
                "relative_improvement": scorecard["raw_model_relative_wape_improvement"],
                "release_status_counts": scorecard["release_status_counts"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

