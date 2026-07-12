"""Control actions: add torrents, trigger sync-movies.

Everything under this router is a write/control action and is gated behind
``require_api_key`` (see ``app/api/deps.py``) — unlike every other router in
this app, which is read-only and unauthenticated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import require_api_key
from app.core.config import get_settings
from app.schemas.actions import (
    AddTorrentResponse,
    AddTorrentUrlRequest,
    SyncMoviesResponse,
    TorrentActionRequest,
    TorrentActionResponse,
)
from app.services.movie_sync_service import run_sync_movies
from app.services.torrent_control_service import (
    add_torrent_by_file,
    add_torrent_by_url,
    delete_torrent,
    pause_torrent,
    resume_torrent,
)

router = APIRouter(
    prefix="/actions", tags=["actions"], dependencies=[Depends(require_api_key)]
)

_ALLOWED_URL_SCHEMES = ("magnet:", "http://", "https://")


@router.post(
    "/torrents", response_model=AddTorrentResponse, summary="Add a torrent by magnet/URL"
)
async def add_torrent_url(body: AddTorrentUrlRequest) -> AddTorrentResponse:
    url = body.url.strip()
    if not url.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise HTTPException(
            status_code=422,
            detail="url must be a magnet: link or an http(s):// URL to a .torrent file",
        )
    return await add_torrent_by_url(
        url, category=body.category, save_path=body.save_path, paused=body.paused
    )


@router.post(
    "/torrents/file",
    response_model=AddTorrentResponse,
    summary="Add a torrent by uploading a .torrent file",
)
async def add_torrent_file(
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    save_path: str | None = Form(default=None),
    paused: bool = Form(default=False),
) -> AddTorrentResponse:
    if not (file.filename or "").lower().endswith(".torrent"):
        raise HTTPException(status_code=422, detail="file must have a .torrent extension")

    settings = get_settings()
    max_bytes = settings.torrent_file_max_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds max size of {settings.torrent_file_max_mb} MB",
        )

    return await add_torrent_by_file(
        file.filename, content, category=category, save_path=save_path, paused=paused
    )


@router.post(
    "/torrents/pause",
    response_model=TorrentActionResponse,
    summary="Pause (stop) a downloading torrent",
)
async def pause_torrent_route(body: TorrentActionRequest) -> TorrentActionResponse:
    return await pause_torrent(body.hash)


@router.post(
    "/torrents/resume",
    response_model=TorrentActionResponse,
    summary="Resume (start) a paused torrent",
)
async def resume_torrent_route(body: TorrentActionRequest) -> TorrentActionResponse:
    return await resume_torrent(body.hash)


@router.post(
    "/torrents/delete",
    response_model=TorrentActionResponse,
    summary="Delete a torrent and its downloaded files",
)
async def delete_torrent_route(body: TorrentActionRequest) -> TorrentActionResponse:
    # delete_files=True: abandoning a download also removes its partial/complete
    # data from disk to reclaim space.
    return await delete_torrent(body.hash, delete_files=True)


@router.post(
    "/sync-movies", response_model=SyncMoviesResponse, summary="Run the sync-movies script"
)
async def sync_movies() -> SyncMoviesResponse:
    return await run_sync_movies()
