from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from metricflow_server.api.admin import router as admin_router
from metricflow_server.api.routes import router as api_router
from metricflow_server.config import settings
from metricflow_server.engine_manager import engine_manager

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    profiles_dir = settings.resolve_profiles_dir()
    source = "MF_PROFILES_B64" if settings.profiles_b64 else "MF_DBT_PROFILES_DIR"
    logger.info("Initialising dbt adapter (profiles_dir=%s, source=%s) …", profiles_dir, source)
    try:
        engine_manager.init_adapter(profiles_dir)
        logger.info("Adapter ready – waiting for manifest via POST /admin/refresh")
        yield
    finally:
        settings.cleanup_profiles_dir()


app = FastAPI(title="MetricFlow Server", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(admin_router)


def cli() -> None:
    uvicorn.run(
        "metricflow_server.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    cli()
