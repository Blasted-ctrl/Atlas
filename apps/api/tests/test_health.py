from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.routes.health import ComponentStatus


def _load_main(monkeypatch: MonkeyPatch) -> object:
    monkeypatch.setenv("API_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import main

    return importlib.reload(main)


def test_health_reports_ok(monkeypatch: MonkeyPatch) -> None:
    main = _load_main(monkeypatch)
    monkeypatch.setattr(
        "app.routes.health._run_checks",
        AsyncMock(
            return_value=ComponentStatus(
                database="ok",
                redis="ok",
                storage="ok",
            )
        ),
    )

    client = TestClient(main.create_app())
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}


def test_metrics_endpoint_exists(monkeypatch: MonkeyPatch) -> None:
    main = _load_main(monkeypatch)
    client = TestClient(main.create_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "atlas_api_request_duration_seconds" in response.text
