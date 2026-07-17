"""Learned tabular baselines: prior floor, logistic regression,
HistGradientBoosting (primary, binary + multiclass), isolation forest
(cold-start anomaly, ADR-0019).

All models consume the TabularData feature frame (categories + floats) and
expose sklearn-style fit/predict_proba so evaluation code is uniform.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from factoryguard.features.tabular import CATEGORICAL, NUMERIC


def prior_baseline() -> DummyClassifier:
    """Sanity floor: predicts the empirical class prior."""
    return DummyClassifier(strategy="prior")


def logistic_baseline(seed: int = 0) -> Pipeline:
    return Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        (
                            "cat",
                            OneHotEncoder(handle_unknown="ignore", min_frequency=5),
                            CATEGORICAL,
                        ),
                        (
                            "num",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(strategy="median")),
                                    ("scale", StandardScaler()),
                                ]
                            ),
                            NUMERIC,
                        ),
                    ]
                ),
            ),
            (
                "clf",
                LogisticRegression(max_iter=3000, class_weight="balanced", random_state=seed),
            ),
        ]
    )


class HgbModel:
    """HistGradientBoosting with native categorical handling (primary tabular).

    Works for binary (y: bool) and multiclass (y: str labels).
    """

    def __init__(self, seed: int = 0, multiclass: bool = False) -> None:
        self.name = "hgb_multiclass" if multiclass else "hgb"
        self.multiclass = multiclass
        self.model = HistGradientBoostingClassifier(
            # Regularized against the low positive rate (~4-6%) and several
            # high-cardinality identity categoricals (lot/tool/machine): an
            # unregularized 31-leaf/300-iter model memorizes train-specific
            # category combinations (train AUC ~1.0, test AUC ~chance).
            # Verified on data/medium: test ROC-AUC 0.52-0.57 with this
            # config vs ~0.50 unregularized, matching the achievable ceiling
            # measured via random (non-temporal) cross-validation.
            max_iter=200,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=150,
            l2_regularization=2.0,
            # early stopping uses a stratified holdout, which fails when a
            # defect category has <2 members (tiny profiles) — binary only.
            early_stopping=not multiclass,
            validation_fraction=0.15,
            class_weight="balanced",
            categorical_features=CATEGORICAL,
            random_state=seed,
        )

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> HgbModel:
        self.model.fit(x, y)
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(x)

    @property
    def classes_(self) -> np.ndarray:
        return self.model.classes_


class IsolationForestScorer:
    """Cold-start tabular anomaly scorer: trained on features only (no labels).

    Categorical columns are ordinal-encoded by training-set category codes;
    score is scaled to [0, 1] where higher = more anomalous.
    """

    name = "isolation_forest"

    def __init__(self, seed: int = 0) -> None:
        self.model = IsolationForest(n_estimators=200, contamination="auto", random_state=seed)
        self._categories: dict[str, pd.CategoricalDtype] = {}
        self._range: tuple[float, float] = (0.0, 1.0)

    def _encode(self, x: pd.DataFrame) -> np.ndarray:
        parts = []
        for col in CATEGORICAL:
            dtype = self._categories[col]
            parts.append(x[col].astype(dtype).cat.codes.to_numpy(dtype=float))
        for col in NUMERIC:
            parts.append(np.nan_to_num(x[col].to_numpy(dtype=float)))
        return np.column_stack(parts)

    def fit(self, x: pd.DataFrame) -> IsolationForestScorer:
        self._categories = {
            col: pd.CategoricalDtype(x[col].astype("category").cat.categories)
            for col in CATEGORICAL
        }
        encoded = self._encode(x)
        self.model.fit(encoded)
        raw = -self.model.score_samples(encoded)
        self._range = (float(raw.min()), float(max(raw.max(), raw.min() + 1e-9)))
        return self

    def anomaly_score(self, x: pd.DataFrame) -> np.ndarray:
        raw = -self.model.score_samples(self._encode(x))
        lo, hi = self._range
        return np.clip((raw - lo) / (hi - lo), 0.0, 1.0)
