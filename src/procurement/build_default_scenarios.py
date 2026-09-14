#!/usr/bin/env python3
"""Build reproducible default P4 procurement scenarios for all core products."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.procurement.common import load_flat_yaml, write_json
from src.procurement.engine import default_parameters, rank_sources


def render_methodology(results: list[dict]) -> str:
    available_local = sum(item["local_benchmark"] is not None for item in results)
    return f"""# P4 到岸成本与排名方法

## 默认历史情景

- 目标城市：北京市。
- 情景起点：2022-05-01；默认跨度：28 日。
- 10 种核心蔬菜均生成一组默认情景；{available_local}/10 有合格本地基准。
- 每组从通过可靠性和最大距离门槛的外地来源中返回单位到岸成本最低的 Top 3。

## 成本分解

1. 城市中心 Haversine 距离乘道路折算系数，得到估算运输距离。
2. 估算运输距离乘运输费率，得到单位运输成本。
3. P2 发布点价格、单位运输成本和风险惩罚相加，得到损耗前单位成本。
4. 损耗前单位成本除以 `1-loss_rate`，得到相同可用到货量口径的单位到岸成本。
5. 单位到岸成本乘到货可用采购量，得到情景总成本。

本地基准使用同一风险与损耗公式，但运输距离为零。外地模拟节省只在本地基准存在时计算。排名并列依次按单位到岸成本、来源可靠性降序和城市 ID 排序。

## 解释边界

采购量只线性改变总成本，不改变单位成本排名。当前没有供应能力、真实运价、道路路线或成交量，排名只表示给定参数下值得进一步询价的候选城市。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p4_procurement.yaml")
    snapshot = pd.read_parquet(
        root / config["procurement_mart_dir"] / "scenario_snapshot.parquet"
    )
    city_geo = pd.read_csv(root / config["city_geo_path"])
    parameters = default_parameters(config)
    product_ids = sorted(snapshot["vegetable_id"].unique().astype(int).tolist())
    results = [
        rank_sources(
            snapshot,
            city_geo,
            str(config["default_target_city_id"]),
            product_id,
            int(config["default_horizon_days"]),
            parameters,
        )
        for product_id in product_ids
    ]
    if any(item["status"] != "ok" or len(item["candidates"]) != 3 for item in results):
        raise ValueError("Every default P4 product scenario must have three candidates")
    payload = {
        "artifact_version": "p4_default_scenarios_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_scenario": True,
        "scenario_origin_date": str(config["scenario_origin_date"]),
        "default_target_city_id": str(config["default_target_city_id"]),
        "default_horizon_days": int(config["default_horizon_days"]),
        "parameters": parameters.__dict__,
        "scenario_count": len(results),
        "scenarios": results,
    }
    output = root / "artifacts/p4/default_scenarios.json"
    write_json(output, payload)
    (root / "docs/p4_cost_methodology.md").write_text(
        render_methodology(results), encoding="utf-8"
    )
    print(f"built {len(results)} default scenarios with three candidates each")


if __name__ == "__main__":
    main()
