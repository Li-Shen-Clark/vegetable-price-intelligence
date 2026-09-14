#!/usr/bin/env python3
"""Audit whether the frozen P2 forecast experiment is feasible on P0 Gold data."""

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
    "excluded_tiers",
    "train_start",
    "train_end",
    "validation_start",
    "validation_end",
    "validation_origin_start",
    "validation_origin_end",
    "final_test_start",
    "final_test_end",
    "final_test_origin_start",
    "final_test_origin_end",
    "origin_frequency",
    "horizons_days",
    "origin_max_forward_fill_days",
    "target_requires_exact_observation",
    "minimum_history_observations",
    "excluded_quality_flags",
    "minimum_product_origin_series_count",
    "minimum_product_origin_series_share",
    "minimum_usable_origins_per_split",
    "baselines",
    "primary_point_metric",
    "probability_quantiles",
}


def parse_scalar(raw: str) -> Any:
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
        result[key.strip()] = parse_scalar(value)
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
        raise ValueError("P2 scope must contain 10 complete product definitions")
    if len({item["vegetable_id"] for item in products}) != 10:
        raise ValueError("P2 product ids must be unique")
    return products


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def monthly_origins(start: str, end: str, frequency: str) -> list[pd.Timestamp]:
    return list(pd.date_range(start, end, freq=frequency))


def validate_config(config: dict[str, Any]) -> None:
    missing = REQUIRED_CONFIG_KEYS.difference(config)
    if missing:
        raise ValueError(f"P2 experiment config misses keys: {sorted(missing)}")
    dates = {
        key: pd.Timestamp(config[key])
        for key in [
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "validation_origin_start",
            "validation_origin_end",
            "final_test_start",
            "final_test_end",
            "final_test_origin_start",
            "final_test_origin_end",
        ]
    }
    if not (
        dates["train_start"] <= dates["train_end"]
        < dates["validation_start"] <= dates["validation_end"]
        < dates["final_test_start"] <= dates["final_test_end"]
    ):
        raise ValueError("train, validation and final-test periods must be ordered and disjoint")
    if config["official_tiers"] != ["A"] or config["shadow_tiers"] != ["B"]:
        raise ValueError("P2 v0.1 official pool must be Tier A and shadow pool Tier B")
    if config["horizons_days"] != [7, 14, 28]:
        raise ValueError("P2 v0.1 horizons must be 7, 14 and 28 days")
    if config["origin_frequency"] != "MS":
        raise ValueError("P2 v0.1 audit supports month-start origins only")
    if config["target_requires_exact_observation"] is not True:
        raise ValueError("forecast targets may not be filled")
    if int(config["origin_max_forward_fill_days"]) not in {0, 1}:
        raise ValueError("origin fill may be at most one day")
    if int(config["minimum_usable_origins_per_split"]) < 12:
        raise ValueError("each split must require at least 12 usable origins")
    final_origin = dates["final_test_origin_end"]
    if final_origin + pd.Timedelta(days=max(config["horizons_days"])) > dates["final_test_end"]:
        raise ValueError("last final-test origin does not leave room for the longest horizon")


def split_definitions(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "train": {
            "start": str(config["train_start"]),
            "end": str(config["train_end"]),
            "origins": [],
        },
        "validation": {
            "start": str(config["validation_start"]),
            "end": str(config["validation_end"]),
            "origins": monthly_origins(
                str(config["validation_origin_start"]),
                str(config["validation_origin_end"]),
                str(config["origin_frequency"]),
            ),
        },
        "final_test": {
            "start": str(config["final_test_start"]),
            "end": str(config["final_test_end"]),
            "origins": monthly_origins(
                str(config["final_test_origin_start"]),
                str(config["final_test_origin_end"]),
                str(config["origin_frequency"]),
            ),
        },
    }


def period_counts(frame: pd.DataFrame, start: str, end: str) -> dict[str, Any]:
    period = frame[frame["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    quality = period["data_quality_flag"].value_counts().to_dict()
    return {
        "observed_rows": int(len(period)),
        "quality_counts": {str(key): int(value) for key, value in sorted(quality.items())},
        "positive_price_rows": int(period["analysis_price"].gt(0).sum()),
    }


def transition_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    ordered = frame.sort_values(["city_id", "date"]).copy()
    grouped = ordered.groupby("city_id", sort=False, observed=True)
    previous_date = grouped["date"].shift()
    previous_price = grouped["analysis_price"].shift()
    consecutive = ordered["date"].sub(previous_date).dt.days.eq(1) & previous_price.notna()
    transitions = ordered.loc[consecutive, "analysis_price"]
    lagged = previous_price.loc[consecutive]
    if transitions.empty:
        return {
            "consecutive_calendar_transitions": 0,
            "unchanged_transition_share": None,
            "median_absolute_log_return": None,
        }
    unchanged = np.isclose(transitions.to_numpy(), lagged.to_numpy(), rtol=0.0, atol=1e-12)
    absolute_log_return = np.abs(np.log(transitions.to_numpy() / lagged.to_numpy()))
    return {
        "consecutive_calendar_transitions": int(len(transitions)),
        "unchanged_transition_share": round(float(unchanged.mean()), 6),
        "median_absolute_log_return": round(float(np.median(absolute_log_return)), 6),
    }


def evaluate_product_origins(
    frame: pd.DataFrame,
    cities: list[str],
    origins: list[pd.Timestamp],
    horizon: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    valid = frame[
        frame["analysis_price"].gt(0)
        & ~frame["data_quality_flag"].isin(config["excluded_quality_flags"])
    ].copy()
    key_set = set(zip(valid["city_id"].astype(str), valid["date"]))
    dates_by_city = {
        str(city): np.sort(group["date"].to_numpy(dtype="datetime64[ns]"))
        for city, group in valid.groupby("city_id", sort=False, observed=True)
    }
    minimum_history = int(config["minimum_history_observations"])
    max_origin_lag = int(config["origin_max_forward_fill_days"])
    min_series = int(config["minimum_product_origin_series_count"])
    min_share = float(config["minimum_product_origin_series_share"])
    counts: list[int] = []
    exact_origin_pairs = 0
    lagged_origin_pairs = 0

    for origin in origins:
        target_date = origin + pd.Timedelta(days=horizon)
        eligible = 0
        for city in cities:
            history_dates = dates_by_city.get(city)
            if history_dates is None:
                continue
            history_count = int(
                np.searchsorted(history_dates, origin.to_datetime64(), side="left")
            )
            if history_count < minimum_history or (city, target_date) not in key_set:
                continue
            origin_lag = next(
                (
                    lag
                    for lag in range(max_origin_lag + 1)
                    if (city, origin - pd.Timedelta(days=lag)) in key_set
                ),
                None,
            )
            if origin_lag is None:
                continue
            eligible += 1
            if origin_lag == 0:
                exact_origin_pairs += 1
            else:
                lagged_origin_pairs += 1
        counts.append(eligible)

    official_series_count = len(cities)
    usable_flags = [
        count >= min_series and count / official_series_count >= min_share
        for count in counts
    ]
    return {
        "horizon_days": int(horizon),
        "origin_count": int(len(origins)),
        "usable_origin_count": int(sum(usable_flags)),
        "eligible_pair_count": int(sum(counts)),
        "eligible_series_min": int(min(counts)) if counts else 0,
        "eligible_series_median": round(float(np.median(counts)), 1) if counts else 0.0,
        "eligible_series_max": int(max(counts)) if counts else 0,
        "eligible_series_share_min": (
            round(float(min(counts) / official_series_count), 4)
            if counts and official_series_count
            else 0.0
        ),
        "exact_origin_pair_count": int(exact_origin_pairs),
        "one_day_filled_origin_pair_count": int(lagged_origin_pairs),
        "passes_minimum_origins": bool(
            sum(usable_flags) >= int(config["minimum_usable_origins_per_split"])
        ),
    }


def build_audit(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    scope_path = root / str(config["scope_config_path"])
    city_fact_path = root / str(config["city_fact_path"])
    tiers_path = root / str(config["coverage_tier_path"])
    products = load_scope_products(scope_path)
    product_ids = [item["vegetable_id"] for item in products]
    product_lookup = {item["vegetable_id"]: item for item in products}

    tiers = pd.read_parquet(
        tiers_path,
        columns=["vegetable_id", "city_id", "coverage_tier", "forecast_eligible_flag"],
        filters=[("vegetable_id", "in", product_ids)],
    )
    facts = pd.read_parquet(
        city_fact_path,
        columns=[
            "date",
            "vegetable_id",
            "vegetable_code",
            "vegetable_name_zh",
            "city_id",
            "analysis_price",
            "data_quality_flag",
        ],
        filters=[("vegetable_id", "in", product_ids)],
    )
    facts["date"] = pd.to_datetime(facts["date"])
    if facts.duplicated(["date", "vegetable_id", "city_id"]).any():
        raise ValueError("Gold city fact primary key is not unique")
    official_keys = tiers[tiers["coverage_tier"].isin(config["official_tiers"])][
        ["vegetable_id", "city_id"]
    ]
    official_facts = facts.merge(official_keys, on=["vegetable_id", "city_id"], how="inner")
    splits = split_definitions(config)
    product_results: list[dict[str, Any]] = []

    for vegetable_id in product_ids:
        definition = product_lookup[vegetable_id]
        product_tiers = tiers[tiers["vegetable_id"].eq(vegetable_id)]
        tier_counts = (
            product_tiers["coverage_tier"].value_counts().reindex(["A", "B", "C"], fill_value=0)
        )
        cities = sorted(
            product_tiers.loc[
                product_tiers["coverage_tier"].isin(config["official_tiers"]), "city_id"
            ].astype(str)
        )
        product_facts = official_facts[official_facts["vegetable_id"].eq(vegetable_id)].copy()
        split_counts = {
            name: period_counts(product_facts, split["start"], split["end"])
            for name, split in splits.items()
        }
        valid_product_facts = product_facts[
            product_facts["analysis_price"].gt(0)
            & ~product_facts["data_quality_flag"].isin(config["excluded_quality_flags"])
        ]
        evaluation: dict[str, list[dict[str, Any]]] = {}
        for split_name in ["validation", "final_test"]:
            origins = splits[split_name]["origins"]
            evaluation[split_name] = [
                evaluate_product_origins(
                    product_facts,
                    cities,
                    origins,
                    int(horizon),
                    config,
                )
                for horizon in config["horizons_days"]
            ]
        product_results.append(
            {
                **definition,
                "tier_counts": {tier: int(tier_counts[tier]) for tier in ["A", "B", "C"]},
                "official_series_count": int(len(cities)),
                "split_counts": split_counts,
                "transition_diagnostics": transition_diagnostics(valid_product_facts),
                "evaluation": evaluation,
            }
        )

    all_gates = [
        result["passes_minimum_origins"]
        for product in product_results
        for split in product["evaluation"].values()
        for result in split
    ]
    official_quality = {
        split_name: period_counts(official_facts, split["start"], split["end"])
        for split_name, split in splits.items()
    }
    return {
        "audit_version": "p2_feasibility_audit_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "experiment_version": config["experiment_version"],
        "status": "pass" if all(all_gates) else "fail",
        "decision": (
            "P2-T1 may proceed under the frozen Tier A monthly-origin protocol."
            if all(all_gates)
            else "Do not proceed to modeling until failed product/split gates are resolved."
        ),
        "inputs": {
            "scope": str(config["scope_config_path"]),
            "scope_sha256": sha256(scope_path),
            "city_fact": str(config["city_fact_path"]),
            "city_fact_sha256": sha256(city_fact_path),
            "coverage_tiers": str(config["coverage_tier_path"]),
            "coverage_tiers_sha256": sha256(tiers_path),
        },
        "contract": {
            "official_tiers": list(config["official_tiers"]),
            "shadow_tiers": list(config["shadow_tiers"]),
            "horizons_days": list(config["horizons_days"]),
            "origin_max_forward_fill_days": int(config["origin_max_forward_fill_days"]),
            "target_requires_exact_observation": bool(
                config["target_requires_exact_observation"]
            ),
            "minimum_history_observations": int(config["minimum_history_observations"]),
            "excluded_quality_flags": list(config["excluded_quality_flags"]),
            "minimum_usable_origins_per_split": int(
                config["minimum_usable_origins_per_split"]
            ),
            "validation_origins": [
                value.date().isoformat() for value in splits["validation"]["origins"]
            ],
            "final_test_origins": [
                value.date().isoformat() for value in splits["final_test"]["origins"]
            ],
        },
        "row_counts": {
            "p2_scope_city_fact_rows": int(len(facts)),
            "official_tier_city_fact_rows": int(len(official_facts)),
            "p2_scope_tier_rows": int(len(tiers)),
            "official_series_count": int(len(official_keys)),
        },
        "official_quality_by_split": official_quality,
        "products": product_results,
        "gate_summary": {
            "checks": int(len(all_gates)),
            "passed": int(sum(all_gates)),
            "failed": int(len(all_gates) - sum(all_gates)),
        },
    }


def format_integer(value: int) -> str:
    return f"{value:,}"


def render_markdown(audit: dict[str, Any]) -> str:
    status_zh = "通过" if audit["status"] == "pass" else "不通过"
    lines = [
        "# P2 预测可行性审计",
        "",
        f"> 实验版本：`{audit['experiment_version']}`  ",
        f"> 审计状态：**{status_zh}**  ",
        f"> 生成时间（UTC）：{audit['generated_at_utc']}",
        "",
        "## 1. 结论",
        "",
    ]
    if audit["status"] == "pass":
        lines.extend(
            [
                "10 种核心蔬菜在 Tier A 正式样本中均满足最低回测条件：2020 年有 12 个验证起点，2021-01 至 2022-05 有 17 个最终测试起点，7/14/28 日三个跨度均可评估。可以进入 P2-T1 建模数据集，但这不代表模型一定优于简单基线。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "至少一个产品、时间段或预测跨度未达到最低回测条件。在解决失败项前，不应进入模型训练。",
                "",
            ]
        )
    rows = audit["row_counts"]
    lines.extend(
        [
            "- P2 范围城市日记录：" + format_integer(rows["p2_scope_city_fact_rows"]),
            "- Tier A 正式城市日记录：" + format_integer(rows["official_tier_city_fact_rows"]),
            "- Tier A 正式产品—城市序列：" + format_integer(rows["official_series_count"]),
            f"- 可评估性检查：{audit['gate_summary']['passed']} / {audit['gate_summary']['checks']} 通过",
            "",
            "## 2. 产品与正式样本",
            "",
            "| 产品 | Tier A | Tier B | Tier C | 训练期记录 | 验证期记录 | 测试期记录 | 连续日同价占比 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for product in audit["products"]:
        tiers = product["tier_counts"]
        split = product["split_counts"]
        unchanged = product["transition_diagnostics"]["unchanged_transition_share"]
        unchanged_text = "—" if unchanged is None else f"{unchanged:.1%}"
        lines.append(
            f"| {product['vegetable_name_zh']} | {tiers['A']} | {tiers['B']} | {tiers['C']} | "
            f"{format_integer(split['train']['observed_rows'])} | "
            f"{format_integer(split['validation']['observed_rows'])} | "
            f"{format_integer(split['final_test']['observed_rows'])} | {unchanged_text} |"
        )
    lines.extend(
        [
            "",
            "连续日同价占比只在相邻自然日均有合格观测时计算。较高占比说明价格变化具有稀疏性，支持在 P2-T3 验证 hurdle/两阶段模型，但不能据此预先选定模型。",
            "",
            "## 3. 回测起点可评估性",
            "",
            "“最少合格城市”是某产品在所有月初起点中的最低值；起点只有在至少 5 个且至少 50% 的 Tier A 城市可评分时才算可用。",
            "",
            "| 产品 | 数据段 | 跨度 | 可用起点 | 合格配对 | 最少合格城市 | 中位合格城市 | 最低覆盖率 | 结果 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for product in audit["products"]:
        for split_name, split_label in [("validation", "验证"), ("final_test", "最终测试")]:
            for result in product["evaluation"][split_name]:
                result_text = "通过" if result["passes_minimum_origins"] else "失败"
                lines.append(
                    f"| {product['vegetable_name_zh']} | {split_label} | {result['horizon_days']}日 | "
                    f"{result['usable_origin_count']}/{result['origin_count']} | "
                    f"{format_integer(result['eligible_pair_count'])} | "
                    f"{result['eligible_series_min']} | {result['eligible_series_median']:.1f} | "
                    f"{result['eligible_series_share_min']:.1%} | {result_text} |"
                )
    lines.extend(
        [
            "",
            "## 4. 已冻结的实验边界",
            "",
            "- 正式样本只使用 Tier A；Tier B 只做影子评估，Tier C 排除。",
            "- 训练期截至 2019-12-31；2020 年用于验证；2021-01-01 至 2022-06-22 是冻结的最终测试期。",
            "- 验证起点为 2020 年每个月月初，共 12 个；最终测试起点为 2021-01 至 2022-05 每个月月初，共 17 个。",
            "- 预测跨度固定为 7、14、28 个自然日。目标日必须有真实、非 poor、正价格观测，绝不填充目标。",
            "- 预测起点允许使用当日或最多前 1 日的合格价格；每个序列在起点前至少要有 365 个合格历史观测。",
            "- 候选模型必须在同一评分行上与最近价格、7 日周期价格、历史季节中位数中的最佳者比较。",
            "",
            "## 5. 泄漏防护",
            "",
            "1. 预测起点之后的数据不得参与特征、缺失处理、归一化、类别编码、季节统计或校准。",
            "2. 目标日不做插值、前向填充或邻日替代。",
            "3. 2021–2022 最终测试目标不得用于算法、特征、阈值或超参数选择。",
            "4. 所有模型与基线按 paired rows 评分；缺失预测不能通过缩小评分样本获得优势。",
            "5. 外部变量只有在能证明其发布时间早于预测起点时才可进入后续版本；P2 MVP 暂不引入外部数据。",
            "",
            "## 6. 风险与下一步",
            "",
            "- 可行性通过只证明样本足够，不证明可预测性或商业收益；P2-T2 的正式简单基线仍是第一道性能门槛。",
            "- 数据截至 2022-06-22，因此该项目展示的是历史回测能力，不是当前市场报价服务。",
            "- 旧版 `baselines/v0_diagnostic.json` 使用全历史与旧映射，只保留为方向性参考，不进入正式记分牌。",
            "- 下一步 P2-T1 应建立一行一个“产品—城市—预测起点—跨度”的防泄漏 mart，并让其样本计数与本审计对齐。",
            "",
            "## 7. 可追溯输入",
            "",
            f"- `{audit['inputs']['scope']}`：`{audit['inputs']['scope_sha256']}`",
            f"- `{audit['inputs']['city_fact']}`：`{audit['inputs']['city_fact_sha256']}`",
            f"- `{audit['inputs']['coverage_tiers']}`：`{audit['inputs']['coverage_tiers_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", default="config/p2_experiment.yaml")
    parser.add_argument("--json-output", default="docs/p2_feasibility_audit.json")
    parser.add_argument("--markdown-output", default="docs/p2_feasibility_audit.md")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / args.config)
    audit = build_audit(root, config)
    write_json(root / args.json_output, audit)
    (root / args.markdown_output).write_text(render_markdown(audit), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": audit["status"],
                "products": len(audit["products"]),
                "official_series": audit["row_counts"]["official_series_count"],
                "gate_summary": audit["gate_summary"],
                "json_output": args.json_output,
                "markdown_output": args.markdown_output,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

