#!/usr/bin/env python3
"""Evaluate frozen P5 edges once on final test and make the release decision."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as t_distribution

from src.procurement.common import load_flat_yaml, sha256, write_json
from src.propagation.modeling import (
    benjamini_hochberg,
    fit_ols,
    improvement,
    predict_ols,
    prepare_lagged_panel,
    regression_metrics,
)
from src.propagation.validate_edge_stability import build_edge_frame


def correlation_test(left: np.ndarray, right: np.ndarray) -> tuple[float, float]:
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    mask = np.isfinite(left) & np.isfinite(right)
    left = left[mask]
    right = right[mask]
    if len(left) < 4 or np.std(left) == 0 or np.std(right) == 0:
        return float("nan"), 1.0
    correlation = float(np.corrcoef(left, right)[0, 1])
    degrees = len(left) - 2
    denominator = max(1e-15, 1.0 - correlation * correlation)
    statistic = abs(correlation) * np.sqrt(degrees / denominator)
    p_value = float(2 * t_distribution.sf(statistic, degrees))
    return correlation, p_value


def common_factor_network_diagnostic(
    panel: pd.DataFrame,
    candidate_edges: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, Any]:
    train = panel.loc[panel["split"].eq("train")]
    series = {
        (int(vegetable_id), str(city_id)): group[
            ["bin_start", "log_return", "propagation_residual"]
        ]
        for (vegetable_id, city_id), group in train.groupby(
            ["vegetable_id", "city_id"], observed=True
        )
    }
    rows: list[dict[str, Any]] = []
    for edge in candidate_edges.itertuples(index=False):
        source = series.get((int(edge.vegetable_id), str(edge.source_city_id)))
        target = series.get((int(edge.vegetable_id), str(edge.target_city_id)))
        if source is None or target is None:
            continue
        joined = source.merge(
            target,
            on="bin_start",
            suffixes=("_source", "_target"),
            how="inner",
            validate="one_to_one",
        ).dropna()
        if len(joined) < int(config["minimum_model_train_rows"]):
            continue
        raw_correlation, raw_p = correlation_test(
            joined["log_return_source"].to_numpy(float),
            joined["log_return_target"].to_numpy(float),
        )
        residual_correlation, residual_p = correlation_test(
            joined["propagation_residual_source"].to_numpy(float),
            joined["propagation_residual_target"].to_numpy(float),
        )
        rows.append(
            {
                "vegetable_id": int(edge.vegetable_id),
                "raw_correlation": raw_correlation,
                "raw_p_value": raw_p,
                "residual_correlation": residual_correlation,
                "residual_p_value": residual_p,
            }
        )
    scores = pd.DataFrame(rows)
    scores["raw_fdr_reject"] = False
    scores["residual_fdr_reject"] = False
    for _, group in scores.groupby("vegetable_id", observed=True):
        raw = benjamini_hochberg(group["raw_p_value"], float(config["fdr_q"]))
        residual = benjamini_hochberg(
            group["residual_p_value"], float(config["fdr_q"])
        )
        scores.loc[group.index, "raw_fdr_reject"] = raw["fdr_reject"]
        scores.loc[group.index, "residual_fdr_reject"] = residual["fdr_reject"]
    raw_edges = int(scores["raw_fdr_reject"].sum())
    residual_edges = int(scores["residual_fdr_reject"].sum())
    return {
        "comparison": "training-period contemporaneous candidate-pair correlation",
        "tested_candidate_pairs": int(len(scores)),
        "raw_fdr_edges": raw_edges,
        "common_factor_adjusted_fdr_edges": residual_edges,
        "edge_reduction": raw_edges - residual_edges,
        "edge_reduction_share": float((raw_edges - residual_edges) / raw_edges)
        if raw_edges
        else None,
        "common_factor_reduction_supported": residual_edges < raw_edges,
        "directional_or_causal_test": False,
    }


def evaluate_frozen_edges(
    panel: pd.DataFrame,
    frozen_edges: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    lags = [int(value) for value in config["primary_lags_bins"]]
    lagged = prepare_lagged_panel(
        panel,
        lags=lags,
        bin_days=int(config["primary_bin_days"]),
    )
    rows: list[dict[str, Any]] = []
    for edge in frozen_edges.itertuples(index=False):
        joined, baseline_features, source_features = build_edge_frame(
            lagged,
            vegetable_id=int(edge.vegetable_id),
            source_city_id=str(edge.source_city_id),
            target_city_id=str(edge.target_city_id),
            lags=lags,
        )
        fit_sample = joined.loc[joined["split"].isin(["train", "validation"])]
        final = joined.loc[joined["split"].eq("final_test")]
        if len(fit_sample) < int(config["minimum_model_train_rows"]) or len(
            final
        ) < int(config["minimum_model_final_test_rows"]):
            raise RuntimeError(
                "A stability-frozen edge no longer meets the predeclared sample minimum."
            )
        restricted = fit_ols(
            fit_sample, "propagation_residual", baseline_features
        )
        full_features = [*baseline_features, *source_features]
        full = fit_ols(fit_sample, "propagation_residual", full_features)
        actual = final["propagation_residual"].to_numpy(float)
        restricted_metrics = regression_metrics(
            actual, predict_ols(final, baseline_features, restricted)
        )
        full_metrics = regression_metrics(
            actual, predict_ols(final, full_features, full)
        )
        rmse_uplift = improvement(
            restricted_metrics["rmse"], full_metrics["rmse"]
        )
        mae_uplift = improvement(restricted_metrics["mae"], full_metrics["mae"])
        rows.append(
            {
                **edge._asdict(),
                "refit_rows_train_validation": int(len(fit_sample)),
                "final_test_rows": int(len(final)),
                "final_baseline_rmse": restricted_metrics["rmse"],
                "final_full_rmse": full_metrics["rmse"],
                "final_rmse_improvement": rmse_uplift,
                "final_baseline_mae": restricted_metrics["mae"],
                "final_full_mae": full_metrics["mae"],
                "final_mae_improvement": mae_uplift,
                "final_confirmed": rmse_uplift
                > float(config["final_minimum_positive_rmse_improvement"]),
                "final_strong_edge": rmse_uplift
                >= float(config["strong_edge_minimum_rmse_improvement"]),
                "model_fit_end": str(config["validation_end"]),
                "model_refit_on_final_test": False,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["vegetable_id", "final_confirmed", "final_rmse_improvement"],
        ascending=[True, False, False],
    )


def make_release_decision(
    scorecard: pd.DataFrame,
    common_factor_diagnostic: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    products: list[dict[str, Any]] = []
    for keys, group in scorecard.groupby(
        ["vegetable_id", "vegetable_code", "vegetable_name_zh"], observed=True
    ):
        products.append(
            {
                "vegetable_id": int(keys[0]),
                "vegetable_code": keys[1],
                "vegetable_name_zh": keys[2],
                "frozen_edges": int(len(group)),
                "final_confirmed_edges": int(group["final_confirmed"].sum()),
                "final_strong_edges": int(group["final_strong_edge"].sum()),
                "median_final_rmse_improvement": float(
                    group["final_rmse_improvement"].median()
                ),
            }
        )
    frozen_count = int(len(scorecard))
    confirmed_count = int(scorecard["final_confirmed"].sum())
    qualifying_products = sum(
        row["final_confirmed_edges"]
        >= int(config["release_minimum_edges_per_product"])
        for row in products
    )
    positive_share = float(confirmed_count / frozen_count) if frozen_count else 0.0
    median_uplift = (
        float(scorecard["final_rmse_improvement"].median())
        if frozen_count
        else float("nan")
    )
    gates = {
        "minimum_products_with_required_edges": {
            "actual": int(qualifying_products),
            "required": int(config["release_minimum_products"]),
            "pass": qualifying_products >= int(config["release_minimum_products"]),
        },
        "positive_final_edge_share": {
            "actual": positive_share,
            "required": float(config["release_minimum_positive_edge_share"]),
            "pass": positive_share
            >= float(config["release_minimum_positive_edge_share"]),
        },
        "median_final_rmse_improvement": {
            "actual": median_uplift,
            "required": float(config["release_minimum_median_rmse_improvement"]),
            "pass": median_uplift
            >= float(config["release_minimum_median_rmse_improvement"]),
        },
        "fdr_and_stability_complete": {
            "actual": bool(
                scorecard["fdr_reject"].all() & scorecard["stability_pass"].all()
            ),
            "required": True,
            "pass": bool(
                scorecard["fdr_reject"].all() & scorecard["stability_pass"].all()
            ),
        },
        "common_factor_network_reduction": {
            "actual": bool(
                common_factor_diagnostic["common_factor_reduction_supported"]
            ),
            "required": True,
            "pass": bool(
                common_factor_diagnostic["common_factor_reduction_supported"]
            ),
        },
        "noncausal_language_contract": {
            "actual": True,
            "required": True,
            "pass": True,
        },
    }
    network_release = all(gate["pass"] for gate in gates.values())
    return {
        "release_status": "network_release" if network_release else "common_shock_only",
        "decision_is_mechanical": True,
        "gates": gates,
        "frozen_edges": frozen_count,
        "final_confirmed_edges": confirmed_count,
        "final_strong_edges": int(scorecard["final_strong_edge"].sum()),
        "positive_final_edge_share": positive_share,
        "median_final_rmse_improvement": median_uplift,
        "qualifying_products": int(qualifying_products),
        "products": products,
    }


def render_model_card(payload: dict[str, Any]) -> str:
    decision = payload["release_decision"]
    diagnostic = payload["common_factor_network_diagnostic"]
    lines = [
        "# P5 模型卡：价格冲击传播",
        "",
        "## 发布结论",
        "",
        f"正式状态：`{decision['release_status']}`。15 条冻结边只在预设 final test 上评估一次；发布状态由冻结门槛机械生成。",
        "",
        "| 发布门槛 | 实际 | 要求 | 结果 |",
        "|---|---:|---:|---|",
    ]
    for name, gate in decision["gates"].items():
        lines.append(
            f"| `{name}` | {gate['actual']} | {gate['required']} | {'通过' if gate['pass'] else '未通过'} |"
        )
    lines.extend(
        [
            "",
            "## Final-test 证据",
            "",
            f"冻结边 {decision['frozen_edges']} 条，final RMSE 改善为正 {decision['final_confirmed_edges']} 条，强边（至少 1%）{decision['final_strong_edges']} 条；正增益占比 {decision['positive_final_edge_share']:.1%}，中位 RMSE 改善 {decision['median_final_rmse_improvement']:.2%}。",
            "",
            "## 共同冲击诊断",
            "",
            f"在训练期同一地理候选集合上，原始变化的同时相关 FDR 边为 {diagnostic['raw_fdr_edges']} 条；剔除季节与 leave-one-out 共同因子后为 {diagnostic['common_factor_adjusted_fdr_edges']} 条，减少 {diagnostic['edge_reduction_share']:.1%}。这是同步性诊断，不是方向或因果检验。",
            "",
            "## 可用与不可用",
            "",
            "本模型可用于历史成本风险的人工复核：识别共同价格冲击、比较城市暴露，并说明为何某些 lead-lag 候选没有获得足够发布证据。它不能证明城市间贸易流，不能作为实时预警，不能自动调价，也不能声称利润改善。",
            "",
            "所有价格数据、scorecard、JSON/Parquet artifacts 和浏览器数据只保留本机，不进入 GitHub。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p5_propagation_experiment.yaml")
    output_dir = root / config["final_artifact_dir"]
    if bool(config["final_test_consumed"]) or (output_dir / "release_decision.json").exists():
        raise RuntimeError(
            "P5 final test is already consumed; this command intentionally refuses a rerun."
        )
    mart_dir = root / config["propagation_mart_dir"]
    panel = pd.read_parquet(mart_dir / "primary_panel.parquet")
    stability_dir = root / config["stability_artifact_dir"]
    stability = pd.read_parquet(stability_dir / "stability_scorecard.parquet")
    frozen = stability.loc[stability["final_test_eligible"]].copy()
    candidate_edges = pd.read_parquet(mart_dir / "candidate_edges.parquet")
    common_factor_diagnostic = common_factor_network_diagnostic(
        panel, candidate_edges, config
    )
    scorecard = evaluate_frozen_edges(panel, frozen, config)
    decision = make_release_decision(scorecard, common_factor_diagnostic, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = output_dir / "final_scorecard.parquet"
    scorecard.to_parquet(scorecard_path, index=False)
    run_timestamp = datetime.now(timezone.utc).isoformat()
    payload = {
        "model_version": "p5_distributed_lag_final_v0.1",
        "generated_at_utc": run_timestamp,
        "final_test_first_and_only_evaluation": True,
        "final_test_evaluated": True,
        "final_test_period": {
            "start": str(config["final_test_start"]),
            "end": str(config["final_test_end"]),
        },
        "model_fit_period": {
            "start": str(config["train_start"]),
            "end": str(config["validation_end"]),
        },
        "model_refit_before_final_test": True,
        "model_refit_on_final_test": False,
        "threshold_reselected_on_final_test": False,
        "candidate_edges_reselected_on_final_test": False,
        "common_factor_network_diagnostic": common_factor_diagnostic,
        "release_decision": decision,
        "scorecard": {
            "path": str(scorecard_path.relative_to(root)),
            "rows": int(len(scorecard)),
            "sha256": sha256(scorecard_path),
        },
    }
    write_json(output_dir / "release_decision.json", payload)
    (root / "docs/p5_model_card.md").write_text(
        render_model_card(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "release_status": decision["release_status"],
                "frozen_edges": decision["frozen_edges"],
                "final_confirmed_edges": decision["final_confirmed_edges"],
                "final_strong_edges": decision["final_strong_edges"],
                "positive_final_edge_share": decision["positive_final_edge_share"],
                "median_final_rmse_improvement": decision[
                    "median_final_rmse_improvement"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
