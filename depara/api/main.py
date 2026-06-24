"""Aplicação FastAPI — depara agnóstico A×B."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from depara.api.routes.jobs import router as jobs_router
from depara.api.storage import mark_orphan_jobs_failed
from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    orphaned = mark_orphan_jobs_failed()
    if orphaned:
        logger.warning("Marcados %d job(s) órfão(s) como failed após startup", orphaned)
    yield


app = FastAPI(
    title="Depara API",
    description="Matching clínico e comparativo de preços entre catálogos subject × reference.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
