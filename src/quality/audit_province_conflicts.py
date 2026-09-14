#!/usr/bin/env python3
"""Audit raw-province versus canonical-province conflicts in Silver."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pyarrow.parquet as pq


AUDIT_VERSION = "province_conflicts_v0.2"
REVIEWED_AT = "2026-09-11T17:33:00.000Z"
MAPPING_REVIEW_NAMES = {
    "张家界市永定区市场管理服务中心": (
        "旧映射城市为张家界市、原始省份为湖南省，但旧映射省份为河北省；城市与省份内部不一致",
        "https://swt.hunan.gov.cn/swt/hnswt/zt/xysytx/xysyjsxd/202407/t20240717_952072391849104640.html",
    ),
    "张家界市永定区奇峰市场": (
        "市场名明确包含张家界市永定区、原始省份为湖南省，但旧映射省份为河北省",
        "https://www.hunan.gov.cn/hnszf/hnyw/szdt/201905/t20190506_5327946.html",
    ),
}
XPCC_EVIDENCE = "https://cif.mofcom.gov.cn/cif/seach.fhtml?commdityid=170290"


def summarize(silver_path: Path) -> Tuple[int, List[Dict[str, Any]]]:
    parquet = pq.ParquetFile(silver_path)
    columns = [
        "raw_market_name",
        "raw_province",
        "market_province",
        "market_city",
        "market_id",
        "mapping_status",
        "date",
        "vegetable_id",
    ]
    total_rows = 0
    total_market_rows: Counter[str] = Counter()
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = defaultdict(
        lambda: {
            "conflict_rows": 0,
            "vegetables": set(),
            "first_date": None,
            "last_date": None,
            "market_id": None,
            "mapped_city": None,
        }
    )

    for batch in parquet.iter_batches(batch_size=100_000, columns=columns):
        frame = batch.to_pandas()
        total_rows += len(frame)
        total_market_rows.update(frame["raw_market_name"].value_counts().to_dict())
        conflict = frame[
            (frame["mapping_status"] == "mapped_existing_city")
            & (frame["raw_province"] != frame["market_province"])
        ]
        for key, part in conflict.groupby(
            ["raw_market_name", "raw_province", "market_province"], sort=False
        ):
            state = groups[key]
            state["conflict_rows"] += len(part)
            state["vegetables"].update(int(x) for x in part["vegetable_id"].unique())
            part_min = part["date"].min()
            part_max = part["date"].max()
            state["first_date"] = part_min if state["first_date"] is None else min(state["first_date"], part_min)
            state["last_date"] = part_max if state["last_date"] is None else max(state["last_date"], part_max)
            ids = part["market_id"].dropna().unique().tolist()
            cities = part["market_city"].dropna().unique().tolist()
            if len(ids) != 1 or len(cities) != 1:
                raise ValueError(f"non-unique mapped identity for conflict group {key}")
            state["market_id"] = ids[0]
            state["mapped_city"] = cities[0]

    ordered = sorted(
        groups.items(),
        key=lambda item: (-item[1]["conflict_rows"], item[0][0], item[0][1], item[0][2]),
    )
    rows: List[Dict[str, Any]] = []
    for index, ((market_name, raw_province, mapped_province), state) in enumerate(ordered, 1):
        if market_name in MAPPING_REVIEW_NAMES:
            decision = "mapping_review_required"
            reason, evidence = MAPPING_REVIEW_NAMES[market_name]
        elif raw_province == "新疆生产建设兵团" and mapped_province == "新疆维吾尔自治区":
            decision = "reporting_scope_difference"
            reason = "原始字段按新疆生产建设兵团报送，正式地理省份按新疆维吾尔自治区保存；两者描述不同维度"
            evidence = XPCC_EVIDENCE
        else:
            decision = "unresolved"
            reason = "现有证据不足以区分来源标签错误与映射错误"
            evidence = ""

        conflict_rows = int(state["conflict_rows"])
        market_rows = int(total_market_rows[market_name])
        rows.append(
            {
                "conflict_id": f"PC{index:03d}",
                "market_id": state["market_id"],
                "raw_market_name": market_name,
                "raw_province": raw_province,
                "mapped_city": state["mapped_city"],
                "mapped_province": mapped_province,
                "conflict_rows": conflict_rows,
                "total_market_rows": market_rows,
                "conflict_share_within_market": conflict_rows / market_rows,
                "share_of_all_silver_rows": conflict_rows / total_rows,
                "vegetable_count": len(state["vegetables"]),
                "first_date": state["first_date"].isoformat(),
                "last_date": state["last_date"].isoformat(),
                "decision": decision,
                "decision_reason": reason,
                "evidence_source": evidence,
                "review_status": "codex_reviewed",
                "reviewed_by": "Codex",
                "reviewed_at": REVIEWED_AT,
                "audit_version": AUDIT_VERSION,
            }
        )
    return total_rows, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--silver", default="data/silver/fact_market_price_mapped.parquet")
    parser.add_argument("--output-json")
    args = parser.parse_args()

    total_rows, rows = summarize(Path(args.silver).resolve())
    payload = {
        "audit_version": AUDIT_VERSION,
        "silver_rows": total_rows,
        "conflict_combination_count": len(rows),
        "conflict_market_count": len({row["raw_market_name"] for row in rows}),
        "conflict_rows": sum(row["conflict_rows"] for row in rows),
        "conflict_share": sum(row["conflict_rows"] for row in rows) / total_rows,
        "decision_counts": dict(sorted(Counter(row["decision"] for row in rows).items())),
        "rows": rows,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json:
        output_path = Path(args.output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(output_path)
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "rows"},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
