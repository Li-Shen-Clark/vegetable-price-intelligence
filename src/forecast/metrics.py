"""Shared deterministic metrics for P2 point and probabilistic forecasts."""

from __future__ import annotations

from typing import Any

import numpy as np


def _arrays(actual: Any, prediction: Any) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(actual, dtype=float)
    p = np.asarray(prediction, dtype=float)
    if y.shape != p.shape:
        raise ValueError("actual and prediction must have identical shapes")
    if y.size == 0 or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError("metrics require non-empty finite arrays")
    return y, p


def wape(actual: Any, prediction: Any) -> float:
    y, p = _arrays(actual, prediction)
    denominator = float(np.abs(y).sum())
    if denominator == 0:
        raise ValueError("WAPE denominator is zero")
    return float(np.abs(y - p).sum() / denominator)


def mae(actual: Any, prediction: Any) -> float:
    y, p = _arrays(actual, prediction)
    return float(np.abs(y - p).mean())


def smape(actual: Any, prediction: Any) -> float:
    y, p = _arrays(actual, prediction)
    denominator = np.abs(y) + np.abs(p)
    values = np.divide(
        2.0 * np.abs(y - p),
        denominator,
        out=np.zeros_like(denominator),
        where=denominator > 0,
    )
    return float(values.mean())


def pinball_loss(actual: Any, prediction: Any, quantile: float) -> float:
    if not 0 < quantile < 1:
        raise ValueError("quantile must be between zero and one")
    y, p = _arrays(actual, prediction)
    error = y - p
    return float(np.maximum(quantile * error, (quantile - 1.0) * error).mean())


def interval_coverage(actual: Any, lower: Any, upper: Any) -> float:
    y, lo = _arrays(actual, lower)
    _, hi = _arrays(actual, upper)
    if np.any(lo > hi):
        raise ValueError("lower interval exceeds upper interval")
    return float(((y >= lo) & (y <= hi)).mean())


def mean_interval_width(lower: Any, upper: Any) -> float:
    lo, hi = _arrays(lower, upper)
    if np.any(lo > hi):
        raise ValueError("lower interval exceeds upper interval")
    return float((hi - lo).mean())


def weighted_interval_score(
    actual: Any,
    lower: Any,
    median: Any,
    upper: Any,
    alpha: float = 0.2,
) -> float:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    y, lo = _arrays(actual, lower)
    _, mid = _arrays(actual, median)
    _, hi = _arrays(actual, upper)
    if np.any(lo > mid) or np.any(mid > hi):
        raise ValueError("quantiles must be ordered")
    interval_score = (
        hi
        - lo
        + (2.0 / alpha) * (lo - y) * (y < lo)
        + (2.0 / alpha) * (y - hi) * (y > hi)
    )
    wis = (0.5 * np.abs(y - mid) + (alpha / 2.0) * interval_score) / (
        0.5 + alpha / 2.0
    )
    return float(wis.mean())


def point_metric_record(actual: Any, prediction: Any) -> dict[str, float | int]:
    y, p = _arrays(actual, prediction)
    return {
        "row_count": int(len(y)),
        "wape": round(wape(y, p), 8),
        "mae": round(mae(y, p), 8),
        "smape": round(smape(y, p), 8),
        "absolute_error_sum": round(float(np.abs(y - p).sum()), 8),
        "absolute_actual_sum": round(float(np.abs(y).sum()), 8),
    }


def probability_metric_record(
    actual: Any,
    p10: Any,
    p50: Any,
    p90: Any,
) -> dict[str, float | int]:
    y, lower = _arrays(actual, p10)
    _, median = _arrays(actual, p50)
    _, upper = _arrays(actual, p90)
    return {
        "row_count": int(len(y)),
        "interval_coverage_80": round(interval_coverage(y, lower, upper), 8),
        "mean_interval_width": round(mean_interval_width(lower, upper), 8),
        "pinball_loss_p10": round(pinball_loss(y, lower, 0.1), 8),
        "pinball_loss_p50": round(pinball_loss(y, median, 0.5), 8),
        "pinball_loss_p90": round(pinball_loss(y, upper, 0.9), 8),
        "wis_80": round(weighted_interval_score(y, lower, median, upper, 0.2), 8),
    }
