"""Worker tracing and Prometheus metrics."""

from __future__ import annotations

import time
from contextlib import contextmanager
from functools import lru_cache
from threading import Lock
from typing import Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.resources import SERVICE_VERSION
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram
from prometheus_client import start_http_server

from worker.config import WorkerSettings

FORECAST_LATENCY_SECONDS = Histogram(
    "atlas_forecast_latency_seconds",
    "End-to-end forecast execution time.",
    labelnames=("metric", "from_cache"),
)
OPTIMIZATION_LATENCY_SECONDS = Histogram(
    "atlas_optimization_latency_seconds",
    "Optimization execution time.",
    labelnames=("algorithm", "scope"),
)
COST_SAVINGS_PERCENT = Gauge(
    "atlas_cost_savings_percent",
    "Estimated savings percentage from the latest optimization run.",
    labelnames=("scope",),
)
QUEUE_DEPTH = Gauge(
    "atlas_queue_depth",
    "Current Redis queue depth by queue name.",
    labelnames=("queue",),
)
JOB_FAILURES_TOTAL = Counter(
    "atlas_job_failures_total",
    "Failed background jobs routed to the DLQ.",
    labelnames=("task_name", "queue"),
)
FORECAST_ERROR_PERCENT = Gauge(
    "atlas_forecast_error_percent",
    "Latest observed forecast MAPE value.",
    labelnames=("metric",),
)

_metrics_server_started = False
_metrics_lock = Lock()


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


def setup_telemetry(settings: WorkerSettings, *, version: str = "0.0.1") -> None:
    """Configure tracing and start the worker metrics server."""
    global _metrics_server_started

    if settings.metrics_enabled:
        with _metrics_lock:
            if not _metrics_server_started:
                try:
                    start_http_server(settings.worker_metrics_port)
                except OSError:
                    pass
                _metrics_server_started = True

    if not settings.otel_enabled:
        return

    provider = _build_provider(
        settings.otel_service_name,
        version,
        settings.otel_environment,
    )
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))


def get_tracer(name: str):
    """Return a named tracer."""
    return trace.get_tracer(name)


@contextmanager
def worker_span(name: str, **attributes: object) -> Iterator[object]:
    """Create a span for worker-side units of work."""
    with get_tracer("atlas.worker").start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span


def observe_forecast(metric: str, elapsed_seconds: float, *, from_cache: bool, mape: float | None) -> None:
    FORECAST_LATENCY_SECONDS.labels(metric=metric, from_cache=str(from_cache).lower()).observe(
        elapsed_seconds
    )
    if mape is not None:
        FORECAST_ERROR_PERCENT.labels(metric=metric).set(mape)


def observe_optimization(algorithm: str, elapsed_seconds: float, *, scope: str) -> None:
    OPTIMIZATION_LATENCY_SECONDS.labels(algorithm=algorithm, scope=scope).observe(elapsed_seconds)


def observe_cost_savings(total_monthly_cost: float, savings_monthly: float, *, scope: str) -> None:
    if total_monthly_cost <= 0:
        percent = 0.0
    else:
        percent = (savings_monthly / total_monthly_cost) * 100.0
    COST_SAVINGS_PERCENT.labels(scope=scope).set(round(percent, 4))


def update_queue_depth(queue: str, depth: int) -> None:
    QUEUE_DEPTH.labels(queue=queue).set(depth)


def increment_job_failure(task_name: str, queue: str) -> None:
    JOB_FAILURES_TOTAL.labels(task_name=task_name, queue=queue).inc()


@contextmanager
def timed_operation(
    span_name: str,
    *,
    attributes: dict[str, object] | None = None,
) -> Iterator[callable]:
    """Yield a callable that returns elapsed seconds on demand."""
    started = time.perf_counter()
    with worker_span(span_name, **(attributes or {})):
        yield lambda: time.perf_counter() - started
