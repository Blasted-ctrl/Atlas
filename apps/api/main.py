"""Atlas API entry point.

Run locally:
    uvicorn main:app --reload --port 8000

Or via the project Makefile / docker-compose.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.logging import get_logger
from app.core.telemetry import setup_telemetry
from app.routes.health import router as health_router

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "atlas_api_starting",
        version=settings.app_version,
        debug=settings.debug,
    )
    yield
    logger.info("atlas_api_shutdown")


# ─── Application factory ─────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Atlas Cloud Cost Optimization Platform API. "
            "Provides cost visibility, resource inventory, and savings recommendations "
            "across AWS, GCP, and Azure."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    setup_telemetry(app, settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global error handler ─────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            method=request.method,
            url=str(request.url),
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred."},
        )

    # ── Routers ──────────────────────────────────────────────────────────────
    app.include_router(health_router)

    # Future routers:
    # app.include_router(accounts_router, prefix="/v1/accounts")
    # app.include_router(costs_router, prefix="/v1/costs")
    # app.include_router(resources_router, prefix="/v1/resources")
    # app.include_router(recommendations_router, prefix="/v1/recommendations")

    logger.info("routes_registered", routes=[r.path for r in app.routes])
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=settings.api_reload,
        log_config=None,  # we configure structlog ourselves
    )
