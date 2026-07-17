"""Calibration behaviour (Phase 4): temperature/isotonic scaling."""

import numpy as np

from factoryguard.evaluation.metrics import expected_calibration_error
from factoryguard.models.calibration import (
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattScaler,
    TemperatureScaler,
    fit_calibrator,
)


def _overconfident_data(n: int = 4000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """True P(y)=σ(z); the 'model' reports σ(3z) — badly over-confident."""
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 1.2, n)
    p_true = 1 / (1 + np.exp(-z))
    y = rng.uniform(size=n) < p_true
    p_model = 1 / (1 + np.exp(-3 * z))
    return p_model, y


def test_temperature_recovers_overconfidence() -> None:
    p, y = _overconfident_data()
    scaler = TemperatureScaler().fit(p, y)
    assert scaler.temperature > 1.5  # must soften an over-confident model
    p_cal = scaler.transform(p)
    assert expected_calibration_error(y, p_cal) < expected_calibration_error(y, p) / 2


def test_temperature_preserves_ranking() -> None:
    p, y = _overconfident_data()
    p_cal = TemperatureScaler().fit(p, y).transform(p)
    assert (np.diff(p_cal[np.argsort(p)]) >= -1e-12).all()


def test_isotonic_improves_ece_and_stays_in_bounds() -> None:
    p, y = _overconfident_data()
    p_cal = IsotonicCalibrator().fit(p, y).transform(p)
    assert (p_cal > 0).all() and (p_cal < 1).all()
    assert expected_calibration_error(y, p_cal) < expected_calibration_error(y, p)


def test_selection_rule() -> None:
    p, y = _overconfident_data(n=1000)
    assert fit_calibrator(p, y, min_isotonic_n=200).method == "isotonic"
    assert fit_calibrator(p[:100], y[:100], min_isotonic_n=200).method == "platt"
    # degenerate: single class → identity fallback
    ones = np.ones(50, dtype=bool)
    assert isinstance(fit_calibrator(p[:50], ones), IdentityCalibrator)


def test_platt_fixes_bias_from_balanced_training() -> None:
    """Balanced class weights center scores near 0.5 at 5% prevalence —
    only a bias-capable calibrator can repair that (D-028)."""
    rng = np.random.default_rng(7)
    n = 3000
    y = rng.uniform(size=n) < 0.05
    # biased but rank-informative score centered at ~0.5
    z = 0.8 * y + rng.normal(0, 1, n)
    p_model = 1 / (1 + np.exp(-z))
    cal = PlattScaler().fit(p_model[:1500], y[:1500])
    p_cal = cal.transform(p_model[1500:])
    from sklearn.metrics import brier_score_loss

    prior_brier = brier_score_loss(y[1500:], np.full(1500, y[:1500].mean()))
    assert brier_score_loss(y[1500:], p_cal) < prior_brier * 1.1  # ≈ beats the prior
    assert brier_score_loss(y[1500:], p_cal) < brier_score_loss(y[1500:], p_model[1500:]) / 2
