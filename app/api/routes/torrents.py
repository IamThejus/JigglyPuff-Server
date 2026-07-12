"""qBittorrent status routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.torrents import TorrentsList, TorrentsSummary
from app.services.qbittorrent_service import get_torrents_list, get_torrents_summary

router = APIRouter(prefix="/torrents", tags=["torrents"])


@router.get("/summary", response_model=TorrentsSummary, summary="Torrent counts & speeds")
async def torrents_summary() -> TorrentsSummary:
    return await get_torrents_summary()


@router.get("/list", response_model=TorrentsList, summary="Torrent queue")
async def torrents_list(
    state: str | None = Query(
        default=None,
        description="Optional filter: downloading | seeding | completed",
    ),
) -> TorrentsList:
    return await get_torrents_list(state_filter=state)
