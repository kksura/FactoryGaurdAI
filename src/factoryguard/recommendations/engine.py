"""Deterministic recommendation engine (spec §11, ADR-0017).

Versioned policy rules over an allow-listed action taxonomy. Properties
the tests enforce:

- every action emitted is in :data:`ACTION_TAXONOMY` — nothing else can
  ever be recommended, whatever upstream models say;
- rules are pure functions of the prediction context: same input, same
  recommendations (no randomness, no model calls);
- high-impact actions (hold unit, escalate) emit as ``PENDING_APPROVAL``
  with a required approver role — they are never auto-approved;
- no recommendation touches machinery: the taxonomy contains only human
  inspection/review actions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from factoryguard.contracts.v1 import RecommendationModel

POLICY_VERSION = "policies-v1"

# Allow-listed action taxonomy (spec §11). Adding an action is a reviewed
# policy change, not a code tweak next to a rule.
ACTION_TAXONOMY = frozenset(
    {
        "inspect_lot",
        "verify_crimp_height",
        "check_tool_wear",
        "validate_calibration",
        "review_first_piece_approval",
        "targeted_visual_inspection",
        "review_maintenance",
        "hold_unit",
        "escalate",
    }
)

_HIGH_IMPACT: dict[str, str] = {
    # action → required approver role (token roles, ADR-0010)
    "hold_unit": "quality-engineer",
    "escalate": "quality-engineer",
}

_DEFAULT_TTL_H = 24.0


@dataclass
class PredictionContext:
    """The slice of a prediction result the policy rules may look at."""

    unit_id: str
    risk_score: float
    is_probability: bool
    abstained: bool
    abstention_reasons: list[str]
    data_quality: str  # ok | degraded | failed
    serving_mode: str
    top_root_causes: list[tuple[str, str]] = field(default_factory=list)  # (type, id)
    tool_wear_evidence: float = 0.0  # [0,1] percentile from root-cause evidence
    lot_evidence: float = 0.0
    calibration_evidence: float = 0.0


class RecommendationEngine:
    """Applies the v1 policy rules. Deterministic; audit-logged by caller."""

    def __init__(self, high_risk_threshold: float = 0.5, ttl_hours: float = _DEFAULT_TTL_H):
        self.high_risk_threshold = high_risk_threshold
        self.ttl_hours = ttl_hours

    def _make(
        self,
        action: str,
        reason: str,
        evidence: list[str],
        policy_id: str,
        severity: str,
    ) -> RecommendationModel:
        if action not in ACTION_TAXONOMY:  # defense in depth; tested
            raise ValueError(f"action {action!r} is not in the allow-listed taxonomy")
        approver = _HIGH_IMPACT.get(action)
        return RecommendationModel(
            recommendation_id=f"REC-{uuid.uuid4().hex[:12]}",
            action=action,
            reason=reason,
            evidence=evidence,
            policy_id=f"{policy_id}@{POLICY_VERSION}",
            severity=severity,  # type: ignore[arg-type]
            status="PENDING_APPROVAL" if approver else "AUTO_APPROVED",
            required_approver_role=approver,
            expires_at=datetime.now(UTC) + timedelta(hours=self.ttl_hours),
        )

    def recommend(self, ctx: PredictionContext) -> list[RecommendationModel]:
        recs: list[RecommendationModel] = []
        high_risk = ctx.is_probability and ctx.risk_score >= self.high_risk_threshold
        elevated = ctx.risk_score >= self.high_risk_threshold  # any mode, rank sense

        # POL-001: abstention or failed data quality → human eyes on the unit.
        if ctx.abstained or ctx.data_quality == "failed":
            recs.append(
                self._make(
                    "targeted_visual_inspection",
                    "Model abstained or input failed data-quality checks; "
                    "route the unit to manual inspection.",
                    ctx.abstention_reasons or [f"data_quality={ctx.data_quality}"],
                    "POL-001",
                    "medium",
                )
            )

        # POL-002: degraded input quality → check the capture chain.
        if ctx.data_quality == "degraded":
            recs.append(
                self._make(
                    "validate_calibration",
                    "Input data quality degraded (e.g. camera blur/misalignment); "
                    "validate station calibration before trusting further scores.",
                    [f"data_quality={ctx.data_quality}"],
                    "POL-002",
                    "low",
                )
            )

        # POL-003..006: root-cause-directed checks for elevated-risk units.
        cause_types = {t for t, _ in ctx.top_root_causes}
        if elevated:
            if "tool" in cause_types or ctx.tool_wear_evidence >= 0.9:
                recs.append(
                    self._make(
                        "check_tool_wear",
                        "Elevated risk with tool wear among the top-ranked causes.",
                        [f"tool_wear_evidence={ctx.tool_wear_evidence:.2f}"]
                        + [f"root_cause={t}:{i}" for t, i in ctx.top_root_causes if t == "tool"],
                        "POL-003",
                        "medium",
                    )
                )
            if "machine" in cause_types or ctx.calibration_evidence >= 0.9:
                recs.append(
                    self._make(
                        "verify_crimp_height",
                        "Elevated risk with machine/calibration evidence; verify "
                        "crimp height against the setpoint.",
                        [f"calibration_evidence={ctx.calibration_evidence:.2f}"],
                        "POL-004",
                        "medium",
                    )
                )
            if "material_lot" in cause_types or ctx.lot_evidence >= 0.9:
                recs.append(
                    self._make(
                        "inspect_lot",
                        "Elevated risk with material-lot evidence; inspect the consumed lot(s).",
                        [f"root_cause={t}:{i}" for t, i in ctx.top_root_causes]
                        or [f"lot_evidence={ctx.lot_evidence:.2f}"],
                        "POL-005",
                        "medium",
                    )
                )
            if "revision" in cause_types:
                recs.append(
                    self._make(
                        "review_first_piece_approval",
                        "Elevated risk attributed to a product revision; review "
                        "first-piece approval for that revision.",
                        [f"root_cause={t}:{i}" for t, i in ctx.top_root_causes if t == "revision"],
                        "POL-006",
                        "medium",
                    )
                )

        # POL-007: calibrated high probability → hold for re-test (approval gated).
        if high_risk:
            recs.append(
                self._make(
                    "hold_unit",
                    f"Calibrated defect probability {ctx.risk_score:.2f} ≥ "
                    f"{self.high_risk_threshold:.2f}; hold the unit for EOL re-test.",
                    [f"defect_probability={ctx.risk_score:.3f}"],
                    "POL-007",
                    "high",
                )
            )

        # POL-008: cold-start mode with a top-rank score → escalate to QE
        # (anomaly scores are not probabilities; a human decides).
        if ctx.serving_mode == "anomaly-only" and ctx.risk_score >= 0.8:
            recs.append(
                self._make(
                    "escalate",
                    "High combined anomaly score in cold-start mode (no labels "
                    "yet) — escalate for engineering review.",
                    [f"anomaly_score={ctx.risk_score:.3f}", "serving_mode=anomaly-only"],
                    "POL-008",
                    "high",
                )
            )
        return recs
