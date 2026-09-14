#!/usr/bin/env python3
"""Audit the frozen P5 propagation contract before estimating directional edges."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.forecast.audit_p2_feasibility import load_scope_products
from src.procurement.common import load_flat_yaml, sha256, write_json


REQUIRED_CONFIG_KEYS = {
    "experiment_version",
    "status",
    "scope_config_path",
    "city_fact_path",
    "coverage_tier_path",
    "city_geo_path",
    "audit_json_path",
    "audit_markdown_path",
    "protocol_markdown_path",
    "propagation_mart_dir",
    "mart_version",
    "baseline_artifact_dir",
    "model_artifact_dir",
    "stability_artifact_dir",
    "final_artifact_dir",
    "official_tiers",
    "shadow_tiers",
    "excluded_quality_flags",
    "train_start",
    "train_end",
    "validation_start",
    "validation_end",
    "final_test_start",
    "final_test_end",
    "primary_frequency",
    "primary_bin_days",
    "primary_anchor_date",
    "primary_minimum_observations_per_bin",
    "robustness_frequency",
    "robustness_bin_days",
    "robustness_anchor_date",
    "robustness_minimum_observations_per_bin",
    "minimum_primary_bins_train",
    "minimum_primary_bins_validation",
    "minimum_primary_bins_final_test",
    "minimum_weekly_bins_train",
    "minimum_weekly_bins_validation",
    "minimum_weekly_bins_final_test",
    "minimum_eligible_cities_per_product",
    "minimum_common_factor_peers",
    "minimum_city_seasonal_observations",
    "shock_quantile",
    "minimum_train_shocks_per_product",
    "minimum_validation_shocks_per_product",
    "minimum_final_test_shocks_per_product",
    "same_province_priority",
    "maximum_candidate_sources_per_target",
    "minimum_candidate_sources_per_target",
    "maximum_candidate_pair_share",
    "primary_lags_bins",
    "weekly_lags_bins",
    "minimum_model_train_rows",
    "minimum_model_validation_rows",
    "minimum_model_final_test_rows",
    "fdr_q",
    "bootstrap_resamples",
    "bootstrap_block_bins",
    "minimum_stability_rate",
    "validation_minimum_rmse_improvement",
    "validation_maximum_mae_degradation",
    "final_minimum_positive_rmse_improvement",
    "strong_edge_minimum_rmse_improvement",
    "release_minimum_products",
    "release_minimum_edges_per_product",
    "release_minimum_positive_edge_share",
    "release_minimum_median_rmse_improvement",
    "final_test_consumed",
}

SPLITS = ("train", "validation", "final_test")


def validate_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_CONFIG_KEYS.difference(config)
    if missing:
        raise ValueError(f"P5 config misses keys: {sorted(missing)}")
    if config["status"] != "frozen":
        raise ValueError("P5 config must be frozen before the feasibility audit")
    if config["official_tiers"] != ["A"] or config["shadow_tiers"] != ["B"]:
        raise ValueError("P5 v0.1 requires Tier A official and Tier B shadow pools")
    if config["primary_frequency"] != "3D" or int(config["primary_bin_days"]) != 3:
        raise ValueError("P5 primary frequency must be anchored three-day bins")
    if config["robustness_frequency"] != "W-MON" or int(config["robustness_bin_days"]) != 7:
        raise ValueError("P5 robustness frequency must be Monday-anchored weeks")
    if config["primary_lags_bins"] != [1, 2, 3, 4]:
        raise ValueError("P5 primary lag set must be 1-4 three-day bins")
    if config["weekly_lags_bins"] != [1, 2]:
        raise ValueError("P5 weekly lag set must be 1-2 weeks")
    if not 0 < float(config["shock_quantile"]) < 1:
        raise ValueError("Shock quantile must be between zero and one")
    if float(config["fdr_q"]) != 0.05:
        raise ValueError("P5 v0.1 freezes BH-FDR at q=0.05")
    if bool(config["final_test_consumed"]):
        raise ValueError("Final test must remain unconsumed at P5-T0")
    minimum_sources = int(config["minimum_candidate_sources_per_target"])
    maximum_sources = int(config["maximum_candidate_sources_per_target"])
    if not 1 <= minimum_sources <= maximum_sources <= 8:
        raise ValueError("Candidate-source bounds must be ordered and capped at eight")
    if not 0 < float(config["maximum_candidate_pair_share"]) <= 0.35:
        raise ValueError("Candidate pair share must be in (0, 0.35]")
    boundaries = {
        name: (
            pd.Timestamp(config[f"{name}_start"]),
            pd.Timestamp(config[f"{name}_end"]),
        )
        for name in SPLITS
    }
    if not (
        boundaries["train"][0] <= boundaries["train"][1]
        < boundaries["validation"][0] <= boundaries["validation"][1]
        < boundaries["final_test"][0] <= boundaries["final_test"][1]
    ):
        raise ValueError("P5 train, validation and final-test windows must be disjoint")


def assign_split(dates: pd.Series, config: dict[str, Any]) -> pd.Series:
    result = pd.Series(pd.NA, index=dates.index, dtype="string")
    for split in SPLITS:
        start = pd.Timestamp(config[f"{split}_start"])
        end = pd.Timestamp(config[f"{split}_end"])
        result.loc[dates.between(start, end)] = split
    return result


def build_binned_panel(
    fact: pd.DataFrame,
    *,
    anchor_date: str,
    bin_days: int,
    minimum_observations: int,
) -> pd.DataFrame:
    frame = fact.copy()
    anchor = pd.Timestamp(anchor_date)
    offsets = (frame["date"] - anchor).dt.days
    frame["bin_start"] = anchor + pd.to_timedelta(
        np.floor_divide(offsets.to_numpy(), bin_days) * bin_days,
        unit="D",
    )
    grouped = (
        frame.groupby(
            ["vegetable_id", "vegetable_code", "vegetable_name_zh", "city_id", "bin_start"],
            observed=True,
            as_index=False,
        )
        .agg(
            analysis_price=("analysis_price", "median"),
            observed_days=("date", "nunique"),
            mean_source_reliability=("source_reliability_score", "mean"),
        )
    )
    grouped = grouped.loc[grouped["observed_days"].ge(minimum_observations)].copy()
    grouped.sort_values(["vegetable_id", "city_id", "bin_start"], inplace=True)
    grouped["previous_bin_start"] = grouped.groupby(
        ["vegetable_id", "city_id"], observed=True
    )["bin_start"].shift(1)
    grouped["previous_price"] = grouped.groupby(
        ["vegetable_id", "city_id"], observed=True
    )["analysis_price"].shift(1)
    consecutive = grouped["bin_start"].sub(grouped["previous_bin_start"]).dt.days.eq(bin_days)
    grouped["log_return"] = np.where(
        consecutive,
        np.log(grouped["analysis_price"]) - np.log(grouped["previous_price"]),
        np.nan,
    )
    return grouped


def coverage_table(panel: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    frame = panel.copy()
    frame["split"] = assign_split(frame["bin_start"], config)
    frame = frame.loc[frame["split"].notna()]
    counts = (
        frame.groupby(["vegetable_id", "city_id", "split"], observed=True)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for split in SPLITS:
        if split not in counts:
            counts[split] = 0
    return counts[["vegetable_id", "city_id", *SPLITS]]


def eligible_series(
    primary: pd.DataFrame,
    weekly: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    primary_counts = coverage_table(primary, config).rename(
        columns={split: f"primary_{split}" for split in SPLITS}
    )
    weekly_counts = coverage_table(weekly, config).rename(
        columns={split: f"weekly_{split}" for split in SPLITS}
    )
    merged = primary_counts.merge(
        weekly_counts,
        on=["vegetable_id", "city_id"],
        how="inner",
        validate="one_to_one",
    )
    mask = pd.Series(True, index=merged.index)
    for split in SPLITS:
        mask &= merged[f"primary_{split}"].ge(
            int(config[f"minimum_primary_bins_{split}"])
        )
        mask &= merged[f"weekly_{split}"].ge(
            int(config[f"minimum_weekly_bins_{split}"])
        )
    return merged.loc[mask].reset_index(drop=True)


def add_propagation_residuals(
    primary: pd.DataFrame,
    eligible: pd.DataFrame,
    config: dict[str, Any],
    *,
    bin_days: int = 3,
) -> pd.DataFrame:
    keys = eligible[["vegetable_id", "city_id"]]
    panel = primary.merge(keys, on=["vegetable_id", "city_id"], how="inner")
    panel["split"] = assign_split(panel["bin_start"], config)
    panel = panel.loc[panel["split"].notna() & panel["log_return"].notna()].copy()
    if bin_days == 7:
        panel["season_position"] = panel["bin_start"].dt.isocalendar().week.astype(int)
    else:
        panel["season_position"] = (
            (panel["bin_start"].dt.dayofyear - 1) // bin_days
        ).astype(int)

    train = panel.loc[panel["split"].eq("train")]
    city_season = (
        train.groupby(
            ["vegetable_id", "city_id", "season_position"], observed=True
        )["log_return"]
        .agg([("city_seasonal_return", "median"), ("city_seasonal_n", "size")])
        .reset_index()
    )
    product_season = (
        train.groupby(["vegetable_id", "season_position"], observed=True)["log_return"]
        .median()
        .rename("product_seasonal_return")
        .reset_index()
    )
    panel = panel.merge(
        city_season,
        on=["vegetable_id", "city_id", "season_position"],
        how="left",
        validate="many_to_one",
    ).merge(
        product_season,
        on=["vegetable_id", "season_position"],
        how="left",
        validate="many_to_one",
    )
    use_city = panel["city_seasonal_n"].ge(
        int(config["minimum_city_seasonal_observations"])
    )
    panel["seasonal_return"] = panel["city_seasonal_return"].where(
        use_city, panel["product_seasonal_return"]
    )
    panel["seasonally_adjusted_return"] = panel["log_return"] - panel["seasonal_return"]

    common = np.full(len(panel), np.nan, dtype=float)
    peers = np.zeros(len(panel), dtype=int)
    for _, positions in panel.groupby(["vegetable_id", "bin_start"], observed=True).indices.items():
        pos = np.asarray(positions, dtype=int)
        values = panel.iloc[pos]["seasonally_adjusted_return"].to_numpy(dtype=float)
        finite = np.isfinite(values)
        finite_count = int(finite.sum())
        for local_index, absolute_position in enumerate(pos):
            if not finite[local_index]:
                continue
            peer_values = values[finite].copy()
            own_rank = int(finite[:local_index].sum())
            peer_values = np.delete(peer_values, own_rank)
            peers[absolute_position] = len(peer_values)
            if len(peer_values) >= int(config["minimum_common_factor_peers"]):
                common[absolute_position] = float(np.median(peer_values))
    panel["common_factor_loo"] = common
    panel["common_factor_peer_count"] = peers
    panel["propagation_residual"] = (
        panel["seasonally_adjusted_return"] - panel["common_factor_loo"]
    )

    thresholds = (
        panel.loc[panel["split"].eq("train") & panel["propagation_residual"].notna()]
        .groupby(["vegetable_id", "city_id"], observed=True)["propagation_residual"]
        .quantile(float(config["shock_quantile"]))
        .rename("train_shock_threshold")
        .reset_index()
    )
    panel = panel.merge(
        thresholds,
        on=["vegetable_id", "city_id"],
        how="left",
        validate="many_to_one",
    )
    panel["positive_shock"] = panel["propagation_residual"].gt(
        panel["train_shock_threshold"]
    )
    return panel


def haversine_km(
    source_lat: np.ndarray,
    source_lon: np.ndarray,
    target_lat: float,
    target_lon: float,
) -> np.ndarray:
    radius_km = 6371.0088
    source_lat_r = np.radians(source_lat)
    target_lat_r = math.radians(target_lat)
    delta_lat = source_lat_r - target_lat_r
    delta_lon = np.radians(source_lon - target_lon)
    a = np.sin(delta_lat / 2) ** 2 + np.cos(source_lat_r) * math.cos(
        target_lat_r
    ) * np.sin(delta_lon / 2) ** 2
    return 2 * radius_km * np.arcsin(np.sqrt(a))


def build_candidate_edges(
    eligible: pd.DataFrame,
    tiers: pd.DataFrame,
    geo: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    cities = eligible[["vegetable_id", "city_id"]].merge(
        tiers[
            ["vegetable_id", "vegetable_code", "vegetable_name_zh", "city_id"]
        ],
        on=["vegetable_id", "city_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        geo[["city_id", "city_name_zh", "province_name_zh", "longitude", "latitude"]],
        on="city_id",
        how="left",
        validate="many_to_one",
    )
    rows: list[dict[str, Any]] = []
    density_cap = float(config["maximum_candidate_pair_share"])
    maximum_sources = int(config["maximum_candidate_sources_per_target"])
    for vegetable_id, product_cities in cities.groupby("vegetable_id", observed=True):
        product_cities = product_cities.sort_values("city_id").reset_index(drop=True)
        city_count = len(product_cities)
        source_limit = min(maximum_sources, math.floor(density_cap * (city_count - 1)))
        for target in product_cities.itertuples(index=False):
            candidates = product_cities.loc[product_cities["city_id"].ne(target.city_id)].copy()
            candidates["distance_km"] = haversine_km(
                candidates["latitude"].to_numpy(float),
                candidates["longitude"].to_numpy(float),
                float(target.latitude),
                float(target.longitude),
            )
            candidates["same_province"] = candidates["province_name_zh"].eq(
                target.province_name_zh
            )
            candidates.sort_values(
                ["same_province", "distance_km", "city_id"],
                ascending=[False, True, True],
                inplace=True,
            )
            for rank, source in enumerate(candidates.head(source_limit).itertuples(index=False), 1):
                rows.append(
                    {
                        "vegetable_id": int(vegetable_id),
                        "vegetable_code": target.vegetable_code,
                        "vegetable_name_zh": target.vegetable_name_zh,
                        "source_city_id": source.city_id,
                        "target_city_id": target.city_id,
                        "candidate_rank": rank,
                        "same_province": bool(source.same_province),
                        "distance_km": float(source.distance_km),
                        "candidate_rule": "same_province_then_nearest_capped",
                    }
                )
    return pd.DataFrame(rows)


def render_protocol(config: dict[str, Any]) -> str:
    return f"""# P5 价格冲击传播实验协议

## 冻结范围

- 产品：P2 冻结的 10 种核心蔬菜；正式城市池为产品内 Tier A。
- 时间：训练期 {config['train_start']}—{config['train_end']}，validation {config['validation_start']}—{config['validation_end']}，final test {config['final_test_start']}—{config['final_test_end']}。
- 主频率：3 日箱，每箱至少 {config['primary_minimum_observations_per_bin']} 个有效城市日；周频为稳健性。
- 候选边：每目标最多 {config['maximum_candidate_sources_per_target']} 个来源且不超过完整有向对的 {float(config['maximum_candidate_pair_share']):.0%}，同省优先、距离补足。
- 统计：训练期联合检验按产品执行 BH-FDR q={config['fdr_q']}；validation 冻结边与阈值；final test 只使用一次。

## 经济机制与竞争解释

空间套利、信息扩散和潜在贸易联系可能形成方向性预测关系；全国供给、天气、季节和共同测量变化也可能产生同步价格变化。因此必须先剔除训练期季节项和 leave-one-out 全国共同因子，再检验来源城市滞后信息是否改善目标城市自身滞后基线。

## 发布边界

结果只能称为“预测性传播关系”或“lead-lag”。没有流量、天气、产量、库存、真实运输网络或外生冲击识别，不能声称因果贸易流。传播信号只用于提前扩大成本、供应和报价人工复核范围，不生成零售价或执行调价。
"""


def render_audit(payload: dict[str, Any]) -> str:
    lines = [
        "# P5-T0 可行性审计",
        "",
        "## 结论",
        "",
        f"状态：`{payload['status']}`。本审计只放行传播 mart、公共因子和基线开发；尚未估计、选择或展示任何方向边。",
        "",
        "## 产品级支持",
        "",
        "| 产品 | Tier A | P5 可用城市 | 候选边 | 完整对占比 | Train/Validation/Final 正向冲击 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["products"]:
        lines.append(
            "| {name} | {tier_a} | {eligible} | {edges} | {share:.1%} | {train}/{validation}/{final_test} |".format(
                name=row["vegetable_name_zh"],
                tier_a=row["tier_a_cities"],
                eligible=row["eligible_cities"],
                edges=row["candidate_edges"],
                share=row["candidate_pair_share"],
                train=row["positive_shocks"]["train"],
                validation=row["positive_shocks"]["validation"],
                final_test=row["positive_shocks"]["final_test"],
            )
        )
    lines.extend(
        [
            "",
            "## 硬检查",
            "",
            *[
                f"- `{key}`：{'pass' if value else 'fail'}"
                for key, value in payload["checks"].items()
            ],
            "",
            "## Economics & Pricing Gate",
            "",
            "- G1：输出只触发成本、供应和报价人工复核。",
            "- G2：共同冲击是空间套利/信息扩散的竞争解释，必须先剔除。",
            "- G3：产品、城市、频率、候选边和滞后均已事前限制。",
            "- G4：自身滞后是最低基线；当前没有因果识别。",
            "- G5：FDR、重采样、窗口稳定性与样本外增益仍是后续硬门槛。",
            "- G6：只作为 Pricing Engine 的上游风险范围输入。",
            "- G7：数据截止 2022-06-22；无流量、天气、产量、库存和真实运输网络。",
            "",
            "Gate：`conditional_pass_to_mart`。若后续没有稳定样本外边，必须降级为 `common_shock_only`。",
            "",
        ]
    )
    return "\n".join(lines)


def run_audit(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    products = load_scope_products(root / config["scope_config_path"])
    product_ids = {int(item["vegetable_id"]) for item in products}

    tiers = pd.read_parquet(root / config["coverage_tier_path"])
    tiers = tiers.loc[
        tiers["vegetable_id"].isin(product_ids)
        & tiers["coverage_tier"].isin(config["official_tiers"])
    ].copy()
    geo = pd.read_csv(root / config["city_geo_path"])
    if geo["city_id"].duplicated().any() or geo[["longitude", "latitude"]].isna().any().any():
        raise ValueError("P5 requires one complete coordinate row per city")

    eligible_keys = tiers[["vegetable_id", "city_id"]]
    fact = pd.read_parquet(
        root / config["city_fact_path"],
        columns=[
            "date",
            "vegetable_id",
            "vegetable_code",
            "vegetable_name_zh",
            "city_id",
            "analysis_price",
            "source_reliability_score",
            "data_quality_flag",
        ],
    )
    fact["date"] = pd.to_datetime(fact["date"])
    fact = fact.loc[
        fact["vegetable_id"].isin(product_ids)
        & fact["analysis_price"].gt(0)
        & ~fact["data_quality_flag"].isin(config["excluded_quality_flags"])
        & fact["date"].between(
            pd.Timestamp(config["train_start"]),
            pd.Timestamp(config["final_test_end"]),
        )
    ].merge(eligible_keys, on=["vegetable_id", "city_id"], how="inner")

    primary = build_binned_panel(
        fact,
        anchor_date=str(config["primary_anchor_date"]),
        bin_days=int(config["primary_bin_days"]),
        minimum_observations=int(config["primary_minimum_observations_per_bin"]),
    )
    weekly = build_binned_panel(
        fact,
        anchor_date=str(config["robustness_anchor_date"]),
        bin_days=int(config["robustness_bin_days"]),
        minimum_observations=int(config["robustness_minimum_observations_per_bin"]),
    )
    eligible = eligible_series(primary, weekly, config)
    residuals = add_propagation_residuals(
        primary, eligible, config, bin_days=int(config["primary_bin_days"])
    )
    edges = build_candidate_edges(eligible, tiers, geo, config)

    tier_counts = tiers.groupby("vegetable_id", observed=True)["city_id"].nunique()
    eligible_counts = eligible.groupby("vegetable_id", observed=True)["city_id"].nunique()
    shock_counts = (
        residuals.loc[residuals["positive_shock"]]
        .groupby(["vegetable_id", "split"], observed=True)
        .size()
        .unstack(fill_value=0)
    )
    product_rows: list[dict[str, Any]] = []
    for item in products:
        vegetable_id = int(item["vegetable_id"])
        city_count = int(eligible_counts.get(vegetable_id, 0))
        product_edges = edges.loc[edges["vegetable_id"].eq(vegetable_id)]
        possible_edges = city_count * (city_count - 1)
        per_target = product_edges.groupby("target_city_id").size()
        shocks = {
            split: int(shock_counts.loc[vegetable_id, split])
            if vegetable_id in shock_counts.index and split in shock_counts.columns
            else 0
            for split in SPLITS
        }
        product_rows.append(
            {
                "vegetable_id": vegetable_id,
                "vegetable_code": item["vegetable_code"],
                "vegetable_name_zh": item["vegetable_name_zh"],
                "tier_a_cities": int(tier_counts.get(vegetable_id, 0)),
                "eligible_cities": city_count,
                "candidate_edges": int(len(product_edges)),
                "possible_directed_edges": int(possible_edges),
                "candidate_pair_share": float(len(product_edges) / possible_edges)
                if possible_edges
                else 0.0,
                "minimum_sources_per_target": int(per_target.min()) if len(per_target) else 0,
                "maximum_sources_per_target": int(per_target.max()) if len(per_target) else 0,
                "median_candidate_distance_km": float(product_edges["distance_km"].median())
                if len(product_edges)
                else None,
                "same_province_edge_share": float(product_edges["same_province"].mean())
                if len(product_edges)
                else 0.0,
                "positive_shocks": shocks,
            }
        )

    checks = {
        "ten_core_products_present": len(product_rows) == 10
        and all(row["tier_a_cities"] > 0 for row in product_rows),
        "minimum_eligible_cities": all(
            row["eligible_cities"] >= int(config["minimum_eligible_cities_per_product"])
            for row in product_rows
        ),
        "candidate_density_capped": all(
            row["candidate_pair_share"]
            <= float(config["maximum_candidate_pair_share"]) + 1e-12
            for row in product_rows
        ),
        "candidate_sources_bounded": all(
            row["minimum_sources_per_target"]
            >= int(config["minimum_candidate_sources_per_target"])
            and row["maximum_sources_per_target"]
            <= int(config["maximum_candidate_sources_per_target"])
            for row in product_rows
        ),
        "train_shock_support": all(
            row["positive_shocks"]["train"]
            >= int(config["minimum_train_shocks_per_product"])
            for row in product_rows
        ),
        "validation_shock_support": all(
            row["positive_shocks"]["validation"]
            >= int(config["minimum_validation_shocks_per_product"])
            for row in product_rows
        ),
        "final_test_support_only": all(
            row["positive_shocks"]["final_test"]
            >= int(config["minimum_final_test_shocks_per_product"])
            for row in product_rows
        ),
        "no_directional_models_fitted": True,
        "final_test_not_used_for_selection": not bool(config["final_test_consumed"]),
    }
    status = "pass" if all(checks.values()) else "fail"
    payload = {
        "audit_version": "p5_feasibility_v0.1",
        "experiment_version": config["experiment_version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks": checks,
        "products": product_rows,
        "totals": {
            "tier_a_series": int(len(tiers)),
            "eligible_series": int(len(eligible)),
            "primary_bin_rows": int(len(primary)),
            "weekly_bin_rows": int(len(weekly)),
            "residual_rows": int(residuals["propagation_residual"].notna().sum()),
            "candidate_edges": int(len(edges)),
        },
        "method_flags": {
            "directional_models_fitted": False,
            "fdr_tests_run": False,
            "candidate_edges_selected_from_prices": False,
            "final_test_used_for_selection": False,
        },
        "inputs": {
            key: {
                "path": str(config[key]),
                "sha256": sha256(root / config[key]),
            }
            for key in ["scope_config_path", "city_fact_path", "coverage_tier_path", "city_geo_path"]
        },
    }
    if status != "pass":
        failed = [key for key, value in checks.items() if not value]
        raise ValueError(f"P5 feasibility audit failed: {failed}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p5_propagation_experiment.yaml")
    payload = run_audit(root, config)

    json_path = root / config["audit_json_path"]
    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(json_path, payload)
    (root / config["audit_markdown_path"]).write_text(
        render_audit(payload), encoding="utf-8"
    )
    (root / config["protocol_markdown_path"]).write_text(
        render_protocol(config), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "eligible_series": payload["totals"]["eligible_series"],
                "candidate_edges": payload["totals"]["candidate_edges"],
                "directional_models_fitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
