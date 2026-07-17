"""Secret redaction for logs and error payloads.

Two layers: key-based redaction (any mapping key that looks sensitive) and
pattern-based redaction (values that look like tokens/keys/connection strings
wherever they appear). Applied by the logging formatter to every record.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|auth|credential|"
    r"connection[_-]?string|private[_-]?key|cookie|session)",
    re.IGNORECASE,
)

_SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9._\-]{10,}"),  # JWT
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),  # Azure storage conn string
    re.compile(r"(?i)sig=[A-Za-z0-9%+/=]{20,}"),  # SAS signature
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(postgres(?:ql)?|mysql|redis|amqp)://[^:\s]+:[^@\s]+@"),  # url creds
]


def redact_text(text: str) -> str:
    """Redact token-shaped substrings from free text."""
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return REDACTED
    return redact_any(value)


def redact_any(value: Any) -> Any:
    """Recursively redact a structure of dicts/lists/strings."""
    if isinstance(value, Mapping):
        return {str(k): redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_any(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
