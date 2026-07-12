"""Torrent control actions (add by URL/magnet or by uploaded .torrent file).

Read-only torrent status lives in ``qbittorrent_service.py`` — this module
only orchestrates writes, on top of the same shared
``QBittorrentClient.add_torrent`` method. Degrades like every other service
module in this repo: qBittorrent being unreachable or rejecting the torrent
comes back as ``AddTorrentResponse(ok=False, message=...)``, never a 500.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.actions import AddTorrentResponse, TorrentActionResponse
from app.services.qbittorrent_service import QBittorrentError, get_client

logger = get_logger(__name__)


async def add_torrent_by_url(
    url: str,
    category: str | None = None,
    save_path: str | None = None,
    paused: bool = False,
    settings: Settings | None = None,
) -> AddTorrentResponse:
    client = get_client(settings or get_settings())
    try:
        await client.add_torrent(
            url=url, category=category, save_path=save_path, paused=paused
        )
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("add_torrent (url) failed: %s", exc)
        return AddTorrentResponse(ok=False, message=str(exc))
    return AddTorrentResponse(ok=True)


async def add_torrent_by_file(
    filename: str,
    file_bytes: bytes,
    category: str | None = None,
    save_path: str | None = None,
    paused: bool = False,
    settings: Settings | None = None,
) -> AddTorrentResponse:
    client = get_client(settings or get_settings())
    try:
        await client.add_torrent(
            filename=filename,
            file_bytes=file_bytes,
            category=category,
            save_path=save_path,
            paused=paused,
        )
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("add_torrent (file) failed: %s", exc)
        return AddTorrentResponse(ok=False, message=str(exc))
    return AddTorrentResponse(ok=True)


async def pause_torrent(
    torrent_hash: str, settings: Settings | None = None
) -> TorrentActionResponse:
    client = get_client(settings or get_settings())
    try:
        await client.stop_torrents([torrent_hash])
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("pause_torrent failed: %s", exc)
        return TorrentActionResponse(ok=False, message=str(exc))
    return TorrentActionResponse(ok=True)


async def resume_torrent(
    torrent_hash: str, settings: Settings | None = None
) -> TorrentActionResponse:
    client = get_client(settings or get_settings())
    try:
        await client.start_torrents([torrent_hash])
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("resume_torrent failed: %s", exc)
        return TorrentActionResponse(ok=False, message=str(exc))
    return TorrentActionResponse(ok=True)


async def delete_torrent(
    torrent_hash: str, delete_files: bool = True, settings: Settings | None = None
) -> TorrentActionResponse:
    """Remove a torrent. ``delete_files=True`` also deletes its data on disk
    (partial or complete) — used to abandon an unwanted download."""

    client = get_client(settings or get_settings())
    try:
        await client.delete_torrents([torrent_hash], delete_files=delete_files)
    except (QBittorrentError, httpx.HTTPError) as exc:
        logger.warning("delete_torrent failed: %s", exc)
        return TorrentActionResponse(ok=False, message=str(exc))
    return TorrentActionResponse(ok=True)
