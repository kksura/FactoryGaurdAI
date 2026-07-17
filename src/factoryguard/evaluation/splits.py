"""Temporal + group-aware splitting (spec §9).

Splits are strictly by time — train → validation → calibration → test —
with two group guards:

1. Work orders never straddle a boundary: each work order is assigned to
   the split containing its median production timestamp, so consecutive
   near-identical units cannot appear on both sides.
2. An unseen-line holdout is carved from the *test period only*: units of
   one designated line are excluded from train/val/calib entirely and
   reported separately.

Leakage tests in ``tests/ml`` assert these properties on real datasets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_FRACTIONS = {"train": 0.55, "val": 0.15, "calib": 0.15, "test": 0.15}


@dataclass
class Splits:
    """Boolean masks over the row index of the aligned feature/meta frames."""

    train: np.ndarray
    val: np.ndarray
    calib: np.ndarray
    test: np.ndarray
    unseen_line_test: np.ndarray
    unseen_line: str
    boundaries: dict[str, pd.Timestamp] = field(default_factory=dict)

    def named(self) -> dict[str, np.ndarray]:
        return {
            "train": self.train,
            "val": self.val,
            "calib": self.calib,
            "test": self.test,
            "unseen_line_test": self.unseen_line_test,
        }


def temporal_group_split(
    meta: pd.DataFrame,
    fractions: dict[str, float] | None = None,
    unseen_line: str | None = None,
) -> Splits:
    """Split by work-order median time into contiguous periods.

    ``meta`` must have columns unit_id, work_order_id, line_id, produced_at
    and be row-aligned with the feature frame.
    """
    fractions = fractions or DEFAULT_FRACTIONS
    if abs(sum(fractions.values()) - 1.0) > 1e-9:
        raise ValueError("split fractions must sum to 1")

    wo_time = meta.groupby("work_order_id")["produced_at"].median().sort_values()
    n = len(wo_time)
    if n < 8:
        raise ValueError(f"need at least 8 work orders to split, have {n}")

    cuts: dict[str, pd.Timestamp] = {}
    order = ["train", "val", "calib", "test"]
    cum = 0.0
    idx: dict[str, set[str]] = {}
    prev = 0
    for name in order:
        cum += fractions[name]
        upto = n if name == order[-1] else max(prev + 1, int(round(cum * n)))
        idx[name] = set(wo_time.index[prev:upto])
        if upto < n:
            cuts[name] = wo_time.iloc[upto - 1]
        prev = upto

    wo_of_row = meta["work_order_id"]
    masks = {name: wo_of_row.isin(wos).to_numpy() for name, wos in idx.items()}

    # Unseen-line holdout: pick the *minority* line of the test period so the
    # main test set survives; skip the holdout entirely when the dataset is
    # too small to afford one (test would drop below min_test_units).
    test_lines = meta.loc[masks["test"], "line_id"]
    if len(test_lines) == 0:
        raise ValueError("empty test split")
    min_test_units = 10
    if unseen_line is None:
        counts = test_lines.value_counts()
        candidate = str(counts.idxmin()) if len(counts) > 1 else None
        if candidate is not None:
            remaining = int((test_lines != candidate).sum())
            unseen_line = candidate if remaining >= min_test_units else None

    if unseen_line is None:
        unseen_line = ""  # holdout disabled (dataset too small / single line)
        unseen_line_test = np.zeros(len(meta), dtype=bool)
    else:
        is_unseen = (meta["line_id"] == unseen_line).to_numpy()
        unseen_line_test = masks["test"] & is_unseen
        for name in ("train", "val", "calib", "test"):
            masks[name] = masks[name] & ~is_unseen

    return Splits(
        train=masks["train"],
        val=masks["val"],
        calib=masks["calib"],
        test=masks["test"],
        unseen_line_test=unseen_line_test,
        unseen_line=unseen_line,
        boundaries=cuts,
    )


def assert_no_leakage(meta: pd.DataFrame, splits: Splits) -> None:
    """Raise AssertionError on any leakage property violation (used by tests
    and defensively by the training pipeline)."""
    named = splits.named()
    # disjoint
    total = np.zeros(len(meta), dtype=int)
    for mask in named.values():
        total += mask.astype(int)
    assert total.max() <= 1, "unit assigned to more than one split"
    # work orders do not straddle
    for wo, grp in meta.groupby("work_order_id"):
        memberships = {name for name, mask in named.items() if mask[grp.index.to_numpy()].any()}
        assert len(memberships) <= 1, f"work order {wo} straddles splits {memberships}"

    # temporal order at work-order granularity
    def wo_span(mask: np.ndarray) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        wos = meta.loc[mask, "work_order_id"].unique()
        if len(wos) == 0:
            return None
        med = meta[meta.work_order_id.isin(wos)].groupby("work_order_id")["produced_at"].median()
        return med.min(), med.max()

    prev_max = None
    for name in ("train", "val", "calib", "test"):
        span = wo_span(named[name])
        if span is None:
            continue
        if prev_max is not None:
            assert span[0] >= prev_max, f"{name} begins before previous split ends"
        prev_max = span[1]
    # unseen line truly unseen (when the holdout is enabled)
    if splits.unseen_line:
        for name in ("train", "val", "calib", "test"):
            assert (meta.loc[named[name], "line_id"] != splits.unseen_line).all(), (
                f"unseen line leaked into {name}"
            )
