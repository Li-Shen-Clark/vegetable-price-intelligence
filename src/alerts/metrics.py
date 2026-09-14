"""Classification and ranking metrics for P3 price-risk alerts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _arrays(y_true: Any, scores: Any) -> tuple[np.ndarray, np.ndarray]:
    labels = np.asarray(y_true, dtype=int)
    probabilities = np.asarray(scores, dtype=float)
    if labels.ndim != 1 or probabilities.ndim != 1 or len(labels) != len(probabilities):
        raise ValueError("labels and scores must be equal-length one-dimensional arrays")
    if len(labels) == 0:
        raise ValueError("metrics require at least one row")
    if not np.isin(labels, [0, 1]).all() or not np.isfinite(probabilities).all():
        raise ValueError("labels must be binary and scores finite")
    return labels, probabilities


def precision_recall_curve(y_true: Any, scores: Any) -> pd.DataFrame:
    labels, probabilities = _arrays(y_true, scores)
    positives = int(labels.sum())
    negatives = int(len(labels) - positives)
    order = np.argsort(-probabilities, kind="mergesort")
    sorted_labels = labels[order]
    sorted_scores = probabilities[order]
    cumulative_tp = np.cumsum(sorted_labels)
    cumulative_fp = np.cumsum(1 - sorted_labels)
    boundary = np.r_[np.flatnonzero(np.diff(sorted_scores)), len(sorted_scores) - 1]
    tp = cumulative_tp[boundary]
    fp = cumulative_fp[boundary]
    alerts = tp + fp
    precision = np.divide(tp, alerts, out=np.ones_like(tp, dtype=float), where=alerts > 0)
    recall = np.divide(tp, positives, out=np.zeros_like(tp, dtype=float), where=positives > 0)
    fpr = np.divide(fp, negatives, out=np.zeros_like(fp, dtype=float), where=negatives > 0)
    top = pd.DataFrame(
        {
            "threshold": [float(np.nextafter(sorted_scores[0], np.inf))],
            "true_positives": [0],
            "false_positives": [0],
            "alerts": [0],
            "precision": [1.0],
            "recall": [0.0],
            "false_positive_rate": [0.0],
            "false_alert_share": [0.0],
        }
    )
    curve = pd.DataFrame(
        {
            "threshold": sorted_scores[boundary],
            "true_positives": tp,
            "false_positives": fp,
            "alerts": alerts,
            "precision": precision,
            "recall": recall,
            "false_positive_rate": fpr,
            "false_alert_share": np.divide(
                fp, alerts, out=np.zeros_like(fp, dtype=float), where=alerts > 0
            ),
        }
    )
    return pd.concat([top, curve], ignore_index=True)


def average_precision(y_true: Any, scores: Any) -> float:
    labels, probabilities = _arrays(y_true, scores)
    positives = int(labels.sum())
    if positives == 0:
        return 0.0
    curve = precision_recall_curve(labels, probabilities)
    recall = curve["recall"].to_numpy(dtype=float)
    precision = curve["precision"].to_numpy(dtype=float)
    return float(np.sum(np.diff(recall) * precision[1:]))


def select_threshold_at_fpr(curve: pd.DataFrame, maximum_fpr: float) -> dict[str, Any]:
    eligible = curve[curve["false_positive_rate"].le(maximum_fpr + 1e-12)].copy()
    if eligible.empty:
        raise ValueError("no PR-curve point satisfies the FPR constraint")
    selected = eligible.sort_values(
        ["recall", "precision", "threshold"], ascending=[False, False, False]
    ).iloc[0]
    return {
        key: float(selected[key]) if key not in {"true_positives", "false_positives", "alerts"} else int(selected[key])
        for key in selected.index
    }


def confusion_metrics(y_true: Any, scores: Any, threshold: float) -> dict[str, Any]:
    labels, probabilities = _arrays(y_true, scores)
    predicted = probabilities >= float(threshold)
    tp = int(((labels == 1) & predicted).sum())
    fp = int(((labels == 0) & predicted).sum())
    fn = int(((labels == 1) & ~predicted).sum())
    tn = int(((labels == 0) & ~predicted).sum())
    alerts = tp + fp
    positives = tp + fn
    negatives = fp + tn
    return {
        "threshold": float(threshold),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "alerts": alerts,
        "precision": float(tp / alerts) if alerts else 1.0,
        "recall": float(tp / positives) if positives else 0.0,
        "false_positive_rate": float(fp / negatives) if negatives else 0.0,
        "false_alert_share": float(fp / alerts) if alerts else 0.0,
    }


def score_alerts(
    y_true: Any,
    scores: Any,
    maximum_fpr: float,
    peak_returns: Any | None = None,
    lead_days: Any | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    labels, probabilities = _arrays(y_true, scores)
    curve = precision_recall_curve(labels, probabilities)
    threshold = select_threshold_at_fpr(curve, maximum_fpr)
    selected = confusion_metrics(labels, probabilities, threshold["threshold"])
    result: dict[str, Any] = {
        "rows": int(len(labels)),
        "events": int(labels.sum()),
        "prevalence": float(labels.mean()),
        "average_precision": average_precision(labels, probabilities),
        "brier_score": float(np.mean((probabilities - labels) ** 2)),
        "threshold_at_fixed_fpr": selected,
    }
    predicted = probabilities >= selected["threshold"]
    if lead_days is not None:
        lead = np.asarray(lead_days, dtype=float)
        matched = (labels == 1) & predicted & np.isfinite(lead)
        result["mean_lead_days"] = float(lead[matched].mean()) if matched.any() else None
        result["median_lead_days"] = float(np.median(lead[matched])) if matched.any() else None
    if peak_returns is not None:
        peaks = np.asarray(peak_returns, dtype=float)
        event_peaks = peaks[labels == 1]
        if len(event_peaks):
            cutoff = float(np.quantile(event_peaks, 0.90))
            top = (labels == 1) & (peaks >= cutoff)
            result["top_decile_peak_return_cutoff"] = cutoff
            result["top_decile_spike_events"] = int(top.sum())
            result["top_decile_spike_recall"] = float((predicted & top).sum() / top.sum()) if top.any() else None
    return result, curve
