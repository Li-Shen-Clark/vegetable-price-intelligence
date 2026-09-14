"""Shared deterministic modeling utilities for P5 propagation experiments."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import f as f_distribution


KEY_COLUMNS = ["vegetable_id", "city_id", "bin_start"]


def add_exact_lags(
    panel: pd.DataFrame,
    *,
    value_columns: Iterable[str],
    lags: Iterable[int],
    bin_days: int,
) -> pd.DataFrame:
    """Add lags only when the exact anchored prior bin exists."""
    result = panel.copy()
    base = panel[[*KEY_COLUMNS, *value_columns]].copy()
    for lag in lags:
        shifted = base.copy()
        shifted["bin_start"] = shifted["bin_start"] + pd.Timedelta(
            days=int(lag) * int(bin_days)
        )
        shifted.rename(
            columns={column: f"{column}_lag{lag}" for column in value_columns},
            inplace=True,
        )
        result = result.merge(
            shifted,
            on=KEY_COLUMNS,
            how="left",
            validate="one_to_one",
        )
    return result


def design_matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    values = frame[columns].to_numpy(dtype=float)
    return np.column_stack([np.ones(len(values)), values])


def fit_ols(frame: pd.DataFrame, target: str, features: list[str]) -> np.ndarray:
    x = design_matrix(frame, features)
    y = frame[target].to_numpy(dtype=float)
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    return coefficients


def predict_ols(frame: pd.DataFrame, features: list[str], coefficients: np.ndarray) -> np.ndarray:
    matrix = design_matrix(frame, features)
    return np.sum(matrix * np.asarray(coefficients, dtype=float).reshape(1, -1), axis=1)


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int]:
    errors = np.asarray(actual, dtype=float) - np.asarray(predicted, dtype=float)
    return {
        "rows": int(len(errors)),
        "rmse": float(np.sqrt(np.mean(np.square(errors)))),
        "mae": float(np.mean(np.abs(errors))),
    }


def improvement(baseline: float, candidate: float) -> float:
    if not np.isfinite(baseline) or baseline <= 0:
        return float("nan")
    return float((baseline - candidate) / baseline)


def joint_f_test(
    y: np.ndarray,
    restricted_predictions: np.ndarray,
    unrestricted_predictions: np.ndarray,
    *,
    added_parameters: int,
    unrestricted_parameters: int,
) -> tuple[float, float]:
    residual_restricted = y - restricted_predictions
    residual_unrestricted = y - unrestricted_predictions
    rss_restricted = float(np.square(residual_restricted).sum())
    rss_unrestricted = float(np.square(residual_unrestricted).sum())
    numerator_df = int(added_parameters)
    denominator_df = int(len(y) - unrestricted_parameters)
    if denominator_df <= 0 or rss_unrestricted <= 0 or numerator_df <= 0:
        return 0.0, 1.0
    numerator = max(0.0, rss_restricted - rss_unrestricted) / numerator_df
    denominator = rss_unrestricted / denominator_df
    statistic = float(numerator / denominator) if denominator > 0 else 0.0
    p_value = float(f_distribution.sf(statistic, numerator_df, denominator_df))
    return statistic, p_value


def benjamini_hochberg(p_values: pd.Series, q: float) -> pd.DataFrame:
    """Return BH adjusted q-values and rejection flags in original row order."""
    values = p_values.to_numpy(dtype=float)
    count = len(values)
    order = np.argsort(values, kind="mergesort")
    ranked = values[order]
    adjusted_ranked = ranked * count / np.arange(1, count + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted_ranked = np.clip(adjusted_ranked, 0.0, 1.0)
    adjusted = np.empty(count, dtype=float)
    adjusted[order] = adjusted_ranked
    return pd.DataFrame(
        {
            "fdr_q_value": adjusted,
            "fdr_reject": adjusted <= float(q),
        },
        index=p_values.index,
    )


def prepare_lagged_panel(
    panel: pd.DataFrame,
    *,
    lags: list[int],
    bin_days: int,
) -> pd.DataFrame:
    return add_exact_lags(
        panel,
        value_columns=["propagation_residual", "common_factor_loo"],
        lags=lags,
        bin_days=bin_days,
    )
