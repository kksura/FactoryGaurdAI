"""Uncertainty quantification and abstention (spec §8.6, approved methods:
split conformal prediction + Mahalanobis OOD — ADRs forbid re-litigating
toward ensembles/MC-dropout).

- :class:`SplitConformal`: distribution-free prediction sets for the
  binary defect decision, calibrated on a dedicated conformal holdout
  (never the same samples used to fit the probability calibrator).
- :class:`MahalanobisOOD`: distance of a unit's embedding from the
  training distribution — flags inputs the model has no business being
  confident about (new lines, drifted sensors, corrupted images).
- :class:`AbstentionPolicy`: combines conformal ambiguity, OOD, and
  data-quality flags into an abstain/predict decision with reasons.
- :func:`abstention_curve`: risk/coverage trade-off data for the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

_EPS = 1e-9


class SplitConformal:
    """Split conformal prediction for binary P(defect) scores.

    Nonconformity is the classical LAC score s = 1 − p(true class). The
    finite-sample-corrected (1−α) quantile of calibration scores gives a
    threshold q̂; the prediction set contains every class c with
    p(c) ≥ 1 − q̂. Marginal coverage ≥ 1−α holds by construction
    (exchangeability caveat: temporal drift can erode it — the report
    states empirical coverage on the test period for exactly this reason).
    """

    def __init__(self, alpha: float = 0.1) -> None:
        self.alpha = alpha
        self.qhat: float = 1.0

    def fit(self, proba: np.ndarray, y: np.ndarray) -> SplitConformal:
        p = np.asarray(proba, dtype=np.float64)
        y_arr = np.asarray(y, dtype=bool)
        n = len(p)
        if n == 0:
            raise ValueError("empty conformal calibration set")
        s = np.where(y_arr, 1.0 - p, p)  # 1 − p(true class)
        rank = int(np.ceil((n + 1) * (1.0 - self.alpha)))
        self.qhat = 1.0 if rank > n else float(np.sort(s)[rank - 1])
        return self

    def prediction_sets(self, proba: np.ndarray) -> np.ndarray:
        """(n, 2) boolean membership [class_ok, class_defect]."""
        p = np.asarray(proba, dtype=np.float64)
        thr = 1.0 - self.qhat
        return np.stack([(1.0 - p) >= thr - _EPS, p >= thr - _EPS], axis=1)

    def ambiguous(self, proba: np.ndarray) -> np.ndarray:
        """True where the set is not a single class (both or empty)."""
        sets = self.prediction_sets(proba)
        return sets.sum(axis=1) != 1

    @staticmethod
    def empirical_coverage(sets: np.ndarray, y: np.ndarray) -> float:
        y_arr = np.asarray(y, dtype=bool)
        return float(np.mean(np.where(y_arr, sets[:, 1], sets[:, 0])))


class MahalanobisOOD:
    """Mahalanobis distance of embeddings from the training distribution.

    Covariance is regularized toward its diagonal (shrinkage γ) plus a
    small ridge so the inverse exists for embedding dims comparable to the
    sample count. Flag threshold is a quantile of *calibration* distances,
    so the false-flag rate on in-distribution data is controlled.
    """

    name = "mahalanobis_ood"

    def __init__(self, shrinkage: float = 0.1, ridge: float = 1e-3) -> None:
        self.shrinkage = shrinkage
        self.ridge = ridge
        self._mean: np.ndarray | None = None
        self._inv: np.ndarray | None = None
        self.threshold: float = float("inf")

    def fit(self, embeddings: np.ndarray) -> MahalanobisOOD:
        x = np.asarray(embeddings, dtype=np.float64)
        x = x[np.isfinite(x).all(axis=1)]
        if len(x) < 2:
            raise ValueError("need ≥2 finite embeddings to fit OOD detector")
        self._mean = x.mean(axis=0)
        cov = np.cov(x, rowvar=False)
        cov = np.atleast_2d(cov)
        diag = np.diag(np.diag(cov))
        cov = (1.0 - self.shrinkage) * cov + self.shrinkage * diag
        cov += self.ridge * np.eye(cov.shape[0])
        self._inv = np.linalg.inv(cov)
        return self

    def anomaly_score(self, embeddings: np.ndarray) -> np.ndarray:
        """Mahalanobis distance per row; NaN rows (missing modality
        upstream) score NaN and must be handled by the caller's policy."""
        assert self._mean is not None and self._inv is not None, "fit() first"
        x = np.asarray(embeddings, dtype=np.float64)
        out = np.full(len(x), np.nan)
        ok = np.isfinite(x).all(axis=1)
        d = x[ok] - self._mean
        out[ok] = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", d, self._inv, d), 0.0))
        return out

    def set_threshold(self, calib_embeddings: np.ndarray, quantile: float = 0.995) -> float:
        d = self.anomaly_score(calib_embeddings)
        d = d[np.isfinite(d)]
        self.threshold = float(np.quantile(d, quantile)) if len(d) else float("inf")
        return self.threshold

    def is_ood(self, embeddings: np.ndarray) -> np.ndarray:
        d = self.anomaly_score(embeddings)
        return np.where(np.isfinite(d), d > self.threshold, False)


@dataclass
class AbstentionDecision:
    abstain: bool
    reasons: list[str] = field(default_factory=list)


class AbstentionPolicy:
    """Abstain when the model cannot stand behind a single answer:
    conformal set ambiguous, embedding out-of-distribution, or the input
    itself failed data-quality checks. Reasons are reported verbatim in
    the prediction response (spec §10 human-readable requirements)."""

    def __init__(self, conformal: SplitConformal, ood: MahalanobisOOD | None = None) -> None:
        self.conformal = conformal
        self.ood = ood

    def decide(
        self,
        proba: np.ndarray,
        embeddings: np.ndarray | None = None,
        quality_flags: np.ndarray | None = None,
    ) -> list[AbstentionDecision]:
        n = len(proba)
        ambiguous = self.conformal.ambiguous(proba)
        ood_flags = np.zeros(n, dtype=bool)
        if self.ood is not None and embeddings is not None:
            ood_flags = np.asarray(self.ood.is_ood(embeddings), dtype=bool)
        quality = (
            np.zeros(n, dtype=bool) if quality_flags is None else np.asarray(quality_flags, bool)
        )
        decisions = []
        for i in range(n):
            reasons = []
            if ambiguous[i]:
                reasons.append("conformal prediction set is not a single class")
            if ood_flags[i]:
                reasons.append("embedding is out-of-distribution (Mahalanobis)")
            if quality[i]:
                reasons.append("input failed data-quality checks")
            decisions.append(AbstentionDecision(abstain=bool(reasons), reasons=reasons))
        return decisions


def abstention_curve(
    y: np.ndarray,
    proba: np.ndarray,
    coverages: np.ndarray | None = None,
    threshold: float = 0.5,
) -> list[dict[str, float]]:
    """Risk/coverage curve: keep the most-confident fraction of predictions
    (confidence = distance of p from the decision threshold) and report the
    error metrics among the retained. The report plots risk falling as
    coverage drops — the operational argument for abstention."""
    y_arr = np.asarray(y, dtype=bool)
    p = np.asarray(proba, dtype=np.float64)
    conf = np.abs(p - threshold)
    order = np.argsort(-conf, kind="stable")
    coverages = coverages if coverages is not None else np.linspace(0.5, 1.0, 11)
    rows = []
    for cov in coverages:
        k = max(1, int(round(cov * len(p))))
        kept = order[:k]
        pred = p[kept] >= threshold
        yy = y_arr[kept]
        err = float(np.mean(pred != yy))
        recall = float(pred[yy].mean()) if yy.any() else float("nan")
        rows.append(
            {
                "coverage": float(k / len(p)),
                "error_rate": err,
                "defect_recall": recall,
                "n": float(k),
            }
        )
    return rows
