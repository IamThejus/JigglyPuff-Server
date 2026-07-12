"""Real-time torrent progress over WebSocket.

Push equivalent of ``GET /torrents/list`` — same data, same
degrade-don't-fail service call, just delivered on an interval instead of
polled. Unauthenticated like the rest of the read-only routes (adding a
torrent is a control action behind /actions; watching progress is not).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.qbittorrent_service import get_torrents_list

logger = get_logger(__name__)

router = APIRouter(tags=["torrents"])


@router.websocket("/torrents/ws")
async def torrents_ws(websocket: WebSocket, state: str | None = None) -> None:
    await websocket.accept()
    interval = get_settings().torrents_ws_interval
    try:
        while True:
            torrents = await get_torrents_list(state_filter=state)
            await websocket.send_text(torrents.model_dump_json())
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("torrents_ws loop failed")
