"""Historical-frequency defect-rate forecast baseline.

Per line: forecast the next-window daily defect rate as the trailing
window mean, with a binomial-style uncertainty interval. The control any
learned forecaster must beat.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ForecastResult:
    frame: pd.DataFrame  # line_id, day, actual_rate, predicted_rate, lower, upper


def daily_rates(units: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    df = units[["unit_id", "line_id", "produced_at"]].merge(
        labels[["unit_id", "failed_eol"]], on="unit_id"
    )
    df["day"] = df["produced_at"].dt.floor("D")
    grp = df.groupby(["line_id", "day"], as_index=False).agg(
        n=("unit_id", "count"), failures=("failed_eol", "sum")
    )
    grp["rate"] = grp["failures"] / grp["n"]
    return grp


class FrequencyForecast:
    name = "frequency_forecast"

    def __init__(self, window_days: int = 14, z: float = 1.96) -> None:
        self.window_days = window_days
        self.z = z

    def forecast(self, rates: pd.DataFrame, split_day: pd.Timestamp) -> ForecastResult:
        """Walk-forward: for each day ≥ split_day predict from the trailing
        window of *previous* days only (no lookahead)."""
        rows = []
        for line_id, grp in rates.groupby("line_id"):
            grp = grp.sort_values("day").reset_index(drop=True)
            for _, row in grp[grp.day >= split_day].iterrows():
                hist = grp[(grp.day < row.day)].tail(self.window_days)
                if hist.empty:
                    continue
                n_hist = int(hist["n"].sum())
                p = float(hist["failures"].sum()) / max(1, n_hist)
                se = float(np.sqrt(max(p * (1 - p), 1e-9) / max(1, n_hist)))
                rows.append(
                    {
                        "line_id": line_id,
                        "day": row.day,
                        "actual_rate": float(row.rate),
                        "predicted_rate": p,
                        "lower": max(0.0, p - self.z * se),
                        "upper": min(1.0, p + self.z * se),
                    }
                )
        return ForecastResult(pd.DataFrame(rows))
