"""Tabular feature construction from the units table.

Only information available at production time is used. The loader refuses
to read anything under ``ground_truth/`` and never joins label columns
into the feature frame (leakage tests enforce both).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

FEATURE_VERSION = "tab-v1"

CATEGORICAL = [
    "plant_id",
    "line_id",
    "machine_id",
    "tool_id",
    "product_id",
    "revision",
    "family",
    "shift",
    "terminal_lot_id",
]
NUMERIC = [
    "cycle_time_s",
    "production_rate_uph",
    "crimp_height_setpoint_mm",
    "crimp_height_mm",
    "crimp_height_deviation_mm",
    "pull_force_n",
    "ambient_temp_c",
    "humidity_pct",
    "tool_age_cycles",
    "days_since_maintenance",
    "changeover_minutes",
    "units_since_changeover",
    "recent_defect_count_line",
    "hour_of_day",
    "day_of_week",
]

# Columns that must never appear in features (identifiers used for grouping,
# timestamps used for splitting, and anything label-derived).
FORBIDDEN_IN_FEATURES = {
    "unit_id",
    "work_order_id",
    "produced_at",
    "failed_eol",
    "defect_category",
    "severity",
    "labeled_at",
}


@dataclass
class TabularData:
    """Feature frame plus aligned metadata needed for splitting/evaluation."""

    features: pd.DataFrame  # CATEGORICAL as category dtype + NUMERIC floats
    meta: pd.DataFrame  # unit_id, work_order_id, line_id, produced_at
    y_binary: pd.Series  # failed_eol (bool)
    y_category: pd.Series  # defect category incl. "none"


def load_tabular(dataset_dir: Path) -> TabularData:
    if "ground_truth" in str(dataset_dir):
        raise ValueError("refusing to load features from a ground_truth path")
    units = pd.read_parquet(dataset_dir / "tables" / "units.parquet")
    labels = pd.read_parquet(dataset_dir / "tables" / "labels.parquet")
    df = units.merge(
        labels[["unit_id", "failed_eol", "defect_category"]], on="unit_id", how="inner"
    ).sort_values("produced_at", ignore_index=True)

    df["crimp_height_deviation_mm"] = df["crimp_height_mm"] - df["crimp_height_setpoint_mm"]
    df["hour_of_day"] = df["produced_at"].dt.hour.astype(float)
    df["day_of_week"] = df["produced_at"].dt.dayofweek.astype(float)

    features = df[CATEGORICAL + NUMERIC].copy()
    for col in CATEGORICAL:
        features[col] = features[col].astype("category")
    for col in NUMERIC:
        features[col] = features[col].astype(float)

    leak = set(features.columns) & FORBIDDEN_IN_FEATURES
    if leak:
        raise ValueError(f"label/grouping columns leaked into features: {leak}")

    return TabularData(
        features=features,
        meta=df[["unit_id", "work_order_id", "line_id", "produced_at"]].copy(),
        y_binary=df["failed_eol"].astype(bool),
        y_category=df["defect_category"].astype(str),
    )
