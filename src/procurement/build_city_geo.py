#!/usr/bin/env python3
"""Build the frozen P4 city anchor dimension and audit legacy market coordinates."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.procurement.common import haversine_km, load_flat_yaml


SPECIAL_CITY = "大理州弥渡县"
SPECIAL_SOURCE_CITY = "大理白族自治州"
SPECIAL_MARKET_ID = "mk115"


def validate_geo(frame: pd.DataFrame, dim_city: pd.DataFrame) -> None:
    required = {
        "city_id",
        "city_name_zh",
        "province_name_zh",
        "longitude",
        "latitude",
        "coordinate_method",
        "coordinate_source",
        "source_city_name",
        "alias_rule",
        "qa_status",
        "geo_dimension_version",
    }
    if set(frame.columns) != required:
        raise ValueError(f"Unexpected city geo columns: {frame.columns.tolist()}")
    if len(frame) != 117 or frame["city_id"].nunique() != 117:
        raise ValueError("P4 city geo dimension must contain 117 unique city ids")
    if set(frame["city_id"]) != set(dim_city["city_id"]):
        raise ValueError("P4 city geo ids must match the frozen P0 city dimension")
    if frame[["longitude", "latitude"]].isna().any().any():
        raise ValueError("P4 city geo coordinates may not be missing")
    if not frame["longitude"].between(70, 140).all():
        raise ValueError("P4 city longitudes fall outside the frozen China sanity range")
    if not frame["latitude"].between(10, 60).all():
        raise ValueError("P4 city latitudes fall outside the frozen China sanity range")
    if not frame["qa_status"].eq("accepted_for_city_anchor").all():
        raise ValueError("Every P4 city anchor must have an accepted QA status")


def build_geo(
    dim_city: pd.DataFrame,
    source_city: pd.DataFrame,
    market_mapping: pd.DataFrame,
    version: str,
) -> pd.DataFrame:
    source = source_city.rename(
        columns={
            "city": "source_city_name",
            "province": "source_province_name",
            "city_longgitude": "source_longitude",
            "city_latitude": "source_latitude",
        }
    )
    source = source[
        [
            "source_city_name",
            "source_province_name",
            "source_longitude",
            "source_latitude",
        ]
    ].copy()
    if len(source) != 117 or source["source_city_name"].nunique() != 117:
        raise ValueError("Source city coordinate snapshot must contain 117 unique cities")

    direct = dim_city.merge(
        source,
        left_on=["city_name_zh", "province_name_zh"],
        right_on=["source_city_name", "source_province_name"],
        how="left",
        validate="one_to_one",
    )
    direct["coordinate_method"] = "city_center_snapshot"
    direct["coordinate_source"] = "reference/source_city_coordinates.csv"
    direct["alias_rule"] = ""

    special_mask = direct["city_name_zh"].eq(SPECIAL_CITY)
    if int(special_mask.sum()) != 1:
        raise ValueError("Expected exactly one Dali county-level city exception")
    special_market = market_mapping.loc[
        market_mapping["market_id"].eq(SPECIAL_MARKET_ID)
        & market_mapping["mapping_status"].eq("mapped_existing_city")
    ]
    if len(special_market) != 1:
        raise ValueError("Dali exception market mk115 must be unique and formally mapped")
    market_row = special_market.iloc[0]
    direct.loc[special_mask, "source_city_name"] = SPECIAL_SOURCE_CITY
    direct.loc[special_mask, "source_province_name"] = market_row["canonical_province"]
    direct.loc[special_mask, "source_longitude"] = float(market_row["longitude"])
    direct.loc[special_mask, "source_latitude"] = float(market_row["latitude"])
    direct.loc[special_mask, "coordinate_method"] = "verified_market_exception"
    direct.loc[special_mask, "coordinate_source"] = (
        "reference/market_mapping.csv#mk115"
    )
    direct.loc[special_mask, "alias_rule"] = (
        "city dimension is county-level; do not substitute Dali prefecture center"
    )

    if int(direct["source_longitude"].isna().sum()) != 0:
        missing = direct.loc[direct["source_longitude"].isna(), "city_name_zh"].tolist()
        raise ValueError(f"Unresolved city coordinate aliases: {missing}")

    result = pd.DataFrame(
        {
            "city_id": direct["city_id"],
            "city_name_zh": direct["city_name_zh"],
            "province_name_zh": direct["province_name_zh"],
            "longitude": direct["source_longitude"].astype(float),
            "latitude": direct["source_latitude"].astype(float),
            "coordinate_method": direct["coordinate_method"],
            "coordinate_source": direct["coordinate_source"],
            "source_city_name": direct["source_city_name"],
            "alias_rule": direct["alias_rule"],
            "qa_status": "accepted_for_city_anchor",
            "geo_dimension_version": version,
        }
    )
    validate_geo(result, dim_city)
    return result


def build_market_coordinate_audit(
    market_mapping: pd.DataFrame, city_geo: pd.DataFrame
) -> pd.DataFrame:
    mapped = market_mapping.loc[
        market_mapping["mapping_status"].eq("mapped_existing_city")
    ].copy()
    audited = mapped.merge(
        city_geo[
            ["city_id", "city_name_zh", "longitude", "latitude", "coordinate_method"]
        ].rename(
            columns={
                "longitude": "city_anchor_longitude",
                "latitude": "city_anchor_latitude",
            }
        ),
        left_on="canonical_city",
        right_on="city_name_zh",
        how="left",
        validate="many_to_one",
    )
    has_coord = audited["longitude"].notna() & audited["latitude"].notna()
    audited["distance_to_city_anchor_km"] = np.nan
    audited.loc[has_coord, "distance_to_city_anchor_km"] = haversine_km(
        audited.loc[has_coord, "latitude"].to_numpy(float),
        audited.loc[has_coord, "longitude"].to_numpy(float),
        audited.loc[has_coord, "city_anchor_latitude"].to_numpy(float),
        audited.loc[has_coord, "city_anchor_longitude"].to_numpy(float),
    )
    distance = audited["distance_to_city_anchor_km"]
    audited["coordinate_audit_status"] = np.select(
        [
            ~has_coord,
            distance.gt(100),
            distance.gt(50),
            distance.gt(25),
        ],
        [
            "missing_market_coordinate",
            "severe_city_mismatch",
            "manual_review",
            "wide_city_or_county_market",
        ],
        default="within_25km",
    )
    columns = [
        "market_id",
        "standardized_name",
        "canonical_city",
        "canonical_province",
        "longitude",
        "latitude",
        "city_id",
        "city_anchor_longitude",
        "city_anchor_latitude",
        "coordinate_method",
        "distance_to_city_anchor_km",
        "coordinate_audit_status",
        "mapping_source",
        "mapping_version",
    ]
    return audited[columns].sort_values("market_id").reset_index(drop=True)


def render_audit_markdown(audit: pd.DataFrame) -> str:
    counts = audit["coordinate_audit_status"].value_counts().to_dict()
    valid = audit["distance_to_city_anchor_km"].dropna()
    top = audit.dropna(subset=["distance_to_city_anchor_km"]).nlargest(
        15, "distance_to_city_anchor_km"
    )
    lines = [
        "# P4 城市与市场坐标审计",
        "",
        "本审计只用于决定 P4 的城市距离锚点。旧市场坐标保留在 P0 映射中，但不进入 P4 正式距离计算。",
        "",
        "## 汇总",
        "",
        f"- 正式映射市场：{len(audit):,} 个。",
        f"- 有市场坐标：{len(valid):,} 个；缺失：{int(audit['distance_to_city_anchor_km'].isna().sum()):,} 个。",
        f"- 距城市锚点超过 50 公里：{int(valid.gt(50).sum()):,} 个。",
        f"- 距城市锚点超过 100 公里：{int(valid.gt(100).sum()):,} 个。",
        f"- 中位偏差：{float(valid.median()):.2f} 公里；最大偏差：{float(valid.max()):.2f} 公里。",
        "- 结论：legacy 市场坐标不足以支持自动质心或主市场聚合。P4 使用独立城市锚点维度。",
        "",
        "状态计数：",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- `{key}`：{int(counts[key])}")
    lines.extend(
        [
            "",
            "## 偏差最大的市场坐标",
            "",
            "| 市场 | 正式城市 | 偏差（公里） | 状态 |",
            "|---|---|---:|---|",
        ]
    )
    for row in top.itertuples(index=False):
        lines.append(
            f"| {row.standardized_name} | {row.canonical_city} | "
            f"{row.distance_to_city_anchor_km:.2f} | `{row.coordinate_audit_status}` |"
        )
    lines.extend(
        [
            "",
            "详细逐市场结果见 `docs/p4_coordinate_audit.csv`。距离为 Haversine 直线距离，不是道路里程。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_flat_yaml(root / "config/p4_procurement.yaml")
    dim_city = pd.read_csv(root / config["city_dimension_path"])
    source_city = pd.read_csv(root / config["source_city_coordinates_path"])
    market_mapping = pd.read_csv(root / config["market_mapping_path"])
    city_geo = build_geo(
        dim_city,
        source_city,
        market_mapping,
        str(config["geo_dimension_version"]),
    )
    geo_path = root / config["city_geo_path"]
    city_geo.to_csv(geo_path, index=False)
    audit = build_market_coordinate_audit(market_mapping, city_geo)
    audit_path = root / "docs/p4_coordinate_audit.csv"
    audit.to_csv(audit_path, index=False)
    markdown_path = root / "docs/p4_coordinate_audit.md"
    markdown_path.write_text(render_audit_markdown(audit), encoding="utf-8")
    print(
        f"built {geo_path.relative_to(root)} ({len(city_geo)} cities); "
        f"audited {len(audit)} markets"
    )


if __name__ == "__main__":
    main()
