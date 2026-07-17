"""CLI: train and evaluate all Phase 3 baselines on a dataset profile.

Usage:
    python -m pipelines.training.train_baselines --profile tiny
        [--data-root data] [--reports-root reports] [--no-tabpfn] [--no-vision]

Writes reports/evaluation/<profile>/{metrics.json, report.md} including the
challenger comparison and cold-start (anomaly-only) sections.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from factoryguard.data.profiles import PROFILE_NAMES, load_profile
from factoryguard.evaluation import metrics as M  # noqa: N812 - conventional metrics-module alias
from factoryguard.evaluation.splits import Splits, assert_no_leakage, temporal_group_split
from factoryguard.features.tabular import FEATURE_VERSION, TabularData, load_tabular
from factoryguard.models.forecast import FrequencyForecast, daily_rates
from factoryguard.models.tabular.rule_baseline import RuleBaseline
from factoryguard.models.tabular.sklearn_models import (
    HgbModel,
    IsolationForestScorer,
    logistic_baseline,
    prior_baseline,
)
from factoryguard.models.timeseries.stat_detector import StatTsDetector
from factoryguard.security.checksums import write_manifest
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("pipelines.training.baselines")


def _git_commit() -> str:
    git = shutil.which("git") or "git"
    try:
        out = subprocess.run(  # noqa: S603 - resolved absolute path, fixed argv
            [git, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def persist_artifacts(
    fitted_models: dict[str, Any],
    out_dir: Path,
    profile_name: str,
    seed: int,
) -> dict[str, Any]:
    """Dump fitted Phase-3 models with a SHA-256 manifest and lineage record.

    This is deliberately lightweight (joblib + a manifest), not the full
    MLflow/registry integration — that remains Phase 6 (ADR-0004/0005) —
    but it closes the gap of Phase 3 producing zero persisted, checksummed
    artifacts (review feedback, 2026-07-17).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for name, model in fitted_models.items():
        path = out_dir / f"{name}.joblib"
        joblib.dump(model, path)
        sizes[name] = path.stat().st_size
    manifest = write_manifest(out_dir, out_dir / "manifest.json")
    lineage = {
        "profile": profile_name,
        "seed": seed,
        "feature_version": FEATURE_VERSION,
        "git_commit": _git_commit(),
        "created_at": datetime.now(UTC).isoformat(),
        "artifact_sizes_bytes": sizes,
        "files": len(manifest),
    }
    (out_dir / "lineage.json").write_text(json.dumps(lineage, indent=2) + "\n")
    return lineage


def _eval_binary_model(
    name: str, proba: np.ndarray, y: np.ndarray, out: dict[str, Any], split: str
) -> None:
    out.setdefault(name, {})[split] = M.classification_metrics(y, proba)


def _eval_anomaly_scorer(
    name: str, score: np.ndarray, y: np.ndarray, out: dict[str, Any], split: str
) -> None:
    """Anomaly/risk scores are rank-evaluated only — never treated as
    calibrated probabilities (ADR-0019; ChatGPT review gap, 2026-07-17)."""
    out.setdefault(name, {})[split] = M.anomaly_metrics(y, score)


def evaluate_severity_slices(
    dataset_dir: Path, data: TabularData, splits: Splits, model: Any, threshold: float = 0.5
) -> dict[str, Any]:
    """Recall broken out by defect severity on the test period — critical
    defects (e.g. terminal deformation, partial insertion) are the ones a
    single aggregate accuracy number can hide (spec Scenario G concern)."""
    labels = pd.read_parquet(dataset_dir / "tables" / "labels.parquet")
    severity = labels.set_index("unit_id")["severity"]
    test_ids = data.meta.loc[splits.test, "unit_id"]
    sev = severity.reindex(test_ids).to_numpy()
    y = data.y_binary.to_numpy()[splits.test]
    proba = model.predict_proba(data.features[splits.test])[:, 1]
    pred = proba >= threshold
    out: dict[str, Any] = {}
    for level in ("critical", "major", "minor"):
        mask = sev == level
        if mask.sum() == 0:
            continue
        out[level] = {
            "n": int(mask.sum()),
            "recall": float(pred[mask & y].mean()) if (mask & y).any() else float("nan"),
        }
    return out


def evaluate_tabular(
    dataset_dir: Path, data: TabularData, splits: Splits, seed: int, use_tabpfn: bool
) -> dict[str, Any]:
    x, yb = data.features, data.y_binary.to_numpy()
    yc = data.y_category.to_numpy()
    tr = splits.train
    results: dict[str, Any] = {}
    timings: dict[str, float] = {}
    fitted: dict[str, Any] = {}

    models: dict[str, Any] = {
        "prior": prior_baseline(),
        "rule_baseline": RuleBaseline(),
        "logistic": logistic_baseline(seed),
        "hgb": HgbModel(seed=seed),
    }
    if use_tabpfn:
        from factoryguard.models.tabular import tabpfn_challenger

        challenger, reason = tabpfn_challenger.try_build(seed, n_train_rows=int(tr.sum()))
        if challenger is not None:
            models["tabpfn"] = challenger
        else:
            results["tabpfn"] = {"unavailable": True, "reason": reason}

    # calib split reserved for calibration diagnostics (reliability + ECE),
    # not for choosing among models — kept separate from val/test throughout.
    eval_splits = {
        "val": splits.val,
        "calib": splits.calib,
        "test": splits.test,
        "unseen_line_test": splits.unseen_line_test,
    }
    for name, model in models.items():
        t0 = time.perf_counter()
        try:
            model.fit(x[tr], yb[tr])
        except Exception as exc:
            # Challengers may fail at fit time (e.g. TabPFN weight download
            # requires a TABPFN_TOKEN license token). Record and continue.
            log.warning("%s unavailable: %s", name, str(exc)[:300])
            results[name] = {"unavailable": True, "reason": str(exc)[:300]}
            continue
        timings[f"{name}_fit_s"] = round(time.perf_counter() - t0, 2)
        fitted[name] = model
        for split_name, mask in eval_splits.items():
            if mask.sum() == 0:
                continue
            proba = model.predict_proba(x[mask])[:, 1]
            _eval_binary_model(name, proba, yb[mask], results, split_name)
        if "calib" in results.get(name, {}):
            proba_calib = model.predict_proba(x[splits.calib])[:, 1]
            results[name]["calib"]["reliability_curve"] = M.reliability_curve(
                yb[splits.calib], proba_calib
            )

    # multiclass on the primary model only (categories incl. "none")
    hgb_mc = HgbModel(seed=seed, multiclass=True).fit(x[tr], yc[tr])
    classes = list(hgb_mc.classes_)
    mc_proba = hgb_mc.predict_proba(x[splits.test])
    results["hgb_multiclass"] = {"test": M.multiclass_metrics(yc[splits.test], mc_proba, classes)}

    # cold-start scorer: isolation forest trained without labels (ADR-0019)
    iso = IsolationForestScorer(seed=seed).fit(x[tr])
    fitted["isolation_forest_coldstart"] = iso
    for split_name, mask in eval_splits.items():
        if mask.sum() == 0 or split_name == "calib":
            continue
        _eval_anomaly_scorer(
            "isolation_forest_coldstart",
            iso.anomaly_score(x[mask]),
            yb[mask],
            results,
            split_name,
        )
    if "hgb" in fitted:
        results["hgb_severity_slices"] = evaluate_severity_slices(
            dataset_dir, data, splits, fitted["hgb"]
        )
    results["_timings"] = timings
    results["_fitted_models"] = fitted
    return results


def evaluate_timeseries(dataset_dir: Path, data: TabularData, splits: Splits) -> dict[str, Any]:
    sensors = pd.read_parquet(dataset_dir / "timeseries" / "sensors.parquet")
    train_units = data.meta.loc[splits.train, "unit_id"]
    det = StatTsDetector().fit(sensors, train_units)
    results: dict[str, Any] = {}
    for split_name, mask in (("test", splits.test), ("unseen_line_test", splits.unseen_line_test)):
        if mask.sum() == 0:
            continue
        ids = data.meta.loc[mask, "unit_id"]
        scores = det.anomaly_scores(sensors[sensors.unit_id.isin(set(ids))])
        aligned = scores.reindex(ids).fillna(0.0).to_numpy()
        y = data.y_binary.to_numpy()[mask]
        results.setdefault("stat_ts_detector", {})[split_name] = M.anomaly_metrics(y, aligned)
    return results


def evaluate_vision(
    dataset_dir: Path, data: TabularData, splits: Splits, seed: int
) -> dict[str, Any]:
    from factoryguard.models.vision.dinov2 import (
        Dinov2Classifier,
        Dinov2Encoder,
        ImageDistanceAnomaly,
    )

    meta = pd.read_parquet(dataset_dir / "tables" / "image_metadata.parquet")
    if meta.empty:
        return {"dinov2_head": {"unavailable": True, "reason": "no images in profile"}}
    unit_split = pd.Series("none", index=data.meta["unit_id"])
    for name, mask in splits.named().items():
        unit_split.loc[data.meta.loc[mask, "unit_id"]] = name
    meta = meta[meta.unit_id.isin(unit_split.index)]
    meta["split"] = unit_split.loc[meta["unit_id"]].to_numpy()
    meta["defective"] = meta["visual_class"] != "normal"

    encoder = Dinov2Encoder()
    paths = [dataset_dir / p for p in meta["image_path"]]
    emb = encoder.embed_paths(paths)

    results: dict[str, Any] = {}
    tr = (meta["split"] == "train").to_numpy()
    te = meta["split"].isin(["test", "unseen_line_test"]).to_numpy()
    if tr.sum() < 10 or te.sum() < 5 or meta.loc[tr, "defective"].nunique() < 2:
        return {"dinov2_head": {"unavailable": True, "reason": "insufficient images per split"}}

    for mode in ("linear", "knn"):
        clf = Dinov2Classifier(encoder, mode=mode, seed=seed).fit_embeddings(
            emb[tr], meta.loc[tr, "defective"].to_numpy()
        )
        proba = clf.predict_proba_embeddings(emb[te])[:, list(clf.classes_).index(True)]
        results[f"dinov2_{mode}"] = {
            "test": M.classification_metrics(meta.loc[te, "defective"].to_numpy(), proba)
        }

    # multiclass visual classes on the linear head
    if meta.loc[tr, "visual_class"].nunique() >= 3:
        clf_mc = Dinov2Classifier(encoder, mode="linear", seed=seed).fit_embeddings(
            emb[tr], meta.loc[tr, "visual_class"].to_numpy()
        )
        classes = list(clf_mc.classes_)
        results["dinov2_multiclass"] = {
            "test": M.multiclass_metrics(
                meta.loc[te, "visual_class"].to_numpy(),
                clf_mc.predict_proba_embeddings(emb[te]),
                classes,
            )
        }

    # cold start: distance to normal-looking reference set (labels unused —
    # reference is simply the train-period image population). Rank-evaluated
    # as an anomaly score, not a calibrated probability (ADR-0019).
    dist = ImageDistanceAnomaly().fit(emb[tr])
    results["image_distance_coldstart"] = {
        "test": M.anomaly_metrics(meta.loc[te, "defective"].to_numpy(), dist.anomaly_score(emb[te]))
    }

    # Image-quality assessment (Scenario C): a separate signal from defect
    # detection, so a blurry/misaligned camera is flagged as a data-quality
    # issue rather than reported as a product defect.
    from factoryguard.models.vision.quality import assess_batch

    quality = assess_batch(paths)
    meta = meta.assign(
        quality_degraded=[q.is_degraded for q in quality],
        blur_variance=[q.blur_variance for q in quality],
    )
    truly_degraded = meta["camera_degraded"].to_numpy()
    flagged_degraded = meta["quality_degraded"].to_numpy()
    results["image_quality_scorer"] = {
        "test": M.anomaly_metrics(
            truly_degraded[te], (1.0 - meta["blur_variance"].to_numpy() / 200.0)[te]
        ),
        "detection_rate_on_camera_degraded_units": (
            float(flagged_degraded[truly_degraded].mean()) if truly_degraded.any() else float("nan")
        ),
        "false_flag_rate_on_healthy_units": (
            float(flagged_degraded[~truly_degraded].mean())
            if (~truly_degraded).any()
            else float("nan")
        ),
    }
    return results


def evaluate_forecast(dataset_dir: Path, splits: Splits) -> dict[str, Any]:
    units = pd.read_parquet(dataset_dir / "tables" / "units.parquet")
    labels = pd.read_parquet(dataset_dir / "tables" / "labels.parquet")
    rates = daily_rates(units, labels)
    calib_end = splits.boundaries.get("calib")
    if calib_end is None:
        return {"frequency_forecast": {"unavailable": True}}
    fc = FrequencyForecast().forecast(rates, split_day=calib_end.floor("D"))
    if fc.frame.empty:
        return {"frequency_forecast": {"unavailable": True, "reason": "no forecastable days"}}
    m = M.forecast_metrics(
        fc.frame["actual_rate"].to_numpy(), fc.frame["predicted_rate"].to_numpy()
    )
    m["interval_coverage"] = M.interval_coverage(
        fc.frame["actual_rate"].to_numpy(),
        fc.frame["lower"].to_numpy(),
        fc.frame["upper"].to_numpy(),
    )
    m["days"] = float(len(fc.frame))
    return {"frequency_forecast": {"test": m}}


def write_report(
    out_dir: Path,
    profile: str,
    results: dict[str, Any],
    splits: Splits,
    artifact_lineage: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_safe = {k: v for k, v in results.items() if k != "_fitted_models"}
    (out_dir / "metrics.json").write_text(json.dumps(json_safe, indent=2, default=str) + "\n")

    def fmt(model: str, split: str = "test") -> str:
        """Format a calibrated-probability model's metrics."""
        m = results.get(model, {}).get(split)
        if not m:
            flag = results.get(model, {})
            return "unavailable" if flag.get("unavailable") else "—"
        return (
            f"PR-AUC {m['pr_auc']:.3f} · ROC-AUC {m['roc_auc']:.3f} · "
            f"recall@5%FPR {m['recall_at_fpr']:.3f} · MCC {m['mcc']:.3f} · "
            f"Brier {m['brier']:.4f} · ECE {m['ece']:.3f}"
        )

    def fmt_anomaly(model: str, split: str = "test") -> str:
        """Format an anomaly/risk scorer — rank metrics only, explicitly NOT
        a calibrated probability (ADR-0019; see factoryguard.evaluation.metrics.anomaly_metrics)."""
        m = results.get(model, {}).get(split)
        if not m:
            flag = results.get(model, {})
            reason = flag.get("reason", "")
            return f"unavailable ({reason})" if flag.get("unavailable") else "—"
        return (
            f"ROC-AUC {m['roc_auc']:.3f} · PR-AUC {m['pr_auc']:.3f} · "
            f"recall@5%FPR {m['recall_at_fpr']:.3f} "
            "*(anomaly risk score — not a defect probability)*"
        )

    lines = [
        f"# Baseline Evaluation Report — profile `{profile}`",
        "",
        f"Splits (work-order grouped, temporal): train/val/calib/test + unseen line "
        f"`{splits.unseen_line or 'none (dataset too small for holdout)'}`.",
        "",
        "## Binary defect prediction (test period)",
        "",
        "| Model | Test metrics |",
        "|---|---|",
    ]
    for model in ("prior", "rule_baseline", "logistic", "hgb", "tabpfn"):
        lines.append(f"| {model} | {fmt(model)} |")
    lines += [
        "",
        "## Calibration (calibration-period holdout, never used for model selection)",
        f"- HGB: Brier {results.get('hgb', {}).get('calib', {}).get('brier', float('nan')):.4f} · "
        f"ECE {results.get('hgb', {}).get('calib', {}).get('ece', float('nan')):.4f} "
        "(reliability curve in metrics.json; temperature scaling arrives in Phase 4)",
        "",
        "## Per-severity recall (HGB, test period)",
        "*Does aggregate accuracy hide poor critical-defect recall?*",
    ]
    for level, m in results.get("hgb_severity_slices", {}).items():
        lines.append(f"- {level}: recall {m['recall']:.3f} (n={m['n']})")
    lines += [
        "",
        "## Challenger comparison (ADR-0021)",
        f"- HGB (primary): {fmt('hgb')}",
        f"- TabPFN (challenger): {fmt('tabpfn')}",
        "",
        "## Cold-start / anomaly-only mode (ADR-0019, labels unused at fit)",
        "*Scores below are uncalibrated anomaly/risk scores, evaluated by rank only — never "
        "interpreted as defect probabilities (a real gap found and fixed 2026-07-17).*",
        "",
        f"- Isolation forest (tabular): {fmt_anomaly('isolation_forest_coldstart')}",
        f"- Statistical TS detector: {fmt_anomaly('stat_ts_detector')}",
        f"- Image distance (DINOv2 embeddings): {fmt_anomaly('image_distance_coldstart')}",
        "",
        "## Image-quality assessment (Scenario C: camera issues ≠ product defects)",
    ]
    iq = results.get("image_quality_scorer", {})
    if iq.get("test"):
        lines.append(
            f"- Detection rate on genuinely camera-degraded units: "
            f"{iq.get('detection_rate_on_camera_degraded_units', float('nan')):.2%}"
        )
        lines.append(
            f"- False-flag rate on healthy units: "
            f"{iq.get('false_flag_rate_on_healthy_units', float('nan')):.2%}"
        )
    else:
        lines.append("- unavailable (no images in this profile)")
    lines += [
        "",
        "## Vision (DINOv2-small frozen encoder, ADR-0018; weights checksum-verified)",
        f"- Linear head: {fmt('dinov2_linear')}",
        f"- k-NN probe: {fmt('dinov2_knn')}",
        "",
        "## Generalization: unseen line",
        f"- HGB: {fmt('hgb', 'unseen_line_test')}",
        f"- Logistic: {fmt('logistic', 'unseen_line_test')}",
        "",
    ]
    fcm = results.get("frequency_forecast", {}).get("test")
    if fcm:
        lines += [
            "## Defect-rate forecast (frequency baseline)",
            f"- MAE {fcm['mae']:.4f} · RMSE {fcm['rmse']:.4f} · sMAPE {fcm['smape']:.3f} · "
            f"95% interval coverage {fcm['interval_coverage']:.2%} "
            f"over {int(fcm['days'])} line-days",
            "",
        ]
    mc = results.get("hgb_multiclass", {}).get("test")
    if mc:
        lines += [
            "## Defect category (multiclass, HGB)",
            f"- accuracy {mc['accuracy']:.3f} · macro-F1 {mc['macro_f1']:.3f} · "
            f"MCC {mc['mcc']:.3f}",
            "",
        ]
    lines += ["## Fit latency and artifact sizes"]
    timings = results.get("_timings", {})
    for k, v in timings.items():
        lines.append(f"- {k}: {v}s")
    if artifact_lineage:
        for name, size in artifact_lineage.get("artifact_sizes_bytes", {}).items():
            lines.append(f"- {name} artifact: {size / 1024:.1f} KiB")
        lines.append(
            f"- artifacts persisted with SHA-256 manifest: "
            f"`{artifact_lineage['files']}` files, commit `{artifact_lineage['git_commit'][:12]}`"
        )
    lines += [
        "",
        "## Known limitations",
        "- Rule/prior baselines are uncalibrated controls, not production candidates.",
        "- Probabilities are not yet calibrated (temperature/isotonic scaling is Phase 4); "
        "Brier/ECE above are diagnostic, not corrected.",
        "- Signal ceiling on synthetic data is modest by design (random-CV ROC-AUC ~0.55-0.60): "
        "mechanisms are deliberately subtle and diluted across 8 defect categories, not tuned "
        "for an unrealistically easy demo (risk register R-03).",
        "- Unseen-line generalization is a genuinely hard transfer task (new machines/tools never "
        "seen in training) and is reported honestly even when it is weak.",
        "- No conformal uncertainty, abstention policy, or root-cause ranking yet — Phase 4.",
    ]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--reports-root", type=Path, default=Path("reports"))
    parser.add_argument("--no-tabpfn", action="store_true")
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts/baselines"))
    args = parser.parse_args()

    configure_logging(fmt="console")
    profile = load_profile(args.profile)
    dataset_dir = args.data_root / args.profile
    if not dataset_dir.is_dir():
        log.error(
            "dataset %s missing — run `make generate-data PROFILE=%s`", dataset_dir, args.profile
        )
        return 1

    data = load_tabular(dataset_dir)
    splits = temporal_group_split(data.meta)
    assert_no_leakage(data.meta, splits)
    log.info(
        "splits: train=%d val=%d calib=%d test=%d unseen(%s)=%d",
        splits.train.sum(),
        splits.val.sum(),
        splits.calib.sum(),
        splits.test.sum(),
        splits.unseen_line,
        splits.unseen_line_test.sum(),
    )

    results: dict[str, Any] = {
        "_meta": {
            "profile": args.profile,
            "feature_version": FEATURE_VERSION,
            "seed": profile.seed,
            "n_units": int(len(data.meta)),
            "unseen_line": splits.unseen_line,
        }
    }
    results.update(
        evaluate_tabular(dataset_dir, data, splits, profile.seed, use_tabpfn=not args.no_tabpfn)
    )
    results.update(evaluate_timeseries(dataset_dir, data, splits))
    if not args.no_vision:
        try:
            results.update(evaluate_vision(dataset_dir, data, splits, profile.seed))
        except Exception as exc:
            log.warning("vision baseline unavailable: %s", exc)
            results["dinov2_linear"] = {"unavailable": True, "reason": str(exc)[:200]}
    results.update(evaluate_forecast(dataset_dir, splits))

    fitted_models = results.get("_fitted_models", {})
    lineage = None
    if fitted_models:
        artifacts_dir = args.artifacts_root / args.profile
        lineage = persist_artifacts(fitted_models, artifacts_dir, args.profile, profile.seed)
        log.info("artifacts persisted to %s (%d files)", artifacts_dir, lineage["files"])

    out_dir = args.reports_root / "evaluation" / args.profile
    write_report(out_dir, args.profile, results, splits, artifact_lineage=lineage)
    log.info("report written to %s", out_dir)

    hgb_test = results.get("hgb", {}).get("test", {})
    log.info(
        "HGB test: PR-AUC=%.3f ROC-AUC=%.3f recall@5%%FPR=%.3f",
        hgb_test.get("pr_auc", float("nan")),
        hgb_test.get("roc_auc", float("nan")),
        hgb_test.get("recall_at_fpr", float("nan")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
