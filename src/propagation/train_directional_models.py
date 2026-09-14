#!/usr/bin/env python3
"""Fit frozen P5 candidate edges, apply BH-FDR, and score validation uplift."""

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
    benjamini_hochberg,
    fit_ols,
    improvement,
    joint_f_test,
    predict_ols,
    prepare_lagged_panel,
    regression_metrics,
)


def fit_candidate_edges(
    panel: pd.DataFrame,
    edges: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    lags = [int(value) for value in config["primary_lags_bins"]]
    lagged = prepare_lagged_panel(
        panel.loc[panel["split"].isin(["train", "validation"])].copy(),
        lags=lags,
        bin_days=int(config["primary_bin_days"]),
    )
    baseline_features = [f"propagation_residual_lag{lag}" for lag in lags] + [
        f"common_factor_loo_lag{lag}" for lag in lags
    ]
    source_features = [f"source_residual_lag{lag}" for lag in lags]
    series: dict[tuple[int, str], pd.DataFrame] = {}
    for (vegetable_id, city_id), group in lagged.groupby(
        ["vegetable_id", "city_id"], observed=True
    ):
        series[(int(vegetable_id), str(city_id))] = group.sort_values("bin_start")

    rows: list[dict[str, Any]] = []
    for edge in edges.itertuples(index=False):
        key_target = (int(edge.vegetable_id), str(edge.target_city_id))
        key_source = (int(edge.vegetable_id), str(edge.source_city_id))
        target = series.get(key_target)
        source = series.get(key_source)
        if target is None or source is None:
            continue
        source_frame = source[
            ["bin_start", *[f"propagation_residual_lag{lag}" for lag in lags]]
        ].rename(
            columns={
                f"propagation_residual_lag{lag}": f"source_residual_lag{lag}"
                for lag in lags
            }
        )
        joined = target.merge(
            source_frame, on="bin_start", how="inner", validate="one_to_one"
        )
        required = ["propagation_residual", *baseline_features, *source_features]
        joined = joined.loc[joined[required].notna().all(axis=1)].copy()
        train = joined.loc[joined["split"].eq("train")]
        validation = joined.loc[joined["split"].eq("validation")]
        if len(train) < int(config["minimum_model_train_rows"]) or len(validation) < int(
            config["minimum_model_validation_rows"]
        ):
            continue

        restricted_coefficients = fit_ols(
            train, "propagation_residual", baseline_features
        )
        full_features = [*baseline_features, *source_features]
        full_coefficients = fit_ols(train, "propagation_residual", full_features)
        train_actual = train["propagation_residual"].to_numpy(float)
        train_restricted = predict_ols(
            train, baseline_features, restricted_coefficients
        )
        train_full = predict_ols(train, full_features, full_coefficients)
        statistic, p_value = joint_f_test(
            train_actual,
            train_restricted,
            train_full,
            added_parameters=len(source_features),
            unrestricted_parameters=len(full_coefficients),
        )
        validation_actual = validation["propagation_residual"].to_numpy(float)
        validation_restricted = predict_ols(
            validation, baseline_features, restricted_coefficients
        )
        validation_full = predict_ols(validation, full_features, full_coefficients)
        baseline_metrics = regression_metrics(validation_actual, validation_restricted)
        full_metrics = regression_metrics(validation_actual, validation_full)
        source_coefficients = full_coefficients[-len(source_features) :]
        dominant_index = int(np.argmax(np.abs(source_coefficients)))
        rows.append(
            {
                "vegetable_id": int(edge.vegetable_id),
                "vegetable_code": edge.vegetable_code,
                "vegetable_name_zh": edge.vegetable_name_zh,
                "source_city_id": edge.source_city_id,
                "source_city_name_zh": edge.source_city_name_zh,
                "source_province_name_zh": edge.source_province_name_zh,
                "target_city_id": edge.target_city_id,
                "target_city_name_zh": edge.target_city_name_zh,
                "target_province_name_zh": edge.target_province_name_zh,
                "distance_km": float(edge.distance_km),
                "same_province": bool(edge.same_province),
                "candidate_rank": int(edge.candidate_rank),
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                "train_joint_f_statistic": statistic,
                "train_joint_p_value": p_value,
                "source_coefficient_sum": float(source_coefficients.sum()),
                "source_lag1_coefficient": float(source_coefficients[0]),
                "source_lag2_coefficient": float(source_coefficients[1]),
                "source_lag3_coefficient": float(source_coefficients[2]),
                "source_lag4_coefficient": float(source_coefficients[3]),
                "dominant_lag_bins": dominant_index + 1,
                "expected_delay_days": (dominant_index + 1)
                * int(config["primary_bin_days"]),
                "validation_baseline_rmse": baseline_metrics["rmse"],
                "validation_full_rmse": full_metrics["rmse"],
                "validation_rmse_improvement": improvement(
                    baseline_metrics["rmse"], full_metrics["rmse"]
                ),
                "validation_baseline_mae": baseline_metrics["mae"],
                "validation_full_mae": full_metrics["mae"],
                "validation_mae_improvement": improvement(
                    baseline_metrics["mae"], full_metrics["mae"]
                ),
                "restricted_coefficients": [
                    float(value) for value in restricted_coefficients
                ],
                "full_coefficients": [float(value) for value in full_coefficients],
            }
        )
    result = pd.DataFrame(rows)
    result["fdr_q_value"] = np.nan
    result["fdr_reject"] = False
    for _, group in result.groupby("vegetable_id", observed=True):
        adjusted = benjamini_hochberg(
            group["train_joint_p_value"], float(config["fdr_q"])
        )
        result.loc[group.index, "fdr_q_value"] = adjusted["fdr_q_value"]
        result.loc[group.index, "fdr_reject"] = adjusted["fdr_reject"]
    result["positive_direction"] = result["source_coefficient_sum"].gt(0)
    result["validation_pass"] = (
        result["fdr_reject"]
        & result["positive_direction"]
        & result["validation_rmse_improvement"].ge(
            float(config["validation_minimum_rmse_improvement"])
        )
        & result["validation_mae_improvement"].ge(
            -float(config["validation_maximum_mae_degradation"])
        )
    )
    result.sort_values(
        ["vegetable_id", "validation_pass", "fdr_q_value", "validation_rmse_improvement"],
        ascending=[True, False, True, False],
        inplace=True,
    )
    return result.reset_index(drop=True)


def summary(scorecard: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for keys, group in scorecard.groupby(
        ["vegetable_id", "vegetable_code", "vegetable_name_zh"], observed=True
    ):
        selected = group.loc[group["validation_pass"]]
        rows.append(
            {
                "vegetable_id": int(keys[0]),
                "vegetable_code": keys[1],
                "vegetable_name_zh": keys[2],
                "modeled_candidate_edges": int(len(group)),
                "raw_significant_edges": int(group["train_joint_p_value"].le(0.05).sum()),
                "fdr_edges": int(group["fdr_reject"].sum()),
                "positive_fdr_edges": int(
                    (group["fdr_reject"] & group["positive_direction"]).sum()
                ),
                "validation_selected_edges": int(len(selected)),
                "selected_median_rmse_improvement": float(
                    selected["validation_rmse_improvement"].median()
                )
                if len(selected)
                else None,
            }
        )
    return rows


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# P5 方向模型与 Validation 报告",
        "",
        "## 结论",
        "",
        f"训练期联合检验与 validation 机械筛选已完成；final test 未读取。当前保留 {payload['totals']['validation_selected_edges']} 条边进入稳定性验证，不代表已发布传播网络。",
        "",
        "| 产品 | 已建模候选 | 原始显著 | FDR后 | 正向FDR | Validation保留 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["products"]:
        lines.append(
            f"| {row['vegetable_name_zh']} | {row['modeled_candidate_edges']} | {row['raw_significant_edges']} | {row['fdr_edges']} | {row['positive_fdr_edges']} | {row['validation_selected_edges']} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "FDR 只控制当前地理候选集合中的多重检验；它不证明贸易联系或因果传播。进入下一阶段的边还必须通过训练分窗、时间块 bootstrap 和 final-test 样本外增益。",
            "",
            "Gate：`conditional_pass_to_stability`。",
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
    mart_dir = root / config["propagation_mart_dir"]
    panel = pd.read_parquet(mart_dir / "primary_panel.parquet")
    edges = pd.read_parquet(mart_dir / "candidate_edges.parquet")
    scorecard = fit_candidate_edges(panel, edges, config)
    output_dir = root / config["model_artifact_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = output_dir / "validation_candidate_scorecard.parquet"
    scorecard.to_parquet(scorecard_path, index=False)
    products = summary(scorecard)
    totals = {
        "geographic_candidate_edges": int(len(edges)),
        "modeled_candidate_edges": int(len(scorecard)),
        "raw_significant_edges": int(scorecard["train_joint_p_value"].le(0.05).sum()),
        "fdr_edges": int(scorecard["fdr_reject"].sum()),
        "positive_fdr_edges": int(
            (scorecard["fdr_reject"] & scorecard["positive_direction"]).sum()
        ),
        "validation_selected_edges": int(scorecard["validation_pass"].sum()),
    }
    payload = {
        "model_version": "p5_distributed_lag_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "validation_frozen",
        "fdr_q": float(config["fdr_q"]),
        "selection_rules": {
            "positive_direction": True,
            "minimum_rmse_improvement": float(
                config["validation_minimum_rmse_improvement"]
            ),
            "minimum_mae_improvement": -float(
                config["validation_maximum_mae_degradation"]
            ),
        },
        "products": products,
        "totals": totals,
        "final_test_evaluated": False,
        "candidate_edges_reselected_from_prices": False,
        "scorecard": {
            "path": str(scorecard_path.relative_to(root)),
            "rows": int(len(scorecard)),
            "sha256": sha256(scorecard_path),
        },
    }
    write_json(output_dir / "validation_summary.json", payload)
    frozen = scorecard.loc[scorecard["validation_pass"]].copy()
    frozen_payload = {
        "model_version": payload["model_version"],
        "frozen_after": str(config["validation_end"]),
        "final_test_evaluated": False,
        "selection_rules": payload["selection_rules"],
        "edge_count": int(len(frozen)),
        "edges": frozen[
            [
                "vegetable_id",
                "source_city_id",
                "target_city_id",
                "fdr_q_value",
                "source_coefficient_sum",
                "dominant_lag_bins",
                "expected_delay_days",
                "validation_rmse_improvement",
                "validation_mae_improvement",
            ]
        ].to_dict(orient="records"),
    }
    write_json(output_dir / "validation_frozen_edges.json", frozen_payload)
    (root / "docs/p5_directional_model_report.md").write_text(
        render_report(payload), encoding="utf-8"
    )
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
