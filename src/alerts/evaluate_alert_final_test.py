#!/usr/bin/env python3
"""Evaluate the frozen P3 alert model once on final_test and decide release status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from .audit_p3_feasibility import load_flat_yaml
    from .build_alert_baselines import build_predictions, validate_baseline_config
    from .metrics import average_precision, confusion_metrics, score_alerts
    from .train_alert_models import predict_from_artifact
except ImportError:
    from audit_p3_feasibility import load_flat_yaml
    from build_alert_baselines import build_predictions, validate_baseline_config
    from metrics import average_precision, confusion_metrics, score_alerts
    from train_alert_models import predict_from_artifact


def frozen_threshold_metrics(
    frame: pd.DataFrame,
    scores: np.ndarray,
    threshold: float,
    fixed_fpr: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    diagnostic, curve = score_alerts(
        frame["event_label"],
        scores,
        fixed_fpr,
        frame["future_peak_return_14d"],
        frame["event_lead_days"],
    )
    selected = confusion_metrics(frame["event_label"], scores, threshold)
    labels = frame["event_label"].to_numpy(dtype=int)
    predicted = scores >= threshold
    lead = frame["event_lead_days"].to_numpy(dtype=float)
    matched = (labels == 1) & predicted & np.isfinite(lead)
    event_peaks = frame.loc[frame["event_label"], "future_peak_return_14d"].to_numpy(dtype=float)
    if len(event_peaks):
        top_cutoff = float(np.quantile(event_peaks, 0.90))
        top = (labels == 1) & (
            frame["future_peak_return_14d"].to_numpy(dtype=float) >= top_cutoff
        )
        top_recall = float((predicted & top).sum() / top.sum()) if top.any() else None
    else:
        top_cutoff = None
        top = np.zeros(len(frame), dtype=bool)
        top_recall = None
    result = {
        "rows": int(len(frame)),
        "events": int(labels.sum()),
        "prevalence": float(labels.mean()),
        "average_precision": float(diagnostic["average_precision"]),
        "brier_score": float(diagnostic["brier_score"]),
        "at_frozen_validation_threshold": selected,
        "mean_lead_days": float(lead[matched].mean()) if matched.any() else None,
        "median_lead_days": float(np.median(lead[matched])) if matched.any() else None,
        "top_decile_peak_return_cutoff": top_cutoff,
        "top_decile_spike_events": int(top.sum()),
        "top_decile_spike_recall": top_recall,
        "diagnostic_oracle_threshold_not_used": diagnostic["threshold_at_fixed_fpr"],
    }
    return result, curve


def product_slices(
    frame: pd.DataFrame, scores: np.ndarray, threshold: float
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for product, group in frame.groupby("vegetable_name_zh", sort=True):
        positions = group.index.to_numpy(dtype=int)
        labels = group["event_label"].to_numpy(dtype=int)
        product_scores = scores[positions]
        result[str(product)] = {
            "rows": int(len(group)),
            "events": int(labels.sum()),
            "prevalence": float(labels.mean()),
            "average_precision": average_precision(labels, product_scores),
            "brier_score": float(np.mean((product_scores - labels) ** 2)),
            "at_frozen_validation_threshold": confusion_metrics(
                labels, product_scores, threshold
            ),
        }
    return result


def month_slices(frame: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    month_key = pd.to_datetime(frame["origin_date"]).dt.strftime("%Y-%m")
    for month, indices in frame.groupby(month_key, sort=True).groups.items():
        positions = np.asarray(list(indices), dtype=int)
        labels = frame.loc[positions, "event_label"].to_numpy(dtype=int)
        month_scores = scores[positions]
        result[str(month)] = {
            "rows": int(len(positions)),
            "events": int(labels.sum()),
            "prevalence": float(labels.mean()),
            "average_precision": average_precision(labels, month_scores),
            "at_frozen_validation_threshold": confusion_metrics(labels, month_scores, threshold),
        }
    return result


def sensitivity_slices(frame: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in sorted(item for item in frame.columns if item.startswith("event_label_abs")):
        labels = frame[column].to_numpy(dtype=int)
        result[column] = {
            "events": int(labels.sum()),
            "prevalence": float(labels.mean()),
            "average_precision": average_precision(labels, scores),
            "at_frozen_validation_threshold": confusion_metrics(labels, scores, threshold),
        }
    return result


def case_records(frame: pd.DataFrame, count: int = 10) -> dict[str, list[dict[str, Any]]]:
    columns = [
        "vegetable_name_zh",
        "market_city",
        "market_province",
        "origin_date",
        "origin_price",
        "risk_probability",
        "future_peak_return_14d",
        "event_lead_days",
        "outcome_type",
        "regional_raw_event_share",
        "event_scope",
    ]
    result: dict[str, list[dict[str, Any]]] = {}
    sorting = {
        "true_positive": ["risk_probability", "future_peak_return_14d"],
        "false_positive": ["risk_probability", "future_peak_return_14d"],
        "false_negative": ["future_peak_return_14d", "risk_probability"],
    }
    for outcome, sort_columns in sorting.items():
        subset = frame[frame["outcome_type"].eq(outcome)].sort_values(
            sort_columns, ascending=False
        ).head(count)
        records = subset[columns].copy()
        records["origin_date"] = records["origin_date"].astype(str)
        records = records.where(pd.notna(records), None)
        result[outcome] = records.to_dict("records")
    return result


def run(root: Path) -> dict[str, Any]:
    experiment = load_flat_yaml(root / "config/p3_alert_experiment.yaml")
    baseline_config = load_flat_yaml(root / "config/p3_baselines.yaml")
    validate_baseline_config(baseline_config)
    mart = root / str(baseline_config["mart_directory"])
    train = pd.read_parquet(mart / "train.parquet")
    final_test = pd.read_parquet(mart / "final_test.parquet").reset_index(drop=True)
    frozen = json.loads(
        (root / "artifacts/p3/models/frozen_alert_model.json").read_text(encoding="utf-8")
    )
    validation_scorecard = json.loads(
        (root / "artifacts/p3/models/candidate_scorecard.json").read_text(encoding="utf-8")
    )
    threshold = float(frozen["validation_action_threshold"])
    scores = predict_from_artifact(final_test, frozen)
    final_test["risk_probability"] = scores
    final_test["action_threshold"] = threshold
    final_test["predicted_alert"] = scores >= threshold

    labels = final_test["event_label"].to_numpy(dtype=bool)
    predicted = final_test["predicted_alert"].to_numpy(dtype=bool)
    final_test["outcome_type"] = np.select(
        [labels & predicted, ~labels & predicted, labels & ~predicted],
        ["true_positive", "false_positive", "false_negative"],
        default="true_negative",
    )
    regional_share = final_test.groupby(
        ["vegetable_id", "origin_date"], observed=True
    )["primary_raw_event"].transform("mean")
    final_test["regional_raw_event_share"] = regional_share
    final_test["event_scope"] = np.select(
        [regional_share.ge(0.25), regional_share.ge(0.10)],
        ["regional", "multi_city"],
        default="local",
    )
    final_test["severity"] = pd.cut(
        final_test["future_peak_return_14d"],
        bins=[-np.inf, 0.20, 0.50, 1.00, np.inf],
        labels=["below_20pct", "elevated", "high", "extreme"],
        right=False,
    ).astype(str)

    overall, model_curve = frozen_threshold_metrics(
        final_test,
        scores,
        threshold,
        float(experiment["fixed_false_positive_rate"]),
    )
    model_curve.insert(0, "score_source", "frozen_model")

    baseline_predictions, baseline_metadata = build_predictions(
        train, final_test, baseline_config
    )
    baseline_scorecards: dict[str, Any] = {}
    curves = [model_curve]
    baseline_score_by_name: dict[str, np.ndarray] = {}
    for name in baseline_config["baselines"]:
        subset = baseline_predictions[baseline_predictions["baseline"].eq(name)].reset_index(drop=True)
        baseline_scores = subset["risk_score"].to_numpy(dtype=float)
        baseline_score_by_name[str(name)] = baseline_scores
        diagnostic, curve = score_alerts(
            final_test["event_label"],
            baseline_scores,
            float(experiment["fixed_false_positive_rate"]),
            final_test["future_peak_return_14d"],
            final_test["event_lead_days"],
        )
        curve.insert(0, "score_source", str(name))
        curves.append(curve)
        baseline_scorecards[str(name)] = diagnostic
    best_baseline = str(frozen["best_baseline"])
    best_baseline_ap = float(baseline_scorecards[best_baseline]["average_precision"])
    final_test["best_baseline_risk_score"] = baseline_score_by_name[best_baseline]
    ap_lift = (
        float(overall["average_precision"] / best_baseline_ap - 1.0)
        if best_baseline_ap > 0
        else None
    )

    fixed = overall["at_frozen_validation_threshold"]
    precision_requirement = float(
        overall["prevalence"]
        * float(experiment["release_minimum_precision_prevalence_multiple"])
    )
    gates = {
        "pr_auc_lift": {
            "actual": ap_lift,
            "required": float(experiment["release_minimum_pr_auc_lift"]),
            "pass": ap_lift is not None
            and ap_lift >= float(experiment["release_minimum_pr_auc_lift"]),
        },
        "false_positive_rate": {
            "actual": float(fixed["false_positive_rate"]),
            "maximum": float(experiment["final_test_false_positive_rate_tolerance"]),
            "pass": fixed["false_positive_rate"]
            <= float(experiment["final_test_false_positive_rate_tolerance"]),
        },
        "recall": {
            "actual": float(fixed["recall"]),
            "required": float(experiment["release_minimum_recall"]),
            "pass": fixed["recall"] >= float(experiment["release_minimum_recall"]),
        },
        "precision_vs_prevalence": {
            "actual": float(fixed["precision"]),
            "required": precision_requirement,
            "pass": fixed["precision"] >= precision_requirement,
        },
        "true_positives": {
            "actual": int(fixed["true_positives"]),
            "required": int(experiment["release_minimum_true_positives"]),
            "pass": fixed["true_positives"]
            >= int(experiment["release_minimum_true_positives"]),
        },
    }
    if all(item["pass"] for item in gates.values()):
        release_status = "alert_release"
    elif (
        overall["average_precision"] > best_baseline_ap
        and fixed["recall"] >= float(experiment["research_minimum_recall"])
    ):
        release_status = "research_only"
    else:
        release_status = "no_signal"

    slices_by_product = product_slices(final_test, scores, threshold)
    slices_by_month = month_slices(final_test, scores, threshold)
    sensitivity = sensitivity_slices(final_test, scores, threshold)
    cases = case_records(final_test)
    validation_metrics = frozen["validation_metrics"]
    stability = {
        "validation_average_precision": float(validation_metrics["average_precision"]),
        "final_test_average_precision": float(overall["average_precision"]),
        "average_precision_change": float(
            overall["average_precision"] - validation_metrics["average_precision"]
        ),
        "validation_recall": float(
            validation_metrics["threshold_at_fixed_fpr"]["recall"]
        ),
        "final_test_recall": float(fixed["recall"]),
        "recall_change": float(
            fixed["recall"]
            - validation_metrics["threshold_at_fixed_fpr"]["recall"]
        ),
        "validation_false_positive_rate": float(
            validation_metrics["threshold_at_fixed_fpr"]["false_positive_rate"]
        ),
        "final_test_false_positive_rate": float(fixed["false_positive_rate"]),
    }

    output = root / "artifacts/p3/final"
    output.mkdir(parents=True, exist_ok=True)
    final_test.to_parquet(
        output / "final_test_predictions.parquet", index=False, compression="zstd"
    )
    pd.concat(curves, ignore_index=True).to_parquet(
        output / "final_pr_curve.parquet", index=False, compression="zstd"
    )
    scorecard = {
        "model_contract_version": frozen["model_contract_version"],
        "frozen_candidate": frozen["candidate_id"],
        "frozen_validation_threshold": threshold,
        "overall": overall,
        "best_baseline": best_baseline,
        "best_baseline_final_average_precision": best_baseline_ap,
        "final_average_precision_lift_vs_baseline": ap_lift,
        "baseline_scorecards": baseline_scorecards,
        "baseline_metadata": baseline_metadata,
        "stability": stability,
        "by_product": slices_by_product,
        "by_month": slices_by_month,
        "sensitivity": sensitivity,
        "cases": cases,
        "model_refit_on_final_test": False,
        "threshold_reselected_on_final_test": False,
    }
    (output / "final_scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    release = {
        "release_status": release_status,
        "decision_scope": "historical_replay_only_until_live_data_and_operations_are_added",
        "gates": gates,
        "frozen_candidate": frozen["candidate_id"],
        "frozen_validation_threshold": threshold,
        "model_refit_on_final_test": False,
        "threshold_reselected_on_final_test": False,
        "product_ui_rule": {
            "alert_release": "show historical risk score and evidence; do not claim real-time status",
            "research_only": "show research badge and historical replay; no executable recommendation",
            "no_signal": "hide model score and show historical volatility facts only",
        }[release_status],
    }
    (output / "release_decision.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "scorecard": scorecard,
        "release": release,
        "predictions": final_test,
    }


def render_model_card(root: Path, result: dict[str, Any]) -> None:
    scorecard = result["scorecard"]
    release = result["release"]
    overall = scorecard["overall"]
    fixed = overall["at_frozen_validation_threshold"]
    lines = [
        "# P3 价格风险预警最终模型卡",
        "",
        f"> 发布状态：**{release['release_status']}**  ",
        "> 使用范围：2014–2022 历史回放；没有实时数据接入，不代表当前市场预警。",
        "",
        "## 最终测试结果",
        "",
        f"- final_test：{overall['rows']:,} 行，{overall['events']:,} 个事件，事件率 {overall['prevalence']:.2%}。",
        f"- PR-AUC：{overall['average_precision']:.4f}；最佳简单基线 {scorecard['best_baseline_final_average_precision']:.4f}；相对提升 {scorecard['final_average_precision_lift_vs_baseline']:.2%}。",
        f"- 冻结阈值 {scorecard['frozen_validation_threshold']:.4f}：precision {fixed['precision']:.2%}、recall {fixed['recall']:.2%}、FPR {fixed['false_positive_rate']:.2%}、误报警占比 {fixed['false_alert_share']:.2%}。",
        f"- 命中 {fixed['true_positives']:,} 个事件；平均提前 {overall['mean_lead_days']:.2f} 天；最强 10% 事件召回 {overall['top_decile_spike_recall']:.2%}。",
        "",
        "## 发布门槛",
        "",
        "| 门槛 | 实际 | 要求 | 结果 |",
        "|---|---:|---:|---|",
    ]
    gate_labels = {
        "pr_auc_lift": "PR-AUC 相对提升",
        "false_positive_rate": "FPR",
        "recall": "Recall",
        "precision_vs_prevalence": "Precision",
        "true_positives": "命中事件数",
    }
    for name, gate in release["gates"].items():
        requirement = gate.get("required", gate.get("maximum"))
        actual = gate["actual"]
        if name == "true_positives":
            actual_text = f"{actual:,}"
            requirement_text = f"≥ {requirement:,}"
        else:
            actual_text = f"{actual:.2%}"
            requirement_text = (
                f"≤ {requirement:.2%}" if "maximum" in gate else f"≥ {requirement:.2%}"
            )
        lines.append(
            f"| {gate_labels[name]} | {actual_text} | {requirement_text} | {'通过' if gate['pass'] else '未通过'} |"
        )
    lines.extend([
        "",
        "## 产品级切片",
        "",
        "| 产品 | 事件率 | PR-AUC | Precision | Recall | FPR |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for product, item in scorecard["by_product"].items():
        product_fixed = item["at_frozen_validation_threshold"]
        lines.append(
            f"| {product} | {item['prevalence']:.2%} | {item['average_precision']:.4f} | "
            f"{product_fixed['precision']:.2%} | {product_fixed['recall']:.2%} | "
            f"{product_fixed['false_positive_rate']:.2%} |"
        )
    lines.extend([
        "",
        "## 稳定性与限制",
        "",
        f"- validation→final-test PR-AUC 变化 {scorecard['stability']['average_precision_change']:+.4f}；recall 变化 {scorecard['stability']['recall_change']:+.2%}。",
        "- final-test 的 oracle 阈值只保留作诊断，从未用于发布判断；正式结果始终使用 validation 冻结阈值。",
        "- 概率是历史样本上的风险排序，不是因果效应，也不是零售需求、库存、成本或最优报价。",
        "- 当前数据止于 2022-06-22；接入实时预警前必须增加新数据、漂移监控、操作责任人和通知治理。",
        "",
    ])
    (root / "docs/p3_final_model_card.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    result = run(root)
    render_model_card(root, result)
    overall = result["scorecard"]["overall"]
    fixed = overall["at_frozen_validation_threshold"]
    print(
        json.dumps(
            {
                "release_status": result["release"]["release_status"],
                "rows": overall["rows"],
                "events": overall["events"],
                "average_precision": overall["average_precision"],
                "average_precision_lift_vs_baseline": result["scorecard"]["final_average_precision_lift_vs_baseline"],
                "precision": fixed["precision"],
                "recall": fixed["recall"],
                "false_positive_rate": fixed["false_positive_rate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
