"""Storage / disk health integration.

Disk usage comes from ``psutil``/``shutil``. Per-folder sizes are computed by
walking the tree (bounded, best-effort). SMART data is read via ``smartctl``
when available and a device is configured.
"""

from __future__ import annotations

import json
import os
import shutil

import psutil

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.storage import (
    DiskUsage,
    FolderSize,
    SmartHealth,
    StorageSummary,
)
from app.utils import shell
from app.utils.formatting import human_bytes, percent

logger = get_logger(__name__)


def get_disk_usage(path: str | os.PathLike[str]) -> DiskUsage:
    """Return usage stats for the filesystem containing ``path``."""

    path_str = str(path)
    if not os.path.exists(path_str):
        return DiskUsage(
            path=path_str,
            exists=False,
            total_bytes=0,
            used_bytes=0,
            free_bytes=0,
            percent_used=0.0,
            total_human="0 B",
            used_human="0 B",
            free_human="0 B",
        )

    usage = shutil.disk_usage(path_str)
    return DiskUsage(
        path=path_str,
        exists=True,
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        percent_used=percent(usage.used, usage.total),
        total_human=human_bytes(usage.total),
        used_human=human_bytes(usage.used),
        free_human=human_bytes(usage.free),
    )


def get_folder_size(path: str | os.PathLike[str], max_entries: int = 200_000) -> FolderSize:
    """Compute the total size of a folder tree (best effort).

    ``max_entries`` guards against pathological trees; scanning stops once the
    limit is reached.
    """

    path_str = str(path)
    if not os.path.isdir(path_str):
        return FolderSize(
            path=path_str, exists=False, size_bytes=0, size_human="0 B", entry_count=0
        )

    total = 0
    count = 0
    for root, _dirs, files in os.walk(path_str):
        for fname in files:
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                continue
            if count >= max_entries:
                logger.warning("folder scan hit max_entries at %s", path_str)
                break
        if count >= max_entries:
            break

    return FolderSize(
        path=path_str,
        exists=True,
        size_bytes=total,
        size_human=human_bytes(total),
        entry_count=count,
    )


def get_smart_health(settings: Settings | None = None) -> SmartHealth:
    """Query SMART health via ``smartctl`` for the configured device."""

    settings = settings or get_settings()
    device = settings.smart_device.strip()

    if not device:
        return SmartHealth(available=False, message="No smart_device configured")
    if not shell.command_exists("smartctl"):
        return SmartHealth(available=False, message="smartctl not installed")

    # -j: JSON output, -H: health, -A: attributes, -i: info
    result = shell.run(["smartctl", "-j", "-H", "-A", "-i", device], timeout=15.0)
    if not result.stdout:
        return SmartHealth(
            available=False,
            device=device,
            message=result.stderr or "no output from smartctl",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return SmartHealth(
            available=False, device=device, message="could not parse smartctl output"
        )

    passed = data.get("smart_status", {}).get("passed")
    temperature = data.get("temperature", {}).get("current")
    power_on = data.get("power_on_time", {}).get("hours")

    return SmartHealth(
        available=True,
        device=device,
        healthy=passed,
        status="PASSED" if passed else "FAILED" if passed is False else "unknown",
        temperature_celsius=temperature,
        power_on_hours=power_on,
    )


def get_primary_disk_usage(settings: Settings | None = None) -> DiskUsage:
    """Usage for the first monitored path (falls back to root)."""

    settings = settings or get_settings()
    paths = settings.monitored_paths_list
    for p in paths:
        if os.path.exists(p):
            return get_disk_usage(p)
    return get_disk_usage("/")


def get_storage_summary(
    settings: Settings | None = None, include_folder_sizes: bool = True
) -> StorageSummary:
    """Aggregate disk usage, per-folder sizes and SMART health."""

    settings = settings or get_settings()

    disks = [get_disk_usage(p) for p in settings.monitored_paths_list]

    folders: list[FolderSize] = []
    if include_folder_sizes:
        for p in (
            settings.movies_path,
            settings.shows_path,
            settings.torrents_complete_path,
            settings.torrents_incomplete_path,
        ):
            folders.append(get_folder_size(p))

    return StorageSummary(
        disks=disks,
        folders=folders,
        smart=get_smart_health(settings),
    )
