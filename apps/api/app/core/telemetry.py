"""OpenTelemetry tracing and Prometheus metrics for the API."""

from __future__ import annotations

import time
from collections.abc import Awaitable
from collections.abc import Callable
from functools import lru_cache

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.resources import SERVICE_VERSION
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Histogram
from prometheus_client import make_asgi_app
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings

REQUEST_LATENCY_SECONDS = Histogram(
    "atlas_api_request_duration_seconds",
    "HTTP request latency for the Atlas API.",
    labelnames=("method", "route", "status_code"),
)


def current_trace_context() -> dict[str, str]:
    """Return trace/span ids for the active span when present."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


@lru_cache(maxsize=1)
def _build_provider(service_name: str, version: str, environment: str) -> TracerProvider:
    current_provider = trace.get_tracer_provider()
    if isinstance(current_provider, TracerProvider):
        return current_provider
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: version,
            DEPLOYMENT_ENVIRONMENT: environment,
        }
    )
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    return provider


def setup_telemetry(app: FastAPI, settings: Settings) -> None:
    """Configure OpenTelemetry tracing and expose Prometheus metrics."""
    if settings.metrics_enabled:
        app.mount(settings.metrics_path, make_asgi_app())
        app.middleware("http")(_request_metrics_middleware)

    if not settings.otel_enabled:
        return

    provider = _build_provider(
        settings.otel_service_name,
        settings.app_version,
        settings.otel_environment,
    )
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


async def _request_metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    REQUEST_LATENCY_SECONDS.labels(
        method=request.method,
        route=route_path,
        status_code=str(response.status_code),
    ).observe(elapsed)
    return response
