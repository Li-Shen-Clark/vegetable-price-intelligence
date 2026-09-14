#!/usr/bin/env python3
"""Rebuild the versioned P0 last-value WAPE diagnostic."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


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


def load_simple_yaml(path: Path) -> dict[str, Any]:
    """Load the deliberately small YAML subset used by this diagnostic."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if ":" not in raw_line:
            raise ValueError(f"Unsupported YAML line {line_number}: {raw_line}")
        key, raw_value = raw_line.strip().split(":", 1)
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value = parse_scalar(raw_value)
        parent[key] = value
        if isinstance(value, dict):
            stack.append((indent, value))
    return root


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scope_codes(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(r"^\s+vegetable_code:\s*([A-Za-z_]+)\s*$", text, flags=re.MULTILINE)


def evaluate_product(
    raw_path: Path,
    mapping: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    columns = cfg["columns"]
    filters = cfg["filters"]
    evaluation = cfg["evaluation"]
    missing = cfg["missing_data"]

    date_col = columns["date"]
    market_col = columns["raw_market"]
    price_col = columns["observed_price"]
    city_col = columns["mapping_city"]

    raw = pd.read_csv(
        raw_path,
        encoding="utf-8-sig",
        usecols=[date_col, market_col, price_col],
    )
    raw[date_col] = pd.to_datetime(raw[date_col], errors="raise")
    raw[price_col] = pd.to_numeric(raw[price_col], errors="raise")
    raw = raw[
        (raw[price_col] > float(filters["minimum_price_exclusive"]))
        & (raw[date_col] >= pd.Timestamp(evaluation["start_date"]))
        & (raw[date_col] <= pd.Timestamp(evaluation["end_date"]))
    ]

    joined = raw.merge(
        mapping,
        left_on=market_col,
        right_on=columns["mapping_market"],
        how="inner",
        validate="many_to_one",
    )
    city_day = (
        joined.groupby([city_col, date_col], as_index=False)[price_col]
        .median()
        .sort_values([city_col, date_col])
    )
    valid_dates = city_day.groupby(city_col).size()
    eligible_cities = valid_dates[
        valid_dates >= int(filters["minimum_city_valid_dates"])
    ].index
    eligible = city_day[city_day[city_col].isin(eligible_cities)].copy()

    accumulators = {
        int(horizon): {"absolute_error_sum": 0.0, "absolute_actual_sum": 0.0, "prediction_count": 0}
        for horizon in evaluation["horizons_days"]
    }
    fill_limit = int(missing["origin_forward_fill_limit_days"])

    for _, city_series in eligible.groupby(city_col, sort=True):
        series = city_series.set_index(date_col)[price_col].sort_index()
        calendar = pd.date_range(series.index.min(), series.index.max(), freq="D")
        observed = series.reindex(calendar)
        observed_target = observed.notna()
        origin_price = observed.ffill(limit=fill_limit)

        for horizon, accumulator in accumulators.items():
            prediction = origin_price.shift(horizon)
            mask = prediction.notna()
            if bool(missing["require_observed_target"]):
                mask &= observed_target
            actual = observed[mask]
            forecast = prediction[mask]
            accumulator["absolute_error_sum"] += float((actual - forecast).abs().sum())
            accumulator["absolute_actual_sum"] += float(actual.abs().sum())
            accumulator["prediction_count"] += int(mask.sum())

    horizons = []
    for horizon in evaluation["horizons_days"]:
        values = accumulators[int(horizon)]
        denominator = values["absolute_actual_sum"]
        wape = values["absolute_error_sum"] / denominator
        if bool(cfg["metric"]["scale_percent"]):
            wape *= 100
        horizons.append(
            {
                "horizon_days": int(horizon),
                "prediction_count": values["prediction_count"],
                "absolute_error_sum": round(values["absolute_error_sum"], 8),
                "absolute_actual_sum": round(values["absolute_actual_sum"], 8),
                "wape_percent": round(wape, 6),
            }
        )

    return {
        "raw_row_count": int(len(pd.read_csv(raw_path, encoding="utf-8-sig", usecols=[date_col]))),
        "positive_in_range_row_count": int(len(raw)),
        "mapped_positive_row_count": int(len(joined)),
        "eligible_city_count": int(len(eligible_cities)),
        "eligible_city_day_count": int(len(eligible)),
        "horizons": horizons,
    }


def build_diagnostic(config_path: Path) -> dict[str, Any]:
    cfg = load_simple_yaml(config_path)
    project_root = config_path.resolve().parent.parent
    raw_dir = project_root / cfg["paths"]["raw_dir"]
    mapping_path = project_root / cfg["paths"]["mapping_file"]
    p2_scope_path = project_root / cfg["paths"]["p2_scope_file"]

    configured_products = list(cfg["scope"]["products"])
    frozen_scope = scope_codes(p2_scope_path)
    if configured_products != frozen_scope:
        raise ValueError("baseline product list does not match config/p2_scope.yaml")

    columns = cfg["columns"]
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")[
        [columns["mapping_market"], columns["mapping_city"]]
    ].drop_duplicates()
    if mapping[columns["mapping_market"]].duplicated().any():
        raise ValueError("mapping market names must be unique")

    input_files = [config_path, mapping_path, p2_scope_path]
    results: list[dict[str, Any]] = []
    for product in configured_products:
        raw_path = raw_dir / f"{product}.csv"
        if not raw_path.exists():
            raise FileNotFoundError(raw_path)
        input_files.append(raw_path)
        results.append(
            {
                "vegetable_code": product,
                **evaluate_product(raw_path, mapping, cfg),
            }
        )

    return {
        "diagnostic_version": cfg["diagnostic_version"],
        "status": "pre_p2_full_history_diagnostic",
        "data_as_of": cfg["evaluation"]["end_date"],
        "method": {
            "model": "last_value",
            "mapping": "exact match against the 200-row legacy mapping only",
            "city_day_aggregation": cfg["aggregation"]["city_day_method"],
            "minimum_city_valid_dates": int(cfg["filters"]["minimum_city_valid_dates"]),
            "origin_forward_fill_limit_days": int(cfg["missing_data"]["origin_forward_fill_limit_days"]),
            "require_observed_target": bool(cfg["missing_data"]["require_observed_target"]),
            "evaluation_start_date": cfg["evaluation"]["start_date"],
            "evaluation_end_date": cfg["evaluation"]["end_date"],
            "horizons_days": [int(x) for x in cfg["evaluation"]["horizons_days"]],
            "metric": "100 * sum(abs(actual - forecast)) / sum(abs(actual))",
        },
        "scope": configured_products,
        "implementation_sha256": sha256(Path(__file__).resolve()),
        "input_sha256": {
            str(path.relative_to(project_root)): sha256(path)
            for path in input_files
        },
        "results": results,
        "limitations": [
            "Uses only the legacy exact market mapping; 69 unmatched names are excluded.",
            "Uses the full historical period and is not a frozen-test or rolling-origin result.",
            "A one-day forward fill is allowed only at the forecast origin; targets must be observed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/baseline_wape.yaml")
    parser.add_argument("--output", default="baselines/v0_diagnostic.json")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    output_path = Path(args.output).resolve()
    result = build_diagnostic(config_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
