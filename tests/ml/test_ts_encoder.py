"""1D-CNN TS encoder behaviour on controlled synthetic waveforms.

CPU-forced and small so it runs everywhere (CI is x86 without GPU)."""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from factoryguard.models.timeseries.cnn_encoder import TsCnnEncoder, TsTensor, build_ts_tensor

_L = 64
_N = 300


def _waveforms(seed: int = 0) -> tuple[TsTensor, np.ndarray]:
    """Normal: centered bump. Defective: shifted + widened bump (the same
    physics direction as the real generator's worn-tool signature)."""
    rng = np.random.default_rng(seed)
    y = rng.uniform(size=_N) < 0.35
    t = np.linspace(0, 1, _L)
    vals = np.empty((_N, 2, _L), dtype=np.float32)
    for i in range(_N):
        center = 0.55 if y[i] else 0.45
        width = 0.16 if y[i] else 0.10
        vals[i, 0] = np.exp(-((t - center) ** 2) / (2 * width**2)) + rng.normal(0, 0.03, _L)
        vals[i, 1] = 0.5 + 0.3 * np.sin(np.pi * t) + rng.normal(0, 0.03, _L)
    # sensor dropout on 5% of points
    drop = rng.uniform(size=vals.shape) < 0.05
    vals[drop] = np.nan
    ids = [f"U{i:04d}" for i in range(_N)]
    return TsTensor(unit_ids=ids, values=vals, channels=["force", "aux"]), y


@pytest.fixture(scope="module")
def fitted() -> tuple[TsCnnEncoder, TsTensor, np.ndarray]:
    tensor, y = _waveforms()
    enc = TsCnnEncoder(length=_L, embed_dim=16, epochs=8, batch_size=64, seed=0, device="cpu")
    train = np.arange(0, 200)
    enc.fit(tensor, y[train], sample_index=train)
    return enc, tensor, y


def test_supervised_head_learns(fitted: tuple[TsCnnEncoder, TsTensor, np.ndarray]) -> None:
    enc, tensor, y = fitted
    test = np.arange(200, _N)
    proba = enc.predict_proba(
        TsTensor(tensor.unit_ids[200:], tensor.values[test], tensor.channels)
    )[:, 1]
    assert roc_auc_score(y[test], proba) > 0.8


def test_embeddings_shape_and_finite(fitted: tuple[TsCnnEncoder, TsTensor, np.ndarray]) -> None:
    enc, tensor, _ = fitted
    emb = enc.embed(tensor)
    assert emb.shape == (_N, 16)
    assert np.isfinite(emb).all()  # NaN inputs must never poison embeddings


def test_anomaly_score_flags_distorted_waveforms(
    fitted: tuple[TsCnnEncoder, TsTensor, np.ndarray],
) -> None:
    enc, tensor, _ = fitted
    distorted = tensor.values.copy()
    distorted += np.sin(np.linspace(0, 40, _L)) * 0.8  # far outside training physics
    s_normal = enc.anomaly_score(tensor)
    s_bad = enc.anomaly_score(TsTensor(tensor.unit_ids, distorted, tensor.channels))
    assert s_bad.mean() > s_normal.mean() + 0.2


def test_ssl_pretraining_path_runs() -> None:
    tensor, y = _waveforms(seed=1)
    enc = TsCnnEncoder(
        length=_L,
        embed_dim=16,
        epochs=2,
        ssl_pretrain=True,
        ssl_epochs=2,
        batch_size=64,
        seed=0,
        device="cpu",
    )
    enc.fit(tensor, y)
    assert enc.predict_proba(tensor).shape == (_N, 2)


def test_unsupervised_fit_without_labels() -> None:
    tensor, _ = _waveforms(seed=2)
    enc = TsCnnEncoder(length=_L, embed_dim=16, ssl_epochs=2, batch_size=64, seed=0, device="cpu")
    enc.fit(tensor, None)  # anomaly-only deployments have no labels
    assert enc.anomaly_score(tensor).shape == (_N,)


def test_build_ts_tensor_resamples_and_keeps_nan() -> None:
    frames = []
    for uid, (ch, n) in [
        ("U1", ("force", 32)),
        ("U1", ("aux", 16)),
        ("U2", ("force", 32)),
        ("U2", ("aux", 16)),
    ]:
        v = np.linspace(0, 1, n, dtype=np.float32)
        if uid == "U2" and ch == "force":
            v = v.copy()
            v[5] = np.nan
        frames.append(pd.DataFrame({"unit_id": uid, "channel": ch, "t": range(n), "value": v}))
    tensor = build_ts_tensor(pd.concat(frames, ignore_index=True), length=32)
    assert tensor.values.shape == (2, 2, 32)
    u2 = tensor.unit_ids.index("U2")
    assert np.isnan(tensor.values[u2, tensor.channels.index("force")]).any()
