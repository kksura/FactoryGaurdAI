"""End-to-end: generate tiny data → train multimodal → serve → predict →
feedback → monitoring → audit, all through the real HTTP surface."""

import sys
import time
from pathlib import Path

import jwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from factoryguard.api import create_app
from factoryguard.config.settings import AuthConfig, Settings
from factoryguard.contracts.v1 import PredictionResponse
from factoryguard.data.generate import generate_dataset
from factoryguard.inference.service import ArtifactBundle, PredictionService
from factoryguard.inference.serving import ServingMode
from factoryguard.recommendations import AuditLog

SECRET = "e2e-secret"


def _token(roles: list[str]) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "e2e",
            "roles": roles,
            "iss": "factoryguard-local",
            "aud": "factoryguard-api",
            "iat": now,
            "exp": now + 600,
        },
        SECRET,
        algorithm="HS256",
    )


def _auth(roles: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(roles)}"}


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    tmp = tmp_path_factory.mktemp("e2e")
    data_root = tmp / "data"
    generate_dataset("tiny", data_root=data_root)

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from pipelines.training.train_multimodal import main as train_main

    argv_backup = sys.argv
    sys.argv = [
        "train_multimodal",
        "--profile",
        "tiny",
        "--data-root",
        str(data_root),
        "--reports-root",
        str(tmp / "reports"),
        "--artifacts-root",
        str(tmp / "artifacts"),
        "--no-vision",
    ]
    try:
        assert train_main() == 0
    finally:
        sys.argv = argv_backup

    bundle = ArtifactBundle.load(tmp / "artifacts" / "tiny")
    service = PredictionService(
        bundle,
        serving_mode=ServingMode.SUPERVISED,
        storage_root=data_root / "tiny",
        log_dir=tmp / "serving-logs",
    )
    settings = Settings(environment="local", auth=AuthConfig(local_jwt_secret=SECRET))
    app = create_app(settings, service, AuditLog(tmp / "audit.jsonl"))
    client = TestClient(app, raise_server_exceptions=False)
    units = pd.read_parquet(data_root / "tiny" / "tables" / "units.parquet")
    sensors = pd.read_parquet(data_root / "tiny" / "timeseries" / "sensors.parquet")
    return client, units, sensors


def _request_payload(units: pd.DataFrame, sensors: pd.DataFrame, idx: int) -> dict:
    row = units.iloc[idx]
    sub = sensors[sensors.unit_id == row.unit_id]
    channels = {
        ch: [None if pd.isna(v) else float(v) for v in grp.sort_values("t")["value"]]
        for ch, grp in sub.groupby("channel")
    }
    return {
        "unit": {
            "unit_id": str(row.unit_id),
            "work_order_id": str(row.work_order_id),
            "plant_id": str(row.plant_id),
            "line_id": str(row.line_id),
            "machine_id": str(row.machine_id),
            "tool_id": str(row.tool_id),
            "operator_id": str(row.operator_id),
            "product_id": str(row.product_id),
            "revision": str(row.revision),
            "family": str(row.family),
            "shift": str(row["shift"]),
            "terminal_lot_id": str(row.terminal_lot_id),
            "wire_lot_id": str(row.wire_lot_id),
            "produced_at": pd.Timestamp(row.produced_at).isoformat(),
        },
        "measurements": {
            k: float(getattr(row, k))
            for k in (
                "cycle_time_s",
                "production_rate_uph",
                "crimp_height_setpoint_mm",
                "crimp_height_mm",
                "pull_force_n",
                "ambient_temp_c",
                "humidity_pct",
                "tool_age_cycles",
                "days_since_maintenance",
                "changeover_minutes",
                "units_since_changeover",
                "recent_defect_count_line",
            )
        },
        "sensors": {"channels": channels},
    }


def test_health_version_openapi(stack) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = stack
    assert client.get("/health/ready").json() == {"status": "ready"}
    v = client.get("/version").json()
    assert v["schema_version"] == "1.0" and v["model_version"].startswith("multimodal-")
    spec = client.get("/openapi.json").json()
    for path in ("/api/v1/predictions", "/api/v1/feedback", "/api/v1/monitoring/summary"):
        assert path in spec["paths"]


def test_prediction_flow_with_idempotency(stack) -> None:  # type: ignore[no-untyped-def]
    client, units, sensors = stack
    payload = _request_payload(units, sensors, len(units) - 3)
    headers = {**_auth(["ml-engineer"]), "Idempotency-Key": "e2e-key-1"}
    r = client.post("/api/v1/predictions", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    resp = PredictionResponse.model_validate(r.json())  # contract-valid
    assert resp.serving_mode == "supervised"
    assert resp.is_probability and resp.defect_probability is not None
    assert resp.modalities  # per-modality availability present
    assert not resp.modalities["vision"].available  # trained --no-vision
    assert resp.assistant is not None and resp.assistant.advisory is True

    replay = client.post("/api/v1/predictions", json=payload, headers=headers)
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json()["prediction_id"] == resp.prediction_id

    got = client.get(f"/api/v1/predictions/{resp.prediction_id}", headers=_auth(["plant-viewer"]))
    assert got.status_code == 200
    assert got.json()["prediction_id"] == resp.prediction_id


def test_missing_modality_declared(stack) -> None:  # type: ignore[no-untyped-def]
    client, units, sensors = stack
    payload = _request_payload(units, sensors, len(units) - 4)
    payload["sensors"] = None
    payload["declared_missing"] = ["timeseries"]
    r = client.post("/api/v1/predictions", json=payload, headers=_auth(["ml-engineer"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modalities"]["timeseries"]["available"] is False
    assert body["modalities"]["tabular"]["available"] is True


def test_batch_endpoint(stack) -> None:  # type: ignore[no-untyped-def]
    client, units, sensors = stack
    items = [_request_payload(units, sensors, len(units) - k) for k in (5, 6)]
    r = client.post("/api/v1/predictions/batch", json={"items": items}, headers=_auth(["service"]))
    assert r.status_code == 200, r.text
    assert len(r.json()["results"]) == 2


def test_feedback_flow(stack) -> None:  # type: ignore[no-untyped-def]
    client, units, sensors = stack
    payload = _request_payload(units, sensors, len(units) - 7)
    pred = client.post("/api/v1/predictions", json=payload, headers=_auth(["ml-engineer"])).json()
    ok = client.post(
        "/api/v1/feedback",
        json={
            "prediction_id": pred["prediction_id"],
            "unit_id": payload["unit"]["unit_id"],
            "failed_eol": False,
        },
        headers=_auth(["quality-engineer"]),
    )
    assert ok.status_code == 200 and ok.json()["accepted"] is True
    bad = client.post(
        "/api/v1/feedback",
        json={
            "prediction_id": "PRED-nope",
            "unit_id": "U",
            "failed_eol": True,
            "defect_category": "x",
        },
        headers=_auth(["quality-engineer"]),
    )
    assert bad.json()["accepted"] is False and bad.json()["validation_errors"]


def test_models_monitoring_data_quality(stack) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = stack
    current = client.get("/api/v1/models/current", headers=_auth(["ml-engineer"]))
    assert current.status_code == 200
    version = current.json()["model_version"]
    card = client.get(f"/api/v1/models/{version}/card", headers=_auth(["auditor"]))
    assert card.status_code == 200
    assert "limitations" in card.json()
    mon = client.get("/api/v1/monitoring/summary", headers=_auth(["plant-viewer"]))
    assert mon.status_code == 200 and mon.json()["predictions_served"] >= 1
    dq = client.get("/api/v1/data-quality/summary", headers=_auth(["data-steward"]))
    assert dq.status_code == 200 and "missing_modality_counts" in dq.json()


def test_approval_requires_role_and_audit_verifies(stack) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = stack
    # unknown recommendation → 404 (approval surface is authenticated + scoped)
    r = client.post(
        "/api/v1/recommendations/REC-nope/approval",
        json={"recommendation_id": "REC-nope", "decision": "approve"},
        headers=_auth(["quality-engineer"]),
    )
    assert r.status_code == 404
    denied = client.post(
        "/api/v1/recommendations/REC-nope/approval",
        json={"recommendation_id": "REC-nope", "decision": "approve"},
        headers=_auth(["plant-viewer"]),
    )
    assert denied.status_code == 403
    audit = client.get("/api/v1/audit/verify", headers=_auth(["auditor"]))
    assert audit.status_code == 200 and audit.json()["chain_valid"] is True
