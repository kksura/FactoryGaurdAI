"""Late fusion (ADR-0006, default serving path).

A logistic meta-classifier over, per modality: the calibrated score
(neutral-filled 0.5 where missing), the availability mask, and an
uncertainty proxy (closeness of the score to 0.5). The mask feature is
what lets the meta-classifier learn *how much to trust* each modality's
neutral fill — a missing modality is a first-class input state, not a
fake observation.

Modality-dropout training (spec §8.5): the training matrix is augmented
with copies in which each present modality is independently dropped, so
serving-time missingness patterns are in-distribution for the meta model.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from factoryguard.models.fusion.inputs import FusionInput

_NEUTRAL = 0.5


class LateFusion:
    name = "late_fusion"

    def __init__(self, dropout_rate: float = 0.3, dropout_copies: int = 2, seed: int = 0) -> None:
        self.dropout_rate = dropout_rate
        self.dropout_copies = dropout_copies
        self.seed = seed
        self.modalities: list[str] = []
        self._meta = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)

    def _features(self, scores: np.ndarray, mask: np.ndarray) -> np.ndarray:
        filled = np.where(mask, np.nan_to_num(scores, nan=_NEUTRAL), _NEUTRAL)
        uncertainty = 1.0 - 2.0 * np.abs(filled - _NEUTRAL)  # 1 at p=0.5, 0 at p∈{0,1}
        return np.concatenate([filled, mask.astype(float), uncertainty], axis=1)

    def fit(self, inputs: FusionInput, y: np.ndarray) -> LateFusion:
        self.modalities = list(inputs.scores.columns)
        scores = inputs.scores.to_numpy(dtype=float)
        mask = inputs.score_mask()
        y_arr = np.asarray(y, dtype=bool)

        rng = np.random.default_rng(self.seed)
        xs, ys = [self._features(scores, mask)], [y_arr]
        for _ in range(self.dropout_copies):
            drop = rng.uniform(size=mask.shape) < self.dropout_rate
            aug_mask = mask & ~drop
            keep = aug_mask.any(axis=1)  # a row with zero modalities teaches nothing
            xs.append(self._features(scores[keep], aug_mask[keep]))
            ys.append(y_arr[keep])
        self._meta.fit(np.concatenate(xs), np.concatenate(ys))
        return self

    def predict_proba(self, inputs: FusionInput) -> np.ndarray:
        scores = inputs.scores.to_numpy(dtype=float)
        x = self._features(scores, inputs.score_mask())
        return np.asarray(self._meta.predict_proba(x))

    def modality_contributions(self) -> dict[str, float]:
        """|meta coefficient| of each modality's score feature — the
        per-modality attribution the report shows (association, not
        causation)."""
        coefs = np.abs(self._meta.coef_[0][: len(self.modalities)])
        return dict(zip(self.modalities, (float(c) for c in coefs), strict=True))
