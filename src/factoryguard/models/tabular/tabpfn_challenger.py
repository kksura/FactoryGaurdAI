"""TabPFN v2 challenger (ADR-0021). Config-switched, strictly optional.

``try_build`` checks explicit preconditions (data size, licensing,
dependency availability) *before* attempting to build the model and
returns a structured skip reason for each gate, rather than relying on a
blanket try/except to discover failures after the fact (tightened per
review feedback, 2026-07-17).
"""

from __future__ import annotations

import importlib.util
import logging
import os

import numpy as np
import pandas as pd

from factoryguard.features.tabular import CATEGORICAL, NUMERIC

log = logging.getLogger(__name__)

# TabPFN is designed for modest table sizes; cap training rows by recency.
_MAX_TRAIN_ROWS = 10_000
_MIN_TRAIN_ROWS = 20
# Rows beyond which CPU inference latency becomes impractical for this demo.
_MAX_ROWS_CPU_ONLY = 50_000


class TabPfnChallenger:
    name = "tabpfn"

    def __init__(self, seed: int = 0, device: str | None = None) -> None:
        import torch
        from tabpfn import TabPFNClassifier  # deferred import — optional dep

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = TabPFNClassifier(device=self.device, random_state=seed)
        self._categories: dict[str, pd.CategoricalDtype] = {}

    def _encode(self, x: pd.DataFrame) -> np.ndarray:
        parts = []
        for col in CATEGORICAL:
            dtype = self._categories[col]
            parts.append(x[col].astype(dtype).cat.codes.to_numpy(dtype=float))
        for col in NUMERIC:
            parts.append(x[col].to_numpy(dtype=float))
        return np.column_stack(parts)

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> TabPfnChallenger:
        if len(x) > _MAX_TRAIN_ROWS:  # keep the most recent rows (frame is time-ordered)
            x = x.iloc[-_MAX_TRAIN_ROWS:]
            y = np.asarray(y)[-_MAX_TRAIN_ROWS:]
        self._categories = {
            col: pd.CategoricalDtype(x[col].astype("category").cat.categories)
            for col in CATEGORICAL
        }
        self.model.fit(self._encode(x), np.asarray(y))
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self._encode(x))


def check_gates(n_train_rows: int) -> str | None:
    """Return a skip reason if any explicit precondition fails, else None."""
    if importlib.util.find_spec("tabpfn") is None:
        return "dependency not installed (pip install -r requirements/challenger.txt)"
    if n_train_rows < _MIN_TRAIN_ROWS:
        return f"training set too small ({n_train_rows} < {_MIN_TRAIN_ROWS} rows)"
    try:
        import torch
    except ImportError:
        return "torch not installed"
    if n_train_rows > _MAX_ROWS_CPU_ONLY and not torch.cuda.is_available():
        return (
            f"training set too large for CPU inference "
            f"({n_train_rows} > {_MAX_ROWS_CPU_ONLY} rows, no CUDA device)"
        )
    if not os.environ.get("TABPFN_TOKEN"):
        return (
            "TABPFN_TOKEN not set — one-time free license acceptance required "
            "at https://ux.priorlabs.ai (see requirements/challenger.txt)"
        )
    return None


def try_build(seed: int = 0, n_train_rows: int = 0) -> tuple[TabPfnChallenger | None, str | None]:
    """Build the challenger after checking explicit gates.

    Returns ``(model, None)`` on success or ``(None, reason)`` when any gate
    fails or construction still raises (e.g. a transient download error) —
    callers must record the reason rather than silently skipping.
    """
    gate_reason = check_gates(n_train_rows)
    if gate_reason is not None:
        log.info("TabPFN challenger skipped: %s", gate_reason)
        return None, gate_reason
    try:
        return TabPfnChallenger(seed=seed), None
    except Exception as exc:  # e.g. transient download/network error
        reason = f"construction failed: {exc}"[:300]
        log.warning("TabPFN challenger unavailable: %s", reason)
        return None, reason
