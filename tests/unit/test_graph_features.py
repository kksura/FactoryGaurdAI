"""Graph feature pipeline: decay math, temporal cutoffs, label latency,
boundedness (the D-024 regression class)."""

import numpy as np
import pandas as pd

from factoryguard.features.graph import (
    build_graph_features,
    decayed_sum_before,
    graph_prior_scores,
)

_DAY_NS = 86_400 * 10**9


def test_decayed_sum_half_life() -> None:
    events = np.array([0], dtype=np.int64)
    values = np.array([1.0])
    queries = np.array([0, _DAY_NS, 2 * _DAY_NS], dtype=np.int64)
    out = decayed_sum_before(queries, events, values, half_life_days=1.0)
    assert out[0] == 0.0  # strictly before: an event at t doesn't see itself
    np.testing.assert_allclose(out[1:], [0.5, 0.25], rtol=1e-9)


def _mini_dataset(n: int = 12) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t0 = pd.Timestamp("2026-01-01")
    units = pd.DataFrame(
        {
            "unit_id": [f"U{i:03d}" for i in range(n)],
            "produced_at": [t0 + pd.Timedelta(hours=6 * i) for i in range(n)],
            "machine_id": ["M1"] * n,
            "tool_id": ["T1" if i % 2 else "T2" for i in range(n)],
            "operator_id": ["O1"] * n,
            "terminal_lot_id": ["LOT-A"] * (n // 2) + ["LOT-B"] * (n - n // 2),
            "wire_lot_id": ["LOT-W"] * n,
            "line_id": ["L1"] * n,
            "product_id": ["P1"] * n,
            "revision": ["A"] * n,
        }
    )
    labels = pd.DataFrame(
        {
            "unit_id": units["unit_id"],
            "failed_eol": [i in (2, 3) for i in range(n)],
            "labeled_at": units["produced_at"] + pd.Timedelta(hours=1),
        }
    )
    edges = pd.DataFrame(
        {
            "src": ["SUP-1", "SUP-1"],
            "dst": ["LOT-A", "LOT-B"],
            "relation": ["supplier_supplied_lot"] * 2,
            "ts": [None, None],
        }
    )
    return units, labels, edges


def test_features_bounded_and_aligned() -> None:
    units, labels, edges = _mini_dataset()
    gf = build_graph_features(units, labels, edges)
    assert len(gf.features) == len(units)
    vals = gf.features.to_numpy()
    assert np.isfinite(vals).all()
    assert (vals >= 0).all() and (vals <= 1).all()
    assert gf.entities.loc[0, "supplier_id"] == "SUP-1"


def test_no_future_leakage() -> None:
    """Mutating labels of *later* units must not change features of earlier
    units — the strict temporal cutoff property."""
    units, labels, edges = _mini_dataset()
    before = build_graph_features(units, labels, edges).features
    labels2 = labels.copy()
    labels2.loc[8:, "failed_eol"] = True  # corrupt the future
    after = build_graph_features(units, labels2, edges).features
    pd.testing.assert_frame_equal(before.iloc[:8], after.iloc[:8])


def test_label_latency_respected() -> None:
    """A defect only becomes evidence once labeled: a defect labeled after
    the next unit's production time must not appear in its features."""
    units, labels, edges = _mini_dataset()
    labels_late = labels.copy()
    # defect at index 2, but the label arrives 5 days later
    labels_late.loc[2, "labeled_at"] = units.loc[2, "produced_at"] + pd.Timedelta(days=5)
    gf_prompt = build_graph_features(units, labels, edges).features
    gf_late = build_graph_features(units, labels_late, edges).features
    col = "g_machine_id_defect_rate"
    # unit 3 (produced 6h later) saw the defect when labels were prompt…
    assert gf_prompt.loc[3, col] > gf_late.loc[3, col]


def test_rates_react_to_defects() -> None:
    units, labels, edges = _mini_dataset()
    gf = build_graph_features(units, labels, edges).features
    # after the two defects (idx 2,3) the machine rate must rise
    assert gf.loc[5, "g_machine_id_defect_rate"] > gf.loc[1, "g_machine_id_defect_rate"]


def test_graph_prior_is_label_free_and_propagates() -> None:
    units, labels, edges = _mini_dataset()
    gf = build_graph_features(units, labels, edges)
    scores = np.zeros(len(units))
    scores[2:4] = 1.0  # two anomalous-looking units early on
    prior = graph_prior_scores(units, gf.entities, scores)
    assert prior.shape == (len(units),)
    assert np.isfinite(prior).all()
    # later units on the same machine inherit elevated risk vs the very first
    assert prior[5] > prior[0]
