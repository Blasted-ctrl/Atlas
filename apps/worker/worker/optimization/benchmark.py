"""Benchmark harness for the cost-optimization engine.

Generates synthetic 10,000-resource datasets and times each algorithm.
Prints a formatted comparison table and approximation-ratio analysis.

Usage
-----
    python -m worker.optimization.benchmark
    python -m worker.optimization.benchmark --n 10000 --seed 42
    python -m worker.optimization.benchmark --n 1000 --quick
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import numpy as np

from .engine import CostOptimizationEngine
from .types import CloudProvider
from .types import ForecastedUsage
from .types import InstanceType
from .types import OptimizationConstraints
from .types import OptimizationResult
from .types import ResourceSpec

# ── Synthetic instance-type catalogue (AWS us-east-1 approximate pricing) ─────

def build_instance_catalogue() -> list[InstanceType]:
    """Return a realistic multi-family instance catalogue."""

    def _make(name, vcpu, mem, od, r1, r3, up1_frac=0.40, gen=2, **kw):
        return InstanceType(
            name=name, vcpu=vcpu, memory_gb=mem,
            cost_hourly=od,
            reserved_1yr_hourly=r1,
            reserved_3yr_hourly=r3,
            upfront_1yr=od * 730 * up1_frac,
            upfront_3yr=od * 730 * 3 * 0.55,
            provider=CloudProvider.AWS,
            region="us-east-1",
            generation=gen,
        )

    return [
        # t3 (burstable general purpose)
        _make("t3.micro",    2,   1,   0.0104,  0.0063,  0.0042, gen=3),
        _make("t3.small",    2,   2,   0.0208,  0.0126,  0.0084, gen=3),
        _make("t3.medium",   2,   4,   0.0416,  0.0252,  0.0168, gen=3),
        _make("t3.large",    2,   8,   0.0832,  0.0504,  0.0336, gen=3),
        _make("t3.xlarge",   4,  16,   0.1664,  0.1008,  0.0672, gen=3),
        # m5 (general purpose)
        _make("m5.large",    2,   8,   0.096,   0.058,   0.038),
        _make("m5.xlarge",   4,  16,   0.192,   0.116,   0.077),
        _make("m5.2xlarge",  8,  32,   0.384,   0.232,   0.154),
        _make("m5.4xlarge", 16,  64,   0.768,   0.464,   0.308),
        _make("m5.8xlarge", 32, 128,   1.536,   0.928,   0.616),
        # c5 (compute optimised)
        _make("c5.large",    2,   4,   0.085,   0.051,   0.034),
        _make("c5.xlarge",   4,   8,   0.170,   0.102,   0.068),
        _make("c5.2xlarge",  8,  16,   0.340,   0.204,   0.136),
        _make("c5.4xlarge", 16,  32,   0.680,   0.408,   0.272),
        # r5 (memory optimised)
        _make("r5.large",    2,  16,   0.126,   0.076,   0.050),
        _make("r5.xlarge",   4,  32,   0.252,   0.152,   0.100),
        _make("r5.2xlarge",  8,  64,   0.504,   0.304,   0.200),
        _make("r5.4xlarge", 16, 128,   1.008,   0.608,   0.400),
    ]


# ── Synthetic data generation ─────────────────────────────────────────────────

def generate_synthetic_data(
    n_resources: int = 10_000,
    seed: int = 42,
) -> tuple[list[ResourceSpec], list[ForecastedUsage]]:
    """Generate a realistic synthetic dataset.

    Population mix (approximates real-world cloud estates):
    - 25 % idle          (cpu_p95 < 2 %)
    - 45 % oversized     (cpu_p95 5–30 %, huge waste)
    - 20 % moderate      (cpu_p95 30–60 %)
    -  5 % rightsized    (cpu_p95 60–85 %)
    -  5 % heavy         (cpu_p95 85–98 %)
    """
    rng = np.random.default_rng(seed)
    catalogue = build_instance_catalogue()

    # Large instances that might be oversized (skip tiny ones for interesting data)
    large_types = [t for t in catalogue if t.vcpu >= 4]

    categories = rng.choice(
        ["idle", "oversized", "moderate", "rightsized", "heavy"],
        size=n_resources,
        p=[0.25, 0.45, 0.20, 0.05, 0.05],
    )

    specs: list[ResourceSpec] = []
    usage: list[ForecastedUsage] = []

    for i in range(n_resources):
        cat = categories[i]
        inst = large_types[int(rng.integers(0, len(large_types)))]
        rid = f"res-{i:06d}"

        if cat == "idle":
            cpu_p50, cpu_p95 = rng.uniform(0.002, 0.010), rng.uniform(0.005, 0.019)
            mem_p50, mem_p95 = rng.uniform(0.010, 0.050), rng.uniform(0.020, 0.090)
            hours = rng.uniform(1, 8)     # sporadic
        elif cat == "oversized":
            cpu_p95 = rng.uniform(0.05, 0.30)
            cpu_p50 = cpu_p95 * rng.uniform(0.4, 0.8)
            mem_p95 = rng.uniform(0.10, 0.40)
            mem_p50 = mem_p95 * rng.uniform(0.4, 0.8)
            hours = rng.uniform(20, 24)
        elif cat == "moderate":
            cpu_p95 = rng.uniform(0.30, 0.60)
            cpu_p50 = cpu_p95 * rng.uniform(0.6, 0.9)
            mem_p95 = rng.uniform(0.30, 0.60)
            mem_p50 = mem_p95 * rng.uniform(0.6, 0.9)
            hours = rng.uniform(20, 24)
        elif cat == "rightsized":
            cpu_p95 = rng.uniform(0.60, 0.85)
            cpu_p50 = cpu_p95 * rng.uniform(0.7, 0.95)
            mem_p95 = rng.uniform(0.55, 0.80)
            mem_p50 = mem_p95 * rng.uniform(0.7, 0.95)
            hours = rng.uniform(22, 24)
        else:  # heavy
            cpu_p95 = rng.uniform(0.85, 0.98)
            cpu_p50 = cpu_p95 * rng.uniform(0.85, 0.98)
            mem_p95 = rng.uniform(0.75, 0.95)
            mem_p50 = mem_p95 * rng.uniform(0.80, 0.98)
            hours = 24.0

        specs.append(ResourceSpec(
            id=rid,
            instance_type=inst.name,
            vcpu=inst.vcpu,
            memory_gb=inst.memory_gb,
            cost_hourly=inst.cost_hourly,
            provider=CloudProvider.AWS,
            region="us-east-1",
            account_id=f"acct-{i % 50:04d}",
        ))

        usage.append(ForecastedUsage(
            resource_id=rid,
            cpu_p50=round(float(min(cpu_p50, cpu_p95)), 4),
            cpu_p95=round(float(cpu_p95), 4),
            mem_p50=round(float(min(mem_p50, mem_p95)), 4),
            mem_p95=round(float(mem_p95), 4),
            avg_daily_hours=round(float(hours), 1),
            horizon_days=30,
        ))

    return specs, usage


# ── Benchmark result type ─────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    algorithm: str
    elapsed_ms: float
    n_resources: int
    n_recommendations: int
    savings_monthly: float
    savings_annual: float
    savings_by_action: dict[str, float]
    lp_upper_bound: float = 0.0      # greedy savings / LP bound = approx ratio
    approximation_ratio: float = 1.0
    milp_solved: bool = False
    n_milp_candidates: int = 0


# ── Run benchmarks ────────────────────────────────────────────────────────────

def run_benchmark(
    n_resources: int = 10_000,
    seed: int = 42,
    *,
    include_ffd: bool = True,
    budget_usd: float = 200_000.0,
) -> dict[str, BenchmarkResult]:
    """Run all algorithms against synthetic data and return results.

    Parameters
    ----------
    n_resources:
        Size of the synthetic dataset.
    seed:
        RNG seed for reproducible data generation.
    include_ffd:
        Whether to include the FFD bin-packing algorithm.
    budget_usd:
        Reserved-instance upfront budget for the knapsack.
    """
    print(f"\nGenerating {n_resources:,} synthetic resources (seed={seed})…", flush=True)
    t_gen = time.perf_counter()
    specs, usage = generate_synthetic_data(n_resources, seed)
    catalogue = build_instance_catalogue()
    t_gen_ms = (time.perf_counter() - t_gen) * 1000
    print(f"  Data generation: {t_gen_ms:.0f} ms\n", flush=True)

    constraints = OptimizationConstraints(
        reserved_upfront_budget=budget_usd,
        milp_candidate_limit=1_000,
    )
    engine = CostOptimizationEngine(instance_types=catalogue)

    results: dict[str, BenchmarkResult] = {}
    algorithms = ["greedy", "milp", "hybrid"]
    if include_ffd:
        algorithms.append("ffd")

    for algo_name in algorithms:
        print(f"  Running {algo_name}…", end=" ", flush=True)
        result: OptimizationResult = engine.optimize(
            specs, usage, constraints, algorithm=algo_name
        )
        ri_savings = result.savings_by_action.get("reserve_1yr", 0.0)
        print(f"{result.elapsed_ms:.0f} ms", flush=True)

        results[algo_name] = BenchmarkResult(
            algorithm=algo_name,
            elapsed_ms=result.elapsed_ms,
            n_resources=result.n_resources,
            n_recommendations=result.n_recommendations,
            savings_monthly=result.total_savings_monthly,
            savings_annual=result.total_savings_annual,
            savings_by_action=result.savings_by_action,
            milp_solved=result.milp_solved,
            n_milp_candidates=result.n_milp_candidates,
            approximation_ratio=1.0,
        )

    # Compute approximation ratios relative to best-savings algorithm
    best_savings = max(r.savings_monthly for r in results.values()) or 1.0
    for r in results.values():
        r.approximation_ratio = round(r.savings_monthly / best_savings, 4)

    return results


# ── Formatted output ──────────────────────────────────────────────────────────

def print_report(results: dict[str, BenchmarkResult]) -> None:
    W = 82
    div  = "═" * W
    thin = "─" * W

    print(f"\n╔{div}╗")
    print(f"║{'Atlas Cost Optimization Engine — Algorithm Comparison':^{W}}║")
    print(f"╠{div}╣")
    header = f"{'Algorithm':<20} {'Time':>8}   {'Savings/mo':>12}   {'Recs':>6}   {'vs. Best':>10}   {'MILP?':>6}"
    print(f"║  {header}  ║")
    print(f"╠{div}╣")

    sorted_results = sorted(results.values(), key=lambda r: -r.savings_monthly)
    for r in sorted_results:
        milp_flag = "✓" if r.milp_solved else "-"
        line = (
            f"{r.algorithm:<20} "
            f"{r.elapsed_ms:>7.0f}ms   "
            f"${r.savings_monthly:>10,.0f}   "
            f"{r.n_recommendations:>6,}   "
            f"{r.approximation_ratio:>9.1%}   "
            f"{milp_flag:>6}"
        )
        print(f"║  {line}  ║")

    print(f"╚{div}╝")

    # Savings breakdown for best algorithm
    best = sorted_results[0]
    print(f"\nSavings breakdown — {best.algorithm}")
    print(thin)
    action_labels = {
        "terminate":   "Terminate (idle)",
        "downsize":    "Downsize (right-size)",
        "reserve_1yr": "Reserve 1-yr",
        "reserve_3yr": "Reserve 3-yr",
        "consolidate": "Consolidate (packing)",
    }
    for action, monthly in sorted(best.savings_by_action.items(), key=lambda x: -x[1]):
        label = action_labels.get(action, action)
        annual = monthly * 12
        print(f"  {label:<28}  ${monthly:>9,.0f}/mo   (${annual:>10,.0f}/yr)")

    print(thin)
    total_monthly = best.savings_monthly
    total_annual  = best.savings_annual
    print(f"  {'TOTAL':<28}  ${total_monthly:>9,.0f}/mo   (${total_annual:>10,.0f}/yr)")

    # Performance guarantees
    print("\nPerformance constraints")
    print(thin)
    n = best.n_resources
    for r in sorted_results:
        status = "✓ PASS" if r.elapsed_ms < 2_000 else "✗ FAIL"
        print(f"  {r.algorithm:<20}  {r.elapsed_ms:>7.0f} ms  ({n:,} resources)  [{status}]")

    # Determinism verification
    print("\nDeterminism check", flush=True)
    print(thin)
    _verify_determinism(best.algorithm)


def _verify_determinism(algorithm: str, n: int = 1_000, seed: int = 99) -> None:
    catalogue = build_instance_catalogue()
    engine = CostOptimizationEngine(instance_types=catalogue)
    specs, usage = generate_synthetic_data(n, seed)
    constraints = OptimizationConstraints()

    r1 = engine.optimize(specs, usage, constraints, algorithm=algorithm)
    r2 = engine.optimize(specs, usage, constraints, algorithm=algorithm)

    ids1 = [r.resource_id for r in r1.recommendations]
    ids2 = [r.resource_id for r in r2.recommendations]
    sv1  = [round(r.savings_monthly, 4) for r in r1.recommendations]
    sv2  = [round(r.savings_monthly, 4) for r in r2.recommendations]

    if ids1 == ids2 and sv1 == sv2:
        print(f"  {algorithm:<20}  ✓ Identical output on 2 independent runs ({n:,} resources)")
    else:
        diff = sum(a != b for a, b in zip(ids1, ids2))
        print(f"  {algorithm:<20}  ✗ Non-deterministic! {diff} differences in {n:,} resources")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Atlas optimization engine benchmark")
    parser.add_argument("--n", type=int, default=10_000, help="Number of resources")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--budget", type=float, default=200_000, help="RI upfront budget (USD)")
    parser.add_argument("--quick", action="store_true", help="Skip FFD packing")
    args = parser.parse_args(argv)

    results = run_benchmark(
        n_resources=args.n,
        seed=args.seed,
        include_ffd=not args.quick,
        budget_usd=args.budget,
    )
    print_report(results)


if __name__ == "__main__":
    main()
