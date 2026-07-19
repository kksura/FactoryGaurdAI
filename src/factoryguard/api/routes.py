"""Versioned REST routes (spec §18). Deny-by-default: every route except
health/version requires an authenticated principal with the declared scope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from factoryguard import __version__ as pkg_version
from factoryguard.api.deps import require
from factoryguard.auth import Principal
from factoryguard.contracts.v1 import (
    SCHEMA_VERSION,
    ApprovalRequest,
    FeedbackRequest,
    FeedbackResponse,
    PredictionRequest,
    PredictionResponse,
)
from factoryguard.inference.service import PredictionService, PredictionServiceError

log = logging.getLogger("factoryguard.api")

health_router = APIRouter()
api_router = APIRouter(prefix="/api/v1")

_MAX_BATCH = 100


def _service(request: Request) -> PredictionService:
    svc: PredictionService | None = request.app.state.service
    if svc is None:
        raise HTTPException(503, "model artifacts not loaded")
    return svc


# ----------------------------------------------------------------- anonymous


@health_router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@health_router.get("/health/ready")
def ready(request: Request) -> dict[str, str]:
    if request.app.state.service is None:
        raise HTTPException(503, "not ready: model artifacts not loaded")
    return {"status": "ready"}


@health_router.get("/version")
def version(request: Request) -> dict[str, str]:
    svc = request.app.state.service
    return {
        "app_version": pkg_version,
        "schema_version": SCHEMA_VERSION,
        "model_version": svc.bundle.model_version if svc else "unloaded",
    }


# ---------------------------------------------------------------- predictions


@api_router.post("/predictions", response_model=PredictionResponse)
def create_prediction(
    body: PredictionRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require("predictions:write")),
) -> PredictionResponse:
    idem_key = request.headers.get("Idempotency-Key")
    cache = request.app.state.idempotency
    if idem_key:
        hit = cache.get(f"{principal.subject}:{idem_key}")
        if hit is not None:
            response.headers["Idempotency-Replayed"] = "true"
            return PredictionResponse.model_validate_json(hit[1])
    try:
        result = _service(request).predict(body)
    except PredictionServiceError as exc:
        raise HTTPException(400, str(exc)) from exc
    if idem_key:
        cache.put(f"{principal.subject}:{idem_key}", 200, result.model_dump_json().encode())
    return result


class BatchRequest(BaseModel):
    items: list[PredictionRequest] = Field(min_length=1, max_length=_MAX_BATCH)


class BatchResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    results: list[PredictionResponse]


@api_router.post("/predictions/batch", response_model=BatchResponse)
def create_predictions_batch(
    body: BatchRequest,
    request: Request,
    principal: Principal = Depends(require("predictions:write")),
) -> BatchResponse:
    svc = _service(request)
    results = []
    for item in body.items:
        try:
            results.append(svc.predict(item))
        except PredictionServiceError as exc:
            raise HTTPException(400, f"unit {item.unit.unit_id}: {exc}") from exc
    return BatchResponse(results=results)


@api_router.get("/predictions/{prediction_id}", response_model=PredictionResponse)
def get_prediction(
    prediction_id: str,
    request: Request,
    principal: Principal = Depends(require("predictions:read")),
) -> PredictionResponse:
    result = _service(request).get_prediction(prediction_id)
    if result is None:
        raise HTTPException(404, "prediction not found")
    return result


# ------------------------------------------------------------------ feedback


@api_router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    principal: Principal = Depends(require("feedback:write")),
) -> FeedbackResponse:
    return _service(request).submit_feedback(body)


# -------------------------------------------------------------------- models


@api_router.get("/models/current")
def current_model(
    request: Request, principal: Principal = Depends(require("models:read"))
) -> dict[str, Any]:
    svc = _service(request)
    return {
        "model_version": svc.bundle.model_version,
        "serving_mode": svc.mode.value,
        "lineage": svc.bundle.lineage,
        "artifact_path": str(svc.bundle.path),
    }


@api_router.get("/models/{model_version}/card")
def model_card(
    model_version: str,
    request: Request,
    principal: Principal = Depends(require("models:read")),
) -> dict[str, Any]:
    svc = _service(request)
    if model_version != svc.bundle.model_version:
        raise HTTPException(404, "unknown model version (only the current is served)")
    lin = svc.bundle.lineage
    return {
        "model_version": model_version,
        "intended_use": "Advisory wire-harness defect-risk scoring; never a "
        "control system. Anomaly/blended risk scores are not probabilities.",
        "training_profile": lin.get("profile"),
        "feature_version": lin.get("feature_version"),
        "seed": lin.get("seed"),
        "created_at": lin.get("created_at"),
        "git_commit": lin.get("git_commit"),
        "evaluation_report": f"reports/evaluation/{lin.get('profile')}/multimodal-report.md",
        "limitations": [
            "Trained on synthetic data; real-world transfer unvalidated.",
            "Conformal coverage assumes exchangeability; drift erodes it.",
            "Root-cause rankings are statistical association, not causal proof.",
        ],
    }


# --------------------------------------------------------------- monitoring


@api_router.get("/monitoring/summary")
def monitoring_summary(
    request: Request, principal: Principal = Depends(require("monitoring:read"))
) -> dict[str, Any]:
    return _service(request).monitoring_summary()


@api_router.get("/data-quality/summary")
def data_quality_summary(
    request: Request, principal: Principal = Depends(require("data-quality:read"))
) -> dict[str, Any]:
    return _service(request).data_quality_summary()


# ------------------------------------------------------ approvals and audit


@api_router.post("/recommendations/{recommendation_id}/approval")
def approve_recommendation(
    recommendation_id: str,
    body: ApprovalRequest,
    request: Request,
    principal: Principal = Depends(require("recommendations:approve")),
) -> dict[str, Any]:
    if body.recommendation_id != recommendation_id:
        raise HTTPException(400, "recommendation_id mismatch between path and body")
    svc = _service(request)
    rec = None
    with svc._lock:
        for pred in svc._predictions.values():
            for r in pred.recommendations:
                if r.recommendation_id == recommendation_id:
                    rec = r
                    break
    if rec is None:
        raise HTTPException(404, "recommendation not found")
    if rec.status != "PENDING_APPROVAL":
        raise HTTPException(409, "recommendation does not require approval")
    required = rec.required_approver_role
    if required and required not in principal.roles and "platform-admin" not in principal.roles:
        raise HTTPException(403, f"approval requires role: {required}")
    entry = request.app.state.audit.append(
        "recommendation_approval",
        {
            "recommendation_id": recommendation_id,
            "action": rec.action,
            "decision": body.decision,
            "notes": body.notes,
        },
        actor=principal.subject,
    )
    return {
        "recommendation_id": recommendation_id,
        "decision": body.decision,
        "audit_hash": entry["entry_hash"],
    }


@api_router.get("/audit/verify")
def audit_verify(
    request: Request, principal: Principal = Depends(require("audit:read"))
) -> dict[str, Any]:
    count = request.app.state.audit.verify()
    return {"entries": count, "chain_valid": True}
