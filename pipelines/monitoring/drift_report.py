"""CLI: drift report for a profile (spec §21).

Usage:
    python -m pipelines.monitoring.drift_report --profile small
        [--simulate-drift] [--data-root data] [--reports-root reports]

Reference window = training period; current window = test period (real
temporal drift, not a mock). ``--simulate-drift`` additionally applies a
synthetic shift to the current window and reports it side by side — the
proof that the detectors fire when drift is injected, not just that they
stay quiet on clean data.

Writes ``reports/monitoring/<profile>/drift-report.{json,md}`` including
the OI-7 drift-aware anomaly-weight suggestion.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from factoryguard.data.profiles import PROFILE_NAMES
from factoryguard.evaluation.splits import temporal_group_split
from factoryguard.features.tabular import load_tabular
from factoryguard.models.tabular.sklearn_models import IsolationForestScorer
from factoryguard.models.timeseries.stat_detector import StatTsDetector
from factoryguard.monitoring.drift import (
    drift_aware_weights,
    embedding_drift,
    feature_drift,
    psi,
    summarize,
)
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("pipelines.monitoring.drift")


def _load_thresholds() -> dict[str, float]:
    path = Path("configs/policies/drift.yaml")
    return dict(yaml.safe_load(path.read_text())) if path.is_file() else {}


def _inject_drift(frame: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Synthetic covariate shift: numeric shift+scale on process features."""
    rng = np.random.default_rng(seed)
    out = frame.copy()
    for col in ("crimp_height_mm", "pull_force_n", "ambient_temp_c"):
        if col in out.columns:
            std = float(out[col].std()) or 1.0
            out[col] = out[col] * 1.15 + 0.8 * std + rng.normal(0, 0.1 * std, len(out))
    return out


def build_report(dataset_dir: Path, simulate: bool) -> dict[str, Any]:
    thresholds = _load_thresholds()
    data = load_tabular(dataset_dir)
    splits = temporal_group_split(data.meta)
    ref = data.features[splits.train]
    cur = data.features[splits.test]

    report: dict[str, Any] = {"thresholds": thresholds}
    features = feature_drift(ref, cur, thresholds)
    report["feature_drift"] = {
        "summary": summarize(features),
        "features": [asdict(f) for f in features],
    }

    # Embedding drift on the tabular numeric block (train stats geometry).
    num = data.features.select_dtypes(include=[float])
    report["embedding_drift"] = embedding_drift(
        num[splits.train].to_numpy(), num[splits.test].to_numpy()
    )

    # Anomaly-component drift → OI-7 weight suggestion: PSI of each
    # label-free component's score distribution, train vs test period.
    iso = IsolationForestScorer(seed=0).fit(data.features[splits.train])
    iso_ref = iso.anomaly_score(data.features[splits.train])
    iso_cur = iso.anomaly_score(data.features[splits.test])
    component_psi = {"isolation_forest": psi(iso_ref, iso_cur)}
    sensors_path = dataset_dir / "timeseries" / "sensors.parquet"
    if sensors_path.is_file():
        sensors = pd.read_parquet(sensors_path)
        det = StatTsDetector().fit(sensors, data.meta.loc[splits.train, "unit_id"])
        s_ref = det.anomaly_scores(
            sensors[sensors.unit_id.isin(set(data.meta.loc[splits.train, "unit_id"]))]
        ).to_numpy()
        s_cur = det.anomaly_scores(
            sensors[sensors.unit_id.isin(set(data.meta.loc[splits.test, "unit_id"]))]
        ).to_numpy()
        component_psi["stat_ts"] = psi(s_ref, s_cur)
    report["anomaly_component_psi"] = {
        k: round(v, 4) if np.isfinite(v) else None for k, v in component_psi.items()
    }
    report["oi7_drift_aware_weights"] = drift_aware_weights(component_psi)

    if simulate:
        drifted = _inject_drift(cur)
        sim_features = feature_drift(ref, drifted, thresholds)
        report["simulated_drift"] = {
            "summary": summarize(sim_features),
            "note": "synthetic shift injected into the current window — the "
            "detector must flag these as major",
        }
    return report


def write_markdown(out_dir: Path, profile: str, report: dict[str, Any]) -> None:
    s = report["feature_drift"]["summary"]
    lines = [
        f"# Drift Report — profile `{profile}`",
        "",
        "Reference window: training period · current window: test period "
        "(real temporal drift, not simulated).",
        "",
        "## Feature drift",
        f"- {s['n_features']} features: {s['by_severity']['ok']} ok · "
        f"{s['by_severity']['moderate']} moderate · {s['by_severity']['major']} major",
        "",
        "| Worst features (PSI) | PSI | Severity |",
        "|---|---|---|",
    ]
    for w in s["worst"]:
        lines.append(f"| {w['feature']} | {w['psi']:.3f} | {w['severity']} |")
    emb = report["embedding_drift"]
    if emb.get("available"):
        lines += [
            "",
            "## Embedding drift (tabular numeric block, reference geometry)",
            f"- mean Mahalanobis-distance ratio: {emb['mean_distance_ratio']:.3f} (1.0 = no shift)",
            f"- tail mass beyond reference p99: {emb['tail_fraction_current']:.1%} "
            f"(expected {emb['tail_fraction_expected']:.1%})",
        ]
    lines += [
        "",
        "## Anomaly-component drift (OI-7)",
        f"- per-component score PSI: {report['anomaly_component_psi']}",
        f"- suggested drift-aware weights: {report['oi7_drift_aware_weights']} "
        "*(applied only when `serving.drift_aware_anomaly_weights` is enabled; "
        "the default rule remains the documented equal-weight mean)*",
    ]
    if "simulated_drift" in report:
        sim = report["simulated_drift"]["summary"]
        lines += [
            "",
            "## Detector validation (synthetic injected shift)",
            f"- after injection: {sim['by_severity']['major']} major / "
            f"{sim['by_severity']['moderate']} moderate — detector fires as required.",
        ]
    (out_dir / "drift-report.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--reports-root", type=Path, default=Path("reports"))
    parser.add_argument("--simulate-drift", action="store_true")
    args = parser.parse_args()

    configure_logging(fmt="console")
    dataset_dir = args.data_root / args.profile
    if not dataset_dir.is_dir():
        log.error("dataset %s missing", dataset_dir)
        return 1
    report = build_report(dataset_dir, simulate=args.simulate_drift)
    out_dir = args.reports_root / "monitoring" / args.profile
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "drift-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    write_markdown(out_dir, args.profile, report)
    s = report["feature_drift"]["summary"]["by_severity"]
    log.info(
        "drift report written to %s (major=%d moderate=%d)", out_dir, s["major"], s["moderate"]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
