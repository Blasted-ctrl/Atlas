"""
Atlas Cloud Cost Optimizer — Python Client

Generated from openapi.yaml v1.0.0
Runtime: httpx (async + sync), Python 3.11+
Install: pip install httpx

All timestamps are ISO 8601 strings in UTC.
All monetary values are floats in USD.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    Generic,
    Literal,
    TypeVar,
)

import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Enumerations (typed aliases)
# ─────────────────────────────────────────────────────────────────────────────

CloudProvider = Literal["aws", "gcp", "azure"]

ResourceType = Literal[
    "ec2_instance",
    "rds_instance",
    "rds_cluster",
    "elasticache_cluster",
    "lambda_function",
    "s3_bucket",
    "eks_node_group",
    "elb",
    "ebs_volume",
    "cloudfront_distribution",
    "nat_gateway",
]

ResourceStatus = Literal["running", "stopped", "terminated", "pending", "unknown"]

MetricName = Literal[
    "cpu_utilization",
    "memory_utilization",
    "network_in_bytes",
    "network_out_bytes",
    "disk_read_ops",
    "disk_write_ops",
    "connections",
    "request_count",
    "error_rate",
]

Granularity = Literal["1m", "5m", "15m", "1h", "6h", "1d"]

RecommendationType = Literal[
    "resize_down",
    "resize_up",
    "terminate",
    "schedule",
    "reserved_instance",
    "savings_plan",
    "graviton_migration",
]

RecommendationStatus = Literal[
    "pending", "accepted", "rejected", "applied", "dismissed", "expired"
]

RecommendationAction = Literal["accept", "reject", "dismiss"]

ForecastGranularity = Literal["daily", "weekly", "monthly"]

OptimizationJobStatus = Literal["queued", "running", "completed", "failed"]

ErrorCode = Literal[
    "invalid_request",
    "authentication_required",
    "forbidden",
    "resource_not_found",
    "conflict",
    "rate_limit_exceeded",
    "internal_error",
    "service_unavailable",
]

# ─────────────────────────────────────────────────────────────────────────────
# Domain Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResourceNetwork:
    vpc_id: str | None
    subnet_id: str | None
    security_groups: list[str]
    public_ip: str | None
    private_ip: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResourceNetwork":
        return cls(
            vpc_id=d.get("vpc_id"),
            subnet_id=d.get("subnet_id"),
            security_groups=d.get("security_groups") or [],
            public_ip=d.get("public_ip"),
            private_ip=d.get("private_ip"),
        )


@dataclass(frozen=True)
class Resource:
    id: str
    external_id: str
    name: str | None
    type: ResourceType
    provider: CloudProvider
    account_id: str
    region: str
    availability_zone: str | None
    status: ResourceStatus
    instance_type: str | None
    tags: dict[str, str]
    monthly_cost_usd: float
    created_at: str
    last_seen_at: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Resource":
        return cls(
            id=d["id"],
            external_id=d["external_id"],
            name=d.get("name"),
            type=d["type"],
            provider=d["provider"],
            account_id=d["account_id"],
            region=d["region"],
            availability_zone=d.get("availability_zone"),
            status=d["status"],
            instance_type=d.get("instance_type"),
            tags=d.get("tags") or {},
            monthly_cost_usd=float(d["monthly_cost_usd"]),
            created_at=d["created_at"],
            last_seen_at=d["last_seen_at"],
        )


@dataclass(frozen=True)
class ResourceDetail(Resource):
    specs: dict[str, Any] | None = None
    network: ResourceNetwork | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ResourceDetail":  # type: ignore[override]
        base = Resource.from_dict(d)
        network_raw = d.get("network")
        return cls(
            **base.__dict__,
            specs=d.get("specs"),
            network=ResourceNetwork.from_dict(network_raw) if network_raw else None,
        )


@dataclass(frozen=True)
class MetricDatapoint:
    timestamp: str
    value: float
    unit: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MetricDatapoint":
        return cls(
            timestamp=d["timestamp"],
            value=float(d["value"]),
            unit=d["unit"],
        )


@dataclass(frozen=True)
class MetricStatistics:
    min: float
    max: float
    avg: float
    p50: float
    p90: float
    p99: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MetricStatistics":
        return cls(
            min=float(d["min"]),
            max=float(d["max"]),
            avg=float(d["avg"]),
            p50=float(d["p50"]),
            p90=float(d["p90"]),
            p99=float(d["p99"]),
        )


@dataclass(frozen=True)
class UsageMetric:
    resource_id: str
    metric: MetricName
    granularity: Granularity
    period_start: str
    period_end: str
    datapoints: list[MetricDatapoint]
    statistics: MetricStatistics | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UsageMetric":
        stats_raw = d.get("statistics")
        return cls(
            resource_id=d["resource_id"],
            metric=d["metric"],
            granularity=d["granularity"],
            period_start=d["period_start"],
            period_end=d["period_end"],
            datapoints=[MetricDatapoint.from_dict(dp) for dp in d.get("datapoints", [])],
            statistics=MetricStatistics.from_dict(stats_raw) if stats_raw else None,
        )


@dataclass(frozen=True)
class ScheduleSuggestion:
    start_cron: str
    stop_cron: str
    timezone: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScheduleSuggestion":
        return cls(
            start_cron=d["start_cron"],
            stop_cron=d["stop_cron"],
            timezone=d["timezone"],
        )


@dataclass(frozen=True)
class RecommendationDetails:
    current_instance_type: str | None
    recommended_instance_type: str | None
    current_monthly_cost_usd: float | None
    projected_monthly_cost_usd: float | None
    avg_cpu_utilization_percent: float | None
    avg_memory_utilization_percent: float | None
    observation_period_days: int | None
    schedule_suggestion: ScheduleSuggestion | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RecommendationDetails":
        sched_raw = d.get("schedule_suggestion")
        return cls(
            current_instance_type=d.get("current_instance_type"),
            recommended_instance_type=d.get("recommended_instance_type"),
            current_monthly_cost_usd=(
                float(d["current_monthly_cost_usd"])
                if d.get("current_monthly_cost_usd") is not None
                else None
            ),
            projected_monthly_cost_usd=(
                float(d["projected_monthly_cost_usd"])
                if d.get("projected_monthly_cost_usd") is not None
                else None
            ),
            avg_cpu_utilization_percent=d.get("avg_cpu_utilization_percent"),
            avg_memory_utilization_percent=d.get("avg_memory_utilization_percent"),
            observation_period_days=d.get("observation_period_days"),
            schedule_suggestion=(
                ScheduleSuggestion.from_dict(sched_raw) if sched_raw else None
            ),
        )


@dataclass(frozen=True)
class Recommendation:
    id: str
    resource_id: str
    type: RecommendationType
    status: RecommendationStatus
    title: str
    description: str
    savings_usd_monthly: float
    savings_usd_annual: float
    confidence: float
    details: RecommendationDetails | None
    created_at: str
    expires_at: str
    applied_at: str | None
    dismissed_at: str | None
    rejection_reason: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Recommendation":
        details_raw = d.get("details")
        return cls(
            id=d["id"],
            resource_id=d["resource_id"],
            type=d["type"],
            status=d["status"],
            title=d["title"],
            description=d["description"],
            savings_usd_monthly=float(d["savings_usd_monthly"]),
            savings_usd_annual=float(d["savings_usd_annual"]),
            confidence=float(d["confidence"]),
            details=RecommendationDetails.from_dict(details_raw) if details_raw else None,
            created_at=d["created_at"],
            expires_at=d["expires_at"],
            applied_at=d.get("applied_at"),
            dismissed_at=d.get("dismissed_at"),
            rejection_reason=d.get("rejection_reason"),
        )


@dataclass(frozen=True)
class ForecastScope:
    account_id: str | None = None
    region: str | None = None
    resource_type: ResourceType | None = None
    resource_id: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ForecastScope":
        return cls(
            account_id=d.get("account_id"),
            region=d.get("region"),
            resource_type=d.get("resource_type"),
            resource_id=d.get("resource_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "account_id": self.account_id,
                "region": self.region,
                "resource_type": self.resource_type,
                "resource_id": self.resource_id,
            }.items()
            if v is not None
        }


@dataclass(frozen=True)
class ForecastDatapoint:
    date: str
    cost_usd: float
    lower_bound_usd: float | None
    upper_bound_usd: float | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ForecastDatapoint":
        return cls(
            date=d["date"],
            cost_usd=float(d["cost_usd"]),
            lower_bound_usd=(
                float(d["lower_bound_usd"]) if d.get("lower_bound_usd") is not None else None
            ),
            upper_bound_usd=(
                float(d["upper_bound_usd"]) if d.get("upper_bound_usd") is not None else None
            ),
        )


@dataclass(frozen=True)
class Forecast:
    id: str
    scope: ForecastScope
    granularity: ForecastGranularity
    model: str
    confidence_level: float
    generated_at: str
    period_start: str
    period_end: str
    datapoints: list[ForecastDatapoint]
    total_cost_usd: float
    savings_opportunity_usd: float | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Forecast":
        return cls(
            id=d["id"],
            scope=ForecastScope.from_dict(d.get("scope") or {}),
            granularity=d["granularity"],
            model=d["model"],
            confidence_level=float(d["confidence_level"]),
            generated_at=d["generated_at"],
            period_start=d["period_start"],
            period_end=d["period_end"],
            datapoints=[ForecastDatapoint.from_dict(dp) for dp in d.get("datapoints", [])],
            total_cost_usd=float(d["total_cost_usd"]),
            savings_opportunity_usd=(
                float(d["savings_opportunity_usd"])
                if d.get("savings_opportunity_usd") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class AsyncJob:
    job_id: str
    status: OptimizationJobStatus
    created_at: str
    estimated_completion: str | None
    completed_at: str | None
    error_message: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AsyncJob":
        return cls(
            job_id=d["job_id"],
            status=d["status"],
            created_at=d["created_at"],
            estimated_completion=d.get("estimated_completion"),
            completed_at=d.get("completed_at"),
            error_message=d.get("error_message"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Pagination
# ─────────────────────────────────────────────────────────────────────────────

T = TypeVar("T")


@dataclass(frozen=True)
class PageInfo:
    total_count: int
    has_next_page: bool
    has_previous_page: bool
    next_cursor: str | None
    previous_cursor: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PageInfo":
        return cls(
            total_count=d["total_count"],
            has_next_page=d["has_next_page"],
            has_previous_page=d["has_previous_page"],
            next_cursor=d.get("next_cursor"),
            previous_cursor=d.get("previous_cursor"),
        )


@dataclass(frozen=True)
class Page(Generic[T]):
    data: list[T]
    pagination: PageInfo

    @classmethod
    def from_dict(
        cls, d: dict[str, Any], item_factory: Callable[[dict[str, Any]], T]
    ) -> "Page[T]":
        return cls(
            data=[item_factory(item) for item in d.get("data", [])],
            pagination=PageInfo.from_dict(d["pagination"]),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RateLimitInfo:
    """Parsed X-RateLimit-* response headers."""

    limit: int
    remaining: int
    reset: int  # Unix timestamp
    window: int  # seconds

    @classmethod
    def from_headers(cls, headers: httpx.Headers) -> "RateLimitInfo | None":
        try:
            return cls(
                limit=int(headers["x-ratelimit-limit"]),
                remaining=int(headers["x-ratelimit-remaining"]),
                reset=int(headers["x-ratelimit-reset"]),
                window=int(headers.get("x-ratelimit-window", "60")),
            )
        except (KeyError, ValueError):
            return None

    @property
    def reset_at(self) -> datetime:
        return datetime.utcfromtimestamp(self.reset)

    @property
    def seconds_until_reset(self) -> float:
        return max(0.0, self.reset - time.time())


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FieldError":
        return cls(field=d["field"], message=d["message"])


class AtlasApiError(Exception):
    """Raised when the Atlas API returns a non-2xx response."""

    def __init__(
        self,
        status_code: int,
        body: dict[str, Any],
        rate_limit: RateLimitInfo | None = None,
    ) -> None:
        self.status_code = status_code
        self.code: ErrorCode = body.get("code", "internal_error")
        self.message: str = body.get("message", "Unknown error")
        self.field_errors: list[FieldError] = [
            FieldError.from_dict(e) for e in (body.get("field_errors") or [])
        ]
        self.request_id: str = body.get("request_id", "unknown")
        self.documentation_url: str | None = body.get("documentation_url")
        self.rate_limit = rate_limit

        super().__init__(
            f"[{self.code}] {self.message} "
            f"(status={status_code}, request_id={self.request_id})"
        )

    @property
    def is_rate_limited(self) -> bool:
        return self.status_code == 429

    @property
    def is_not_found(self) -> bool:
        return self.status_code == 404

    @property
    def is_auth_error(self) -> bool:
        return self.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
# Internal Base Client
# ─────────────────────────────────────────────────────────────────────────────

_SENTINEL = object()


def _build_params(mapping: dict[str, Any]) -> dict[str, str]:
    """Convert a dict to string query params, dropping None values."""
    out: dict[str, str] = {}
    for key, value in mapping.items():
        if value is None or value is _SENTINEL:
            continue
        # Convert camelCase keys to snake_case (already snake_case in Python)
        if isinstance(value, list):
            # Repeat the key for list values
            # httpx handles list params natively; return as-is
            out[key] = ",".join(str(v) for v in value)
        elif isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


class _AsyncBaseClient:
    def __init__(self, client: "AsyncAtlasClient") -> None:
        self._c = client

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._c._request("GET", path, params=params)

    async def _post(self, path: str, body: Any = None) -> Any:
        return await self._c._request("POST", path, body=body)


class _SyncBaseClient:
    def __init__(self, client: "AtlasClient") -> None:
        self._c = client

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._c._request("GET", path, params=params)

    def _post(self, path: str, body: Any = None) -> Any:
        return self._c._request("POST", path, body=body)


# ─────────────────────────────────────────────────────────────────────────────
# Async Domain Clients
# ─────────────────────────────────────────────────────────────────────────────


class AsyncResourcesClient(_AsyncBaseClient):
    async def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        resource_type: ResourceType | None = None,
        provider: CloudProvider | None = None,
        account_id: str | None = None,
        region: str | None = None,
        status: ResourceStatus | None = None,
        tag: str | list[str] | None = None,
        min_monthly_cost: float | None = None,
        max_monthly_cost: float | None = None,
        sort: str | None = None,
    ) -> Page[Resource]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                resource_type=resource_type,
                provider=provider,
                account_id=account_id,
                region=region,
                status=status,
                tag=tag if isinstance(tag, list) else ([tag] if tag else None),
                min_monthly_cost=min_monthly_cost,
                max_monthly_cost=max_monthly_cost,
                sort=sort,
            )
        )
        raw = await self._get("/resources", params)
        return Page.from_dict(raw, Resource.from_dict)

    async def get(self, resource_id: str) -> ResourceDetail:
        raw = await self._get(f"/resources/{resource_id}")
        return ResourceDetail.from_dict(raw)

    async def iterate(self, **kwargs: Any) -> AsyncGenerator[Resource, None]:
        cursor: str | None = None
        while True:
            page = await self.list(cursor=cursor, limit=kwargs.pop("limit", 100), **kwargs)
            for resource in page.data:
                yield resource
            if not page.pagination.has_next_page or not page.pagination.next_cursor:
                break
            cursor = page.pagination.next_cursor


class AsyncUsageClient(_AsyncBaseClient):
    async def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        start_time: str | None = None,
        end_time: str | None = None,
        resource_type: ResourceType | None = None,
        resource_id: str | list[str] | None = None,
        metric: MetricName | None = None,
        granularity: Granularity = "1h",
        account_id: str | None = None,
        region: str | None = None,
    ) -> Page[UsageMetric]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
                resource_type=resource_type,
                resource_id=(
                    ",".join(resource_id)
                    if isinstance(resource_id, list)
                    else resource_id
                ),
                metric=metric,
                granularity=granularity,
                account_id=account_id,
                region=region,
            )
        )
        raw = await self._get("/usage", params)
        return Page.from_dict(raw, UsageMetric.from_dict)

    async def get_for_resource(
        self,
        resource_id: str,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        metric: MetricName | list[MetricName] | None = None,
        granularity: Granularity = "1h",
    ) -> list[UsageMetric]:
        params = _build_params(
            dict(
                start_time=start_time,
                end_time=end_time,
                metric=(
                    ",".join(metric) if isinstance(metric, list) else metric
                ),
                granularity=granularity,
            )
        )
        raw = await self._get(f"/usage/{resource_id}", params)
        return [UsageMetric.from_dict(item) for item in raw]


class AsyncRecommendationsClient(_AsyncBaseClient):
    async def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        resource_type: ResourceType | None = None,
        resource_id: str | None = None,
        type: RecommendationType | None = None,
        status: RecommendationStatus | None = None,
        min_savings: float | None = None,
        min_confidence: float | None = None,
        account_id: str | None = None,
        region: str | None = None,
        sort: str | None = None,
    ) -> Page[Recommendation]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                resource_type=resource_type,
                resource_id=resource_id,
                type=type,
                status=status,
                min_savings=min_savings,
                min_confidence=min_confidence,
                account_id=account_id,
                region=region,
                sort=sort,
            )
        )
        raw = await self._get("/recommendations", params)
        return Page.from_dict(raw, Recommendation.from_dict)

    async def get(self, recommendation_id: str) -> Recommendation:
        raw = await self._get(f"/recommendations/{recommendation_id}")
        return Recommendation.from_dict(raw)

    async def accept(self, recommendation_id: str) -> Recommendation:
        return await self._act(recommendation_id, "accept")

    async def reject(
        self, recommendation_id: str, reason: str | None = None
    ) -> Recommendation:
        return await self._act(recommendation_id, "reject", reason=reason)

    async def dismiss(
        self, recommendation_id: str, reason: str | None = None
    ) -> Recommendation:
        return await self._act(recommendation_id, "dismiss", reason=reason)

    async def _act(
        self,
        recommendation_id: str,
        action: RecommendationAction,
        reason: str | None = None,
    ) -> Recommendation:
        body: dict[str, Any] = {"action": action}
        if reason is not None:
            body["reason"] = reason
        raw = await self._post(
            f"/recommendations/{recommendation_id}/actions", body
        )
        return Recommendation.from_dict(raw)

    async def iterate(self, **kwargs: Any) -> AsyncGenerator[Recommendation, None]:
        cursor: str | None = None
        while True:
            page = await self.list(cursor=cursor, limit=kwargs.pop("limit", 100), **kwargs)
            for rec in page.data:
                yield rec
            if not page.pagination.has_next_page or not page.pagination.next_cursor:
                break
            cursor = page.pagination.next_cursor


class AsyncForecastsClient(_AsyncBaseClient):
    async def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        start_time: str | None = None,
        end_time: str | None = None,
        resource_type: ResourceType | None = None,
        account_id: str | None = None,
        region: str | None = None,
        resource_id: str | None = None,
        granularity: ForecastGranularity | None = None,
    ) -> Page[Forecast]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
                resource_type=resource_type,
                account_id=account_id,
                region=region,
                resource_id=resource_id,
                granularity=granularity,
            )
        )
        raw = await self._get("/forecasts", params)
        return Page.from_dict(raw, Forecast.from_dict)

    async def get(self, forecast_id: str) -> Forecast:
        raw = await self._get(f"/forecasts/{forecast_id}")
        return Forecast.from_dict(raw)

    async def generate(
        self,
        period_start: str,
        period_end: str,
        granularity: ForecastGranularity,
        scope: ForecastScope | None = None,
    ) -> AsyncJob:
        body: dict[str, Any] = {
            "period_start": period_start,
            "period_end": period_end,
            "granularity": granularity,
        }
        if scope is not None:
            body["scope"] = scope.to_dict()
        raw = await self._post("/forecasts/generate", body)
        return AsyncJob.from_dict(raw)


class AsyncOptimizationClient(_AsyncBaseClient):
    async def trigger(
        self,
        scope: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncJob:
        body: dict[str, Any] = {}
        if scope:
            body["scope"] = scope
        if options:
            body["options"] = options
        raw = await self._post("/optimize", body)
        return AsyncJob.from_dict(raw)

    async def get_job(self, job_id: str) -> AsyncJob:
        raw = await self._get(f"/optimize/{job_id}")
        return AsyncJob.from_dict(raw)

    async def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 600.0,
    ) -> AsyncJob:
        """
        Poll until the job reaches a terminal state (completed / failed).

        Raises:
            TimeoutError: if timeout_seconds elapses before the job finishes.

        Example::

            job = await client.optimize.trigger()
            done = await client.optimize.wait_for_job(job.job_id)
            print(done.status)  # "completed"
        """
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = await self.get_job(job_id)
            if job.status in ("completed", "failed"):
                return job
            remaining = deadline - time.monotonic()
            await asyncio.sleep(min(poll_interval_seconds, max(0, remaining)))

        raise TimeoutError(
            f"Optimization job {job_id} did not finish within {timeout_seconds}s"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Async Root Client
# ─────────────────────────────────────────────────────────────────────────────


class AsyncAtlasClient:
    """
    Async Atlas Cloud Cost Optimizer client.

    Usage::

        import asyncio
        from atlas_client import AsyncAtlasClient

        async def main():
            async with AsyncAtlasClient(api_key="ak_...") as atlas:
                page = await atlas.resources.list(
                    resource_type="ec2_instance",
                    status="running",
                    limit=50,
                )
                for resource in page.data:
                    print(resource.id, resource.monthly_cost_usd)

                # Accept all high-confidence resize recommendations
                async for rec in atlas.recommendations.iterate(
                    type="resize_down",
                    min_confidence=0.9,
                    status="pending",
                ):
                    await atlas.recommendations.accept(rec.id)

        asyncio.run(main())

    Args:
        api_key: Static API key (sends ``X-API-Key`` header).
        get_token: Async callable returning the current Bearer JWT.
                   Takes precedence over api_key if both are provided.
        base_url: Override the API base URL.
        timeout: Request timeout in seconds (default: 30).
        on_rate_limit: Optional callback invoked with RateLimitInfo after each response.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        get_token: Callable[[], Awaitable[str]] | None = None,
        base_url: str = "https://api.atlas.example.com/v1",
        timeout: float = 30.0,
        on_rate_limit: Callable[[RateLimitInfo], None] | None = None,
    ) -> None:
        if not api_key and not get_token:
            raise ValueError("Provide either `api_key` or `get_token`.")

        self._api_key = api_key
        self._get_token = get_token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._on_rate_limit = on_rate_limit
        self._http: httpx.AsyncClient | None = None

        self.resources = AsyncResourcesClient(self)
        self.usage = AsyncUsageClient(self)
        self.recommendations = AsyncRecommendationsClient(self)
        self.forecasts = AsyncForecastsClient(self)
        self.optimize = AsyncOptimizationClient(self)

    async def __aenter__(self) -> "AsyncAtlasClient":
        self._http = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _auth_headers(self) -> dict[str, str]:
        if self._get_token:
            token = await self._get_token()
            return {"Authorization": f"Bearer {token}"}
        return {"X-API-Key": self._api_key or ""}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: Any = None,
    ) -> Any:
        if self._http is None:
            raise RuntimeError(
                "Client is not open. Use `async with AsyncAtlasClient(...) as client:`."
            )

        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(await self._auth_headers()),
        }

        response = await self._http.request(
            method,
            url,
            params=params or {},
            json=body,
            headers=headers,
        )

        rate_limit = RateLimitInfo.from_headers(response.headers)
        if rate_limit and self._on_rate_limit:
            self._on_rate_limit(rate_limit)

        if response.is_error:
            try:
                err_body = response.json()
            except Exception:
                err_body = {
                    "code": "internal_error",
                    "message": f"HTTP {response.status_code}",
                    "request_id": response.headers.get("x-request-id", "unknown"),
                }
            raise AtlasApiError(response.status_code, err_body, rate_limit)

        if response.status_code == 204:
            return None

        return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# Sync Domain Clients
# ─────────────────────────────────────────────────────────────────────────────


class SyncResourcesClient(_SyncBaseClient):
    def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        resource_type: ResourceType | None = None,
        provider: CloudProvider | None = None,
        account_id: str | None = None,
        region: str | None = None,
        status: ResourceStatus | None = None,
        tag: str | list[str] | None = None,
        min_monthly_cost: float | None = None,
        max_monthly_cost: float | None = None,
        sort: str | None = None,
    ) -> Page[Resource]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                resource_type=resource_type,
                provider=provider,
                account_id=account_id,
                region=region,
                status=status,
                tag=tag if isinstance(tag, list) else ([tag] if tag else None),
                min_monthly_cost=min_monthly_cost,
                max_monthly_cost=max_monthly_cost,
                sort=sort,
            )
        )
        raw = self._get("/resources", params)
        return Page.from_dict(raw, Resource.from_dict)

    def get(self, resource_id: str) -> ResourceDetail:
        return ResourceDetail.from_dict(self._get(f"/resources/{resource_id}"))

    def iterate(self, **kwargs: Any) -> Generator[Resource, None, None]:
        cursor: str | None = None
        while True:
            page = self.list(cursor=cursor, limit=kwargs.pop("limit", 100), **kwargs)
            yield from page.data
            if not page.pagination.has_next_page or not page.pagination.next_cursor:
                break
            cursor = page.pagination.next_cursor


class SyncRecommendationsClient(_SyncBaseClient):
    def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        resource_type: ResourceType | None = None,
        resource_id: str | None = None,
        type: RecommendationType | None = None,
        status: RecommendationStatus | None = None,
        min_savings: float | None = None,
        min_confidence: float | None = None,
        account_id: str | None = None,
        region: str | None = None,
        sort: str | None = None,
    ) -> Page[Recommendation]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                resource_type=resource_type,
                resource_id=resource_id,
                type=type,
                status=status,
                min_savings=min_savings,
                min_confidence=min_confidence,
                account_id=account_id,
                region=region,
                sort=sort,
            )
        )
        raw = self._get("/recommendations", params)
        return Page.from_dict(raw, Recommendation.from_dict)

    def get(self, recommendation_id: str) -> Recommendation:
        return Recommendation.from_dict(
            self._get(f"/recommendations/{recommendation_id}")
        )

    def accept(self, recommendation_id: str) -> Recommendation:
        return self._act(recommendation_id, "accept")

    def reject(
        self, recommendation_id: str, reason: str | None = None
    ) -> Recommendation:
        return self._act(recommendation_id, "reject", reason=reason)

    def dismiss(
        self, recommendation_id: str, reason: str | None = None
    ) -> Recommendation:
        return self._act(recommendation_id, "dismiss", reason=reason)

    def _act(
        self,
        recommendation_id: str,
        action: RecommendationAction,
        reason: str | None = None,
    ) -> Recommendation:
        body: dict[str, Any] = {"action": action}
        if reason is not None:
            body["reason"] = reason
        return Recommendation.from_dict(
            self._post(f"/recommendations/{recommendation_id}/actions", body)
        )

    def iterate(self, **kwargs: Any) -> Generator[Recommendation, None, None]:
        cursor: str | None = None
        while True:
            page = self.list(cursor=cursor, limit=kwargs.pop("limit", 100), **kwargs)
            yield from page.data
            if not page.pagination.has_next_page or not page.pagination.next_cursor:
                break
            cursor = page.pagination.next_cursor


class SyncForecastsClient(_SyncBaseClient):
    def list(
        self,
        *,
        cursor: str | None = None,
        limit: int = 20,
        start_time: str | None = None,
        end_time: str | None = None,
        resource_type: ResourceType | None = None,
        account_id: str | None = None,
        region: str | None = None,
        resource_id: str | None = None,
        granularity: ForecastGranularity | None = None,
    ) -> Page[Forecast]:
        params = _build_params(
            dict(
                cursor=cursor,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
                resource_type=resource_type,
                account_id=account_id,
                region=region,
                resource_id=resource_id,
                granularity=granularity,
            )
        )
        raw = self._get("/forecasts", params)
        return Page.from_dict(raw, Forecast.from_dict)

    def get(self, forecast_id: str) -> Forecast:
        return Forecast.from_dict(self._get(f"/forecasts/{forecast_id}"))

    def generate(
        self,
        period_start: str,
        period_end: str,
        granularity: ForecastGranularity,
        scope: ForecastScope | None = None,
    ) -> AsyncJob:
        body: dict[str, Any] = {
            "period_start": period_start,
            "period_end": period_end,
            "granularity": granularity,
        }
        if scope is not None:
            body["scope"] = scope.to_dict()
        return AsyncJob.from_dict(self._post("/forecasts/generate", body))


class SyncOptimizationClient(_SyncBaseClient):
    def trigger(
        self,
        scope: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncJob:
        body: dict[str, Any] = {}
        if scope:
            body["scope"] = scope
        if options:
            body["options"] = options
        return AsyncJob.from_dict(self._post("/optimize", body))

    def get_job(self, job_id: str) -> AsyncJob:
        return AsyncJob.from_dict(self._get(f"/optimize/{job_id}"))

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 600.0,
    ) -> AsyncJob:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            if job.status in ("completed", "failed"):
                return job
            time.sleep(min(poll_interval_seconds, max(0, deadline - time.monotonic())))
        raise TimeoutError(
            f"Optimization job {job_id} did not finish within {timeout_seconds}s"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sync Root Client
# ─────────────────────────────────────────────────────────────────────────────


class AtlasClient:
    """
    Synchronous Atlas Cloud Cost Optimizer client.

    Prefer ``AsyncAtlasClient`` in async codebases. This client is a thin
    synchronous wrapper around httpx.Client.

    Usage::

        from atlas_client import AtlasClient

        with AtlasClient(api_key="ak_...") as atlas:
            page = atlas.resources.list(
                resource_type="ec2_instance",
                status="running",
                limit=50,
            )
            for resource in page.data:
                print(resource.id, resource.monthly_cost_usd)

            for rec in atlas.recommendations.iterate(
                type="resize_down",
                min_confidence=0.9,
                status="pending",
            ):
                atlas.recommendations.accept(rec.id)

    Args:
        api_key: Static API key.
        get_token: Callable returning the current Bearer JWT (sync).
        base_url: Override the API base URL.
        timeout: Request timeout in seconds (default: 30).
        on_rate_limit: Optional callback invoked with RateLimitInfo.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        get_token: Callable[[], str] | None = None,
        base_url: str = "https://api.atlas.example.com/v1",
        timeout: float = 30.0,
        on_rate_limit: Callable[[RateLimitInfo], None] | None = None,
    ) -> None:
        if not api_key and not get_token:
            raise ValueError("Provide either `api_key` or `get_token`.")

        self._api_key = api_key
        self._get_token = get_token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._on_rate_limit = on_rate_limit
        self._http: httpx.Client | None = None

        self.resources = SyncResourcesClient(self)
        self.recommendations = SyncRecommendationsClient(self)
        self.forecasts = SyncForecastsClient(self)
        self.optimize = SyncOptimizationClient(self)

    def __enter__(self) -> "AtlasClient":
        self._http = httpx.Client(timeout=self._timeout)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._http:
            self._http.close()
            self._http = None

    def _auth_headers(self) -> dict[str, str]:
        if self._get_token:
            return {"Authorization": f"Bearer {self._get_token()}"}
        return {"X-API-Key": self._api_key or ""}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: Any = None,
    ) -> Any:
        if self._http is None:
            raise RuntimeError(
                "Client is not open. Use `with AtlasClient(...) as client:`."
            )

        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self._auth_headers(),
        }

        response = self._http.request(
            method,
            url,
            params=params or {},
            json=body,
            headers=headers,
        )

        rate_limit = RateLimitInfo.from_headers(response.headers)
        if rate_limit and self._on_rate_limit:
            self._on_rate_limit(rate_limit)

        if response.is_error:
            try:
                err_body = response.json()
            except Exception:
                err_body = {
                    "code": "internal_error",
                    "message": f"HTTP {response.status_code}",
                    "request_id": response.headers.get("x-request-id", "unknown"),
                }
            raise AtlasApiError(response.status_code, err_body, rate_limit)

        if response.status_code == 204:
            return None

        return response.json()
