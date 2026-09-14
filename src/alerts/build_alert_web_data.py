#!/usr/bin/env python3
"""Export compact P3 historical alert replay data for the local web app."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RECORD_FIELDS = [
    "city_id",
    "origin_date",
    "origin_price",
    "risk_probability",
    "action_threshold",
    "predicted_alert",
    "event_label",
    "future_peak_price",
    "future_peak_date",
    "future_peak_return_14d",
    "event_lead_days",
    "outcome_type",
    "severity",
    "event_scope",
    "regional_raw_event_share",
    "origin_data_quality_flag",
    "origin_fill_days",
    "event_effective_return_threshold",
    "best_baseline_risk_score",
    "origin_stale_quote_share",
    "origin_outlier_share",
]


def _clean(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _downsample_curve(curve: pd.DataFrame, points: int = 160) -> list[dict[str, float]]:
    model = curve[curve["score_source"].eq("frozen_model")].reset_index(drop=True)
    if len(model) > points:
        positions = np.unique(np.linspace(0, len(model) - 1, points).astype(int))
        model = model.iloc[positions]
    return [
        {
            "threshold": float(row.threshold),
            "precision": float(row.precision),
            "recall": float(row.recall),
            "false_positive_rate": float(row.false_positive_rate),
        }
        for row in model.itertuples(index=False)
    ]


def build(root: Path) -> dict[str, Any]:
    final_dir = root / "artifacts/p3/final"
    predictions = pd.read_parquet(final_dir / "final_test_predictions.parquet")
    scorecard = json.loads((final_dir / "final_scorecard.json").read_text(encoding="utf-8"))
    release = json.loads((final_dir / "release_decision.json").read_text(encoding="utf-8"))
    curve = pd.read_parquet(final_dir / "final_pr_curve.parquet")
    output = root / "web/public/data/alerts"
    products_dir = output / "products"
    products_dir.mkdir(parents=True, exist_ok=True)

    true_positives = predictions[predictions["outcome_type"].eq("true_positive")]
    if true_positives.empty:
        default_row = predictions.sort_values("risk_probability", ascending=False).iloc[0]
    else:
        default_row = true_positives.sort_values(
            ["risk_probability", "future_peak_return_14d"], ascending=False
        ).iloc[0]

    products = []
    files: dict[str, dict[str, Any]] = {}
    for vegetable_id, frame in predictions.groupby("vegetable_id", sort=True):
        frame = frame.sort_values(["origin_date", "city_id"]).reset_index(drop=True)
        name = str(frame.iloc[0]["vegetable_name_zh"])
        code = str(frame.iloc[0]["vegetable_code"])
        metrics = scorecard["by_product"][name]
        cities = (
            frame[["city_id", "market_city", "market_province"]]
            .drop_duplicates()
            .sort_values(["market_province", "market_city", "city_id"])
        )
        records = [
            [_clean(value) for value in row]
            for row in frame[RECORD_FIELDS].itertuples(index=False, name=None)
        ]
        relative_path = f"data/alerts/products/{int(vegetable_id)}.json"
        payload = {
            "historical_replay": True,
            "product": {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": code,
                "vegetable_name_zh": name,
            },
            "release_status": release["release_status"],
            "metrics": metrics,
            "cities": [
                {
                    "city_id": str(row.city_id),
                    "city_name_zh": str(row.market_city),
                    "province_name_zh": str(row.market_province),
                }
                for row in cities.itertuples(index=False)
            ],
            "origins": sorted(frame["origin_date"].astype(str).unique().tolist()),
            "record_fields": RECORD_FIELDS,
            "records": records,
        }
        path = products_dir / f"{int(vegetable_id)}.json"
        _write_json(path, payload)
        products.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": code,
                "vegetable_name_zh": name,
                "data_file": relative_path,
                "city_count": int(frame["city_id"].nunique()),
                "origin_count": int(frame["origin_date"].nunique()),
                "row_count": int(len(frame)),
                "event_count": int(frame["event_label"].sum()),
                "predicted_alert_count": int(frame["predicted_alert"].sum()),
                "average_precision": float(metrics["average_precision"]),
                "recall_at_frozen_threshold": float(
                    metrics["at_frozen_validation_threshold"]["recall"]
                ),
            }
        )
        files[relative_path] = {"rows": int(len(frame)), "sha256": _sha256(path)}

    overall = scorecard["overall"]
    fixed = overall["at_frozen_validation_threshold"]
    metadata = {
        "title": "Historical Price Risk Alert Replay",
        "historical_replay": True,
        "data_period": {"start": "2021-01-04", "end": "2022-06-20", "source_end": "2022-06-22"},
        "event_definition": "未来14天峰值涨幅至少20%，且超过起点以前历史季节90分位；同产品—城市21天内去重。",
        "model_name": scorecard["frozen_candidate"],
        "release_status": release["release_status"],
        "action_threshold": float(scorecard["frozen_validation_threshold"]),
        "overall": {
            "rows": int(overall["rows"]),
            "events": int(overall["events"]),
            "prevalence": float(overall["prevalence"]),
            "average_precision": float(overall["average_precision"]),
            "best_baseline_average_precision": float(scorecard["best_baseline_final_average_precision"]),
            "average_precision_lift_vs_baseline": float(scorecard["final_average_precision_lift_vs_baseline"]),
            "precision": float(fixed["precision"]),
            "recall": float(fixed["recall"]),
            "false_positive_rate": float(fixed["false_positive_rate"]),
            "false_alert_share": float(fixed["false_alert_share"]),
            "true_positives": int(fixed["true_positives"]),
            "mean_lead_days": float(overall["mean_lead_days"]),
            "top_decile_spike_recall": float(overall["top_decile_spike_recall"]),
        },
        "defaults": {
            "vegetable_id": int(default_row["vegetable_id"]),
            "city_id": str(default_row["city_id"]),
            "origin_date": str(default_row["origin_date"]),
        },
        "products": products,
        "pr_curve": _downsample_curve(curve),
        "status_definition": {
            "alert_release": "通过离线历史测试，可用于历史回放和人工复核触发设计；尚不是实时预警。",
            "research_only": "仅供研究回放，不应驱动业务动作。",
            "no_signal": "没有可发布的模型信号，只展示历史事实。",
        },
        "boundary": "本页使用2021年至2022年历史最终测试数据。风险提醒用于启动人工复核，不自动报价、不自动调价。",
    }
    metadata_path = output / "metadata.json"
    _write_json(metadata_path, metadata)
    files["data/alerts/metadata.json"] = {
        "rows": 1,
        "sha256": _sha256(metadata_path),
    }
    manifest = {
        "dataset": "p3_alert_web_v0.1",
        "release_status": release["release_status"],
        "record_fields": RECORD_FIELDS,
        "files": files,
        "total_rows": int(len(predictions)),
        "historical_replay": True,
    }
    manifest_path = output / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    manifest = build(args.root.resolve())
    print(json.dumps({"total_rows": manifest["total_rows"], "files": len(manifest["files"]), "release_status": manifest["release_status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
