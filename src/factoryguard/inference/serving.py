"""Serving modes (ADR-0019): anomaly-only / blended / supervised.

The mode is configuration, validated fail-closed, and stamped on every
prediction result. The anomaly-combination rule is deliberately fixed and
documented (an equally-weighted mean over the anomaly scores available
for a unit) — a tunable ensemble here would be an unauditable model in
disguise.

Semantics of ``risk_score`` by mode:
- ``anomaly-only``: combined anomaly score. NOT a probability — wide
  uncertainty, conservative abstention, rank-meaningful only.
- ``blended``: w·P(defect) + (1−w)·anomaly. A monitored transition state,
  also not a calibrated probability (stated in the response).
- ``supervised``: the calibrated fused probability; anomaly scores remain
  attached as OOD/drift evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd


class ServingMode(StrEnum):
    ANOMALY_ONLY = "anomaly-only"
    BLENDED = "blended"
    SUPERVISED = "supervised"


def combine_anomaly_scores(
    anomaly: pd.DataFrame, weights: dict[str, float] | None = None
) -> np.ndarray:
    """Documented combination rule: mean of whichever anomaly scores are
    available per unit (NaN = that scorer missing). Units with no scorer at
    all get NaN — the caller must abstain on them.

    ``weights`` enables the drift-aware variant (OI-7): per-component
    weights from the drift report (``drift_aware_weights``), renormalized
    over the components available for each unit. Off by default —
    ``serving.drift_aware_anomaly_weights`` config gates it; the baseline
    remains the equal-weight mean (ADR-0019)."""
    if not weights:
        return anomaly.mean(axis=1, skipna=True).to_numpy(dtype=float)
    w = np.array([float(weights.get(c, 0.0)) for c in anomaly.columns])
    vals = anomaly.to_numpy(dtype=float)
    mask = np.isfinite(vals)
    wm = mask * w  # per-row weights over available components only
    denom = wm.sum(axis=1)
    num = np.nansum(vals * wm, axis=1)
    return np.where(denom > 0, num / np.maximum(denom, 1e-12), np.nan)


@dataclass
class ServingScores:
    """Row-aligned serving output for a batch of units."""

    mode: ServingMode
    risk_score: np.ndarray
    probability: np.ndarray | None  # calibrated P(defect); None in anomaly-only
    components: pd.DataFrame  # per-signal transparency (anomaly cols + supervised)
    is_probability: bool


def serve(
    mode: ServingMode,
    anomaly: pd.DataFrame,
    supervised_proba: np.ndarray | None = None,
    blend_weight: float = 0.7,
    anomaly_weights: dict[str, float] | None = None,
) -> ServingScores:
    """Produce the mode-appropriate risk score (spec §8.5/§18: the serving
    mode and per-component evidence are part of every response)."""
    if not 0.0 <= blend_weight <= 1.0:
        raise ValueError("blend_weight must be in [0, 1]")
    combined = combine_anomaly_scores(anomaly, weights=anomaly_weights)
    components = anomaly.copy()

    if mode is ServingMode.ANOMALY_ONLY:
        return ServingScores(mode, combined, None, components, is_probability=False)

    if supervised_proba is None:
        raise ValueError(f"mode {mode} requires supervised probabilities")
    proba = np.asarray(supervised_proba, dtype=float)
    components = components.assign(supervised_proba=proba)

    if mode is ServingMode.BLENDED:
        # Where no anomaly signal exists, fall back to the supervised term
        # rather than propagating NaN into the risk score.
        anomaly_term = np.where(np.isfinite(combined), combined, proba)
        risk = blend_weight * proba + (1.0 - blend_weight) * anomaly_term
        return ServingScores(mode, risk, proba, components, is_probability=False)

    return ServingScores(mode, proba, proba, components, is_probability=True)
