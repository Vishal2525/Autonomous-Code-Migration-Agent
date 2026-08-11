"""FastAPI application entry point.
Run from the backend/ directory:
python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

# Windows: required for asyncio subprocess support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import runs as runs_api
from app.api import ws as ws_api
from app.config import settings
from app.db import mongo
from app.db.repositories import store
from app.logging_config import configure_logging, get_logger
from app.services.worker import recover_orphaned_runs


configure_logging()
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await mongo.connect()
    store.bind(db)

    await recover_orphaned_runs()

    settings.workspace_root.mkdir(parents=True, exist_ok=True)

    log.info(
        "backend_ready",
        llm_provider=settings.llm_provider,
        workspace=str(settings.workspace_root),
    )

    yield

    await mongo.close()


app = FastAPI(
    title="Autonomous Code Migration Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_api.router)
app.include_router(ws_api.router)


@app.get("/")
async def root():
    return {
        "message": "Autonomous Code Migration Agent API",
        "status": "running",
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "database": settings.mongodb_db,
    }