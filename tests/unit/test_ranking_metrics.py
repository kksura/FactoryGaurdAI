"""Ranking metrics used by root-cause evaluation (spec §9)."""

import numpy as np
import pytest

from factoryguard.evaluation.metrics import aggregate_rankings, ranking_metrics


def test_hand_computed_case() -> None:
    m = ranking_metrics(["a", "b", "c"], {"b": 1.0}, ks=(1, 3))
    assert m["mrr"] == 0.5
    assert m["hit_at_1"] == 0.0 and m["hit_at_3"] == 1.0
    assert m["recall_at_1"] == 0.0 and m["recall_at_3"] == 1.0
    assert m["ndcg_at_3"] == pytest.approx(1.0 / np.log2(3))


def test_graded_relevance_orders_ndcg() -> None:
    rel = {"strong": 2.0, "weak": 0.5}
    good = ranking_metrics(["strong", "weak", "x"], rel, ks=(3,))
    bad = ranking_metrics(["weak", "strong", "x"], rel, ks=(3,))
    assert good["ndcg_at_3"] > bad["ndcg_at_3"]
    assert good["ndcg_at_3"] == pytest.approx(1.0)


def test_no_relevant_found() -> None:
    m = ranking_metrics(["a", "b"], {"z": 1.0}, ks=(1,))
    assert m["mrr"] == 0.0 and m["hit_at_1"] == 0.0


def test_aggregate_is_nan_aware_mean() -> None:
    q1 = ranking_metrics(["a"], {"a": 1.0}, ks=(1,))
    q2 = ranking_metrics(["b"], {"a": 1.0}, ks=(1,))
    agg = aggregate_rankings([q1, q2])
    assert agg["mrr"] == 0.5
    assert aggregate_rankings([]) == {}
