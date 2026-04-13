"""Root conftest.py — shared fixtures available to every test module.

Scope conventions
-----------------
session   — expensive objects built once per pytest run (large datasets, engine)
module    — objects shared within a test file
function  — default; rebuilt for each test (safe for mutation)

Marker hooks
------------
Tests marked @pytest.mark.slow are skipped unless --run-slow is passed.
Tests marked @pytest.mark.load are never run by pytest (use locust directly).
"""

from __future__ import annotations

import numpy as np
import pytest

from worker.config import get_settings
from worker.optimization.benchmark import build_instance_catalogue
from worker.optimization.engine import CostOptimizationEngine
from worker.optimization.types import CloudProvider
from worker.optimization.types import ForecastedUsage
from worker.optimization.types import InstanceType
from worker.optimization.types import OptimizationConstraints
from worker.optimization.types import ResourceSpec


@pytest.fixture(autouse=True)
def worker_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic and local-only."""
    monkeypatch.setenv("OTEL_ENABLED", "false")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    get_settings.cache_clear()

# ── CLI option for slow tests ─────────────────────────────────────────────────

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow", action="store_true", default=False,
        help="Include tests marked @pytest.mark.slow",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="Pass --run-slow to enable")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)

    # Load tests are never collected by pytest
    skip_load = pytest.mark.skip(reason="Load tests run via locust, not pytest")
    for item in items:
        if "load" in item.keywords:
            item.add_marker(skip_load)


# ── Instance type catalogue ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def catalogue() -> list[InstanceType]:
    """Full AWS us-east-1 instance catalogue (built once per session)."""
    return build_instance_catalogue()


@pytest.fixture(scope="session")
def engine(catalogue: list[InstanceType]) -> CostOptimizationEngine:
    """Shared engine instance (stateless, safe to reuse across tests)."""
    return CostOptimizationEngine(instance_types=catalogue)


# ── Constraint presets ────────────────────────────────────────────────────────

@pytest.fixture()
def default_constraints() -> OptimizationConstraints:
    return OptimizationConstraints()


@pytest.fixture()
def tight_constraints() -> OptimizationConstraints:
    """Very aggressive thresholds — useful for edge-case tests."""
    return OptimizationConstraints(
        cpu_headroom=0.05,
        mem_headroom=0.05,
        min_savings_monthly=1.0,
        reserved_upfront_budget=500_000.0,
    )


@pytest.fixture()
def conservative_constraints() -> OptimizationConstraints:
    """Conservative thresholds — should produce fewer recommendations."""
    return OptimizationConstraints(
        cpu_headroom=0.40,
        mem_headroom=0.40,
        min_savings_monthly=200.0,
        reserved_upfront_budget=50_000.0,
    )


# ── Canonical instance types ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def m5_large(catalogue: list[InstanceType]) -> InstanceType:
    return next(t for t in catalogue if t.name == "m5.large")


@pytest.fixture(scope="session")
def m5_4xlarge(catalogue: list[InstanceType]) -> InstanceType:
    return next(t for t in catalogue if t.name == "m5.4xlarge")


# ── Resource builders ─────────────────────────────────────────────────────────

def make_spec(
    rid: str,
    instance_type: str = "m5.2xlarge",
    vcpu: float = 8.0,
    memory_gb: float = 32.0,
    cost_hourly: float = 0.384,
    region: str = "us-east-1",
) -> ResourceSpec:
    return ResourceSpec(
        id=rid,
        instance_type=instance_type,
        vcpu=vcpu,
        memory_gb=memory_gb,
        cost_hourly=cost_hourly,
        provider=CloudProvider.AWS,
        region=region,
    )


def make_usage(
    rid: str,
    cpu_p95: float = 0.50,
    mem_p95: float = 0.50,
    *,
    cpu_p50: float | None = None,
    mem_p50: float | None = None,
    hours: float = 24.0,
    horizon: int = 30,
) -> ForecastedUsage:
    return ForecastedUsage(
        resource_id=rid,
        cpu_p50=cpu_p50 if cpu_p50 is not None else cpu_p95 * 0.7,
        cpu_p95=cpu_p95,
        mem_p50=mem_p50 if mem_p50 is not None else mem_p95 * 0.7,
        mem_p95=mem_p95,
        avg_daily_hours=hours,
        horizon_days=horizon,
    )


@pytest.fixture()
def idle_resource() -> tuple[ResourceSpec, ForecastedUsage]:
    spec  = make_spec("idle-001", "m5.2xlarge", 8, 32, 0.384)
    usage = make_usage("idle-001", cpu_p95=0.010, mem_p95=0.030, hours=2.0)
    return spec, usage


@pytest.fixture()
def oversized_resource() -> tuple[ResourceSpec, ForecastedUsage]:
    spec  = make_spec("over-001", "m5.4xlarge", 16, 64, 0.768)
    usage = make_usage("over-001", cpu_p95=0.12, mem_p95=0.18)
    return spec, usage


@pytest.fixture()
def rightsized_resource() -> tuple[ResourceSpec, ForecastedUsage]:
    spec  = make_spec("right-001", "m5.large", 2, 8, 0.096)
    usage = make_usage("right-001", cpu_p95=0.72, mem_p95=0.68, hours=24.0)
    return spec, usage


# ── Small mixed dataset (for engine tests) ────────────────────────────────────

@pytest.fixture()
def mixed_dataset() -> tuple[list[ResourceSpec], list[ForecastedUsage]]:
    """30 resources: 8 idle, 15 oversized, 7 rightsized."""
    rng = np.random.default_rng(seed=2024)
    specs: list[ResourceSpec] = []
    usages: list[ForecastedUsage] = []

    instance_pool = [
        ("m5.2xlarge", 8, 32, 0.384),
        ("m5.4xlarge", 16, 64, 0.768),
        ("c5.2xlarge", 8, 16, 0.340),
    ]
    categories = (["idle"] * 8 + ["oversized"] * 15 + ["rightsized"] * 7)

    for i, cat in enumerate(categories):
        name, vcpu, mem, od = instance_pool[i % 3]
        rid = f"mix-{i:03d}"

        if cat == "idle":
            cpu95 = float(rng.uniform(0.004, 0.015))
            mem95 = float(rng.uniform(0.015, 0.060))
            hours = float(rng.uniform(1, 4))
        elif cat == "oversized":
            cpu95 = float(rng.uniform(0.06, 0.22))
            mem95 = float(rng.uniform(0.08, 0.25))
            hours = 23.5
        else:
            cpu95 = float(rng.uniform(0.62, 0.82))
            mem95 = float(rng.uniform(0.55, 0.78))
            hours = 24.0

        specs.append(make_spec(rid, name, vcpu, mem, od))
        usages.append(make_usage(rid, cpu95, mem95, hours=hours))

    return specs, usages
