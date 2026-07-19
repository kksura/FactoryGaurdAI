"""Drift suite behaviour: quiet on identical data, fires on real shift."""

import numpy as np
import pandas as pd

from factoryguard.monitoring.drift import (
    calibration_drift,
    categorical_psi,
    drift_aware_weights,
    embedding_drift,
    feature_drift,
    js_divergence,
    ks_statistic,
    psi,
    summarize,
    wasserstein,
)

RNG = np.random.default_rng(0)
REF = RNG.normal(0, 1, 2000)
SAME = RNG.normal(0, 1, 2000)
SHIFTED = RNG.normal(1.5, 1, 2000)


def test_psi_quiet_then_fires() -> None:
    assert psi(REF, SAME) < 0.05
    assert psi(REF, SHIFTED) > 0.25  # major by every rule of thumb


def test_js_ks_wasserstein_ordering() -> None:
    assert js_divergence(REF, SHIFTED) > js_divergence(REF, SAME)
    ks_same, p_same = ks_statistic(REF, SAME)
    ks_shift, p_shift = ks_statistic(REF, SHIFTED)
    assert ks_shift > ks_same and p_shift < 0.001 < p_same
    assert wasserstein(REF, SHIFTED) > wasserstein(REF, SAME)


def test_categorical_psi_detects_mix_change() -> None:
    ref = pd.Series(["a"] * 800 + ["b"] * 200)
    same = pd.Series(["a"] * 790 + ["b"] * 210)
    shifted = pd.Series(["a"] * 300 + ["b"] * 500 + ["c"] * 200)
    assert categorical_psi(ref, same) < 0.05
    assert categorical_psi(ref, shifted) > 0.25


def test_feature_drift_severity_and_summary() -> None:
    ref = pd.DataFrame({"x": REF, "cat": pd.Categorical(["a"] * 1000 + ["b"] * 1000)})
    cur = pd.DataFrame({"x": SHIFTED, "cat": pd.Categorical(["a"] * 1000 + ["b"] * 1000)})
    result = feature_drift(ref, cur, {"psi_moderate": 0.1, "psi_major": 0.25})
    by_name = {f.feature: f for f in result}
    assert by_name["x"].severity == "major"
    assert by_name["cat"].severity == "ok"
    s = summarize(result)
    assert s["by_severity"]["major"] == 1
    assert s["worst"][0]["feature"] == "x"


def test_embedding_drift_ratio() -> None:
    ref = RNG.normal(0, 1, (600, 8))
    same = RNG.normal(0, 1, (600, 8))
    shifted = RNG.normal(2.0, 1, (600, 8))
    quiet = embedding_drift(ref, same)
    loud = embedding_drift(ref, shifted)
    assert 0.9 < quiet["mean_distance_ratio"] < 1.15
    assert loud["mean_distance_ratio"] > 1.5
    assert loud["tail_fraction_current"] > 0.5 > quiet["tail_fraction_current"]


def test_calibration_drift_deltas() -> None:
    y = RNG.uniform(size=2000) < 0.3
    good = np.where(y, 0.7, 0.2) + RNG.normal(0, 0.02, 2000)
    out = calibration_drift(y, np.clip(good, 0.01, 0.99), baseline_ece=0.05, baseline_brier=0.15)
    assert out["available"] == 1.0
    assert "ece_delta" in out and "brier_delta" in out


def test_drift_aware_weights_downweight_drifted() -> None:
    w = drift_aware_weights({"stable": 0.02, "drifted": 0.8})
    assert w["stable"] > w["drifted"]
    assert abs(sum(w.values()) - 1.0) < 1e-6
    # NaN drift (component unavailable) → treated as no drift, not dropped
    w2 = drift_aware_weights({"a": float("nan"), "b": 0.0})
    assert abs(w2["a"] - w2["b"]) < 1e-9
