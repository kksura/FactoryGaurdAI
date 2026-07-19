"""OpenTelemetry tracing setup (spec §20).

Only the OTel API/SDK are pinned — no OTLP exporter package — so locally
the span exporter is the console one (enabled when ``otel_endpoint`` is
set to the literal ``console``) or a no-op. The Azure design exports via
the collector sidecar (Phase 7); the instrumentation points are the same
either way. ``span()`` is safe to call with tracing disabled.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

_tracer: Any = None


def setup_tracing(otel_endpoint: str, service_name: str = "factoryguard-api") -> bool:
    """Initialize the tracer provider. Returns True when tracing is active."""
    global _tracer
    if not otel_endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if otel_endpoint == "console":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        else:
            # No OTLP exporter in the pinned env: document, don't crash.
            log.warning(
                "otel endpoint %s configured but no OTLP exporter is pinned; "
                "spans are recorded with a no-op exporter (Phase 7 wires the "
                "collector)",
                otel_endpoint,
            )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        return True
    except Exception as exc:
        log.warning("otel setup failed (%s); tracing disabled", exc)
        return False


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as sp:
        for key, value in attributes.items():
            sp.set_attribute(key, value)
        yield
