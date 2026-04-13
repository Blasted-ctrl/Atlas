from __future__ import annotations

import importlib

from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def test_unhandled_exceptions_return_json(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("API_SECRET_KEY", "y" * 32)
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    import main

    main = importlib.reload(main)
    app = main.create_app()

    @app.get("/boom", response_model=None)
    async def boom() -> None:
        raise RuntimeError("unexpected")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
