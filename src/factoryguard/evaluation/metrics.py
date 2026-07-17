"""Evaluation metrics (spec §9): classification, calibration, forecast.

All functions are pure and take plain numpy arrays so they are trivially
property-testable. Thresholds/costs come from configuration, never here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn import metrics as skm


def classification_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
    fixed_fpr: float = 0.05,
    cost_fn: float = 25.0,
    cost_fp: float = 1.0,
) -> dict[str, float]:
    """Binary metrics. ``y_prob`` is P(positive). Degenerate single-class
    inputs return NaN for rank metrics rather than raising."""
    y_true = np.asarray(y_true, dtype=bool)
    y_prob = np.asarray(y_prob, dtype=float)
    y_pred = y_prob >= threshold
    out: dict[str, float] = {
        "n": float(len(y_true)),
        "prevalence": float(y_true.mean()) if len(y_true) else float("nan"),
        "precision": float(skm.precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(skm.recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(skm.f1_score(y_true, y_pred, zero_division=0)),
        "mcc": float(skm.matthews_corrcoef(y_true, y_pred)) if y_true.any() else 0.0,
        "brier": float(skm.brier_score_loss(y_true, y_prob)),
    }
    if y_true.any() and not y_true.all():
        out["roc_auc"] = float(skm.roc_auc_score(y_true, y_prob))
        out["pr_auc"] = float(skm.average_precision_score(y_true, y_prob))
        fpr, tpr, _ = skm.roc_curve(y_true, y_prob)
        out["recall_at_fpr"] = float(np.interp(fixed_fpr, fpr, tpr))
    else:
        out["roc_auc"] = out["pr_auc"] = out["recall_at_fpr"] = float("nan")
    tn, fp, fn, tp = skm.confusion_matrix(y_true, y_pred, labels=[False, True]).ravel()
    out.update(tn=float(tn), fp=float(fp), fn=float(fn), tp=float(tp))
    out["cost_weighted_error"] = float((cost_fn * fn + cost_fp * fp) / max(1, len(y_true)))
    out["fn_per_million"] = float(fn / max(1, len(y_true)) * 1_000_000)
    out["ece"] = expected_calibration_error(y_true, y_prob)
    return out


def anomaly_metrics(
    y_true: np.ndarray, score: np.ndarray, fixed_fpr: float = 0.05
) -> dict[str, float]:
    """Rank-based evaluation for anomaly/risk scores against labels used only
    for *evaluation* (never for fitting — these are unsupervised scorers).

    Deliberately excludes threshold-derived precision/recall/MCC and
    probability-calibration metrics (Brier/ECE): an anomaly score is not a
    calibrated probability, and reporting those would misrepresent it as
    one. Only rank-based metrics (which depend solely on ordering) are
    reported, plus the score distribution for transparency.
    """
    y_true = np.asarray(y_true, dtype=bool)
    score = np.asarray(score, dtype=float)
    out: dict[str, float] = {
        "n": float(len(y_true)),
        "prevalence": float(y_true.mean()) if len(y_true) else float("nan"),
        "score_mean": float(np.mean(score)) if len(score) else float("nan"),
        "score_std": float(np.std(score)) if len(score) else float("nan"),
    }
    if y_true.any() and not y_true.all():
        out["roc_auc"] = float(skm.roc_auc_score(y_true, score))
        out["pr_auc"] = float(skm.average_precision_score(y_true, score))
        fpr, tpr, _ = skm.roc_curve(y_true, score)
        out["recall_at_fpr"] = float(np.interp(fixed_fpr, fpr, tpr))
    else:
        out["roc_auc"] = out["pr_auc"] = out["recall_at_fpr"] = float("nan")
    return out


def multiclass_metrics(
    y_true: np.ndarray, y_prob: np.ndarray, classes: list[str]
) -> dict[str, Any]:
    """Multiclass metrics with per-class breakdown."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(classes, dtype=object)[np.argmax(y_prob, axis=1)]
    report = skm.classification_report(
        y_true, y_pred, labels=classes, output_dict=True, zero_division=0
    )
    per_class = {
        c: {
            "precision": float(report[c]["precision"]),
            "recall": float(report[c]["recall"]),
            "f1": float(report[c]["f1-score"]),
            "support": float(report[c]["support"]),
        }
        for c in classes
        if c in report
    }
    return {
        "accuracy": float(skm.accuracy_score(y_true, y_pred)),
        "macro_f1": float(skm.f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(skm.f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "mcc": float(skm.matthews_corrcoef(y_true, y_pred)),
        "per_class": per_class,
        "confusion": skm.confusion_matrix(y_true, y_pred, labels=classes).tolist(),
        "classes": classes,
    }


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    """Standard binned ECE."""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    if len(y_true) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (y_prob >= lo) & (y_prob < hi if hi < 1.0 else y_prob <= hi)
        if mask.any():
            ece += mask.mean() * abs(y_true[mask].mean() - y_prob[mask].mean())
    return float(ece)


def reliability_curve(
    y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10
) -> dict[str, list[float]]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    mids, obs, cnt = [], [], []
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (y_prob >= lo) & (y_prob < hi if hi < 1.0 else y_prob <= hi)
        mids.append(float((lo + hi) / 2))
        obs.append(float(y_true[mask].mean()) if mask.any() else float("nan"))
        cnt.append(float(mask.sum()))
    return {"bin_mid": mids, "observed_rate": obs, "count": cnt}


def forecast_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_pred - y_true
    out = {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
    }
    # sMAPE avoids divide-by-zero on zero-defect days (justified alternative to MAPE)
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    valid = denom > 0
    out["smape"] = (
        float(np.mean(np.abs(err[valid]) / denom[valid])) if valid.any() else float("nan")
    )
    return out


def interval_coverage(y_true: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    return float(np.mean((y_true >= lower) & (y_true <= upper))) if len(y_true) else float("nan")
