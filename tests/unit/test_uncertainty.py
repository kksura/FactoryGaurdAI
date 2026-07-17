"""Conformal prediction, Mahalanobis OOD and abstention (spec §8.6)."""

import numpy as np

from factoryguard.inference.uncertainty import (
    AbstentionPolicy,
    MahalanobisOOD,
    SplitConformal,
    abstention_curve,
)


def _calibrated_stream(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    p = rng.beta(2, 5, n)
    y = rng.uniform(size=n) < p
    return p, y


def test_conformal_marginal_coverage() -> None:
    p_cal, y_cal = _calibrated_stream(800, 1)
    p_te, y_te = _calibrated_stream(4000, 2)
    conf = SplitConformal(alpha=0.1).fit(p_cal, y_cal)
    sets = conf.prediction_sets(p_te)
    cov = conf.empirical_coverage(sets, y_te)
    assert cov >= 0.88  # guaranteed ≥ 0.9 marginally; allow sampling slack
    assert sets.any(axis=1).all()  # LAC sets are never empty


def test_conformal_confident_predictions_are_singletons() -> None:
    p_cal, y_cal = _calibrated_stream(500, 3)
    conf = SplitConformal(alpha=0.2).fit(p_cal, y_cal)
    assert not conf.ambiguous(np.array([0.001, 0.999])).any()


def test_mahalanobis_flags_shifted_embeddings() -> None:
    rng = np.random.default_rng(0)
    train = rng.normal(0, 1, (500, 16))
    calib = rng.normal(0, 1, (200, 16))
    shifted = rng.normal(6, 1, (100, 16))
    ood = MahalanobisOOD().fit(train)
    ood.set_threshold(calib, quantile=0.99)
    assert ood.is_ood(shifted).mean() > 0.95
    assert ood.is_ood(calib).mean() < 0.05
    # missing-modality rows (NaN) are never silently flagged
    assert not ood.is_ood(np.full((3, 16), np.nan)).any()


def test_abstention_policy_reasons() -> None:
    p_cal, y_cal = _calibrated_stream(500, 4)
    conf = SplitConformal(alpha=0.1).fit(p_cal, y_cal)
    rng = np.random.default_rng(1)
    ood = MahalanobisOOD().fit(rng.normal(0, 1, (300, 8)))
    ood.set_threshold(rng.normal(0, 1, (100, 8)))
    policy = AbstentionPolicy(conf, ood)
    proba = np.array([0.999, 0.5])
    emb = np.vstack([np.zeros(8), np.full(8, 9.0)])
    decisions = policy.decide(proba, emb, quality_flags=np.array([False, True]))
    assert not decisions[0].abstain
    assert decisions[1].abstain and len(decisions[1].reasons) >= 2


def test_abstention_curve_lower_coverage_lower_risk() -> None:
    p, y = _calibrated_stream(3000, 5)
    rows = abstention_curve(y, p)
    assert rows[-1]["coverage"] == 1.0
    # retaining only confident predictions must not increase error
    assert rows[0]["error_rate"] <= rows[-1]["error_rate"] + 1e-9
