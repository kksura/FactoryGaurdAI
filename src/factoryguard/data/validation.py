"""Dataset validation: schema, ranges, referential integrity, time order,
duplicates, missingness thresholds — with quarantine of offending rows and
a machine-readable data-quality report.

Invalid rows are never silently dropped: they are copied to
``<dataset>/quarantine/<table>.parquet`` with a ``_violation`` column, and
the report records counts. Validation fails (nonzero exit) when violations
exceed configured thresholds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from factoryguard.data.mechanisms import CATEGORIES

_MAX_INVALID_FRACTION = 0.001  # >0.1% invalid rows in any table fails validation


def unit_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            "unit_id": pa.Column(str, pa.Check.str_matches(r"^UNIT-\d{7}$"), unique=True),
            "work_order_id": pa.Column(str),
            "product_id": pa.Column(str),
            "revision": pa.Column(str, pa.Check.isin(["A", "B"])),
            "plant_id": pa.Column(str),
            "line_id": pa.Column(str),
            "machine_id": pa.Column(str),
            "tool_id": pa.Column(str),
            "operator_id": pa.Column(str, pa.Check.str_matches(r"^OP-")),
            "shift": pa.Column(str, pa.Check.isin(["day", "evening", "night"])),
            "produced_at": pa.Column("datetime64[ns, UTC]"),
            "cycle_time_s": pa.Column(float, pa.Check.in_range(5, 3600)),
            "crimp_height_setpoint_mm": pa.Column(float, pa.Check.in_range(1.0, 4.0)),
            "crimp_height_mm": pa.Column(float, pa.Check.in_range(0.5, 5.0)),
            "pull_force_n": pa.Column(float, pa.Check.in_range(0, 200)),
            "humidity_pct": pa.Column(float, pa.Check.in_range(0, 100)),
            "tool_age_cycles": pa.Column(int, pa.Check.ge(0)),
            "units_since_changeover": pa.Column(int, pa.Check.ge(1)),
        },
        strict=False,
        coerce=False,
    )


def label_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            "unit_id": pa.Column(str, unique=True),
            "failed_eol": pa.Column(bool),
            "defect_category": pa.Column(str, pa.Check.isin([*CATEGORIES, "none"])),
            "severity": pa.Column(str, pa.Check.isin(["minor", "major", "critical", "none"])),
            "labeled_at": pa.Column("datetime64[ns, UTC]"),
        },
        strict=False,
    )


def sensor_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            "unit_id": pa.Column(str),
            "channel": pa.Column(str),
            "t": pa.Column("int32", pa.Check.ge(0)),
            "value": pa.Column("float32", nullable=True),  # NaN = sensor dropout
        },
        strict=True,
    )


@dataclass
class TableReport:
    rows: int = 0
    schema_violations: int = 0
    integrity_violations: int = 0
    duplicate_rows: int = 0
    missing_fraction: float = 0.0
    quarantined: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    dataset: str
    generated_at: str
    tables: dict[str, TableReport] = field(default_factory=dict)
    passed: bool = True

    def to_json(self) -> str:
        return json.dumps(
            {
                "dataset": self.dataset,
                "generated_at": self.generated_at,
                "passed": self.passed,
                "tables": {
                    k: {
                        "rows": t.rows,
                        "schema_violations": t.schema_violations,
                        "integrity_violations": t.integrity_violations,
                        "duplicate_rows": t.duplicate_rows,
                        "missing_fraction": round(t.missing_fraction, 5),
                        "quarantined": t.quarantined,
                        "notes": t.notes,
                    }
                    for k, t in self.tables.items()
                },
            },
            indent=2,
        )


def _apply_schema(
    df: pd.DataFrame, schema: pa.DataFrameSchema, report: TableReport
) -> pd.DataFrame:
    """Return valid rows; count and separate schema violations."""
    try:
        schema.validate(df, lazy=True)
        return df
    except pa.errors.SchemaErrors as exc:
        bad_idx = {
            int(i) for i in exc.failure_cases["index"].dropna().unique() if int(i) in df.index
        }
        report.schema_violations = len(bad_idx)
        report.notes.extend(str(m) for m in exc.failure_cases["check"].astype(str).unique()[:5])
        return df.drop(index=sorted(bad_idx))


def validate_dataset(dataset_dir: Path) -> ValidationReport:
    tables_dir = dataset_dir / "tables"
    quarantine_dir = dataset_dir / "quarantine"
    report = ValidationReport(dataset=str(dataset_dir), generated_at=datetime.now(UTC).isoformat())

    units = pd.read_parquet(tables_dir / "units.parquet")
    labels = pd.read_parquet(tables_dir / "labels.parquet")
    sensors = pd.read_parquet(dataset_dir / "timeseries" / "sensors.parquet")
    steps = pd.read_parquet(tables_dir / "step_events.parquet")
    images = pd.read_parquet(tables_dir / "image_metadata.parquet")
    lots = pd.read_parquet(tables_dir / "material_lots.parquet")
    machines = pd.read_parquet(tables_dir / "machines.parquet")

    # --- units ---
    tr = TableReport(rows=len(units))
    valid_units = _apply_schema(units, unit_schema(), tr)
    dup = int(units.duplicated(subset=["unit_id"]).sum())
    tr.duplicate_rows = dup
    tr.missing_fraction = float(units.drop(columns=["seal_lot_id"]).isna().mean().mean())
    # referential integrity
    bad_machine = ~valid_units["machine_id"].isin(machines["machine_id"])
    bad_lot = ~valid_units["terminal_lot_id"].isin(lots["lot_id"])
    integrity_bad = valid_units[bad_machine | bad_lot]
    tr.integrity_violations = len(integrity_bad)
    quarantined = pd.concat(
        [
            units.loc[~units.index.isin(valid_units.index)].assign(_violation="schema"),
            integrity_bad.assign(_violation="referential_integrity"),
        ]
    )
    if not quarantined.empty:
        quarantine_dir.mkdir(exist_ok=True)
        quarantined.to_parquet(quarantine_dir / "units.parquet", index=False)
    tr.quarantined = len(quarantined)
    report.tables["units"] = tr

    # --- labels ---
    tr = TableReport(rows=len(labels))
    valid_labels = _apply_schema(labels, label_schema(), tr)
    orphan = ~valid_labels["unit_id"].isin(units["unit_id"])
    tr.integrity_violations = int(orphan.sum())
    # every produced unit must eventually be labeled
    unlabeled = int((~units["unit_id"].isin(labels["unit_id"])).sum())
    if unlabeled:
        tr.notes.append(f"{unlabeled} units without labels")
        tr.integrity_violations += unlabeled
    report.tables["labels"] = tr

    # --- time order: labels must not precede production; steps monotonic ---
    tr = TableReport(rows=len(steps))
    merged = labels.merge(units[["unit_id", "produced_at"]], on="unit_id", how="inner")
    time_bad = int((merged["labeled_at"] < merged["produced_at"]).sum())
    if time_bad:
        tr.notes.append(f"{time_bad} labels timestamped before production")
        tr.integrity_violations += time_bad
    step_order = steps.sort_values(["unit_id", "step_no"])
    non_monotonic = int(
        (step_order.groupby("unit_id")["started_at"].diff().dropna() < pd.Timedelta(0)).sum()
    )
    if non_monotonic:
        tr.notes.append(f"{non_monotonic} non-monotonic step timestamps")
        tr.integrity_violations += non_monotonic
    report.tables["step_events"] = tr

    # --- sensors ---
    tr = TableReport(rows=len(sensors))
    _apply_schema(sensors, sensor_schema(), tr)
    tr.missing_fraction = float(sensors["value"].isna().mean())
    if tr.missing_fraction > 0.05:
        tr.notes.append("sensor missingness above 5%")
        tr.integrity_violations += 1
    orphan_sensors = int(~sensors["unit_id"].isin(units["unit_id"]).sum() > 0)
    tr.integrity_violations += orphan_sensors
    report.tables["sensors"] = tr

    # --- images: metadata refers to existing files, valid PNG magic ---
    tr = TableReport(rows=len(images))
    missing_files = 0
    bad_magic = 0
    for rel in images["image_path"]:
        p = dataset_dir / rel
        if not p.is_file():
            missing_files += 1
            continue
        with p.open("rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                bad_magic += 1
    if missing_files or bad_magic:
        tr.notes.append(f"{missing_files} missing files, {bad_magic} bad PNG headers")
    tr.integrity_violations = missing_files + bad_magic
    report.tables["images"] = tr

    for t in report.tables.values():
        frac = (t.schema_violations + t.integrity_violations) / max(1, t.rows)
        if frac > _MAX_INVALID_FRACTION:
            report.passed = False
            t.notes.append(f"invalid fraction {frac:.4f} exceeds {_MAX_INVALID_FRACTION}")

    (dataset_dir / "data-quality-report.json").write_text(report.to_json() + "\n")
    return report
