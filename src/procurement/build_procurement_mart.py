#!/usr/bin/env python3
"""Build the frozen P4 historical procurement snapshot and risk calibration table."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.procurement.common import load_flat_yaml, sha256, write_json


KEYS = ["vegetable_id", "city_id", "origin_date", "horizon_days", "target_date"]


def release_routes(release_payload: dict) -> pd.DataFrame:
    rows = []
    for item in release_payload["group_results"]:
        rows.append(
            {
                "vegetable_id": int(item["vegetable_id"]),
                "horizon_days": int(item["horizon_days"]),
                "release_status_expected": str(item["release_status"]),
                "release_point_source": str(item["release_point_source"]),
                "release_interval_expected": bool(item["release_interval"]),
            }
        )
    result = pd.DataFrame(rows)
    if len(result) != 30 or result.duplicated(["vegetable_id", "horizon_days"]).any():
        raise ValueError("P2 release matrix must contain 30 unique product-horizon groups")
    return result


def risk_calibration(
    predictions: pd.DataFrame,
    routes: pd.DataFrame,
    scenario_date: pd.Timestamp,
    quantile: float,
    minimum_rows: int,
) -> pd.DataFrame:
    history = predictions.merge(
        routes,
        on=["vegetable_id", "horizon_days"],
        how="left",
        validate="many_to_one",
    )
    history = history.loc[
        history["target_date"].lt(scenario_date)
        & history["target_price"].gt(0)
        & history["released_point_prediction"].gt(0)
    ].copy()
    history["absolute_log_error"] = np.abs(
        np.log(history["target_price"] / history["released_point_prediction"])
    )
    rows: list[dict] = []
    for keys, group in history.groupby(
        ["vegetable_id", "vegetable_name_zh", "horizon_days", "release_point_source"],
        sort=True,
        observed=True,
    ):
        vegetable_id, vegetable_name, horizon, route = keys
        if len(group) < minimum_rows:
            raise ValueError(
                f"Insufficient product-horizon-route residuals: {keys} has {len(group)}"
            )
        rows.append(
            {
                "vegetable_id": int(vegetable_id),
                "vegetable_name_zh": str(vegetable_name),
                "horizon_days": int(horizon),
                "release_point_source": str(route),
                "calibration_level": "product_horizon_route",
                "sample_count": int(len(group)),
                "residual_quantile": float(quantile),
                "q80_absolute_log_error": float(
                    group["absolute_log_error"].quantile(quantile, interpolation="linear")
                ),
                "median_absolute_log_error": float(group["absolute_log_error"].median()),
                "calibration_target_start": group["target_date"].min(),
                "calibration_target_end": group["target_date"].max(),
                "scenario_origin_date": scenario_date,
                "no_lookahead_pass": bool(group["target_date"].max() < scenario_date),
            }
        )
    result = pd.DataFrame(rows).sort_values(
        ["vegetable_id", "horizon_days"]
    ).reset_index(drop=True)
    if len(result) != 30 or not result["no_lookahead_pass"].all():
        raise ValueError("Risk calibration must cover 30 groups without lookahead")
    return result


def attach_reliability(
    root: Path,
    config: dict,
    snapshot: pd.DataFrame,
    scenario_date: pd.Timestamp,
) -> pd.DataFrame:
    lookback_days = int(config["reliability_lookback_days"])
    start = scenario_date - pd.Timedelta(days=lookback_days)
    fact = pd.read_parquet(
        root / config["city_fact_path"],
        columns=[
            "date",
            "vegetable_id",
            "city_id",
            "source_reliability_score",
            "data_quality_flag",
            "number_of_reporting_markets",
        ],
        filters=[("date", ">=", start.date()), ("date", "<=", scenario_date.date())],
    )
    fact["date"] = pd.to_datetime(fact["date"])
    if fact.duplicated(["date", "vegetable_id", "city_id"]).any():
        raise ValueError("Gold city reliability keys must be unique")
    exact = fact.rename(
        columns={
            "date": "origin_price_date",
            "source_reliability_score": "origin_source_reliability_score",
            "data_quality_flag": "origin_data_quality_flag",
            "number_of_reporting_markets": "origin_reporting_markets",
        }
    )
    result = snapshot.merge(
        exact,
        on=["vegetable_id", "city_id", "origin_price_date"],
        how="left",
        validate="many_to_one",
    )
    result["reliability_source"] = np.where(
        result["origin_source_reliability_score"].notna(),
        "origin_price_date_exact",
        "trailing_28d_median",
    )
    trailing = (
        fact.loc[fact["date"].le(scenario_date)]
        .groupby(["vegetable_id", "city_id"], observed=True)["source_reliability_score"]
        .median()
        .rename("trailing_reliability")
        .reset_index()
    )
    result = result.merge(
        trailing, on=["vegetable_id", "city_id"], how="left", validate="many_to_one"
    )
    result["origin_source_reliability_score"] = result[
        "origin_source_reliability_score"
    ].fillna(result["trailing_reliability"])
    result.drop(columns=["trailing_reliability"], inplace=True)
    if result["origin_source_reliability_score"].isna().any():
        missing = result.loc[
            result["origin_source_reliability_score"].isna(),
            ["vegetable_id", "city_id"],
        ].drop_duplicates()
        raise ValueError(f"Missing P4 source reliability: {missing.to_dict('records')}")
    return result


def price_labels(frame: pd.DataFrame) -> pd.DataFrame:
    source = frame["release_point_source"].astype(str)
    baseline_last = source.eq("baseline:last_valid_price")
    baseline_seasonal = source.eq("baseline:historical_seasonal")
    interval = frame["release_interval_expected"].astype(bool)
    frame["price_input_label"] = np.select(
        [baseline_last, baseline_seasonal, interval],
        [
            "当前价格延续（基线），不是模型预测",
            "历史季节中位数（基线），不是模型预测",
            "模型点预测与已校准区间",
        ],
        default="模型点预测；区间未通过校准",
    )
    frame["interval_status"] = np.select(
        [baseline_last | baseline_seasonal, interval],
        ["not_applicable_baseline", "calibrated_released"],
        default="not_released_under_p2_gate",
    )
    frame["risk_basis"] = np.where(
        interval,
        "released_p90_minus_point",
        "historical_released_route_q80_log_error",
    )
    return frame


def render_data_dictionary() -> str:
    return """# P4 采购快照数据字典

## `scenario_snapshot.parquet`

粒度为产品×来源城市×历史情景起点×预测跨度。点价格逐组沿用 P2 发布路线；城市坐标来自 `dim_city_geo.csv`；可靠性来自预测起点实际报价日期的 Gold 城市日事实。

| 字段 | 含义 |
|---|---|
| `released_point_prediction` | P2 正式发布点价格，可能是模型或冻结基线，元/公斤 |
| `release_status` / `release_point_source` | P2 发布状态与实际点价格来源 |
| `released_p10` / `released_p90` | 仅 P2 允许发布的区间；其他组为空 |
| `price_input_label` | 面向用户的模型或基线说明 |
| `origin_source_reliability_score` | 起点实际使用报价日的数据可靠性分数 |
| `reliability_source` | 精确起点报价日或过去28日中位数回退 |
| `base_uncertainty_per_kg` | 合格区间上沿缓冲或无前视历史残差缓冲，元/公斤 |
| `risk_basis` | 风险缓冲来源；经验残差不是校准区间 |
| `eligible_under_default_reliability` | 是否通过默认 0.65 可靠性阈值 |
| `later_actual_price` | 历史目标日真实价，只用于事后核对，不参与排名或风险校准 |

## `residual_calibration.parquet`

每个产品×跨度×实际发布路线一行。`q80_absolute_log_error` 只使用 `target_date < 2022-05-01` 的已完成 P2 final-test 历史预测；所有组至少 30 行。该表提供未发布区间切片的经验风险缓冲，不生成 P10/P90。
"""


def render_risk_report(calibration: pd.DataFrame, snapshot: pd.DataFrame) -> str:
    interval_groups = snapshot.loc[
        snapshot["interval_status"].eq("calibrated_released"),
        ["vegetable_id", "horizon_days"],
    ].drop_duplicates()
    return f"""# P4 风险缓冲校准

## 结果

- 校准分组：{len(calibration)} 个产品×跨度×发布路线。
- 历史残差行数范围：{int(calibration['sample_count'].min())}–{int(calibration['sample_count'].max())}。
- 绝对对数误差 Q80 范围：{calibration['q80_absolute_log_error'].min():.4f}–{calibration['q80_absolute_log_error'].max():.4f}。
- P2 合格区间组：{len(interval_groups)} 个；其快照行使用发布 P90−点预测。
- 其余组使用发布路线的历史 Q80 残差，且不展示为预测区间。
- 快照可靠性精确连接：{int(snapshot['reliability_source'].eq('origin_price_date_exact').sum())}/{len(snapshot)} 行。

## 使用边界

风险缓冲是采购情景中的保守成本加项。它把预测误差尺度和报价数据可靠性分开处理，但没有供货、运输延误或实时市场冲击数据，不能解释为总业务风险或概率保证。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p4_procurement.yaml")
    scenario_date = pd.Timestamp(config["scenario_origin_date"])

    import json

    release_payload = json.loads(
        (root / config["p2_release_matrix_path"]).read_text(encoding="utf-8")
    )
    routes = release_routes(release_payload)
    predictions = pd.read_parquet(root / config["p2_predictions_path"])
    forecast_mart = pd.read_parquet(
        root / config["forecast_mart_path"],
        columns=KEYS + ["origin_price_date", "origin_fill_days"],
    )
    for frame in [predictions, forecast_mart]:
        for column in ["origin_date", "target_date", "origin_price_date"]:
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column])
    predictions = predictions.merge(
        routes,
        on=["vegetable_id", "horizon_days"],
        how="left",
        validate="many_to_one",
    )
    if not predictions["release_status"].eq(
        predictions["release_status_expected"]
    ).all():
        raise ValueError("P2 predictions and release matrix status disagree")
    calibration = risk_calibration(
        predictions.drop(
            columns=[
                "release_status_expected",
                "release_interval_expected",
                "release_point_source",
            ]
        ),
        routes,
        scenario_date,
        float(config["residual_quantile"]),
        int(config["minimum_residual_rows"]),
    )

    snapshot = predictions.loc[predictions["origin_date"].eq(scenario_date)].copy()
    snapshot = snapshot.merge(forecast_mart, on=KEYS, how="left", validate="one_to_one")
    if snapshot[["origin_price_date", "origin_fill_days"]].isna().any().any():
        raise ValueError("P4 snapshot did not fully join P2 origin provenance")
    snapshot = attach_reliability(root, config, snapshot, scenario_date)
    geo = pd.read_csv(root / config["city_geo_path"])
    coverage = pd.read_parquet(root / config["coverage_tier_path"])[
        [
            "vegetable_id",
            "city_id",
            "coverage_tier",
            "coverage_rate",
            "active_span_coverage_rate",
            "mean_source_reliability_score",
            "poor_day_share",
            "forecast_eligible_flag",
        ]
    ]
    snapshot = snapshot.merge(
        geo[
            [
                "city_id",
                "city_name_zh",
                "province_name_zh",
                "longitude",
                "latitude",
                "coordinate_method",
                "geo_dimension_version",
            ]
        ],
        on="city_id",
        how="left",
        validate="many_to_one",
    ).merge(
        coverage,
        on=["vegetable_id", "city_id"],
        how="left",
        validate="many_to_one",
    )
    if not snapshot["coverage_tier"].eq(config["official_tier"]).all():
        raise ValueError("P4 snapshot must contain only Tier A sources")
    snapshot = snapshot.merge(
        calibration[
            [
                "vegetable_id",
                "horizon_days",
                "release_point_source",
                "calibration_level",
                "sample_count",
                "q80_absolute_log_error",
            ]
        ],
        on=["vegetable_id", "horizon_days", "release_point_source"],
        how="left",
        validate="many_to_one",
    )
    snapshot = price_labels(snapshot)
    interval_mask = snapshot["release_interval_expected"].astype(bool)
    valid_interval = (
        snapshot["released_p90"].notna()
        & snapshot["released_p10"].notna()
        & snapshot["released_p90"].ge(snapshot["released_point_prediction"])
    )
    if not valid_interval.eq(interval_mask).all():
        raise ValueError("P4 interval availability must exactly match the P2 release gate")
    empirical = snapshot["released_point_prediction"] * (
        np.exp(snapshot["q80_absolute_log_error"]) - 1.0
    )
    interval_buffer = (
        snapshot["released_p90"] - snapshot["released_point_prediction"]
    ).clip(lower=0)
    snapshot["base_uncertainty_per_kg"] = np.where(
        interval_mask, interval_buffer, empirical
    )
    snapshot["default_reliability_multiplier"] = np.clip(
        1.0
        + float(config["reliability_gamma"])
        * (1.0 - snapshot["origin_source_reliability_score"]),
        1.0,
        float(config["maximum_reliability_multiplier"]),
    )
    snapshot["default_risk_penalty_per_kg"] = (
        float(config["default_risk_aversion"])
        * snapshot["base_uncertainty_per_kg"]
        * snapshot["default_reliability_multiplier"]
    )
    snapshot["eligible_under_default_reliability"] = snapshot[
        "origin_source_reliability_score"
    ].ge(float(config["default_minimum_reliability"]))
    snapshot.rename(columns={"target_price": "later_actual_price"}, inplace=True)
    snapshot["mart_version"] = str(config["mart_version"])
    snapshot = snapshot.sort_values(
        ["vegetable_id", "horizon_days", "city_id"]
    ).reset_index(drop=True)
    if len(snapshot) != 843 or snapshot.duplicated(KEYS).any():
        raise ValueError("P4 snapshot must contain 843 unique P2 forecast tasks")
    finite_columns = [
        "released_point_prediction",
        "origin_source_reliability_score",
        "longitude",
        "latitude",
        "base_uncertainty_per_kg",
        "default_risk_penalty_per_kg",
    ]
    if not np.isfinite(snapshot[finite_columns].to_numpy(dtype=float)).all():
        raise ValueError("P4 snapshot contains non-finite required values")

    mart_dir = root / config["procurement_mart_dir"]
    mart_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = mart_dir / "scenario_snapshot.parquet"
    calibration_path = mart_dir / "residual_calibration.parquet"
    snapshot.to_parquet(snapshot_path, index=False)
    calibration.to_parquet(calibration_path, index=False)
    manifest = {
        "manifest_version": "p4_procurement_mart_manifest_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenario_origin_date": scenario_date.date().isoformat(),
        "snapshot": {
            "path": str(snapshot_path.relative_to(root)),
            "rows": int(len(snapshot)),
            "products": int(snapshot["vegetable_id"].nunique()),
            "cities": int(snapshot["city_id"].nunique()),
            "horizons": sorted(snapshot["horizon_days"].unique().astype(int).tolist()),
            "sha256": sha256(snapshot_path),
        },
        "residual_calibration": {
            "path": str(calibration_path.relative_to(root)),
            "rows": int(len(calibration)),
            "minimum_sample_count": int(calibration["sample_count"].min()),
            "maximum_target_date": calibration["calibration_target_end"].max().date().isoformat(),
            "sha256": sha256(calibration_path),
        },
        "release_status_counts": {
            str(key): int(value)
            for key, value in snapshot[["vegetable_id", "horizon_days", "release_status"]]
            .drop_duplicates()["release_status"]
            .value_counts()
            .items()
        },
        "risk_basis_row_counts": {
            str(key): int(value) for key, value in snapshot["risk_basis"].value_counts().items()
        },
        "reliability_source_counts": {
            str(key): int(value)
            for key, value in snapshot["reliability_source"].value_counts().items()
        },
    }
    write_json(mart_dir / "manifest.json", manifest)
    (root / "docs/p4_data_dictionary.md").write_text(
        render_data_dictionary(), encoding="utf-8"
    )
    (root / "docs/p4_risk_calibration.md").write_text(
        render_risk_report(calibration, snapshot), encoding="utf-8"
    )
    print(
        f"built P4 mart: {len(snapshot)} snapshot rows, "
        f"{len(calibration)} no-lookahead calibration groups"
    )


if __name__ == "__main__":
    main()
