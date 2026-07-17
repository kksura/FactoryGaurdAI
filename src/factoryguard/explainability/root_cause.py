"""Root-cause candidate ranking (spec §10; evaluated vs generator truth).

For a flagged unit, the candidates are the entities that unit actually
touched (tool, machine, material lots, revision, operator, line, plant,
work order). Each is scored by two bounded signals:

1. *history*: the entity's time-decayed, EB-smoothed defect rate at the
   unit's production time (from the graph feature pipeline — strictly
   pre-cutoff evidence), expressed relative to the concurrent global rate;
2. *evidence*: mechanism-specific measurements on the unit itself (tool
   wear percentile for tools, crimp-height deviation for machines, pull
   force for lots, humidity for plants, changeover recency for work
   orders), percentile-ranked against the *training period* only.

Scores rank hypotheses for an investigator — the report is explicit that
this is statistical association plus engineered priors, not causal proof
(spec §10). Evaluation compares rankings against the synthetic generator's
entity-attributed ground truth (``ground_truth/root_causes.parquet``) with
Recall@K, MRR, NDCG@K and top-1/top-3 accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from factoryguard.evaluation.metrics import aggregate_rankings, ranking_metrics
from factoryguard.features.graph import GraphFeatures

_HISTORY_WEIGHT = 0.6
_EVIDENCE_WEIGHT = 0.4
_NEUTRAL = 0.5

# candidate entity_type → (units column with the id, graph-feature entity col)
_CANDIDATES: dict[str, tuple[str, str | None]] = {
    "tool": ("tool_id", "tool_id"),
    "machine": ("machine_id", "machine_id"),
    "material_lot": ("terminal_lot_id", "terminal_lot_id"),
    "material_lot_wire": ("wire_lot_id", "wire_lot_id"),
    "revision": ("revision_id", "revision_id"),
    "operator": ("operator_id", "operator_id"),
    "line": ("line_id", "line_id"),
    "plant": ("plant_id", None),
    "work_order": ("work_order_id", None),
}
# both lot columns report as entity_type "material_lot" in rankings
_TYPE_ALIAS = {"material_lot_wire": "material_lot"}


class _PercentileRank:
    """Percentile transform frozen on training-period values (bounded [0,1],
    immune to the unbounded-monotonic-feature failure mode, D-024)."""

    def __init__(self, train_values: np.ndarray) -> None:
        v = np.asarray(train_values, dtype=np.float64)
        self._sorted = np.sort(v[np.isfinite(v)])

    def __call__(self, values: np.ndarray) -> np.ndarray:
        v = np.asarray(values, dtype=np.float64)
        if len(self._sorted) == 0:
            return np.full(len(v), _NEUTRAL)
        pct = np.searchsorted(self._sorted, v, side="right") / len(self._sorted)
        return np.where(np.isfinite(v), pct, _NEUTRAL)


@dataclass
class RankedCauses:
    """Per-unit ranked candidate table: entity_type, entity_id, score,
    history, evidence — sorted best-first."""

    per_unit: dict[str, pd.DataFrame]


class RootCauseRanker:
    def fit(self, units_train: pd.DataFrame) -> RootCauseRanker:
        dev = (units_train["crimp_height_mm"] - units_train["crimp_height_setpoint_mm"]).abs()
        self._wear = _PercentileRank(units_train["tool_age_cycles"].to_numpy())
        self._dev = _PercentileRank(dev.to_numpy())
        self._pull = _PercentileRank(units_train["pull_force_n"].to_numpy())
        hum_med = float(units_train["humidity_pct"].median())
        self._hum_med = hum_med
        self._hum = _PercentileRank((units_train["humidity_pct"] - hum_med).abs().to_numpy())
        self._chg = _PercentileRank(units_train["units_since_changeover"].to_numpy())
        return self

    def _evidence(self, units: pd.DataFrame) -> dict[str, np.ndarray]:
        """Per-entity-type mechanism evidence in [0, 1] (0.5 = uninformative)."""
        dev = (units["crimp_height_mm"] - units["crimp_height_setpoint_mm"]).abs().to_numpy()
        neutral = np.full(len(units), _NEUTRAL)
        return {
            "tool": self._wear(units["tool_age_cycles"].to_numpy()),
            "machine": self._dev(dev),
            "material_lot": 1.0 - self._pull(units["pull_force_n"].to_numpy()),
            "material_lot_wire": 1.0 - self._pull(units["pull_force_n"].to_numpy()),
            "revision": neutral,
            "operator": neutral,
            "line": neutral,
            "plant": self._hum((units["humidity_pct"] - self._hum_med).abs().to_numpy()),
            "work_order": 1.0 - self._chg(units["units_since_changeover"].to_numpy()),
        }

    def rank(
        self,
        units: pd.DataFrame,
        graph: GraphFeatures,
        row_positions: np.ndarray,
    ) -> RankedCauses:
        """Rank candidates for the units at ``row_positions`` (positional
        indices into the row-aligned ``units``/``graph`` frames)."""
        evidence = self._evidence(units)
        gf = graph.features.reset_index(drop=True)
        entities = graph.entities.reset_index(drop=True)
        units_flat = units.reset_index(drop=True)
        global_rate = np.nanmean(
            gf[[c for c in gf.columns if c.endswith("_defect_rate")]].to_numpy()
        )

        per_unit: dict[str, pd.DataFrame] = {}
        for pos in row_positions:
            rows = []
            for ctype, (unit_col, gcol) in _CANDIDATES.items():
                if unit_col in units_flat.columns:
                    entity_id = units_flat.at[pos, unit_col]
                elif unit_col in entities.columns:
                    entity_id = entities.at[pos, unit_col]
                else:
                    continue
                if entity_id is None or (isinstance(entity_id, float) and np.isnan(entity_id)):
                    continue
                if gcol is not None and f"g_{gcol}_defect_rate" in gf.columns:
                    rate = float(cast(float, gf.at[pos, f"g_{gcol}_defect_rate"]))
                    history = rate / (rate + global_rate + 1e-9)  # 0.5 = at prior
                else:
                    history = _NEUTRAL
                ev = float(evidence[ctype][pos])
                rows.append(
                    {
                        "entity_type": _TYPE_ALIAS.get(ctype, ctype),
                        "entity_id": str(entity_id),
                        "score": _HISTORY_WEIGHT * history + _EVIDENCE_WEIGHT * ev,
                        "history": history,
                        "evidence": ev,
                    }
                )
            frame = (
                pd.DataFrame(rows)
                .sort_values("score", ascending=False, kind="stable")
                .reset_index(drop=True)
            )
            per_unit[str(units_flat.at[pos, "unit_id"])] = frame
        return RankedCauses(per_unit=per_unit)


def evaluate_root_cause(
    ranked: RankedCauses, ground_truth: pd.DataFrame, ks: tuple[int, ...] = (1, 3, 5)
) -> dict[str, float]:
    """Aggregate ranking metrics over every unit that has both a ranking and
    ground-truth causes. Relevance grades are the generator's ``delta_logit``
    contributions (a stronger cause counts more in NDCG)."""
    truth_by_unit = {
        str(uid): {str(r.entity_id): float(cast(float, r.delta_logit)) for r in grp.itertuples()}
        for uid, grp in ground_truth.groupby("unit_id")
    }
    per_query = []
    for uid, frame in ranked.per_unit.items():
        relevant = truth_by_unit.get(uid)
        if not relevant:
            continue
        per_query.append(ranking_metrics(list(frame["entity_id"]), relevant, ks=ks))
    out = aggregate_rankings(per_query)
    out["n_evaluated_units"] = float(len(per_query))
    return out
