"""API contract v1 (spec §18): request/response/feedback models.

Versioning rules (enforced by ``tests/contract``):
- every response carries ``schema_version``;
- changes within v1 must be additive (new optional fields only) — the
  committed golden JSON Schemas are the compatibility baseline;
- breaking changes require a new module (``v2.py``) served side by side.

Field semantics worth reading twice:
- ``risk_score`` is always present; whether it is a calibrated probability
  depends on the serving mode and is stated by ``is_probability`` — in
  ``anomaly-only``/``blended`` modes it must never be read as P(defect).
- A missing modality is *declared*, not zero-filled (ADR-0006); the
  response echoes per-modality availability back.
- Root-cause entries are ranked hypotheses (statistical association +
  engineered priors), not causal proof — wording fixed by spec §10.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

_ID = Field(min_length=1, max_length=128)


class Modality(StrEnum):
    TABULAR = "tabular"
    TIMESERIES = "timeseries"
    VISION = "vision"
    GRAPH = "graph"


class UnitContext(BaseModel):
    """Entity identifiers of the unit being scored (production context)."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str = _ID
    work_order_id: str = _ID
    plant_id: str = _ID
    line_id: str = _ID
    machine_id: str = _ID
    tool_id: str = _ID
    operator_id: str = _ID
    product_id: str = _ID
    revision: str = _ID
    family: str = _ID
    shift: str = _ID
    terminal_lot_id: str = _ID
    wire_lot_id: str = _ID
    seal_lot_id: str | None = Field(default=None, max_length=128)
    produced_at: datetime


class ProcessMeasurements(BaseModel):
    """Structured tabular features captured at production time."""

    model_config = ConfigDict(extra="forbid")

    cycle_time_s: float
    production_rate_uph: float
    crimp_height_setpoint_mm: float
    crimp_height_mm: float
    pull_force_n: float
    ambient_temp_c: float
    humidity_pct: float
    tool_age_cycles: float
    days_since_maintenance: float
    changeover_minutes: float
    units_since_changeover: float
    recent_defect_count_line: float


class SensorSequences(BaseModel):
    """Raw sensor waveforms for the crimp cycle. ``null`` samples encode
    sensor dropout and are preserved (mask-aware model input)."""

    model_config = ConfigDict(extra="forbid")

    channels: dict[str, list[float | None]] = Field(min_length=1)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: UnitContext
    measurements: ProcessMeasurements
    sensors: SensorSequences | None = None
    image_refs: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Storage-relative image paths; never absolute paths or URLs.",
    )
    declared_missing: list[Modality] = Field(
        default_factory=list,
        description="Modalities the caller declares absent (ADR-0006: missing "
        "is an explicit state, not an empty payload).",
    )
    correlation_id: str | None = Field(default=None, max_length=128)


class ModalityStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason: str = ""  # e.g. "declared missing", "no image reference supplied"


class UncertaintyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conformal_set: list[Literal["ok", "defect"]]
    conformal_alpha: float
    ambiguous: bool
    ood: bool
    ood_distance: float | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str  # e.g. "modality:tabular", "graph:tool_id", "image-quality"
    description: str
    value: float | None = None


class RootCauseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    entity_type: str
    entity_id: str
    score: float
    history: float
    evidence: float


class SimilarIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    defect_category: str
    produced_at: datetime
    distance: float


class RecommendationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str
    action: str  # from the allow-listed taxonomy
    reason: str
    evidence: list[str]
    policy_id: str
    severity: Literal["low", "medium", "high", "critical"]
    status: Literal["AUTO_APPROVED", "PENDING_APPROVAL"]
    required_approver_role: str | None = None
    expires_at: datetime


class AssistantOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    generator: str  # "template" | "slm" | "vlm"
    advisory: Literal[True] = True  # assistant text is never authoritative


class PredictionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    prediction_id: str
    correlation_id: str
    model_version: str
    feature_version: str
    serving_mode: Literal["anomaly-only", "blended", "supervised"]
    risk_score: float
    is_probability: bool
    defect_probability: float | None = None  # None outside supervised mode
    category_probabilities: dict[str, float] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: UncertaintyInfo
    abstained: bool
    abstention_reasons: list[str]
    data_quality: Literal["ok", "degraded", "failed"]
    modalities: dict[Modality, ModalityStatus]
    top_evidence: list[EvidenceItem]
    root_causes: list[RootCauseCandidate]
    recommendations: list[RecommendationModel]
    similar_incidents: list[SimilarIncident]
    assistant: AssistantOutput | None = None
    processing_ms: float
    timestamp: datetime


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str = _ID
    unit_id: str = _ID
    failed_eol: bool
    defect_category: str | None = Field(default=None, max_length=64)
    severity: Literal["minor", "major", "critical"] | None = None
    notes: str = Field(default="", max_length=2000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    feedback_id: str
    accepted: bool
    validation_errors: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = _ID
    decision: Literal["approve", "reject"]
    notes: str = Field(default="", max_length=2000)
