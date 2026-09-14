#!/usr/bin/env python3
"""Build product-by-city coverage metrics and deterministic A/B/C tiers."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


TIER_SCHEMA = pa.schema(
    [
        pa.field("vegetable_id", pa.int32(), nullable=False),
        pa.field("vegetable_code", pa.string(), nullable=False),
        pa.field("vegetable_name_zh", pa.string(), nullable=False),
        pa.field("city_id", pa.string(), nullable=False),
        pa.field("city_name_zh", pa.string(), nullable=False),
        pa.field("province_name_zh", pa.string(), nullable=False),
        pa.field("calendar_start_date", pa.date32(), nullable=False),
        pa.field("calendar_end_date", pa.date32(), nullable=False),
        pa.field("calendar_day_count", pa.int32(), nullable=False),
        pa.field("first_valid_date", pa.date32(), nullable=True),
        pa.field("last_valid_date", pa.date32(), nullable=True),
        pa.field("valid_day_count", pa.int32(), nullable=False),
        pa.field("coverage_rate", pa.float64(), nullable=False),
        pa.field("active_span_day_count", pa.int32(), nullable=False),
        pa.field("active_span_coverage_rate", pa.float64(), nullable=False),
        pa.field("leading_gap_days", pa.int32(), nullable=False),
        pa.field("trailing_gap_days", pa.int32(), nullable=False),
        pa.field("longest_internal_gap_days", pa.int32(), nullable=False),
        pa.field("longest_overall_gap_days", pa.int32(), nullable=False),
        pa.field("mean_reporting_markets", pa.float64(), nullable=True),
        pa.field("max_reporting_markets", pa.int32(), nullable=False),
        pa.field("single_market_day_share", pa.float64(), nullable=True),
        pa.field("mean_stale_quote_share", pa.float64(), nullable=True),
        pa.field("mean_outlier_share", pa.float64(), nullable=True),
        pa.field("mean_duplicate_market_share", pa.float64(), nullable=True),
        pa.field("mean_source_reliability_score", pa.float64(), nullable=True),
        pa.field("good_day_share", pa.float64(), nullable=True),
        pa.field("caution_day_share", pa.float64(), nullable=True),
        pa.field("poor_day_share", pa.float64(), nullable=True),
        pa.field("coverage_score", pa.float64(), nullable=False),
        pa.field("coverage_tier", pa.string(), nullable=False),
        pa.field("forecast_eligible_flag", pa.bool_(), nullable=False),
        pa.field("monitor_eligible_flag", pa.bool_(), nullable=False),
        pa.field("tier_reason", pa.string(), nullable=False),
        pa.field("tier_rule_version", pa.string(), nullable=False),
    ]
)


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return {}
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def load_flat_yaml(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(" ") or ":" not in raw_line:
            raise ValueError(f"Unsupported flat YAML line {line_number}: {raw_line}")
        key, value = raw_line.split(":", 1)
        result[key.strip()] = parse_scalar(value)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_dimensions(
    dim_vegetable_path: Path,
    dim_city_path: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    vegetables_raw = read_csv(dim_vegetable_path)
    cities = read_csv(dim_city_path)
    vegetables = [
        {
            "vegetable_id": int(row["vegetable_id"]),
            "vegetable_code": row["vegetable_code"],
            "vegetable_name_zh": row["vegetable_name_zh"],
        }
        for row in vegetables_raw
    ]
    if len(vegetables) != 30 or len({row["vegetable_id"] for row in vegetables}) != 30:
        raise ValueError("dim_vegetable must contain 30 unique vegetables")
    if len(cities) != 117 or len({row["city_id"] for row in cities}) != 117:
        raise ValueError("dim_city must contain 117 unique cities")
    if len({row["city_name_zh"] for row in cities}) != 117:
        raise ValueError("dim_city city names must be unique")
    return vegetables, cities


def validate_config(config: Dict[str, Any]) -> Tuple[date, date, int]:
    start = date.fromisoformat(str(config["coverage_calendar_start"]))
    end = date.fromisoformat(str(config["coverage_calendar_end"]))
    day_count = (end - start).days + 1
    if day_count != int(config["coverage_calendar_expected_days"]):
        raise ValueError(f"calendar has {day_count} days, expected contract differs")
    weight_keys = [
        "coverage_score_weight_global_coverage",
        "coverage_score_weight_active_span_coverage",
        "coverage_score_weight_recency",
        "coverage_score_weight_freshness",
        "coverage_score_weight_non_outlier",
        "coverage_score_weight_non_poor",
    ]
    weights = [float(config[key]) for key in weight_keys]
    if any(weight < 0 for weight in weights) or not np.isclose(sum(weights), 1.0):
        raise ValueError(f"coverage score weights must sum to 1, found {weights}")
    if int(config["tier_b_min_valid_days"]) > int(config["tier_a_min_valid_days"]):
        raise ValueError("Tier B minimum valid days cannot exceed Tier A")
    return start, end, day_count


def failed_a_gates(metrics: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    checks = [
        (metrics["valid_day_count"] >= int(config["tier_a_min_valid_days"]), "valid_days"),
        (
            metrics["active_span_coverage_rate"]
            >= float(config["tier_a_min_active_span_coverage"]),
            "active_span_coverage",
        ),
        (
            metrics["longest_internal_gap_days"]
            <= int(config["tier_a_max_internal_gap_days"]),
            "internal_gap",
        ),
        (
            metrics["trailing_gap_days"] <= int(config["tier_a_max_trailing_gap_days"]),
            "trailing_gap",
        ),
        (
            metrics["mean_stale_quote_share"] is not None
            and metrics["mean_stale_quote_share"]
            <= float(config["tier_a_max_mean_stale_share"]),
            "stale_share",
        ),
        (
            metrics["mean_outlier_share"] is not None
            and metrics["mean_outlier_share"]
            <= float(config["tier_a_max_mean_outlier_share"]),
            "outlier_share",
        ),
        (
            metrics["poor_day_share"] is not None
            and metrics["poor_day_share"] <= float(config["tier_a_max_poor_day_share"]),
            "poor_day_share",
        ),
    ]
    return [name for passed, name in checks if not passed]


def failed_b_gates(metrics: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    checks = [
        (metrics["valid_day_count"] >= int(config["tier_b_min_valid_days"]), "valid_days"),
        (
            metrics["active_span_coverage_rate"]
            >= float(config["tier_b_min_active_span_coverage"]),
            "active_span_coverage",
        ),
        (
            metrics["longest_internal_gap_days"]
            <= int(config["tier_b_max_internal_gap_days"]),
            "internal_gap",
        ),
        (
            metrics["trailing_gap_days"] <= int(config["tier_b_max_trailing_gap_days"]),
            "trailing_gap",
        ),
        (
            metrics["poor_day_share"] is not None
            and metrics["poor_day_share"] <= float(config["tier_b_max_poor_day_share"]),
            "poor_day_share",
        ),
    ]
    return [name for passed, name in checks if not passed]


def calculate_metrics(
    city_rows: pd.DataFrame,
    start: date,
    end: date,
    calendar_days: int,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    valid_days = len(city_rows)
    if valid_days == 0:
        return {
            "first_valid_date": None,
            "last_valid_date": None,
            "valid_day_count": 0,
            "coverage_rate": 0.0,
            "active_span_day_count": 0,
            "active_span_coverage_rate": 0.0,
            "leading_gap_days": calendar_days,
            "trailing_gap_days": calendar_days,
            "longest_internal_gap_days": 0,
            "longest_overall_gap_days": calendar_days,
            "mean_reporting_markets": None,
            "max_reporting_markets": 0,
            "single_market_day_share": None,
            "mean_stale_quote_share": None,
            "mean_outlier_share": None,
            "mean_duplicate_market_share": None,
            "mean_source_reliability_score": None,
            "good_day_share": None,
            "caution_day_share": None,
            "poor_day_share": None,
            "coverage_score": 0.0,
        }

    city_rows = city_rows.sort_values("date", kind="mergesort")
    dates = pd.to_datetime(city_rows["date"])
    if dates.duplicated().any():
        raise ValueError("city/product input contains duplicate dates")
    first_valid = dates.iloc[0].date()
    last_valid = dates.iloc[-1].date()
    if first_valid < start or last_valid > end:
        raise ValueError("city fact date falls outside configured calendar")
    active_span_days = (last_valid - first_valid).days + 1
    date_ordinals = dates.to_numpy(dtype="datetime64[D]").astype(np.int64)
    internal_gaps = np.diff(date_ordinals) - 1
    longest_internal = int(internal_gaps.max()) if len(internal_gaps) else 0
    leading_gap = (first_valid - start).days
    trailing_gap = (end - last_valid).days
    quality_counts = city_rows["data_quality_flag"].value_counts()
    poor_share = float(quality_counts.get("poor", 0) / valid_days)
    stale_share = float(city_rows["stale_quote_share"].mean())
    outlier_share = float(city_rows["outlier_share"].mean())
    global_coverage = valid_days / calendar_days
    active_coverage = valid_days / active_span_days
    recency_score = max(
        0.0,
        1.0 - trailing_gap / int(config["coverage_recency_scale_days"]),
    )
    score = (
        float(config["coverage_score_weight_global_coverage"]) * global_coverage
        + float(config["coverage_score_weight_active_span_coverage"]) * active_coverage
        + float(config["coverage_score_weight_recency"]) * recency_score
        + float(config["coverage_score_weight_freshness"]) * (1.0 - stale_share)
        + float(config["coverage_score_weight_non_outlier"]) * (1.0 - outlier_share)
        + float(config["coverage_score_weight_non_poor"]) * (1.0 - poor_share)
    )
    return {
        "first_valid_date": first_valid,
        "last_valid_date": last_valid,
        "valid_day_count": valid_days,
        "coverage_rate": float(global_coverage),
        "active_span_day_count": active_span_days,
        "active_span_coverage_rate": float(active_coverage),
        "leading_gap_days": leading_gap,
        "trailing_gap_days": trailing_gap,
        "longest_internal_gap_days": longest_internal,
        "longest_overall_gap_days": max(leading_gap, trailing_gap, longest_internal),
        "mean_reporting_markets": float(city_rows["number_of_reporting_markets"].mean()),
        "max_reporting_markets": int(city_rows["number_of_reporting_markets"].max()),
        "single_market_day_share": float(
            city_rows["number_of_reporting_markets"].eq(1).mean()
        ),
        "mean_stale_quote_share": stale_share,
        "mean_outlier_share": outlier_share,
        "mean_duplicate_market_share": float(city_rows["duplicate_market_share"].mean()),
        "mean_source_reliability_score": float(
            city_rows["source_reliability_score"].mean()
        ),
        "good_day_share": float(quality_counts.get("good", 0) / valid_days),
        "caution_day_share": float(quality_counts.get("caution", 0) / valid_days),
        "poor_day_share": poor_share,
        "coverage_score": float(np.clip(score, 0.0, 1.0)),
    }


def assign_tier(metrics: Dict[str, Any], config: Dict[str, Any]) -> Tuple[str, str]:
    failed_a = failed_a_gates(metrics, config)
    if not failed_a:
        return "A", "meets_all_tier_a_gates"
    failed_b = failed_b_gates(metrics, config)
    if not failed_b:
        return "B", f"tier_a_failed:{','.join(failed_a)};meets_all_tier_b_gates"
    return (
        "C",
        f"tier_a_failed:{','.join(failed_a)};tier_b_failed:{','.join(failed_b)}",
    )


def build_product_tiers(
    product: Dict[str, Any],
    cities: List[Dict[str, str]],
    city_fact: pd.DataFrame,
    start: date,
    end: date,
    calendar_days: int,
    config: Dict[str, Any],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    by_city = {
        str(city_id): rows.copy()
        for city_id, rows in city_fact.groupby("city_id", sort=False, observed=True)
    }
    output_rows: List[Dict[str, Any]] = []
    for city in cities:
        city_id = city["city_id"]
        metrics = calculate_metrics(
            by_city.get(city_id, city_fact.iloc[0:0]),
            start,
            end,
            calendar_days,
            config,
        )
        tier, reason = assign_tier(metrics, config)
        output_rows.append(
            {
                **product,
                "city_id": city_id,
                "city_name_zh": city["city_name_zh"],
                "province_name_zh": city["province_name_zh"],
                "calendar_start_date": start,
                "calendar_end_date": end,
                "calendar_day_count": calendar_days,
                **metrics,
                "coverage_tier": tier,
                "forecast_eligible_flag": tier == "A",
                "monitor_eligible_flag": tier in {"A", "B"},
                "tier_reason": reason,
                "tier_rule_version": str(config["tier_rule_version"]),
            }
        )
    output = pd.DataFrame(output_rows)[[field.name for field in TIER_SCHEMA]]
    if len(output) != 117 or output["city_id"].nunique() != 117:
        raise ValueError("product tier output must contain all 117 cities exactly once")
    if set(output["coverage_tier"]) - {"A", "B", "C"}:
        raise ValueError("invalid coverage tier")
    if not output["coverage_score"].between(0, 1).all():
        raise ValueError("coverage scores must be in [0, 1]")
    if not output["forecast_eligible_flag"].eq(output["coverage_tier"].eq("A")).all():
        raise ValueError("forecast eligibility conflicts with Tier")
    if not output["monitor_eligible_flag"].eq(output["coverage_tier"].isin(["A", "B"])).all():
        raise ValueError("monitor eligibility conflicts with Tier")
    no_data = output["valid_day_count"].eq(0)
    if not output.loc[no_data, "coverage_tier"].eq("C").all():
        raise ValueError("no-data combinations must be Tier C")
    tier_counts = {
        tier: int(output["coverage_tier"].eq(tier).sum()) for tier in ["A", "B", "C"]
    }
    stats = {
        **product,
        "tier_counts": tier_counts,
        "no_data_cities": int(no_data.sum()),
        "median_valid_days": float(output["valid_day_count"].median()),
        "median_coverage_rate": float(output["coverage_rate"].median()),
        "max_valid_days": int(output["valid_day_count"].max()),
    }
    return output, stats


def build_summary(
    products: List[Dict[str, Any]],
    total_counts: Dict[str, int],
    start: date,
    end: date,
    calendar_days: int,
    config: Dict[str, Any],
) -> str:
    lines = [
        "# 覆盖率与 Tier 分层摘要",
        "",
        f"规则版本：`{config['tier_rule_version']}`  ",
        f"统一日历：{start.isoformat()} 至 {end.isoformat()}（{calendar_days:,} 个自然日）  ",
        "粒度：每个蔬菜×城市一行；30×117 = 3,510 个组合。",
        "",
        "## 全局结果",
        "",
        f"- Tier A：{total_counts['A']:,}",
        f"- Tier B：{total_counts['B']:,}",
        f"- Tier C：{total_counts['C']:,}",
        "",
        "Tier A 表示适合本历史数据集内的正式预测回测，Tier B 表示只进入价格监控，Tier C 只保留质量可见性。这不是 2026 年实时可用性判定。",
        "",
        "## 分蔬菜计数",
        "",
        "| 蔬菜代码 | 中文名 | Tier A | Tier B | Tier C | 无数据城市 | 有效日期中位数 | 覆盖率中位数 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in products:
        counts = item["tier_counts"]
        if sum(counts.values()) != 117:
            raise ValueError("product Tier counts do not sum to 117")
        lines.append(
            "| {code} | {name} | {a} | {b} | {c} | {none} | {days:,.0f} | {rate:.1%} |".format(
                code=item["vegetable_code"],
                name=item["vegetable_name_zh"],
                a=counts["A"],
                b=counts["B"],
                c=counts["C"],
                none=item["no_data_cities"],
                days=item["median_valid_days"],
                rate=item["median_coverage_rate"],
            )
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 覆盖率以统一的 3,063 日历史窗口为分母，不把缺失日期填成价格。",
            "- 尾部缺口相对数据集截止日 2022-06-22 计算，不代表相对当前日期的新鲜度。",
            "- Tier 由预先固定的绝对门槛决定，没有为了获得某个 Tier A 数量进行分位数调参。",
            "- `coverage_score` 用于排序和诊断；Tier 标签由各项门槛共同决定，不能仅凭总分反推。",
            "",
        ]
    )
    return "\n".join(lines)


def build(paths_path: Path, tiering_path: Path) -> Dict[str, Any]:
    paths = load_flat_yaml(paths_path)
    config = load_flat_yaml(tiering_path)
    start, end, calendar_days = validate_config(config)
    project_root = paths_path.resolve().parent.parent
    city_fact_path = project_root / str(paths["gold_fact_city_price"])
    dim_vegetable_path = project_root / str(paths["dim_vegetable"])
    dim_city_path = project_root / str(paths["dim_city"])
    output_path = project_root / str(paths["gold_coverage_tiers"])
    manifest_path = project_root / str(paths["gold_coverage_manifest"])
    summary_path = project_root / str(paths["coverage_tier_summary"])
    vegetables, cities = read_dimensions(dim_vegetable_path, dim_city_path)

    city_file = pq.ParquetFile(city_fact_path)
    if city_file.metadata.num_rows <= 0:
        raise ValueError("city fact is empty")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_temp = output_path.with_suffix(output_path.suffix + ".tmp")
    manifest_temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    summary_temp = summary_path.with_suffix(summary_path.suffix + ".tmp")
    for temp in [output_temp, manifest_temp, summary_temp]:
        temp.unlink(missing_ok=True)

    columns = [
        "date",
        "vegetable_id",
        "vegetable_code",
        "vegetable_name_zh",
        "city_id",
        "market_city",
        "market_province",
        "number_of_reporting_markets",
        "stale_quote_share",
        "outlier_share",
        "duplicate_market_share",
        "source_reliability_score",
        "data_quality_flag",
    ]
    writer = None
    try:
        writer = pq.ParquetWriter(
            output_temp,
            TIER_SCHEMA,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        product_stats: List[Dict[str, Any]] = []
        total_counts: Counter[str] = Counter()
        observed_date_min: date | None = None
        observed_date_max: date | None = None
        for product in vegetables:
            city_fact = pq.read_table(
                city_fact_path,
                columns=columns,
                filters=[("vegetable_id", "=", product["vegetable_id"])],
            ).to_pandas()
            if city_fact.empty:
                raise ValueError(f"city fact has no rows for {product['vegetable_code']}")
            if set(city_fact["vegetable_code"].unique()) != {product["vegetable_code"]}:
                raise ValueError(f"vegetable dimension mismatch for {product['vegetable_code']}")
            local_min = pd.to_datetime(city_fact["date"]).min().date()
            local_max = pd.to_datetime(city_fact["date"]).max().date()
            observed_date_min = (
                local_min if observed_date_min is None or local_min < observed_date_min else observed_date_min
            )
            observed_date_max = (
                local_max if observed_date_max is None or local_max > observed_date_max else observed_date_max
            )
            tiers, stats = build_product_tiers(
                product,
                cities,
                city_fact,
                start,
                end,
                calendar_days,
                config,
            )
            writer.write_table(
                pa.Table.from_pandas(tiers, schema=TIER_SCHEMA, preserve_index=False, safe=True),
                row_group_size=len(tiers),
            )
            product_stats.append(stats)
            total_counts.update(stats["tier_counts"])
        writer.close()
        writer = None
        if observed_date_min != start or observed_date_max != end:
            raise ValueError(
                f"city fact global dates {observed_date_min}..{observed_date_max} differ from calendar"
            )

        output_file = pq.ParquetFile(output_temp)
        expected_rows = len(vegetables) * len(cities)
        if output_file.metadata.num_rows != expected_rows or output_file.schema_arrow != TIER_SCHEMA:
            raise ValueError("coverage tier Parquet contract mismatch")
        if output_file.metadata.num_row_groups != len(vegetables):
            raise ValueError("coverage output must have one row group per vegetable")
        if sum(total_counts.values()) != expected_rows:
            raise ValueError("global Tier counts do not sum to the output row count")

        summary = build_summary(
            product_stats,
            {tier: int(total_counts[tier]) for tier in ["A", "B", "C"]},
            start,
            end,
            calendar_days,
            config,
        )
        summary_temp.write_text(summary, encoding="utf-8")
        manifest: Dict[str, Any] = {
            "dataset": "coverage_tiers",
            "layer": "gold",
            "schema_version": "gold_coverage_v0.1",
            "tier_rule_version": str(config["tier_rule_version"]),
            "row_count": expected_rows,
            "column_count": len(TIER_SCHEMA),
            "product_count": len(vegetables),
            "city_count": len(cities),
            "calendar_start_date": start.isoformat(),
            "calendar_end_date": end.isoformat(),
            "calendar_day_count": calendar_days,
            "tier_counts": {tier: int(total_counts[tier]) for tier in ["A", "B", "C"]},
            "no_data_combinations": int(sum(item["no_data_cities"] for item in product_stats)),
            "parquet_row_group_count": output_file.metadata.num_row_groups,
            "parquet_compression": "zstd",
            "parquet_sha256": sha256(output_temp),
            "summary_sha256": sha256(summary_temp),
            "input_city_fact_sha256": sha256(city_fact_path),
            "dim_city_sha256": sha256(dim_city_path),
            "dim_vegetable_sha256": sha256(dim_vegetable_path),
            "tiering_config_sha256": sha256(tiering_path),
            "implementation_sha256": sha256(Path(__file__).resolve()),
            "products": product_stats,
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in TIER_SCHEMA
            ],
        }
        manifest_temp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output_temp.replace(output_path)
        manifest_temp.replace(manifest_path)
        summary_temp.replace(summary_path)
        return manifest
    except Exception:
        if writer is not None:
            writer.close()
        for temp in [output_temp, manifest_temp, summary_temp]:
            temp.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", default="config/paths.yaml")
    parser.add_argument("--tiering", default="config/tiering.yaml")
    args = parser.parse_args()
    manifest = build(Path(args.paths).resolve(), Path(args.tiering).resolve())
    print(
        json.dumps(
            {
                "dataset": manifest["dataset"],
                "rows": manifest["row_count"],
                "columns": manifest["column_count"],
                "tier_counts": manifest["tier_counts"],
                "no_data_combinations": manifest["no_data_combinations"],
                "sha256": manifest["parquet_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
