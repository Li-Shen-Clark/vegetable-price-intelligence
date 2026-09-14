#!/usr/bin/env python3
"""Build the traceable P0 Bronze market-price Parquet."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


EXPECTED_COLUMNS = ["日期", "idx", "地区", "时长", "当日价格", "前一日价格", "环比"]
CHUNK_SIZE = 100_000

BRONZE_SCHEMA = pa.schema(
    [
        pa.field("vegetable_id", pa.int32(), nullable=False),
        pa.field("vegetable_code", pa.string(), nullable=False),
        pa.field("vegetable_name_zh", pa.string(), nullable=False),
        pa.field("source_file", pa.string(), nullable=False),
        pa.field("source_file_row_number", pa.int64(), nullable=False),
        pa.field("source_row_index", pa.int32(), nullable=False),
        pa.field("raw_date", pa.string(), nullable=False),
        pa.field("date", pa.date32(), nullable=False),
        pa.field("raw_province", pa.string(), nullable=False),
        pa.field("raw_market_name", pa.string(), nullable=False),
        pa.field("raw_observed_price", pa.string(), nullable=False),
        pa.field("observed_price", pa.float64(), nullable=False),
        pa.field("raw_previous_price", pa.string(), nullable=False),
        pa.field("previous_price", pa.float64(), nullable=False),
        pa.field("raw_reported_change", pa.string(), nullable=False),
        pa.field("reported_change_pct", pa.float64(), nullable=False),
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
            raise ValueError(f"Unsupported paths YAML line {line_number}: {raw_line}")
        key, value = raw_line.split(":", 1)
        result[key.strip()] = parse_scalar(value)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_dimension(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"vegetable_id", "vegetable_code", "vegetable_name_zh", "source_file"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("dim_vegetable is missing required columns")
    if len(rows) != len({row["vegetable_id"] for row in rows}):
        raise ValueError("vegetable_id must be unique")
    if len(rows) != len({row["source_file"] for row in rows}):
        raise ValueError("source_file must be unique")
    return rows


def parse_chunk(
    raw: pd.DataFrame,
    dim_row: Dict[str, str],
    file_row_offset: int,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if list(raw.columns) != EXPECTED_COLUMNS:
        raise ValueError(
            f"{dim_row['source_file']} header mismatch: {list(raw.columns)}"
        )

    parsed_date = pd.to_datetime(raw["日期"], format="%Y-%m-%d", errors="coerce")
    parsed_idx = pd.to_numeric(raw["idx"], errors="coerce")
    observed = pd.to_numeric(raw["当日价格"], errors="coerce")
    previous = pd.to_numeric(raw["前一日价格"], errors="coerce")
    reported_change = pd.to_numeric(
        raw["环比"].str.replace("%", "", regex=False), errors="coerce"
    )

    failures = {
        "date_parse_failures": int(parsed_date.isna().sum()),
        "source_index_parse_failures": int(parsed_idx.isna().sum()),
        "observed_price_parse_failures": int(observed.isna().sum()),
        "previous_price_parse_failures": int(previous.isna().sum()),
        "reported_change_parse_failures": int(reported_change.isna().sum()),
    }
    if any(failures.values()):
        raise ValueError(f"parse failures in {dim_row['source_file']}: {failures}")

    row_count = len(raw)
    output = pd.DataFrame(
        {
            "vegetable_id": np.full(row_count, int(dim_row["vegetable_id"]), dtype=np.int32),
            "vegetable_code": np.full(row_count, dim_row["vegetable_code"], dtype=object),
            "vegetable_name_zh": np.full(row_count, dim_row["vegetable_name_zh"], dtype=object),
            "source_file": np.full(row_count, dim_row["source_file"], dtype=object),
            "source_file_row_number": np.arange(
                file_row_offset + 1, file_row_offset + row_count + 1, dtype=np.int64
            ),
            "source_row_index": parsed_idx.astype(np.int32),
            "raw_date": raw["日期"],
            "date": parsed_date.dt.date,
            "raw_province": raw["地区"],
            "raw_market_name": raw["时长"],
            "raw_observed_price": raw["当日价格"],
            "observed_price": observed.astype(float),
            "raw_previous_price": raw["前一日价格"],
            "previous_price": previous.astype(float),
            "raw_reported_change": raw["环比"],
            "reported_change_pct": reported_change.astype(float),
        }
    )
    return output, failures


def build(config_path: Path) -> Dict[str, Any]:
    config = load_flat_yaml(config_path)
    project_root = config_path.resolve().parent.parent
    raw_dir = project_root / str(config["raw_price_dir"])
    dim_path = project_root / str(config["dim_vegetable"])
    output_path = project_root / str(config["bronze_fact_market_price"])
    manifest_path = project_root / str(config["bronze_manifest"])
    expected_files = int(config["expected_raw_files"])
    expected_rows = int(config["expected_raw_rows"])

    dimension = read_dimension(dim_path)
    if len(dimension) != expected_files:
        raise ValueError(f"expected {expected_files} dimension rows, found {len(dimension)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_output.unlink(missing_ok=True)
    temp_manifest.unlink(missing_ok=True)

    writer = None
    source_manifest: List[Dict[str, Any]] = []
    total_rows = 0
    global_min_date = None
    global_max_date = None

    try:
        writer = pq.ParquetWriter(
            temp_output,
            BRONZE_SCHEMA,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        for dim_row in dimension:
            raw_path = raw_dir / dim_row["source_file"]
            if not raw_path.exists():
                raise FileNotFoundError(raw_path)

            file_rows = 0
            file_min_date = None
            file_max_date = None
            file_failures = {
                "date_parse_failures": 0,
                "source_index_parse_failures": 0,
                "observed_price_parse_failures": 0,
                "previous_price_parse_failures": 0,
                "reported_change_parse_failures": 0,
            }

            chunks = pd.read_csv(
                raw_path,
                encoding="utf-8-sig",
                dtype=str,
                keep_default_na=False,
                chunksize=CHUNK_SIZE,
            )
            for raw_chunk in chunks:
                output_chunk, failures = parse_chunk(raw_chunk, dim_row, file_rows)
                for key, value in failures.items():
                    file_failures[key] += value

                chunk_min = output_chunk["date"].min()
                chunk_max = output_chunk["date"].max()
                file_min_date = chunk_min if file_min_date is None else min(file_min_date, chunk_min)
                file_max_date = chunk_max if file_max_date is None else max(file_max_date, chunk_max)

                table = pa.Table.from_pandas(
                    output_chunk,
                    schema=BRONZE_SCHEMA,
                    preserve_index=False,
                    safe=True,
                )
                writer.write_table(table, row_group_size=len(table))
                file_rows += len(table)

            if file_rows == 0:
                raise ValueError(f"empty source file: {raw_path}")
            total_rows += file_rows
            global_min_date = file_min_date if global_min_date is None else min(global_min_date, file_min_date)
            global_max_date = file_max_date if global_max_date is None else max(global_max_date, file_max_date)
            source_manifest.append(
                {
                    "source_file": dim_row["source_file"],
                    "vegetable_id": int(dim_row["vegetable_id"]),
                    "vegetable_code": dim_row["vegetable_code"],
                    "row_count": file_rows,
                    "minimum_date": file_min_date.isoformat(),
                    "maximum_date": file_max_date.isoformat(),
                    "sha256": sha256(raw_path),
                    **file_failures,
                }
            )

        writer.close()
        writer = None

        if total_rows != expected_rows:
            raise ValueError(f"expected {expected_rows} rows, wrote {total_rows}")
        parquet = pq.ParquetFile(temp_output)
        if parquet.metadata.num_rows != total_rows:
            raise ValueError(
                f"Parquet metadata rows {parquet.metadata.num_rows} != {total_rows}"
            )
        if parquet.schema_arrow != BRONZE_SCHEMA:
            raise ValueError("Parquet schema does not match the Bronze contract")

        output_hash = sha256(temp_output)
        manifest: Dict[str, Any] = {
            "dataset": "fact_market_price_raw",
            "layer": "bronze",
            "schema_version": "bronze_v0.1",
            "row_count": total_rows,
            "column_count": len(BRONZE_SCHEMA),
            "source_file_count": len(source_manifest),
            "minimum_date": global_min_date.isoformat(),
            "maximum_date": global_max_date.isoformat(),
            "trace_key": ["source_file", "source_file_row_number"],
            "trace_key_unique_by_construction": True,
            "parquet_compression": "zstd",
            "parquet_row_group_count": parquet.metadata.num_row_groups,
            "parquet_sha256": output_hash,
            "config_sha256": sha256(config_path),
            "dimension_sha256": sha256(dim_path),
            "implementation_sha256": sha256(Path(__file__).resolve()),
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in BRONZE_SCHEMA
            ],
            "source_files": source_manifest,
        }
        temp_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_output.replace(output_path)
        temp_manifest.replace(manifest_path)
        return manifest
    except Exception:
        if writer is not None:
            writer.close()
        temp_output.unlink(missing_ok=True)
        temp_manifest.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/paths.yaml")
    args = parser.parse_args()
    manifest = build(Path(args.config).resolve())
    print(
        json.dumps(
            {
                "dataset": manifest["dataset"],
                "rows": manifest["row_count"],
                "files": manifest["source_file_count"],
                "dates": [manifest["minimum_date"], manifest["maximum_date"]],
                "row_groups": manifest["parquet_row_group_count"],
                "parquet_sha256": manifest["parquet_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
