"""Leakage-safety tests for temporal + group-aware splitting (spec §9).

These run against a real generated dataset (not synthetic mocks) so they
exercise the same code path the training pipeline uses.
"""

from pathlib import Path

import pytest

from factoryguard.data.generate import generate_dataset
from factoryguard.evaluation.splits import assert_no_leakage, temporal_group_split
from factoryguard.features.tabular import FORBIDDEN_IN_FEATURES, load_tabular


@pytest.fixture(scope="module")
def small_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_dataset("small", data_root=tmp_path_factory.mktemp("ml"))


def test_no_leakage_on_real_dataset(small_dataset: Path) -> None:
    data = load_tabular(small_dataset)
    splits = temporal_group_split(data.meta)
    assert_no_leakage(data.meta, splits)  # raises AssertionError on violation


def test_splits_are_non_trivial(small_dataset: Path) -> None:
    data = load_tabular(small_dataset)
    splits = temporal_group_split(data.meta)
    for name, mask in splits.named().items():
        assert mask.sum() > 0, f"{name} split is empty"
    assert splits.train.sum() > splits.test.sum()  # train is the majority period


def test_work_order_never_split_across_periods(small_dataset: Path) -> None:
    data = load_tabular(small_dataset)
    splits = temporal_group_split(data.meta)
    named = splits.named()
    for wo, grp in data.meta.groupby("work_order_id"):
        idx = grp.index.to_numpy()
        memberships = {name for name, mask in named.items() if mask[idx].any()}
        assert len(memberships) <= 1, f"{wo} appears in {memberships}"


def test_unseen_line_fully_excluded_from_training_splits(small_dataset: Path) -> None:
    data = load_tabular(small_dataset)
    splits = temporal_group_split(data.meta)
    if not splits.unseen_line:
        pytest.skip("dataset too small for an unseen-line holdout")
    for name in ("train", "val", "calib", "test"):
        mask = splits.named()[name]
        assert (data.meta.loc[mask, "line_id"] != splits.unseen_line).all()


def test_feature_frame_excludes_labels_and_identifiers(small_dataset: Path) -> None:
    data = load_tabular(small_dataset)
    assert not (set(data.features.columns) & FORBIDDEN_IN_FEATURES)


def test_temporal_boundaries_are_monotonic(small_dataset: Path) -> None:
    """Work-order *median* time is strictly ordered across splits — this is
    the actual guarantee (raw per-unit timestamps may interleave slightly at
    a boundary since multiple lines run in parallel with independent clocks).
    """
    data = load_tabular(small_dataset)
    splits = temporal_group_split(data.meta)
    named = splits.named()
    prev_end = None
    for name in ("train", "val", "calib", "test"):
        mask = named[name]
        if mask.sum() == 0:
            continue
        wos = data.meta.loc[mask, "work_order_id"].unique()
        medians = (
            data.meta[data.meta.work_order_id.isin(wos)]
            .groupby("work_order_id")["produced_at"]
            .median()
        )
        if prev_end is not None:
            assert medians.min() >= prev_end
        prev_end = medians.max()
