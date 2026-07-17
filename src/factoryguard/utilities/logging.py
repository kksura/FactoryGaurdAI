"""Structured JSON logging with correlation IDs and secret redaction.

Every record passes through :func:`factoryguard.security.redaction.redact_any`
so token-shaped values never reach a sink, regardless of caller mistakes.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from factoryguard.security.redaction import redact_any, redact_text

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

# Attributes of LogRecord that are not user-supplied extras.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        if cid := _correlation_id.get():
            payload["correlation_id"] = cid
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            payload["extra"] = redact_any(extras)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable local format; still redacts."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{datetime.fromtimestamp(record.created, tz=UTC):%H:%M:%S} "
            f"{record.levelname:<7} {record.name}: {redact_text(record.getMessage())}"
        )
        if cid := _correlation_id.get():
            base += f" [{cid}]"
        return base


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Idempotent root-logger configuration."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    root.handlers[:] = [handler]
    # Quiet noisy third-party loggers; app loggers inherit root level.
    for noisy in ("urllib3", "botocore", "httpx", "uvicorn.access"):
        logging.getLogger(noisy).setLevel("WARNING")
