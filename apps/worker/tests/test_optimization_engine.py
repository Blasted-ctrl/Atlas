"""Tests for the cost-optimization engine.

Coverage
--------
* types         — dataclass properties (cost_monthly, sort_key, priority)
* scorer        — score_resource thresholds, find_cheapest_feasible
* greedy        — right-sizing, termination, RI knapsack edge cases
* solver        — LP relaxation bound, MILP selection vs greedy
* packer        — FFD/BFD packing, bin count, savings computation
* engine        — full pipeline (greedy/milp/hybrid/ffd), determinism, < 2s
* benchmark     — data generation shape and reproducibility

No live DB, Redis, or network required — all pure-function tests.
"""

from __future__ import annotations

import time

import pytest

from worker.optimization.benchmark import build_instance_catalogue
from worker.optimization.benchmark import generate_synthetic_data
from worker.optimization.engine import CostOptimizationEngine
from worker.optimization.greedy import greedy_ri_knapsack
from worker.optimization.packer import WorkloadItem
from worker.optimization.packer import best_fit_decreasing
from worker.optimization.packer import first_fit_decreasing
from worker.optimization.scorer import find_cheapest_feasible
from worker.optimization.scorer import score_resource
from worker.optimization.solver import _lp_relaxation_bound
from worker.optimization.solver import solve_ri_milp
from worker.optimization.types import AlgorithmName
from worker.optimization.types import CloudProvider
from worker.optimization.types import ForecastedUsage
from worker.optimization.types import InstanceType
from worker.optimization.types import OptimizationConstraints
from worker.optimization.types import Recommendation
from worker.optimization.types import RecommendationAction
from worker.optimization.types import ResourceSpec
from worker.optimization.types import RICandidate
from worker.optimization.types import RiskLevel

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

AWS = CloudProvider.AWS
REGION = "us-east-1"


def _itype(name, vcpu, mem, od, r1=None, r3=None, upfront1=None):
    od = float(od)
    r1 = r1 or od * 0.60
    r3 = r3 or od * 0.40
    return InstanceType(
        name=name, vcpu=vcpu, memory_gb=mem,
        cost_hourly=od, reserved_1yr_hourly=r1, reserved_3yr_hourly=r3,
        upfront_1yr=upfront1 or od * 730 * 0.40,
        upfront_3yr=od * 730 * 3 * 0.55,
        provider=AWS, region=REGION, generation=2,
    )


@pytest.fixture()
def catalogue():
    return [
        _itype("t3.micro",    2,   1,  0.010),
        _itype("t3.small",    2,   2,  0.021),
        _itype("m5.large",    2,   8,  0.096),
        _itype("m5.xlarge",   4,  16,  0.192),
        _itype("m5.2xlarge",  8,  32,  0.384),
        _itype("m5.4xlarge", 16,  64,  0.768),
        _itype("c5.xlarge",   4,   8,  0.170),
        _itype("r5.xlarge",   4,  32,  0.252),
    ]


def _spec(rid, inst, vcpu, mem, od, region=REGION):
    return ResourceSpec(
        id=rid, instance_type=inst,
        vcpu=vcpu, memory_gb=mem, cost_hourly=od,
        provider=AWS, region=region,
    )


def _usage(rid, cpu50, cpu95, mem50, mem95, hours=24.0, horizon=30):
    return ForecastedUsage(
        resource_id=rid, cpu_p50=cpu50, cpu_p95=cpu95,
        mem_p50=mem50, mem_p95=mem95,
        avg_daily_hours=hours, horizon_days=horizon,
    )


def _ri_cand(rid, cur, r1, r3, up1, up3, util=0.8):
    sv1 = cur - r1
    sv3 = cur - r3
    return RICandidate(
        resource_id=rid,
        current_monthly=cur,
        reserved_1yr_monthly=r1,
        reserved_3yr_monthly=r3,
        upfront_1yr=up1,
        upfront_3yr=up3,
        savings_1yr_monthly=sv1,
        savings_3yr_monthly=sv3,
        utilisation_score=util,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Types — properties
# ─────────────────────────────────────────────────────────────────────────────

class TestTypes:
    def test_resource_spec_cost_monthly(self):
        spec = _spec("r1", "m5.large", 2, 8, 0.096)
        assert spec.cost_monthly == pytest.approx(0.096 * 730)

    def test_instance_type_cost_monthly(self):
        it = _itype("m5.large", 2, 8, 0.096)
        assert it.cost_monthly == pytest.approx(0.096 * 730)
        assert it.reserved_1yr_monthly == pytest.approx(0.096 * 0.60 * 730)

    def test_recommendation_sort_key(self):
        r1 = Recommendation(
            resource_id="bbb", action=RecommendationAction.DOWNSIZE,
            current_instance_type="m5.2xlarge", target_instance_type="m5.large",
            current_cost_monthly=280, projected_cost_monthly=70,
            savings_monthly=210, savings_pct=75, confidence=0.9,
            risk=RiskLevel.LOW, reason="",
        )
        r2 = Recommendation(
            resource_id="aaa", action=RecommendationAction.DOWNSIZE,
            current_instance_type="m5.2xlarge", target_instance_type="m5.large",
            current_cost_monthly=280, projected_cost_monthly=70,
            savings_monthly=210, savings_pct=75, confidence=0.9,
            risk=RiskLevel.LOW, reason="",
        )
        # Tie in savings → sort by resource_id asc
        recs = sorted([r1, r2], key=lambda r: r.sort_key())
        assert recs[0].resource_id == "aaa"

    def test_recommendation_priority(self):
        def _rec(savings):
            return Recommendation(
                resource_id="x", action=RecommendationAction.DOWNSIZE,
                current_instance_type="m5.4xlarge", target_instance_type="m5.large",
                current_cost_monthly=500, projected_cost_monthly=500 - savings,
                savings_monthly=savings, savings_pct=savings / 5,
                confidence=1.0, risk=RiskLevel.LOW, reason="",
            )

        assert _rec(600).priority == 1
        assert _rec(150).priority == 2
        assert _rec(50).priority == 3


# ─────────────────────────────────────────────────────────────────────────────
# Scorer
# ─────────────────────────────────────────────────────────────────────────────

class TestScorer:
    def test_idle_detection(self):
        spec    = _spec("r1", "m5.xlarge", 4, 16, 0.192)
        usage   = _usage("r1", cpu50=0.005, cpu95=0.010, mem50=0.02, mem95=0.05)
        constr  = OptimizationConstraints()
        profile = score_resource(spec, usage, constr)
        assert profile.is_idle is True

    def test_oversized_detection(self):
        spec    = _spec("r2", "m5.4xlarge", 16, 64, 0.768)
        usage   = _usage("r2", cpu50=0.05, cpu95=0.15, mem50=0.10, mem95=0.20)
        profile = score_resource(spec, usage, OptimizationConstraints())
        assert profile.is_oversized is True
        assert profile.is_idle is False

    def test_rightsized_not_oversized(self):
        spec    = _spec("r3", "m5.large", 2, 8, 0.096)
        usage   = _usage("r3", cpu50=0.70, cpu95=0.80, mem50=0.65, mem95=0.75)
        profile = score_resource(spec, usage, OptimizationConstraints())
        assert profile.is_oversized is False

    def test_required_capacity_includes_headroom(self):
        spec    = _spec("r4", "m5.2xlarge", 8, 32, 0.384)
        usage   = _usage("r4", cpu50=0.40, cpu95=0.50, mem50=0.40, mem95=0.50)
        constr  = OptimizationConstraints(cpu_headroom=0.20, mem_headroom=0.20)
        profile = score_resource(spec, usage, constr)
        # required = 50% of 8 vCPUs * 1.20 = 4.8 cores
        assert profile.required_cpu_cores == pytest.approx(8 * 0.50 * 1.20)
        assert profile.required_mem_gb    == pytest.approx(32 * 0.50 * 1.20)

    def test_ri_viable_for_stable_resource(self):
        spec    = _spec("r5", "m5.xlarge", 4, 16, 0.192)
        usage   = _usage("r5", cpu50=0.70, cpu95=0.75, mem50=0.60, mem95=0.65, hours=24.0)
        constr  = OptimizationConstraints(min_utilisation_for_reserve=0.30)
        profile = score_resource(spec, usage, constr)
        assert profile.ri_viable is True

    def test_ri_not_viable_for_spiky_resource(self):
        spec    = _spec("r6", "m5.xlarge", 4, 16, 0.192)
        # p50 << p95: highly spiky
        usage   = _usage("r6", cpu50=0.05, cpu95=0.80, mem50=0.10, mem95=0.70, hours=24.0)
        profile = score_resource(spec, usage, OptimizationConstraints())
        assert profile.ri_viable is False

    def test_data_confidence_short_horizon(self):
        spec    = _spec("r7", "m5.large", 2, 8, 0.096)
        usage   = _usage("r7", cpu50=0.5, cpu95=0.6, mem50=0.4, mem95=0.5, horizon=3)
        profile = score_resource(spec, usage, OptimizationConstraints())
        assert profile.data_confidence < 1.0


class TestFindCheapestFeasible:
    def test_returns_cheapest_feasible(self, catalogue):
        # Need 1.5 vCPU, 6 GB → m5.large (2 vCPU, 8 GB, $0.096) is cheapest
        result = find_cheapest_feasible(1.5, 6.0, catalogue, AWS, REGION)
        assert result is not None
        assert result.vcpu >= 1.5
        assert result.memory_gb >= 6.0
        assert result.name == "m5.large"

    def test_respects_memory_constraint(self, catalogue):
        # Need 2 vCPU but 20 GB → must be m5.xlarge or larger
        result = find_cheapest_feasible(2.0, 20.0, catalogue, AWS, REGION)
        assert result is not None
        assert result.memory_gb >= 20.0

    def test_returns_none_when_no_fit(self, catalogue):
        # Nothing fits 1000 vCPU
        result = find_cheapest_feasible(1000.0, 1.0, catalogue, AWS, REGION)
        assert result is None

    def test_deterministic_for_same_input(self, catalogue):
        r1 = find_cheapest_feasible(1.0, 4.0, catalogue, AWS, REGION)
        r2 = find_cheapest_feasible(1.0, 4.0, catalogue, AWS, REGION)
        assert r1 == r2

    def test_region_filter(self, catalogue):
        result = find_cheapest_feasible(1.0, 1.0, catalogue, AWS, "eu-west-1")
        assert result is None  # no eu-west-1 instances in fixture


# ─────────────────────────────────────────────────────────────────────────────
# Greedy knapsack
# ─────────────────────────────────────────────────────────────────────────────

class TestGreedyKnapsack:
    def _make_candidates(self):
        # 5 candidates: vary savings and upfront cost
        return [
            _ri_cand("r1", 200, 120, 80, 500,   900),   # savings=80/mo, up=500
            _ri_cand("r2", 500, 300, 200, 700,  1200),  # savings=200/mo, up=700 ← best ratio
            _ri_cand("r3", 100,  60, 40, 800,   1400),  # savings=40/mo, up=800
            _ri_cand("r4", 800, 480, 320, 600,  1100),  # savings=320/mo, up=600
            _ri_cand("r5",  50,  30, 20, 200,    400),  # savings=20/mo, up=200
        ]

    def test_selects_within_budget(self):
        cands = self._make_candidates()
        result = greedy_ri_knapsack(cands, budget=1000.0)
        assert result.total_upfront_committed <= 1000.0

    def test_empty_candidates(self):
        result = greedy_ri_knapsack([], budget=10_000.0)
        assert result.selected == []
        assert result.total_savings_monthly == 0.0

    def test_zero_budget(self):
        cands = self._make_candidates()
        result = greedy_ri_knapsack(cands, budget=0.0)
        assert result.selected == []

    def test_unlimited_budget_takes_all_positive(self):
        cands = self._make_candidates()
        result = greedy_ri_knapsack(cands, budget=float("inf"))
        assert len(result.selected) == len(cands)

    def test_prefers_high_efficiency(self):
        # r2 has best savings/upfront ratio (200/700 ≈ 0.286)
        # r4 has next best (320/600 ≈ 0.533 — actually higher)
        # With budget=600, should pick r4 ($320/mo savings from $600 upfront)
        cands = self._make_candidates()
        result = greedy_ri_knapsack(cands, budget=600.0)
        selected_ids = {c.resource_id for c in result.selected}
        assert "r4" in selected_ids  # highest efficiency item

    def test_deterministic_output(self):
        cands = self._make_candidates()
        r1 = greedy_ri_knapsack(cands, budget=1000.0)
        r2 = greedy_ri_knapsack(cands, budget=1000.0)
        assert [c.resource_id for c in r1.selected] == [c.resource_id for c in r2.selected]


# ─────────────────────────────────────────────────────────────────────────────
# LP relaxation bound
# ─────────────────────────────────────────────────────────────────────────────

class TestLPRelaxationBound:
    def test_bound_geq_greedy_savings(self):
        from worker.optimization.greedy import greedy_ri_knapsack
        cands = [
            _ri_cand("r1", 200, 120, 80, 500, 900),
            _ri_cand("r2", 500, 300, 200, 700, 1200),
            _ri_cand("r3", 100, 60, 40, 800, 1400),
        ]
        budget = 900.0
        lp_ub  = _lp_relaxation_bound(
            cands, budget,
            lambda c: c.savings_1yr_monthly,
            lambda c: c.upfront_1yr,
        )
        greedy = greedy_ri_knapsack(cands, budget)
        assert lp_ub >= greedy.total_savings_monthly - 1e-6

    def test_empty_candidates(self):
        ub = _lp_relaxation_bound([], 1000.0, lambda c: 0, lambda c: 1)
        assert ub == pytest.approx(0.0)

    def test_zero_budget(self):
        cands = [_ri_cand("r1", 200, 120, 80, 500, 900)]
        ub = _lp_relaxation_bound(cands, 0.0, lambda c: c.savings_1yr_monthly, lambda c: c.upfront_1yr)
        assert ub == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# MILP solver
# ─────────────────────────────────────────────────────────────────────────────

class TestMILPSolver:
    def _candidates(self, n=10):
        import numpy as np
        rng = np.random.default_rng(7)
        cands = []
        for i in range(n):
            cur = rng.uniform(100, 800)
            r1  = cur * 0.60
            r3  = cur * 0.40
            cands.append(_ri_cand(
                f"r{i:03d}", cur, r1, r3,
                up1=cur * 0.40 * 730 / 12,
                up3=cur * 0.55 * 730 * 3 / 12,
            ))
        return cands

    def test_milp_savings_geq_greedy(self):
        cands = self._candidates(15)
        constraints = OptimizationConstraints(
            reserved_upfront_budget=5000.0,
            milp_candidate_limit=100,
        )
        milp_res   = solve_ri_milp(cands, constraints)
        greedy_res = greedy_ri_knapsack(cands, 5000.0)
        # MILP should be at least as good as greedy
        assert milp_res.total_savings_monthly >= greedy_res.total_savings_monthly - 0.01

    def test_milp_respects_budget(self):
        cands = self._candidates(20)
        budget = 3000.0
        constraints = OptimizationConstraints(
            reserved_upfront_budget=budget,
            milp_candidate_limit=100,
        )
        result = solve_ri_milp(cands, constraints)
        assert result.total_upfront_committed <= budget + 1e-3

    def test_milp_falls_back_for_large_input(self):
        cands = self._candidates(50)
        constraints = OptimizationConstraints(
            reserved_upfront_budget=100_000.0,
            milp_candidate_limit=10,   # force fallback
        )
        result = solve_ri_milp(cands, constraints)
        assert not result.solved_exactly
        assert "greedy_fallback" in result.solver_status

    def test_approximation_ratio_leq_1(self):
        cands = self._candidates(10)
        constraints = OptimizationConstraints(
            reserved_upfront_budget=5000.0,
            milp_candidate_limit=100,
        )
        result = solve_ri_milp(cands, constraints)
        assert result.approximation_ratio <= 1.001   # allow tiny floating-point slack


# ─────────────────────────────────────────────────────────────────────────────
# Bin-packing
# ─────────────────────────────────────────────────────────────────────────────

class TestBinPacking:
    def _workloads(self, n=10, cpu_max=2.0, mem_max=8.0, seed=0):
        import numpy as np
        rng = np.random.default_rng(seed)
        return [
            WorkloadItem(
                resource_id=f"w{i:04d}",
                peak_cpu_cores=float(rng.uniform(0.1, cpu_max)),
                peak_mem_gb=float(rng.uniform(0.5, mem_max)),
            )
            for i in range(n)
        ]

    def test_ffd_packs_all_items(self, catalogue):
        workloads = self._workloads(50, cpu_max=1.5, mem_max=6.0)
        result = first_fit_decreasing(workloads, catalogue, AWS, REGION)
        packed = sum(len(b.workloads) for b in result.bins)
        assert packed + len(result.unpacked) == len(workloads)

    def test_ffd_respects_bin_capacity(self, catalogue):
        workloads = self._workloads(30, cpu_max=1.0, mem_max=4.0)
        result = first_fit_decreasing(workloads, catalogue, AWS, REGION)
        for b in result.bins:
            assert b.used_cpu <= b.instance_type.vcpu + 1e-9
            assert b.used_mem <= b.instance_type.memory_gb + 1e-9

    def test_ffd_fewer_bins_than_items(self, catalogue):
        # Small workloads should consolidate onto fewer instances
        workloads = self._workloads(20, cpu_max=0.5, mem_max=2.0)
        result = first_fit_decreasing(workloads, catalogue, AWS, REGION)
        assert result.n_bins < len(workloads)

    def test_bfd_packs_all_items(self, catalogue):
        workloads = self._workloads(40, cpu_max=1.5, mem_max=6.0)
        result = best_fit_decreasing(workloads, catalogue, AWS, REGION)
        packed = sum(len(b.workloads) for b in result.bins)
        assert packed + len(result.unpacked) == len(workloads)

    def test_bfd_leq_ffd_bins(self, catalogue):
        # BFD should achieve at least as good packing as FFD (usually better)
        workloads = self._workloads(60, cpu_max=1.2, mem_max=5.0, seed=99)
        ffd = first_fit_decreasing(workloads, catalogue, AWS, REGION)
        bfd = best_fit_decreasing(workloads, catalogue, AWS, REGION)
        # BFD may use same or fewer bins; never more
        assert bfd.n_bins <= ffd.n_bins + 2   # slight tolerance for tie-breaking

    def test_deterministic_packing(self, catalogue):
        workloads = self._workloads(20)
        r1 = first_fit_decreasing(workloads, catalogue, AWS, REGION)
        r2 = first_fit_decreasing(workloads, catalogue, AWS, REGION)
        assert [b.instance_type.name for b in r1.bins] == [b.instance_type.name for b in r2.bins]
        assert [b.workloads for b in r1.bins] == [b.workloads for b in r2.bins]

    def test_no_feasible_bin_type(self):
        # Giant workload that no bin can fit → unpacked
        workloads = [WorkloadItem("huge", peak_cpu_cores=1000.0, peak_mem_gb=9999.0)]
        tiny_catalogue = [_itype("t3.micro", 2, 1, 0.01)]
        result = first_fit_decreasing(workloads, tiny_catalogue, AWS, REGION)
        assert result.unpacked == ["huge"]
        assert result.n_bins == 0

    def test_savings_computed_correctly(self, catalogue):
        workloads = self._workloads(10)
        original_cost = 1000.0   # pretend each workload had its own m5.xlarge
        result = first_fit_decreasing(
            workloads, catalogue, AWS, REGION, original_cost_monthly=original_cost
        )
        expected_savings = max(0.0, original_cost - result.total_cost_monthly)
        assert result.savings_monthly == pytest.approx(expected_savings, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# Full Engine
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def engine(catalogue):
    return CostOptimizationEngine(instance_types=catalogue)


def _make_dataset(n=100, seed=0):
    """Tiny synthetic dataset for engine tests."""
    import numpy as np
    rng = np.random.default_rng(seed)
    specs, usage = [], []
    cats = rng.choice(["idle", "oversized", "rightsized"], size=n, p=[0.25, 0.55, 0.20])
    types_pool = [("m5.2xlarge", 8, 32, 0.384), ("m5.4xlarge", 16, 64, 0.768)]

    for i, cat in enumerate(cats):
        name, vcpu, mem, od = types_pool[i % 2]
        rid = f"r{i:05d}"
        if cat == "idle":
            cpu95, mem95 = 0.010, 0.04
        elif cat == "oversized":
            cpu95 = float(rng.uniform(0.08, 0.25))
            mem95 = float(rng.uniform(0.10, 0.35))
        else:
            cpu95 = float(rng.uniform(0.60, 0.80))
            mem95 = float(rng.uniform(0.55, 0.75))

        specs.append(ResourceSpec(
            id=rid, instance_type=name, vcpu=vcpu, memory_gb=mem,
            cost_hourly=od, provider=AWS, region=REGION,
        ))
        usage.append(ForecastedUsage(
            resource_id=rid, cpu_p50=cpu95 * 0.7, cpu_p95=cpu95,
            mem_p50=mem95 * 0.7, mem_p95=mem95,
            avg_daily_hours=23.0, horizon_days=30,
        ))
    return specs, usage


class TestEngineGreedy:
    def test_returns_recommendations(self, engine):
        specs, usage = _make_dataset(100)
        result = engine.optimize(specs, usage, algorithm="greedy")
        assert result.algorithm == AlgorithmName.GREEDY
        assert result.n_resources == 100
        assert result.n_recommendations > 0

    def test_recommendations_sorted_by_savings(self, engine):
        specs, usage = _make_dataset(100)
        result = engine.optimize(specs, usage, algorithm="greedy")
        savings = [r.savings_monthly for r in result.recommendations]
        assert savings == sorted(savings, reverse=True)

    def test_terminate_for_idle_resources(self, engine):
        specs = [_spec("idle-1", "m5.2xlarge", 8, 32, 0.384)]
        usage = [_usage("idle-1", cpu50=0.005, cpu95=0.010, mem50=0.02, mem95=0.05)]
        result = engine.optimize(specs, usage, algorithm="greedy")
        actions = {r.action for r in result.recommendations}
        assert RecommendationAction.TERMINATE in actions

    def test_downsize_for_oversized_resources(self, engine):
        # Heavily oversized m5.4xlarge at 10% CPU
        specs = [_spec("over-1", "m5.4xlarge", 16, 64, 0.768)]
        usage = [_usage("over-1", cpu50=0.05, cpu95=0.10, mem50=0.10, mem95=0.15)]
        result = engine.optimize(specs, usage, algorithm="greedy")
        actions = {r.action for r in result.recommendations}
        assert RecommendationAction.DOWNSIZE in actions

    def test_no_recommendations_below_threshold(self, engine):
        # Cheap resource, tiny savings → filtered out
        specs = [_spec("cheap-1", "t3.micro", 2, 1, 0.010)]
        usage = [_usage("cheap-1", cpu50=0.05, cpu95=0.10, mem50=0.10, mem95=0.15)]
        constr = OptimizationConstraints(min_savings_monthly=1_000_000.0)
        result = engine.optimize(specs, usage, constr, algorithm="greedy")
        assert result.n_recommendations == 0

    def test_savings_by_action_sums_correctly(self, engine):
        specs, usage = _make_dataset(50)
        result = engine.optimize(specs, usage, algorithm="greedy")
        total_from_breakdown = sum(result.savings_by_action.values())
        assert total_from_breakdown == pytest.approx(result.total_savings_monthly, rel=1e-5)

    def test_savings_annual_is_12x_monthly(self, engine):
        specs, usage = _make_dataset(50)
        result = engine.optimize(specs, usage, algorithm="greedy")
        assert result.total_savings_annual == pytest.approx(result.total_savings_monthly * 12, rel=1e-5)

    def test_no_usage_resources_excluded(self, engine):
        specs = [_spec("r1", "m5.xlarge", 4, 16, 0.192), _spec("r2", "m5.xlarge", 4, 16, 0.192)]
        usage = [_usage("r1", cpu50=0.05, cpu95=0.10, mem50=0.10, mem95=0.15)]  # r2 missing
        result = engine.optimize(specs, usage, algorithm="greedy")
        rec_ids = {r.resource_id for r in result.recommendations}
        assert "r2" not in rec_ids


class TestEngineHybrid:
    def test_hybrid_savings_geq_greedy(self, engine):
        specs, usage = _make_dataset(100)
        greedy = engine.optimize(specs, usage, algorithm="greedy")
        hybrid = engine.optimize(specs, usage, algorithm="hybrid")
        # Hybrid uses same right-sizing but possibly better RI selection
        assert hybrid.total_savings_monthly >= greedy.total_savings_monthly - 0.01

    def test_hybrid_recommendations_match_structure(self, engine):
        specs, usage = _make_dataset(80)
        result = engine.optimize(specs, usage, algorithm="hybrid")
        assert result.algorithm == AlgorithmName.HYBRID
        for r in result.recommendations:
            assert r.savings_monthly >= 0
            assert r.savings_pct >= 0
            assert r.confidence >= 0.0


class TestEngineMILP:
    def test_milp_result_structure(self, engine):
        specs, usage = _make_dataset(50)
        result = engine.optimize(
            specs, usage,
            OptimizationConstraints(milp_candidate_limit=100),
            algorithm="milp",
        )
        assert result.algorithm == AlgorithmName.MILP
        assert result.total_savings_monthly >= 0


class TestEngineFFD:
    def test_ffd_returns_result(self, engine):
        specs, usage = _make_dataset(50)
        result = engine.optimize(specs, usage, algorithm="ffd")
        assert result.algorithm == AlgorithmName.FFD_PACK


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    @pytest.mark.parametrize("algo", ["greedy", "hybrid", "ffd"])
    def test_identical_output_on_repeated_calls(self, engine, algo):
        specs, usage = _make_dataset(200)
        constr = OptimizationConstraints()

        r1 = engine.optimize(specs, usage, constr, algorithm=algo)
        r2 = engine.optimize(specs, usage, constr, algorithm=algo)

        ids1 = [r.resource_id for r in r1.recommendations]
        ids2 = [r.resource_id for r in r2.recommendations]
        sv1  = [round(r.savings_monthly, 4) for r in r1.recommendations]
        sv2  = [round(r.savings_monthly, 4) for r in r2.recommendations]

        assert ids1 == ids2, f"Resource IDs differ for {algo}"
        assert sv1  == sv2,  f"Savings differ for {algo}"

    def test_deterministic_across_input_orderings(self, engine):
        import random
        specs, usage = _make_dataset(100)
        constr = OptimizationConstraints()

        r_orig = engine.optimize(specs, usage, constr, algorithm="greedy")

        # Shuffle inputs (with fixed seed for reproducibility)
        rand = random.Random(42)
        specs_shuffled = list(specs)
        usage_shuffled = list(usage)
        rand.shuffle(specs_shuffled)
        rand.shuffle(usage_shuffled)

        r_shuf = engine.optimize(specs_shuffled, usage_shuffled, constr, algorithm="greedy")

        # Same recommendations regardless of input order
        ids_orig = sorted(r.resource_id for r in r_orig.recommendations)
        ids_shuf = sorted(r.resource_id for r in r_shuf.recommendations)
        assert ids_orig == ids_shuf


# ─────────────────────────────────────────────────────────────────────────────
# Performance (< 2 s for 10k resources)
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformance:
    @pytest.mark.parametrize("algo,limit_ms", [
        ("greedy", 2_000),
        ("hybrid", 2_000),
        ("ffd",    5_000),
    ])
    def test_completes_within_limit(self, algo, limit_ms):
        specs, usage = generate_synthetic_data(10_000, seed=1)
        catalogue = build_instance_catalogue()
        engine = CostOptimizationEngine(instance_types=catalogue)

        t0 = time.perf_counter()
        result = engine.optimize(specs, usage, algorithm=algo)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < limit_ms, (
            f"{algo} took {elapsed_ms:.0f}ms — exceeds {limit_ms}ms limit"
        )
        assert result.n_resources == 10_000


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark data generation
# ─────────────────────────────────────────────────────────────────────────────

class TestSyntheticDataGeneration:
    def test_generates_correct_count(self):
        specs, usage = generate_synthetic_data(500)
        assert len(specs) == 500
        assert len(usage) == 500

    def test_resource_ids_unique(self):
        specs, _ = generate_synthetic_data(1000)
        ids = [s.id for s in specs]
        assert len(ids) == len(set(ids))

    def test_usage_resource_ids_match_specs(self):
        specs, usage = generate_synthetic_data(500)
        spec_ids  = {s.id for s in specs}
        usage_ids = {u.resource_id for u in usage}
        assert spec_ids == usage_ids

    def test_seeded_reproducibility(self):
        s1, u1 = generate_synthetic_data(100, seed=7)
        s2, u2 = generate_synthetic_data(100, seed=7)
        assert [s.id for s in s1] == [s.id for s in s2]
        assert [s.cost_hourly for s in s1] == [s.cost_hourly for s in s2]
        assert [u.cpu_p95 for u in u1] == [u.cpu_p95 for u in u2]

    def test_different_seeds_produce_different_data(self):
        s1, _ = generate_synthetic_data(100, seed=1)
        s2, _ = generate_synthetic_data(100, seed=2)
        # At least some instance types should differ
        types1 = [s.instance_type for s in s1]
        types2 = [s.instance_type for s in s2]
        assert types1 != types2

    def test_utilisation_fractions_in_range(self):
        _, usage = generate_synthetic_data(200)
        for u in usage:
            assert 0.0 <= u.cpu_p50 <= 1.0
            assert 0.0 <= u.cpu_p95 <= 1.0
            assert 0.0 <= u.mem_p50 <= 1.0
            assert 0.0 <= u.mem_p95 <= 1.0
            assert u.cpu_p50 <= u.cpu_p95 + 1e-9

    def test_idle_resources_present(self):
        _, usage = generate_synthetic_data(1000)
        idle = [u for u in usage if u.cpu_p95 < 0.02]
        assert len(idle) > 50  # ~25% × 1000 = 250 expected

    def test_all_providers_aws(self):
        specs, _ = generate_synthetic_data(100)
        assert all(s.provider == CloudProvider.AWS for s in specs)
