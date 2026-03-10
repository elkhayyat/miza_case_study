"""OpenTelemetry tracing setup — no-op when disabled."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.trace import Tracer, TracerProvider
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def setup_tracing(app: FastAPI) -> TracerProvider | None:
    """Configure OTel tracing if enabled. Returns None when disabled."""
    settings = get_settings()
    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing disabled")
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_endpoint:
        exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_endpoint,
            insecure=settings.otel_exporter_insecure,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    RedisInstrumentor().instrument()

    endpoint = settings.otel_exporter_endpoint or "no exporter"
    logger.info("OpenTelemetry tracing enabled → %s", endpoint)
    return provider


def setup_sqlalchemy_tracing(engine: AsyncEngine) -> None:
    """Instrument SQLAlchemy engine if OTel is enabled."""
    settings = get_settings()
    if not settings.otel_enabled:
        return

    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    logger.info("SQLAlchemy tracing instrumented")


def get_tracer(name: str) -> Tracer:
    """Return the current tracer (no-op when OTel is not configured)."""
    from opentelemetry import trace

    return trace.get_tracer(name)
