"""Aggregates the other services into a single dashboard payload.

This is what the mobile app home screen calls. It fans out to the system,
storage, torrent, library and service modules and composes one response. The
torrent call is async; the rest are quick synchronous ``psutil``/filesystem
reads, so they run inline.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.dashboard import Dashboard, DashboardStorage
from app.services import (
    library_service,
    service_status_service,
    storage_service,
    system_service,
)
from app.services.qbittorrent_service import get_torrents_summary
from app.utils.formatting import human_duration

logger = get_logger(__name__)


async def get_dashboard(settings: Settings | None = None) -> Dashboard:
    settings = settings or get_settings()

    primary_disk = storage_service.get_primary_disk_usage(settings)
    torrents = await get_torrents_summary(settings)
    services = service_status_service.get_services_status(settings)
    library = library_service.get_library_summary(settings, recent_limit=0)
    uptime = system_service.get_uptime_seconds()

    hostname = socket.gethostname()

    return Dashboard(
        hostname=hostname,
        server_name=settings.app_name,
        uptime_seconds=uptime,
        uptime_human=human_duration(uptime),
        cpu_percent=system_service.get_cpu_percent(),
        memory_percent=system_service.get_memory_percent(),
        disk_percent_used=primary_disk.percent_used,
        storage=DashboardStorage(
            primary_path=primary_disk.path,
            total_human=primary_disk.total_human,
            used_human=primary_disk.used_human,
            free_human=primary_disk.free_human,
            percent_used=primary_disk.percent_used,
        ),
        torrents_active=torrents.downloading + torrents.seeding,
        torrents_downloading=torrents.downloading,
        torrents_seeding=torrents.seeding,
        torrents_reachable=torrents.reachable,
        movies_count=library.movies_count,
        shows_count=library.shows_count,
        services=services.services,
        generated_at_iso=datetime.now(tz=timezone.utc).isoformat(),
    )
