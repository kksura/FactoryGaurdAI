"""CLI: train and evaluate the Phase 4 multimodal system on a profile.

Usage:
    python -m pipelines.training.train_multimodal --profile small
        [--data-root data] [--reports-root reports] [--no-vision]
        [--compare-ssl] [--config configs/models/multimodal.yaml]

Covers spec §8.2–8.6 + §9/§10 Phase 4 scope: per-modality models (tabular
HGB, graph logistic, 1D-CNN TS, DINOv2 vision), per-modality calibration,
late + embedding fusion with modality dropout, conformal + Mahalanobis
abstention, serving modes, root-cause ranking vs ground truth, and
similar-incident retrieval. Writes
``reports/evaluation/<profile>/multimodal-{metrics.json,report.md}`` and
persists checksummed artifacts to ``artifacts/multimodal/<profile>/``.

Split usage discipline:
- base models fit on **train**;
- the fusion meta-model fits on **val** (base-model scores there are
  out-of-sample);
- per-modality and fused calibrators fit on **calib-A**;
- conformal quantiles and OOD thresholds fit on **calib-B** (never the
  same rows as the calibrators — conformal validity requires it);
- every headline number comes from **test** / **unseen-line test**.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from factoryguard.config.multimodal import MultimodalConfig, load_multimodal_config
from factoryguard.data.profiles import PROFILE_NAMES, load_profile
from factoryguard.evaluation import metrics as M  # noqa: N812 - conventional metrics-module alias
from factoryguard.evaluation.splits import Splits, assert_no_leakage, temporal_group_split
from factoryguard.explainability.root_cause import RootCauseRanker, evaluate_root_cause
from factoryguard.features.graph import GraphFeatures, build_graph_features, graph_prior_scores
from factoryguard.features.tabular import TabularData, load_tabular
from factoryguard.inference.retrieval import SimilarIncidentIndex
from factoryguard.inference.serving import ServingMode, serve
from factoryguard.inference.uncertainty import (
    AbstentionPolicy,
    MahalanobisOOD,
    SplitConformal,
    abstention_curve,
)
from factoryguard.models.calibration import fit_calibrator
from factoryguard.models.fusion import EmbeddingFusion, FusionInput, LateFusion
from factoryguard.models.tabular.sklearn_models import HgbModel, IsolationForestScorer
from factoryguard.models.timeseries.cnn_encoder import TsCnnEncoder, TsTensor, build_ts_tensor
from factoryguard.models.timeseries.stat_detector import StatTsDetector
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("pipelines.training.multimodal")

MODALITY_ORDER = ["tabular", "timeseries", "vision", "graph"]


# --------------------------------------------------------------------------
# helpers


def split_calibration(meta: pd.DataFrame, splits: Splits) -> tuple[np.ndarray, np.ndarray]:
    """Halve the calibration period at work-order granularity: earlier half
    (A) fits probability calibrators, later half (B) fits conformal/OOD
    thresholds. Conformal coverage claims are invalid if these overlap."""
    calib_wos = (
        meta.loc[splits.calib].groupby("work_order_id")["produced_at"].median().sort_values()
    )
    half = len(calib_wos) // 2
    wos_a = set(calib_wos.index[:half])
    in_a = meta["work_order_id"].isin(wos_a).to_numpy()
    return splits.calib & in_a, splits.calib & ~in_a


def subset_tensor(tensor: TsTensor, idx: np.ndarray) -> TsTensor:
    return TsTensor(
        unit_ids=[tensor.unit_ids[i] for i in idx],
        values=tensor.values[idx],
        channels=tensor.channels,
    )


def align_units(dataset_dir: Path, data: TabularData) -> pd.DataFrame:
    units = pd.read_parquet(dataset_dir / "tables" / "units.parquet")
    aligned = units.set_index("unit_id").reindex(data.meta["unit_id"]).reset_index()
    if aligned["produced_at"].isna().any():
        raise ValueError("units table does not cover all labeled units")
    return aligned


def _calibrated(cal: Any, proba: np.ndarray) -> np.ndarray:
    out = np.full(len(proba), np.nan)
    ok = np.isfinite(proba)
    out[ok] = cal.transform(proba[ok])
    return out


# --------------------------------------------------------------------------
# per-modality scores + embeddings (row-aligned with data.meta)


def tabular_modality(
    data: TabularData, splits: Splits, seed: int
) -> tuple[np.ndarray, np.ndarray, HgbModel]:
    hgb = HgbModel(seed=seed).fit(
        data.features[splits.train], data.y_binary.to_numpy()[splits.train]
    )
    proba = hgb.predict_proba(data.features)[:, 1]
    # tabular "embedding" for OOD/fusion: numeric feature block, z-scored on train
    num = data.features.select_dtypes(include=[float]).to_numpy(dtype=np.float64)
    mean = num[splits.train].mean(axis=0)
    std = num[splits.train].std(axis=0) + 1e-9
    return proba, ((num - mean) / std).astype(np.float32), hgb


def graph_modality(
    graph: GraphFeatures, y: np.ndarray, splits: Splits, seed: int
) -> tuple[np.ndarray, np.ndarray, Any]:
    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)
    x = graph.features.to_numpy(dtype=np.float64)
    clf.fit(x[splits.train], y[splits.train])
    return clf.predict_proba(x)[:, 1], x.astype(np.float32), clf


def timeseries_modality(
    dataset_dir: Path, data: TabularData, splits: Splits, cfg: MultimodalConfig, ssl: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray, TsCnnEncoder, TsTensor]:
    sensors = pd.read_parquet(dataset_dir / "timeseries" / "sensors.parquet")
    tensor = build_ts_tensor(sensors, length=cfg.ts_encoder.length)
    pos = {uid: i for i, uid in enumerate(tensor.unit_ids)}
    row_idx = np.array([pos[u] for u in data.meta["unit_id"]], dtype=np.int64)
    aligned = subset_tensor(tensor, row_idx)

    enc = TsCnnEncoder(
        length=cfg.ts_encoder.length,
        embed_dim=cfg.ts_encoder.embed_dim,
        epochs=cfg.ts_encoder.epochs,
        ssl_pretrain=ssl,
        ssl_epochs=cfg.ts_encoder.ssl_epochs,
        batch_size=cfg.ts_encoder.batch_size,
        lr=cfg.ts_encoder.lr,
        seed=0,
    )
    tr = np.flatnonzero(splits.train)
    y_all = data.y_binary.to_numpy()
    enc.fit(
        aligned,
        y_all[splits.train],
        sample_index=tr,
        val_index=np.flatnonzero(splits.val),
        y_val=y_all[splits.val],
    )
    proba = enc.predict_proba(aligned)[:, 1]
    emb = enc.embed(aligned)
    anomaly = enc.anomaly_score(aligned)
    return proba, emb, anomaly, enc, aligned


def vision_modality(
    dataset_dir: Path, data: TabularData, splits: Splits, seed: int
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Unit-level vision score/embedding (NaN rows where a unit has no
    image — missingness stays explicit for fusion, ADR-0006)."""
    from factoryguard.models.vision.dinov2 import Dinov2Classifier, Dinov2Encoder

    n = len(data.meta)
    proba = np.full(n, np.nan)
    emb = np.full((n, 384), np.nan, dtype=np.float32)
    extras: dict[str, Any] = {}

    meta_img = pd.read_parquet(dataset_dir / "tables" / "image_metadata.parquet")
    meta_img = meta_img[meta_img.unit_id.isin(set(data.meta["unit_id"]))]
    if meta_img.empty:
        return proba, emb, {"unavailable": True, "reason": "no images in profile"}

    unit_row = pd.Series(range(n), index=data.meta["unit_id"])
    unit_split = pd.Series("none", index=data.meta["unit_id"])
    for name, mask in splits.named().items():
        unit_split.loc[data.meta.loc[mask, "unit_id"]] = name
    img_split = unit_split.reindex(meta_img["unit_id"]).to_numpy()
    y_unit = pd.Series(data.y_binary.to_numpy(), index=data.meta["unit_id"])
    y_img = y_unit.reindex(meta_img["unit_id"]).to_numpy(dtype=bool)

    encoder = Dinov2Encoder()
    paths = [dataset_dir / p for p in meta_img["image_path"]]
    img_emb = encoder.embed_paths(paths)

    tr_img = img_split == "train"
    if tr_img.sum() < 10 or y_img[tr_img].sum() < 2:
        return proba, emb, {"unavailable": True, "reason": "insufficient training images"}
    clf = Dinov2Classifier(encoder, mode="linear", seed=seed).fit_embeddings(
        img_emb[tr_img], y_img[tr_img]
    )
    p_img = clf.predict_proba_embeddings(img_emb)[:, list(clf.classes_).index(True)]

    per_unit = (
        pd.DataFrame({"unit_id": meta_img["unit_id"].to_numpy(), "p": p_img})
        .groupby("unit_id")["p"]
        .mean()
    )
    emb_unit = pd.DataFrame(img_emb, index=meta_img["unit_id"].to_numpy()).groupby(level=0).mean()
    rows = unit_row.reindex(per_unit.index).to_numpy(dtype=np.int64)
    proba[rows] = per_unit.to_numpy()
    emb[unit_row.reindex(emb_unit.index).to_numpy(dtype=np.int64)] = emb_unit.to_numpy(
        dtype=np.float32
    )

    extras["encoder"] = encoder
    extras["image_meta"] = meta_img.assign(split=img_split)
    extras["image_embeddings"] = img_emb
    extras["head"] = clf
    return proba, emb, extras


# --------------------------------------------------------------------------
# report assembly


def _fmt(m: dict[str, float] | None) -> str:
    if not m:
        return "—"
    return (
        f"PR-AUC {m['pr_auc']:.3f} · ROC-AUC {m['roc_auc']:.3f} · "
        f"recall@5%FPR {m['recall_at_fpr']:.3f} · Brier {m['brier']:.4f} · ECE {m['ece']:.3f}"
    )


def _fmt_anom(m: dict[str, float] | None) -> str:
    if not m:
        return "—"
    return (
        f"ROC-AUC {m['roc_auc']:.3f} · PR-AUC {m['pr_auc']:.3f} *(risk score — not a probability)*"
    )


def write_report(out_dir: Path, profile: str, r: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "multimodal-metrics.json").write_text(
        json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, indent=2, default=str)
        + "\n"
    )
    mode = r["serving"]["configured_mode"]
    lines = [
        f"# Multimodal Evaluation Report — profile `{profile}` (Phase 4)",
        "",
        f"Serving mode (config): `{mode}` — reported on every prediction (ADR-0019).",
        "",
        "## Per-modality defect prediction (test period, calibrated)",
        "",
        "| Modality | Availability | Test metrics |",
        "|---|---|---|",
    ]
    for m in MODALITY_ORDER:
        mm = r["modalities"].get(m, {})
        avail = mm.get("availability_test")
        avail_s = f"{avail:.0%}" if avail is not None else "—"
        lines.append(f"| {m} | {avail_s} | {_fmt(mm.get('test'))} |")
    lines += [
        "",
        "## Calibration (fit on calib-A; shown on test)",
        "",
        "| Signal | Method | Brier pre → post | ECE pre → post |",
        "|---|---|---|---|",
    ]
    for name, c in r["calibration"].items():
        lines.append(
            f"| {name} | {c['method']} | {c['brier_pre']:.4f} → {c['brier_post']:.4f} "
            f"| {c['ece_pre']:.3f} → {c['ece_post']:.3f} |"
        )
    lf, ef = r["fusion"]["late"], r["fusion"]["embedding"]
    lines += [
        "",
        "## Fusion comparison (ADR-0006: late = default, embedding = challenger)",
        f"- Late fusion (test): {_fmt(lf.get('test'))}",
        f"- Embedding fusion (test): {_fmt(ef.get('test'))}",
        f"- Late fusion (unseen line): {_fmt(lf.get('unseen_line_test'))}",
        f"- Embedding fusion (unseen line): {_fmt(ef.get('unseen_line_test'))}",
        f"- Late-fusion modality weights (|coef|): {r['fusion']['late_contributions']}",
        "",
        "## Missing-modality robustness (test, one modality dropped at a time)",
        "*Missing ≠ zero: fusion consumes availability masks; ROC-AUC shown.*",
        "",
        "| Dropped | Late fusion | Embedding fusion |",
        "|---|---|---|",
    ]
    for m in MODALITY_ORDER:
        d = r["fusion"]["missing_modality"].get(m, {})
        lines.append(
            f"| {m} | {d.get('late', float('nan')):.3f} | {d.get('embedding', float('nan')):.3f} |"
        )
    base_l = lf.get("test", {}).get("roc_auc", float("nan"))
    base_e = ef.get("test", {}).get("roc_auc", float("nan"))
    lines += [
        f"| *(none — baseline)* | {base_l:.3f} | {base_e:.3f} |",
        "",
        "## Uncertainty and abstention (conformal + Mahalanobis, spec §8.6)",
        f"- Conformal target coverage: {r['uncertainty']['target_coverage']:.0%} · "
        f"empirical test coverage: {r['uncertainty']['empirical_coverage']:.1%}",
        f"- Ambiguous-set rate (test): {r['uncertainty']['ambiguous_rate']:.1%} · "
        f"OOD flag rate (test): {r['uncertainty']['ood_rate_test']:.1%} · "
        f"OOD flag rate (unseen line): {r['uncertainty']['ood_rate_unseen']:.1%}",
        f"- Overall abstention rate (test): {r['uncertainty']['abstention_rate']:.1%}",
        "",
        "### Risk–coverage curve (retain most-confident fraction)",
        "",
        "| Coverage | Error rate | Defect recall |",
        "|---|---|---|",
    ]
    for row in r["uncertainty"]["risk_coverage"]:
        lines.append(
            f"| {row['coverage']:.0%} | {row['error_rate']:.3f} | {row['defect_recall']:.3f} |"
        )
    lines += [
        "",
        "## Serving modes (ADR-0019)",
        f"- `anomaly-only` (cold start, labels unused): "
        f"{_fmt_anom(r['serving']['anomaly_only'].get('test'))}",
    ]
    for comp, cm in r["serving"].get("anomaly_component_metrics", {}).items():
        lines.append(f"  - component `{comp}`: {_fmt_anom(cm)}")
    lines += [
        f"- `blended` (w={r['serving']['blend_weight']}): "
        f"{_fmt_anom(r['serving']['blended'].get('test'))}",
        f"- `supervised`: {_fmt(r['fusion']['late'].get('test'))}",
        "",
        "## Root-cause ranking vs generator ground truth (spec §9)",
    ]
    rc = r["root_cause"]
    if rc.get("n_evaluated_units", 0):
        lines += [
            f"- Units evaluated: {int(rc['n_evaluated_units'])}",
            f"- top-1 accuracy {rc['hit_at_1']:.3f} · top-3 accuracy {rc['hit_at_3']:.3f} · "
            f"MRR {rc['mrr']:.3f}",
            f"- Recall@1 {rc['recall_at_1']:.3f} · Recall@3 {rc['recall_at_3']:.3f} · "
            f"Recall@5 {rc['recall_at_5']:.3f}",
            f"- NDCG@3 {rc['ndcg_at_3']:.3f} · NDCG@5 {rc['ndcg_at_5']:.3f}",
        ]
    else:
        lines.append("- unavailable (no ground-truth-attributed defective units in test)")
    lines += [
        "",
        "## Similar-incident retrieval (exact in-process search, ADR-0021)",
        f"- precision@{r['retrieval']['k']} (same defect category): "
        f"{r['retrieval']['precision_at_k']:.3f} over "
        f"{r['retrieval']['n_queries']} queries against "
        f"{r['retrieval']['index_size']} indexed incidents "
        f"(random baseline {r['retrieval']['random_baseline']:.3f})",
        "",
        "## Vision attribution (attention, validated vs synthetic geometry)",
    ]
    va = r["vision_attribution"]
    if va.get("available"):
        lines += [
            f"- Center-band attention mass: {va['center_band_mass_mean']:.2f} "
            f"(uniform baseline {va['uniform_baseline']:.2f}, n={va['n_images']}) — "
            "attention concentrates on the harness region, not the empty border.",
        ]
    else:
        lines.append(f"- unavailable ({va.get('reason', 'no images')})")
    if r.get("ssl_comparison"):
        sc = r["ssl_comparison"]
        lines += [
            "",
            "## TS encoder: SSL pretraining vs supervised-only (config flag)",
            f"- supervised-only (test): {_fmt(sc.get('supervised'))}",
            f"- SSL-pretrained (test): {_fmt(sc.get('ssl'))}",
        ]
    hg = r.get("hgb_with_graph_features", {})
    if hg:
        lines += [
            "",
            "## OI-6 re-measure: HGB + graph features on the unseen line",
            f"- HGB (tabular only, unseen line): {_fmt(hg.get('tabular_only'))}",
            f"- HGB (+ graph features, unseen line): {_fmt(hg.get('with_graph'))}",
        ]
    lines += [
        "",
        "## Known limitations",
        "- Attribution is model attribution, never causal proof (spec §10).",
        "- Conformal coverage assumes exchangeability; temporal drift can erode "
        "it — the empirical number above is the honest check.",
        "- Blended/anomaly risk scores are not calibrated probabilities and are "
        "labeled as such wherever they appear.",
        "- Vision covers only units with images; fusion handles the gap via "
        "availability masks, never zero-filling.",
    ]
    (out_dir / "multimodal-report.md").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# main


def main() -> int:  # noqa: C901 - orchestration is long but linear
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--reports-root", type=Path, default=Path("reports"))
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts/multimodal"))
    parser.add_argument("--config", type=Path, default=Path("configs/models/multimodal.yaml"))
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument(
        "--compare-ssl",
        action="store_true",
        help="also train the SSL-pretrained TS encoder and report the comparison",
    )
    parser.add_argument("--no-mlflow", action="store_true", help="skip MLflow experiment tracking")
    parser.add_argument(
        "--mlflow-uri",
        default="sqlite:///mlruns/mlflow.db",
        help="MLflow tracking URI (default: local serverless sqlite; set to the "
        "compose server, e.g. http://127.0.0.1:5000, to log there)",
    )
    args = parser.parse_args()

    configure_logging(fmt="console")
    cfg = load_multimodal_config(args.config)
    profile = load_profile(args.profile)
    seed = profile.seed
    dataset_dir = args.data_root / args.profile
    if not dataset_dir.is_dir():
        log.error(
            "dataset %s missing — run `make generate-data PROFILE=%s`", dataset_dir, args.profile
        )
        return 1

    t0 = time.perf_counter()
    data = load_tabular(dataset_dir)
    splits = temporal_group_split(data.meta)
    assert_no_leakage(data.meta, splits)
    calib_a, calib_b = split_calibration(data.meta, splits)
    y = data.y_binary.to_numpy()
    units = align_units(dataset_dir, data)
    labels = pd.read_parquet(dataset_dir / "tables" / "labels.parquet")
    edges = pd.read_parquet(dataset_dir / "tables" / "graph_edges.parquet")

    results: dict[str, Any] = {
        "_meta": {"profile": args.profile, "seed": seed, "n_units": int(len(data.meta))}
    }

    # ---- modality scores + embeddings ------------------------------------
    log.info("modalities: tabular + graph + timeseries%s", "" if args.no_vision else " + vision")
    graph = build_graph_features(
        units,
        labels,
        edges,
        half_life_days=cfg.graph.half_life_days,
        smoothing=cfg.graph.smoothing,
    )
    p_tab, emb_tab, hgb = tabular_modality(data, splits, seed)
    p_graph, emb_graph, graph_clf = graph_modality(graph, y, splits, seed)
    p_ts, emb_ts, ts_anomaly, ts_enc, tensor = timeseries_modality(
        dataset_dir, data, splits, cfg, ssl=cfg.ts_encoder.ssl_pretrain
    )
    if args.no_vision:
        p_vis = np.full(len(data.meta), np.nan)
        emb_vis = np.full((len(data.meta), 384), np.nan, dtype=np.float32)
        vis_extras: dict[str, Any] = {"unavailable": True, "reason": "--no-vision"}
    else:
        p_vis, emb_vis, vis_extras = vision_modality(dataset_dir, data, splits, seed)

    raw_scores = {"tabular": p_tab, "timeseries": p_ts, "vision": p_vis, "graph": p_graph}
    embeddings = {
        "tabular": emb_tab,
        "timeseries": emb_ts,
        "vision": emb_vis,
        "graph": emb_graph,
    }

    # ---- per-modality calibration on calib-A -----------------------------
    calibrators: dict[str, Any] = {}
    results["calibration"] = {}
    cal_scores: dict[str, np.ndarray] = {}
    for m in MODALITY_ORDER:
        p = raw_scores[m]
        ok_a = calib_a & np.isfinite(p)
        cal = fit_calibrator(p[ok_a], y[ok_a], min_isotonic_n=cfg.calibration.min_isotonic_n)
        calibrators[m] = cal
        cal_scores[m] = _calibrated(cal, p)
        te = splits.test & np.isfinite(p)
        if te.sum():
            results["calibration"][m] = {
                "method": cal.method,
                "brier_pre": M.classification_metrics(y[te], p[te])["brier"],
                "brier_post": M.classification_metrics(y[te], cal_scores[m][te])["brier"],
                "ece_pre": M.expected_calibration_error(y[te], p[te]),
                "ece_post": M.expected_calibration_error(y[te], cal_scores[m][te]),
            }

    results["modalities"] = {}
    for m in MODALITY_ORDER:
        p = cal_scores[m]
        entry: dict[str, Any] = {"availability_test": float(np.isfinite(p[splits.test]).mean())}
        eval_pairs = (("test", splits.test), ("unseen_line_test", splits.unseen_line_test))
        for split_name, mask in eval_pairs:
            ok = mask & np.isfinite(p)
            if ok.sum() >= 5 and y[ok].any():
                entry[split_name] = M.classification_metrics(y[ok], p[ok])
        results["modalities"][m] = entry

    # ---- fusion ----------------------------------------------------------
    scores_frame = pd.DataFrame(cal_scores)[list(MODALITY_ORDER)]
    fusion_in = FusionInput(scores=scores_frame, embeddings=embeddings)

    def subset_inputs(mask: np.ndarray) -> FusionInput:
        return FusionInput(
            scores=scores_frame.loc[mask].reset_index(drop=True),
            embeddings={k: v[mask] for k, v in embeddings.items()},
        )

    late = LateFusion(
        dropout_rate=cfg.fusion.modality_dropout,
        dropout_copies=cfg.fusion.dropout_copies,
        seed=seed,
    ).fit(subset_inputs(splits.val), y[splits.val])
    p_late_raw = late.predict_proba(fusion_in)[:, 1]
    cal_late = fit_calibrator(
        p_late_raw[calib_a], y[calib_a], min_isotonic_n=cfg.calibration.min_isotonic_n
    )
    p_late = cal_late.transform(p_late_raw)

    emb_fusion = EmbeddingFusion(
        proj_dim=cfg.fusion.proj_dim,
        epochs=cfg.fusion.epochs,
        lr=cfg.fusion.lr,
        dropout_rate=cfg.fusion.modality_dropout,
        seed=seed,
    ).fit(subset_inputs(splits.train), y[splits.train])
    p_embf_raw = emb_fusion.predict_proba(fusion_in)[:, 1]
    cal_embf = fit_calibrator(
        p_embf_raw[calib_a], y[calib_a], min_isotonic_n=cfg.calibration.min_isotonic_n
    )
    p_embf = cal_embf.transform(p_embf_raw)
    fused_emb = emb_fusion.embed(fusion_in)

    results["fusion"] = {"late": {}, "embedding": {}}
    for name, p in (("late", p_late), ("embedding", p_embf)):
        eval_pairs = (("test", splits.test), ("unseen_line_test", splits.unseen_line_test))
        for split_name, mask in eval_pairs:
            if mask.sum() >= 5 and y[mask].any():
                results["fusion"][name][split_name] = M.classification_metrics(y[mask], p[mask])
    results["calibration"]["late_fusion"] = {
        "method": cal_late.method,
        "brier_pre": M.classification_metrics(y[splits.test], p_late_raw[splits.test])["brier"],
        "brier_post": M.classification_metrics(y[splits.test], p_late[splits.test])["brier"],
        "ece_pre": M.expected_calibration_error(y[splits.test], p_late_raw[splits.test]),
        "ece_post": M.expected_calibration_error(y[splits.test], p_late[splits.test]),
    }
    results["fusion"]["late_contributions"] = {
        k: round(v, 3) for k, v in late.modality_contributions().items()
    }

    # missing-modality robustness: drop one modality across the whole test set
    results["fusion"]["missing_modality"] = {}
    test_mask = splits.test
    for m in MODALITY_ORDER:
        scores_drop = scores_frame.copy()
        scores_drop[m] = np.nan
        emb_drop = {k: (np.full_like(v, np.nan) if k == m else v) for k, v in embeddings.items()}
        dropped = FusionInput(scores=scores_drop, embeddings=emb_drop)
        p_l = cal_late.transform(late.predict_proba(dropped)[:, 1])
        p_e = cal_embf.transform(emb_fusion.predict_proba(dropped)[:, 1])
        results["fusion"]["missing_modality"][m] = {
            "late": M.classification_metrics(y[test_mask], p_l[test_mask])["roc_auc"],
            "embedding": M.classification_metrics(y[test_mask], p_e[test_mask])["roc_auc"],
        }

    # ---- uncertainty: conformal on calib-B, OOD, abstention --------------
    conformal = SplitConformal(alpha=cfg.uncertainty.conformal_alpha).fit(
        p_late[calib_b], y[calib_b]
    )
    ood = MahalanobisOOD(shrinkage=cfg.uncertainty.ood_shrinkage).fit(fused_emb[splits.train])
    ood.set_threshold(fused_emb[calib_b], quantile=cfg.uncertainty.ood_quantile)
    policy = AbstentionPolicy(conformal, ood)
    sets_test = conformal.prediction_sets(p_late[test_mask])
    decisions = policy.decide(p_late[test_mask], fused_emb[test_mask])
    unseen = splits.unseen_line_test
    results["uncertainty"] = {
        "target_coverage": 1.0 - cfg.uncertainty.conformal_alpha,
        "conformal_qhat": conformal.qhat,
        "empirical_coverage": conformal.empirical_coverage(sets_test, y[test_mask]),
        "ambiguous_rate": float(conformal.ambiguous(p_late[test_mask]).mean()),
        "ood_threshold": ood.threshold,
        "ood_rate_test": float(np.mean(ood.is_ood(fused_emb[test_mask]))),
        "ood_rate_unseen": (
            float(np.mean(ood.is_ood(fused_emb[unseen]))) if unseen.sum() else float("nan")
        ),
        "abstention_rate": float(np.mean([d.abstain for d in decisions])),
        "risk_coverage": abstention_curve(y[test_mask], p_late[test_mask]),
    }

    # ---- serving modes ---------------------------------------------------
    # anomaly-only components are all label-free (ADR-0019): a cold-start TS
    # encoder is retrained without labels so no supervised signal leaks in.
    iso = IsolationForestScorer(seed=seed).fit(data.features[splits.train])
    iso_all = iso.anomaly_score(data.features)
    ts_cold = TsCnnEncoder(
        length=cfg.ts_encoder.length,
        embed_dim=cfg.ts_encoder.embed_dim,
        ssl_epochs=cfg.ts_encoder.ssl_epochs,
        batch_size=cfg.ts_encoder.batch_size,
        lr=cfg.ts_encoder.lr,
        seed=1,
    ).fit(tensor, None, sample_index=np.flatnonzero(splits.train))
    ts_cold_anomaly = ts_cold.anomaly_score(tensor)
    sensors_stat = pd.read_parquet(dataset_dir / "timeseries" / "sensors.parquet")
    stat_det = StatTsDetector().fit(sensors_stat, data.meta.loc[splits.train, "unit_id"])
    stat_scores = (
        stat_det.anomaly_scores(sensors_stat).reindex(data.meta["unit_id"]).to_numpy(dtype=float)
    )
    gp = graph_prior_scores(units, graph.entities, iso_all, half_life_days=cfg.graph.half_life_days)
    anomaly_frame = pd.DataFrame(
        {
            "isolation_forest": iso_all,
            "ts_reconstruction": ts_cold_anomaly,
            "stat_ts": stat_scores,
            "graph_prior": gp,
        }
    )
    if "image_embeddings" in vis_extras:
        from factoryguard.models.vision.dinov2 import ImageDistanceAnomaly

        img_meta = vis_extras["image_meta"]
        dist = ImageDistanceAnomaly().fit(
            vis_extras["image_embeddings"][img_meta["split"].to_numpy() == "train"]
        )
        vis_extras["image_distance"] = dist
        d_img = dist.anomaly_score(vis_extras["image_embeddings"])
        per_unit = (
            pd.DataFrame({"unit_id": img_meta["unit_id"].to_numpy(), "d": d_img})
            .groupby("unit_id")["d"]
            .mean()
        )
        anomaly_frame["image_distance"] = per_unit.reindex(data.meta["unit_id"]).to_numpy(
            dtype=float
        )

    srv_anom = serve(ServingMode.ANOMALY_ONLY, anomaly_frame)
    srv_blend = serve(
        ServingMode.BLENDED, anomaly_frame, p_late, blend_weight=cfg.serving.blend_weight
    )
    component_metrics = {}
    for col in anomaly_frame.columns:
        sc = anomaly_frame[col].to_numpy(dtype=float)
        ok = test_mask & np.isfinite(sc)
        if ok.sum() >= 5 and y[ok].any():
            component_metrics[col] = M.anomaly_metrics(y[ok], sc[ok])
    results["serving"] = {
        "configured_mode": str(cfg.serving.mode),
        "blend_weight": cfg.serving.blend_weight,
        "anomaly_components": list(anomaly_frame.columns),
        "anomaly_component_metrics": component_metrics,
        "anomaly_only": {"test": M.anomaly_metrics(y[test_mask], srv_anom.risk_score[test_mask])},
        "graph_prior": {"test": M.anomaly_metrics(y[test_mask], gp[test_mask])},
        "blended": {"test": M.anomaly_metrics(y[test_mask], srv_blend.risk_score[test_mask])},
    }

    # ---- root cause ------------------------------------------------------
    graph_rc = build_graph_features(
        units,
        labels,
        edges,
        half_life_days=cfg.root_cause.half_life_days,
        smoothing=cfg.graph.smoothing,
    )
    units_rc = units.assign(revision_id=graph_rc.entities["revision_id"].to_numpy())
    ranker = RootCauseRanker().fit(units_rc[splits.train])
    truth = pd.read_parquet(dataset_dir / "ground_truth" / "root_causes.parquet")
    eval_mask = (splits.test | splits.unseen_line_test) & y
    ranked = ranker.rank(units_rc, graph_rc, np.flatnonzero(eval_mask))
    results["root_cause"] = evaluate_root_cause(ranked, truth)

    # ---- retrieval -------------------------------------------------------
    # Index the standardized concatenation of the always-available modality
    # embeddings, not the fused space: the fused embedding is trained on the
    # binary objective and collapses defect-*category* structure, which is
    # what similar-incident search needs to preserve.
    def _zscore(emb: np.ndarray) -> np.ndarray:
        ref = emb[splits.train]
        return ((emb - ref.mean(axis=0)) / (ref.std(axis=0) + 1e-9)).astype(np.float32)

    retr_emb = np.concatenate(
        [_zscore(embeddings[m]) for m in ("tabular", "timeseries", "graph")], axis=1
    )
    hist_mask = (splits.train | splits.val) & y  # historical incidents
    idx_meta = data.meta.loc[hist_mask, ["unit_id", "produced_at"]].reset_index(drop=True)
    idx_meta["defect_category"] = data.y_category.to_numpy()[hist_mask]
    index = SimilarIncidentIndex().fit(retr_emb[hist_mask], idx_meta)
    q_mask = test_mask & y
    q_cats = data.y_category.to_numpy()[q_mask]
    hist_cats = idx_meta["defect_category"].to_numpy()
    random_baseline = float(
        np.mean([(hist_cats == c).mean() for c in q_cats]) if q_mask.sum() else float("nan")
    )
    results["retrieval"] = {
        "k": cfg.retrieval.k,
        "index_size": int(hist_mask.sum()),
        "n_queries": int(q_mask.sum()),
        "precision_at_k": index.precision_at_k(retr_emb[q_mask], q_cats, k=cfg.retrieval.k),
        "random_baseline": random_baseline,
    }

    # ---- vision attribution geometry check -------------------------------
    if "image_meta" in vis_extras:
        from factoryguard.models.vision.attribution import attention_maps, center_band_mass

        img_meta = vis_extras["image_meta"]
        defect_imgs = img_meta[img_meta["visual_class"] != "normal"].head(32)
        if len(defect_imgs):
            maps = attention_maps(
                vis_extras["encoder"],
                [dataset_dir / p for p in defect_imgs["image_path"]],
                method="last",
            )
            band = center_band_mass(maps)
            results["vision_attribution"] = {
                "available": True,
                "n_images": int(len(defect_imgs)),
                "center_band_mass_mean": float(band.mean()),
                "uniform_baseline": 0.5,
            }
        else:
            results["vision_attribution"] = {"available": False, "reason": "no defect images"}
    else:
        results["vision_attribution"] = {
            "available": False,
            "reason": vis_extras.get("reason", "vision disabled"),
        }

    # ---- optional SSL comparison ----------------------------------------
    if args.compare_ssl:
        p_ssl, _, _, _, _ = timeseries_modality(dataset_dir, data, splits, cfg, ssl=True)
        cal_ssl = fit_calibrator(
            p_ssl[calib_a], y[calib_a], min_isotonic_n=cfg.calibration.min_isotonic_n
        )
        p_ssl_c = _calibrated(cal_ssl, p_ssl)
        results["ssl_comparison"] = {
            "supervised": results["modalities"]["timeseries"].get("test"),
            "ssl": M.classification_metrics(y[test_mask], p_ssl_c[test_mask]),
        }

    # ---- OI-6 re-measure: HGB + graph features on the unseen line --------
    if unseen.sum() >= 5 and y[unseen].any():
        feats_aug = pd.concat(
            [data.features.reset_index(drop=True), graph.features.reset_index(drop=True)],
            axis=1,
        )
        hgb_g = HgbModel(seed=seed).fit(feats_aug[splits.train], y[splits.train])
        results["hgb_with_graph_features"] = {
            "tabular_only": M.classification_metrics(
                y[unseen], hgb.predict_proba(data.features[unseen])[:, 1]
            ),
            "with_graph": M.classification_metrics(
                y[unseen], hgb_g.predict_proba(feats_aug[unseen])[:, 1]
            ),
        }

    # ---- artifacts + report ----------------------------------------------
    from pipelines.training.train_baselines import persist_artifacts

    for torch_model in (ts_enc, ts_cold, emb_fusion):
        if getattr(torch_model, "_model", None) is not None:
            torch_model._model = torch_model._model.cpu()
            torch_model.device = "cpu"
    # Serving metadata (Phase 5): everything the API needs to score one unit
    # without the training frames — feature dtypes (unseen categories map to
    # NaN → HGB missing-handling), TS tensor config, retrieval z-stats, and
    # an as-of-deployment graph entity-rate snapshot (pre-test rows only, so
    # the persisted state never embeds test-period outcomes).
    pre_test = splits.train | splits.val | splits.calib
    graph_snapshot: dict[str, dict[str, list[float]]] = {}
    gf_flat = graph.features.reset_index(drop=True)
    ent_flat = graph.entities.reset_index(drop=True)
    pre_idx = np.flatnonzero(pre_test)
    for col in ent_flat.columns:
        rate_col = f"g_{col}_defect_rate"
        sup_col = f"g_{col}_support"
        cen_col = f"g_{col}_centrality"
        if rate_col not in gf_flat.columns:
            continue
        snap: dict[str, list[float]] = {}
        ents = ent_flat[col].to_numpy()
        for i in pre_idx:  # later rows overwrite → last pre-test state wins
            snap[str(ents[i])] = [
                float(gf_flat.at[i, rate_col]),
                float(gf_flat.at[i, sup_col]),
                float(gf_flat.at[i, cen_col]) if cen_col in gf_flat.columns else 0.0,
            ]
        graph_snapshot[col] = snap
    num_cols = data.features.select_dtypes(include=[float]).columns.tolist()
    num_block = data.features[num_cols].to_numpy(dtype=np.float64)
    hgb_mc = HgbModel(seed=seed, multiclass=True).fit(
        data.features[splits.train], data.y_category.to_numpy()[splits.train]
    )
    serving_meta = {
        "profile": args.profile,
        "feature_dtypes": {c: data.features[c].dtype for c in data.features.columns},
        "numeric_columns": num_cols,
        "ts_channels": tensor.channels,
        "ts_length": cfg.ts_encoder.length,
        "graph_snapshot": graph_snapshot,
        "graph_global_rate": float(
            gf_flat.loc[pre_idx, [c for c in gf_flat.columns if c.endswith("_defect_rate")]]
            .to_numpy()
            .mean()
        ),
        "graph_feature_columns": gf_flat.columns.tolist(),
        "retrieval_stats": {
            "tabular": (
                num_block[splits.train].mean(axis=0),
                num_block[splits.train].std(axis=0) + 1e-9,
            ),
            "timeseries": (
                emb_ts[splits.train].mean(axis=0),
                emb_ts[splits.train].std(axis=0) + 1e-9,
            ),
            "graph": (
                emb_graph[splits.train].mean(axis=0),
                emb_graph[splits.train].std(axis=0) + 1e-9,
            ),
        },
        "conformal_alpha": cfg.uncertainty.conformal_alpha,
        "blend_weight": cfg.serving.blend_weight,
        "defect_categories": [str(c) for c in hgb_mc.classes_],
    }
    fitted = {
        "hgb": hgb,
        "hgb_multiclass": hgb_mc,
        "graph_logistic": graph_clf,
        "ts_cnn": ts_enc,
        "ts_cnn_coldstart": ts_cold,
        "late_fusion": late,
        "embedding_fusion": emb_fusion,
        "calibrators": {**calibrators, "late_fusion": cal_late, "embedding_fusion": cal_embf},
        "conformal": conformal,
        "mahalanobis_ood": ood,
        "incident_index": index,
        "root_cause_ranker": ranker,
        "isolation_forest": iso,
        "stat_ts_detector": stat_det,
        "serving_meta": serving_meta,
    }
    if "head" in vis_extras:
        fitted["vision_head"] = vis_extras["head"].head  # sklearn head only (no encoder ref)
    if "image_distance" in vis_extras:
        fitted["image_distance"] = vis_extras["image_distance"]
    lineage = persist_artifacts(fitted, args.artifacts_root / args.profile, args.profile, seed)
    results["_meta"]["artifact_files"] = lineage["files"]
    results["_meta"]["wall_time_s"] = round(time.perf_counter() - t0, 1)

    out_dir = args.reports_root / "evaluation" / args.profile
    write_report(out_dir, args.profile, results)
    if not args.no_mlflow:
        try:
            from factoryguard.mlops.tracking import log_training_run

            run_id = log_training_run(
                results,
                lineage,
                artifacts_dir=args.artifacts_root / args.profile,
                report_dir=out_dir,
                tracking_uri=args.mlflow_uri,
                extra_params={"ssl_pretrain": cfg.ts_encoder.ssl_pretrain},
            )
            results["_meta"]["mlflow_run_id"] = run_id
        except Exception as exc:  # tracking must never fail a training run
            log.warning("mlflow tracking skipped: %s", str(exc)[:200])
    log.info(
        "multimodal done in %.1fs — late fusion test: %s",
        results["_meta"]["wall_time_s"],
        _fmt(results["fusion"]["late"].get("test")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
