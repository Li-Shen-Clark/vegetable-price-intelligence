#!/usr/bin/env python3
"""Build the frozen P2 validation baseline predictions and scorecard."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.forecast.audit_p2_feasibility import sha256
from src.forecast.metrics import point_metric_record


BASELINES = [
    ("last_valid_price", "origin_price"),
    ("weekly_pattern", "weekly_pattern_median"),
    ("historical_seasonal", "historical_seasonal_median"),
]
KEY_COLUMNS = [
    "vegetable_id",
    "vegetable_code",
    "vegetable_name_zh",
    "city_id",
    "origin_date",
    "horizon_days",
    "target_date",
]


def score_by_groups(
    predictions: pd.DataFrame,
    group_columns: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    grouped = predictions.groupby(group_columns, sort=True, observed=True, dropna=False)
    for group_key, frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        dimensions = dict(zip(group_columns, group_key))
        for baseline_name, _ in BASELINES:
            records.append(
                {
                    **{
                        key: value.item() if hasattr(value, "item") else value
                        for key, value in dimensions.items()
                    },
                    "baseline": baseline_name,
                    **point_metric_record(frame["actual_price"], frame[baseline_name]),
                }
            )
    return records


def build_scorecard(root: Path) -> dict[str, Any]:
    mart_path = root / "data/modeling/p2_forecast_mart/validation.parquet"
    frame = pd.read_parquet(mart_path)
    if set(frame["split"]) != {"validation"}:
        raise ValueError("baseline task may read validation mart only")
    predictions = frame[KEY_COLUMNS + ["target_price"]].rename(
        columns={"target_price": "actual_price"}
    )
    for baseline_name, source_column in BASELINES:
        predictions[baseline_name] = frame[source_column].astype(float)
    baseline_columns = [name for name, _ in BASELINES]
    if not np.isfinite(predictions[baseline_columns].to_numpy(dtype=float)).all():
        raise ValueError("all baseline predictions must be finite on paired rows")
    if not predictions[baseline_columns].gt(0).all().all():
        raise ValueError("all baseline predictions must be positive")
    if predictions.duplicated(
        ["vegetable_id", "city_id", "origin_date", "horizon_days"]
    ).any():
        raise ValueError("baseline predictions have duplicate task keys")

    output_dir = root / "artifacts/p2/baselines"
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / "validation_predictions.parquet"
    temporary_path = output_dir / ".validation_predictions.parquet.tmp"
    predictions.to_parquet(temporary_path, index=False, compression="zstd")
    os.replace(temporary_path, prediction_path)

    product_horizon = score_by_groups(
        predictions,
        ["vegetable_id", "vegetable_name_zh", "horizon_days"],
    )
    overall = score_by_groups(predictions, ["horizon_days"])
    series = score_by_groups(
        predictions,
        ["vegetable_id", "vegetable_name_zh", "city_id", "horizon_days"],
    )
    score_frame = pd.DataFrame(product_horizon)
    baseline_order = {name: index for index, (name, _) in enumerate(BASELINES)}
    score_frame["baseline_order"] = score_frame["baseline"].map(baseline_order)
    best_rows = (
        score_frame.sort_values(
            ["vegetable_id", "horizon_days", "wape", "baseline_order"]
        )
        .groupby(["vegetable_id", "horizon_days"], sort=True, as_index=False)
        .first()
    )
    best_baselines = [
        {
            "vegetable_id": int(row.vegetable_id),
            "vegetable_name_zh": str(row.vegetable_name_zh),
            "horizon_days": int(row.horizon_days),
            "baseline": str(row.baseline),
            "validation_wape": round(float(row.wape), 8),
            "row_count": int(row.row_count),
        }
        for row in best_rows.itertuples(index=False)
    ]
    scorecard = {
        "scorecard_version": "p2_validation_baselines_v0.1",
        "status": "frozen_validation_only",
        "final_test_opened": False,
        "input": {
            "path": str(mart_path.relative_to(root)),
            "sha256": sha256(mart_path),
        },
        "predictions": {
            "path": str(prediction_path.relative_to(root)),
            "sha256": sha256(prediction_path),
            "row_count": int(len(predictions)),
            "paired_row_count": int(len(predictions)),
            "baseline_columns": baseline_columns,
        },
        "definitions": {
            name: {"source_column": source, "tie_break_order": index}
            for index, (name, source) in enumerate(BASELINES)
        },
        "best_baselines": best_baselines,
        "product_horizon_scores": product_horizon,
        "overall_horizon_scores": overall,
        "series_scores": series,
    }
    scorecard_path = output_dir / "validation_scorecard.json"
    temporary_scorecard = output_dir / ".validation_scorecard.json.tmp"
    temporary_scorecard.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_scorecard, scorecard_path)
    return scorecard


def render_markdown(scorecard: dict[str, Any]) -> str:
    scores = pd.DataFrame(scorecard["product_horizon_scores"])
    pivot = scores.pivot_table(
        index=["vegetable_id", "vegetable_name_zh", "horizon_days"],
        columns="baseline",
        values="wape",
        aggfunc="first",
    ).reset_index()
    best_lookup = {
        (row["vegetable_id"], row["horizon_days"]): row
        for row in scorecard["best_baselines"]
    }
    lines = [
        "# P2 正式验证基线报告",
        "",
        "> 状态：2020 validation 基线已冻结；最终测试未打开。  ",
        f"> Paired rows：{scorecard['predictions']['row_count']:,}",
        "",
        "## 1. 基线定义",
        "",
        "- `last_valid_price`：预测起点当日或最多前 1 日的最近有效价格。",
        "- `weekly_pattern`：在预测起点以前，与目标日星期相同的最近 4 条有效价格中位数。",
        "- `historical_seasonal`：预测起点以前、与目标月份相同的历史价格中位数；样本不足时回退全历史中位数。",
        "",
        "三个基线对完全相同的 11,882 行评分。每个产品×跨度以 WAPE 最低者作为后续候选模型必须击败的基线；平局按上面顺序处理。",
        "",
        "## 2. 产品×跨度 WAPE",
        "",
        "| 产品 | 跨度 | 最近价格 | 周度模式 | 历史季节 | 最佳基线 | 最佳 WAPE |",
        "|---|---:|---:|---:|---:|---|---:|",
    ]
    for row in pivot.itertuples(index=False):
        best = best_lookup[(int(row.vegetable_id), int(row.horizon_days))]
        lines.append(
            f"| {row.vegetable_name_zh} | {int(row.horizon_days)}日 | "
            f"{float(row.last_valid_price):.2%} | {float(row.weekly_pattern):.2%} | "
            f"{float(row.historical_seasonal):.2%} | `{best['baseline']}` | "
            f"{float(best['validation_wape']):.2%} |"
        )
    lines.extend(
        [
            "",
            "## 3. 总体跨度表现",
            "",
            "| 跨度 | 基线 | WAPE | MAE | sMAPE | 行数 |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in scorecard["overall_horizon_scores"]:
        lines.append(
            f"| {row['horizon_days']}日 | `{row['baseline']}` | {row['wape']:.2%} | "
            f"{row['mae']:.3f} | {row['smape']:.2%} | {row['row_count']:,} |"
        )
    lines.extend(
        [
            "",
            "## 4. 使用边界",
            "",
            "- 本报告只用于模型选择前的验证基准，不是最终测试成绩。",
            "- 最终测试基线将在 P2-T5 与冻结模型同时生成，确保相同 paired rows。",
            "- 旧版全历史 WAPE 不参与任何比较。",
            "- 基线是最低可信门槛；复杂模型若不稳定优于它，应直接回退基线。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report", default="docs/p2_baseline_report.md")
    args = parser.parse_args()
    root = args.root.resolve()
    scorecard = build_scorecard(root)
    (root / args.report).write_text(render_markdown(scorecard), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": scorecard["status"],
                "rows": scorecard["predictions"]["row_count"],
                "best_baseline_count": len(scorecard["best_baselines"]),
                "final_test_opened": scorecard["final_test_opened"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

