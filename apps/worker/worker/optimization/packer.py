"""Multi-dimensional bin-packing for workload consolidation.

Use case
--------
When multiple small cloud resources (containers, functions, microVMs) need to
be consolidated onto fewer, larger host instances to reduce per-resource
overhead cost.

Algorithms
----------
* **First-Fit Decreasing (FFD)**: Sort items by descending size (primary: CPU,
  secondary: memory), then place each into the first bin with sufficient
  remaining capacity.  Approximation ratio ≤ 11/9 · OPT + 6/9 (bin count).

* **Best-Fit Decreasing (BFD)**: Like FFD but uses the bin with the *least*
  remaining slack — produces tighter packing at the cost of one extra O(n)
  scan per item.

Both algorithms:
- Run in O(n log n + n · b) where b = number of open bins (typically ≪ n).
- Produce deterministic output (items are sorted by (cpu_desc, mem_desc, id)).
- Handle multi-dimensional capacity (CPU + memory simultaneously).
- Try each available instance type in cost-per-unit order; use the cheapest
  type that can fit all workloads in the assigned bin.

Limitations
-----------
No statistical multiplexing: assumes workload peaks are **concurrent** (the
conservative / safe assumption for production usage).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .types import CloudProvider
from .types import InstanceType
from .types import PackingBin
from .types import SizedResource

logger = logging.getLogger(__name__)


# ── Public input / result types ───────────────────────────────────────────────

@dataclass(frozen=True)
class WorkloadItem:
    """A single workload to be packed into a bin."""

    resource_id: str
    peak_cpu_cores: float   # absolute vCPU demand (p95 + headroom already applied)
    peak_mem_gb:    float   # absolute memory demand


@dataclass
class PackingResult:
    """Output from a packing run."""

    algorithm: str
    bins: list[PackingBin]
    unpacked: list[str]             # resource_ids that could not be packed
    n_bins: int
    total_cost_monthly: float
    original_cost_monthly: float    # cost if each workload had its own instance
    savings_monthly: float
    savings_pct: float
    elapsed_ms: float = 0.0


# ── FFD ───────────────────────────────────────────────────────────────────────

def first_fit_decreasing(
    workloads: list[WorkloadItem],
    bin_types: list[InstanceType],
    provider: CloudProvider,
    region: str,
    *,
    original_cost_monthly: float = 0.0,
) -> PackingResult:
    """First-Fit Decreasing bin-packing.

    Parameters
    ----------
    workloads:
        Items to pack.  Must already have headroom applied.
    bin_types:
        Available instance types (all must match provider/region).
    provider / region:
        Used to filter ``bin_types`` to compatible options.
    original_cost_monthly:
        Baseline cost for computing savings (sum of per-workload costs before
        consolidation).
    """
    import time
    t0 = time.perf_counter()

    feasible_types = _filter_and_sort_types(bin_types, provider, region)
    if not feasible_types:
        return PackingResult(
            algorithm="ffd", bins=[], unpacked=[w.resource_id for w in workloads],
            n_bins=0, total_cost_monthly=0.0,
            original_cost_monthly=original_cost_monthly, savings_monthly=0.0,
            savings_pct=0.0,
        )

    # Sort items: largest first (CPU primary, memory secondary, id for determinism)
    items = sorted(
        workloads,
        key=lambda w: (-w.peak_cpu_cores, -w.peak_mem_gb, w.resource_id),
    )

    bins: list[PackingBin] = []
    remaining_cpu: list[float] = []
    remaining_mem: list[float] = []
    unpacked: list[str] = []

    for item in items:
        placed = False

        # Try to fit into an existing bin (first-fit)
        for idx, (rcpu, rmem) in enumerate(zip(remaining_cpu, remaining_mem)):
            if rcpu >= item.peak_cpu_cores and rmem >= item.peak_mem_gb:
                bins[idx].workloads.append(item.resource_id)
                bins[idx].used_cpu += item.peak_cpu_cores
                bins[idx].used_mem += item.peak_mem_gb
                remaining_cpu[idx] -= item.peak_cpu_cores
                remaining_mem[idx] -= item.peak_mem_gb
                placed = True
                break

        if not placed:
            # Open a new bin with the cheapest type that fits this item alone
            bin_type = _pick_bin_type(item, feasible_types)
            if bin_type is None:
                unpacked.append(item.resource_id)
                continue

            bins.append(PackingBin(
                instance_type=bin_type,
                workloads=[item.resource_id],
                used_cpu=item.peak_cpu_cores,
                used_mem=item.peak_mem_gb,
            ))
            remaining_cpu.append(bin_type.vcpu - item.peak_cpu_cores)
            remaining_mem.append(bin_type.memory_gb - item.peak_mem_gb)

    return _make_result(
        "ffd", bins, unpacked, original_cost_monthly,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


# ── BFD ───────────────────────────────────────────────────────────────────────

def best_fit_decreasing(
    workloads: list[WorkloadItem],
    bin_types: list[InstanceType],
    provider: CloudProvider,
    region: str,
    *,
    original_cost_monthly: float = 0.0,
) -> PackingResult:
    """Best-Fit Decreasing bin-packing (tighter packing than FFD).

    Each item is placed into the bin with the **least** remaining CPU slack
    (among feasible bins), reducing wasted capacity.
    """
    import time
    t0 = time.perf_counter()

    feasible_types = _filter_and_sort_types(bin_types, provider, region)
    if not feasible_types:
        return PackingResult(
            algorithm="bfd", bins=[], unpacked=[w.resource_id for w in workloads],
            n_bins=0, total_cost_monthly=0.0,
            original_cost_monthly=original_cost_monthly, savings_monthly=0.0,
            savings_pct=0.0,
        )

    items = sorted(
        workloads,
        key=lambda w: (-w.peak_cpu_cores, -w.peak_mem_gb, w.resource_id),
    )

    bins: list[PackingBin] = []
    remaining_cpu: list[float] = []
    remaining_mem: list[float] = []
    unpacked: list[str] = []

    for item in items:
        # Find best-fit bin: feasible AND minimum remaining CPU slack
        best_idx = -1
        best_slack = float("inf")
        for idx, (rcpu, rmem) in enumerate(zip(remaining_cpu, remaining_mem)):
            if rcpu >= item.peak_cpu_cores and rmem >= item.peak_mem_gb:
                slack = rcpu - item.peak_cpu_cores
                if slack < best_slack:
                    best_slack = slack
                    best_idx = idx

        if best_idx >= 0:
            bins[best_idx].workloads.append(item.resource_id)
            bins[best_idx].used_cpu += item.peak_cpu_cores
            bins[best_idx].used_mem += item.peak_mem_gb
            remaining_cpu[best_idx] -= item.peak_cpu_cores
            remaining_mem[best_idx] -= item.peak_mem_gb
        else:
            bin_type = _pick_bin_type(item, feasible_types)
            if bin_type is None:
                unpacked.append(item.resource_id)
                continue
            bins.append(PackingBin(
                instance_type=bin_type,
                workloads=[item.resource_id],
                used_cpu=item.peak_cpu_cores,
                used_mem=item.peak_mem_gb,
            ))
            remaining_cpu.append(bin_type.vcpu - item.peak_cpu_cores)
            remaining_mem.append(bin_type.memory_gb - item.peak_mem_gb)

    return _make_result(
        "bfd", bins, unpacked, original_cost_monthly,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _filter_and_sort_types(
    types: list[InstanceType],
    provider: CloudProvider,
    region: str,
) -> list[InstanceType]:
    """Return types matching provider/region, sorted cheapest first."""
    filtered = [t for t in types if t.provider == provider and t.region == region]
    filtered.sort(key=lambda t: (t.cost_hourly, -t.generation, t.name))
    return filtered


def _pick_bin_type(
    item: WorkloadItem,
    sorted_types: list[InstanceType],
) -> InstanceType | None:
    """Return the cheapest type that can fit *item* alone."""
    for t in sorted_types:
        if t.vcpu >= item.peak_cpu_cores and t.memory_gb >= item.peak_mem_gb:
            return t
    return None


def _make_result(
    algorithm: str,
    bins: list[PackingBin],
    unpacked: list[str],
    original_cost_monthly: float,
    elapsed_ms: float,
) -> PackingResult:
    total_cost = sum(b.instance_type.cost_monthly for b in bins)
    savings = max(0.0, original_cost_monthly - total_cost)
    savings_pct = savings / max(original_cost_monthly, 0.01) * 100

    return PackingResult(
        algorithm=algorithm,
        bins=bins,
        unpacked=unpacked,
        n_bins=len(bins),
        total_cost_monthly=total_cost,
        original_cost_monthly=original_cost_monthly,
        savings_monthly=savings,
        savings_pct=savings_pct,
        elapsed_ms=elapsed_ms,
    )


# ── Convenience: extract workload items from SizedResource list ───────────────

def workloads_from_sized(sized: list[SizedResource]) -> list[WorkloadItem]:
    """Convert a list of :class:`SizedResource` into packing inputs."""
    return [
        WorkloadItem(
            resource_id=sr.resource.id,
            peak_cpu_cores=sr.peak_cpu_cores,
            peak_mem_gb=sr.peak_mem_gb,
        )
        for sr in sized
        if not sr.is_idle   # idle resources are terminated, not packed
    ]
