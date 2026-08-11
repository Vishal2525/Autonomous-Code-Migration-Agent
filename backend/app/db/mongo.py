"""Motor (async MongoDB) client lifecycle + collection handles + indexes."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings
from app.logging_config import get_logger

log = get_logger("db.mongo")

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect(db_name: str | None = None) -> AsyncIOMotorDatabase:
    """Connect (idempotent) and create indexes. Returns the database handle."""
    global _client, _db
    if _db is not None:
        return _db
    _client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    _db = _client[db_name or settings.mongodb_db]
    # fail fast if the server is unreachable
    await _client.admin.command("ping")
    await ensure_indexes(_db)
    log.info("mongo_connected", uri=settings.mongodb_uri, db=_db.name)
    return _db


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB is not connected — call connect() first")
    return _db


async def close() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.runs.create_index("run_id", unique=True)
    await db.repository_indexes.create_index("run_id", unique=True)
    await db.files.create_index([("run_id", 1), ("path", 1)], unique=True)
    await db.dependencies.create_index([("run_id", 1), ("source_file", 1)], unique=True)
    await db.plans.create_index("run_id", unique=True)
    await db.tasks.create_index([("run_id", 1), ("task_id", 1)], unique=True)
    await db.checkpoints.create_index([("run_id", 1), ("created_at", -1)])
    await db.checkpoints.create_index([("run_id", 1), ("phase", 1), ("task_id", 1)])
    await db.events.create_index([("run_id", 1), ("_id", 1)])
    await db.test_results.create_index([("run_id", 1), ("created_at", -1)])
    await db.approvals.create_index([("run_id", 1), ("key", 1)], unique=True)
