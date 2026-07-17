"""Graph-derived per-unit features with strict temporal cutoffs (ADR-0007).

Every feature answers "what did this unit's neighborhood look like *before*
this unit was produced?" — computed with exponentially time-decayed sums so
no feature grows monotonically over the simulated date range (the exact
failure mode that collapsed temporal generalization in Phase 3, D-024):

- entity defect *rates* (decayed defects / decayed exposure, EB-smoothed
  toward the concurrent global rate) — bounded [0, 1];
- entity *support* (how much decayed evidence exists) — bounded [0, 1);
- machine/tool defect *centrality* (entity share of all decayed defects)
  — bounded [0, 1];
- supplier-lot risk: the unit's terminal lot inherits its supplier's decayed
  defect rate, resolved through the typed edge list with NetworkX.

Leakage rules:
- exposure events use ``produced_at`` (a unit is known to exist once built);
- defect evidence uses ``labeled_at`` (a defect is only usable evidence
  once the EOL label exists — assumption A14 label latency);
- both enter a unit's features only with event time strictly before that
  unit's ``produced_at``.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

GRAPH_FEATURE_VERSION = "graph-v1"

# Entity columns ranked (with derived columns added by _entity_frame).
ENTITY_COLUMNS = [
    "machine_id",
    "tool_id",
    "operator_id",
    "terminal_lot_id",
    "wire_lot_id",
    "revision_id",
    "line_id",
    "supplier_id",
]
_CENTRALITY_ENTITIES = ("machine_id", "tool_id")


def decayed_sum_before(
    query_times: np.ndarray,
    event_times: np.ndarray,
    event_values: np.ndarray,
    half_life_days: float,
) -> np.ndarray:
    """Exponentially decayed sum of events *strictly before* each query time.

    ``query_times`` must be sorted ascending; events may be in any order.
    Times are int64 nanoseconds. Runs in O(n log n).
    """
    order = np.argsort(event_times, kind="stable")
    ev_t = event_times[order].astype(np.float64)
    ev_v = event_values[order].astype(np.float64)
    lam = np.log(2.0) / (half_life_days * 86_400e9)  # decay rate per ns

    out = np.zeros(len(query_times), dtype=np.float64)
    acc = 0.0
    last_t = ev_t[0] if len(ev_t) else 0.0
    j = 0
    for i, qt in enumerate(query_times.astype(np.float64)):
        while j < len(ev_t) and ev_t[j] < qt:
            acc = acc * np.exp(-lam * (ev_t[j] - last_t)) + ev_v[j]
            last_t = ev_t[j]
            j += 1
        out[i] = acc * np.exp(-lam * (qt - last_t)) if j > 0 else 0.0
    return out


def _lot_to_supplier(edges: pd.DataFrame) -> dict[str, str]:
    """Resolve lot → supplier through the typed edge list (NetworkX)."""
    g = nx.DiGraph()
    for r in edges[edges.relation == "supplier_supplied_lot"].itertuples():
        g.add_edge(str(r.src), str(r.dst), relation=r.relation)
    return {lot: supplier for supplier, lot in g.edges()}


def _entity_frame(units: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """Unit-aligned frame of entity ids, including derived columns."""
    ent = units[
        ["machine_id", "tool_id", "operator_id", "terminal_lot_id", "wire_lot_id", "line_id"]
    ].astype(str)
    ent["revision_id"] = units["product_id"].astype(str) + ":" + units["revision"].astype(str)
    supplier_of = _lot_to_supplier(edges)
    ent["supplier_id"] = ent["terminal_lot_id"].map(supplier_of).fillna("UNKNOWN")
    return ent


def _group_positions(entity: pd.Series) -> list[np.ndarray]:
    """Positional (iloc) index arrays for each entity-value group."""
    flat = entity.reset_index(drop=True)
    return [
        np.asarray(idx, dtype=np.int64) for idx in flat.groupby(flat, observed=True).groups.values()
    ]


@dataclass
class GraphFeatures:
    """Row-aligned with the input units frame."""

    features: pd.DataFrame
    entities: pd.DataFrame  # unit-aligned entity ids (incl. derived revision/supplier)
    half_life_days: float


def _per_entity_decayed(
    entity: pd.Series,
    produced_ns: np.ndarray,
    labeled_ns: np.ndarray,
    defective: np.ndarray,
    half_life_days: float,
) -> tuple[np.ndarray, np.ndarray]:
    """(decayed_defects, decayed_exposure) at each unit's production time,
    over that unit's entity group only. Input arrays are unit-aligned and
    must be sorted by ``produced_ns``."""
    defects = np.zeros(len(entity), dtype=np.float64)
    exposure = np.zeros(len(entity), dtype=np.float64)
    for pos in _group_positions(entity):
        q = produced_ns[pos]
        exposure[pos] = decayed_sum_before(q, q, np.ones(len(pos)), half_life_days)
        defects[pos] = decayed_sum_before(
            q, labeled_ns[pos], defective[pos].astype(np.float64), half_life_days
        )
    return defects, exposure


def build_graph_features(
    units: pd.DataFrame,
    labels: pd.DataFrame,
    edges: pd.DataFrame,
    half_life_days: float = 7.0,
    smoothing: float = 25.0,
) -> GraphFeatures:
    """Compute per-unit graph features. ``units`` must be sorted by
    ``produced_at`` (the tabular loader already guarantees this)."""
    if not units["produced_at"].is_monotonic_increasing:
        raise ValueError("units must be sorted by produced_at")

    lab = labels.set_index("unit_id")
    aligned = lab.reindex(units["unit_id"])
    defective = aligned["failed_eol"].fillna(False).to_numpy(dtype=bool)
    produced_ns = units["produced_at"].astype("int64").to_numpy()
    labeled_at = pd.to_datetime(aligned["labeled_at"]).fillna(units["produced_at"].iloc[-1])
    labeled_ns = labeled_at.astype("int64").to_numpy()

    entities = _entity_frame(units, edges)

    # Concurrent global decayed rate = the EB prior every entity shrinks toward.
    g_defects = decayed_sum_before(
        produced_ns, labeled_ns, defective.astype(np.float64), half_life_days
    )
    g_exposure = decayed_sum_before(produced_ns, produced_ns, np.ones(len(units)), half_life_days)
    global_rate = (g_defects + 1.0) / (g_exposure + 20.0)  # weak fixed prior at start

    feats: dict[str, np.ndarray] = {}
    for col in ENTITY_COLUMNS:
        defects, exposure = _per_entity_decayed(
            entities[col], produced_ns, labeled_ns, defective, half_life_days
        )
        rate = (defects + smoothing * global_rate) / (exposure + smoothing)
        feats[f"g_{col}_defect_rate"] = rate
        feats[f"g_{col}_support"] = exposure / (exposure + smoothing)
        if col in _CENTRALITY_ENTITIES:
            feats[f"g_{col}_centrality"] = defects / (g_defects + 1.0)

    features = pd.DataFrame(feats, index=units.index).astype(float).clip(0.0, 1.0)
    return GraphFeatures(features=features, entities=entities, half_life_days=half_life_days)


def graph_prior_scores(
    units: pd.DataFrame,
    entities: pd.DataFrame,
    base_scores: np.ndarray,
    half_life_days: float = 7.0,
    smoothing: float = 25.0,
    entity_cols: tuple[str, ...] = ("machine_id", "tool_id", "terminal_lot_id", "supplier_id"),
) -> np.ndarray:
    """Label-free cold-start graph prior (ADR-0019, deferred from Phase 3).

    Propagates an unsupervised anomaly score through shared entities: each
    unit's prior is the mean of its entities' decayed average anomaly score
    among strictly-earlier neighbor units. High values mean "this unit's
    tool/machine/lot recently produced anomalous-looking units", using no
    labels anywhere. Returned as a relative risk score (AnomalyScorer
    semantics — rank-evaluated only).
    """
    produced_ns = units["produced_at"].astype("int64").to_numpy()
    scores = np.asarray(base_scores, dtype=np.float64)
    global_mean = float(np.nanmean(scores)) if len(scores) else 0.0
    filled = np.where(np.isfinite(scores), scores, global_mean)

    per_entity: list[np.ndarray] = []
    for col in entity_cols:
        val = np.zeros(len(units), dtype=np.float64)
        den = np.zeros(len(units), dtype=np.float64)
        for pos in _group_positions(entities[col]):
            q = produced_ns[pos]
            # anomaly scores are available at production time (no label latency)
            val[pos] = decayed_sum_before(q, q, filled[pos], half_life_days)
            den[pos] = decayed_sum_before(q, q, np.ones(len(pos)), half_life_days)
        per_entity.append((val + smoothing * global_mean) / (den + smoothing))
    return np.mean(np.stack(per_entity, axis=0), axis=0)
