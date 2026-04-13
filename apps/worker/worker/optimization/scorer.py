"""Utilisation scoring — converts (ResourceSpec, ForecastedUsage) into
actionable signal before any solver runs.

Design
------
* All functions are pure (no I/O, no state) → trivially testable.
* Output is deterministic for a given (spec, usage, constraints) triple.
* ``score_resource`` is the primary entry point; it is called once per
  resource in O(1) time, so the full pass over N resources is O(N).
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import CloudProvider
from .types import ForecastedUsage
from .types import InstanceType
from .types import OptimizationConstraints
from .types import ResourceSpec

# ── Public output type ────────────────────────────────────────────────────────

@dataclass(slots=True)
class UtilisationProfile:
    """Scoring artefact for one resource."""

    resource_id: str

    # Absolute peak demands (after applying headroom)
    required_cpu_cores: float     # vcpu needed to satisfy p95 + headroom
    required_mem_gb:    float     # memory GB needed to satisfy p95 + headroom

    # Fractional waste relative to provisioned capacity
    cpu_waste_frac: float         # 1 - cpu_p95 ∈ [0, 1]
    mem_waste_frac: float         # 1 - mem_p95 ∈ [0, 1]

    # Composite waste: max of CPU and memory waste (worst dimension drives sizing)
    composite_waste: float        # 0 = fully utilised, 1 = completely idle

    # Flags used for action routing
    is_idle:      bool            # both dimensions below idle threshold
    is_oversized: bool            # composite_waste > some threshold
    ri_viable:    bool            # stable enough to benefit from reservation

    # Confidence in usage data (low when fewer samples than expected)
    data_confidence: float        # 0.0–1.0


def score_resource(
    spec: ResourceSpec,
    usage: ForecastedUsage,
    constraints: OptimizationConstraints,
) -> UtilisationProfile:
    """Compute a utilisation profile for *spec* given *usage*.

    Parameters
    ----------
    spec:
        Currently provisioned resource.
    usage:
        Forecasted peak/median utilisation fractions (0–1).
    constraints:
        Engine constraints (headroom, idle thresholds, etc.).

    Returns
    -------
    :class:`UtilisationProfile`
    """
    cpu_p95 = _clamp(usage.cpu_p95)
    mem_p95 = _clamp(usage.mem_p95)

    # ── Idle detection ────────────────────────────────────────────────────────
    is_idle = (
        cpu_p95 < constraints.idle_cpu_p95
        and mem_p95 < constraints.idle_mem_p95
    )

    # ── Waste fractions ───────────────────────────────────────────────────────
    cpu_waste = 1.0 - cpu_p95
    mem_waste = 1.0 - mem_p95
    composite_waste = max(cpu_waste, mem_waste)

    # ── Required capacity (p95 demand + headroom) ─────────────────────────────
    required_cpu_frac = min(cpu_p95 * (1.0 + constraints.cpu_headroom), 1.0)
    required_mem_frac = min(mem_p95 * (1.0 + constraints.mem_headroom), 1.0)
    required_cpu_cores = spec.vcpu * required_cpu_frac
    required_mem_gb    = spec.memory_gb * required_mem_frac

    # ── Oversized flag ────────────────────────────────────────────────────────
    # A resource is "oversized" if the cheapest feasible instance is materially
    # cheaper than the current one.  We determine that in the solver, but the
    # flag here is whether there's *any* waste worth investigating.
    is_oversized = composite_waste > 0.30 and not is_idle

    # ── Reserved-instance viability ───────────────────────────────────────────
    # Reservation is worthwhile when:
    # (a) the resource is used consistently (high p50 relative to p95), AND
    # (b) it runs close to 24 h / day
    coefficient_of_variation = _cv(usage.cpu_p50, usage.cpu_p95)
    is_stable  = coefficient_of_variation < 0.5   # low variance → predictable
    is_running = usage.avg_daily_hours >= 20.0     # essentially always-on
    ri_viable  = (
        is_stable
        and is_running
        and cpu_p95 >= constraints.min_utilisation_for_reserve
        and not is_idle
    )

    # ── Data confidence ───────────────────────────────────────────────────────
    # horizon_days < 7 → short window, lower confidence
    data_confidence = min(1.0, usage.horizon_days / 14.0)

    return UtilisationProfile(
        resource_id=spec.id,
        required_cpu_cores=required_cpu_cores,
        required_mem_gb=required_mem_gb,
        cpu_waste_frac=cpu_waste,
        mem_waste_frac=mem_waste,
        composite_waste=composite_waste,
        is_idle=is_idle,
        is_oversized=is_oversized,
        ri_viable=ri_viable,
        data_confidence=data_confidence,
    )


def find_cheapest_feasible(
    required_cpu: float,
    required_mem: float,
    candidates: list[InstanceType],
    same_provider: CloudProvider,
    same_region: str,
) -> InstanceType | None:
    """Return the cheapest instance type that satisfies *required_cpu* and
    *required_mem*, filtering to *same_provider* and *same_region*.

    Tie-breaking: lower cost → higher generation → alphabetical name (deterministic).
    Returns ``None`` if no feasible type exists.
    """
    feasible = [
        t for t in candidates
        if (
            t.provider == same_provider
            and t.region == same_region
            and t.vcpu      >= required_cpu
            and t.memory_gb >= required_mem
        )
    ]
    if not feasible:
        return None
    # Deterministic sort: cost asc, then generation desc (prefer newer), then name
    feasible.sort(key=lambda t: (t.cost_hourly, -t.generation, t.name))
    return feasible[0]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _cv(p50: float, p95: float) -> float:
    """Approximate coefficient of variation from percentiles.

    Assumes a log-normal distribution: sigma ≈ (ln(p95) - ln(p50)) / 1.645
    Returns 0 when both values are zero.
    """
    if p50 <= 0 or p95 <= 0:
        return 0.0
    import math
    return abs(math.log(max(p95, 1e-9)) - math.log(max(p50, 1e-9))) / 1.645


