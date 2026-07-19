"""FastAPI application factory (spec §18, §14).

``create_app`` takes explicit dependencies (settings, prediction service,
audit log) so tests construct apps with temp state and no globals. The
uvicorn entry point lives in ``apps/api/main.py``.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from factoryguard.api.middleware import (
    BodyLimitMiddleware,
    CorrelationMiddleware,
    IdempotencyCache,
    RateLimitMiddleware,
)
from factoryguard.api.routes import api_router, health_router
from factoryguard.auth import build_verifier
from factoryguard.config.settings import Settings
from factoryguard.inference.service import PredictionService
from factoryguard.recommendations import AuditLog

log = logging.getLogger("factoryguard.api")


def create_app(
    settings: Settings,
    service: PredictionService | None,
    audit: AuditLog,
) -> FastAPI:
    docs_on = settings.api.docs_enabled and not settings.environment.is_hardened
    app = FastAPI(
        title="FactoryGuard AI",
        version="1.0",
        docs_url="/docs" if docs_on else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_on else None,
    )
    app.state.service = service
    app.state.audit = audit
    app.state.idempotency = IdempotencyCache()
    app.state.verifier = build_verifier(
        settings.auth.provider,
        secret=settings.auth.local_jwt_secret,
        issuer=settings.auth.issuer,
        audience=settings.auth.audience,
    )

    # middleware executes in reverse add-order: correlation wraps everything
    app.add_middleware(RateLimitMiddleware, per_minute=settings.api.rate_limit_per_minute)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.api.max_request_bytes)
    app.add_middleware(CorrelationMiddleware)
    # CORS: deny by default — the middleware is added only when origins are
    # explicitly configured (and the hardened validator forbids wildcards).
    if settings.api.cors_allowed_origins:
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    app.include_router(health_router)
    app.include_router(api_router)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        cid = getattr(request.state, "correlation_id", "-")
        return JSONResponse(
            {"error": str(exc.detail), "correlation_id": cid},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        cid = getattr(request.state, "correlation_id", "-")
        # field paths only — no echoed input values in error responses
        fields = sorted({".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()})
        return JSONResponse(
            {"error": "request validation failed", "fields": fields, "correlation_id": cid},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        cid = getattr(request.state, "correlation_id", "-")
        log.exception("unhandled error cid=%s", cid)  # full trace to logs only
        return JSONResponse({"error": "internal error", "correlation_id": cid}, status_code=500)

    return app
