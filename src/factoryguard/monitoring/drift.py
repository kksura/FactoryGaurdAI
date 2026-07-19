"""Drift detection suite (spec §21, ADR-0016).

Pure functions over reference/current samples — no I/O, no thresholds
baked in (severity thresholds live in ``configs/policies/drift.yaml``,
spec §17). Four families:

- feature drift: PSI + Jensen–Shannon + KS + Wasserstein for numeric
  columns, PSI over category frequencies for categoricals;
- embedding drift: shift of the Mahalanobis-distance distribution of
  current embeddings under the *reference* covariance (mean shift and
  tail mass beyond the reference p99);
- calibration drift: ECE/Brier of recent labeled predictions vs the
  baseline calibration-period values;
- OI-7 hook: :func:`drift_aware_weights` converts per-component drift
  into down-weighting suggestions for the anomaly-only combination rule
  (config-gated at serve time; the default rule stays the documented
  equal-weight mean).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

_EPS = 1e-9


# ------------------------------------------------------------- univariate


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index over quantile bins of the reference.

    Rule of thumb: <0.1 stable · 0.1–0.25 moderate · >0.25 major shift.
    """
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 10 or len(cur) < 10:
        return float("nan")
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:  # (near-)constant feature — PSI undefined, not drifted
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    p = np.histogram(ref, bins=edges)[0] / len(ref)
    q = np.histogram(cur, bins=edges)[0] / len(cur)
    p, q = np.clip(p, _EPS, None), np.clip(q, _EPS, None)
    return float(np.sum((p - q) * np.log(p / q)))


def categorical_psi(reference: pd.Series, current: pd.Series) -> float:
    """PSI over category frequencies (union of categories; unseen → eps)."""
    cats = sorted(set(reference.dropna().unique()) | set(current.dropna().unique()))
    if not cats or len(reference) == 0 or len(current) == 0:
        return float("nan")
    p = reference.value_counts(normalize=True).reindex(cats).fillna(0).to_numpy()
    q = current.value_counts(normalize=True).reindex(cats).fillna(0).to_numpy()
    p, q = np.clip(p, _EPS, None), np.clip(q, _EPS, None)
    return float(np.sum((p - q) * np.log(p / q)))


def js_divergence(reference: np.ndarray, current: np.ndarray, bins: int = 20) -> float:
    """Jensen–Shannon divergence (base-2, in [0, 1]) over shared bins."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 10 or len(cur) < 10:
        return float("nan")
    lo = min(ref.min(), cur.min())
    hi = max(ref.max(), cur.max())
    if hi <= lo:
        return 0.0
    edges = np.linspace(lo, hi, bins + 1)
    p = np.histogram(ref, bins=edges)[0] / len(ref)
    q = np.histogram(cur, bins=edges)[0] / len(cur)
    return (
        float(
            stats.entropy((p + q) / 2, base=2)
            - (stats.entropy(p, base=2) + stats.entropy(q, base=2)) / 2
        )
        if (p.sum() and q.sum())
        else float("nan")
    )


def ks_statistic(reference: np.ndarray, current: np.ndarray) -> tuple[float, float]:
    """Two-sample Kolmogorov–Smirnov statistic and p-value."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 10 or len(cur) < 10:
        return float("nan"), float("nan")
    res = stats.ks_2samp(ref, cur)
    return float(res.statistic), float(res.pvalue)


def wasserstein(reference: np.ndarray, current: np.ndarray) -> float:
    """1-Wasserstein distance, scaled by the reference IQR so it is
    comparable across features (a distance of 1 ≈ one IQR of shift)."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 10 or len(cur) < 10:
        return float("nan")
    iqr = float(np.subtract(*np.percentile(ref, [75, 25]))) or 1.0
    return float(stats.wasserstein_distance(ref, cur) / iqr)


# ----------------------------------------------------------- higher level


@dataclass
class FeatureDrift:
    feature: str
    kind: str  # numeric | categorical
    psi: float
    js: float
    ks: float
    ks_pvalue: float
    wasserstein_iqr: float
    severity: str  # ok | moderate | major


def _severity(psi_value: float, thresholds: dict[str, float]) -> str:
    if not np.isfinite(psi_value):
        return "ok"
    if psi_value >= thresholds.get("psi_major", 0.25):
        return "major"
    if psi_value >= thresholds.get("psi_moderate", 0.10):
        return "moderate"
    return "ok"


def feature_drift(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    thresholds: dict[str, float] | None = None,
) -> list[FeatureDrift]:
    """Column-wise drift between two aligned feature frames. PSI drives the
    severity call; the other statistics are reported for diagnosis."""
    thresholds = thresholds or {}
    out: list[FeatureDrift] = []
    for col in reference.columns:
        if col not in current.columns:
            continue
        ref_col, cur_col = reference[col], current[col]
        if ref_col.dtype.name in ("category", "object", "bool"):
            p = categorical_psi(ref_col.astype(str), cur_col.astype(str))
            out.append(
                FeatureDrift(
                    feature=col,
                    kind="categorical",
                    psi=p,
                    js=float("nan"),
                    ks=float("nan"),
                    ks_pvalue=float("nan"),
                    wasserstein_iqr=float("nan"),
                    severity=_severity(p, thresholds),
                )
            )
        else:
            ref_v = ref_col.to_numpy(dtype=float)
            cur_v = cur_col.to_numpy(dtype=float)
            p = psi(ref_v, cur_v)
            ks, ks_p = ks_statistic(ref_v, cur_v)
            out.append(
                FeatureDrift(
                    feature=col,
                    kind="numeric",
                    psi=p,
                    js=js_divergence(ref_v, cur_v),
                    ks=ks,
                    ks_pvalue=ks_p,
                    wasserstein_iqr=wasserstein(ref_v, cur_v),
                    severity=_severity(p, thresholds),
                )
            )
    return out


def embedding_drift(
    reference_embeddings: np.ndarray,
    current_embeddings: np.ndarray,
    ood_quantile: float = 0.99,
) -> dict[str, float]:
    """Distribution shift of embeddings under the reference geometry.

    Fits Mahalanobis on the reference, scores both sets, and reports the
    mean-distance ratio plus the fraction of current points beyond the
    reference's ``ood_quantile`` distance (expected ≈ 1 − quantile when
    nothing drifted)."""
    from factoryguard.inference.uncertainty import MahalanobisOOD

    ood = MahalanobisOOD().fit(reference_embeddings)
    d_ref = ood.anomaly_score(reference_embeddings)
    d_cur = ood.anomaly_score(current_embeddings)
    d_ref, d_cur = d_ref[np.isfinite(d_ref)], d_cur[np.isfinite(d_cur)]
    if len(d_ref) < 10 or len(d_cur) < 10:
        return {"available": 0.0}
    threshold = float(np.quantile(d_ref, ood_quantile))
    return {
        "available": 1.0,
        "mean_distance_ratio": float(d_cur.mean() / (d_ref.mean() + _EPS)),
        "tail_fraction_current": float((d_cur > threshold).mean()),
        "tail_fraction_expected": float(1.0 - ood_quantile),
        "distance_psi": psi(d_ref, d_cur),
    }


def calibration_drift(
    y_true: np.ndarray,
    proba: np.ndarray,
    baseline_ece: float,
    baseline_brier: float,
) -> dict[str, float]:
    """Calibration on a recent labeled window vs the recorded baseline."""
    from factoryguard.evaluation.metrics import expected_calibration_error

    y = np.asarray(y_true, dtype=bool)
    p = np.asarray(proba, dtype=float)
    if len(y) < 20:
        return {"available": 0.0}
    ece = expected_calibration_error(y, p)
    brier = float(np.mean((p - y) ** 2))
    return {
        "available": 1.0,
        "ece": ece,
        "brier": brier,
        "baseline_ece": baseline_ece,
        "baseline_brier": baseline_brier,
        "ece_delta": ece - baseline_ece,
        "brier_delta": brier - baseline_brier,
    }


def drift_aware_weights(component_psi: dict[str, float]) -> dict[str, float]:
    """OI-7: suggested anomaly-component weights, down-weighting drifted
    components: w ∝ 1 / (1 + PSI), renormalized. Deterministic and
    reported alongside the drift report; serving applies them only when
    ``serving.drift_aware_anomaly_weights`` is enabled (default off — the
    baseline rule remains the documented equal-weight mean, ADR-0019)."""
    raw = {name: 1.0 / (1.0 + (p if np.isfinite(p) else 0.0)) for name, p in component_psi.items()}
    total = sum(raw.values()) or 1.0
    return {name: round(w / total, 4) for name, w in raw.items()}


def summarize(features: list[FeatureDrift]) -> dict[str, Any]:
    by_sev: dict[str, int] = {"ok": 0, "moderate": 0, "major": 0}
    for f in features:
        by_sev[f.severity] += 1
    worst = sorted((f for f in features if np.isfinite(f.psi)), key=lambda f: -f.psi)[:5]
    return {
        "n_features": len(features),
        "by_severity": by_sev,
        "worst": [
            {"feature": f.feature, "psi": round(f.psi, 4), "severity": f.severity} for f in worst
        ],
    }
