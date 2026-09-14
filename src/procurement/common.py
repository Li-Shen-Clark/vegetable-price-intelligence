from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def haversine_km(
    latitude_a: float | np.ndarray,
    longitude_a: float | np.ndarray,
    latitude_b: float | np.ndarray,
    longitude_b: float | np.ndarray,
) -> float | np.ndarray:
    radius_km = 6371.0088
    lat_a = np.radians(latitude_a)
    lat_b = np.radians(latitude_b)
    delta_lat = np.radians(np.asarray(latitude_b) - np.asarray(latitude_a))
    delta_lon = np.radians(np.asarray(longitude_b) - np.asarray(longitude_a))
    value = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(lat_a) * np.cos(lat_b) * np.sin(delta_lon / 2.0) ** 2
    )
    distance = 2.0 * radius_km * np.arcsin(np.sqrt(np.minimum(1.0, value)))
    if np.ndim(distance) == 0:
        return float(distance)
    return distance
