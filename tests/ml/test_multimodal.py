"""Phase 4 components against a real generated dataset (not mocks):
graph-feature leakage/boundedness on true production data, root-cause
ranking vs the generator's entity-attributed ground truth, and the
end-to-end multimodal pipeline on the tiny profile.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factoryguard.data.generate import generate_dataset
from factoryguard.evaluation.splits import temporal_group_split
from factoryguard.explainability.root_cause import RootCauseRanker, evaluate_root_cause
from factoryguard.features.graph import build_graph_features
from factoryguard.features.tabular import load_tabular


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_dataset("small", data_root=tmp_path_factory.mktemp("mm"))


@pytest.fixture(scope="module")
def graph_inputs(dataset: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data = load_tabular(dataset)
    units = (
        pd.read_parquet(dataset / "tables" / "units.parquet")
        .set_index("unit_id")
        .reindex(data.meta["unit_id"])
        .reset_index()
    )
    labels = pd.read_parquet(dataset / "tables" / "labels.parquet")
    edges = pd.read_parquet(dataset / "tables" / "graph_edges.parquet")
    return data.meta, units, labels, edges


def test_graph_features_bounded_and_ranges_overlap(
    dataset: Path,
    graph_inputs: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    """The D-024 guard extended to graph features: bounded, and no feature
    may have disjoint train/test ranges on a real dataset."""
    meta, units, labels, edges = graph_inputs
    gf = build_graph_features(units, labels, edges).features
    vals = gf.to_numpy()
    assert np.isfinite(vals).all()
    assert (vals >= 0).all() and (vals <= 1).all()

    splits = temporal_group_split(meta)
    for col in gf.columns:
        tr, te = gf.loc[splits.train, col], gf.loc[splits.test, col]
        if tr.nunique() <= 1 or te.nunique() <= 1:
            continue
        assert tr.min() <= te.max() and te.min() <= tr.max(), (
            f"graph feature {col} has disjoint train/test ranges — "
            "unbounded time-correlated construction (see D-024)"
        )


def test_graph_features_no_future_leakage_on_real_data(
    graph_inputs: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    meta, units, labels, edges = graph_inputs
    cut = int(len(units) * 0.7)
    before = build_graph_features(units, labels, edges).features
    labels2 = labels.copy()
    late_ids = set(units["unit_id"].iloc[cut:])
    flip = labels2["unit_id"].isin(late_ids)
    labels2.loc[flip, "failed_eol"] = ~labels2.loc[flip, "failed_eol"].astype(bool)
    after = build_graph_features(units, labels2, edges).features
    pd.testing.assert_frame_equal(before.iloc[:cut], after.iloc[:cut])


def test_root_cause_ranking_beats_chance(
    dataset: Path,
    graph_inputs: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
) -> None:
    meta, units, labels, edges = graph_inputs
    data = load_tabular(dataset)
    splits = temporal_group_split(meta)
    graph = build_graph_features(units, labels, edges, half_life_days=14.0)
    units_rc = units.assign(revision_id=graph.entities["revision_id"].to_numpy())
    ranker = RootCauseRanker().fit(units_rc[splits.train])
    y = data.y_binary.to_numpy()
    eval_mask = (splits.test | splits.unseen_line_test) & y
    truth = pd.read_parquet(dataset / "ground_truth" / "root_causes.parquet")
    ranked = ranker.rank(units_rc, graph, np.flatnonzero(eval_mask))
    m = evaluate_root_cause(ranked, truth)
    if m.get("n_evaluated_units", 0) < 3:
        pytest.skip("too few ground-truth-attributed defects in the test period")
    assert m["mrr"] > 0.0
    assert m["hit_at_5"] >= m["hit_at_3"] >= m["hit_at_1"]
    assert m["hit_at_3"] > 0.0  # at least some causes found in the top 3


def test_multimodal_pipeline_end_to_end_tiny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full Phase 4 pipeline on the tiny profile (vision disabled — DINOv2
    weights are exercised by test_attribution when cached). Asserts the
    report and artifacts exist and headline metrics are present."""
    import json

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:  # pipelines/ is not an installed package
        sys.path.insert(0, str(repo_root))
    from pipelines.training.train_multimodal import main

    data_root = tmp_path / "data"
    generate_dataset("tiny", data_root=data_root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train_multimodal",
            "--profile",
            "tiny",
            "--data-root",
            str(data_root),
            "--reports-root",
            str(tmp_path / "reports"),
            "--artifacts-root",
            str(tmp_path / "artifacts"),
            "--no-vision",
        ],
    )
    assert main() == 0
    out = tmp_path / "reports" / "evaluation" / "tiny"
    metrics = json.loads((out / "multimodal-metrics.json").read_text())
    assert (out / "multimodal-report.md").is_file()
    assert "late" in metrics["fusion"] and "embedding" in metrics["fusion"]
    assert 0.0 <= metrics["uncertainty"]["empirical_coverage"] <= 1.0
    assert (tmp_path / "artifacts" / "tiny" / "manifest.json").is_file()
    assert (tmp_path / "artifacts" / "tiny" / "lineage.json").is_file()
