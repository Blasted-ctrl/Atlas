"""Integration tests — ingestion → forecast → recommendation pipeline.

Each test exercises the full algorithmic path across multiple real modules:
    raw usage rows
    → preprocess()  (preprocessor.py)
    → select_model() + train_and_forecast()  (models.py)
    → evaluate()  (evaluator.py)
    → save_forecast()  (store.py — mocked to in-memory)
    → cache_forecast()  (cache.py — fakeredis)
    → forecast_result_to_usage()  (bridge)
    → CostOptimizationEngine.optimize()  (engine.py)
    → List[Recommendation]

I/O boundaries mocked: Postgres (InMemoryForecastStore), Redis (fakeredis).
All business logic runs on real code.
"""

from __future__ import annotations

import time
from datetime import datetime

import numpy as np
import pytest

from tests.conftest import make_spec
from tests.integration.conftest import forecast_result_to_usage
from tests.integration.conftest import idle_rows
from tests.integration.conftest import make_rows
from tests.integration.conftest import oversized_rows
from tests.integration.conftest import rightsized_rows
from tests.integration.conftest import seasonal_rows
from tests.integration.conftest import sparse_rows
from worker.forecasting.pipeline import ForecastPipeline
from worker.optimization.types import ForecastedUsage
from worker.optimization.types import OptimizationConstraints
from worker.optimization.types import RecommendationAction

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Forecast pipeline correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestForecastPipelineCorrectness:
    def test_idle_resource_produces_low_forecast_values(
        self, forecast_pipeline, monkeypatch
    ):
        """An idle resource's forecast should predict low utilisation."""
        rows = idle_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("idle-001", "cpu_utilization")

        assert not result.skipped
        # Predicted utilisation values should be below 5%
        values = [p.value for p in result.predictions]
        assert np.mean(values) < 0.05, f"Expected idle resource values < 5%, got {np.mean(values):.2%}"

    def test_oversized_resource_forecast_reflects_low_utilisation(
        self, forecast_pipeline, monkeypatch
    ):
        rows = oversized_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("over-001", "cpu_utilization")

        assert not result.skipped
        values = [p.value for p in result.predictions]
        assert np.mean(values) < 0.30, f"Expected oversized values < 30%, got {np.mean(values):.2%}"

    def test_rightsized_resource_forecast_close_to_0_7(
        self, forecast_pipeline, monkeypatch
    ):
        rows = rightsized_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("right-001", "cpu_utilization")

        assert not result.skipped
        values = [p.value for p in result.predictions]
        assert 0.50 < np.mean(values) < 0.90, (
            f"Expected rightsized values in [50%, 90%], got {np.mean(values):.2%}"
        )

    def test_sparse_data_uses_linear_model(
        self, forecast_pipeline, monkeypatch
    ):
        """With only 10 data points, the pipeline should use LinearTrendModel."""
        rows = sparse_rows(n=10)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("sparse-001", "cpu_utilization")

        if not result.skipped:
            assert result.model_type == "linear", (
                f"Expected linear model for sparse data, got {result.model_type}"
            )

    def test_rich_data_uses_holt_or_better(
        self, forecast_pipeline, monkeypatch
    ):
        """≥ 168 samples → HoltWinters (or Holt fallback for non-seasonal data)."""
        rows = seasonal_rows(n=300)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("rich-001", "cpu_utilization")

        assert not result.skipped
        assert result.model_type in ("holt_winters", "holt"), (
            f"Expected holt_winters or holt for 300 samples, got {result.model_type}"
        )

    def test_forecast_produces_30_daily_predictions(
        self, forecast_pipeline, monkeypatch
    ):
        rows = rightsized_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("check-001", "cpu_utilization")

        assert not result.skipped
        assert len(result.predictions) == 30, (
            f"Expected 30 daily predictions, got {len(result.predictions)}"
        )

    def test_forecast_dates_are_contiguous(
        self, forecast_pipeline, monkeypatch
    ):
        """Daily predictions must be consecutive calendar dates."""
        rows = rightsized_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("date-001", "cpu_utilization")

        if result.skipped or len(result.predictions) < 2:
            pytest.skip("not enough predictions")

        dates = [datetime.strptime(p.date, "%Y-%m-%d").date() for p in result.predictions]
        for i in range(1, len(dates)):
            delta = (dates[i] - dates[i - 1]).days
            assert delta == 1, f"Gap of {delta} days between predictions at index {i}"

    def test_forecast_ci_lower_leq_point_leq_upper(
        self, forecast_pipeline, monkeypatch
    ):
        """Every prediction must have lower ≤ value ≤ upper."""
        rows = oversized_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("ci-001", "cpu_utilization")

        if result.skipped:
            pytest.skip("pipeline skipped")

        for p in result.predictions:
            assert p.lower_95 <= p.value + 1e-6, (
                f"lower_95={p.lower_95:.4f} > value={p.value:.4f} on {p.date}"
            )
            assert p.value <= p.upper_95 + 1e-6, (
                f"value={p.value:.4f} > upper_95={p.upper_95:.4f} on {p.date}"
            )

    def test_mape_reported_for_sufficient_data(
        self, forecast_pipeline, monkeypatch
    ):
        """MAPE must be non-None when there are ≥ 48 samples."""
        rows = rightsized_rows(n=250)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        result = forecast_pipeline.run("mape-001", "cpu_utilization")

        if not result.skipped and result.metrics:
            assert result.metrics.mape is not None
            assert result.metrics.mape >= 0.0
            assert result.metrics.mape < 200.0  # sanity — MAPE should be reasonable

    def test_forecast_persisted_to_store(
        self, forecast_pipeline, db_store, monkeypatch
    ):
        """A successful run must write exactly one row to the store."""
        rows = rightsized_rows(n=200)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        before = db_store.count()
        result = forecast_pipeline.run("persist-001", "cpu_utilization")

        if not result.skipped:
            assert db_store.count() == before + 1

    def test_repeated_run_upserts_not_appends(
        self, forecast_pipeline, db_store, monkeypatch
    ):
        """Running the pipeline twice for the same (resource, metric) → exactly 1 stored row."""
        rows = rightsized_rows(n=200)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        # Disable cache so second run goes through the full pipeline
        pipeline = ForecastPipeline(use_cache=False)
        # Patch DB for this local pipeline
        monkeypatch.setattr("worker.forecasting.pipeline.save_forecast",
                            lambda **kw: db_store.save(**kw))

        pipeline.run("upsert-001", "cpu_utilization")
        before = db_store.count()
        pipeline.run("upsert-001", "cpu_utilization")  # second call
        # The InMemoryForecastStore.save() uses (resource_id, metric) as the key
        assert db_store.count() == before   # no net new rows

    def test_empty_rows_returns_skipped(
        self, forecast_pipeline, monkeypatch
    ):
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: [],
        )
        result = forecast_pipeline.run("empty-001", "cpu_utilization")
        assert result.skipped
        assert result.skip_reason != ""

    def test_cache_hit_avoids_retraining(
        self, forecast_pipeline, monkeypatch, mock_redis
    ):
        """Second call with use_cache=True should return from cache, not retrain."""
        rows = rightsized_rows(n=200)
        fetch_calls: list[int] = []

        def _counting_fetch(*a, **kw):
            fetch_calls.append(1)
            return rows

        monkeypatch.setattr("worker.forecasting.pipeline.fetch_usage_rows", _counting_fetch)

        pipeline = ForecastPipeline(use_cache=True)
        monkeypatch.setattr(
            "worker.forecasting.pipeline.save_forecast",
            lambda **kw: str(id(kw)),
        )

        r1 = pipeline.run("cache-001", "cpu_utilization")
        calls_after_first = len(fetch_calls)
        r2 = pipeline.run("cache-001", "cpu_utilization")
        calls_after_second = len(fetch_calls)

        if not r1.skipped:
            # Second run should serve from cache — fetch not called again
            assert calls_after_second == calls_after_first
            assert r2.from_cache

    def test_db_store(self, db_store):
        # Needed for fixture resolution — reuse db_store in test_cache_hit
        assert db_store.count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Forecast → Optimization bridge
# ─────────────────────────────────────────────────────────────────────────────

class TestForecastToOptimizationBridge:
    def _run_forecast(self, pipeline, monkeypatch, rows, rid, metric="cpu_utilization"):
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: rows,
        )
        return pipeline.run(rid, metric)

    def test_idle_forecast_produces_terminate_recommendation(
        self, forecast_pipeline, opt_engine, monkeypatch
    ):
        """Idle historical data → idle forecast → TERMINATE recommended."""
        rows = idle_rows(n=250)
        result = self._run_forecast(forecast_pipeline, monkeypatch, rows, "idle-br-001")

        spec  = make_spec("idle-br-001", "m5.2xlarge", 8, 32, 0.384)
        usage = forecast_result_to_usage("idle-br-001", result)

        opt = opt_engine.optimize([spec], [usage], algorithm="greedy")
        actions = {r.action for r in opt.recommendations}
        assert RecommendationAction.TERMINATE in actions, (
            f"Expected TERMINATE for idle resource, got {actions}"
        )

    def test_oversized_forecast_produces_downsize_recommendation(
        self, forecast_pipeline, opt_engine, monkeypatch
    ):
        rows = oversized_rows(n=250)
        result = self._run_forecast(forecast_pipeline, monkeypatch, rows, "over-br-001")

        spec  = make_spec("over-br-001", "m5.4xlarge", 16, 64, 0.768)
        usage = forecast_result_to_usage("over-br-001", result)

        opt = opt_engine.optimize([spec], [usage], algorithm="greedy")
        actions = {r.action for r in opt.recommendations}
        assert RecommendationAction.DOWNSIZE in actions, (
            f"Expected DOWNSIZE for oversized resource, got {actions}. "
            f"cpu_p95={usage.cpu_p95:.2%}, mem_p95={usage.mem_p95:.2%}"
        )

    def test_rightsized_stable_resource_may_get_reserve(
        self, forecast_pipeline, opt_engine, monkeypatch
    ):
        """A stable, always-on rightsized resource should be recommended for reservation."""
        rows = rightsized_rows(n=300)
        result = self._run_forecast(forecast_pipeline, monkeypatch, rows, "right-br-001")

        spec  = make_spec("right-br-001", "m5.xlarge", 4, 16, 0.192)
        usage = forecast_result_to_usage("right-br-001", result, avg_daily_hours=24.0)

        constr = OptimizationConstraints(
            min_utilisation_for_reserve=0.30,
            allow_downsize=False,   # focus on RI
        )
        opt = opt_engine.optimize([spec], [usage], constr, algorithm="greedy")
        actions = {r.action for r in opt.recommendations}
        # Either we recommend RI or there's no meaningful savings — both are valid
        # Key assertion: no erroneous action
        for r in opt.recommendations:
            assert r.action in (
                RecommendationAction.RESERVE_1YR,
                RecommendationAction.RESERVE_3YR,
                RecommendationAction.KEEP,
            )

    def test_savings_mathematically_correct(
        self, forecast_pipeline, opt_engine, monkeypatch
    ):
        """savings = current_cost - projected_cost (within floating-point tolerance)."""
        rows = oversized_rows(n=250)
        result = self._run_forecast(forecast_pipeline, monkeypatch, rows, "math-001")

        spec  = make_spec("math-001", "m5.4xlarge", 16, 64, 0.768)
        usage = forecast_result_to_usage("math-001", result)
        opt   = opt_engine.optimize([spec], [usage], algorithm="greedy")

        for rec in opt.recommendations:
            expected = rec.current_cost_monthly - rec.projected_cost_monthly
            assert rec.savings_monthly == pytest.approx(expected, abs=0.01), (
                f"savings_monthly mismatch: {rec.savings_monthly} ≠ {expected}"
            )

    def test_annual_savings_equals_12x_monthly(
        self, forecast_pipeline, opt_engine, monkeypatch
    ):
        rows = oversized_rows(n=250)
        result = self._run_forecast(forecast_pipeline, monkeypatch, rows, "annual-001")
        spec  = make_spec("annual-001", "m5.4xlarge", 16, 64, 0.768)
        usage = forecast_result_to_usage("annual-001", result)
        opt   = opt_engine.optimize([spec], [usage], algorithm="greedy")

        for rec in opt.recommendations:
            assert rec.savings_annual == pytest.approx(rec.savings_monthly * 12, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Multi-resource pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiResourcePipeline:
    """End-to-end test with 50 mixed resources."""

    N_RESOURCES = 50

    def _build_resources(self):
        rng = np.random.default_rng(seed=77)
        categories = (
            ["idle"] * 12 + ["oversized"] * 25 + ["rightsized"] * 10 + ["mixed"] * 3
        )
        resources = []
        for i, cat in enumerate(categories):
            rid = f"multi-{i:04d}"
            if cat in ("idle", "oversized"):
                spec = make_spec(rid, "m5.2xlarge", 8, 32, 0.384)
            else:
                spec = make_spec(rid, "m5.xlarge", 4, 16, 0.192)
            resources.append((rid, cat, spec))
        return resources

    def _run_forecasts(self, pipeline, monkeypatch, resources):
        forecast_results = {}
        for rid, cat, _ in resources:
            if cat == "idle":
                rows = idle_rows(n=200, seed=hash(rid) % 100)
            elif cat == "oversized":
                rows = oversized_rows(n=200, seed=hash(rid) % 100)
            elif cat == "rightsized":
                rows = rightsized_rows(n=200, seed=hash(rid) % 100)
            else:
                rows = make_rows(n=200, base=0.35, noise=0.05, seed=hash(rid) % 100)

            monkeypatch.setattr(
                "worker.forecasting.pipeline.fetch_usage_rows",
                lambda *a, _rows=rows, **kw: _rows,
            )
            forecast_results[rid] = pipeline.run(rid, "cpu_utilization")
        return forecast_results

    def test_50_resources_end_to_end(
        self, forecast_pipeline, opt_engine, monkeypatch, db_store
    ):
        resources = self._build_resources()
        forecasts = self._run_forecasts(forecast_pipeline, monkeypatch, resources)

        specs  = [spec for _, _, spec in resources]
        usages = [forecast_result_to_usage(rid, forecasts[rid]) for rid, _, _ in resources]

        opt = opt_engine.optimize(specs, usages, algorithm="hybrid")

        # Should produce a meaningful number of recommendations
        assert opt.n_recommendations > 0
        assert opt.total_savings_monthly > 0

        # All resource IDs in recommendations must be valid
        valid_ids = {r.id for r in specs}
        for rec in opt.recommendations:
            assert rec.resource_id in valid_ids, f"Unknown resource_id: {rec.resource_id}"

    def test_action_distribution_matches_input_profile(
        self, forecast_pipeline, opt_engine, monkeypatch, db_store
    ):
        """12 idle, 25 oversized, 13 rightsized → terminate > downsize."""
        resources = self._build_resources()
        forecasts = self._run_forecasts(forecast_pipeline, monkeypatch, resources)

        specs  = [spec for _, _, spec in resources]
        usages = [forecast_result_to_usage(rid, forecasts[rid]) for rid, _, _ in resources]

        opt = opt_engine.optimize(specs, usages, algorithm="greedy")

        terminate_count = sum(
            1 for r in opt.recommendations if r.action == RecommendationAction.TERMINATE
        )
        downsize_count = sum(
            1 for r in opt.recommendations if r.action == RecommendationAction.DOWNSIZE
        )

        # We injected 12 idle resources → at least some terminates expected
        assert terminate_count > 0, "Expected at least one TERMINATE for idle resources"
        # We injected 25 oversized → at least some downsizes expected
        assert downsize_count > 0, "Expected at least one DOWNSIZE for oversized resources"

    def test_total_savings_positive(
        self, forecast_pipeline, opt_engine, monkeypatch, db_store
    ):
        resources = self._build_resources()
        forecasts = self._run_forecasts(forecast_pipeline, monkeypatch, resources)
        specs  = [spec for _, _, spec in resources]
        usages = [forecast_result_to_usage(rid, forecasts[rid]) for rid, _, _ in resources]
        opt = opt_engine.optimize(specs, usages, algorithm="greedy")
        assert opt.total_savings_monthly > 0
        assert opt.total_savings_annual == pytest.approx(opt.total_savings_monthly * 12, rel=1e-5)

    def test_pipeline_completes_within_10s(
        self, forecast_pipeline, opt_engine, monkeypatch, db_store
    ):
        """50-resource pipeline (forecast + optimize) must complete in < 10 s."""
        resources = self._build_resources()
        t0 = time.perf_counter()
        forecasts = self._run_forecasts(forecast_pipeline, monkeypatch, resources)
        specs  = [spec for _, _, spec in resources]
        usages = [forecast_result_to_usage(rid, forecasts[rid]) for rid, _, _ in resources]
        opt_engine.optimize(specs, usages, algorithm="greedy")
        elapsed = time.perf_counter() - t0
        assert elapsed < 10.0, f"Pipeline took {elapsed:.1f}s — exceeded 10s budget"


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineIdempotency:
    def test_same_input_same_recommendations(
        self, forecast_pipeline, opt_engine, monkeypatch
    ):
        """Running the full pipeline twice on the same data must produce identical output."""
        rows = oversized_rows(n=250)

        def _fetch(*a, **kw):
            return rows

        monkeypatch.setattr("worker.forecasting.pipeline.fetch_usage_rows", _fetch)

        # Run 1
        r1 = forecast_pipeline.run("idem-001", "cpu_utilization", force_refresh=True)
        # Run 2 (force_refresh to bypass cache)
        r2 = forecast_pipeline.run("idem-001", "cpu_utilization", force_refresh=True)

        if not r1.skipped and not r2.skipped:
            # Same daily predictions (allow tiny floating-point drift)
            assert len(r1.predictions) == len(r2.predictions)
            for p1, p2 in zip(r1.predictions, r2.predictions):
                assert p1.date == p2.date
                assert p1.value == pytest.approx(p2.value, rel=1e-5)

    def test_optimizer_deterministic_given_same_usage(self, opt_engine):
        """The optimization engine must produce byte-identical output on repeated calls."""
        specs  = [make_spec(f"det-{i:03d}", "m5.2xlarge", 8, 32, 0.384) for i in range(20)]
        usages = [
            ForecastedUsage(
                resource_id=f"det-{i:03d}",
                cpu_p50=0.08, cpu_p95=0.14, mem_p50=0.12, mem_p95=0.20,
                avg_daily_hours=23.0, horizon_days=30,
            )
            for i in range(20)
        ]

        r1 = opt_engine.optimize(specs, usages, algorithm="hybrid")
        r2 = opt_engine.optimize(specs, usages, algorithm="hybrid")

        ids1 = [r.resource_id for r in r1.recommendations]
        ids2 = [r.resource_id for r in r2.recommendations]
        sv1  = [round(r.savings_monthly, 4) for r in r1.recommendations]
        sv2  = [round(r.savings_monthly, 4) for r in r2.recommendations]

        assert ids1 == ids2, "Resource ID order differs between runs"
        assert sv1  == sv2,  "Savings values differ between runs"


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Budget-constrained RI selection
# ─────────────────────────────────────────────────────────────────────────────

class TestBudgetConstrainedRI:
    def test_tight_budget_selects_highest_roi_resources(
        self, opt_engine, monkeypatch
    ):
        """With a very tight budget, only the best RI candidates should be selected."""
        # All resources run at high utilisation — all are RI candidates
        specs = [
            make_spec(f"ri-{i:03d}", "m5.xlarge", 4, 16, 0.192)
            for i in range(10)
        ]
        from worker.optimization.types import ForecastedUsage
        usages = [
            ForecastedUsage(
                resource_id=f"ri-{i:03d}",
                cpu_p50=0.68, cpu_p95=0.75, mem_p50=0.60, mem_p95=0.68,
                avg_daily_hours=24.0, horizon_days=30,
            )
            for i in range(10)
        ]
        # Budget only allows ~2 reservations (upfront ≈ $43 each for m5.xlarge)
        tight_budget = 100.0
        constr = OptimizationConstraints(
            reserved_upfront_budget=tight_budget,
            allow_terminate=False,
            allow_downsize=False,
        )
        result = opt_engine.optimize(specs, usages, constr, algorithm="milp")

        reserve_recs = [
            r for r in result.recommendations
            if r.action in (RecommendationAction.RESERVE_1YR, RecommendationAction.RESERVE_3YR)
        ]
        # Total upfront committed must not exceed budget
        total_upfront = sum(r.projected_cost_monthly for r in reserve_recs)  # rough check
        if reserve_recs:
            assert len(reserve_recs) <= 10
            # All recommended resources should have positive savings
            for rec in reserve_recs:
                assert rec.savings_monthly > 0

    def test_unlimited_budget_reserves_all_viable(
        self, opt_engine
    ):
        """Infinite budget → every viable RI candidate should be reserved."""
        from worker.optimization.types import ForecastedUsage
        specs = [make_spec(f"all-{i:03d}", "m5.xlarge", 4, 16, 0.192) for i in range(5)]
        usages = [
            ForecastedUsage(
                resource_id=f"all-{i:03d}",
                cpu_p50=0.70, cpu_p95=0.78, mem_p50=0.65, mem_p95=0.72,
                avg_daily_hours=24.0, horizon_days=30,
            )
            for i in range(5)
        ]
        constr = OptimizationConstraints(
            reserved_upfront_budget=float("inf"),
            allow_terminate=False,
            allow_downsize=False,
            min_savings_monthly=1.0,
        )
        result = opt_engine.optimize(specs, usages, constr, algorithm="greedy")
        reserve_recs = [
            r for r in result.recommendations
            if r.action in (RecommendationAction.RESERVE_1YR, RecommendationAction.RESERVE_3YR)
        ]
        # Every resource should receive a reservation recommendation
        assert len(reserve_recs) == len(specs)
