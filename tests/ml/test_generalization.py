"""Regression test for the tool-wear/temporal-extrapolation bug found during
Phase 3 (2026-07-17): unbounded, ever-increasing wear-derived features
(``days_since_maintenance``, ``tool_age_cycles``) made train/test feature
ranges disjoint, collapsing HGB's temporal-split ROC-AUC to chance even
though random cross-validation showed real signal (~0.55-0.57).

This test would have caught it: it asserts the primary model's temporal
test-period ROC-AUC is not substantially worse than a random-CV estimate of
the achievable ceiling on the same data.
"""

from pathlib import Path

import pytest
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score

from factoryguard.data.generate import generate_dataset
from factoryguard.evaluation.splits import temporal_group_split
from factoryguard.features.tabular import load_tabular
from factoryguard.models.tabular.sklearn_models import HgbModel, logistic_baseline

_MAX_ACCEPTABLE_GAP = 0.08  # ROC-AUC points test may trail the random-CV ceiling


@pytest.fixture(scope="module")
def medium_like_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # `small` is large enough to carry signal and fast enough for CI.
    return generate_dataset("small", data_root=tmp_path_factory.mktemp("gen"))


def test_hgb_temporal_test_auc_near_random_cv_ceiling(medium_like_dataset: Path) -> None:
    data = load_tabular(medium_like_dataset)
    x, y = data.features, data.y_binary.to_numpy()

    ceiling = cross_val_score(
        logistic_baseline(0),
        x,
        y,
        cv=StratifiedKFold(5, shuffle=True, random_state=0),
        scoring="roc_auc",
    ).mean()

    splits = temporal_group_split(data.meta)
    model = HgbModel(seed=0).fit(x[splits.train], y[splits.train])
    proba = model.predict_proba(x[splits.test])[:, 1]
    test_auc = roc_auc_score(y[splits.test], proba)

    assert test_auc >= ceiling - _MAX_ACCEPTABLE_GAP, (
        f"HGB temporal test AUC ({test_auc:.3f}) collapsed relative to the "
        f"random-CV signal ceiling ({ceiling:.3f}) — check for unbounded "
        f"time-correlated features (e.g. an ever-increasing counter that "
        f"never resets) creating disjoint train/test ranges."
    )


def test_no_feature_has_disjoint_train_test_range(medium_like_dataset: Path) -> None:
    """Catches the specific failure mode: a numeric feature whose train-period
    range and test-period range don't overlap at all."""
    from factoryguard.features.tabular import NUMERIC

    data = load_tabular(medium_like_dataset)
    splits = temporal_group_split(data.meta)
    violations = []
    for col in NUMERIC:
        tr = data.features.loc[splits.train, col]
        te = data.features.loc[splits.test, col]
        if te.min() > tr.max() or te.max() < tr.min():
            violations.append(col)
    assert not violations, f"features with disjoint train/test ranges: {violations}"
