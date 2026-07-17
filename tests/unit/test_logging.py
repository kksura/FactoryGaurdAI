import json
import logging

from factoryguard.security.redaction import REDACTED
from factoryguard.utilities.logging import (
    JsonFormatter,
    get_correlation_id,
    set_correlation_id,
)


def _format(record_msg: str, **extra: object) -> dict:
    logger = logging.getLogger("test.fg")
    record = logger.makeRecord("test.fg", logging.INFO, __file__, 1, record_msg, (), None)
    for k, v in extra.items():
        setattr(record, k, v)
    return json.loads(JsonFormatter().format(record))


def test_json_structure() -> None:
    out = _format("hello")
    assert out["level"] == "INFO"
    assert out["message"] == "hello"
    assert "ts" in out


def test_correlation_id_included() -> None:
    set_correlation_id("cor-" + "a" * 32)
    try:
        out = _format("traced")
        assert out["correlation_id"] == "cor-" + "a" * 32
    finally:
        set_correlation_id(None)
    assert get_correlation_id() is None


def test_secrets_redacted_from_message_and_extras() -> None:
    out = _format(
        "auth used Bearer supersecrettoken123",
        api_key="sk-notreal-abc",
        unit_id="UNIT-1",
    )
    assert "supersecrettoken123" not in out["message"]
    assert out["extra"]["api_key"] == REDACTED
    assert out["extra"]["unit_id"] == "UNIT-1"
