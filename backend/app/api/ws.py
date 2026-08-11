"""WebSocket endpoint: live event stream per run (with snapshot replay on connect)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from app.db.repositories import store
from app.logging_config import get_logger
from app.services.event_bus import event_bus, serialize_event

log = get_logger("ws")

router = APIRouter()


async def _run_snapshot(run_id: str) -> dict | None:
    run = await store.get_run(run_id)
    if run is None:
        return None
    approval = await store.pending_approval(run_id)
    return {
        "type": "snapshot",
        "run": jsonable_encoder(run.model_dump()),
        "pending_approval": jsonable_encoder(approval.model_dump()) if approval else None,
        "events": [serialize_event(e) for e in await store.recent_events(run_id, 150)],
    }


@router.websocket("/ws/runs/{run_id}")
async def run_events(websocket: WebSocket, run_id: str):
    await websocket.accept()
    snapshot = await _run_snapshot(run_id)
    if snapshot is None:
        await websocket.close(code=4404)
        return
    await websocket.send_json(snapshot)

    queue = event_bus.subscribe(run_id)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(payload)
            # piggyback a fresh run document so the UI never needs to poll
            run = await store.get_run(run_id)
            if run is not None:
                approval = await store.pending_approval(run_id)
                await websocket.send_json(
                    {
                        "type": "run_update",
                        "run": jsonable_encoder(run.model_dump()),
                        "pending_approval": (
                            jsonable_encoder(approval.model_dump()) if approval else None
                        ),
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ws_closed", run_id=run_id, error=repr(exc))
    finally:
        event_bus.unsubscribe(run_id, queue)
