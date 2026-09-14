#!/usr/bin/env python3
"""Run the frozen P4 parameter grid and summarize ranking stability."""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.procurement.common import load_flat_yaml, sha256, write_json
from src.procurement.engine import default_parameters, rank_sources


def scenario_summary(
    rows: pd.DataFrame,
    default_scenario: dict,
    combination_count: int,
) -> dict:
    default_ranks = {
        item["city_id"]: int(item["rank"]) for item in default_scenario["candidates"]
    }
    city_rows = []
    for (city_id, city_name, province), group in rows.groupby(
        ["city_id", "city_name_zh", "province_name_zh"], sort=True, observed=True
    ):
        top3_count = int(group["combination_id"].nunique())
        first_count = int(group.loc[group["rank"].eq(1), "combination_id"].nunique())
        city_rows.append(
            {
                "city_id": str(city_id),
                "city_name_zh": str(city_name),
                "province_name_zh": str(province),
                "default_rank": default_ranks.get(str(city_id)),
                "top3_count": top3_count,
                "top3_share": float(top3_count / combination_count),
                "first_count": first_count,
                "first_share": float(first_count / combination_count),
                "mean_rank_when_selected": float(group["rank"].mean()),
                "minimum_unit_landed_cost": float(group["unit_landed_cost"].min()),
                "maximum_unit_landed_cost": float(group["unit_landed_cost"].max()),
            }
        )
    city_rows.sort(
        key=lambda item: (
            -item["first_share"],
            -item["top3_share"],
            item["mean_rank_when_selected"],
            item["city_id"],
        )
    )
    default_first = default_scenario["candidates"][0]["city_id"]
    default_first_row = next(item for item in city_rows if item["city_id"] == default_first)
    return {
        "target_city_id": default_scenario["target_city"]["city_id"],
        "target_city_name_zh": default_scenario["target_city"]["city_name_zh"],
        "vegetable_id": int(default_scenario["vegetable_id"]),
        "vegetable_name_zh": default_scenario["vegetable_name_zh"],
        "horizon_days": int(default_scenario["horizon_days"]),
        "combination_count": int(combination_count),
        "default_first_city_id": default_first,
        "default_first_city_name_zh": default_scenario["candidates"][0]["city_name_zh"],
        "default_first_share": default_first_row["first_share"],
        "distinct_first_cities": int(rows.loc[rows["rank"].eq(1), "city_id"].nunique()),
        "distinct_top3_cities": int(rows["city_id"].nunique()),
        "candidate_stability": city_rows,
    }


def render_report(payload: dict) -> str:
    stable = payload["most_stable_case"]
    sensitive = payload["most_sensitive_case"]
    return f"""# P4 参数敏感性报告

## 范围

- 默认目标城市：北京市；默认跨度：28 日；10 种核心蔬菜。
- 每个产品运行 {payload['combination_count']} 个组合，共 {payload['scenario_count'] * payload['combination_count']} 个情景。
- 每个情景保存 Top 3，因此明细共 {payload['row_count']} 行。
- 变化参数：4 个运输费率、3 个损耗率、3 个风险偏好。其他门槛保持默认值。

## 排名稳定性

- 最稳定案例：{stable['vegetable_name_zh']}。默认第一名为{stable['default_first_city_name_zh']}，在 {stable['default_first_share']:.1%} 的参数组合中仍为第一名，共出现 {stable['distinct_first_cities']} 个不同第一名城市。
- 最敏感案例：{sensitive['vegetable_name_zh']}。默认第一名为{sensitive['default_first_city_name_zh']}，第一名保持率为 {sensitive['default_first_share']:.1%}，共出现 {sensitive['distinct_first_cities']} 个不同第一名城市。

## 解释

损耗率对同一产品下所有候选使用相同乘数，单独变化时通常不会改变名次；运输费率会惩罚远距离低价城市，风险偏好会惩罚残差缓冲更高或数据可靠性较低的城市。页面应展示进入 Top 3 和成为第一名的频率，而不是只展示默认参数下的一次排名。

这些结果是历史参数化情景，不代表真实供应商稳定性或已实现节省。
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
    defaults = json.loads(
        (root / "artifacts/p4/default_scenarios.json").read_text(encoding="utf-8")
    )
    base_parameters = default_parameters(config)
    grid = list(
        itertools.product(
            config["sensitivity_transport_costs"],
            config["sensitivity_loss_rates"],
            config["sensitivity_risk_aversions"],
        )
    )
    if len(grid) != 36 or len(set(grid)) != 36:
        raise ValueError("Frozen P4 sensitivity grid must contain 36 unique combinations")

    rows: list[dict] = []
    for default_scenario in defaults["scenarios"]:
        for index, (transport, loss, risk) in enumerate(grid, 1):
            parameters = replace(
                base_parameters,
                transport_cost_per_kg_km=float(transport),
                loss_rate=float(loss),
                risk_aversion=float(risk),
            )
            result = rank_sources(
                snapshot,
                city_geo,
                default_scenario["target_city"]["city_id"],
                int(default_scenario["vegetable_id"]),
                int(default_scenario["horizon_days"]),
                parameters,
            )
            if result["status"] != "ok" or len(result["candidates"]) != 3:
                raise ValueError("Every sensitivity combination must return three candidates")
            for candidate in result["candidates"]:
                rows.append(
                    {
                        "combination_id": f"combo_{index:02d}",
                        "target_city_id": result["target_city"]["city_id"],
                        "target_city_name_zh": result["target_city"]["city_name_zh"],
                        "vegetable_id": int(result["vegetable_id"]),
                        "vegetable_name_zh": result["vegetable_name_zh"],
                        "horizon_days": int(result["horizon_days"]),
                        "transport_cost_per_kg_km": float(transport),
                        "loss_rate": float(loss),
                        "risk_aversion": float(risk),
                        "city_id": candidate["city_id"],
                        "city_name_zh": candidate["city_name_zh"],
                        "province_name_zh": candidate["province_name_zh"],
                        "rank": int(candidate["rank"]),
                        "unit_landed_cost": float(candidate["unit_landed_cost"]),
                        "total_landed_cost": float(candidate["total_landed_cost"]),
                    }
                )
    detail = pd.DataFrame(rows).sort_values(
        ["vegetable_id", "combination_id", "rank"]
    ).reset_index(drop=True)
    expected_rows = len(defaults["scenarios"]) * len(grid) * 3
    if len(detail) != expected_rows or detail.duplicated(
        ["vegetable_id", "horizon_days", "combination_id", "rank"]
    ).any():
        raise ValueError("Sensitivity detail row count or key failed")

    summaries = []
    for default_scenario in defaults["scenarios"]:
        group = detail.loc[
            detail["vegetable_id"].eq(int(default_scenario["vegetable_id"]))
            & detail["horizon_days"].eq(int(default_scenario["horizon_days"]))
        ]
        summaries.append(scenario_summary(group, default_scenario, len(grid)))
    stable = max(
        summaries,
        key=lambda item: (item["default_first_share"], -item["distinct_first_cities"]),
    )
    sensitive = min(
        summaries,
        key=lambda item: (item["default_first_share"], -item["distinct_first_cities"]),
    )
    detail_path = root / "artifacts/p4/sensitivity_rows.parquet"
    detail.to_parquet(detail_path, index=False)
    payload = {
        "artifact_version": "p4_sensitivity_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_scenario": True,
        "scenario_count": len(summaries),
        "combination_count": len(grid),
        "row_count": len(detail),
        "detail_sha256": sha256(detail_path),
        "parameter_grid": {
            "transport_cost_per_kg_km": config["sensitivity_transport_costs"],
            "loss_rate": config["sensitivity_loss_rates"],
            "risk_aversion": config["sensitivity_risk_aversions"],
        },
        "most_stable_case": {key: value for key, value in stable.items() if key != "candidate_stability"},
        "most_sensitive_case": {key: value for key, value in sensitive.items() if key != "candidate_stability"},
        "scenarios": summaries,
    }
    write_json(root / "artifacts/p4/sensitivity_summary.json", payload)
    (root / "docs/p4_sensitivity_report.md").write_text(
        render_report(payload), encoding="utf-8"
    )
    print(f"built {len(detail)} sensitivity rows across {len(summaries)} scenarios")


if __name__ == "__main__":
    main()
