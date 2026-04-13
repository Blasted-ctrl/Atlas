"""Optimised solvers: MILP knapsack and LP-relaxation fallback.

Reserved-instance selection as a 0/1 knapsack
----------------------------------------------
Decision variables:  x_i ∈ {0, 1}  (1 = commit resource i to reserved plan)
Objective:           maximise  Σ_i  savings_i · x_i
Constraint:          Σ_i  upfront_i · x_i  ≤  budget

This is solved exactly using :func:`scipy.optimize.milp` (HiGHS solver, LP
branch-and-bound).  For n ≤ 1,000 candidates the solve typically takes
< 500 ms; above that the engine falls back to the greedy knapsack.

LP-relaxation bound
-------------------
The LP relaxation (x_i ∈ [0, 1]) gives an upper bound on achievable savings.
We report it in the benchmark for approximation-ratio comparison:

    approximation_ratio = greedy_savings / lp_bound

Right-sizing note
-----------------
Per-resource instance selection is provably optimal via greedy (argmin over
feasible types) — no MILP is needed there.  This module focuses entirely on
the global portfolio problem (RI selection) where coupling across resources
(shared budget) makes the exact solver valuable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .greedy import greedy_ri_knapsack
from .types import OptimizationConstraints
from .types import RICandidate

logger = logging.getLogger(__name__)


# ── Public result type ────────────────────────────────────────────────────────

@dataclass(slots=True)
class MILPResult:
    selected: list[RICandidate]
    total_savings_monthly: float
    total_upfront_committed: float
    lp_upper_bound_monthly: float   # LP relaxation value (optimal upper bound)
    approximation_ratio: float      # this_solution / lp_upper_bound
    elapsed_ms: float
    solved_exactly: bool            # False when fell back to greedy
    solver_status: str


# ── Main entry point ──────────────────────────────────────────────────────────

def solve_ri_milp(
    candidates: list[RICandidate],
    constraints: OptimizationConstraints,
    *,
    prefer_3yr: bool = False,
) -> MILPResult:
    """Solve the RI-selection knapsack exactly via MILP.

    Falls back to greedy when:
    - No candidates or zero budget.
    - scipy.optimize.milp is unavailable.
    - n_candidates > constraints.milp_candidate_limit.
    - MILP solver does not converge within the time limit.

    Always returns a valid :class:`MILPResult`.
    """
    t0 = time.perf_counter()

    if not candidates or constraints.reserved_upfront_budget <= 0:
        return MILPResult(
            selected=[], total_savings_monthly=0.0,
            total_upfront_committed=0.0, lp_upper_bound_monthly=0.0,
            approximation_ratio=1.0, elapsed_ms=0.0,
            solved_exactly=True, solver_status="empty",
        )

    # Filter to candidates with positive savings (remove dominated options)
    def _savings(c: RICandidate) -> float:
        return c.savings_3yr_monthly if prefer_3yr else c.savings_1yr_monthly

    def _upfront(c: RICandidate) -> float:
        return c.upfront_3yr if prefer_3yr else c.upfront_1yr

    viable = [c for c in candidates if _savings(c) > 0 and _upfront(c) > 0]
    viable.sort(key=lambda c: (c.resource_id,))   # deterministic input ordering

    budget = constraints.reserved_upfront_budget

    # ── LP upper bound (always computed — fast) ───────────────────────────────
    lp_ub = _lp_relaxation_bound(viable, budget, _savings, _upfront)

    # ── Decide: MILP or greedy fallback ───────────────────────────────────────
    if len(viable) > constraints.milp_candidate_limit:
        logger.info(
            "optimization.ri.milp_too_large",
            n_candidates=len(viable),
            limit=constraints.milp_candidate_limit,
        )
        greedy = greedy_ri_knapsack(viable, budget, prefer_3yr=prefer_3yr)
        sv = greedy.total_savings_monthly
        return MILPResult(
            selected=greedy.selected,
            total_savings_monthly=sv,
            total_upfront_committed=greedy.total_upfront_committed,
            lp_upper_bound_monthly=lp_ub,
            approximation_ratio=sv / lp_ub if lp_ub > 0 else 1.0,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
            solved_exactly=False,
            solver_status="greedy_fallback_size",
        )

    # ── Attempt MILP ──────────────────────────────────────────────────────────
    try:
        selected, status = _run_milp(viable, budget, _savings, _upfront)
        sv = sum(_savings(c) for c in selected)
        up = sum(_upfront(c) for c in selected)
        return MILPResult(
            selected=selected,
            total_savings_monthly=sv,
            total_upfront_committed=up,
            lp_upper_bound_monthly=lp_ub,
            approximation_ratio=sv / lp_ub if lp_ub > 0 else 1.0,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
            solved_exactly=True,
            solver_status=status,
        )
    except Exception as exc:
        logger.warning("optimization.ri.milp_failed", error=str(exc))
        greedy = greedy_ri_knapsack(viable, budget, prefer_3yr=prefer_3yr)
        sv = greedy.total_savings_monthly
        return MILPResult(
            selected=greedy.selected,
            total_savings_monthly=sv,
            total_upfront_committed=greedy.total_upfront_committed,
            lp_upper_bound_monthly=lp_ub,
            approximation_ratio=sv / lp_ub if lp_ub > 0 else 1.0,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
            solved_exactly=False,
            solver_status=f"milp_error:{exc!r}",
        )


# ── MILP implementation ───────────────────────────────────────────────────────

def _run_milp(
    candidates: list[RICandidate],
    budget: float,
    savings_fn,
    upfront_fn,
) -> tuple[list[RICandidate], str]:
    """Run scipy.optimize.milp.  Raises on failure."""
    from scipy.optimize import Bounds
    from scipy.optimize import LinearConstraint
    from scipy.optimize import milp

    n = len(candidates)
    savings_arr = np.array([savings_fn(c) for c in candidates], dtype=float)
    upfront_arr = np.array([upfront_fn(c) for c in candidates], dtype=float)

    # Objective: minimise -savings (= maximise savings)
    c_obj = -savings_arr

    # Budget constraint: upfront @ x ≤ budget
    A = upfront_arr.reshape(1, n)
    constraint = LinearConstraint(A, lb=-np.inf, ub=budget)

    # x_i ∈ {0, 1}
    integrality = np.ones(n, dtype=int)
    bounds = Bounds(lb=0.0, ub=1.0)

    res = milp(
        c=c_obj,
        constraints=constraint,
        integrality=integrality,
        bounds=bounds,
        options={"time_limit": 10.0, "disp": False},
    )

    if not res.success and res.status not in (0, 2):  # 0=optimal, 2=feasible
        raise RuntimeError(f"MILP solver: {res.message}")

    selected = [candidates[i] for i in range(n) if res.x[i] > 0.5]
    return selected, f"milp_status_{res.status}"


# ── LP relaxation bound ───────────────────────────────────────────────────────

def _lp_relaxation_bound(
    candidates: list[RICandidate],
    budget: float,
    savings_fn,
    upfront_fn,
) -> float:
    """Compute the LP relaxation optimum (fractional knapsack = upper bound).

    Greedy fractional solution: sort by savings/upfront, take fully while
    budget allows, then take fraction of the next item.

    This is O(n log n) and provably equals the LP optimal for a single-constraint
    knapsack.
    """
    if not candidates or budget <= 0:
        return 0.0

    items = sorted(
        [(savings_fn(c), upfront_fn(c), c.resource_id) for c in candidates],
        key=lambda t: (-(t[0] / max(t[1], 1e-9)), t[2]),  # ratio desc, id asc
    )

    remaining = budget
    total = 0.0
    for sv, up, _ in items:
        if up <= 0:
            continue
        if up <= remaining:
            total += sv
            remaining -= up
        else:
            # Take the fractional part
            total += sv * (remaining / up)
            break

    return total
