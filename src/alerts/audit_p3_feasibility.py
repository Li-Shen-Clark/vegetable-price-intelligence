#!/usr/bin/env python3
"""Audit the frozen P3 alert sampling contract before labels or models are built."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_CONFIG_KEYS = {
    "experiment_version",
    "scope_config_path",
    "city_fact_path",
    "coverage_tier_path",
    "official_tiers",
    "shadow_tiers",
    "train_start",
    "train_end",
    "train_origin_start",
    "train_origin_end",
    "validation_start",
    "validation_end",
    "validation_origin_start",
    "validation_origin_end",
    "final_test_start",
    "final_test_end",
    "final_test_origin_start",
    "final_test_origin_end",
    "origin_frequency",
    "target_horizon_days",
    "minimum_future_observations",
    "minimum_history_observations",
    "origin_max_forward_fill_days",
    "excluded_quality_flags",
    "absolute_spike_threshold",
    "sensitivity_absolute_thresholds",
    "seasonal_quantile",
    "sensitivity_seasonal_quantiles",
    "event_deduplication_days",
    "fixed_false_positive_rate",
    "minimum_eligible_rows_per_product_split",
    "minimum_raw_spikes_for_diagnostic",
}


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def load_flat_yaml(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(" ") or ":" not in raw_line:
            raise ValueError(f"Unsupported flat YAML line {line_number}: {raw_line}")
        key, value = raw_line.split(":", 1)
        result[key.strip()] = _parse_scalar(value)
    return result


def load_scope_products(path: Path) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- vegetable_id:"):
            if current is not None:
                products.append(current)
            current = {"vegetable_id": int(stripped.split(":", 1)[1].strip())}
        elif current is not None and stripped.startswith("vegetable_code:"):
            current["vegetable_code"] = stripped.split(":", 1)[1].strip()
        elif current is not None and stripped.startswith("vegetable_name_zh:"):
            current["vegetable_name_zh"] = stripped.split(":", 1)[1].strip()
    if current is not None:
        products.append(current)
    required = {"vegetable_id", "vegetable_code", "vegetable_name_zh"}
    if len(products) != 10 or any(set(item) != required for item in products):
        raise ValueError("P3 scope must contain 10 complete product definitions")
    return products


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weekly_origins(start: str, end: str, frequency: str = "W-MON") -> list[pd.Timestamp]:
    return list(pd.date_range(start, end, freq=frequency))


def validate_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_CONFIG_KEYS.difference(config)
    if missing:
        raise ValueError(f"P3 experiment config misses keys: {sorted(missing)}")
    if config["official_tiers"] != ["A"] or config["shadow_tiers"] != ["B"]:
        raise ValueError("P3 v0.1 official pool must be Tier A and shadow pool Tier B")
    if config["origin_frequency"] != "W-MON":
        raise ValueError("P3 v0.1 requires Monday weekly origins")
    if int(config["target_horizon_days"]) != 14:
        raise ValueError("P3 v0.1 target horizon must be 14 days")
    if int(config["minimum_future_observations"]) > 14:
        raise ValueError("minimum future observations cannot exceed target horizon")
    if int(config["origin_max_forward_fill_days"]) not in {0, 1}:
        raise ValueError("origin fill may be at most one day")
    if float(config["absolute_spike_threshold"]) != 0.20:
        raise ValueError("primary absolute spike threshold must remain 20%")
    if float(config["seasonal_quantile"]) != 0.90:
        raise ValueError("primary seasonal quantile must remain 90%")
    if int(config["event_deduplication_days"]) != 21:
        raise ValueError("same-series events must be deduplicated within 21 days")
    if float(config["fixed_false_positive_rate"]) != 0.10:
        raise ValueError("validation threshold must be selected at 10% maximum FPR")

    names = ["train", "validation", "final_test"]
    boundaries = {
        name: (
            pd.Timestamp(config[f"{name}_start"]),
            pd.Timestamp(config[f"{name}_end"]),
            pd.Timestamp(config[f"{name}_origin_start"]),
            pd.Timestamp(config[f"{name}_origin_end"]),
        )
        for name in names
    }
    if not (
        boundaries["train"][0] <= boundaries["train"][1]
        < boundaries["validation"][0] <= boundaries["validation"][1]
        < boundaries["final_test"][0] <= boundaries["final_test"][1]
    ):
        raise ValueError("train, validation and final-test periods must be ordered and disjoint")
    horizon = pd.Timedelta(days=int(config["target_horizon_days"]))
    for name, (start, end, origin_start, origin_end) in boundaries.items():
        if origin_start < start or origin_end + horizon > end:
            raise ValueError(f"{name} origins do not fit inside the split target window")
        origins = weekly_origins(str(origin_start.date()), str(origin_end.date()), config["origin_frequency"])
        if not origins or any(origin.dayofweek != 0 for origin in origins):
            raise ValueError(f"{name} does not contain valid Monday origins")


def _series_audit(
    group: pd.DataFrame,
    origins: list[pd.Timestamp],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    valid = group[
        group["analysis_price"].gt(0)
        & ~group["data_quality_flag"].isin(config["excluded_quality_flags"])
    ].sort_values("date")
    if valid.empty:
        return []
    dates = valid["date"].to_numpy(dtype="datetime64[ns]")
    prices = valid["analysis_price"].to_numpy(dtype=float)
    max_lag = int(config["origin_max_forward_fill_days"])
    minimum_history = int(config["minimum_history_observations"])
    minimum_future = int(config["minimum_future_observations"])
    horizon = int(config["target_horizon_days"])
    thresholds = [float(value) for value in config["sensitivity_absolute_thresholds"]]
    results: list[dict[str, Any]] = []

    for origin in origins:
        origin64 = origin.to_datetime64()
        history_count = int(np.searchsorted(dates, origin64, side="left"))
        if history_count < minimum_history:
            continue
        origin_index = None
        origin_lag = None
        for lag in range(max_lag + 1):
            candidate = (origin - pd.Timedelta(days=lag)).to_datetime64()
            position = int(np.searchsorted(dates, candidate, side="left"))
            if position < len(dates) and dates[position] == candidate:
                origin_index = position
                origin_lag = lag
                break
        if origin_index is None:
            continue
        future_start = int(np.searchsorted(dates, origin64, side="right"))
        future_end = int(
            np.searchsorted(
                dates,
                (origin + pd.Timedelta(days=horizon)).to_datetime64(),
                side="right",
            )
        )
        future_prices = prices[future_start:future_end]
        if len(future_prices) < minimum_future:
            continue
        peak_return = float(future_prices.max() / prices[origin_index] - 1.0)
        row: dict[str, Any] = {
            "origin_date": origin,
            "origin_lag_days": int(origin_lag),
            "future_observations": int(len(future_prices)),
            "future_peak_return_14d": peak_return,
        }
        for threshold in thresholds:
            row[f"raw_spike_{int(round(threshold * 100))}"] = peak_return >= threshold
        results.append(row)
    return results


def run_audit(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    products = load_scope_products(root / config["scope_config_path"])
    product_ids = [item["vegetable_id"] for item in products]
    fact_path = root / config["city_fact_path"]
    tier_path = root / config["coverage_tier_path"]
    facts = pd.read_parquet(
        fact_path,
        columns=[
            "date",
            "vegetable_id",
            "vegetable_code",
            "vegetable_name_zh",
            "city_id",
            "market_city",
            "analysis_price",
            "data_quality_flag",
        ],
        filters=[("vegetable_id", "in", product_ids)],
    )
    facts["date"] = pd.to_datetime(facts["date"])
    tiers = pd.read_parquet(
        tier_path,
        columns=["vegetable_id", "city_id", "coverage_tier"],
        filters=[("vegetable_id", "in", product_ids)],
    )
    official = tiers[tiers["coverage_tier"].isin(config["official_tiers"])][
        ["vegetable_id", "city_id"]
    ].drop_duplicates()
    facts = facts.merge(official, on=["vegetable_id", "city_id"], how="inner")

    split_origins = {
        name: weekly_origins(
            str(config[f"{name}_origin_start"]),
            str(config[f"{name}_origin_end"]),
            str(config["origin_frequency"]),
        )
        for name in ["train", "validation", "final_test"]
    }
    rows: list[dict[str, Any]] = []
    group_columns = ["vegetable_id", "vegetable_code", "vegetable_name_zh", "city_id", "market_city"]
    for keys, group in facts.groupby(group_columns, observed=True, sort=True):
        identity = dict(zip(group_columns, keys))
        for split, origins in split_origins.items():
            for result in _series_audit(group, origins, config):
                rows.append({**identity, "split": split, **result})
    samples = pd.DataFrame(rows)
    if samples.empty:
        raise ValueError("P3 feasibility audit produced no eligible weekly samples")

    product_results: list[dict[str, Any]] = []
    thresholds = [float(value) for value in config["sensitivity_absolute_thresholds"]]
    minimum_rows = int(config["minimum_eligible_rows_per_product_split"])
    minimum_spikes = int(config["minimum_raw_spikes_for_diagnostic"])
    failed_eligibility = 0
    raw_spike_warnings = 0
    for product in products:
        item: dict[str, Any] = {
            **product,
            "official_series_count": int(
                official[official["vegetable_id"] == product["vegetable_id"]]["city_id"].nunique()
            ),
            "splits": {},
        }
        product_rows = samples[samples["vegetable_id"] == product["vegetable_id"]]
        for split in ["train", "validation", "final_test"]:
            subset = product_rows[product_rows["split"] == split]
            spike_counts = {
                f"raw_spike_{int(round(threshold * 100))}_count": int(
                    subset[f"raw_spike_{int(round(threshold * 100))}"].sum()
                )
                for threshold in thresholds
            }
            eligibility_pass = len(subset) >= minimum_rows
            spike_warning = spike_counts["raw_spike_20_count"] < minimum_spikes
            if split in {"validation", "final_test"} and not eligibility_pass:
                failed_eligibility += 1
            if split in {"validation", "final_test"} and spike_warning:
                raw_spike_warnings += 1
            item["splits"][split] = {
                "scheduled_origins": len(split_origins[split]),
                "eligible_rows": int(len(subset)),
                "eligible_series": int(subset["city_id"].nunique()),
                "eligible_origins": int(subset["origin_date"].nunique()),
                "origin_fill_share": round(float(subset["origin_lag_days"].gt(0).mean()), 6) if len(subset) else None,
                "mean_future_observations": round(float(subset["future_observations"].mean()), 3) if len(subset) else None,
                "median_peak_return": round(float(subset["future_peak_return_14d"].median()), 6) if len(subset) else None,
                **spike_counts,
                **{
                    f"raw_spike_{int(round(threshold * 100))}_rate": round(
                        float(subset[f"raw_spike_{int(round(threshold * 100))}"].mean()), 6
                    ) if len(subset) else None
                    for threshold in thresholds
                },
                "passes_minimum_eligible_rows": eligibility_pass,
                "raw_spike_20_diagnostic_warning": spike_warning,
            }
        product_results.append(item)

    totals: dict[str, Any] = {}
    for split in ["train", "validation", "final_test"]:
        subset = samples[samples["split"] == split]
        totals[split] = {
            "scheduled_origins": len(split_origins[split]),
            "eligible_rows": int(len(subset)),
            "eligible_series": int(subset[["vegetable_id", "city_id"]].drop_duplicates().shape[0]),
            "eligible_origins": int(subset["origin_date"].nunique()),
            **{
                f"raw_spike_{int(round(threshold * 100))}_count": int(
                    subset[f"raw_spike_{int(round(threshold * 100))}"].sum()
                )
                for threshold in thresholds
            },
            **{
                f"raw_spike_{int(round(threshold * 100))}_rate": round(
                    float(subset[f"raw_spike_{int(round(threshold * 100))}"].mean()), 6
                )
                for threshold in thresholds
            },
        }

    return {
        "experiment_version": config["experiment_version"],
        "status": "pass" if failed_eligibility == 0 else "fail",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_files": {
            str(config["city_fact_path"]): sha256(fact_path),
            str(config["coverage_tier_path"]): sha256(tier_path),
            str(config["scope_config_path"]): sha256(root / config["scope_config_path"]),
        },
        "contract": {
            "official_tiers": config["official_tiers"],
            "origin_frequency": config["origin_frequency"],
            "target_horizon_days": config["target_horizon_days"],
            "minimum_future_observations": config["minimum_future_observations"],
            "minimum_history_observations": config["minimum_history_observations"],
            "absolute_spike_threshold": config["absolute_spike_threshold"],
            "seasonal_quantile": config["seasonal_quantile"],
            "event_deduplication_days": config["event_deduplication_days"],
            "fixed_false_positive_rate": config["fixed_false_positive_rate"],
        },
        "totals": totals,
        "products": product_results,
        "gate_summary": {
            "official_product_split_checks": 20,
            "failed_eligibility_checks": failed_eligibility,
            "raw_spike_diagnostic_warnings": raw_spike_warnings,
        },
        "notes": [
            "Raw spike rates only apply the absolute 15/20/25 percent rules.",
            "Historical seasonal thresholds and 21-day event deduplication are intentionally deferred to P3-T1.",
            "Final-test counts establish feasibility only and were not used to choose a model or threshold.",
        ],
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# P3 价格风险预警可行性审计",
        "",
        f"> 实验版本：`{audit['experiment_version']}`  ",
        f"> 审计状态：**{audit['status']}**  ",
        "> 本报告只验证周度样本与原始涨价率，不是正式事件标签或模型成绩。",
        "",
        "## 总体样本",
        "",
        "| 切分 | 周度起点 | 合格行 | 合格序列 | 15%原始涨价 | 20%原始涨价 | 25%原始涨价 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for split in ["train", "validation", "final_test"]:
        item = audit["totals"][split]
        lines.append(
            f"| {split} | {item['scheduled_origins']} | {item['eligible_rows']:,} | "
            f"{item['eligible_series']} | {item['raw_spike_15_count']:,} "
            f"({item['raw_spike_15_rate']:.1%}) | {item['raw_spike_20_count']:,} "
            f"({item['raw_spike_20_rate']:.1%}) | {item['raw_spike_25_count']:,} "
            f"({item['raw_spike_25_rate']:.1%}) |"
        )
    lines.extend([
        "",
        "## 产品级 validation / final-test 检查",
        "",
        "| 产品 | Tier A序列 | validation合格行 | validation 20% | final-test合格行 | final-test 20% | 资格门槛 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ])
    for product in audit["products"]:
        validation = product["splits"]["validation"]
        final_test = product["splits"]["final_test"]
        passes = validation["passes_minimum_eligible_rows"] and final_test["passes_minimum_eligible_rows"]
        lines.append(
            f"| {product['vegetable_name_zh']} | {product['official_series_count']} | "
            f"{validation['eligible_rows']:,} | {validation['raw_spike_20_count']:,} | "
            f"{final_test['eligible_rows']:,} | {final_test['raw_spike_20_count']:,} | "
            f"{'通过' if passes else '未通过'} |"
        )
    summary = audit["gate_summary"]
    lines.extend([
        "",
        "## 结论与边界",
        "",
        f"- 正式产品×评估切分资格检查 {summary['official_product_split_checks']} 项，失败 {summary['failed_eligibility_checks']} 项。",
        f"- 20% 原始涨价个数低于诊断下限的产品×切分共 {summary['raw_spike_diagnostic_warnings']} 项；这只是稀有度预警，不修改事件口径。",
        "- 原始涨价率尚未叠加历史季节 90 分位门槛，也未做 21 天事件去重，因此不能作为模型 prevalence 或成功声明。",
        "- 最终测试只读取了资格与原始事件数量来确认可行性；模型、超参数和行动阈值仍必须只由 train / validation 冻结。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p3_alert_experiment.yaml")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / args.config)
    audit = run_audit(root, config)
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "p3_feasibility_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (docs / "p3_feasibility_audit.md").write_text(render_markdown(audit), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "totals": audit["totals"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
