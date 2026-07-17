"""Similar-incident retrieval (spec §10; ADR-0021: in-process exact
search over the incident embeddings — dataset scales make a vector DB
pure overhead, and exact search has no recall loss to explain away).

The index stores embeddings of historical *defective* units with their
metadata; a query returns the nearest incidents with distances, feeding
the "similar cases" section of explanations and the report's retrieval
precision metric (same defect category as the query's true category).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_EPS = 1e-9


class SimilarIncidentIndex:
    name = "similar_incidents"

    def __init__(self, metric: str = "cosine") -> None:
        if metric not in ("cosine", "l2"):
            raise ValueError("metric must be 'cosine' or 'l2'")
        self.metric = metric
        self._emb: np.ndarray | None = None
        self._meta: pd.DataFrame | None = None

    def fit(self, embeddings: np.ndarray, meta: pd.DataFrame) -> SimilarIncidentIndex:
        """``meta`` must include unit_id, defect_category, produced_at and be
        row-aligned with ``embeddings``. Rows with non-finite embeddings
        (missing modality) are dropped from the index."""
        emb = np.asarray(embeddings, dtype=np.float32)
        if len(emb) != len(meta):
            raise ValueError("embeddings and meta are not row-aligned")
        ok = np.asarray(np.isfinite(emb).all(axis=1), dtype=bool)
        emb = emb[ok]
        if self.metric == "cosine":
            emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + _EPS)
        self._emb = emb
        self._meta = meta.loc[ok].reset_index(drop=True)
        return self

    def query(self, embeddings: np.ndarray, k: int = 5) -> list[pd.DataFrame]:
        """Per query row: a frame of the k nearest incidents (unit_id,
        defect_category, produced_at, distance), nearest first. Non-finite
        query rows return an empty frame."""
        assert self._emb is not None and self._meta is not None, "fit() first"
        q = np.asarray(embeddings, dtype=np.float32)
        k = min(k, len(self._emb))
        results: list[pd.DataFrame] = []
        finite = np.asarray(np.isfinite(q).all(axis=1), dtype=bool)
        if self.metric == "cosine":
            qn = q / (np.linalg.norm(q, axis=1, keepdims=True) + _EPS)
            dist_all = 1.0 - qn @ self._emb.T
        else:
            dist_all = (
                np.sum(q**2, axis=1, keepdims=True)
                - 2.0 * q @ self._emb.T
                + np.sum(self._emb**2, axis=1)
            )
            dist_all = np.sqrt(np.maximum(dist_all, 0.0))
        for i in range(len(q)):
            if not finite[i] or k == 0:
                results.append(self._meta.iloc[0:0].assign(distance=np.zeros(0)))
                continue
            idx = np.argsort(dist_all[i], kind="stable")[:k]
            hit = self._meta.iloc[idx].copy()
            hit["distance"] = dist_all[i][idx].astype(float)
            results.append(hit.reset_index(drop=True))
        return results

    def precision_at_k(
        self, embeddings: np.ndarray, true_categories: np.ndarray, k: int = 5
    ) -> float:
        """Mean fraction of retrieved incidents sharing the query's true
        defect category — the report's retrieval-quality number."""
        hits = self.query(embeddings, k=k)
        cats = np.asarray(true_categories, dtype=object)
        fracs = [
            float((h["defect_category"].to_numpy() == cats[i]).mean())
            for i, h in enumerate(hits)
            if len(h)
        ]
        return float(np.mean(fracs)) if fracs else float("nan")
