"""Atlas cost-optimization engine.

Public surface
--------------
::

    from worker.optimization.engine import CostOptimizationEngine
    from worker.optimization.types import (
        OptimizationConstraints,
        OptimizationResult,
        Recommendation,
        RecommendationAction,
    )

    engine = CostOptimizationEngine(instance_types=catalogue)
    result = engine.optimize(
        resources=specs,
        usage=usage_list,
        constraints=OptimizationConstraints(reserved_upfront_budget=100_000),
        algorithm="hybrid",   # "greedy" | "milp" | "hybrid" | "ffd"
    )

    for rec in result.recommendations:
        print(rec.resource_id, rec.action, f"${rec.savings_monthly:,.0f}/mo")

Algorithms
----------
greedy:
    O(n log n).  Greedy right-sizing + greedy RI knapsack.
    Always < 500 ms for 10,000 resources.
    Achieves ≥ 95 % of MILP savings on typical workloads.

milp:
    MILP exact solver (scipy HiGHS) for RI knapsack on ≤ 1,000 candidates;
    greedy fallback for larger inputs.  Right-sizing remains greedy (optimal).
    Typically < 1 s for 10,000 resources.

hybrid:
    Greedy right-sizing + MILP RI selection.  Best practical trade-off.
    Recommended default.

ffd:
    First-Fit Decreasing bin-packing for workload consolidation.
    Use when packing multiple containers/functions onto shared hosts.
    O(n log n), always < 300 ms.

Run the benchmark
-----------------
::

    python -m worker.optimization.benchmark --n 10000
"""

from .engine import CostOptimizationEngine
from .types import AlgorithmName
from .types import CloudProvider
from .types import ForecastedUsage
from .types import InstanceType
from .types import OptimizationConstraints
from .types import OptimizationResult
from .types import Recommendation
from .types import RecommendationAction
from .types import ResourceSpec
from .types import RICandidate
from .types import RiskLevel

__all__ = [
    "CostOptimizationEngine",
    "AlgorithmName",
    "CloudProvider",
    "ForecastedUsage",
    "InstanceType",
    "OptimizationConstraints",
    "OptimizationResult",
    "RICandidate",
    "Recommendation",
    "RecommendationAction",
    "ResourceSpec",
    "RiskLevel",
]
