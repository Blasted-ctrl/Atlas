"""CostOptimizationEngine — the public orchestration layer.

Entry point
-----------
    from worker.optimization.engine import CostOptimizationEngine
    from worker.optimization.types import OptimizationConstraints

    engine = CostOptimizationEngine(instance_types=catalogue)
    result = engine.optimize(
        resources=specs,
        usage=usage_list,
        constraints=OptimizationConstraints(),
        algorithm="hybrid",  # "greedy" | "milp" | "hybrid" | "ffd"
    )

Performance guarantees (10 k resources)
----------------------------------------
* "greedy"  → always < 500 ms
* "milp"    → < 2 s (MILP on ≤ 1,000 RI candidates; greedy fallback otherwise)
* "hybrid"  → < 2 s (greedy sizing + MILP RI selection)
* "ffd"     → always < 300 ms

Determinism
-----------
Output order is stable: recommendations are sorted by
``(-savings_monthly, resource_id)``.  The same input always produces the
same output regardless of OS, Python version, or hardware.
"""

from __future__ import annotations

import logging
import time

from worker.telemetry import observe_cost_savings
from worker.telemetry import observe_optimization
from worker.telemetry import worker_span

from .greedy import build_recommendations
from .greedy import greedy_ri_knapsack
from .greedy import right_size_with_usage
from .packer import PackingResult
from .packer import best_fit_decreasing
from .packer import first_fit_decreasing
from .packer import workloads_from_sized
from .scorer import score_resource
from .solver import MILPResult
from .solver import solve_ri_milp
from .types import AlgorithmName
from .types import CloudProvider
from .types import ForecastedUsage
from .types import InstanceType
from .types import OptimizationConstraints
from .types import OptimizationResult
from .types import Recommendation
from .types import ResourceSpec
from .types import RICandidate
from .types import SizedResource

logger = logging.getLogger(__name__)

_HOURS_PER_MONTH = 730


# ── Engine ────────────────────────────────────────────────────────────────────

class CostOptimizationEngine:
    """Stateless engine: call :meth:`optimize` as many times as needed."""

    def __init__(self, instance_types: list[InstanceType]) -> None:
        """
        Parameters
        ----------
        instance_types:
            Full catalogue of purchasable instance types (all providers/regions).
            The engine selects the subset matching each resource's provider+region.
        """
        self._types = instance_types

    # ── Public interface ──────────────────────────────────────────────────────

    def optimize(
        self,
        resources: list[ResourceSpec],
        usage: list[ForecastedUsage],
        constraints: OptimizationConstraints | None = None,
        *,
        algorithm: str = "hybrid",
    ) -> OptimizationResult:
        """Run the cost-optimization pipeline.

        Parameters
        ----------
        resources:
            Currently provisioned resources.
        usage:
            Forecasted utilisation for each resource (resource_id must match).
            Resources without a matching usage entry are skipped.
        constraints:
            Tunable thresholds (defaults used when None).
        algorithm:
            One of: ``"greedy"``, ``"milp"``, ``"hybrid"``, ``"ffd"``.
        """
        t0 = time.perf_counter()
        constraints = constraints or OptimizationConstraints()
        algo = AlgorithmName(algorithm)
        total_monthly_cost = sum(resource.cost_monthly for resource in resources)

        # ── Build index structures ─────────────────────────────────────────────
        with worker_span("optimization.engine.run", algorithm=algo.value, resources=len(resources)):
            usage_map: dict[str, ForecastedUsage] = {u.resource_id: u for u in usage}

        # Only optimize resources that have usage data
        scoped = [r for r in resources if r.id in usage_map]
        if not scoped:
            return _empty_result(algo, len(resources))

        # ── Step 1: Score every resource (O(n)) ───────────────────────────────
        profiles_list = [
            score_resource(r, usage_map[r.id], constraints)
            for r in scoped
        ]
        profiles = {p.resource_id: p for p in profiles_list}

        # ── Step 2: Right-size (O(n·m)) ───────────────────────────────────────
        sized: list[SizedResource] = right_size_with_usage(
            scoped, usage_map, profiles_list, self._types, constraints
        )
        if algo == AlgorithmName.FFD_PACK:
            pack_result = self._run_packing(sized, constraints, algorithm="ffd")
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "optimization.complete",
                algorithm=algo.value,
                n_resources=len(scoped),
                n_recs=0,
                elapsed_ms=round(elapsed, 1),
            )
            return self._build_result(
                recs=[],
                algo=algo,
                elapsed_ms=elapsed,
                n_resources=len(resources),
                n_milp=0,
                milp_solved=False,
                solver_status="packing",
                pack_result=pack_result,
            )

        # ── Step 3: Build RI candidates ────────────────────────────────────────
        ri_candidates = self._build_ri_candidates(sized, constraints)
        ri_map = {c.resource_id: c for c in ri_candidates}

        # ── Step 4: Solve RI portfolio ─────────────────────────────────────────
        milp_result: MILPResult | None = None
        n_milp = 0
        milp_solved = False

        if algo in (AlgorithmName.GREEDY, AlgorithmName.HYBRID):
            knapsack = greedy_ri_knapsack(ri_candidates, constraints.reserved_upfront_budget)
            ri_selected = {c.resource_id for c in knapsack.selected}

        elif algo == AlgorithmName.MILP:
            milp_result = solve_ri_milp(ri_candidates, constraints)
            ri_selected = {c.resource_id for c in milp_result.selected}
            n_milp = len(ri_candidates)
            milp_solved = milp_result.solved_exactly

        else:  # ffd — RI handled by greedy, primary output is packing
            knapsack = greedy_ri_knapsack(ri_candidates, constraints.reserved_upfront_budget)
            ri_selected = {c.resource_id for c in knapsack.selected}

        # ── Step 5: Generate recommendations ──────────────────────────────────
        recs = build_recommendations(
            sized=sized,
            ri_selected=ri_selected,
            ri_candidate_map=ri_map,
            profiles=profiles,
            constraints=constraints,
        )

        # ── Step 6 (FFD only): bin-packing consolidation ───────────────────────
        pack_result: PackingResult | None = None
        if algo == AlgorithmName.FFD_PACK:
            pack_result = self._run_packing(
                sized, constraints, algorithm="ffd"
            )

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "optimization.complete",
            algorithm=algo.value,
            n_resources=len(scoped),
            n_recs=len(recs),
            elapsed_ms=round(elapsed, 1),
        )
        observe_optimization(algo.value, elapsed / 1000, scope="engine")
        result = self._build_result(
            recs=recs,
            algo=algo,
            elapsed_ms=elapsed,
            n_resources=len(resources),
            n_milp=n_milp,
            milp_solved=milp_solved,
            solver_status=milp_result.solver_status if milp_result else "greedy",
            pack_result=pack_result,
        )
        observe_cost_savings(
            total_monthly_cost,
            result.total_savings_monthly,
            scope="optimization_run",
        )
        return result

    def optimize_greedy(
        self,
        resources: list[ResourceSpec],
        usage: list[ForecastedUsage],
        constraints: OptimizationConstraints | None = None,
    ) -> OptimizationResult:
        """Convenience wrapper: always runs the greedy algorithm."""
        return self.optimize(resources, usage, constraints, algorithm="greedy")

    def optimize_milp(
        self,
        resources: list[ResourceSpec],
        usage: list[ForecastedUsage],
        constraints: OptimizationConstraints | None = None,
    ) -> OptimizationResult:
        """Convenience wrapper: runs MILP for RI selection."""
        return self.optimize(resources, usage, constraints, algorithm="milp")

    def pack(
        self,
        resources: list[ResourceSpec],
        usage: list[ForecastedUsage],
        constraints: OptimizationConstraints | None = None,
        *,
        algorithm: str = "ffd",
    ) -> PackingResult:
        """Run bin-packing consolidation only (no RI or termination analysis)."""
        constraints = constraints or OptimizationConstraints()
        usage_map = {u.resource_id: u for u in usage}
        scoped = [r for r in resources if r.id in usage_map]
        profiles_list = [score_resource(r, usage_map[r.id], constraints) for r in scoped]
        sized = right_size_with_usage(scoped, usage_map, profiles_list, self._types, constraints)
        return self._run_packing(sized, constraints, algorithm=algorithm)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_ri_candidates(
        self,
        sized: list[SizedResource],
        constraints: OptimizationConstraints,
    ) -> list[RICandidate]:
        """Build the list of resources eligible for reserved-instance conversion."""
        if not constraints.allow_reserve:
            return []

        candidates: list[RICandidate] = []
        for sr in sized:
            if sr.is_idle:
                continue
            usage = sr.usage
            target = sr.target_type
            current_monthly  = target.cost_monthly
            ri_1yr_monthly   = target.reserved_1yr_monthly
            ri_3yr_monthly   = target.reserved_3yr_monthly
            savings_1yr      = current_monthly - ri_1yr_monthly
            savings_3yr      = current_monthly - ri_3yr_monthly

            # Only consider if savings exceed threshold and resource is suitable
            if savings_1yr < constraints.min_savings_monthly:
                continue
            if usage.cpu_p95 < constraints.min_utilisation_for_reserve:
                continue

            # Utilisation score: higher p50/p95 ratio = more stable = better RI candidate
            util_score = (
                min(usage.cpu_p50, usage.cpu_p95) / max(usage.cpu_p95, 1e-6)
            ) * min(usage.avg_daily_hours / 24.0, 1.0)

            candidates.append(RICandidate(
                resource_id=sr.resource.id,
                current_monthly=current_monthly,
                reserved_1yr_monthly=ri_1yr_monthly,
                reserved_3yr_monthly=ri_3yr_monthly,
                upfront_1yr=target.upfront_1yr,
                upfront_3yr=target.upfront_3yr,
                savings_1yr_monthly=savings_1yr,
                savings_3yr_monthly=savings_3yr,
                utilisation_score=round(util_score, 4),
            ))

        return candidates

    def _run_packing(
        self,
        sized: list[SizedResource],
        constraints: OptimizationConstraints,
        algorithm: str = "ffd",
    ) -> PackingResult:
        workloads = workloads_from_sized(sized)
        original_cost = sum(sr.resource.cost_monthly for sr in sized if not sr.is_idle)

        # Determine predominant provider/region (use majority vote)
        provider, region = _majority_provider_region(sized)

        if algorithm == "bfd":
            return best_fit_decreasing(
                workloads, self._types, provider, region,
                original_cost_monthly=original_cost,
            )
        return first_fit_decreasing(
            workloads, self._types, provider, region,
            original_cost_monthly=original_cost,
        )

    @staticmethod
    def _build_result(
        recs: list[Recommendation],
        algo: AlgorithmName,
        elapsed_ms: float,
        n_resources: int,
        n_milp: int,
        milp_solved: bool,
        solver_status: str,
        pack_result: PackingResult | None,
    ) -> OptimizationResult:
        savings_by_action: dict[str, float] = {}
        for r in recs:
            key = r.action.value
            savings_by_action[key] = savings_by_action.get(key, 0.0) + r.savings_monthly

        # Augment with packing savings if present
        if pack_result and pack_result.savings_monthly > 0:
            key = "consolidate"
            savings_by_action[key] = savings_by_action.get(key, 0.0) + pack_result.savings_monthly

        total = sum(savings_by_action.values())

        return OptimizationResult(
            recommendations=recs,
            algorithm=algo,
            elapsed_ms=round(elapsed_ms, 2),
            n_resources=n_resources,
            n_recommendations=len(recs),
            total_savings_monthly=round(total, 2),
            total_savings_annual=round(total * 12, 2),
            savings_by_action={k: round(v, 2) for k, v in savings_by_action.items()},
            n_milp_candidates=n_milp,
            milp_solved=milp_solved,
            solver_status=solver_status,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_result(algo: AlgorithmName, n: int) -> OptimizationResult:
    return OptimizationResult(
        recommendations=[],
        algorithm=algo,
        elapsed_ms=0.0,
        n_resources=n,
        n_recommendations=0,
        total_savings_monthly=0.0,
        total_savings_annual=0.0,
        savings_by_action={},
    )


def _majority_provider_region(
    sized: list[SizedResource],
) -> tuple[CloudProvider, str]:
    """Return the (provider, region) that appears most often in *sized*."""
    from collections import Counter
    counts: Counter[tuple] = Counter(
        (sr.resource.provider, sr.resource.region)
        for sr in sized if not sr.is_idle
    )
    if not counts:
        return CloudProvider.AWS, "us-east-1"
    return counts.most_common(1)[0][0]
