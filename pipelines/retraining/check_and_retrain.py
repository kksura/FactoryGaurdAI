"""CLI: drift-triggered retraining workflow (spec §21/§22).

Usage:
    python -m pipelines.retraining.check_and_retrain --profile small
        [--force] [--data-root data] [--reports-root reports]

Flow (every step recorded, nothing auto-deploys):
1. Read the latest drift report; apply the sustained-breach rule from
   ``configs/policies/drift.yaml``.
2. On breach (or ``--force``): train a candidate bundle into
   ``artifacts/candidates/<timestamp>/`` via the standard pipeline.
3. Register the candidate (CANDIDATE) and attempt promotion to VALIDATED
   through the metric gates; record the comparison against the current
   champion (or the serving-profile artifacts when no champion exists).
4. Write a decision file. CHAMPION promotion stays a human action
   (registry ``approve`` + ``promote`` — ADR-0017); shadow/canary rollout
   is documented in ``docs/operations/retraining-runbook.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from factoryguard.data.profiles import PROFILE_NAMES
from factoryguard.mlops.registry import ModelRegistry, PromotionError
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("pipelines.retraining")


def breach_detected(drift_report: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    reasons = []
    exclude = set(policy.get("breach_exclude_features", []))
    features = drift_report["feature_drift"].get("features", [])
    if features:
        majors = sum(
            1 for f in features if f["severity"] == "major" and f["feature"] not in exclude
        )
    else:  # older reports without the per-feature list
        majors = drift_report["feature_drift"]["summary"]["by_severity"].get("major", 0)
    if majors >= int(policy.get("min_major_features", 3)):
        reasons.append(f"{majors} features with major drift (excluding consumable ids)")
    emb = drift_report.get("embedding_drift", {})
    if emb.get("available") and emb.get("tail_fraction_current", 0.0) > float(
        policy.get("embedding_tail_max", 0.05)
    ):
        reasons.append(f"embedding tail mass {emb['tail_fraction_current']:.1%} beyond limit")
    calib = drift_report.get("calibration_drift", {})
    if calib.get("available") and calib.get("ece_delta", 0.0) > float(
        policy.get("ece_delta_max", 0.05)
    ):
        reasons.append(f"calibration ECE degraded by {calib['ece_delta']:.3f}")
    return reasons


def _candidate_metrics(report_dir: Path) -> dict[str, float]:
    metrics = json.loads((report_dir / "multimodal-metrics.json").read_text())
    late = metrics["fusion"]["late"].get("test", {})
    return {
        "test_roc_auc": float(late.get("roc_auc", float("nan"))),
        "test_ece": float(late.get("ece", float("nan"))),
        "conformal_coverage": float(metrics["uncertainty"].get("empirical_coverage", float("nan"))),
    }


def train_candidate(profile: str, data_root: Path, out_root: Path) -> Path:
    from pipelines.training.train_multimodal import main as train_main

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifacts_root = out_root / stamp
    argv_backup = sys.argv
    sys.argv = [
        "train_multimodal",
        "--profile",
        profile,
        "--data-root",
        str(data_root),
        "--reports-root",
        str(artifacts_root / "reports"),
        "--artifacts-root",
        str(artifacts_root / "artifacts"),
        "--no-vision",
        "--no-mlflow",
    ]
    try:
        if train_main() != 0:
            raise RuntimeError("candidate training failed")
    finally:
        sys.argv = argv_backup
    return artifacts_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--reports-root", type=Path, default=Path("reports"))
    parser.add_argument("--candidates-root", type=Path, default=Path("artifacts/candidates"))
    parser.add_argument("--registry-root", type=Path, default=Path("artifacts/registry"))
    parser.add_argument(
        "--force", action="store_true", help="train a candidate even without a drift breach"
    )
    args = parser.parse_args()
    configure_logging(fmt="console")

    drift_path = args.reports_root / "monitoring" / args.profile / "drift-report.json"
    if not drift_path.is_file():
        log.error("no drift report at %s — run pipelines.monitoring.drift_report first", drift_path)
        return 1
    drift_report = json.loads(drift_path.read_text())
    policy = yaml.safe_load(Path("configs/policies/drift.yaml").read_text()) or {}
    reasons = breach_detected(drift_report, policy)

    decision: dict[str, Any] = {
        "profile": args.profile,
        "checked_at": datetime.now(UTC).isoformat(),
        "breach": bool(reasons),
        "breach_reasons": reasons,
        "forced": args.force,
    }
    out_dir = args.reports_root / "retraining" / args.profile
    out_dir.mkdir(parents=True, exist_ok=True)

    if not reasons and not args.force:
        decision["action"] = "none (no sustained breach)"
        (out_dir / "decision.json").write_text(json.dumps(decision, indent=2) + "\n")
        log.info("no breach — nothing to do")
        return 0

    candidate_root = train_candidate(args.profile, args.data_root, args.candidates_root)
    candidate_artifacts = candidate_root / "artifacts" / args.profile
    candidate_report = candidate_root / "reports" / "evaluation" / args.profile
    cand_metrics = _candidate_metrics(candidate_report)
    lineage = json.loads((candidate_artifacts / "lineage.json").read_text())

    registry = ModelRegistry(args.registry_root)
    model_id = registry.register(
        candidate_artifacts, cand_metrics, lineage, actor="retraining-pipeline"
    )
    decision["candidate_model_id"] = model_id
    decision["candidate_metrics"] = cand_metrics

    # champion comparison (or serving-profile artifacts as the incumbent)
    champion = registry.champion_path()
    incumbent_report = args.reports_root / "evaluation" / args.profile
    incumbent = (
        _candidate_metrics(incumbent_report)
        if (incumbent_report / "multimodal-metrics.json").is_file()
        else {}
    )
    comparison = {
        "incumbent": incumbent,
        "candidate": cand_metrics,
        "incumbent_source": str(champion) if champion else "serving-profile artifacts",
    }
    registry.record_champion_comparison(model_id, comparison, actor="retraining-pipeline")
    decision["comparison"] = comparison

    try:
        registry.promote(model_id, "VALIDATED", actor="retraining-pipeline")
        decision["validated"] = True
        decision["action"] = (
            "candidate VALIDATED — human approval required for STAGING/CHAMPION "
            "(registry.approve + promote; see docs/operations/retraining-runbook.md)"
        )
    except PromotionError as exc:
        decision["validated"] = False
        decision["action"] = f"candidate rejected by gates: {exc}"

    (out_dir / "decision.json").write_text(json.dumps(decision, indent=2) + "\n")
    log.info("retraining decision: %s", decision["action"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
