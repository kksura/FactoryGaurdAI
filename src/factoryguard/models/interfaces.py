"""Common model interfaces (spec §3.9 gap: "a common model interface").

Two protocols distinguish calibrated-probability models from anomaly/risk
scorers — conflating the two is a real reporting error (an isolation-forest
anomaly score is not a defect probability and must never be evaluated with
threshold-based precision/recall/Brier/ECE as if it were one).

These are structural (``Protocol``, not ABCs) so existing model classes
satisfy them without inheritance changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class ProbabilisticClassifier(Protocol):
    """A supervised model whose output is intended to be a calibrated (or
    calibratable) probability of the positive/target class."""

    name: str

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> ProbabilisticClassifier: ...
    def predict_proba(self, x: pd.DataFrame) -> np.ndarray: ...


@runtime_checkable
class AnomalyScorer(Protocol):
    """A model whose output is a relative risk/anomaly score — ordinally
    meaningful (higher = more anomalous) but NOT a calibrated probability.
    Fit without labels; scored with :func:`anomaly_metrics`, never
    :func:`classification_metrics`.
    """

    name: str

    def fit(self, x: object) -> AnomalyScorer: ...
    def anomaly_score(self, x: object) -> np.ndarray: ...
