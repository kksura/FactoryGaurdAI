"""Rule-based baseline: the thresholds a quality engineer applies today.

No learning. Serves as the "is ML helping at all?" control. Thresholds are
constructor parameters (defaults mirror configs/policies/rules.yaml).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class RuleBaseline:
    name = "rule_baseline"

    def __init__(
        self,
        height_dev_mm: float = 0.05,
        min_pull_force_n: float = 80.0,
        max_tool_age_cycles: int = 100_000,
        first_pieces: int = 3,
        max_humidity_pct: float = 80.0,
    ) -> None:
        self.height_dev_mm = height_dev_mm
        self.min_pull_force_n = min_pull_force_n
        self.max_tool_age_cycles = max_tool_age_cycles
        self.first_pieces = first_pieces
        self.max_humidity_pct = max_humidity_pct

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> RuleBaseline:  # noqa: ARG002 - no learning
        return self

    def rule_hits(self, x: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "height_dev": x["crimp_height_deviation_mm"].abs() > self.height_dev_mm,
                "low_pull_force": x["pull_force_n"] < self.min_pull_force_n,
                "old_tool": x["tool_age_cycles"] > self.max_tool_age_cycles,
                "first_piece": x["units_since_changeover"] <= self.first_pieces,
                "high_humidity": x["humidity_pct"] > self.max_humidity_pct,
            }
        )

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        """Pseudo-probability = fraction of fired rules, floored at 0.02.

        Not calibrated — reported as-is to show what rules alone achieve.
        """
        hits = self.rule_hits(x)
        score = 0.02 + 0.98 * hits.mean(axis=1).to_numpy()
        return np.column_stack([1 - score, score])
