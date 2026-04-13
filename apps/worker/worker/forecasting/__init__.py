"""Atlas forecasting sub-package.

Public surface area:

    from worker.forecasting.pipeline import ForecastPipeline, PipelineResult

    pipeline = ForecastPipeline()
    result = pipeline.run(resource_id="...", metric="cpu_utilization")
    # result.predictions: list of ForecastPoint
    # result.metrics:     ForecastMetrics (MAPE, RMSE, …)
"""
