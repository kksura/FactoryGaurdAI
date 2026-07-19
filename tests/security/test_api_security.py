"""API security behaviour (spec §14): authn/z, size limits, content types,
security headers, rate limiting, safe errors. These run without model
artifacts — authentication and middleware must reject requests before any
model code is reachable."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from factoryguard.api import create_app
from factoryguard.config.settings import ApiConfig, AuthConfig, Settings
from factoryguard.recommendations import AuditLog

SECRET = "security-test-secret"


def _settings(**api_overrides: object) -> Settings:
    return Settings(
        environment="local",
        auth=AuthConfig(local_jwt_secret=SECRET),
        api=ApiConfig(**api_overrides),  # type: ignore[arg-type]
    )


def _token(roles: list[str], ttl: int = 600) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "sec-tester",
            "roles": roles,
            "iss": "factoryguard-local",
            "aud": "factoryguard-api",
            "iat": now,
            "exp": now + ttl,
        },
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def client(tmp_path) -> TestClient:  # type: ignore[no-untyped-def]
    app = create_app(_settings(), service=None, audit=AuditLog(tmp_path / "a.jsonl"))
    return TestClient(app, raise_server_exceptions=False)


def test_health_and_version_are_anonymous(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
    assert client.get("/version").status_code == 200


def test_missing_token_is_401(client: TestClient) -> None:
    r = client.post("/api/v1/predictions", json={})
    assert r.status_code == 401


def test_garbage_token_is_401(client: TestClient) -> None:
    r = client.get("/api/v1/monitoring/summary", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_wrong_role_is_403_deny_by_default(client: TestClient) -> None:
    viewer = _token(["plant-viewer"])  # has predictions:read, not write
    r = client.post("/api/v1/predictions", json={}, headers={"Authorization": f"Bearer {viewer}"})
    assert r.status_code == 403
    assert "predictions:write" in r.json()["error"] or "scope" in r.json()["error"]


def test_auditor_cannot_write_predictions(client: TestClient) -> None:
    auditor = _token(["auditor"])
    r = client.post("/api/v1/predictions", json={}, headers={"Authorization": f"Bearer {auditor}"})
    assert r.status_code == 403


def test_oversized_body_is_413(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(
        _settings(max_request_bytes=2048),
        service=None,
        audit=AuditLog(tmp_path / "a.jsonl"),
    )
    client = TestClient(app, raise_server_exceptions=False)
    big = {"x": "a" * 10_000}
    r = client.post(
        "/api/v1/predictions",
        json=big,
        headers={"Authorization": f"Bearer {_token(['service'])}"},
    )
    assert r.status_code == 413
    assert "stack" not in r.text.lower() and "Traceback" not in r.text


def test_wrong_content_type_is_415(client: TestClient) -> None:
    r = client.post(
        "/api/v1/predictions",
        content=b"<xml/>",
        headers={
            "Authorization": f"Bearer {_token(['service'])}",
            "Content-Type": "application/xml",
        },
    )
    assert r.status_code == 415


def test_security_headers_and_correlation_id_on_every_response(
    client: TestClient,
) -> None:
    r = client.get("/health/live")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Correlation-Id"]
    echoed = client.get("/health/live", headers={"X-Correlation-Id": "cid-123"})
    assert echoed.headers["X-Correlation-Id"] == "cid-123"


def test_rate_limit_returns_429(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(
        _settings(rate_limit_per_minute=3),
        service=None,
        audit=AuditLog(tmp_path / "a.jsonl"),
    )
    client = TestClient(app, raise_server_exceptions=False)
    statuses = [client.get("/health/live").status_code for _ in range(5)]
    assert 429 in statuses
    assert statuses[0] == 200


def test_validation_error_does_not_echo_input_values(client: TestClient) -> None:
    secret_value = "TOPSECRET-LOT-VALUE"
    r = client.post(
        "/api/v1/predictions",
        json={"unit": {"unit_id": secret_value}},
        headers={"Authorization": f"Bearer {_token(['service'])}"},
    )
    assert r.status_code == 422
    assert secret_value not in r.text  # field paths only, never values
    assert "fields" in r.json()


def test_unloaded_service_is_503_not_500(client: TestClient) -> None:
    r = client.get("/health/ready")
    assert r.status_code == 503
    ml = _token(["ml-engineer"])
    r2 = client.get("/api/v1/monitoring/summary", headers={"Authorization": f"Bearer {ml}"})
    assert r2.status_code == 503


def test_docs_disabled_when_configured(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(
        _settings(docs_enabled=False), service=None, audit=AuditLog(tmp_path / "a.jsonl")
    )
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_metrics_endpoint_exposes_aggregates_only(client: TestClient) -> None:
    client.get("/health/live")  # generate at least one request metric
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "fg_http_requests_total" in r.text
    # aggregate counters only — never unit ids or tokens
    assert "UNIT-" not in r.text and "Bearer" not in r.text
