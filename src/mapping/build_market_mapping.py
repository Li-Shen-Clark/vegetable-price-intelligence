#!/usr/bin/env python3
"""Join the versioned market mapping onto Bronze and build Silver."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


CHUNK_SIZE = 100_000
MAPPING_REQUIRED_COLUMNS = {
    "raw_market_name",
    "standardized_name",
    "market_id",
    "canonical_city",
    "canonical_province",
    "identified_city",
    "identified_province",
    "longitude",
    "latitude",
    "mapping_status",
    "mapping_confidence",
    "mapping_source",
    "mapping_version",
    "raw_market_name_recovered",
}
VALID_STATUSES = {
    "mapped_existing_city",
    "unmapped_new_city",
    "unmapped_unknown",
}


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


def optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_mapping(
    rows: List[Dict[str, str]],
    expected_markets: int,
    expected_version: str,
) -> None:
    if len(rows) != expected_markets:
        raise ValueError(f"expected {expected_markets} mapping rows, found {len(rows)}")
    if not rows or not MAPPING_REQUIRED_COLUMNS.issubset(rows[0]):
        missing = sorted(MAPPING_REQUIRED_COLUMNS - (set(rows[0]) if rows else set()))
        raise ValueError(f"mapping table missing required columns: {missing}")
    if len({row["raw_market_name"] for row in rows}) != len(rows):
        raise ValueError("mapping raw_market_name must be unique")
    if len({row["market_id"] for row in rows}) != len(rows):
        raise ValueError("mapping market_id must be unique")
    invalid_statuses = sorted({row["mapping_status"] for row in rows} - VALID_STATUSES)
    if invalid_statuses:
        raise ValueError(f"invalid mapping statuses: {invalid_statuses}")
    invalid_versions = sorted({row["mapping_version"] for row in rows} - {expected_version})
    if invalid_versions:
        raise ValueError(f"unexpected mapping versions: {invalid_versions}")
    for row in rows:
        status = row["mapping_status"]
        if not row["raw_market_name"] or not row["standardized_name"] or not row["market_id"]:
            raise ValueError("mapping identity fields cannot be blank")
        if not row["identified_city"] or not row["identified_province"]:
            raise ValueError(f"identified location blank for {row['raw_market_name']}")
        if status == "mapped_existing_city" and (
            not row["canonical_city"] or not row["canonical_province"]
        ):
            raise ValueError(f"canonical location blank for mapped row {row['raw_market_name']}")
        if status != "mapped_existing_city" and (
            row["canonical_city"] or row["canonical_province"]
        ):
            raise ValueError(f"out-of-scope row has canonical city {row['raw_market_name']}")


def validate_legacy_preservation(
    legacy_rows: List[Dict[str, str]],
    mapping_rows: List[Dict[str, str]],
    expected_version: str,
) -> None:
    by_name = {row["raw_market_name"]: row for row in mapping_rows}
    if len(legacy_rows) != 200:
        raise ValueError(f"expected 200 legacy rows, found {len(legacy_rows)}")
    for legacy in legacy_rows:
        raw_name = legacy["market_Name"]
        current = by_name.get(raw_name)
        if current is None:
            raise ValueError(f"legacy market missing from mapping: {raw_name}")
        expected = {
            "market_id": legacy["market_ID"],
            "canonical_city": legacy["market_city"],
            "canonical_province": legacy["market_province"],
            "longitude": legacy["market_Longitude"],
            "latitude": legacy["market_Latitude"],
        }
        if expected_version == "v0.2" and legacy["market_ID"] in {"mk54", "mk173"}:
            expected["canonical_province"] = "湖南省"
        actual = {key: current[key] for key in expected}
        if actual != expected:
            raise ValueError(
                f"legacy mapping drift for {raw_name}: expected {expected}, found {actual}"
            )


def build_schema(bronze_schema: pa.Schema) -> pa.Schema:
    return pa.schema(
        list(bronze_schema)
        + [
            pa.field("market_id", pa.string(), nullable=False),
            pa.field("standardized_market_name", pa.string(), nullable=False),
            pa.field("market_city", pa.string(), nullable=True),
            pa.field("market_province", pa.string(), nullable=True),
            pa.field("identified_city", pa.string(), nullable=False),
            pa.field("identified_province", pa.string(), nullable=False),
            pa.field("market_longitude", pa.float64(), nullable=True),
            pa.field("market_latitude", pa.float64(), nullable=True),
            pa.field("mapping_status", pa.string(), nullable=False),
            pa.field("mapping_confidence", pa.string(), nullable=False),
            pa.field("mapping_source", pa.string(), nullable=False),
            pa.field("mapping_version", pa.string(), nullable=False),
            pa.field("raw_market_name_recovered", pa.string(), nullable=True),
        ]
    )


def mapping_vectors(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    vectors: Dict[str, Dict[str, Any]] = {
        "market_id": {},
        "standardized_market_name": {},
        "market_city": {},
        "market_province": {},
        "identified_city": {},
        "identified_province": {},
        "market_longitude": {},
        "market_latitude": {},
        "mapping_status": {},
        "mapping_confidence": {},
        "mapping_source": {},
        "mapping_version": {},
        "raw_market_name_recovered": {},
    }
    for row in rows:
        key = row["raw_market_name"]
        vectors["market_id"][key] = row["market_id"]
        vectors["standardized_market_name"][key] = row["standardized_name"]
        vectors["market_city"][key] = row["canonical_city"] or None
        vectors["market_province"][key] = row["canonical_province"] or None
        vectors["identified_city"][key] = row["identified_city"]
        vectors["identified_province"][key] = row["identified_province"]
        vectors["market_longitude"][key] = optional_float(row["longitude"])
        vectors["market_latitude"][key] = optional_float(row["latitude"])
        vectors["mapping_status"][key] = row["mapping_status"]
        vectors["mapping_confidence"][key] = row["mapping_confidence"]
        vectors["mapping_source"][key] = row["mapping_source"]
        vectors["mapping_version"][key] = row["mapping_version"]
        vectors["raw_market_name_recovered"][key] = row["raw_market_name_recovered"] or None
    return vectors


def build(config_path: Path) -> Dict[str, Any]:
    config = load_flat_yaml(config_path)
    project_root = config_path.resolve().parent.parent
    bronze_path = project_root / str(config["bronze_fact_market_price"])
    mapping_path = project_root / str(config["market_mapping"])
    legacy_path = project_root / str(config["legacy_market_mapping"])
    output_path = project_root / str(config["silver_fact_market_price"])
    manifest_path = project_root / str(config["silver_manifest"])
    expected_rows = int(config["expected_raw_rows"])
    expected_markets = int(config["expected_unique_markets"])
    expected_version = str(config["market_mapping_version"])

    mapping_rows = read_csv_rows(mapping_path)
    validate_mapping(mapping_rows, expected_markets, expected_version)
    validate_legacy_preservation(read_csv_rows(legacy_path), mapping_rows, expected_version)
    vectors = mapping_vectors(mapping_rows)

    bronze = pq.ParquetFile(bronze_path)
    if bronze.metadata.num_rows != expected_rows:
        raise ValueError(
            f"Bronze rows {bronze.metadata.num_rows} do not match expected {expected_rows}"
        )
    silver_schema = build_schema(bronze.schema_arrow)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_output.unlink(missing_ok=True)
    temp_manifest.unlink(missing_ok=True)

    writer = None
    total_rows = 0
    status_counts: Counter[str] = Counter()
    source_file_counts: Counter[str] = Counter()
    observed_market_names: set[str] = set()
    try:
        writer = pq.ParquetWriter(
            temp_output,
            silver_schema,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        for batch in bronze.iter_batches(batch_size=CHUNK_SIZE):
            frame = batch.to_pandas()
            raw_names = frame["raw_market_name"]
            observed_market_names.update(raw_names.unique().tolist())
            for column, lookup in vectors.items():
                frame[column] = raw_names.map(lookup)

            missing_count = int(frame["mapping_status"].isna().sum())
            if missing_count:
                missing_names = sorted(
                    frame.loc[frame["mapping_status"].isna(), "raw_market_name"].unique()
                )
                raise ValueError(f"unmapped Bronze names: {missing_names}")

            status_counts.update(frame["mapping_status"].value_counts().to_dict())
            source_file_counts.update(frame["source_file"].value_counts().to_dict())
            table = pa.Table.from_pandas(
                frame,
                schema=silver_schema,
                preserve_index=False,
                safe=True,
            )
            writer.write_table(table, row_group_size=len(table))
            total_rows += len(table)

        writer.close()
        writer = None

        if total_rows != expected_rows:
            raise ValueError(f"expected {expected_rows} Silver rows, wrote {total_rows}")
        if observed_market_names != {row["raw_market_name"] for row in mapping_rows}:
            missing = sorted({row["raw_market_name"] for row in mapping_rows} - observed_market_names)
            extra = sorted(observed_market_names - {row["raw_market_name"] for row in mapping_rows})
            raise ValueError(f"market-name coverage mismatch: mapping_only={missing}, bronze_only={extra}")

        silver = pq.ParquetFile(temp_output)
        if silver.metadata.num_rows != total_rows:
            raise ValueError("Silver metadata row count mismatch")
        if silver.schema_arrow != silver_schema:
            raise ValueError("Silver schema does not match contract")

        mapped_rows = status_counts.get("mapped_existing_city", 0)
        manifest: Dict[str, Any] = {
            "dataset": "fact_market_price_mapped",
            "layer": "silver",
            "schema_version": "silver_v0.1",
            "mapping_version": expected_version,
            "row_count": total_rows,
            "column_count": len(silver_schema),
            "unique_market_count": len(observed_market_names),
            "mapping_status_row_counts": dict(sorted(status_counts.items())),
            "mapped_existing_city_row_rate": mapped_rows / total_rows,
            "source_file_row_counts": dict(sorted(source_file_counts.items())),
            "trace_key": ["source_file", "source_file_row_number"],
            "trace_key_unique_by_construction": True,
            "parquet_compression": "zstd",
            "parquet_row_group_count": silver.metadata.num_row_groups,
            "parquet_sha256": sha256(temp_output),
            "bronze_sha256": sha256(bronze_path),
            "mapping_sha256": sha256(mapping_path),
            "legacy_mapping_sha256": sha256(legacy_path),
            "config_sha256": sha256(config_path),
            "implementation_sha256": sha256(Path(__file__).resolve()),
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in silver_schema
            ],
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
                "columns": manifest["column_count"],
                "markets": manifest["unique_market_count"],
                "mapping_status_row_counts": manifest["mapping_status_row_counts"],
                "mapped_existing_city_row_rate": manifest["mapped_existing_city_row_rate"],
                "row_groups": manifest["parquet_row_group_count"],
                "parquet_sha256": manifest["parquet_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
