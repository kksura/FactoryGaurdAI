"""Prometheus metrics for the API (spec §20).

Exposed at ``/metrics`` when ``monitoring.metrics_enabled`` — the one
documented exception to the authenticated-routes rule: the endpoint
serves aggregate counters only (no unit ids, no scores per unit, no
tokens), the local stack binds to loopback, and the Prometheus scraper
has no auth header support in the compose setup. The Azure design fronts
it with the gateway instead (Phase 7).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "fg_http_requests_total",
    "HTTP requests",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)
LATENCY = Histogram(
    "fg_http_request_seconds",
    "HTTP request latency",
    labelnames=("route",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
PREDICTIONS = Counter(
    "fg_predictions_total",
    "Predictions served",
    labelnames=("serving_mode", "abstained"),
    registry=REGISTRY,
)
RISK_SCORE = Histogram(
    "fg_prediction_risk_score",
    "Distribution of served risk scores",
    buckets=tuple(round(x / 10, 1) for x in range(11)),
    registry=REGISTRY,
)


def record_prediction(serving_mode: str, abstained: bool, risk_score: float) -> None:
    PREDICTIONS.labels(serving_mode=serving_mode, abstained=str(abstained).lower()).inc()
    RISK_SCORE.observe(risk_score)


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    route = request.url.path
    # collapse dynamic segments so label cardinality stays bounded
    for prefix in ("/api/v1/predictions/", "/api/v1/models/", "/api/v1/recommendations/"):
        if route.startswith(prefix) and len(route) > len(prefix):
            route = prefix + "{id}"
            break
    start = time.perf_counter()
    response = await call_next(request)
    LATENCY.labels(route=route).observe(time.perf_counter() - start)
    REQUESTS.labels(method=request.method, route=route, status=str(response.status_code)).inc()
    return response


def metrics_endpoint() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
