"""Identifier generation: prediction IDs, correlation IDs, entity IDs.

All IDs are URL-safe, sortable where useful, and never derived from
user-controlled input.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

_PREDICTION_PREFIX = "prd"
_CORRELATION_PREFIX = "cor"


def new_prediction_id(now: datetime | None = None) -> str:
    """Time-prefixed unique prediction ID, e.g. ``prd-20260717T104501-9f3ab2c4d1``."""
    ts = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    return f"{_PREDICTION_PREFIX}-{ts}-{secrets.token_hex(5)}"


def new_correlation_id() -> str:
    """Opaque correlation ID for request tracing."""
    return f"{_CORRELATION_PREFIX}-{uuid.uuid4().hex}"


def is_valid_correlation_id(value: str) -> bool:
    """Accept only IDs this system could have issued (defence against log injection)."""
    if not value.startswith(f"{_CORRELATION_PREFIX}-"):
        return False
    suffix = value.removeprefix(f"{_CORRELATION_PREFIX}-")
    return len(suffix) == 32 and all(c in "0123456789abcdef" for c in suffix)
