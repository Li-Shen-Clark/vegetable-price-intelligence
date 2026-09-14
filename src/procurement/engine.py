"""Deterministic P4 procurement scenario calculations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.procurement.common import haversine_km


@dataclass(frozen=True)
class ScenarioParameters:
    quantity_kg: float
    transport_cost_per_kg_km: float
    loss_rate: float
    max_distance_km: float
    road_factor: float
    risk_aversion: float
    minimum_reliability: float
    reliability_gamma: float = 1.0
    maximum_reliability_multiplier: float = 1.5

    def validate(self) -> None:
        if not np.isfinite(self.quantity_kg) or self.quantity_kg <= 0:
            raise ValueError("quantity_kg must be finite and positive")
        if (
            not np.isfinite(self.transport_cost_per_kg_km)
            or self.transport_cost_per_kg_km < 0
        ):
            raise ValueError("transport_cost_per_kg_km must be finite and non-negative")
        if not np.isfinite(self.loss_rate) or not 0 <= self.loss_rate < 1:
            raise ValueError("loss_rate must be finite and in [0, 1)")
        if not np.isfinite(self.max_distance_km) or self.max_distance_km <= 0:
            raise ValueError("max_distance_km must be finite and positive")
        if not np.isfinite(self.road_factor) or self.road_factor < 1:
            raise ValueError("road_factor must be finite and at least one")
        if not np.isfinite(self.risk_aversion) or self.risk_aversion < 0:
            raise ValueError("risk_aversion must be finite and non-negative")
        if not np.isfinite(self.minimum_reliability) or not 0 <= self.minimum_reliability <= 1:
            raise ValueError("minimum_reliability must be in [0, 1]")
        if not np.isfinite(self.reliability_gamma) or self.reliability_gamma < 0:
            raise ValueError("reliability_gamma must be non-negative")
        if self.maximum_reliability_multiplier < 1:
            raise ValueError("maximum_reliability_multiplier must be at least one")


def default_parameters(config: dict[str, Any]) -> ScenarioParameters:
    return ScenarioParameters(
        quantity_kg=float(config["default_quantity_kg"]),
        transport_cost_per_kg_km=float(config["default_transport_cost_per_kg_km"]),
        loss_rate=float(config["default_loss_rate"]),
        max_distance_km=float(config["default_max_distance_km"]),
        road_factor=float(config["default_road_factor"]),
        risk_aversion=float(config["default_risk_aversion"]),
        minimum_reliability=float(config["default_minimum_reliability"]),
        reliability_gamma=float(config["reliability_gamma"]),
        maximum_reliability_multiplier=float(config["maximum_reliability_multiplier"]),
    )


def calculate_cost_rows(
    rows: pd.DataFrame,
    target_longitude: float,
    target_latitude: float,
    parameters: ScenarioParameters,
) -> pd.DataFrame:
    parameters.validate()
    result = rows.copy()
    result["straight_line_distance_km"] = haversine_km(
        result["latitude"].to_numpy(float),
        result["longitude"].to_numpy(float),
        float(target_latitude),
        float(target_longitude),
    )
    result["estimated_transport_distance_km"] = (
        result["straight_line_distance_km"] * parameters.road_factor
    )
    result["unit_transport_cost"] = (
        result["estimated_transport_distance_km"]
        * parameters.transport_cost_per_kg_km
    )
    result["reliability_multiplier"] = np.clip(
        1.0
        + parameters.reliability_gamma
        * (1.0 - result["origin_source_reliability_score"]),
        1.0,
        parameters.maximum_reliability_multiplier,
    )
    result["risk_penalty_per_kg"] = (
        parameters.risk_aversion
        * result["base_uncertainty_per_kg"]
        * result["reliability_multiplier"]
    )
    result["unit_pre_loss_cost"] = (
        result["released_point_prediction"]
        + result["unit_transport_cost"]
        + result["risk_penalty_per_kg"]
    )
    result["unit_landed_cost"] = result["unit_pre_loss_cost"] / (
        1.0 - parameters.loss_rate
    )
    result["unit_loss_cost"] = result["unit_landed_cost"] - result["unit_pre_loss_cost"]
    result["total_landed_cost"] = result["unit_landed_cost"] * parameters.quantity_kg
    return result


def row_to_record(row: pd.Series, local_unit_cost: float | None) -> dict[str, Any]:
    savings = None
    savings_rate = None
    if local_unit_cost is not None:
        savings = float(local_unit_cost - row["unit_landed_cost"])
        savings_rate = float(savings / local_unit_cost) if local_unit_cost > 0 else None
    keys = [
        "city_id",
        "city_name_zh",
        "province_name_zh",
        "release_status",
        "release_point_source",
        "price_input_label",
        "interval_status",
        "risk_basis",
        "released_point_prediction",
        "released_p10",
        "released_p90",
        "later_actual_price",
        "origin_source_reliability_score",
        "base_uncertainty_per_kg",
        "straight_line_distance_km",
        "estimated_transport_distance_km",
        "unit_transport_cost",
        "reliability_multiplier",
        "risk_penalty_per_kg",
        "unit_pre_loss_cost",
        "unit_loss_cost",
        "unit_landed_cost",
        "total_landed_cost",
    ]
    record: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if pd.isna(value):
            record[key] = None
        elif isinstance(value, (np.integer, int)):
            record[key] = int(value)
        elif isinstance(value, (np.floating, float)):
            record[key] = float(value)
        else:
            record[key] = str(value)
    record["savings_vs_local_per_kg"] = savings
    record["savings_vs_local_rate"] = savings_rate
    return record


def rank_sources(
    snapshot: pd.DataFrame,
    city_geo: pd.DataFrame,
    target_city_id: str,
    vegetable_id: int,
    horizon_days: int,
    parameters: ScenarioParameters,
    top_n: int = 3,
) -> dict[str, Any]:
    parameters.validate()
    target_rows = city_geo.loc[city_geo["city_id"].eq(target_city_id)]
    if len(target_rows) != 1:
        raise ValueError(f"Unknown or duplicate target city: {target_city_id}")
    target = target_rows.iloc[0]
    group = snapshot.loc[
        snapshot["vegetable_id"].eq(int(vegetable_id))
        & snapshot["horizon_days"].eq(int(horizon_days))
    ].copy()
    if group.empty:
        return {
            "status": "no_product_horizon_data",
            "target_city": {"city_id": target_city_id, "city_name_zh": target["city_name_zh"]},
            "vegetable_id": int(vegetable_id),
            "horizon_days": int(horizon_days),
            "parameters": asdict(parameters),
            "local_benchmark": None,
            "candidates": [],
            "filter_counts": {"input": 0, "reliability": 0, "distance": 0, "external": 0},
        }
    calculated = calculate_cost_rows(
        group,
        float(target["longitude"]),
        float(target["latitude"]),
        parameters,
    )
    reliable = calculated.loc[
        calculated["origin_source_reliability_score"].ge(parameters.minimum_reliability)
    ].copy()
    within_distance = reliable.loc[
        reliable["estimated_transport_distance_km"].le(parameters.max_distance_km)
    ].copy()
    local = within_distance.loc[within_distance["city_id"].eq(target_city_id)]
    local_record = None
    local_unit_cost = None
    if not local.empty:
        if len(local) != 1:
            raise ValueError("Local benchmark key is not unique")
        local_unit_cost = float(local.iloc[0]["unit_landed_cost"])
        local_record = row_to_record(local.iloc[0], local_unit_cost)

    external = within_distance.loc[~within_distance["city_id"].eq(target_city_id)].copy()
    external = external.sort_values(
        ["unit_landed_cost", "origin_source_reliability_score", "city_id"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    external["rank"] = np.arange(1, len(external) + 1)
    candidates = []
    for _, row in external.head(top_n).iterrows():
        record = row_to_record(row, local_unit_cost)
        record["rank"] = int(row["rank"])
        candidates.append(record)
    return {
        "status": "ok" if candidates else "no_candidates",
        "scenario_origin_date": pd.Timestamp(group["origin_date"].iloc[0]).date().isoformat(),
        "target_date": pd.Timestamp(group["target_date"].iloc[0]).date().isoformat(),
        "target_city": {
            "city_id": str(target_city_id),
            "city_name_zh": str(target["city_name_zh"]),
            "province_name_zh": str(target["province_name_zh"]),
        },
        "vegetable_id": int(vegetable_id),
        "vegetable_name_zh": str(group["vegetable_name_zh"].iloc[0]),
        "horizon_days": int(horizon_days),
        "parameters": asdict(parameters),
        "local_benchmark": local_record,
        "candidates": candidates,
        "filter_counts": {
            "input": int(len(calculated)),
            "reliability": int(len(reliable)),
            "distance": int(len(within_distance)),
            "external": int(len(external)),
        },
    }
