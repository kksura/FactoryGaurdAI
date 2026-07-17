"""Shared fusion contract (ADR-0006): per-modality scores, embeddings and
availability masks. Missing modality ≠ zero-valued observation, ever —
missingness is carried explicitly as NaN plus a mask and both fusion paths
are required to consume the mask.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MODALITIES = ("tabular", "timeseries", "vision", "graph")


@dataclass
class FusionInput:
    """Row-aligned fusion inputs for one set of units.

    ``scores``: one column per modality of *calibrated* P(defect); NaN
    where the modality is missing for that unit.
    ``embeddings``: modality → (n, d_m) float arrays; rows for units
    missing that modality are all-NaN.
    """

    scores: pd.DataFrame
    embeddings: dict[str, np.ndarray]

    def __post_init__(self) -> None:
        unknown = set(self.scores.columns) - set(MODALITIES)
        if unknown:
            raise ValueError(f"unknown modalities in scores: {unknown}")
        for name, emb in self.embeddings.items():
            if len(emb) != len(self.scores):
                raise ValueError(f"embedding {name} not row-aligned with scores")

    def score_mask(self) -> np.ndarray:
        """(n, M) availability of each score column, in scores-column order."""
        return np.isfinite(self.scores.to_numpy(dtype=float))

    def embedding_mask(self, order: list[str]) -> np.ndarray:
        """(n, M) availability of each embedding (a row is present when it
        contains no NaN)."""
        cols = [np.isfinite(self.embeddings[m]).all(axis=1) for m in order]
        return np.stack(cols, axis=1)
