"""System health integration built on ``psutil`` + stdlib.

Everything here is read-only. When an optional metric is unavailable on the
host (temperatures, battery ...) it is simply omitted rather than failing.
"""

from __future__ import annotations

import os
import platform
import socket
import time
from datetime import datetime, timezone

import psutil

from app.core.logging import get_logger
from app.schemas.system import (
    BatteryInfo,
    LoadAverage,
    MemoryInfo,
    NetworkInterface,
    SwapInfo,
    SystemOverview,
    TemperatureReading,
)
from app.utils.formatting import human_bytes, human_duration

logger = get_logger(__name__)


def _load_average() -> LoadAverage | None:
    try:
        one, five, fifteen = os.getloadavg()
    except (OSError, AttributeError):  # not available on some platforms
        return None
    return LoadAverage(one=round(one, 2), five=round(five, 2), fifteen=round(fifteen, 2))


def _temperatures() -> list[TemperatureReading]:
    readings: list[TemperatureReading] = []
    sensors = getattr(psutil, "sensors_temperatures", None)
    if sensors is None:
        return readings
    try:
        data = sensors()
    except Exception:  # pragma: no cover - platform dependent
        return readings
    for chip, entries in data.items():
        for entry in entries:
            label = entry.label or chip
            readings.append(
                TemperatureReading(
                    label=label,
                    current_celsius=round(entry.current, 1),
                    high_celsius=entry.high,
                    critical_celsius=entry.critical,
                )
            )
    return readings


def _battery() -> BatteryInfo | None:
    fn = getattr(psutil, "sensors_battery", None)
    if fn is None:
        return None
    try:
        batt = fn()
    except Exception:  # pragma: no cover - platform dependent
        return None
    if batt is None:
        return None
    secs = batt.secsleft
    if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED):
        secs = None
    return BatteryInfo(
        percent=round(batt.percent, 1),
        power_plugged=batt.power_plugged,
        secs_left=secs,
    )


def _interfaces() -> list[NetworkInterface]:
    interfaces: list[NetworkInterface] = []
    try:
        addrs = psutil.net_if_addrs()
    except Exception:  # pragma: no cover
        return interfaces
    for name, snics in addrs.items():
        if name == "lo":
            continue
        ips = [
            s.address
            for s in snics
            if s.family in (socket.AF_INET, socket.AF_INET6)
            and not s.address.startswith("fe80")  # skip link-local
        ]
        if ips:
            interfaces.append(NetworkInterface(name=name, addresses=ips))
    return interfaces


def get_uptime_seconds() -> int:
    return int(time.time() - psutil.boot_time())


def get_cpu_percent() -> float:
    # Non-blocking: returns usage since the previous call.
    return round(psutil.cpu_percent(interval=None), 1)


def get_memory_percent() -> float:
    return round(psutil.virtual_memory().percent, 1)


def get_system_overview() -> SystemOverview:
    """Build the full system overview payload."""

    uname = platform.uname()
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)

    return SystemOverview(
        hostname=socket.gethostname(),
        os=f"{uname.system} {uname.release}",
        kernel=uname.version,
        architecture=uname.machine,
        uptime_seconds=get_uptime_seconds(),
        uptime_human=human_duration(get_uptime_seconds()),
        boot_time_iso=boot_time.isoformat(),
        cpu_percent=get_cpu_percent(),
        cpu_count_logical=psutil.cpu_count(logical=True) or 0,
        cpu_count_physical=psutil.cpu_count(logical=False),
        load_average=_load_average(),
        memory=MemoryInfo(
            total_bytes=vm.total,
            used_bytes=vm.used,
            available_bytes=vm.available,
            percent=round(vm.percent, 1),
            total_human=human_bytes(vm.total),
            used_human=human_bytes(vm.used),
        ),
        swap=SwapInfo(
            total_bytes=swap.total,
            used_bytes=swap.used,
            percent=round(swap.percent, 1),
            total_human=human_bytes(swap.total),
        ),
        temperatures=_temperatures(),
        battery=_battery(),
        interfaces=_interfaces(),
    )
