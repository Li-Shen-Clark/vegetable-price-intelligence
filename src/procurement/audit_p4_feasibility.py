#!/usr/bin/env python3
"""Audit the frozen P4 procurement scenario contract before ranking sources."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.forecast.audit_p2_feasibility import load_scope_products
from src.procurement.build_city_geo import validate_geo
from src.procurement.common import load_flat_yaml, sha256, write_json


REQUIRED_CONFIG_KEYS = {
    "procurement_version",
    "status",
    "scenario_origin_date",
    "scope_config_path",
    "city_dimension_path",
    "market_mapping_path",
    "source_city_coordinates_path",
    "city_geo_path",
    "coverage_tier_path",
    "city_fact_path",
    "forecast_mart_path",
    "p2_predictions_path",
    "p2_release_matrix_path",
    "procurement_mart_dir",
    "official_tier",
    "horizons_days",
    "default_horizon_days",
    "default_target_city_id",
    "residual_quantile",
    "minimum_residual_rows",
    "residual_fallback_levels",
    "default_quantity_kg",
    "default_transport_cost_per_kg_km",
    "default_loss_rate",
    "default_max_distance_km",
    "default_road_factor",
    "default_risk_aversion",
    "default_minimum_reliability",
    "reliability_gamma",
    "maximum_reliability_multiplier",
    "reliability_lookback_days",
    "sensitivity_transport_costs",
    "sensitivity_loss_rates",
    "sensitivity_risk_aversions",
    "geo_dimension_version",
    "mart_version",
}


def validate_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_CONFIG_KEYS.difference(config)
    if missing:
        raise ValueError(f"P4 config misses keys: {sorted(missing)}")
    if config["status"] != "frozen":
        raise ValueError("P4 config must be frozen before implementation")
    if config["official_tier"] != "A":
        raise ValueError("P4 v0.1 official candidate pool must be Tier A")
    if config["horizons_days"] != [7, 14, 28] or config["default_horizon_days"] != 28:
        raise ValueError("P4 horizons must be 7/14/28 with 28-day default")
    if not 0 < float(config["residual_quantile"]) < 1:
        raise ValueError("Residual quantile must be between zero and one")
    if int(config["minimum_residual_rows"]) < 30:
        raise ValueError("P4 residual calibration requires at least 30 rows")
    if not 0 <= float(config["default_loss_rate"]) < 1:
        raise ValueError("Loss rate must be in [0, 1)")
    if float(config["default_quantity_kg"]) <= 0:
        raise ValueError("Procurement quantity must be positive")
    if len(config["sensitivity_transport_costs"]) * len(
        config["sensitivity_loss_rates"]
    ) * len(config["sensitivity_risk_aversions"]) != 36:
        raise ValueError("P4 v0.1 sensitivity grid must contain 36 combinations")


def render_protocol(config: dict[str, Any]) -> str:
    return f"""# P4 采购情景实验协议

## 冻结对象

- 历史情景日期：{config['scenario_origin_date']}。
- 产品：P2 的 10 种核心蔬菜；正式来源池：Tier A。
- 跨度：7、14、28 日，默认 28 日。
- 发布点价格：逐组严格沿用 P2 `release_matrix.json`；基线回退不得称为模型预测。
- 距离：117 城独立城市锚点的 Haversine 距离乘可编辑道路折算系数；不是公路 API 路线。
- 风险：合格区间使用 P90−P50；其余使用情景日期以前已完成发布预测的绝对对数残差 {float(config['residual_quantile']):.0%} 分位数。

## 防泄漏与证据边界

残差样本必须满足 `target_date < scenario_origin_date`。当前情景的真实目标价格只可用于事后核对，不得进入风险缓冲或候选排名。P4 不重新拟合 P2，不重新选择发布路线，也不为未通过校准的组生成伪区间。

采购量、运输费率、损耗率、道路折算、最大距离、风险偏好和可靠性阈值都是情景输入。数据没有供应能力、库存、成交量、供应商报价或真实运输路线，因此结果只支持历史采购情景比较，不生成采购订单或自动报价。
"""


def render_audit(payload: dict[str, Any]) -> str:
    releases = payload["release_matrix"]
    candidates = payload["snapshot_candidates"]
    return f"""# P4 可行性审计

## 结论

状态：`{payload['status']}`。117 城均有唯一城市锚点，P2 发布矩阵和 2022-05-01 快照可以支撑参数化采购情景。旧市场坐标已从正式距离计算中隔离。

## 核心检查

- 城市锚点：{payload['city_geo']['rows']} 行，{payload['city_geo']['unique_city_ids']} 个唯一城市；直接城市中心 {payload['city_geo']['city_center_rows']} 行，大理县级特殊锚点 {payload['city_geo']['exception_rows']} 行。
- 市场映射：`mapped_existing_city` {payload['market_mapping']['mapped_existing_city']} 行，`unmapped_new_city` {payload['market_mapping']['unmapped_new_city']} 行；正式市场坐标缺失 {payload['market_mapping']['missing_coordinates']} 行。
- P2 发布矩阵：`model_target` {releases.get('model_target', 0)}、`model_minimum` {releases.get('model_minimum', 0)}、`point_only_model` {releases.get('point_only_model', 0)}、`baseline_fallback` {releases.get('baseline_fallback', 0)}。
- 快照预测：{candidates['rows']} 行，覆盖 {candidates['products']} 种产品、{candidates['cities']} 个城市、{candidates['horizons']} 个跨度；每产品来源城市范围 {candidates['minimum_cities_per_product']}–{candidates['maximum_cities_per_product']}。
- 敏感性网格：{payload['sensitivity']['combinations']} 个组合。

## 放行边界

本审计只放行 P4 数据准备和情景引擎开发。所有输出仍是 Historical scenario；不得把城市中心距离称为公路里程，不得把基线价格称为模型预测，也不得把参数化排名称为真实供应建议。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p4_procurement.yaml")
    validate_config(config)
    products = load_scope_products(root / config["scope_config_path"])
    product_ids = {item["vegetable_id"] for item in products}

    dim_city = pd.read_csv(root / config["city_dimension_path"])
    city_geo = pd.read_csv(root / config["city_geo_path"])
    validate_geo(city_geo, dim_city)
    mapping = pd.read_csv(root / config["market_mapping_path"])
    release = json.loads((root / config["p2_release_matrix_path"]).read_text(encoding="utf-8"))
    predictions = pd.read_parquet(root / config["p2_predictions_path"])
    predictions["origin_date"] = pd.to_datetime(predictions["origin_date"])
    snapshot = predictions.loc[
        predictions["origin_date"].eq(pd.Timestamp(config["scenario_origin_date"]))
        & predictions["vegetable_id"].isin(product_ids)
        & predictions["horizon_days"].isin(config["horizons_days"])
    ].copy()
    city_counts = snapshot.groupby("vegetable_id")["city_id"].nunique()
    status_counts = {
        str(key): int(value)
        for key, value in pd.Series(release["status_counts"]).items()
    }
    expected_status = {
        "model_target": 1,
        "model_minimum": 3,
        "point_only_model": 16,
        "baseline_fallback": 10,
    }
    if status_counts != expected_status:
        raise ValueError(f"Unexpected P2 release matrix: {status_counts}")
    checks = {
        "city_geo_complete": bool(
            len(city_geo) == 117 and city_geo["city_id"].nunique() == 117
        ),
        "product_scope_complete": bool(set(snapshot["vegetable_id"]) == product_ids),
        "horizons_complete": bool(
            sorted(snapshot["horizon_days"].unique().tolist()) == [7, 14, 28]
        ),
        "released_points_positive": bool(
            snapshot["released_point_prediction"].gt(0).all()
        ),
        "release_matrix_frozen": bool(status_counts == expected_status),
        "sensitivity_grid_36": bool(len(config["sensitivity_transport_costs"])
        * len(config["sensitivity_loss_rates"])
        * len(config["sensitivity_risk_aversions"])
        == 36),
    }
    if not all(checks.values()):
        raise ValueError(f"P4 feasibility audit failed: {checks}")

    status_series = mapping["mapping_status"].value_counts()
    payload = {
        "audit_version": "p4_feasibility_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "scenario_origin_date": str(config["scenario_origin_date"]),
        "checks": checks,
        "city_geo": {
            "rows": int(len(city_geo)),
            "unique_city_ids": int(city_geo["city_id"].nunique()),
            "city_center_rows": int(city_geo["coordinate_method"].eq("city_center_snapshot").sum()),
            "exception_rows": int(city_geo["coordinate_method"].eq("verified_market_exception").sum()),
            "sha256": sha256(root / config["city_geo_path"]),
        },
        "market_mapping": {
            "mapped_existing_city": int(status_series.get("mapped_existing_city", 0)),
            "unmapped_new_city": int(status_series.get("unmapped_new_city", 0)),
            "missing_coordinates": int(
                mapping.loc[mapping["mapping_status"].eq("mapped_existing_city"), ["longitude", "latitude"]]
                .isna()
                .any(axis=1)
                .sum()
            ),
        },
        "release_matrix": status_counts,
        "snapshot_candidates": {
            "rows": int(len(snapshot)),
            "products": int(snapshot["vegetable_id"].nunique()),
            "cities": int(snapshot["city_id"].nunique()),
            "horizons": int(snapshot["horizon_days"].nunique()),
            "minimum_cities_per_product": int(city_counts.min()),
            "maximum_cities_per_product": int(city_counts.max()),
        },
        "sensitivity": {"combinations": 36},
        "inputs": {
            path_key: sha256(root / config[path_key])
            for path_key in [
                "city_dimension_path",
                "market_mapping_path",
                "source_city_coordinates_path",
                "p2_predictions_path",
                "p2_release_matrix_path",
            ]
        },
    }
    json_path = root / "docs/p4_feasibility_audit.json"
    write_json(json_path, payload)
    (root / "docs/p4_feasibility_audit.md").write_text(
        render_audit(payload), encoding="utf-8"
    )
    (root / "docs/p4_procurement_protocol.md").write_text(
        render_protocol(config), encoding="utf-8"
    )
    print(f"P4 feasibility audit passed: {len(snapshot)} snapshot forecast rows")


if __name__ == "__main__":
    main()
