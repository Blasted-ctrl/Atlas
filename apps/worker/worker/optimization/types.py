"""Shared types for the cost-optimization engine.

All public dataclasses are frozen (hashable, safely cached) and follow
strict ordering by ``resource_id`` as the canonical tie-breaker, ensuring
deterministic output regardless of input ordering.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Final

# ── Enums ─────────────────────────────────────────────────────────────────────

class CloudProvider(str, Enum):
    AWS   = "aws"
    GCP   = "gcp"
    AZURE = "azure"


class RecommendationAction(str, Enum):
    TERMINATE   = "terminate"
    DOWNSIZE    = "downsize"
    RESERVE_1YR = "reserve_1yr"
    RESERVE_3YR = "reserve_3yr"
    KEEP        = "keep"


class RiskLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


class AlgorithmName(str, Enum):
    GREEDY         = "greedy"
    MILP           = "milp"
    HYBRID         = "hybrid"
    FFD_PACK       = "ffd"


# ── Core input types ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResourceSpec:
    """A currently provisioned cloud resource."""

    id: str                    # globally unique resource UUID
    instance_type: str         # e.g. "m5.xlarge"
    vcpu: float                # provisioned vCPUs
    memory_gb: float           # provisioned memory in GB
    cost_hourly: float         # on-demand hourly rate (USD)
    provider: CloudProvider
    region: str
    account_id: str = ""
    tags: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def cost_monthly(self) -> float:
        return self.cost_hourly * _HOURS_PER_MONTH


@dataclass(frozen=True)
class ForecastedUsage:
    """Forecasted peak and average usage for a resource over the planning horizon.

    All utilisation fields are fractions in [0, 1] relative to provisioned
    capacity (not absolute cores/GB).
    """

    resource_id: str
    cpu_p50:     float   # median CPU utilisation fraction
    cpu_p95:     float   # 95th-percentile CPU (used for headroom sizing)
    mem_p50:     float   # median memory utilisation fraction
    mem_p95:     float   # 95th-percentile memory
    avg_daily_hours: float = 24.0   # average hours/day resource is active
    horizon_days: int = 30          # planning horizon these forecasts cover


@dataclass(frozen=True)
class InstanceType:
    """A purchasable cloud instance type with optional reserved pricing."""

    name: str
    vcpu: float
    memory_gb: float
    cost_hourly: float              # on-demand price
    reserved_1yr_hourly: float      # amortised hourly for 1-yr all-upfront reserved
    reserved_3yr_hourly: float      # amortised hourly for 3-yr all-upfront reserved
    upfront_1yr: float              # upfront payment required for 1-yr reservation
    upfront_3yr: float              # upfront payment required for 3-yr reservation
    provider: CloudProvider
    region: str
    generation: int = 1             # higher = newer; prefer newer for same cost

    @property
    def cost_monthly(self) -> float:
        return self.cost_hourly * _HOURS_PER_MONTH

    @property
    def reserved_1yr_monthly(self) -> float:
        return self.reserved_1yr_hourly * _HOURS_PER_MONTH

    @property
    def reserved_3yr_monthly(self) -> float:
        return self.reserved_3yr_hourly * _HOURS_PER_MONTH

    @property
    def vcpu_cost_ratio(self) -> float:
        """Cost per vCPU-hour (used for efficiency ranking)."""
        return self.cost_hourly / max(self.vcpu, 0.001)

    @property
    def mem_cost_ratio(self) -> float:
        """Cost per GB-hour."""
        return self.cost_hourly / max(self.memory_gb, 0.001)


@dataclass(frozen=True)
class OptimizationConstraints:
    """Tunable knobs passed to the engine."""

    # Sizing headroom — target instance must have this much slack above p95
    cpu_headroom:  float = 0.20   # 20% free above p95 CPU
    mem_headroom:  float = 0.20   # 20% free above p95 memory

    # Termination — resource is "idle" when BOTH metrics stay below threshold
    idle_cpu_p95:  float = 0.02   # < 2% CPU p95 → idle
    idle_mem_p95:  float = 0.10   # < 10% memory p95 → idle

    # Economic filters
    min_savings_monthly: float = 10.0   # skip recommendations below this threshold
    reserved_upfront_budget: float = 1_000_000.0  # max total RI upfront commitment (USD)
    min_utilisation_for_reserve: float = 0.30  # don't reserve spiky resources

    # What actions are permitted
    allow_terminate: bool = True
    allow_downsize:  bool = True
    allow_reserve:   bool = True

    # Solver tuning
    milp_candidate_limit: int = 1_000  # switch to greedy knapsack above this size


# ── Output types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Recommendation:
    """A single cost-optimization action for one resource."""

    resource_id: str
    action: RecommendationAction
    current_instance_type: str
    target_instance_type: str | None          # None for TERMINATE / KEEP

    current_cost_monthly:   float
    projected_cost_monthly: float
    savings_monthly:        float
    savings_pct:            float             # 0–100

    confidence: float      # 0.0–1.0
    risk:       RiskLevel
    reason:     str

    @property
    def savings_annual(self) -> float:
        return self.savings_monthly * 12

    @property
    def priority(self) -> int:
        """1 = high, 2 = medium, 3 = low (for UI sorting)."""
        if self.savings_monthly >= 500:
            return 1
        if self.savings_monthly >= 100:
            return 2
        return 3

    def sort_key(self) -> tuple:
        """Deterministic sort: savings desc, then resource_id asc."""
        return (-self.savings_monthly, self.resource_id)


@dataclass
class OptimizationResult:
    """Full output from :class:`~worker.optimization.engine.CostOptimizationEngine`."""

    recommendations: list[Recommendation]
    algorithm: AlgorithmName
    elapsed_ms: float

    # Aggregate stats
    n_resources:          int
    n_recommendations:    int
    total_savings_monthly: float
    total_savings_annual:  float
    savings_by_action: dict[str, float]   # action.value → monthly savings

    # Solver metadata
    n_milp_candidates:  int = 0    # resources evaluated by MILP (0 for pure greedy)
    milp_solved:        bool = False
    solver_status:      str = "ok"


# ── Intermediate types used inside the engine ─────────────────────────────────

@dataclass(frozen=True)
class SizedResource:
    """A resource after right-sizing analysis."""

    resource: ResourceSpec
    usage: ForecastedUsage
    target_type: InstanceType     # cheapest feasible instance type
    is_idle: bool
    peak_cpu_cores: float         # absolute peak CPU demand
    peak_mem_gb: float            # absolute peak memory demand


@dataclass(frozen=True)
class RICandidate:
    """A resource that is a candidate for reserved-instance conversion."""

    resource_id: str
    current_monthly: float
    reserved_1yr_monthly: float
    reserved_3yr_monthly: float
    upfront_1yr: float
    upfront_3yr: float
    savings_1yr_monthly: float
    savings_3yr_monthly: float
    utilisation_score: float      # higher = more confident in commitment


@dataclass
class PackingBin:
    """A single bin (VM instance) in the bin-packing solution."""

    instance_type: InstanceType
    workloads: list[str]          # resource IDs packed into this bin
    used_cpu: float               # sum of peak CPU cores of all workloads
    used_mem: float               # sum of peak memory GB

    @property
    def cpu_utilisation(self) -> float:
        return self.used_cpu / max(self.instance_type.vcpu, 0.001)

    @property
    def mem_utilisation(self) -> float:
        return self.used_mem / max(self.instance_type.memory_gb, 0.001)


# ── Constants ─────────────────────────────────────────────────────────────────

_HOURS_PER_MONTH: Final = 730    # 365.25 * 24 / 12
