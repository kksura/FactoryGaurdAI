"""Prediction service: Phase 4 artifacts → contract v1 responses.

Framework-free on purpose — the FastAPI layer is a thin adapter over this
class, so the whole prediction path is unit-testable without HTTP.

Serving rules carried over from training (do not "simplify" away):
- categorical values unseen in training cast to NaN via the persisted
  dtypes → HGB's native missing-handling (never a fake category);
- a modality the caller didn't provide (or declared missing) flows through
  the fusion availability masks — never zero-filled (ADR-0006);
- graph features come from the persisted pre-test entity-rate snapshot;
  unknown entities fall back to the global prior with zero support;
- artifact integrity is verified against the SHA-256 manifest at load
  time (fail-closed when ``verify_checksums`` is on).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
import pandas as pd

from factoryguard.contracts.v1 import (
    AssistantOutput,
    EvidenceItem,
    FeedbackRequest,
    FeedbackResponse,
    Modality,
    ModalityStatus,
    PredictionRequest,
    PredictionResponse,
    RootCauseCandidate,
    SimilarIncident,
    UncertaintyInfo,
)
from factoryguard.features.graph import GraphFeatures
from factoryguard.inference.serving import ServingMode, serve
from factoryguard.inference.uncertainty import AbstentionPolicy
from factoryguard.models.timeseries.cnn_encoder import TsTensor, build_ts_tensor
from factoryguard.recommendations.engine import PredictionContext, RecommendationEngine
from factoryguard.security.checksums import verify_manifest

log = logging.getLogger(__name__)

_MODALITIES = ["tabular", "timeseries", "vision", "graph"]


class PredictionServiceError(Exception):
    pass


@dataclass
class ArtifactBundle:
    """Loaded, checksum-verified Phase 4 model artifacts."""

    models: dict[str, Any]
    meta: dict[str, Any]
    lineage: dict[str, Any]
    path: Path

    @classmethod
    def load(cls, path: Path, verify_checksums: bool = True) -> ArtifactBundle:
        if verify_checksums:
            verify_manifest(path, path / "manifest.json")
        models = {f.stem: joblib.load(f) for f in sorted(path.glob("*.joblib"))}
        if "serving_meta" not in models:
            raise PredictionServiceError(
                f"{path} has no serving_meta artifact — re-run train_multimodal "
                "(Phase 5 extended the persisted artifact set)"
            )
        meta = models.pop("serving_meta")
        lineage = json.loads((path / "lineage.json").read_text())
        return cls(models=models, meta=meta, lineage=lineage, path=path)

    @property
    def model_version(self) -> str:
        return f"multimodal-{self.lineage.get('git_commit', 'unknown')[:12]}"


@dataclass
class _ModalityResult:
    available: bool
    reason: str = ""
    raw_score: float = float("nan")
    embedding: np.ndarray | None = None


class PredictionService:
    def __init__(
        self,
        bundle: ArtifactBundle,
        serving_mode: ServingMode = ServingMode.SUPERVISED,
        storage_root: Path | None = None,
        enable_vision: bool = False,
        summarizer: Any | None = None,
        log_dir: Path | None = None,
    ) -> None:
        from factoryguard.assistants import TemplateSummarizer

        self.bundle = bundle
        self.mode = serving_mode
        self.storage_root = storage_root
        self.enable_vision = enable_vision
        self.summarizer = summarizer or TemplateSummarizer()
        self.recommender = RecommendationEngine()
        self._encoder: Any = None
        self._lock = threading.Lock()
        self._predictions: dict[str, PredictionResponse] = {}
        self._log_dir = log_dir
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
        self._feedback_count = 0

    # ------------------------------------------------------------ modalities

    def _tabular_frame(self, req: PredictionRequest) -> pd.DataFrame:
        u, m = req.unit, req.measurements
        row: dict[str, Any] = {
            "plant_id": u.plant_id,
            "line_id": u.line_id,
            "machine_id": u.machine_id,
            "tool_id": u.tool_id,
            "product_id": u.product_id,
            "revision": u.revision,
            "family": u.family,
            "shift": u.shift,
            "terminal_lot_id": u.terminal_lot_id,
            **m.model_dump(),
            "crimp_height_deviation_mm": m.crimp_height_mm - m.crimp_height_setpoint_mm,
            "hour_of_day": float(u.produced_at.hour),
            "day_of_week": float(u.produced_at.weekday()),
        }
        dtypes: dict[str, Any] = self.bundle.meta["feature_dtypes"]
        frame = pd.DataFrame([{c: row.get(c) for c in dtypes}])
        for col, dtype in dtypes.items():
            # unseen categorical values become NaN here — HGB treats them as
            # missing, exactly like training-time missingness
            frame[col] = frame[col].astype(dtype)
        return frame

    def _graph_row(self, req: PredictionRequest) -> tuple[pd.DataFrame, pd.DataFrame]:
        u = req.unit
        entity_values = {
            "machine_id": u.machine_id,
            "tool_id": u.tool_id,
            "operator_id": u.operator_id,
            "terminal_lot_id": u.terminal_lot_id,
            "wire_lot_id": u.wire_lot_id,
            "revision_id": f"{u.product_id}:{u.revision}",
            "line_id": u.line_id,
            "supplier_id": "UNKNOWN",  # lot→supplier resolution is a training-
            # time graph traversal; at serve time the supplier column falls
            # back to the prior (support 0) unless the snapshot knows the lot
        }
        snapshot: dict[str, dict[str, list[float]]] = self.bundle.meta["graph_snapshot"]
        prior = float(self.bundle.meta["graph_global_rate"])
        feats: dict[str, float] = {}
        for col, value in entity_values.items():
            rate, support, centrality = snapshot.get(col, {}).get(str(value), [prior, 0.0, 0.0])
            feats[f"g_{col}_defect_rate"] = rate
            feats[f"g_{col}_support"] = support
            if f"g_{col}_centrality" in self.bundle.meta["graph_feature_columns"]:
                feats[f"g_{col}_centrality"] = centrality
        cols = self.bundle.meta["graph_feature_columns"]
        gf = pd.DataFrame(
            [[feats.get(c, prior if c.endswith("_defect_rate") else 0.0) for c in cols]],
            columns=cols,
        )
        entities = pd.DataFrame([entity_values])
        return gf, entities

    def _ts_tensor(self, req: PredictionRequest) -> TsTensor | None:
        if req.sensors is None:
            return None
        channels: list[str] = self.bundle.meta["ts_channels"]
        frames = []
        for ch, values in req.sensors.channels.items():
            if ch not in channels:
                raise PredictionServiceError(f"unknown sensor channel: {ch}")
            arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float32)
            frames.append(
                pd.DataFrame(
                    {
                        "unit_id": req.unit.unit_id,
                        "channel": ch,
                        "t": np.arange(len(arr), dtype=np.int32),
                        "value": arr,
                    }
                )
            )
        long = pd.concat(frames, ignore_index=True)
        return build_ts_tensor(long, length=int(self.bundle.meta["ts_length"]), channels=channels)

    def _resolve_image(self, ref: str) -> Path:
        if self.storage_root is None:
            raise PredictionServiceError("no storage root configured for image refs")
        root = self.storage_root.resolve()
        candidate = (root / ref).resolve()
        if not candidate.is_relative_to(root):  # path traversal
            raise PredictionServiceError(f"image ref escapes storage root: {ref}")
        if not candidate.is_file():
            raise PredictionServiceError(f"image not found: {ref}")
        return candidate

    def _vision(self, req: PredictionRequest) -> tuple[_ModalityResult, float, bool]:
        """→ (result, image_distance_anomaly, quality_degraded)."""
        if Modality.VISION in req.declared_missing:
            return _ModalityResult(False, "declared missing"), float("nan"), False
        if not req.image_refs:
            return _ModalityResult(False, "no image reference supplied"), float("nan"), False
        if not self.enable_vision or "vision_head" not in self.bundle.models:
            return (
                _ModalityResult(False, "vision disabled in this deployment"),
                float("nan"),
                False,
            )
        from factoryguard.models.vision.quality import assess_batch

        paths = [self._resolve_image(r) for r in req.image_refs]
        if self._encoder is None:
            from factoryguard.models.vision.dinov2 import Dinov2Encoder

            self._encoder = Dinov2Encoder()
        emb = self._encoder.embed_paths(paths)
        head = self.bundle.models["vision_head"]
        proba = float(np.mean(head.predict_proba(emb)[:, list(head.classes_).index(True)]))
        distance = float("nan")
        if "image_distance" in self.bundle.models:
            distance = float(np.mean(self.bundle.models["image_distance"].anomaly_score(emb)))
        degraded = any(q.is_degraded for q in assess_batch(paths))
        return (
            _ModalityResult(True, raw_score=proba, embedding=emb.mean(axis=0)),
            distance,
            degraded,
        )

    # --------------------------------------------------------------- predict

    def predict(self, req: PredictionRequest) -> PredictionResponse:
        t0 = time.perf_counter()
        models, meta = self.bundle.models, self.bundle.meta
        results: dict[str, _ModalityResult] = {}

        # tabular
        tab_frame = self._tabular_frame(req)
        num_block = tab_frame[meta["numeric_columns"]].to_numpy(dtype=np.float64)
        if Modality.TABULAR in req.declared_missing:
            results["tabular"] = _ModalityResult(False, "declared missing")
        else:
            results["tabular"] = _ModalityResult(
                True,
                raw_score=float(models["hgb"].predict_proba(tab_frame)[0, 1]),
                embedding=self._zscore("tabular", num_block)[0],
            )

        # graph
        gf_row, ent_row = self._graph_row(req)
        if Modality.GRAPH in req.declared_missing:
            results["graph"] = _ModalityResult(False, "declared missing")
        else:
            results["graph"] = _ModalityResult(
                True,
                raw_score=float(models["graph_logistic"].predict_proba(gf_row.to_numpy())[0, 1]),
                embedding=gf_row.to_numpy(dtype=np.float32)[0],
            )

        # timeseries
        ts_cold_anom = float("nan")
        tensor = None if Modality.TIMESERIES in req.declared_missing else self._ts_tensor(req)
        if tensor is None:
            reason = (
                "declared missing"
                if Modality.TIMESERIES in req.declared_missing
                else "no sensor sequences supplied"
            )
            results["timeseries"] = _ModalityResult(False, reason)
        else:
            results["timeseries"] = _ModalityResult(
                True,
                raw_score=float(models["ts_cnn"].predict_proba(tensor)[0, 1]),
                embedding=models["ts_cnn"].embed(tensor)[0],
            )
            ts_cold_anom = float(models["ts_cnn_coldstart"].anomaly_score(tensor)[0])

        # vision
        results["vision"], img_distance, quality_degraded = self._vision(req)

        # calibrated per-modality scores → fusion input
        calibrators = models["calibrators"]
        cal_scores: dict[str, float] = {}
        for m in _MODALITIES:
            r = results[m]
            cal_scores[m] = (
                float(calibrators[m].transform(np.array([r.raw_score]))[0])
                if r.available
                else float("nan")
            )
        scores_frame = pd.DataFrame([cal_scores])[_MODALITIES]
        embeddings = self._fusion_embeddings(results)
        from factoryguard.models.fusion import FusionInput

        fusion_in = FusionInput(scores=scores_frame, embeddings=embeddings)
        p_fused = float(
            calibrators["late_fusion"].transform(
                models["late_fusion"].predict_proba(fusion_in)[:, 1]
            )[0]
        )
        fused_emb = models["embedding_fusion"].embed(fusion_in)

        # uncertainty + abstention
        conformal, ood = models["conformal"], models["mahalanobis_ood"]
        policy = AbstentionPolicy(conformal, ood)
        decision = policy.decide(np.array([p_fused]), fused_emb, np.array([quality_degraded]))[0]
        sets = conformal.prediction_sets(np.array([p_fused]))[0]
        ood_dist = float(ood.anomaly_score(fused_emb)[0])

        # serving mode
        anomaly_frame = pd.DataFrame(
            [
                {
                    "isolation_forest": float(
                        models["isolation_forest"].anomaly_score(tab_frame)[0]
                    )
                    if results["tabular"].available
                    else float("nan"),
                    "ts_reconstruction": ts_cold_anom,
                    "image_distance": img_distance,
                }
            ]
        )
        served = serve(
            self.mode,
            anomaly_frame,
            None if self.mode is ServingMode.ANOMALY_ONLY else np.array([p_fused]),
            blend_weight=float(meta.get("blend_weight", 0.7)),
        )
        risk = float(served.risk_score[0])
        if not np.isfinite(risk):
            decision.abstain = True
            decision.reasons.append("no scoring signal available for this unit")
            risk = 0.0

        # root cause + retrieval + categories
        root_causes = self._root_causes(req, tab_frame, gf_row, ent_row)
        similar = self._similar_incidents(results, num_block)
        category_probs = None
        if self.mode is ServingMode.SUPERVISED and results["tabular"].available:
            mc = models["hgb_multiclass"]
            probs = mc.predict_proba(tab_frame)[0]
            category_probs = {
                str(c): round(float(p), 4) for c, p in zip(mc.classes_, probs, strict=True)
            }

        data_quality = "degraded" if quality_degraded else "ok"
        confidence = (
            max(p_fused, 1 - p_fused) if served.is_probability else 0.5
        )  # cold-start modes are served with deliberately wide uncertainty
        response = PredictionResponse(
            prediction_id=f"PRED-{uuid.uuid4().hex[:16]}",
            correlation_id=req.correlation_id or uuid.uuid4().hex,
            model_version=self.bundle.model_version,
            feature_version=str(self.bundle.lineage.get("feature_version", "unknown")),
            serving_mode=self.mode.value,
            risk_score=risk,
            is_probability=served.is_probability,
            defect_probability=p_fused if served.is_probability else None,
            category_probabilities=category_probs,
            confidence=confidence,
            uncertainty=UncertaintyInfo(
                conformal_set=cast(
                    'list[Literal["ok", "defect"]]',
                    [lbl for lbl, inc in zip(("ok", "defect"), sets, strict=True) if inc],
                ),
                conformal_alpha=float(meta.get("conformal_alpha", 0.1)),
                ambiguous=bool(sets.sum() != 1),
                ood=bool(ood.is_ood(fused_emb)[0]),
                ood_distance=ood_dist if np.isfinite(ood_dist) else None,
            ),
            abstained=decision.abstain,
            abstention_reasons=decision.reasons,
            data_quality=data_quality,  # type: ignore[arg-type]
            modalities={
                Modality(m): ModalityStatus(
                    available=results[m].available, reason=results[m].reason
                )
                for m in _MODALITIES
            },
            top_evidence=self._evidence(results, cal_scores, anomaly_frame),
            root_causes=root_causes,
            recommendations=[],
            similar_incidents=similar,
            assistant=None,
            processing_ms=0.0,
            timestamp=datetime.now(UTC),
        )

        # recommendations operate on the assembled result (deterministic rules)
        evidence_by_type = {rc.entity_type: rc.evidence for rc in root_causes}
        ctx = PredictionContext(
            unit_id=req.unit.unit_id,
            risk_score=risk,
            is_probability=served.is_probability,
            abstained=decision.abstain,
            abstention_reasons=decision.reasons,
            data_quality=data_quality,
            serving_mode=self.mode.value,
            top_root_causes=[(rc.entity_type, rc.entity_id) for rc in root_causes[:3]],
            tool_wear_evidence=evidence_by_type.get("tool", 0.0),
            lot_evidence=evidence_by_type.get("material_lot", 0.0),
            calibration_evidence=evidence_by_type.get("machine", 0.0),
        )
        response = response.model_copy(update={"recommendations": self.recommender.recommend(ctx)})
        summary: AssistantOutput = self.summarizer.summarize(response)
        response = response.model_copy(
            update={
                "assistant": summary,
                "processing_ms": round((time.perf_counter() - t0) * 1000, 2),
            }
        )
        with self._lock:
            self._predictions[response.prediction_id] = response
        self._append_log("predictions.jsonl", response.model_dump(mode="json"))
        return response

    # --------------------------------------------------------------- helpers

    def _zscore(self, name: str, block: np.ndarray) -> np.ndarray:
        mean, std = self.bundle.meta["retrieval_stats"][name]
        return (block - mean) / std

    def _fusion_embeddings(self, results: dict[str, _ModalityResult]) -> dict[str, np.ndarray]:
        emb_fusion = self.bundle.models["embedding_fusion"]
        dims = {m: emb_fusion._stats[m][0].shape[0] for m in emb_fusion.modalities}
        out: dict[str, np.ndarray] = {}
        for m in _MODALITIES:
            r = results[m]
            if r.available and r.embedding is not None:
                out[m] = r.embedding.astype(np.float32).reshape(1, -1)
            else:
                out[m] = np.full((1, dims[m]), np.nan, dtype=np.float32)
        return out

    def _root_causes(
        self,
        req: PredictionRequest,
        tab_frame: pd.DataFrame,
        gf_row: pd.DataFrame,
        ent_row: pd.DataFrame,
    ) -> list[RootCauseCandidate]:
        ranker = self.bundle.models["root_cause_ranker"]
        u = req.unit
        units_row = tab_frame.assign(
            unit_id=u.unit_id,
            work_order_id=u.work_order_id,
            operator_id=u.operator_id,
            wire_lot_id=u.wire_lot_id,
            revision_id=f"{u.product_id}:{u.revision}",
        )
        gf = GraphFeatures(features=gf_row, entities=ent_row, half_life_days=0.0)
        ranked = ranker.rank(units_row, gf, np.array([0]))
        frame = ranked.per_unit.get(str(u.unit_id))
        if frame is None or frame.empty:
            return []
        return [
            RootCauseCandidate(
                rank=i + 1,
                entity_type=str(r.entity_type),
                entity_id=str(r.entity_id),
                score=round(float(r.score), 4),
                history=round(float(r.history), 4),
                evidence=round(float(r.evidence), 4),
            )
            for i, r in enumerate(frame.head(5).itertuples())
        ]

    def _similar_incidents(
        self, results: dict[str, _ModalityResult], num_block: np.ndarray
    ) -> list[SimilarIncident]:
        ts = results["timeseries"]
        graph = results["graph"]
        if not (results["tabular"].available and ts.available and graph.available):
            return []  # retrieval space needs all always-available modalities
        assert ts.embedding is not None and graph.embedding is not None
        query = np.concatenate(
            [
                self._zscore("tabular", num_block)[0],
                self._zscore("timeseries", ts.embedding.reshape(1, -1))[0],
                self._zscore("graph", graph.embedding.reshape(1, -1))[0],
            ]
        ).reshape(1, -1)
        hits = self.bundle.models["incident_index"].query(query, k=5)[0]
        return [
            SimilarIncident(
                unit_id=str(r.unit_id),
                defect_category=str(r.defect_category),
                produced_at=pd.Timestamp(r.produced_at).to_pydatetime(),
                distance=round(float(r.distance), 4),
            )
            for r in hits.itertuples()
        ]

    def _evidence(
        self,
        results: dict[str, _ModalityResult],
        cal_scores: dict[str, float],
        anomaly_frame: pd.DataFrame,
    ) -> list[EvidenceItem]:
        items = [
            EvidenceItem(
                source=f"modality:{m}",
                description=f"calibrated {m} defect score",
                value=round(cal_scores[m], 4),
            )
            for m in _MODALITIES
            if results[m].available and np.isfinite(cal_scores[m])
        ]
        for col in anomaly_frame.columns:
            v = float(anomaly_frame[col].iloc[0])
            if np.isfinite(v):
                items.append(
                    EvidenceItem(
                        source=f"anomaly:{col}",
                        description=f"{col} anomaly score (rank signal, not a probability)",
                        value=round(v, 4),
                    )
                )
        return items

    # ------------------------------------------------------ feedback / reads

    def get_prediction(self, prediction_id: str) -> PredictionResponse | None:
        with self._lock:
            return self._predictions.get(prediction_id)

    def submit_feedback(self, fb: FeedbackRequest) -> FeedbackResponse:
        errors: list[str] = []
        with self._lock:
            known = fb.prediction_id in self._predictions
        if not known:
            errors.append(f"unknown prediction_id: {fb.prediction_id}")
        if fb.failed_eol and not fb.defect_category:
            errors.append("failed_eol=true requires a defect_category")
        accepted = not errors
        if accepted:
            self._feedback_count += 1
            self._append_log("feedback.jsonl", fb.model_dump(mode="json"))
        return FeedbackResponse(
            feedback_id=f"FB-{uuid.uuid4().hex[:12]}",
            accepted=accepted,
            validation_errors=errors,
        )

    def monitoring_summary(self) -> dict[str, Any]:
        with self._lock:
            preds = list(self._predictions.values())
        n = len(preds)
        return {
            "predictions_served": n,
            "abstention_rate": (round(sum(p.abstained for p in preds) / n, 4) if n else None),
            "mean_risk_score": (
                round(float(np.mean([p.risk_score for p in preds])), 4) if n else None
            ),
            "feedback_received": self._feedback_count,
            "serving_mode": self.mode.value,
            "model_version": self.bundle.model_version,
        }

    def data_quality_summary(self) -> dict[str, Any]:
        with self._lock:
            preds = list(self._predictions.values())
        n = len(preds)
        by_status: dict[str, int] = {}
        missing: dict[str, int] = dict.fromkeys(_MODALITIES, 0)
        for p in preds:
            by_status[p.data_quality] = by_status.get(p.data_quality, 0) + 1
            for m, st in p.modalities.items():
                if not st.available:
                    missing[m.value] += 1
        return {"predictions": n, "by_status": by_status, "missing_modality_counts": missing}

    def _append_log(self, name: str, payload: dict[str, Any]) -> None:
        if self._log_dir is None:
            return
        with self._lock, (self._log_dir / name).open("a") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
