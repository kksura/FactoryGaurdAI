"""Similar-incident retrieval: exact search, ADR-0021."""

import numpy as np
import pandas as pd

from factoryguard.inference.retrieval import SimilarIncidentIndex


def _clustered() -> tuple[np.ndarray, pd.DataFrame]:
    rng = np.random.default_rng(0)
    a = rng.normal(0, 0.1, (20, 6)) + np.array([1, 0, 0, 0, 0, 0])
    b = rng.normal(0, 0.1, (20, 6)) + np.array([0, 1, 0, 0, 0, 0])
    emb = np.vstack([a, b]).astype(np.float32)
    meta = pd.DataFrame(
        {
            "unit_id": [f"U{i}" for i in range(40)],
            "defect_category": ["crimp"] * 20 + ["seal"] * 20,
            "produced_at": pd.date_range("2026-01-01", periods=40, freq="h"),
        }
    )
    return emb, meta


def test_query_returns_sorted_neighbors_with_metadata() -> None:
    emb, meta = _clustered()
    index = SimilarIncidentIndex().fit(emb, meta)
    hits = index.query(emb[:2], k=3)
    assert len(hits) == 2
    for h in hits:
        assert list(h.columns[-1:]) == ["distance"]
        assert (np.diff(h["distance"]) >= -1e-9).all()
        assert set(h["defect_category"]) == {"crimp"}


def test_precision_at_k_on_separable_clusters() -> None:
    emb, meta = _clustered()
    index = SimilarIncidentIndex().fit(emb, meta)
    cats = meta["defect_category"].to_numpy()
    assert index.precision_at_k(emb, cats, k=5) == 1.0


def test_nan_rows_are_skipped() -> None:
    emb, meta = _clustered()
    emb_bad = emb.copy()
    emb_bad[5] = np.nan
    index = SimilarIncidentIndex().fit(emb_bad, meta)
    assert len(index._meta) == 39  # NaN row dropped from the index
    hits = index.query(np.full((1, 6), np.nan), k=3)
    assert len(hits[0]) == 0  # NaN query → empty result, not garbage
