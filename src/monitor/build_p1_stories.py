#!/usr/bin/env python3
"""Build the reproducible P1 portfolio stories from the published Web mart."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


def product_payload(root: Path, vegetable_id: int) -> dict[str, Any]:
    return load_json(root / f"web/public/data/products/{vegetable_id}.json")


def city_name(metadata: dict[str, Any], city_id: str) -> str:
    row = next(city for city in metadata["cities"] if city["city_id"] == city_id)
    return str(row["city_name_zh"])


def find_record(payload: dict[str, Any], city_id: str, month: str) -> list[Any]:
    return next(
        record
        for record in payload["records"]
        if record[0] == city_id and record[1] == month
    )


def compute_stories(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    metadata = load_json(root / "web/public/data/metadata.json")

    season_product = product_payload(root, int(config["seasonality_vegetable_id"]))
    season_city_id = str(config["seasonality_city_id"])
    season_rows = [
        record
        for record in season_product["records"]
        if record[0] == season_city_id
        and record[1] <= metadata["data_period"]["last_complete_month"]
    ]
    calendar_months: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    for record in season_rows:
        calendar_months[int(record[1][5:7])].append(float(record[2]))
    season_medians = {
        month: quantile(values, 0.5)
        for month, values in calendar_months.items()
        if values
    }
    high_month = max(season_medians, key=season_medians.get)
    low_month = min(season_medians, key=season_medians.get)
    seasonality = {
        "vegetable_id": int(config["seasonality_vegetable_id"]),
        "vegetable_name": season_product["product"]["vegetable_name_zh"],
        "city_id": season_city_id,
        "city_name": city_name(metadata, season_city_id),
        "high_month": high_month,
        "high_price": round(season_medians[high_month], 3),
        "high_month_sample_years": len(calendar_months[high_month]),
        "low_month": low_month,
        "low_price": round(season_medians[low_month], 3),
        "low_month_sample_years": len(calendar_months[low_month]),
        "high_vs_low_pct": round(
            (season_medians[high_month] / season_medians[low_month] - 1) * 100, 1
        ),
    }

    spread_product = product_payload(root, int(config["spread_vegetable_id"]))
    spread_month = str(config["spread_month"])
    profiles = {row[0]: row for row in spread_product["city_profiles"]}
    ranking_policy = metadata["ranking_policy"]
    spread_rows = [
        record
        for record in spread_product["records"]
        if record[1] == spread_month
        and int(record[5]) >= int(ranking_policy["minimum_valid_days_in_month"])
        and profiles[record[0]][1] in ranking_policy["eligible_tiers"]
    ]
    spread_rows.sort(key=lambda row: float(row[2]), reverse=True)
    prices = [float(row[2]) for row in spread_rows]
    cross_city = {
        "vegetable_id": int(config["spread_vegetable_id"]),
        "vegetable_name": spread_product["product"]["vegetable_name_zh"],
        "month": spread_month,
        "comparable_city_count": len(spread_rows),
        "highest_city": city_name(metadata, str(spread_rows[0][0])),
        "highest_price": round(float(spread_rows[0][2]), 3),
        "lowest_city": city_name(metadata, str(spread_rows[-1][0])),
        "lowest_price": round(float(spread_rows[-1][2]), 3),
        "city_price_p25": round(quantile(prices, 0.25), 3),
        "city_price_median": round(quantile(prices, 0.5), 3),
        "city_price_p75": round(quantile(prices, 0.75), 3),
        "highest_vs_lowest_pct": round(
            (float(spread_rows[0][2]) / float(spread_rows[-1][2]) - 1) * 100, 1
        ),
    }

    quality_product = product_payload(root, int(config["quality_vegetable_id"]))
    quality_city_id = str(config["quality_city_id"])
    quality_month = str(config["quality_month"])
    quality_record = find_record(quality_product, quality_city_id, quality_month)
    quality_profile = next(
        profile for profile in quality_product["city_profiles"] if profile[0] == quality_city_id
    )
    quality_risk = {
        "vegetable_id": int(config["quality_vegetable_id"]),
        "vegetable_name": quality_product["product"]["vegetable_name_zh"],
        "city_id": quality_city_id,
        "city_name": city_name(metadata, quality_city_id),
        "month": quality_month,
        "tier": quality_profile[1],
        "valid_days": int(quality_record[5]),
        "reliability": round(float(quality_record[8]), 4),
        "good_days": int(quality_record[9]),
        "caution_days": int(quality_record[10]),
        "poor_days": int(quality_record[11]),
        "poor_day_share_pct": round(int(quality_record[11]) / int(quality_record[5]) * 100, 1),
        "median_reporting_markets": round(float(quality_record[12]), 1),
        "median_price": round(float(quality_record[2]), 3),
    }

    return {
        "data_start": metadata["data_period"]["start"],
        "data_end": metadata["data_period"]["end"],
        "last_complete_month": metadata["data_period"]["last_complete_month"],
        "city_gold_sha256": metadata["source_artifacts"]["city_gold"]["sha256"],
        "seasonality": seasonality,
        "cross_city": cross_city,
        "quality_risk": quality_risk,
    }


def render_markdown(stories: dict[str, Any]) -> str:
    season = stories["seasonality"]
    spread = stories["cross_city"]
    quality = stories["quality_risk"]
    return f"""# P1 可复现数据故事

本文件由正式 P1 Web mart 重算生成，用于面试演示与产品叙事。数据范围为 {stories['data_start']} 至 {stories['data_end']}，最后完整月份为 {stories['last_complete_month']}。所有价格均为历史人民币/公斤口径，不代表当前报价。

重建命令：`python3 src/monitor/build_p1_stories.py`

## 故事一：覆盖良好的城市也存在清晰的历史季节区间

### 筛选

- 蔬菜：{season['vegetable_name']}（`{season['vegetable_id']}`）
- 城市：{season['city_name']}（`{season['city_id']}`）
- 口径：对 2014–2022 各自然月的“月度中位价格”再做跨年中位数

### 可复现指标

- 历史高位月：{season['high_month']} 月，¥{season['high_price']:.2f}/kg，样本 {season['high_month_sample_years']} 年
- 历史低位月：{season['low_month']} 月，¥{season['low_price']:.2f}/kg，样本 {season['low_month_sample_years']} 年
- 高位月比低位月高：{season['high_vs_low_pct']:.1f}%

### 观察

{season['vegetable_name']}在{season['city_name']}的历史月度分布并非全年平坦。对 pricing 岗位而言，这个视图适合作为“历史基准带”：同样的绝对价格落在不同月份，业务含义可能不同。

### 不能推出

这不是未来价格预测，也不能仅凭月份差异判断供给、天气或节日是原因。

## 故事二：用中位区间比只看全国最高/最低更稳健

### 筛选

- 蔬菜：{spread['vegetable_name']}（`{spread['vegetable_id']}`）
- 月份：{spread['month']}
- 准入：Tier A/B 且该月至少 15 个有效日

### 可复现指标

- 可比城市：{spread['comparable_city_count']} 个
- 城市价格中位数：¥{spread['city_price_median']:.2f}/kg
- 中间 50% 城市区间：¥{spread['city_price_p25']:.2f}–¥{spread['city_price_p75']:.2f}/kg
- 最高：{spread['highest_city']} ¥{spread['highest_price']:.2f}/kg；最低：{spread['lowest_city']} ¥{spread['lowest_price']:.2f}/kg
- 最高比最低高：{spread['highest_vs_lowest_pct']:.1f}%

### 观察

极值价差远大于中间 50% 城市的价格带。用于定价参照时，全国最高/最低更适合触发调查，而城市中位数和四分位区间更适合作为常规 benchmark。

### 不能推出

原数据没有规格、包装、成交量和运费，不能把极值直接解释为套利空间或城市真实到岸成本差。

## 故事三：Coverage Tier 与单月数据质量必须分开看

### 筛选

- 蔬菜：{quality['vegetable_name']}（`{quality['vegetable_id']}`）
- 城市：{quality['city_name']}（`{quality['city_id']}`）
- 月份：{quality['month']}

### 可复现指标

- 全期 Coverage Tier：{quality['tier']}
- 当月有效日：{quality['valid_days']} 天
- 当月平均可靠性：{quality['reliability'] * 100:.2f}/100
- 日级质量构成：good {quality['good_days']} 天、caution {quality['caution_days']} 天、poor {quality['poor_days']} 天
- poor 日占比：{quality['poor_day_share_pct']:.1f}%
- 报告市场数中位数：{quality['median_reporting_markets']:.1f}；月度中位价格：¥{quality['median_price']:.2f}/kg

### 观察

该组合全期覆盖达到 Tier {quality['tier']}，但所选月全部有效日仍被 P0 标为 poor。产品上不能把“长期覆盖合格”翻译成“每个月都可靠”；排名、趋势和质量需要同屏。

### 不能推出

月度 mart 只能指出需要调查，不能在没有市场明细下确定 poor 的具体来源或修复报价。

## 面试讲法

1. 先展示季节基准，说明价格判断必须有历史位置；
2. 再切到跨城市价差，说明为什么用分位区间而不是只报极值；
3. 最后用质量反例说明本项目不是“漂亮图表”，而是把可用性条件嵌入 pricing decision support。

Gold 来源 SHA-256：`{stories['city_gold_sha256']}`。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/p1_stories.yaml")
    parser.add_argument("--output", default="docs/p1_data_stories.md")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    stories = compute_stories(root, load_flat_yaml(root / args.config))
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(stories), encoding="utf-8")
    print(f"Built {output_path.relative_to(root)} with 3 reproducible P1 stories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
