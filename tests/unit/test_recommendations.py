"""Recommendation engine policies + hash-chained audit log (spec §11)."""

from pathlib import Path

import pytest

from factoryguard.recommendations import (
    ACTION_TAXONOMY,
    AuditLog,
    PredictionContext,
    RecommendationEngine,
)
from factoryguard.recommendations.audit import AuditIntegrityError


def _ctx(**overrides: object) -> PredictionContext:
    base = {
        "unit_id": "UNIT-1",
        "risk_score": 0.1,
        "is_probability": True,
        "abstained": False,
        "abstention_reasons": [],
        "data_quality": "ok",
        "serving_mode": "supervised",
    }
    base.update(overrides)
    return PredictionContext(**base)  # type: ignore[arg-type]


def test_low_risk_clean_input_yields_nothing() -> None:
    assert RecommendationEngine().recommend(_ctx()) == []


def test_abstention_routes_to_visual_inspection() -> None:
    recs = RecommendationEngine().recommend(
        _ctx(abstained=True, abstention_reasons=["conformal set ambiguous"])
    )
    assert [r.action for r in recs] == ["targeted_visual_inspection"]
    assert recs[0].status == "AUTO_APPROVED"
    assert recs[0].policy_id.endswith("@policies-v1")


def test_high_probability_holds_unit_pending_approval() -> None:
    recs = RecommendationEngine().recommend(
        _ctx(risk_score=0.8, top_root_causes=[("tool", "T-1")], tool_wear_evidence=0.95)
    )
    actions = {r.action for r in recs}
    assert "hold_unit" in actions and "check_tool_wear" in actions
    hold = next(r for r in recs if r.action == "hold_unit")
    assert hold.status == "PENDING_APPROVAL"
    assert hold.required_approver_role == "quality-engineer"


def test_anomaly_mode_never_claims_probability() -> None:
    recs = RecommendationEngine().recommend(
        _ctx(risk_score=0.9, is_probability=False, serving_mode="anomaly-only")
    )
    actions = {r.action for r in recs}
    assert "hold_unit" not in actions  # POL-007 requires a calibrated probability
    assert "escalate" in actions  # POL-008: human decides in cold start


def test_all_actions_in_taxonomy_and_deterministic() -> None:
    ctx = _ctx(
        risk_score=0.9,
        abstained=True,
        data_quality="degraded",
        top_root_causes=[("machine", "M-1"), ("material_lot", "LOT-9"), ("revision", "P:B")],
    )
    engine = RecommendationEngine()
    a = engine.recommend(ctx)
    b = engine.recommend(ctx)
    assert all(r.action in ACTION_TAXONOMY for r in a)
    assert [r.action for r in a] == [r.action for r in b]  # deterministic


def test_engine_refuses_non_taxonomy_action() -> None:
    with pytest.raises(ValueError, match="allow-listed"):
        RecommendationEngine()._make("restart_machine", "r", [], "POL-X", "high")


# ---------------------------------------------------------------- audit log


def test_audit_chain_appends_and_verifies(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.append("recommendation_approval", {"n": i}, actor=f"user-{i}")
    assert log.verify() == 5
    entries = log.entries()
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]


def test_audit_detects_tampered_payload(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("e", {"decision": "approve"}, actor="a")
    log.append("e", {"decision": "reject"}, actor="b")
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    lines[0] = lines[0].replace("approve", "APPROVE")
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(AuditIntegrityError):
        log.verify()


def test_audit_detects_deleted_entry(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("e", {"n": i}, actor="a")
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    (tmp_path / "audit.jsonl").write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(AuditIntegrityError, match="chain break"):
        log.verify()
