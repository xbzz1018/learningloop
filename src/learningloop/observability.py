from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from learningloop.config import Settings


class Telemetry:
    """Optional OpenTelemetry bridge; local JSONL/SQLite remain the source of truth."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = False
        self.tracer: Any = None
        if not settings.otel_enabled:
            return
        try:
            from opentelemetry import trace

            if settings.otel_exporter_endpoint:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                provider = TracerProvider(
                    resource=Resource.create({"service.name": settings.otel_service_name})
                )
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint))
                )
                trace.set_tracer_provider(provider)
            self.tracer = trace.get_tracer(settings.otel_service_name)
            self.enabled = True
        except ImportError:
            # Observability is optional; missing extras must not break the learning service.
            self.enabled = False

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
        if not self.enabled or self.tracer is None:
            with nullcontext() as span:
                yield span
            return
        with self.tracer.start_as_current_span(name) as span:
            for key, value in (attributes or {}).items():
                if value is not None:
                    span.set_attribute(key, value)
            yield span
