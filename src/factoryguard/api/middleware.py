"""Security middleware (spec §14): size limits, content-type allow-list,
rate limiting, security headers, correlation IDs, safe errors.

All in-memory state (rate buckets, idempotency cache) is per-process —
correct for the local single-process deployment; the Azure design swaps
these for gateway-level equivalents (Phase 7 docs).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
_ALLOWED_CONTENT_TYPES = ("application/json",)


def _problem(status: int, detail: str, correlation_id: str) -> JSONResponse:
    """Safe error shape — never a stack trace (spec §14)."""
    return JSONResponse({"error": detail, "correlation_id": correlation_id}, status_code=status)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = getattr(request.state, "correlation_id", "-")
        if request.method in ("POST", "PUT", "PATCH"):
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                return _problem(413, "request body too large", cid)
            body = await request.body()
            if len(body) > self.max_bytes:  # chunked bodies without a length
                return _problem(413, "request body too large", cid)
            ctype = request.headers.get("content-type", "").split(";")[0].strip()
            if body and ctype not in _ALLOWED_CONTENT_TYPES:
                return _problem(415, f"unsupported content type: {ctype or 'none'}", cid)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-client limiter. Client key = authenticated subject
    when present (set downstream), else the peer address."""

    def __init__(self, app, per_minute: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.per_minute = per_minute
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = getattr(request.state, "correlation_id", "-")
        client = request.client.host if request.client else "unknown"
        auth = request.headers.get("authorization", "")
        key = f"{client}:{hash(auth) & 0xFFFF}"
        window = int(time.time() // 60)
        with self._lock:
            w, count = self._windows.get(key, (window, 0))
            if w != window:
                w, count = window, 0
            count += 1
            self._windows[key] = (w, count)
            if len(self._windows) > 10_000:  # bounded memory
                self._windows.clear()
        if count > self.per_minute:
            resp = _problem(429, "rate limit exceeded", cid)
            resp.headers["Retry-After"] = "60"
            return resp
        return await call_next(request)


class IdempotencyCache:
    """Bounded LRU of Idempotency-Key → serialized response for POST
    /predictions: retries return the original result instead of re-scoring."""

    def __init__(self, max_entries: int = 1024) -> None:
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[int, bytes]] = OrderedDict()
        self.max_entries = max_entries

    def get(self, key: str) -> tuple[int, bytes] | None:
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def put(self, key: str, status: int, body: bytes) -> None:
        with self._lock:
            self._cache[key] = (status, body)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
