#!/usr/bin/env python3
"""Build frozen P3 validation baselines and their PR scorecards."""

from __future__ import annotations

import argparse
import json
import math
import os
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


def validate_baseline_config(config: dict[str, Any]) -> None:
    required = {
        "baseline_contract_version",
        "experiment_config_path",
        "mart_directory",
        "output_directory",
        "baselines",
        "heuristic_features",
        "heuristic_weights",
        "standardized_feature_clip",
        "probability_floor",
        "probability_ceiling",
        "best_baseline_metric",
        "tie_break_order",
    }
    missing = required.difference(config)
    if missing:
        raise ValueError(f"P3 baseline config misses keys: {sorted(missing)}")
    expected = ["train_product_prevalence", "series_event_rate_52w", "volatility_momentum"]
    if list(config["baselines"]) != expected:
        raise ValueError("P3 v0.1 baseline set changed unexpectedly")
    if len(config["heuristic_features"]) != len(config["heuristic_weights"]):
        raise ValueError("heuristic features and weights must align")


def _clip_probability(values: np.ndarray, config: dict[str, Any]) -> np.ndarray:
    return np.clip(
        values,
        float(config["probability_floor"]),
        float(config["probability_ceiling"]),
    )


def build_predictions(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    product_prevalence = train.groupby("vegetable_id")["event_label"].mean().to_dict()
    global_prevalence = float(train["event_label"].mean())
    feature_stats: dict[str, dict[str, float]] = {}
    for feature in config["heuristic_features"]:
        values = pd.to_numeric(train[feature], errors="coerce")
        median = float(values.median())
        std = float(values.fillna(median).std(ddof=0))
        feature_stats[str(feature)] = {"median": median, "std": std if std > 1e-12 else 1.0}

    base_probability = validation["vegetable_id"].map(product_prevalence).fillna(global_prevalence).to_numpy(dtype=float)
    series_rate = validation["historical_event_rate_series_52w"].to_numpy(dtype=float)
    series_rate = np.where(np.isfinite(series_rate), series_rate, base_probability)
    base_logit = np.log(np.clip(base_probability, 1e-6, 1 - 1e-6) / np.clip(1 - base_probability, 1e-6, 1))
    heuristic_logit = base_logit.copy()
    clip = float(config["standardized_feature_clip"])
    for feature, weight in zip(config["heuristic_features"], config["heuristic_weights"]):
        stats = feature_stats[str(feature)]
        raw = pd.to_numeric(validation[str(feature)], errors="coerce").fillna(stats["median"]).to_numpy(dtype=float)
        standardized = np.clip((raw - stats["median"]) / stats["std"], -clip, clip)
        heuristic_logit += float(weight) * standardized
    heuristic = 1.0 / (1.0 + np.exp(-np.clip(heuristic_logit, -30, 30)))

    scores = {
        "train_product_prevalence": _clip_probability(base_probability, config),
        "series_event_rate_52w": _clip_probability(series_rate, config),
        "volatility_momentum": _clip_probability(heuristic, config),
    }
    keep = KEY_COLUMNS + [
        "vegetable_name_zh",
        "market_city",
        "market_province",
        "event_label",
        "event_lead_days",
        "future_peak_return_14d",
    ]
    outputs = []
    for name in config["baselines"]:
        item = validation[keep].copy()
        item["baseline"] = str(name)
        item["risk_score"] = scores[str(name)]
        outputs.append(item)
    metadata = {
        "train_global_prevalence": global_prevalence,
        "train_product_prevalence": {str(key): float(value) for key, value in product_prevalence.items()},
        "heuristic_feature_stats": feature_stats,
        "heuristic_features": config["heuristic_features"],
        "heuristic_weights": config["heuristic_weights"],
    }
    return pd.concat(outputs, ignore_index=True), metadata


def run(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    validate_baseline_config(config)
    experiment = load_flat_yaml(root / str(config["experiment_config_path"]))
    maximum_fpr = float(experiment["fixed_false_positive_rate"])
    mart = root / str(config["mart_directory"])
    train = pd.read_parquet(mart / "train.parquet")
    validation = pd.read_parquet(mart / "validation.parquet")
    predictions, metadata = build_predictions(train, validation, config)
    scorecards: dict[str, Any] = {}
    curves = []
    for name in config["baselines"]:
        subset = predictions[predictions["baseline"].eq(name)]
        overall, curve = score_alerts(
            subset["event_label"],
            subset["risk_score"],
            maximum_fpr,
            subset["future_peak_return_14d"],
            subset["event_lead_days"],
        )
        curve.insert(0, "baseline", name)
        curves.append(curve)
        by_product: dict[str, Any] = {}
        threshold = float(overall["threshold_at_fixed_fpr"]["threshold"])
        for product, group in subset.groupby("vegetable_name_zh", sort=True):
            metrics, _ = score_alerts(
                group["event_label"],
                group["risk_score"],
                maximum_fpr,
                group["future_peak_return_14d"],
                group["event_lead_days"],
            )
            metrics["at_global_threshold"] = confusion_metrics(
                group["event_label"], group["risk_score"], threshold
            )
            by_product[str(product)] = metrics
        scorecards[str(name)] = {"overall": overall, "by_product": by_product}

    tie_order = {name: index for index, name in enumerate(config["tie_break_order"])}
    best = sorted(
        config["baselines"],
        key=lambda name: (-scorecards[str(name)]["overall"]["average_precision"], tie_order[str(name)]),
    )[0]
    scorecard = {
        "baseline_contract_version": config["baseline_contract_version"],
        "validation_rows": int(len(validation)),
        "fixed_false_positive_rate": maximum_fpr,
        "best_baseline": str(best),
        "selection_metric": config["best_baseline_metric"],
        "metadata": metadata,
        "baselines": scorecards,
        "final_test_read": False,
    }
    output = root / str(config["output_directory"])
    output.mkdir(parents=True, exist_ok=True)
    prediction_path = output / "validation_predictions.parquet"
    curve_path = output / "validation_pr_curve.parquet"
    scorecard_path = output / "validation_scorecard.json"
    predictions.to_parquet(prediction_path, index=False, compression="zstd")
    pd.concat(curves, ignore_index=True).to_parquet(curve_path, index=False, compression="zstd")
    scorecard_path.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return scorecard


def render_report(root: Path, scorecard: dict[str, Any]) -> None:
    lines = [
        "# P3 简单风险基线报告",
        "",
        "> 只使用 train 拟合统计量，在 validation 的完全相同 16,388 行上比较；未读取 final_test。",
        "",
        "## 总体比较",
        "",
        "| 基线 | PR-AUC | Brier | 固定FPR阈值 | Precision | Recall | FPR | 误报警占比 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "train_product_prevalence": "训练期产品事件率",
        "series_event_rate_52w": "序列过去52周事件率",
        "volatility_momentum": "近期波动+动量启发式",
    }
    for name, item in scorecard["baselines"].items():
        overall = item["overall"]
        fixed = overall["threshold_at_fixed_fpr"]
        lines.append(
            f"| {labels[name]} | {overall['average_precision']:.4f} | {overall['brier_score']:.4f} | "
            f"{fixed['threshold']:.4f} | {fixed['precision']:.2%} | {fixed['recall']:.2%} | "
            f"{fixed['false_positive_rate']:.2%} | {fixed['false_alert_share']:.2%} |"
        )
    best = scorecard["best_baseline"]
    lines.extend([
        "",
        "## 冻结结果",
        "",
        f"- 最佳简单基线：**{labels[best]}**（按 validation PR-AUC 选择）。",
        "- `FPR` 是非事件中被误报的比例；`误报警占比` 是全部发出提醒中错误提醒的比例，两者不能混用。",
        "- 本任务只建立比较底线。模型必须在相同 validation 行上超过该基线，最终测试前不得调整事件定义或行动阈值。",
        "",
    ])
    (root / "docs/p3_baseline_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p3_baselines.yaml")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / args.config)
    scorecard = run(root, config)
    render_report(root, scorecard)
    print(json.dumps({"best_baseline": scorecard["best_baseline"], "validation_rows": scorecard["validation_rows"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
