#!/usr/bin/env python3
"""Export local-only P5 common-shock and city-exposure browser data."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml, sha256, write_json


TIMELINE_FIELDS = [
    "bin_start",
    "split",
    "common_factor",
    "seasonally_adjusted_return",
    "exposed_city_count",
    "observed_city_count",
    "positive_common_shock",
]

EXPOSURE_FIELDS = [
    "window_id",
    "city_id",
    "city_name_zh",
    "province_name_zh",
    "observed_bins",
    "positive_residual_shocks",
    "positive_residual_shock_rate",
    "common_factor_beta",
    "common_factor_correlation",
    "residual_volatility",
    "mean_source_reliability",
    "latest_analysis_price",
    "exposure_score",
    "exposure_rank",
]

WINDOWS = [
    {
        "id": "full_history",
        "label": "全历史 · 2014–2022",
        "splits": ["train", "validation", "final_test"],
    },
    {"id": "train", "label": "训练期 · 2014–2019", "splits": ["train"]},
    {
        "id": "validation",
        "label": "Validation · 2020",
        "splits": ["validation"],
    },
    {
        "id": "final_test",
        "label": "Final test · 2021–2022",
        "splits": ["final_test"],
    },
]


def json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return str(value)


def write_compact_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def product_timeline(group: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    timeline = (
        group.groupby(["bin_start", "split"], observed=True)
        .agg(
            common_factor=("common_factor_loo", "median"),
            seasonally_adjusted_return=("seasonally_adjusted_return", "median"),
            exposed_city_count=("positive_shock", "sum"),
            observed_city_count=("city_id", "nunique"),
        )
        .reset_index()
        .sort_values("bin_start")
    )
    train = timeline.loc[timeline["split"].eq("train"), "common_factor"]
    threshold = float(train.quantile(0.95))
    timeline["positive_common_shock"] = timeline["common_factor"].gt(threshold)
    return timeline, threshold


def _safe_beta_and_correlation(group: pd.DataFrame) -> tuple[float, float]:
    values = group[["common_factor_loo", "seasonally_adjusted_return"]].dropna()
    if len(values) < 4 or values["common_factor_loo"].var() <= 0:
        return float("nan"), float("nan")
    beta = float(
        values["common_factor_loo"].cov(values["seasonally_adjusted_return"])
        / values["common_factor_loo"].var()
    )
    correlation = float(
        values["common_factor_loo"].corr(values["seasonally_adjusted_return"])
    )
    return beta, correlation


def city_exposure(group: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        sample = group.loc[group["split"].isin(window["splits"])]
        window_rows: list[dict[str, Any]] = []
        for keys, city in sample.groupby(
            ["city_id", "city_name_zh", "province_name_zh"], observed=True
        ):
            beta, correlation = _safe_beta_and_correlation(city)
            latest = city.sort_values("bin_start").iloc[-1]
            window_rows.append(
                {
                    "window_id": window["id"],
                    "city_id": keys[0],
                    "city_name_zh": keys[1],
                    "province_name_zh": keys[2],
                    "observed_bins": int(len(city)),
                    "positive_residual_shocks": int(city["positive_shock"].sum()),
                    "positive_residual_shock_rate": float(city["positive_shock"].mean()),
                    "common_factor_beta": beta,
                    "common_factor_correlation": correlation,
                    "residual_volatility": float(city["propagation_residual"].std()),
                    "mean_source_reliability": float(
                        city["mean_source_reliability"].mean()
                    ),
                    "latest_analysis_price": float(latest["analysis_price"]),
                }
            )
        frame = pd.DataFrame(window_rows)
        sensitivity_rank = frame["common_factor_beta"].clip(lower=0).rank(pct=True)
        shock_rank = frame["positive_residual_shock_rate"].rank(pct=True)
        volatility_rank = frame["residual_volatility"].rank(pct=True)
        frame["exposure_score"] = (
            100 * (0.45 * shock_rank + 0.35 * sensitivity_rank + 0.20 * volatility_rank)
        )
        frame["exposure_rank"] = (
            frame["exposure_score"].rank(method="first", ascending=False).astype(int)
        )
        rows.extend(frame.to_dict(orient="records"))
    return pd.DataFrame(rows).sort_values(["window_id", "exposure_rank"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p5_propagation_experiment.yaml")
    panel = pd.read_parquet(
        root / config["propagation_mart_dir"] / "primary_panel.parquet"
    )
    final = json.loads(
        (root / config["final_artifact_dir"] / "release_decision.json").read_text(
            encoding="utf-8"
        )
    )
    decision = final["release_decision"]
    if decision["release_status"] != "common_shock_only":
        raise RuntimeError("This exporter implements the frozen common_shock_only view.")
    final_products = {
        int(item["vegetable_id"]): item for item in decision["products"]
    }
    output = root / "web/public/data/propagation"
    product_dir = output / "products"
    product_dir.mkdir(parents=True, exist_ok=True)
    product_metadata: list[dict[str, Any]] = []
    product_files: list[dict[str, Any]] = []
    for vegetable_id, group in panel.groupby("vegetable_id", sort=True, observed=True):
        timeline, threshold = product_timeline(group)
        exposures = city_exposure(group)
        vegetable_code = str(group["vegetable_code"].iloc[0])
        vegetable_name = str(group["vegetable_name_zh"].iloc[0])
        release_product = final_products.get(int(vegetable_id), {})
        relative = Path("data/propagation/products") / f"{int(vegetable_id)}.json"
        path = root / "web/public" / relative
        payload = {
            "schema_version": "p5_common_shock_product_v0.1",
            "historical_only": True,
            "release_status": "common_shock_only",
            "directional_edges_included": False,
            "product": {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": vegetable_code,
                "vegetable_name_zh": vegetable_name,
            },
            "positive_common_shock_threshold": threshold,
            "timeline_fields": TIMELINE_FIELDS,
            "timeline": [
                [json_value(row[field]) for field in TIMELINE_FIELDS]
                for _, row in timeline.iterrows()
            ],
            "exposure_fields": EXPOSURE_FIELDS,
            "city_exposures": [
                [json_value(row[field]) for field in EXPOSURE_FIELDS]
                for _, row in exposures.iterrows()
            ],
        }
        write_compact_json(path, payload)
        product_metadata.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_code": vegetable_code,
                "vegetable_name_zh": vegetable_name,
                "data_file": str(relative),
                "city_count": int(group["city_id"].nunique()),
                "common_shock_bins": int(timeline["positive_common_shock"].sum()),
                "validation_edges": int(release_product.get("frozen_edges", 0)),
                "final_confirmed_edges": int(
                    release_product.get("final_confirmed_edges", 0)
                ),
            }
        )
        product_files.append(
            {
                "path": str(relative),
                "timeline_rows": int(len(timeline)),
                "exposure_rows": int(len(exposures)),
                "sha256": sha256(path),
            }
        )
    diagnostic = final["common_factor_network_diagnostic"]
    metadata = {
        "schema_version": "p5_common_shock_metadata_v0.1",
        "title": "Common Shock & City Exposure",
        "historical_only": True,
        "data_as_of": str(config["final_test_end"]),
        "release_status": decision["release_status"],
        "directional_network_released": False,
        "release_message": "方向 lead-lag 未通过跨产品 final-test 门槛；当前只发布共同冲击与城市暴露。",
        "defaults": {
            "vegetable_id": 170060,
            "window_id": "final_test",
            "city_id": "all",
        },
        "windows": WINDOWS,
        "products": product_metadata,
        "evidence_funnel": [
            {"label": "事前地理候选", "count": 2736},
            {"label": "满足建模样本", "count": 991},
            {"label": "训练期 FDR", "count": 51},
            {"label": "Validation 保留", "count": 15},
            {"label": "稳定性通过", "count": 15},
            {"label": "Final 改善为正", "count": int(decision["final_confirmed_edges"])},
            {"label": "产品发布方向边", "count": 0},
        ],
        "release_metrics": {
            "frozen_edges": int(decision["frozen_edges"]),
            "final_confirmed_edges": int(decision["final_confirmed_edges"]),
            "final_strong_edges": int(decision["final_strong_edges"]),
            "positive_final_edge_share": float(decision["positive_final_edge_share"]),
            "median_final_rmse_improvement": float(
                decision["median_final_rmse_improvement"]
            ),
            "qualifying_products": int(decision["qualifying_products"]),
        },
        "common_factor_diagnostic": diagnostic,
        "exposure_score_formula": "45% 历史正向残差冲击率 + 35% 非负共同因子敏感度 + 20% 残差波动率的产品×窗口内百分位",
        "pricing_action": "用于扩大成本与报价人工复核范围；不是价格建议或自动调价触发器。",
        "boundary": "2014–2022 历史研究；无天气、产量、库存、销量或真实贸易流；共同变化不等于城市间因果传播。",
    }
    write_compact_json(output / "metadata.json", metadata)
    manifest = {
        "manifest_version": "p5_common_shock_web_manifest_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "release_status": decision["release_status"],
        "directional_edges_included": False,
        "metadata": {
            "path": "data/propagation/metadata.json",
            "sha256": sha256(output / "metadata.json"),
        },
        "products": product_files,
    }
    write_json(output / "manifest.json", manifest)
    print(
        f"built P5 common-shock web data: {len(product_files)} products; no directional edges"
    )


if __name__ == "__main__":
    main()
