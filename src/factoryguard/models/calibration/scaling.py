"""Probability calibration (spec §8.6): temperature and isotonic scaling.

Calibrators are fit on the dedicated calibration period only (never on
train/val/test — the split framework provides it) and applied to any
model that emits P(defect). Reports show Brier/ECE and reliability curves
before and after calibration.

Method selection rule (documented, not tuned per run): isotonic when the
calibration set is large enough to support a stepwise fit without
overfitting (≥ ``min_isotonic_n`` samples including both classes), Platt
scaling otherwise. Platt (scale *and* bias on the logit) rather than pure
temperature scaling because every base model here trains with balanced
class weights, which centers raw scores near 0.5 while true prevalence is
a few percent — a bias temperature alone cannot remove (D-028).
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression

_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), _EPS, 1.0 - _EPS)
    return np.log(p / (1.0 - p))


class IdentityCalibrator:
    """No-op fallback (degenerate calibration sets)."""

    method = "identity"

    def fit(self, p: np.ndarray, y: np.ndarray) -> IdentityCalibrator:
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return np.asarray(p, dtype=np.float64)


class TemperatureScaler:
    """Single-parameter logit scaling: p' = σ(logit(p) / T).

    T > 1 softens over-confident probabilities; T < 1 sharpens. Fit by
    minimizing NLL on the calibration set. Rank-preserving.
    """

    method = "temperature"

    def __init__(self) -> None:
        self.temperature: float = 1.0

    def fit(self, p: np.ndarray, y: np.ndarray) -> TemperatureScaler:
        z = _logit(p)
        y_arr = np.asarray(y, dtype=np.float64)

        def nll(log_t: float) -> float:
            zz = z / np.exp(log_t)
            # stable log(1+exp): softplus
            return float(np.mean(np.logaddexp(0.0, zz) - y_arr * zz))

        res = minimize_scalar(nll, bounds=(-3.0, 3.0), method="bounded")
        self.temperature = float(np.exp(res.x))
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        z = _logit(p) / self.temperature
        return 1.0 / (1.0 + np.exp(-z))


class IsotonicCalibrator:
    """Monotone piecewise-constant map fit on the calibration set. Output
    clipped away from exact 0/1 so downstream log-loss stays finite."""

    method = "isotonic"

    def __init__(self) -> None:
        self._iso = IsotonicRegression(out_of_bounds="clip", y_min=_EPS, y_max=1.0 - _EPS)

    def fit(self, p: np.ndarray, y: np.ndarray) -> IsotonicCalibrator:
        self._iso.fit(np.asarray(p, dtype=np.float64), np.asarray(y, dtype=np.float64))
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return np.asarray(self._iso.predict(np.asarray(p, dtype=np.float64)), dtype=np.float64)


class PlattScaler:
    """Two-parameter logistic map: p' = σ(a·logit(p) + b), with a > 0.

    ``a`` fixes over/under-confidence, ``b`` fixes systematic bias (e.g.
    balanced-class-weight training at low prevalence). The slope is
    constrained positive so calibration can *never invert the ranking*: on
    a small calibration slice whose few positives happen to anti-correlate
    with the score, an unconstrained fit flips sign and destroys test-set
    ROC (observed on the small profile — ROC 0.71 → 0.29). Under the
    constraint, the worst case is a ≈ 0: predictions flatten toward the
    base rate but keep their order.
    """

    method = "platt"
    _A_BOUNDS = (0.05, 20.0)
    _B_BOUNDS = (-15.0, 15.0)

    def __init__(self) -> None:
        self.a: float = 1.0
        self.b: float = 0.0

    def fit(self, p: np.ndarray, y: np.ndarray) -> PlattScaler:
        from scipy.optimize import minimize

        z = _logit(p)
        y_arr = np.asarray(y, dtype=np.float64)

        def nll(params: np.ndarray) -> float:
            zz = params[0] * z + params[1]
            return float(np.mean(np.logaddexp(0.0, zz) - y_arr * zz))

        base = float(np.clip(y_arr.mean(), _EPS, 1 - _EPS))
        x0 = np.array([1.0, np.log(base / (1 - base)) - float(np.mean(z))])
        res = minimize(nll, x0, method="L-BFGS-B", bounds=[self._A_BOUNDS, self._B_BOUNDS])
        self.a, self.b = float(res.x[0]), float(res.x[1])
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        z = self.a * _logit(p) + self.b
        return 1.0 / (1.0 + np.exp(-z))


Calibrator = IdentityCalibrator | TemperatureScaler | PlattScaler | IsotonicCalibrator


def fit_calibrator(
    p_calib: np.ndarray, y_calib: np.ndarray, min_isotonic_n: int = 200
) -> Calibrator:
    """Apply the documented selection rule and fit on the calibration set."""
    y_arr = np.asarray(y_calib, dtype=bool)
    if len(y_arr) < 10 or y_arr.all() or not y_arr.any():
        return IdentityCalibrator().fit(p_calib, y_calib)
    if len(y_arr) >= min_isotonic_n:
        return IsotonicCalibrator().fit(p_calib, y_calib)
    return PlattScaler().fit(p_calib, y_calib)
