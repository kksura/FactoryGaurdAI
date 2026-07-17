"""Fusion contract + late/embedding fusion behaviour (ADR-0006).

The load-bearing property: a missing modality is an explicit input state
(mask), never a zero-valued observation.
"""

import numpy as np
import pandas as pd
import pytest

from factoryguard.models.fusion import EmbeddingFusion, FusionInput, LateFusion


def _toy_inputs(n: int = 600, seed: int = 0) -> tuple[FusionInput, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = rng.uniform(size=n) < 0.3
    noise = lambda s: rng.normal(0, s, n)  # noqa: E731
    scores = pd.DataFrame(
        {
            "tabular": np.clip(0.28 * y + 0.2 + noise(0.1), 0.01, 0.99),
            "timeseries": np.clip(0.22 * y + 0.25 + noise(0.12), 0.01, 0.99),
            "vision": np.clip(0.3 * y + 0.2 + noise(0.1), 0.01, 0.99),
            "graph": np.clip(0.1 * y + 0.3 + noise(0.15), 0.01, 0.99),
        }
    )
    # vision missing for 60% of units (like real image coverage)
    missing = rng.uniform(size=n) < 0.6
    scores.loc[missing, "vision"] = np.nan
    emb = {
        m: (y[:, None] * 1.5 + rng.normal(0, 1, (n, 8))).astype(np.float32)
        for m in ("tabular", "timeseries", "vision", "graph")
    }
    emb["vision"][missing] = np.nan
    return FusionInput(scores=scores, embeddings=emb), y


def test_fusion_input_validates_alignment() -> None:
    scores = pd.DataFrame({"tabular": [0.5, 0.5]})
    with pytest.raises(ValueError, match="row-aligned"):
        FusionInput(scores=scores, embeddings={"tabular": np.zeros((3, 4))})
    with pytest.raises(ValueError, match="unknown modalities"):
        FusionInput(scores=pd.DataFrame({"lidar": [0.1]}), embeddings={})


def test_late_fusion_learns_and_beats_worst_modality() -> None:
    inputs, y = _toy_inputs()
    fused = LateFusion(seed=0).fit(inputs, y).predict_proba(inputs)[:, 1]
    from sklearn.metrics import roc_auc_score

    auc = roc_auc_score(y, fused)
    worst = roc_auc_score(y, np.nan_to_num(inputs.scores["graph"], nan=0.5))
    assert auc > worst
    assert auc > 0.75


def test_late_fusion_missing_is_not_zero() -> None:
    inputs, y = _toy_inputs()
    model = LateFusion(seed=0).fit(inputs, y)
    row = pd.DataFrame({"tabular": [0.9], "timeseries": [0.8], "vision": [np.nan], "graph": [0.6]})
    row_zero = row.assign(vision=0.0)
    emb = {m: np.zeros((1, 8), dtype=np.float32) for m in row.columns}
    p_missing = model.predict_proba(FusionInput(scores=row, embeddings=emb))[0, 1]
    p_zero = model.predict_proba(FusionInput(scores=row_zero, embeddings=emb))[0, 1]
    # a present-but-zero vision score is strong healthy evidence; a missing
    # one must not be interpreted that way
    assert p_missing != pytest.approx(p_zero, abs=1e-6)


def test_embedding_fusion_fits_and_handles_missing_rows() -> None:
    inputs, y = _toy_inputs()
    model = EmbeddingFusion(epochs=30, seed=0, device="cpu").fit(inputs, y)
    proba = model.predict_proba(inputs)
    assert proba.shape == (len(y), 2)
    assert np.isfinite(proba).all()  # rows with missing vision still predict
    from sklearn.metrics import roc_auc_score

    assert roc_auc_score(y, proba[:, 1]) > 0.7
    fused = model.embed(inputs)
    assert fused.shape == (len(y), model.proj_dim)
    gates = model.gate_weights(inputs)
    np.testing.assert_allclose(gates.sum(axis=1), 1.0, atol=1e-4)
