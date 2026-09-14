#!/usr/bin/env python3
"""Validate P5 edges with train halves, block bootstrap, and weekly sensitivity."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml, sha256, write_json
from src.propagation.modeling import (
    fit_ols,
    improvement,
    predict_ols,
    prepare_lagged_panel,
    regression_metrics,
)


def _edge_seed(base_seed: int, vegetable_id: int, source: str, target: str) -> int:
    digest = hashlib.sha256(
        f"{base_seed}|{vegetable_id}|{source}|{target}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "little")


def build_edge_frame(
    lagged_panel: pd.DataFrame,
    *,
    vegetable_id: int,
    source_city_id: str,
    target_city_id: str,
    lags: list[int],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    target = lagged_panel.loc[
        lagged_panel["vegetable_id"].eq(vegetable_id)
        & lagged_panel["city_id"].eq(target_city_id)
    ].copy()
    source = lagged_panel.loc[
        lagged_panel["vegetable_id"].eq(vegetable_id)
        & lagged_panel["city_id"].eq(source_city_id)
    ].copy()
    baseline_features = [f"propagation_residual_lag{lag}" for lag in lags] + [
        f"common_factor_loo_lag{lag}" for lag in lags
    ]
    source_features = [f"source_residual_lag{lag}" for lag in lags]
    source_frame = source[
        ["bin_start", *[f"propagation_residual_lag{lag}" for lag in lags]]
    ].rename(
        columns={
            f"propagation_residual_lag{lag}": f"source_residual_lag{lag}"
            for lag in lags
        }
    )
    joined = target.merge(
        source_frame,
        on="bin_start",
        how="inner",
        validate="one_to_one",
    )
    required = ["propagation_residual", *baseline_features, *source_features]
    joined = joined.loc[joined[required].notna().all(axis=1)].copy()
    return joined.sort_values("bin_start"), baseline_features, source_features


def cumulative_source_coefficient(
    frame: pd.DataFrame,
    baseline_features: list[str],
    source_features: list[str],
) -> float:
    coefficients = fit_ols(
        frame,
        "propagation_residual",
        [*baseline_features, *source_features],
    )
    return float(coefficients[-len(source_features) :].sum())


def moving_block_positive_rate(
    train: pd.DataFrame,
    baseline_features: list[str],
    source_features: list[str],
    *,
    resamples: int,
    block_bins: int,
    seed: int,
) -> float:
    row_count = len(train)
    if row_count < block_bins:
        return float("nan")
    rng = np.random.default_rng(seed)
    blocks_needed = int(np.ceil(row_count / block_bins))
    positive = 0
    for _ in range(resamples):
        starts = rng.integers(0, row_count - block_bins + 1, size=blocks_needed)
        indices = np.concatenate(
            [np.arange(start, start + block_bins) for start in starts]
        )[:row_count]
        sample = train.iloc[indices]
        positive += cumulative_source_coefficient(
            sample, baseline_features, source_features
        ) > 0
    return float(positive / resamples)


def weekly_diagnostic(
    joined: pd.DataFrame,
    baseline_features: list[str],
    source_features: list[str],
    config: dict[str, Any],
) -> dict[str, float | int | bool | None]:
    train = joined.loc[joined["split"].eq("train")]
    validation = joined.loc[joined["split"].eq("validation")]
    if len(train) < int(config["minimum_weekly_bins_train"]) or len(
        validation
    ) < int(config["minimum_weekly_bins_validation"]):
        return {
            "weekly_available": False,
            "weekly_train_rows": int(len(train)),
            "weekly_validation_rows": int(len(validation)),
            "weekly_source_coefficient_sum": None,
            "weekly_validation_rmse_improvement": None,
            "weekly_validation_mae_improvement": None,
        }
    restricted = fit_ols(train, "propagation_residual", baseline_features)
    full_features = [*baseline_features, *source_features]
    full = fit_ols(train, "propagation_residual", full_features)
    actual = validation["propagation_residual"].to_numpy(float)
    restricted_metrics = regression_metrics(
        actual, predict_ols(validation, baseline_features, restricted)
    )
    full_metrics = regression_metrics(
        actual, predict_ols(validation, full_features, full)
    )
    return {
        "weekly_available": True,
        "weekly_train_rows": int(len(train)),
        "weekly_validation_rows": int(len(validation)),
        "weekly_source_coefficient_sum": float(full[-len(source_features) :].sum()),
        "weekly_validation_rmse_improvement": improvement(
            restricted_metrics["rmse"], full_metrics["rmse"]
        ),
        "weekly_validation_mae_improvement": improvement(
            restricted_metrics["mae"], full_metrics["mae"]
        ),
    }


def validate_edges(
    primary_panel: pd.DataFrame,
    weekly_panel: pd.DataFrame,
    selected_edges: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    primary_lags = [int(value) for value in config["primary_lags_bins"]]
    weekly_lags = [int(value) for value in config["weekly_lags_bins"]]
    primary_lagged = prepare_lagged_panel(
        primary_panel.loc[primary_panel["split"].isin(["train", "validation"])],
        lags=primary_lags,
        bin_days=int(config["primary_bin_days"]),
    )
    weekly_lagged = prepare_lagged_panel(
        weekly_panel.loc[weekly_panel["split"].isin(["train", "validation"])],
        lags=weekly_lags,
        bin_days=int(config["robustness_bin_days"]),
    )

    rows: list[dict[str, Any]] = []
    for edge in selected_edges.itertuples(index=False):
        primary, baseline_features, source_features = build_edge_frame(
            primary_lagged,
            vegetable_id=int(edge.vegetable_id),
            source_city_id=str(edge.source_city_id),
            target_city_id=str(edge.target_city_id),
            lags=primary_lags,
        )
        train = primary.loc[primary["split"].eq("train")].copy()
        split_index = len(train) // 2
        first_half = train.iloc[:split_index]
        second_half = train.iloc[split_index:]
        first_sum = cumulative_source_coefficient(
            first_half, baseline_features, source_features
        )
        second_sum = cumulative_source_coefficient(
            second_half, baseline_features, source_features
        )
        bootstrap_rate = moving_block_positive_rate(
            train,
            baseline_features,
            source_features,
            resamples=int(config["bootstrap_resamples"]),
            block_bins=int(config["bootstrap_block_bins"]),
            seed=_edge_seed(
                int(config["bootstrap_seed"]),
                int(edge.vegetable_id),
                str(edge.source_city_id),
                str(edge.target_city_id),
            ),
        )
        weekly, weekly_baseline, weekly_source = build_edge_frame(
            weekly_lagged,
            vegetable_id=int(edge.vegetable_id),
            source_city_id=str(edge.source_city_id),
            target_city_id=str(edge.target_city_id),
            lags=weekly_lags,
        )
        weekly_result = weekly_diagnostic(
            weekly, weekly_baseline, weekly_source, config
        )
        halves_positive = first_sum > 0 and second_sum > 0
        stability_pass = halves_positive and bootstrap_rate >= float(
            config["minimum_stability_rate"]
        )
        weekly_positive = bool(
            weekly_result["weekly_available"]
            and float(weekly_result["weekly_source_coefficient_sum"]) > 0
        )
        rows.append(
            {
                **edge._asdict(),
                "first_half_train_rows": int(len(first_half)),
                "second_half_train_rows": int(len(second_half)),
                "first_half_source_coefficient_sum": first_sum,
                "second_half_source_coefficient_sum": second_sum,
                "train_halves_direction_consistent": halves_positive,
                "bootstrap_resamples": int(config["bootstrap_resamples"]),
                "bootstrap_block_bins": int(config["bootstrap_block_bins"]),
                "bootstrap_positive_direction_rate": bootstrap_rate,
                **weekly_result,
                "weekly_direction_consistent": weekly_positive,
                "frequency_sensitive": not weekly_positive,
                "stability_pass": stability_pass,
                "final_test_eligible": stability_pass,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["vegetable_id", "stability_pass", "bootstrap_positive_direction_rate"],
        ascending=[True, False, False],
    )


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# P5 稳定性验证报告",
        "",
        "## 结论",
        "",
        f"对 validation 冻结的 {payload['validation_selected_edges']} 条边完成训练分窗、moving-block bootstrap 和周频敏感性检查；{payload['stability_pass_edges']} 条通过预设稳定性硬门槛并冻结进入 final test。此处仍未读取 final test。",
        "",
        "| 产品 | Validation边 | 稳定边 | 周频同向边 |",
        "|---|---:|---:|---:|",
    ]
    for row in payload["products"]:
        lines.append(
            f"| {row['vegetable_name_zh']} | {row['validation_edges']} | {row['stability_edges']} | {row['weekly_direction_consistent_edges']} |"
        )
    lines.extend(
        [
            "",
            "## 判定规则",
            "",
            f"硬门槛为训练期前后半段累计来源系数均为正，且 {payload['bootstrap_resamples']} 次、每块 {payload['bootstrap_block_bins']} 个 3 日箱的 moving-block bootstrap 中正方向比例至少 {payload['minimum_stability_rate']:.0%}。周频方向与 validation 增益作为敏感性信息完整披露，不在结果产生后追加为淘汰门槛。",
            "",
            "## 解释边界",
            "",
            "稳定性降低了偶然相关的风险，但不能识别贸易流或因果机制。共同天气、产量、库存和测量变化仍可能产生剩余关联。",
            "",
            "Gate：`conditional_pass_to_final_test`。",
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
    model_dir = root / config["model_artifact_dir"]
    selected = pd.read_parquet(model_dir / "validation_candidate_scorecard.parquet")
    selected = selected.loc[selected["validation_pass"]].copy()
    scorecard = validate_edges(
        pd.read_parquet(mart_dir / "primary_panel.parquet"),
        pd.read_parquet(mart_dir / "weekly_panel.parquet"),
        selected,
        config,
    )
    output_dir = root / config["stability_artifact_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = output_dir / "stability_scorecard.parquet"
    scorecard.to_parquet(scorecard_path, index=False)
    products: list[dict[str, Any]] = []
    for keys, group in scorecard.groupby(
        ["vegetable_id", "vegetable_code", "vegetable_name_zh"], observed=True
    ):
        products.append(
            {
                "vegetable_id": int(keys[0]),
                "vegetable_code": keys[1],
                "vegetable_name_zh": keys[2],
                "validation_edges": int(len(group)),
                "stability_edges": int(group["stability_pass"].sum()),
                "weekly_direction_consistent_edges": int(
                    group["weekly_direction_consistent"].sum()
                ),
            }
        )
    payload = {
        "stability_version": "p5_stability_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "stability_frozen",
        "validation_selected_edges": int(len(scorecard)),
        "stability_pass_edges": int(scorecard["stability_pass"].sum()),
        "weekly_direction_consistent_edges": int(
            scorecard["weekly_direction_consistent"].sum()
        ),
        "bootstrap_resamples": int(config["bootstrap_resamples"]),
        "bootstrap_block_bins": int(config["bootstrap_block_bins"]),
        "bootstrap_seed": int(config["bootstrap_seed"]),
        "minimum_stability_rate": float(config["minimum_stability_rate"]),
        "products": products,
        "final_test_evaluated": False,
        "candidate_edges_reselected": False,
        "scorecard": {
            "path": str(scorecard_path.relative_to(root)),
            "rows": int(len(scorecard)),
            "sha256": sha256(scorecard_path),
        },
    }
    write_json(output_dir / "summary.json", payload)
    frozen = scorecard.loc[scorecard["stability_pass"]].copy()
    write_json(
        output_dir / "frozen_edges.json",
        {
            "stability_version": payload["stability_version"],
            "frozen_after": str(config["validation_end"]),
            "edge_count": int(len(frozen)),
            "final_test_evaluated": False,
            "thresholds_reselected": False,
            "edges": frozen[
                [
                    "vegetable_id",
                    "vegetable_code",
                    "vegetable_name_zh",
                    "source_city_id",
                    "source_city_name_zh",
                    "target_city_id",
                    "target_city_name_zh",
                    "expected_delay_days",
                    "fdr_q_value",
                    "validation_rmse_improvement",
                    "bootstrap_positive_direction_rate",
                    "weekly_direction_consistent",
                ]
            ].to_dict(orient="records"),
        },
    )
    (root / "docs/p5_stability_report.md").write_text(
        render_report(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "validation_selected_edges": payload["validation_selected_edges"],
                "stability_pass_edges": payload["stability_pass_edges"],
                "weekly_direction_consistent_edges": payload[
                    "weekly_direction_consistent_edges"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
