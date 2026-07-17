"""Serving-mode semantics (ADR-0019)."""

import numpy as np
import pandas as pd
import pytest

from factoryguard.inference.serving import ServingMode, combine_anomaly_scores, serve


def _anomaly_frame() -> pd.DataFrame:
    return pd.DataFrame({"isolation_forest": [0.2, 0.8, np.nan], "stat_ts": [0.4, np.nan, np.nan]})


def test_combine_rule_is_nan_aware_mean() -> None:
    combined = combine_anomaly_scores(_anomaly_frame())
    np.testing.assert_allclose(combined[:2], [0.3, 0.8])
    assert np.isnan(combined[2])  # no scorer at all → caller must abstain


def test_anomaly_only_has_no_probability() -> None:
    out = serve(ServingMode.ANOMALY_ONLY, _anomaly_frame())
    assert out.probability is None
    assert not out.is_probability
    assert out.mode is ServingMode.ANOMALY_ONLY


def test_blended_math_and_nan_fallback() -> None:
    proba = np.array([0.6, 0.2, 0.5])
    out = serve(ServingMode.BLENDED, _anomaly_frame(), proba, blend_weight=0.7)
    np.testing.assert_allclose(out.risk_score[0], 0.7 * 0.6 + 0.3 * 0.3)
    # unit with no anomaly signal falls back to the supervised term
    np.testing.assert_allclose(out.risk_score[2], 0.5)
    assert not out.is_probability
    assert "supervised_proba" in out.components.columns


def test_supervised_passthrough_and_validation() -> None:
    proba = np.array([0.6, 0.2, 0.5])
    out = serve(ServingMode.SUPERVISED, _anomaly_frame(), proba)
    np.testing.assert_allclose(out.risk_score, proba)
    assert out.is_probability
    with pytest.raises(ValueError, match="requires supervised"):
        serve(ServingMode.BLENDED, _anomaly_frame(), None)
    with pytest.raises(ValueError, match="blend_weight"):
        serve(ServingMode.BLENDED, _anomaly_frame(), proba, blend_weight=1.5)
