"""Event bus: every event is persisted to MongoDB AND pushed to WebSocket subscribers."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.db.repositories import store
from app.logging_config import get_logger
from app.models.enums import EventType
from app.models.schemas import Event

log = get_logger("events")


def serialize_event(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    ts = out.get("created_at")
    if isinstance(ts, datetime):
        out["created_at"] = ts.isoformat()
    return out


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id)
        if subs:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(run_id, None)

    async def emit(
        self,
        run_id: str,
        event: EventType,
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        doc = await store.add_event(
            Event(run_id=run_id, event=event, message=message, data=data or {})
        )
        payload = {"type": "event", **serialize_event(doc)}
        for queue in list(self._subscribers.get(run_id, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow client — it can catch up via GET /events
        log.info("event", run=run_id[:8], type=event.value, msg=message[:120])


event_bus = EventBus()
